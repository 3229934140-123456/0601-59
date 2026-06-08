import os
from pathlib import Path
from typing import List, Tuple

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from PIL import Image

from brand_kit.cli import pass_brand
from brand_kit.utils import (
    get_files_by_extension,
    sanitize_filename,
    format_size,
    confirm_overwrite,
    check_overwrites,
    get_file_info,
)

console = Console()


RESIZE_PRESETS = {
    "icon": [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256), (512, 512)],
    "banner": [(1920, 1080), (1280, 720), (768, 432)],
    "thumbnail": [(400, 300), (200, 150)],
    "square": [(800, 800), (400, 400), (200, 200)],
    "social": [
        (1200, 630),   # Facebook/LinkedIn
        (1080, 1080),  # Instagram Square
        (1080, 1920),  # Instagram Story
        (1200, 675),   # Twitter
    ],
    "app": [
        (1024, 1024),  # App Store
        (512, 512),    # Play Store
        (180, 180),    # iPhone
        (167, 167),    # iPad Pro
    ],
}


RESAMPLE_METHODS = {
    "lanczos": Image.LANCZOS,
    "bicubic": Image.BICUBIC,
    "bilinear": Image.BILINEAR,
    "nearest": Image.NEAREST,
}


@click.command("resize")
@click.argument("source", type=click.Path(exists=True, file_okay=True, dir_okay=True), required=False)
@click.option("--sizes", "-s", multiple=True, help="尺寸列表，如 1920x1080 800x600")
@click.option("--preset", "-p", multiple=True,
              type=click.Choice(list(RESIZE_PRESETS.keys()) + ["all"]),
              help="预设尺寸方案")
@click.option("--output", "-o", default=None, help="输出目录")
@click.option("--theme", default="default", help="主题名称")
@click.option("--format", "output_format", default="original",
              type=click.Choice(["original", "png", "jpg", "webp", "jpeg"]),
              help="输出格式")
@click.option("--quality", type=int, default=85, help="输出质量 (1-100)")
@click.option("--method", default="lanczos",
              type=click.Choice(list(RESAMPLE_METHODS.keys())),
              help="缩放算法")
@click.option("--fit", default="contain",
              type=click.Choice(["contain", "cover", "fill", "width", "height"]),
              help="尺寸适应方式")
