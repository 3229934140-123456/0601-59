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
    safe_copy,
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
@click.option("--overwrite", is_flag=True, help="覆盖已存在的文件")
@click.option("--copyright", "copyright_text", default="", help="版权说明")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def resize_cmd(brand, source, sizes, preset, output, theme, output_format,
               quality, method, fit, background, suffix, recursive,
               preview, overwrite, copyright_text, report):
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

    if preview:
        _show_preview(files, target_sizes, output_dir, output_format, fit)
        return

    logger.start_session("resize")

    results = {
        "items": [],
        "summary": {
            "源图片": len(files),
            "目标尺寸": len(target_sizes),
            "生成文件": 0,
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
        total = len(files) * len(target_sizes)
        task = progress.add_task(f"生成 {total} 张图片...", total=total)

        for img_path in files:
            try:
                img = Image.open(img_path)
                original_size = img.size

                for size_name, (target_w, target_h) in target_sizes:
                    try:
                        resized_img = _resize_image(img, target_w, target_h, fit, background, resample)

                        out_filename = _generate_filename(
                            img_path, size_name, target_w, target_h,
                            output_format, suffix
                        )
                        out_path = output_dir / out_filename

                        if out_path.exists() and not overwrite:
                            results["items"].append({
                                "name": out_path.name,
                                "type": "image",
                                "size": format_size(out_path.stat().st_size),
                                "status": "skipped",
                                "notes": "文件已存在",
                            })
                            progress.advance(task)
                            continue

                        _save_image(resized_img, out_path, output_format, quality, copyright_text)

                        results["items"].append({
                            "name": out_path.name,
                            "type": "image",
                            "size": f"{target_w}x{target_h}",
                            "status": "success",
                            "notes": f"{format_size(out_path.stat().st_size)}",
                        })
                        results["summary"]["生成文件"] += 1

                        logger.log_action(
                            "resize", str(img_path), str(out_path),
                            status="success",
                            details=f"{original_size[0]}x{original_size[1]} -> {target_w}x{target_h}"
                        )
                    except Exception as e:
                        results["items"].append({
                            "name": f"{img_path.name} ({target_w}x{target_h})",
                            "type": "image",
                            "size": "N/A",
                            "status": "error",
                            "notes": str(e),
                        })
                        results["summary"]["失败"] += 1
                        logger.log_action(
                            "resize", str(img_path),
                            status="failed",
                            details=f"{target_w}x{target_h}: {e}"
                        )

                    progress.advance(task)

                img.close()
            except Exception as e:
                results["items"].append({
                    "name": img_path.name,
                    "type": "image",
                    "size": "N/A",
                    "status": "error",
                    "notes": f"打开失败: {e}",
                })
                results["summary"]["失败"] += len(target_sizes)
                logger.log_action(
                    "resize", str(img_path),
                    status="failed", details=f"打开失败: {e}"
                )
                for _ in target_sizes:
                    progress.advance(task)

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


def _show_preview(files: List[Path], sizes: List[Tuple[str, Tuple[int, int]]],
                  output_dir: Path, output_format: str, fit: str):
    table = Table(title=f"尺寸预览 - {len(files)} 张图片 × {len(sizes)} 种尺寸")
    table.add_column("尺寸名称", style="cyan")
    table.add_column("宽×高", style="green")
    table.add_column("适应方式", style="yellow")
    table.add_column("输出格式", style="magenta")

    for name, (w, h) in sizes:
        table.add_row(name, f"{w} × {h}", fit, output_format)

    console.print(table)

    click.echo(f"\n将生成 {len(files) * len(sizes)} 个文件")
    click.echo(f"输出目录: {output_dir}")
    click.echo(click.style("\n预览模式 - 不会实际生成文件", fg="yellow"))


def _show_results(results: dict, output_dir: Path):
    click.echo()
    table = Table(title="批量调整结果")
    table.add_column("统计项", style="cyan")
    table.add_column("数量", style="green", justify="right")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)
    click.echo(f"\n输出目录: {output_dir}")

    success_count = results["summary"].get("生成文件", 0)
    if success_count > 0:
        click.echo(click.style(f"\n✓ 成功生成 {success_count} 个文件", fg="green"))
    else:
        click.echo(click.style("\n✗ 没有生成文件", fg="yellow"))
