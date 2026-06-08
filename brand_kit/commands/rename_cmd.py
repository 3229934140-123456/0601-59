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
    confirm_overwrite,
    check_overwrites,
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

    rename_pairs = []
    for idx, file_path in enumerate(files, start=start_index):
        new_name = _generate_name(
            file_path, naming_pattern, theme, base_name, idx,
            prefix, suffix, lower, replace_space
        )
        new_path = file_path.parent / new_name
        rename_pairs.append((file_path, new_path))

    if preview:
        _show_preview(rename_pairs, overwrite)
        return

    overwrite_pairs = [(s, t) for s, t in rename_pairs if t.exists() and s != t]
    if overwrite_pairs:
        confirmed_pairs = confirm_overwrite(overwrite_pairs, auto_confirm=overwrite)
        confirmed_targets = {str(t) for _, t in confirmed_pairs}
    else:
        confirmed_targets = set()

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

    renamed_files = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"重命名 {len(files)} 个文件...", total=len(files))

        for file_path, new_path in rename_pairs:
            try:
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

                if new_path.exists():
                    if not overwrite and str(new_path) not in confirmed_targets:
                        results["items"].append({
                            "name": file_path.name,
                            "type": file_path.suffix.lstrip("."),
                            "size": format_size(file_path.stat().st_size),
                            "status": "skipped",
                            "notes": f"目标已存在: {new_path.name}",
                        })
                        results["summary"]["跳过"] += 1
                        logger.log_action(
                            "rename", str(file_path), str(new_path),
                            status="skipped", details="目标文件已存在，未确认覆盖"
                        )
                        progress.advance(task)
                        continue

                success, msg = safe_move(file_path, new_path, overwrite)

                if success:
                    renamed_files.append((str(file_path), str(new_path)))
                    results["items"].append({
                        "name": f"{file_path.name} → {new_path.name}",
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
    _save_rename_history(project_root, renamed_files)

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


def _show_preview(rename_pairs: list, overwrite: bool):
    overwrite_pairs = [(s, t) for s, t in rename_pairs if t.exists() and s != t]
    overwrite_count = len(overwrite_pairs)

    table = Table(title=f"重命名预览 - 共 {len(rename_pairs)} 个文件")
    table.add_column("#", style="yellow", width=4)
    table.add_column("原文件名", style="cyan", overflow="fold")
    table.add_column("新文件名", style="green", overflow="fold")
    table.add_column("状态", style="white")

    for idx, (old_path, new_path) in enumerate(rename_pairs[:20], 1):
        status = ""
        if old_path == new_path:
            status = "名称未变"
        elif new_path.exists():
            status = "⚠ 将覆盖"
        table.add_row(
            str(idx),
            old_path.name,
            new_path.name,
            click.style(status, fg="yellow") if status else "",
        )

    if len(rename_pairs) > 20:
        table.add_row("...", f"... 还有 {len(rename_pairs) - 20} 个文件", "", "")

    console.print(table)

    if overwrite_count > 0:
        click.echo(click.style(
            f"\n⚠  有 {overwrite_count} 个目标文件已存在，将被覆盖：",
            fg="yellow", bold=True
        ))
        display_count = min(overwrite_count, 10)
        for i, (s, t) in enumerate(overwrite_pairs[:display_count], 1):
            click.echo(f"  {i:2d}. {t.name}")
        if overwrite_count > 10:
            click.echo(f"  ... 还有 {overwrite_count - 10} 个文件将被覆盖")
        click.echo(click.style("  运行时会提示确认，未确认的文件将跳过", fg="cyan"))

    click.echo(click.style("\n预览模式 - 不会实际重命名文件，磁盘文件保持不变", fg="yellow"))


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


def _save_rename_history(project_root: Path, renamed_files: list):
    if not renamed_files:
        return
    history_file = project_root / ".brand-kit" / "cache" / "rename_last.json"
    history_file.parent.mkdir(parents=True, exist_ok=True)
    import json
    from datetime import datetime
    data = {
        "timestamp": datetime.now().isoformat(),
        "files": [{"old": old, "new": new} for old, new in renamed_files],
    }
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_last_rename(project_root: Path) -> dict:
    history_file = project_root / ".brand-kit" / "cache" / "rename_last.json"
    if not history_file.exists():
        return {}
    import json
    with open(history_file, "r", encoding="utf-8") as f:
        return json.load(f)


def undo_last_rename(project_root: Path, logger, results: dict):
    last_rename = load_last_rename(project_root)
    if not last_rename:
        return False, "没有找到上次重命名记录"

    renamed = last_rename.get("files", [])
    if not renamed:
        return False, "上次重命名记录为空"

    success_count = 0
    fail_count = 0

    for item in reversed(renamed):
        old_path = Path(item["old"])
        new_path = Path(item["new"])

        actual_current = new_path
        try:
            if actual_current.exists() and not old_path.exists():
                success, msg = safe_move(actual_current, old_path, False)
                if success:
                    success_count += 1
                    results["items"].append({
                        "name": f"{actual_current.name} → {old_path.name}",
                        "type": old_path.suffix.lstrip("."),
                        "size": format_size(old_path.stat().st_size),
                        "status": "success",
                        "notes": "已撤销重命名",
                    })
                    logger.log_action(
                        "undo_rename", str(actual_current), str(old_path),
                        status="success", details="撤销重命名"
                    )
                else:
                    fail_count += 1
                    results["items"].append({
                        "name": actual_current.name,
                        "type": actual_current.suffix.lstrip("."),
                        "size": format_size(actual_current.stat().st_size),
                        "status": "error",
                        "notes": msg,
                    })
                    logger.log_action(
                        "undo_rename", str(actual_current),
                        status="failed", details=msg
                    )
            elif old_path.exists():
                fail_count += 1
                results["items"].append({
                    "name": old_path.name,
                    "type": old_path.suffix.lstrip("."),
                    "size": "N/A",
                    "status": "warning",
                    "notes": "目标已存在，跳过",
                })
                logger.log_action(
                    "undo_rename", str(actual_current),
                    status="skipped", details="目标已存在"
                )
            else:
                fail_count += 1
                results["items"].append({
                    "name": actual_current.name if actual_current.exists() else "unknown",
                    "type": actual_current.suffix.lstrip("."),
                    "size": "N/A",
                    "status": "error",
                    "notes": "文件不存在",
                })
                logger.log_action(
                    "undo_rename", str(actual_current),
                    status="failed", details="文件不存在"
                )
        except Exception as e:
            fail_count += 1
            results["items"].append({
                "name": actual_current.name,
                "type": actual_current.suffix.lstrip("."),
                "size": "N/A",
                "status": "error",
                "notes": str(e),
            })
            logger.log_action(
                "undo_rename", str(actual_current),
                status="failed", details=str(e)
            )

    results["summary"]["撤销成功"] = success_count
    results["summary"]["撤销失败"] = fail_count

    history_file = project_root / ".brand-kit" / "cache" / "rename_last.json"
    if history_file.exists():
        history_file.unlink()

    return True, f"撤销 {success_count} 个文件，失败 {fail_count} 个"
