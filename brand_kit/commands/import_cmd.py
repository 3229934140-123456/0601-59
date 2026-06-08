import os
import shutil
from pathlib import Path
from typing import List, Set, Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from brand_kit.cli import pass_brand
from brand_kit.utils import (
    get_files_by_extension,
    safe_copy,
    sanitize_filename,
    get_next_available_path,
    get_file_hash,
    format_size,
    IMAGE_EXTENSIONS,
    FONT_EXTENSIONS,
    ICON_EXTENSIONS,
)
from brand_kit.logger import Logger

console = Console()


@click.command("import")
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False, dir_okay=True))
@click.option("--type", "-t", "import_type",
              type=click.Choice(["image", "font", "icon", "all"], case_sensitive=False),
              default="all", help="导入类型")
@click.option("--theme", default="default", help="主题分类")
@click.option("--filter", "-f", "format_filter", multiple=True,
              help="过滤指定格式，如 --filter .png --filter .jpg")
@click.option("--recursive/--no-recursive", default=True, help="是否递归扫描子目录")
@click.option("--overwrite", is_flag=True, help="覆盖已存在的文件")
@click.option("--preview", is_flag=True, help="预览模式，不实际复制文件")
@click.option("--copyright", "copyright_text", default="", help="添加版权说明")
@click.option("--dedup/--no-dedup", default=True, help="去重检测")
@click.option("--report", is_flag=True, help="生成复核报告")
@click.option("--resume", is_flag=True, help="从上次中断处恢复")
@pass_brand
def import_cmd(brand, source_dir, import_type, theme, format_filter,
               recursive, overwrite, preview, copyright_text, dedup,
               report, resume):
    """导入图片、字体和图标素材"""
    project_root = brand["project_root"]
    config = brand["config"]
    logger = brand["logger"]

    source_path = Path(source_dir).resolve()

    target_dirs = {
        "image": project_root / "assets" / "images" / theme,
        "font": project_root / "assets" / "fonts" / theme,
        "icon": project_root / "assets" / "icons" / theme,
    }

    extensions = _get_extensions(import_type, config, format_filter)

    files = get_files_by_extension(source_path, extensions, recursive)

    if not files:
        click.echo(click.style("✗ 未找到符合条件的文件", fg="yellow"))
        return

    if preview:
        _show_preview(files, import_type, theme, target_dirs)
        return

    if resume:
        processed = _load_resume_state(project_root)
        files = [f for f in files if str(f) not in processed]
        click.echo(click.style(f"恢复操作，跳过 {len(processed)} 个已处理文件", fg="cyan"))

    logger.start_session("import")

    results = {
        "items": [],
        "summary": {
            "总计": len(files),
            "成功": 0,
            "跳过": 0,
            "失败": 0,
        },
    }

    existing_hashes = set()
    if dedup:
        existing_hashes = _collect_existing_hashes(target_dirs, import_type)

    processed_files = set()
    if resume:
        processed_files = _load_resume_state(project_root)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"导入 {len(files)} 个文件...", total=len(files))

        for file_path in files:
            try:
                file_type = _get_file_type(file_path, import_type)
                if not file_type:
                    continue

                target_dir = target_dirs.get(file_type)
                if not target_dir:
                    continue

                target_dir.mkdir(parents=True, exist_ok=True)

                if dedup:
                    file_hash = get_file_hash(file_path)
                    if file_hash in existing_hashes:
                        results["items"].append({
                            "name": file_path.name,
                            "type": file_type,
                            "size": format_size(file_path.stat().st_size),
                            "status": "skipped",
                            "notes": "重复文件",
                        })
                        results["summary"]["跳过"] += 1
                        logger.log_action(
                            "import", str(file_path),
                            status="skipped", details="重复文件"
                        )
                        progress.advance(task)
                        continue
                    existing_hashes.add(file_hash)

                target_filename = sanitize_filename(file_path.name)
                target_path = target_dir / target_filename

                if target_path.exists() and not overwrite:
                    target_path = get_next_available_path(target_dir, target_filename)

                success, msg = safe_copy(file_path, target_path, overwrite)

                if success:
                    if copyright_text:
                        _add_copyright_metadata(target_path, copyright_text)

                    results["items"].append({
                        "name": target_path.name,
                        "type": file_type,
                        "size": format_size(target_path.stat().st_size),
                        "status": "success",
                        "notes": msg,
                    })
                    results["summary"]["成功"] += 1
                    logger.log_action(
                        "import", str(file_path), str(target_path),
                        status="success", details=msg
                    )
                else:
                    results["items"].append({
                        "name": file_path.name,
                        "type": file_type,
                        "size": format_size(file_path.stat().st_size),
                        "status": "error",
                        "notes": msg,
                    })
                    results["summary"]["失败"] += 1
                    logger.log_action(
                        "import", str(file_path),
                        status="failed", details=msg
                    )

                processed_files.add(str(file_path))
                _save_resume_state(project_root, processed_files)

            except Exception as e:
                results["items"].append({
                    "name": file_path.name,
                    "type": "unknown",
                    "size": format_size(file_path.stat().st_size) if file_path.exists() else "N/A",
                    "status": "error",
                    "notes": str(e),
                })
                results["summary"]["失败"] += 1
                logger.log_action(
                    "import", str(file_path),
                    status="failed", details=str(e)
                )

            progress.advance(task)

    logger.end_session()
    _clear_resume_state(project_root)

    _show_results(results)

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("import", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


def _get_extensions(import_type: str, config, format_filter) -> Set[str]:
    if format_filter:
        return {f.lower() if f.startswith(".") else f".{f.lower()}" for f in format_filter}

    exts = set()
    if import_type in ("image", "all"):
        exts.update(config.image_formats)
    if import_type in ("font", "all"):
        exts.update(config.font_formats)
    if import_type in ("icon", "all"):
        exts.update(config.icon_formats)
    return exts


def _get_file_type(file_path: Path, import_type: str) -> Optional[str]:
    ext = file_path.suffix.lower()
    if import_type == "all":
        if ext in IMAGE_EXTENSIONS:
            return "image"
        if ext in FONT_EXTENSIONS:
            return "font"
        if ext in ICON_EXTENSIONS:
            return "icon"
        return None
    return import_type.lower()


def _collect_existing_hashes(target_dirs: dict, import_type: str) -> Set[str]:
    hashes = set()
    for ftype, tdir in target_dirs.items():
        if import_type != "all" and ftype != import_type:
            continue
        if not tdir.exists():
            continue
        for ext_dir, _, files in os.walk(tdir):
            for f in files:
                fpath = Path(ext_dir) / f
                try:
                    hashes.add(get_file_hash(fpath))
                except Exception:
                    pass
    return hashes


def _show_preview(files: List[Path], import_type: str, theme: str, target_dirs: dict):
    table = Table(title=f"导入预览 - 共 {len(files)} 个文件")
    table.add_column("源文件", style="cyan", overflow="fold")
    table.add_column("类型", style="green")
    table.add_column("大小", style="yellow")
    table.add_column("目标位置", style="magenta")

    for f in files[:20]:
        ftype = _get_file_type(f, import_type) or "unknown"
        target = target_dirs.get(ftype, Path("N/A"))
        table.add_row(
            f.name,
            ftype,
            format_size(f.stat().st_size),
            str(target / f.name),
        )

    if len(files) > 20:
        table.add_row(f"... 还有 {len(files) - 20} 个文件", "", "", "")

    console.print(table)
    click.echo(click.style("\n预览模式 - 不会实际复制文件", fg="yellow"))


def _show_results(results: dict):
    click.echo()
    table = Table(title="导入结果")
    table.add_column("统计项", style="cyan")
    table.add_column("数量", style="green", justify="right")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)

    success_count = results["summary"].get("成功", 0)
    if success_count > 0:
        click.echo(click.style(f"\n✓ 成功导入 {success_count} 个文件", fg="green"))
    else:
        click.echo(click.style("\n✗ 没有文件被成功导入", fg="red"))


def _add_copyright_metadata(file_path: Path, copyright_text: str):
    ext = file_path.suffix.lower()
    if ext in (".jpg", ".jpeg", ".png"):
        try:
            from PIL import Image, PngImagePlugin
            img = Image.open(file_path)
            if ext in (".jpg", ".jpeg"):
                exif = img.getexif()
                exif[0x8298] = copyright_text
                img.save(file_path, exif=exif)
            elif ext == ".png":
                meta = PngImagePlugin.PngInfo()
                meta.add_text("Copyright", copyright_text)
                img.save(file_path, pnginfo=meta)
        except Exception:
            pass


def _save_resume_state(project_root: Path, processed: set):
    state_file = project_root / ".brand-kit" / "cache" / "import_resume.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    import json
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(list(processed), f)


def _load_resume_state(project_root: Path) -> set:
    state_file = project_root / ".brand-kit" / "cache" / "import_resume.json"
    if not state_file.exists():
        return set()
    import json
    with open(state_file, "r", encoding="utf-8") as f:
        return set(json.load(f))


def _clear_resume_state(project_root: Path):
    state_file = project_root / ".brand-kit" / "cache" / "import_resume.json"
    if state_file.exists():
        state_file.unlink()