@click.option("--background", default="white", help="填充背景色 (cover模式)")
@click.option("--suffix/--no-suffix", default=True, help="文件名添加尺寸后缀")
@click.option("--recursive/--no-recursive", default=True, help="递归处理子目录")
@click.option("--preview", is_flag=True, help="预览模式")
@click.option("--dry-run", "dry_run", is_flag=True, help="对比模式，展示详细差异但不执行")
@click.option("--overwrite", is_flag=True, help="覆盖已存在的文件")
@click.option("--copyright", "copyright_text", default="", help="版权说明")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def resize_cmd(brand, source, sizes, preset, output, theme, output_format,
               quality, method, fit, background, suffix, recursive,
               preview, dry_run, overwrite, copyright_text, report):
    """批量输出多尺寸图片"""
    project_root = brand["project_root"]
    config = brand["config"]
    logger = brand["logger"]

    if source is None:
        source = project_root / "assets" / "images"

    source_path = Path(source).resolve()

    if not source_path.exists():
        click.echo(click.style(f"✗ 路径不存在: {source_path}", fg="red"))
        return

    image_extensions = set(e for e in config.image_formats if e not in (".svg",))
    files = _collect_images(source_path, image_extensions, recursive)

    if not files:
        click.echo(click.style("✗ 未找到图片文件", fg="yellow"))
        return

    target_sizes = _parse_sizes(sizes, preset, config)

    if not target_sizes:
        click.echo(click.style("✗ 请指定尺寸或预设方案", fg="red"))
        return

    if output is None:
        output_dir = project_root / "output" / "resized" / theme
    else:
        output_dir = Path(output).resolve()

    output_pairs = []
    for img_path in files:
        for size_name, (target_w, target_h) in target_sizes:
            out_filename = _generate_filename(
                img_path, size_name, target_w, target_h,
                output_format, suffix
            )
            out_path = output_dir / out_filename
            output_pairs.append((img_path, out_path, size_name, target_w, target_h))

    if preview:
        _show_preview(output_pairs, output_dir, output_format, fit, overwrite)
        return

    if dry_run:
        _show_dry_run(output_pairs, output_dir, target_sizes)
        return

    overwrite_check = [(Path("dummy"), t) for _, t, _, _, _ in output_pairs]
    overwrite_pairs = check_overwrites(overwrite_check)
    if overwrite_pairs:
        confirmed_pairs = confirm_overwrite(overwrite_pairs, auto_confirm=overwrite)
        confirmed_targets = {str(t) for _, t in confirmed_pairs}
    else:
        confirmed_targets = set()

    logger.start_session("resize")

    results = {
        "items": [],
        "summary": {
            "源图片": len(files),
            "目标尺寸": len(target_sizes),
            "新增": 0,
            "覆盖": 0,
            "跳过": 0,
            "失败": 0,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    resample = RESAMPLE_METHODS.get(method, Image.LANCZOS)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        total = len(output_pairs)
        task = progress.add_task(f"生成 {total} 张图片...", total=total)

        current_img = None
        current_img_path = None
        for img_path, out_path, size_name, target_w, target_h in output_pairs:
            try:
                if current_img_path != img_path:
                    if current_img:
                        current_img.close()
                    current_img = Image.open(img_path)
                    current_img_path = img_path
                    original_size = current_img.size

                is_overwrite = out_path.exists()
                if is_overwrite:
                    if str(out_path) not in confirmed_targets:
                        results["items"].append({
                            "source": img_path.name,
                            "target": out_path.name,
                            "name": out_path.name,
                            "type": "image",
                            "size": format_size(out_path.stat().st_size),
                            "status": "skipped",
                            "notes": "\u6587\u4ef6\u5df2\u5b58\u5728\uff0c\u672a\u786e\u8ba4\u8986\u76d6",
                        })
                        results["summary"]["跳过"] += 1
                        logger.log_action(
                            "resize", str(img_path), str(out_path),
                            status="skipped", details="目标文件已存在，未确认覆盖"
                        )
                        progress.advance(task)
                        continue

                resized_img = _resize_image(current_img, target_w, target_h, fit, background, resample)
                _save_image(resized_img, out_path, output_format, quality, copyright_text)

                status = "overwritten" if is_overwrite else "generated"
                status_key = "\u8986\u76d6" if is_overwrite else "\u65b0\u589e"
                results["items"].append({
                    "source": img_path.name,
                    "target": out_path.name,
                    "name": out_path.name,
                    "type": "image",
                    "size": f"{target_w}x{target_h}",
                    "status": status,
                    "notes": f"{format_size(out_path.stat().st_size)}",
                })
                results["summary"][status_key] += 1

                logger.log_action(
                    "resize", str(img_path), str(out_path),
                    status=status,
                    details=f"{original_size[0]}x{original_size[1]} -> {target_w}x{target_h}"
                )
            except Exception as e:
                results["items"].append({
                    "source": img_path.name if 'img_path' in dir() else "",
                    "target": f"{target_w}x{target_h}",
                    "name": f"{img_path.name} ({target_w}x{target_h})",
                    "type": "image",
                    "size": "N/A",
                    "status": "failed",
                    "notes": str(e),
                })
                results["summary"]["失败"] += 1
                logger.log_action(
                    "resize", str(img_path),
                    status="failed",
                    details=f"{target_w}x{target_h}: {e}"
                )

            progress.advance(task)

        if current_img:
            current_img.close()

    logger.end_session()
    _show_results(results, output_dir)

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("resize", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


def _collect_images(source_path: Path, extensions: set, recursive: bool) -> List[Path]:
    if source_path.is_file():
        return [source_path] if source_path.suffix.lower() in extensions else []
    return get_files_by_extension(source_path, extensions, recursive)


def _parse_sizes(sizes_arg: tuple, presets: tuple, config) -> List[Tuple[str, Tuple[int, int]]]:
    result = []

    for size_str in sizes_arg:
        try:
            w, h = size_str.lower().replace("x", ",").replace("*", ",").split(",")
            w, h = int(w.strip()), int(h.strip())
            result.append((f"{w}x{h}", (w, h)))
        except Exception:
            pass

    preset_list = list(presets)
    if "all" in preset_list:
        preset_list = list(RESIZE_PRESETS.keys())

    for p in preset_list:
        if p in RESIZE_PRESETS:
            for w, h in RESIZE_PRESETS[p]:
                result.append((f"{p}_{w}x{h}", (w, h)))

    if not result and hasattr(config, 'resize_sizes') and config.resize_sizes:
        for name, sizes in config.resize_sizes.items():
            for w, h in sizes:
                result.append((f"{name}_{w}x{h}", (w, h)))

    return result


def _resize_image(img: Image.Image, target_w: int, target_h: int,
                  fit: str, background: str, resample) -> Image.Image:
    if fit == "fill":
        return img.resize((target_w, target_h), resample)

    original_w, original_h = img.size
    aspect = original_w / original_h
    target_aspect = target_w / target_h

    if fit == "contain":
        if aspect > target_aspect:
            new_w = target_w
            new_h = int(target_w / aspect)
        else:
            new_h = target_h
            new_w = int(target_h * aspect)

        resized = img.resize((new_w, new_h), resample)
        canvas = Image.new("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB",
                          (target_w, target_h), background)
        x = (target_w - new_w) // 2
        y = (target_h - new_h) // 2
        canvas.paste(resized, (x, y), resized if resized.mode == "RGBA" else None)
        return canvas

    elif fit == "cover":
        if aspect > target_aspect:
            new_h = target_h
            new_w = int(target_h * aspect)
        else:
            new_w = target_w
            new_h = int(target_w / aspect)

        resized = img.resize((new_w, new_h), resample)
        left = (new_w - target_w) // 2
        top = (new_h - target_h) // 2
        return resized.crop((left, top, left + target_w, top + target_h))

    elif fit == "width":
        new_w = target_w
        new_h = int(target_w / aspect)
        return img.resize((new_w, new_h), resample)

    elif fit == "height":
        new_h = target_h
        new_w = int(target_h * aspect)
        return img.resize((new_w, new_h), resample)

    return img.resize((target_w, target_h), resample)


def _generate_filename(img_path: Path, size_name: str, w: int, h: int,
                       output_format: str, add_suffix: bool) -> str:
    stem = img_path.stem
    if output_format == "original":
        ext = img_path.suffix
    else:
        ext = f".{output_format}"
        if ext == ".jpeg":
            ext = ".jpg"

    if add_suffix:
        return f"{stem}_{size_name}{ext}"
    return f"{stem}{ext}"


def _save_image(img: Image.Image, output_path: Path, output_format: str,
                quality: int, copyright_text: str):
    save_kwargs = {}
    ext = output_path.suffix.lower()

    if ext in (".jpg", ".jpeg"):
        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, "white")
            background.paste(img, mask=img.split()[3])
            img = background
        save_kwargs["quality"] = quality
        save_kwargs["optimize"] = True

        if copyright_text:
            from PIL import ExifTags
            exif = img.getexif()
            exif[0x8298] = copyright_text
            save_kwargs["exif"] = exif

    elif ext == ".png":
        save_kwargs["optimize"] = True
        if copyright_text:
            from PIL import PngImagePlugin
            meta = PngImagePlugin.PngInfo()
            meta.add_text("Copyright", copyright_text)
            save_kwargs["pnginfo"] = meta

    elif ext == ".webp":
        save_kwargs["quality"] = quality
        if copyright_text:
            meta = img.info
            meta["Copyright"] = copyright_text
            save_kwargs["exif"] = b""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, **save_kwargs)


def _show_preview(output_pairs: list, output_dir: Path, output_format: str,
                  fit: str, overwrite: bool):
    files_set = set()
    sizes_set = set()
    overwrite_pairs = [(s, t) for s, t, _, _, _ in output_pairs if t.exists()]
    overwrite_count = len(overwrite_pairs)

    for img_path, out_path, size_name, w, h in output_pairs:
        files_set.add(img_path.name)
        sizes_set.add((size_name, w, h))

    table = Table(title=f"尺寸预览 - {len(files_set)} 张图片 × {len(sizes_set)} 种尺寸")
    table.add_column("尺寸名称", style="cyan")
    table.add_column("宽×高", style="green")
    table.add_column("适应方式", style="yellow")
    table.add_column("输出格式", style="magenta")

    for name, w, h in sorted(sizes_set):
        table.add_row(name, f"{w} × {h}", fit, output_format)

    console.print(table)

    click.echo(f"\n将生成 {len(output_pairs)} 个文件")
    click.echo(f"输出目录: {output_dir}")

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

    click.echo(click.style("\n预览模式 - 不会实际生成文件，磁盘文件保持不变", fg="yellow"))


def _show_dry_run(output_pairs: list, output_dir: Path, target_sizes: list):
    overwrite_pairs = [(s, t, w, h) for s, t, _, w, h in output_pairs if t.exists()]
    new_pairs = [(s, t, w, h) for s, t, _, w, h in output_pairs if not t.exists()]

    total = len(output_pairs)
    will_overwrite = len(overwrite_pairs)
    will_create = len(new_pairs)

    files_set = {s.name for s, _, _, _, _ in output_pairs}

    click.echo()
    click.echo(click.style("=== Dry-Run 对比模式 ===", fg="cyan", bold=True))
    click.echo(f"源图片: {len(files_set)} 张，目标尺寸: {len(target_sizes)} 种")
    click.echo(f"总计 {total} 个输出文件："
               f"新增 {will_create} 个，覆盖 {will_overwrite} 个")
    click.echo(f"输出目录: {output_dir}")

    if overwrite_pairs:
        click.echo()
        table = Table(title=f"\u5373\u5c06\u8986\u76d6 ({will_overwrite} 个)")
        table.add_column("目标文件", style="yellow", overflow="fold")
        table.add_column("目标尺寸", style="green", justify="right")
        table.add_column("源大小", style="cyan", justify="right")
        table.add_column("目标大小", style="magenta", justify="right")
        table.add_column("源尺寸", style="cyan", justify="right")
        table.add_column("目标尺寸(实际)", style="magenta", justify="right")
        table.add_column("源哈希", style="cyan")
        table.add_column("目标哈希", style="magenta")

        for s, t, w, h in overwrite_pairs[:15]:
            src_info = get_file_info(s)
            tgt_info = get_file_info(t)
            src_hash_short = src_info["hash"][:8] if src_info["hash"] else "N/A"
            tgt_hash_short = tgt_info["hash"][:8] if tgt_info["hash"] else "N/A"
            table.add_row(
                t.name,
                f"{w}x{h}",
                src_info["size_str"],
                tgt_info["size_str"],
                src_info["dimensions_str"],
                tgt_info["dimensions_str"],
                src_hash_short,
                tgt_hash_short,
            )

        if len(overwrite_pairs) > 15:
            table.add_row(f"... 还有 {len(overwrite_pairs) - 15} 个", "", "", "", "", "", "", "")

        console.print(table)

    if new_pairs:
        click.echo()
        table = Table(title=f"\u5373\u5c06\u65b0\u589e ({will_create} 个)")
        table.add_column("新文件名", style="green", overflow="fold")
        table.add_column("目标尺寸", style="green", justify="right")
        table.add_column("源大小", style="cyan", justify="right")
        table.add_column("源尺寸", style="cyan", justify="right")
        table.add_column("源哈希", style="cyan")

        seen = set()
        rows = []
        for s, t, w, h in new_pairs:
            key = (s.name, w, h)
            if key in seen:
                continue
            seen.add(key)
            src_info = get_file_info(s)
            src_hash_short = src_info["hash"][:8] if src_info["hash"] else "N/A"
            rows.append((
                t.name,
                f"{w}x{h}",
                src_info["size_str"],
                src_info["dimensions_str"],
                src_hash_short,
            ))

        for row in rows[:15]:
            table.add_row(*row)

        if len(rows) > 15:
            table.add_row(f"... 还有 {len(rows) - 15} 个", "", "", "", "")

        console.print(table)

    click.echo()
    click.echo(click.style("Dry-Run 模式 - 仅读取文件信息，不生成任何输出", fg="yellow"))
    click.echo(click.style("  确认无误后，去掉 --dry-run 即可执行实际操作", fg="cyan"))


def _show_results(results: dict, output_dir: Path):
    click.echo()
    table = Table(title="\u6279\u91cf\u8c03\u6574\u7ed3\u679c")
    table.add_column("\u7edf\u8ba1\u9879", style="cyan")
    table.add_column("\u6570\u91cf", style="green", justify="right")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)
    click.echo(f"\n输出目录: {output_dir}")

    generated = results["summary"].get("\u65b0\u589e", 0)
    overwritten = results["summary"].get("\u8986\u76d6", 0)
    total_success = generated + overwritten
    if total_success > 0:
        parts = []
        if generated > 0:
            parts.append(f"\u65b0\u589e {generated} \u4e2a")
        if overwritten > 0:
            parts.append(f"\u8986\u76d6 {overwritten} \u4e2a")
        click.echo(click.style(f"\n\u2713 \u6210\u529f\u751f\u6210 {total_success} \u4e2a\u6587\u4ef6\uff08{', '.join(parts)}\uff09", fg="green"))
    else:
        click.echo(click.style("\n\u2717 \u6ca1\u6709\u751f\u6210\u6587\u4ef6", fg="yellow"))
