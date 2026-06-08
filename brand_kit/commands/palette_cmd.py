import os
import json
from pathlib import Path
from typing import List, Tuple, Dict

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from PIL import Image
from colorgram import colorgram

from brand_kit.cli import pass_brand
from brand_kit.utils import (
    get_files_by_extension,
    sanitize_filename,
    format_size,
)

console = Console()


@click.command("palette")
@click.argument("source", type=click.Path(exists=True, file_okay=True, dir_okay=True), required=False)
@click.option("--colors", "-n", type=int, default=6, help="提取颜色数量")
@click.option("--output", "-o", default=None, help="输出目录")
@click.option("--theme", default="default", help="主题名称")
@click.option("--format", "output_format", multiple=True,
              type=click.Choice(["image", "css", "json", "text", "ase", "all"]),
              default=["image", "json"], help="输出格式")
@click.option("--quality", type=click.Choice(["fast", "normal", "best"]),
              default="normal", help="提取质量")
@click.option("--sort-by", type=click.Choice(["frequency", "hue", "saturation", "luminance"]),
              default="frequency", help="颜色排序方式")
@click.option("--preview", is_flag=True, help="预览模式，只显示颜色不生成文件")
@click.option("--merge/--no-merge", default=False, help="合并所有图片的颜色")
@click.option("--copyright", "copyright_text", default="", help="版权说明")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def palette_cmd(brand, source, colors, output, theme, output_format,
                quality, sort_by, preview, merge, copyright_text, report):
    """提取主色并生成色板"""
    project_root = brand["project_root"]
    config = brand["config"]
    logger = brand["logger"]

    if source is None:
        source = project_root / "assets" / "images"

    source_path = Path(source).resolve()

    if not source_path.exists():
        click.echo(click.style(f"✗ 路径不存在: {source_path}", fg="red"))
        return

    image_files = _collect_images(source_path, config)

    if not image_files:
        click.echo(click.style("✗ 未找到图片文件", fg="yellow"))
        return

    if output is None:
        output_dir = project_root / "output" / "palettes" / theme
    else:
        output_dir = Path(output).resolve()

    if "all" in output_format:
        output_format = ["image", "css", "json", "text", "ase"]

    if preview:
        _show_preview(image_files, colors, quality, sort_by)
        return

    logger.start_session("palette")

    results = {
        "items": [],
        "summary": {
            "处理图片": len(image_files),
            "生成色板": 0,
            "总颜色数": 0,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    if merge:
        all_colors = []
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"分析 {len(image_files)} 张图片...", total=len(image_files))

            for img_path in image_files:
                try:
                    img_colors = _extract_colors(img_path, colors, quality)
                    all_colors.extend(img_colors)
                except Exception as e:
                    results["items"].append({
                        "name": img_path.name,
                        "type": "image",
                        "size": format_size(img_path.stat().st_size),
                        "status": "error",
                        "notes": str(e),
                    })
                progress.advance(task)

        merged_colors = _merge_colors(all_colors, colors, sort_by)
        palette_name = sanitize_filename(f"{theme}_merged")
        generated = _generate_palette_files(
            merged_colors, output_dir, palette_name,
            output_format, theme, copyright_text
        )

        results["items"].append({
            "name": f"{palette_name} (合并)",
            "type": "palette",
            "size": f"{len(merged_colors)} 种颜色",
            "status": "success",
            "notes": f"生成格式: {', '.join(generated)}",
        })
        results["summary"]["生成色板"] = 1
        results["summary"]["总颜色数"] = len(merged_colors)

        logger.log_action(
            "palette", str(source_path), str(output_dir),
            status="success",
            details=f"合并 {len(image_files)} 张图片，提取 {len(merged_colors)} 种颜色"
        )
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"处理 {len(image_files)} 张图片...", total=len(image_files))

            for img_path in image_files:
                try:
                    colors_list = _extract_colors(img_path, colors, quality)
                    colors_list = _sort_colors(colors_list, sort_by)

                    palette_name = sanitize_filename(img_path.stem)
                    generated = _generate_palette_files(
                        colors_list, output_dir, palette_name,
                        output_format, theme, copyright_text
                    )

                    results["items"].append({
                        "name": img_path.name,
                        "type": "image",
                        "size": format_size(img_path.stat().st_size),
                        "status": "success",
                        "notes": f"{len(colors_list)} 色, 格式: {', '.join(generated)}",
                    })
                    results["summary"]["生成色板"] += 1
                    results["summary"]["总颜色数"] += len(colors_list)

                    logger.log_action(
                        "palette", str(img_path), str(output_dir),
                        status="success",
                        details=f"提取 {len(colors_list)} 种颜色"
                    )
                except Exception as e:
                    results["items"].append({
                        "name": img_path.name,
                        "type": "image",
                        "size": format_size(img_path.stat().st_size),
                        "status": "error",
                        "notes": str(e),
                    })
                    logger.log_action(
                        "palette", str(img_path),
                        status="failed", details=str(e)
                    )

                progress.advance(task)

    logger.end_session()
    _show_results(results, output_dir)

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("palette", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


def _collect_images(source_path: Path, config) -> List[Path]:
    if source_path.is_file():
        ext = source_path.suffix.lower()
        if ext in config.image_formats and ext not in (".svg",):
            return [source_path]
        return []
    return get_files_by_extension(
        source_path,
        set(e for e in config.image_formats if e not in (".svg",)),
        True
    )


def _extract_colors(image_path: Path, num_colors: int, quality: str) -> List[Tuple[int, int, int, float]]:
    quality_map = {"fast": 100, "normal": 500, "best": 2000}
    max_colors = quality_map.get(quality, 500)

    colors = colorgram.extract(str(image_path), min(num_colors * 5, max_colors))

    result = []
    for c in colors[:num_colors]:
        result.append((c.rgb.r, c.rgb.g, c.rgb.b, c.proportion))

    return result


def _sort_colors(colors: List[Tuple[int, int, int, float]], sort_by: str) -> List:
    if sort_by == "frequency":
        return sorted(colors, key=lambda x: x[3], reverse=True)
    elif sort_by == "hue":
        return sorted(colors, key=lambda x: _rgb_to_hsl(x[0], x[1], x[2])[0])
    elif sort_by == "saturation":
        return sorted(colors, key=lambda x: _rgb_to_hsl(x[0], x[1], x[2])[1], reverse=True)
    elif sort_by == "luminance":
        return sorted(colors, key=lambda x: _rgb_to_hsl(x[0], x[1], x[2])[2], reverse=True)
    return colors


def _merge_colors(all_colors: List, num_colors: int, sort_by: str) -> List:
    color_map = {}
    total_weight = 0
    for r, g, b, weight in all_colors:
        key = (round(r / 10) * 10, round(g / 10) * 10, round(b / 10) * 10)
        if key in color_map:
            color_map[key] += weight
        else:
            color_map[key] = weight
        total_weight += weight

    sorted_colors = sorted(color_map.items(), key=lambda x: x[1], reverse=True)
    result = []
    for (r, g, b), weight in sorted_colors[:num_colors]:
        result.append((r, g, b, weight / total_weight if total_weight > 0 else 0))

    return _sort_colors(result, sort_by)


def _rgb_to_hsl(r: int, g: int, b: int) -> Tuple[float, float, float]:
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    max_val = max(r, g, b)
    min_val = min(r, g, b)
    h, s, l = 0, 0, (max_val + min_val) / 2

    if max_val != min_val:
        d = max_val - min_val
        s = d / (2 - max_val - min_val) if l > 0.5 else d / (max_val + min_val)
        if max_val == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif max_val == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6

    return (h, s, l)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02x}{g:02x}{b:02x}"


