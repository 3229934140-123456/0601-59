import os
import re
from pathlib import Path
from typing import List, Optional, Tuple

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from brand_kit.cli import pass_brand
from brand_kit.utils import (
    sanitize_filename,
    get_files_by_extension,
    safe_move,
    format_size,
    IMAGE_EXTENSIONS,
    FONT_EXTENSIONS,
    ICON_EXTENSIONS,
)

console = Console()


RENAME_PATTERNS = {
    "snake": "{theme}_{name}_{index:03d}",
    "kebab": "{theme}-{name}-{index:03d}",
    "camel": "{theme}{Name}{index:03d}",
    "pascal": "{Theme}{Name}{index:03d}",
}


@click.command("rename")
@click.argument("target_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True), required=False)
@click.option("--pattern", "-p", default="snake",
              type=click.Choice(["snake", "kebab", "camel", "pascal", "custom"]),
              help="命名模式")
@click.option("--custom-pattern", default="", help="自定义命名模板")
@click.option("--theme", default="default", help="主题名称")
@click.option("--name", "base_name", default="asset", help="基础名称")
@click.option("--start-index", type=int, default=1, help="起始序号")
@click.option("--type", "file_type",
              type=click.Choice(["image", "font", "icon", "all"], case_sensitive=False),
              default="all", help="文件类型筛选")
@click.option("--prefix", default="", help="名称前缀")
@click.option("--suffix", default="", help="名称后缀")
@click.option("--lower/--no-lower", default=True, help="转小写")
@click.option("--replace-space", default="_", help="空格替换字符")
@click.option("--recursive/--no-recursive", default=False, help="递归处理子目录")
@click.option("--preview", is_flag=True, help="预览模式，不实际重命名")
@click.option("--overwrite", is_flag=True, help="覆盖已存在的文件")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def rename_cmd(brand, target_dir, pattern, custom_pattern, theme, base_name,
               start_index, file_type, prefix, suffix, lower, replace_space,
               recursive, preview, overwrite, report):
    """按规则批量重命名文件"""
    project_root = brand["project_root"]
    config = brand["config"]
    logger = brand["logger"]

    if target_dir is None:
        target_dir = project_root / "assets" / "images"

    target_path = Path(target_dir).resolve()

    if not target_path.exists():
        click.echo(click.style(f"✗ 目录不存在: {target_path}", fg="red"))
        return

    extensions = _get_extensions(file_type, config)
    files = get_files_by_extension(target_path, extensions, recursive)

    if not files:
        click.echo(click.style("✗ 未找到符合条件的文件", fg="yellow"))
        return

    naming_pattern = custom_pattern if pattern == "custom" and custom_pattern else RENAME_PATTERNS.get(pattern, RENAME_PATTERNS["snake"])

    if preview:
        _show_preview(files, naming_pattern, theme, base_name, start_index,
                      prefix, suffix, lower, replace_space)
        return

    logger.start_session("rename")

    results = {
        "items": [],
        "summary": {
            "总计": len(files),
            "成功": 0,
            "跳过": 0,
            "失败": 0,
        },
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"重命名 {len(files)} 个文件...", total=len(files))

        for idx, file_path in enumerate(files, start=start_index):
            try:
                new_name = _generate_name(
                    file_path, naming_pattern, theme, base_name, idx,
                    prefix, suffix, lower, replace_space
                )
                new_path = file_path.parent / new_name

                if new_path == file_path:
                    results["items"].append({
                        "name": file_path.name,
                        "type": file_path.suffix.lstrip("."),
                        "size": format_size(file_path.stat().st_size),
                        "status": "skipped",
                        "notes": "名称未变化",
                    })
                    results["summary"]["跳过"] += 1
                    progress.advance(task)
                    continue

                if new_path.exists() and not overwrite:
                    results["items"].append({
                        "name": file_path.name,
                        "type": file_path.suffix.lstrip("."),
                        "size": format_size(file_path.stat().st_size),
                        "status": "skipped",
                        "notes": f"目标已存在: {new_name}",
                    })
                    results["summary"]["跳过"] += 1
                    logger.log_action(
                        "rename", str(file_path), str(new_path),
                        status="skipped", details="目标文件已存在"
                    )
                    progress.advance(task)
                    continue

                success, msg = safe_move(file_path, new_path, overwrite)

                if success:
                    results["items"].append({
                        "name": f"{file_path.name} → {new_name}",
                        "type": file_path.suffix.lstrip("."),
                        "size": format_size(new_path.stat().st_size),
                        "status": "success",
                        "notes": msg,
                    })
                    results["summary"]["成功"] += 1
                    logger.log_action(
                        "rename", str(file_path), str(new_path),
                        status="success", details=msg
                    )
                else:
                    results["items"].append({
                        "name": file_path.name,
                        "type": file_path.suffix.lstrip("."),
                        "size": format_size(file_path.stat().st_size),
                        "status": "error",
                        "notes": msg,
                    })
                    results["summary"]["失败"] += 1
                    logger.log_action(
                        "rename", str(file_path),
                        status="failed", details=msg
                    )

            except Exception as e:
                results["items"].append({
                    "name": file_path.name,
                    "type": file_path.suffix.lstrip("."),
                    "size": format_size(file_path.stat().st_size) if file_path.exists() else "N/A",
                    "status": "error",
                    "notes": str(e),
                })
                results["summary"]["失败"] += 1
                logger.log_action(
                    "rename", str(file_path),
                    status="failed", details=str(e)
                )

            progress.advance(task)

    logger.end_session()
    _show_results(results)

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("rename", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


def _get_extensions(file_type: str, config) -> set:
    if file_type == "image":
        return set(config.image_formats)
    elif file_type == "font":
        return set(config.font_formats)
    elif file_type == "icon":
        return set(config.icon_formats)
    else:
        return set(config.image_formats) | set(config.font_formats) | set(config.icon_formats)


def _generate_name(file_path: Path, pattern: str, theme: str, base_name: str,
                   index: int, prefix: str, suffix: str, lower: bool,
                   replace_space: str) -> str:
    stem = file_path.stem
    ext = file_path.suffix

    name = base_name if base_name else stem
    name = name.replace(" ", replace_space)
    name = sanitize_filename(name)

    try:
        new_stem = pattern.format(
            theme=theme,
            Theme=theme.capitalize(),
            name=name,
            Name=name.capitalize(),
            NAME=name.upper(),
            index=index,
            prefix=prefix,
            suffix=suffix,
        )
    except KeyError as e:
        new_stem = f"{theme}_{name}_{index:03d}"

    if prefix:
        new_stem = f"{prefix}{new_stem}"
    if suffix:
        new_stem = f"{new_stem}{suffix}"

    if lower:
        new_stem = new_stem.lower()

    return f"{new_stem}{ext}"


def _show_preview(files: List[Path], pattern: str, theme: str, base_name: str,
                  start_index: int, prefix: str, suffix: str, lower: bool,
                  replace_space: str):
    table = Table(title=f"重命名预览 - 共 {len(files)} 个文件")
    table.add_column("#", style="yellow", width=4)
    table.add_column("原文件名", style="cyan", overflow="fold")
    table.add_column("新文件名", style="green", overflow="fold")

    for idx, f in enumerate(files[:20], start=start_index):
        new_name = _generate_name(
            f, pattern, theme, base_name, idx,
            prefix, suffix, lower, replace_space
        )
        table.add_row(str(idx), f.name, new_name)

    if len(files) > 20:
        table.add_row("...", f"... 还有 {len(files) - 20} 个文件", "")

    console.print(table)
    click.echo(click.style("\n预览模式 - 不会实际重命名文件", fg="yellow"))


def _show_results(results: dict):
    click.echo()
    table = Table(title="重命名结果")
    table.add_column("统计项", style="cyan")
    table.add_column("数量", style="green", justify="right")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)

    success_count = results["summary"].get("成功", 0)
    if success_count > 0:
        click.echo(click.style(f"\n✓ 成功重命名 {success_count} 个文件", fg="green"))
    else:
        click.echo(click.style("\n✗ 没有文件被重命名", fg="yellow"))
