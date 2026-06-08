import os
import re
from pathlib import Path
from typing import List, Dict, Tuple, Set
from collections import defaultdict

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from PIL import Image

from brand_kit.cli import pass_brand
from brand_kit.utils import (
    get_files_by_extension,
    get_file_hash,
    format_size,
    IMAGE_EXTENSIONS,
    FONT_EXTENSIONS,
    ICON_EXTENSIONS,
)

console = Console()


NAMING_PATTERNS = {
    "snake": r"^[a-z][a-z0-9]*(_[a-z0-9]+)*$",
    "kebab": r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$",
    "camel": r"^[a-z][a-zA-Z0-9]*$",
    "pascal": r"^[A-Z][a-zA-Z0-9]*$",
}


@click.command("check")
@click.argument("target_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True), required=False)
@click.option("--type", "check_type",
              type=click.Choice(["all", "resolution", "alpha", "naming", "duplicate"]),
              default="all", help="检查类型")
@click.option("--min-width", type=int, default=None, help="最小宽度")
@click.option("--min-height", type=int, default=None, help="最小高度")
@click.option("--naming-style", default="snake",
              type=click.Choice(["snake", "kebab", "camel", "pascal"]),
              help="命名风格")
@click.option("--file-type", default="image",
              type=click.Choice(["image", "font", "icon", "all"]),
              help="文件类型")
@click.option("--theme", default="", help="按主题过滤")
@click.option("--recursive/--no-recursive", default=True, help="递归检查")
@click.option("--threshold", type=float, default=1.0,
              help="透明边检测阈值 (像素)")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def check_cmd(brand, target_dir, check_type, min_width, min_height,
              naming_style, file_type, theme, recursive, threshold, report):
    """检查分辨率、透明边、命名和重复文件"""
    project_root = brand["project_root"]
    config = brand["config"]
    logger = brand["logger"]

    if target_dir is None:
        target_dir = project_root / "assets" / "images"
        if theme:
            target_dir = target_dir / theme

    target_path = Path(target_dir).resolve()

    if not target_path.exists():
        click.echo(click.style(f"✗ 目录不存在: {target_path}", fg="red"))
        return

    extensions = _get_extensions(file_type, config)
    files = get_files_by_extension(target_path, extensions, recursive)

    if not files:
        click.echo(click.style("✗ 未找到文件", fg="yellow"))
        return

    logger.start_session("check")

    results = {
        "items": [],
        "summary": {
            "总文件数": len(files),
            "通过": 0,
            "警告": 0,
            "错误": 0,
        },
    }

    checks_to_run = []
    if check_type == "all":
        checks_to_run = ["resolution", "alpha", "naming", "duplicate"]
    else:
        checks_to_run = [check_type]

    file_status = {}
    file_notes = {}
    for f in files:
        file_status[f] = "success"
        file_notes[f] = []

    if "resolution" in checks_to_run:
        _check_resolution(files, file_status, file_notes, min_width or config.min_resolution[0],
                          min_height or config.min_resolution[1])

    if "alpha" in checks_to_run:
        _check_alpha(files, file_status, file_notes, threshold)

    if "naming" in checks_to_run:
        _check_naming(files, file_status, file_notes, naming_style)

    if "duplicate" in checks_to_run:
        duplicates = _check_duplicates(files, file_status, file_notes)
        results["summary"]["重复文件组"] = len(duplicates)

    for f in files:
        status = file_status[f]
        results["items"].append({
            "name": f.name,
            "type": f.suffix.lstrip("."),
            "size": format_size(f.stat().st_size),
            "status": status,
            "notes": "; ".join(file_notes[f]) if file_notes[f] else "通过检查",
        })

        if status == "success":
            results["summary"]["通过"] += 1
        elif status == "warning":
            results["summary"]["警告"] += 1
        else:
            results["summary"]["错误"] += 1

    logger.log_action(
        "check", str(target_path),
        status="success",
        details=f"检查 {len(files)} 个文件，通过 {results['summary']['通过']}，"
                f"警告 {results['summary']['警告']}，错误 {results['summary']['错误']}"
    )
    logger.end_session()

    _show_results(results, checks_to_run)

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("check", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


def _get_extensions(file_type: str, config) -> set:
    if file_type == "image":
        return set(e for e in config.image_formats if e not in (".svg",))
    elif file_type == "font":
        return set(config.font_formats)
    elif file_type == "icon":
        return set(e for e in config.icon_formats if e not in (".svg",))
    else:
        exts = set(config.image_formats) | set(config.font_formats) | set(config.icon_formats)
        return set(e for e in exts if e not in (".svg",))


def _check_resolution(files: List[Path], file_status: dict, file_notes: dict,
                      min_width: int, min_height: int):
    for f in files:
        try:
            with Image.open(f) as img:
                w, h = img.size
                if w < min_width or h < min_height:
                    file_status[f] = "error"
                    file_notes[f].append(f"分辨率不足: {w}x{h} (需要 {min_width}x{min_height})")
        except Exception as e:
            file_status[f] = "error"
            file_notes[f].append(f"无法读取: {e}")


def _check_alpha(files: List[Path], file_status: dict, file_notes: dict, threshold: float):
    for f in files:
        try:
            with Image.open(f) as img:
                if img.mode not in ("RGBA", "LA", "PA"):
                    continue

                alpha = img.split()[-1] if img.mode in ("RGBA", "LA") else None
                if alpha is None and img.mode == "PA":
                    alpha = img.convert("RGBA").split()[-1]

                if alpha is None:
                    continue

                alpha_data = alpha.load()
                w, h = img.size
                has_transparency = False
                transparent_borders = 0

                top_row = all(alpha_data[x, 0] < 10 for x in range(w))
                bottom_row = all(alpha_data[x, h - 1] < 10 for x in range(w))
                left_col = all(alpha_data[0, y] < 10 for y in range(h))
                right_col = all(alpha_data[w - 1, y] < 10 for y in range(h))

                border_count = sum([top_row, bottom_row, left_col, right_col])
                if border_count > 0:
                    if border_count >= 2 and file_status[f] != "error":
                        file_status[f] = "warning"
                    file_notes[f].append(f"检测到 {border_count} 条透明边")

        except Exception as e:
            if file_status[f] == "success":
                file_status[f] = "warning"
            file_notes[f].append(f"透明检查失败: {e}")


def _check_naming(files: List[Path], file_status: dict, file_notes: dict, style: str):
    pattern = NAMING_PATTERNS.get(style, NAMING_PATTERNS["snake"])
    regex = re.compile(pattern)

    for f in files:
        stem = f.stem
        if not regex.match(stem):
            if file_status[f] == "success":
                file_status[f] = "warning"
            file_notes[f].append(f"命名不符合 {style} 风格")


def _check_duplicates(files: List[Path], file_status: dict, file_notes: dict) -> List[List[Path]]:
    hash_map = defaultdict(list)

    for f in files:
        try:
            file_hash = get_file_hash(f)
            hash_map[file_hash].append(f)
        except Exception:
            pass

    duplicates = []
    for file_hash, file_list in hash_map.items():
        if len(file_list) > 1:
            duplicates.append(file_list)
            for f in file_list:
                file_status[f] = "error"
                other_files = ", ".join([x.name for x in file_list if x != f])
                file_notes[f].append(f"与其他文件重复: {other_files}")

    return duplicates


def _show_results(results: dict, checks: List[str]):
    click.echo()

    table = Table(title=f"检查结果 - 检查项: {', '.join(checks)}")
    table.add_column("统计项", style="cyan")
    table.add_column("数量", style="green", justify="right")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)

    click.echo()
    detail_table = Table(title="详细结果 (前20条)")
    detail_table.add_column("文件名", style="cyan", overflow="fold")
    detail_table.add_column("类型", style="yellow")
    detail_table.add_column("状态", style="green")
    detail_table.add_column("备注", overflow="fold")

    for item in results["items"][:20]:
        status = item["status"]
        status_style = {
            "success": "green",
            "warning": "yellow",
            "error": "red",
        }.get(status, "white")

        detail_table.add_row(
            item["name"],
            item["type"],
            click.style(status, fg=status_style),
            item["notes"],
        )

    if len(results["items"]) > 20:
        detail_table.add_row(f"... 还有 {len(results['items']) - 20} 个文件", "", "", "")

    console.print(detail_table)

    errors = results["summary"].get("错误", 0)
    warnings = results["summary"].get("警告", 0)

    if errors > 0:
        click.echo(click.style(f"\n✗ 发现 {errors} 个错误", fg="red"))
    if warnings > 0:
        click.echo(click.style(f"⚠  发现 {warnings} 个警告", fg="yellow"))
    if errors == 0 and warnings == 0:
        click.echo(click.style("\n✓ 所有检查通过！", fg="green"))