def _generate_palette_files(colors: List, output_dir: Path, name: str,
                            formats: List[str], theme: str,
                            copyright_text: str) -> List[str]:
    generated = []

    if "image" in formats:
        _generate_palette_image(colors, output_dir / f"{name}.png")
        generated.append("image")

    if "css" in formats:
        _generate_css_file(colors, output_dir / f"{name}.css", theme, copyright_text)
        generated.append("css")

    if "json" in formats:
        _generate_json_file(colors, output_dir / f"{name}.json", theme, copyright_text)
        generated.append("json")

    if "text" in formats:
        _generate_text_file(colors, output_dir / f"{name}.txt", theme, copyright_text)
        generated.append("text")

    if "ase" in formats:
        _generate_ase_file(colors, output_dir / f"{name}.ase", theme)
        generated.append("ase")

    return generated


def _generate_palette_image(colors: List, output_path: Path):
    num_colors = len(colors)
    swatch_width = 200
    swatch_height = 120
    padding = 20
    text_height = 40

    img_width = swatch_width * num_colors + padding * (num_colors + 1)
    img_height = swatch_height + padding * 2 + text_height

    from PIL import ImageDraw, ImageFont
    img = Image.new("RGB", (img_width, img_height), "white")
    draw = ImageDraw.Draw(img)

    for i, (r, g, b, proportion) in enumerate(colors):
        x = padding + i * (swatch_width + padding)
        y = padding

        draw.rectangle([x, y, x + swatch_width, y + swatch_height], fill=(r, g, b))

        hex_color = _rgb_to_hex(r, g, b)
        text_y = y + swatch_height + 10

        text_color = "white" if (r + g + b) / 3 < 128 else "black"
        draw.rectangle([x, y + swatch_height - 25, x + swatch_width, y + swatch_height],
                       fill=(r, g, b))

        try:
            font = ImageFont.truetype("arial.ttf", 12)
        except Exception:
            font = ImageFont.load_default()

        draw.text((x + 10, y + swatch_height - 22), hex_color, fill=text_color, font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)


def _generate_css_file(colors: List, output_path: Path, theme: str, copyright_text: str):
    lines = []
    if copyright_text:
        lines.append(f"/* {copyright_text} */")
        lines.append("")
    lines.append(f"/* Palette: {theme} */")
    lines.append(":root {")
    for i, (r, g, b, proportion) in enumerate(colors):
        hex_color = _rgb_to_hex(r, g, b)
        lines.append(f"  --color-primary-{i + 1}: {hex_color};")
        lines.append(f"  --color-primary-{i + 1}-rgb: {r}, {g}, {b};")
    lines.append("}")
    lines.append("")
    lines.append(f".palette-{theme} {{")
    for i, (r, g, b, proportion) in enumerate(colors):
        hex_color = _rgb_to_hex(r, g, b)
        lines.append(f"  --color-{i + 1}: {hex_color};")
    lines.append("}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_json_file(colors: List, output_path: Path, theme: str, copyright_text: str):
    data = {
        "theme": theme,
        "copyright": copyright_text,
        "colors": [],
    }
    for i, (r, g, b, proportion) in enumerate(colors):
        data["colors"].append({
            "name": f"color-{i + 1}",
            "hex": _rgb_to_hex(r, g, b),
            "rgb": {"r": r, "g": g, "b": b},
            "hsl": {"h": round(c * 360) for c in _rgb_to_hsl(r, g, b)},
            "proportion": round(proportion, 4),
        })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _generate_text_file(colors: List, output_path: Path, theme: str, copyright_text: str):
    lines = []
    if copyright_text:
        lines.append(f"# {copyright_text}")
        lines.append("")
    lines.append(f"# Palette: {theme}")
    lines.append(f"# Total colors: {len(colors)}")
    lines.append("")
    lines.append(f"{'#':<4} {'HEX':<10} {'RGB':<15} {'Proportion':>10}")
    lines.append("-" * 45)

    for i, (r, g, b, proportion) in enumerate(colors):
        hex_color = _rgb_to_hex(r, g, b)
        rgb_str = f"({r:3d}, {g:3d}, {b:3d})"
        lines.append(f"{i + 1:<4} {hex_color:<10} {rgb_str:<15} {proportion:>10.2%}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _generate_ase_file(colors: List, output_path: Path, theme: str):
    import struct

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "wb") as f:
        f.write(b"ASEF")
        f.write(struct.pack(">H", 1))
        f.write(struct.pack(">H", 0))

        num_blocks = len(colors) + 1
        f.write(struct.pack(">I", num_blocks))

        group_name = theme.encode("utf-16-be") + b"\x00\x00"
        group_name_len = len(group_name) // 2
        f.write(struct.pack(">H", 0xC001))
        f.write(struct.pack(">I", 2 + group_name_len * 2))
        f.write(struct.pack(">H", group_name_len))
        f.write(group_name)

        for i, (r, g, b, _) in enumerate(colors):
            name = f"Color {i + 1}".encode("utf-16-be") + b"\x00\x00"
            name_len = len(name) // 2

            f.write(struct.pack(">H", 0x0001))
            block_len = 2 + name_len * 2 + 4 * 3 + 2
            f.write(struct.pack(">I", block_len))
            f.write(struct.pack(">H", name_len))
            f.write(name)

            f.write(b"RGB ")
            f.write(struct.pack(">f", r / 255.0))
            f.write(struct.pack(">f", g / 255.0))
            f.write(struct.pack(">f", b / 255.0))
            f.write(struct.pack(">H", 0))


def _show_preview(image_files: List[Path], num_colors: int, quality: str, sort_by: str):
    click.echo(click.style(f"色板预览 - {len(image_files)} 张图片", fg="cyan", bold=True))
    click.echo()

    for img_path in image_files[:5]:
        try:
            colors = _extract_colors(img_path, num_colors, quality)
            colors = _sort_colors(colors, sort_by)

            click.echo(f"📷 {img_path.name}")
            color_bar = ""
            for r, g, b, _ in colors:
                hex_color = _rgb_to_hex(r, g, b)
                color_bar += f"  [{hex_color}]███[/]"
            console.print(color_bar)

            for i, (r, g, b, proportion) in enumerate(colors):
                hex_color = _rgb_to_hex(r, g, b)
                click.echo(f"  {i + 1:2d}. {hex_color}  ({r:3d}, {g:3d}, {b:3d})  {proportion:.1%}")
            click.echo()
        except Exception as e:
            click.echo(f"  ✗ 处理失败: {e}")
            click.echo()

    if len(image_files) > 5:
        click.echo(f"... 还有 {len(image_files) - 5} 张图片")

    click.echo(click.style("\n预览模式 - 不会生成文件", fg="yellow"))


def _show_results(results: dict, output_dir: Path):
    click.echo()
    table = Table(title="色板生成结果")
    table.add_column("统计项", style="cyan")
    table.add_column("数量", style="green", justify="right")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)
    click.echo(f"\n输出目录: {output_dir}")

    success_count = results["summary"].get("生成色板", 0)
    if success_count > 0:
        click.echo(click.style(f"\n✓ 成功生成 {success_count} 个色板", fg="green"))
    else:
        click.echo(click.style("\n✗ 没有生成色板", fg="yellow"))
