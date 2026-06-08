import os
import zipfile
import json
import csv
from pathlib import Path
from datetime import datetime
from typing import List, Dict

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from brand_kit.cli import pass_brand
from brand_kit.utils import (
    get_files_by_extension,
    format_size,
    sanitize_filename,
)

console = Console()


MANIFEST_TEMPLATE = """# 交付清单

**项目名称**: {project_name}
**生成时间**: {generated_at}
**主题**: {theme}
**版权**: {copyright}

## 文件统计

- 总文件数: {total_files}
- 总大小: {total_size}
- 图片文件: {image_count}
- 字体文件: {font_count}
- 图标文件: {icon_count}
- 其他文件: {other_count}

## 目录结构

```
{tree_structure}
```

## 文件清单

{file_list}
"""


@click.command("pack")
@click.argument("source", type=click.Path(exists=True, file_okay=True, dir_okay=True), required=False)
@click.option("--output", "-o", default=None, help="输出目录")
@click.option("--name", "-n", default=None, help="交付包名称")
@click.option("--format", "pack_format", default="zip",
              type=click.Choice(["zip", "tar", "dir"]),
              help="打包格式")
@click.option("--theme", default="default", help="主题名称")
@click.option("--type", "file_type", default="all",
              type=click.Choice(["image", "font", "icon", "all"]),
              help="文件类型")
@click.option("--manifest/--no-manifest", default=True, help="生成清单文件")
@click.option("--manifest-format", default="markdown",
              type=click.Choice(["markdown", "json", "csv", "txt"]),
              help="清单格式")
@click.option("--copyright", "copyright_text", default="", help="版权说明")
@click.option("--include-config", is_flag=True, help="包含配置文件")
@click.option("--include-readme/--no-include-readme", default=True, help="包含README")
@click.option("--preview", is_flag=True, help="预览模式")
@click.option("--overwrite", is_flag=True, help="覆盖已存在文件")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def pack_cmd(brand, source, output, name, pack_format, theme, file_type,
             manifest, manifest_format, copyright_text, include_config,
             include_readme, preview, overwrite, report):
    """生成交付包和清单"""
    project_root = brand["project_root"]
    config = brand["config"]
    logger = brand["logger"]

    if source is None:
        source = project_root / "assets"

    source_path = Path(source).resolve()

    if not source_path.exists():
        click.echo(click.style(f"✗ 源路径不存在: {source_path}", fg="red"))
        return

    if output is None:
        output_dir = project_root / "output" / "delivery"
    else:
        output_dir = Path(output).resolve()

    package_name = name or f"{config.project_name}_{theme}_{datetime.now().strftime('%Y%m%d')}"
    package_name = sanitize_filename(package_name)

    files, file_counts = _collect_files(source_path, file_type, config, theme)

    if not files:
        click.echo(click.style("✗ 未找到可打包的文件", fg="yellow"))
        return

    total_size = sum(f.stat().st_size for f in files)

    if preview:
        _show_preview(files, file_counts, total_size, package_name, pack_format, output_dir)
        return

    logger.start_session("pack")

    results = {
        "items": [],
        "summary": {
            "文件总数": len(files),
            "图片": file_counts.get("image", 0),
            "字体": file_counts.get("font", 0),
            "图标": file_counts.get("icon", 0),
            "总大小": format_size(total_size),
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)

    if pack_format == "dir":
        package_path = output_dir / package_name
        _pack_to_directory(files, source_path, package_path, overwrite,
                          manifest, manifest_format, config, theme,
                          copyright_text, include_config, include_readme,
                          results, logger)
    elif pack_format == "tar":
        package_path = output_dir / f"{package_name}.tar.gz"
        _pack_to_tar(files, source_path, package_path, overwrite,
                    manifest, manifest_format, config, theme,
                    copyright_text, include_config, include_readme,
                    results, logger)
    else:
        package_path = output_dir / f"{package_name}.zip"
        _pack_to_zip(files, source_path, package_path, overwrite,
                    manifest, manifest_format, config, theme,
                    copyright_text, include_config, include_readme,
                    results, logger)

    if package_path.exists():
        if pack_format != "dir":
            pkg_size = format_size(package_path.stat().st_size)
        else:
            pkg_size = format_size(total_size)
        results["summary"]["交付包大小"] = pkg_size

    logger.end_session()
    _show_results(results, package_path)

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("pack", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


def _collect_files(source_path: Path, file_type: str, config, theme: str) -> tuple:
    files = []
    counts = {"image": 0, "font": 0, "icon": 0, "other": 0}

    extensions = set()
    if file_type in ("image", "all"):
        extensions.update(config.image_formats)
    if file_type in ("font", "all"):
        extensions.update(config.font_formats)
    if file_type in ("icon", "all"):
        extensions.update(config.icon_formats)

    if source_path.is_file():
        return [source_path], {}

    for root, _, filenames in os.walk(source_path):
        for filename in filenames:
            fpath = Path(root) / filename
            ext = fpath.suffix.lower()

            if file_type != "all" and ext not in extensions:
                continue

            if theme and theme != "default":
                rel = fpath.relative_to(source_path)
                if theme not in str(rel):
                    continue

            files.append(fpath)

            if ext in config.image_formats and ext not in config.icon_formats:
                counts["image"] += 1
            elif ext in config.font_formats:
                counts["font"] += 1
            elif ext in config.icon_formats:
                counts["icon"] += 1
            else:
                counts["other"] += 1

    return sorted(files), counts


def _generate_manifest(files: List[Path], source_path: Path, config, theme: str,
                       copyright_text: str, fmt: str) -> str:
    total_size = sum(f.stat().st_size for f in files)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    image_count = sum(1 for f in files if f.suffix.lower() in config.image_formats)
    font_count = sum(1 for f in files if f.suffix.lower() in config.font_formats)
    icon_count = sum(1 for f in files if f.suffix.lower() in config.icon_formats)
    other_count = len(files) - image_count - font_count - icon_count

    if fmt == "json":
        data = {
            "project_name": config.project_name,
            "generated_at": generated_at,
            "theme": theme,
            "copyright": copyright_text,
            "stats": {
                "total_files": len(files),
                "total_size": total_size,
                "image_count": image_count,
                "font_count": font_count,
                "icon_count": icon_count,
                "other_count": other_count,
            },
            "files": [],
        }
        for f in files:
            rel_path = f.relative_to(source_path) if f.is_relative_to(source_path) else f.name
            data["files"].append({
                "path": str(rel_path),
                "size": f.stat().st_size,
                "type": f.suffix.lstrip("."),
            })
        return json.dumps(data, indent=2, ensure_ascii=False)

    elif fmt == "csv":
        lines = ["路径,大小(字节),类型"]
        for f in files:
            rel_path = f.relative_to(source_path) if f.is_relative_to(source_path) else f.name
            lines.append(f'"{rel_path}",{f.stat().st_size},{f.suffix.lstrip(".")}')
        return "\n".join(lines)

    elif fmt == "txt":
        lines = []
        lines.append(f"项目: {config.project_name}")
        lines.append(f"生成时间: {generated_at}")
        lines.append(f"主题: {theme}")
        lines.append("-" * 50)
        lines.append(f"{'文件':<40} {'大小':>12}")
        lines.append("-" * 50)
        for f in files:
            rel_path = f.relative_to(source_path) if f.is_relative_to(source_path) else f.name
            lines.append(f"{str(rel_path):<40} {format_size(f.stat().st_size):>12}")
        lines.append("-" * 50)
        lines.append(f"{'总计':<40} {format_size(total_size):>12}")
        return "\n".join(lines)

    else:
        tree_str = _generate_tree(files, source_path)
        file_list_str = _generate_file_list(files, source_path)

        return MANIFEST_TEMPLATE.format(
            project_name=config.project_name,
            generated_at=generated_at,
            theme=theme,
            copyright=copyright_text or "无",
            total_files=len(files),
            total_size=format_size(total_size),
            image_count=image_count,
            font_count=font_count,
            icon_count=icon_count,
            other_count=other_count,
            tree_structure=tree_str,
            file_list=file_list_str,
        )


def _generate_tree(files: List[Path], source_path: Path) -> str:
    tree = {}
    for f in files:
        try:
            rel = f.relative_to(source_path)
        except ValueError:
            rel = Path(f.name)
        parts = rel.parts
        current = tree
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = None

    lines = []
    _render_tree(tree, "", lines)
    return "\n".join(lines)


def _render_tree(node: dict, prefix: str, lines: List[str]):
    items = sorted(node.items())
    for i, (name, children) in enumerate(items):
        is_last = i == len(items) - 1
        connector = "└── " if is_last else "├── "
        lines.append(f"{prefix}{connector}{name}")
        if children is not None:
            extension = "    " if is_last else "│   "
            _render_tree(children, prefix + extension, lines)


def _generate_file_list(files: List[Path], source_path: Path) -> str:
    lines = []
    lines.append("| # | 文件名 | 类型 | 大小 |")
    lines.append("|---|--------|------|------|")
    for i, f in enumerate(files, 1):
        try:
            rel = f.relative_to(source_path)
        except ValueError:
            rel = Path(f.name)
        lines.append(f"| {i} | {rel} | {f.suffix.lstrip('.')} | {format_size(f.stat().st_size)} |")
    return "\n".join(lines)


def _pack_to_zip(files: List[Path], source_path: Path, output_path: Path,
                 overwrite: bool, manifest: bool, manifest_fmt: str, config,
                 theme: str, copyright_text: str, include_config: bool,
                 include_readme: bool, results: dict, logger):
    if output_path.exists():
        if not overwrite:
            click.echo(click.style(f"✗ 交付包已存在: {output_path}", fg="red"))
            return
        output_path.unlink()

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"打包 {len(files)} 个文件...", total=len(files))

            for f in files:
                try:
                    rel_path = f.relative_to(source_path) if f.is_relative_to(source_path) else f.name
                    zf.write(f, rel_path)

                    results["items"].append({
                        "name": str(rel_path),
                        "type": f.suffix.lstrip("."),
                        "size": format_size(f.stat().st_size),
                        "status": "success",
                        "notes": "已添加到交付包",
                    })
                    logger.log_action("pack", str(f), str(rel_path), status="success")
                except Exception as e:
                    results["items"].append({
                        "name": f.name,
                        "type": f.suffix.lstrip("."),
                        "size": format_size(f.stat().st_size),
                        "status": "error",
                        "notes": str(e),
                    })
                    logger.log_action("pack", str(f), status="failed", details=str(e))

                progress.advance(task)

            if manifest:
                manifest_content = _generate_manifest(files, source_path, config, theme,
                                                     copyright_text, manifest_fmt)
                manifest_name = f"manifest.{manifest_fmt if manifest_fmt != 'markdown' else 'md'}"
                zf.writestr(manifest_name, manifest_content)

            if include_config:
                config_path = source_path.parent / ".brand-kit" / "config.json"
                if config_path.exists():
                    zf.write(config_path, "config.json")

            if include_readme:
                readme_path = source_path.parent / "README.md"
                if readme_path.exists():
                    zf.write(readme_path, "README.md")


def _pack_to_directory(files: List[Path], source_path: Path, output_dir: Path,
                       overwrite: bool, manifest: bool, manifest_fmt: str, config,
                       theme: str, copyright_text: str, include_config: bool,
                       include_readme: bool, results: dict, logger):
    import shutil

    if output_dir.exists():
        if not overwrite:
            click.echo(click.style(f"✗ 目标目录已存在: {output_dir}", fg="red"))
            return
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"复制 {len(files)} 个文件...", total=len(files))

        for f in files:
            try:
                rel_path = f.relative_to(source_path) if f.is_relative_to(source_path) else Path(f.name)
                dest = output_dir / rel_path
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dest)

                results["items"].append({
                    "name": str(rel_path),
                    "type": f.suffix.lstrip("."),
                    "size": format_size(f.stat().st_size),
                    "status": "success",
                    "notes": "已复制",
                })
                logger.log_action("pack", str(f), str(dest), status="success")
            except Exception as e:
                results["items"].append({
                    "name": f.name,
                    "type": f.suffix.lstrip("."),
                    "size": format_size(f.stat().st_size),
                    "status": "error",
                    "notes": str(e),
                })
                logger.log_action("pack", str(f), status="failed", details=str(e))

            progress.advance(task)

        if manifest:
            manifest_content = _generate_manifest(files, source_path, config, theme,
                                                 copyright_text, manifest_fmt)
            manifest_name = f"manifest.{manifest_fmt if manifest_fmt != 'markdown' else 'md'}"
            with open(output_dir / manifest_name, "w", encoding="utf-8") as f:
                f.write(manifest_content)

        if include_config:
            config_path = source_path.parent / ".brand-kit" / "config.json"
            if config_path.exists():
                shutil.copy2(config_path, output_dir / "config.json")

        if include_readme:
            readme_path = source_path.parent / "README.md"
            if readme_path.exists():
                shutil.copy2(readme_path, output_dir / "README.md")


def _pack_to_tar(files: List[Path], source_path: Path, output_path: Path,
                 overwrite: bool, manifest: bool, manifest_fmt: str, config,
                 theme: str, copyright_text: str, include_config: bool,
                 include_readme: bool, results: dict, logger):
    import tarfile
    import tempfile
    import shutil

    if output_path.exists():
        if not overwrite:
            click.echo(click.style(f"✗ 交付包已存在: {output_path}", fg="red"))
            return
        output_path.unlink()

    with tarfile.open(output_path, "w:gz") as tar:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"打包 {len(files)} 个文件...", total=len(files))

            for f in files:
                try:
                    rel_path = f.relative_to(source_path) if f.is_relative_to(source_path) else f.name
                    tar.add(f, arcname=str(rel_path))

                    results["items"].append({
                        "name": str(rel_path),
                        "type": f.suffix.lstrip("."),
                        "size": format_size(f.stat().st_size),
                        "status": "success",
                        "notes": "已添加到交付包",
                    })
                    logger.log_action("pack", str(f), str(rel_path), status="success")
                except Exception as e:
                    results["items"].append({
                        "name": f.name,
                        "type": f.suffix.lstrip("."),
                        "size": format_size(f.stat().st_size),
                        "status": "error",
                        "notes": str(e),
                    })
                    logger.log_action("pack", str(f), status="failed", details=str(e))

                progress.advance(task)

            if manifest:
                manifest_content = _generate_manifest(files, source_path, config, theme,
                                                     copyright_text, manifest_fmt)
                manifest_name = f"manifest.{manifest_fmt if manifest_fmt != 'markdown' else 'md'}"

                with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=manifest_fmt) as tmp:
                    tmp.write(manifest_content)
                    tmp_path = tmp.name

                tar.add(tmp_path, arcname=manifest_name)
                os.unlink(tmp_path)


def _show_preview(files: List[Path], counts: dict, total_size: int,
                  package_name: str, pack_format: str, output_dir: Path):
    table = Table(title="打包预览")
    table.add_column("项目", style="cyan")
    table.add_column("内容", style="green")

    table.add_row("交付包名称", package_name)
    table.add_row("打包格式", pack_format)
    table.add_row("文件总数", str(len(files)))
    table.add_row("总大小", format_size(total_size))
    table.add_row("图片文件", str(counts.get("image", 0)))
    table.add_row("字体文件", str(counts.get("font", 0)))
    table.add_row("图标文件", str(counts.get("icon", 0)))
    table.add_row("输出目录", str(output_dir))

    console.print(table)

    if len(files) <= 20:
        click.echo("\n文件列表:")
        for f in files:
            click.echo(f"  - {f.name} ({format_size(f.stat().st_size)})")
    else:
        click.echo(f"\n包含 {len(files)} 个文件")

    click.echo(click.style("\n预览模式 - 不会实际生成交付包", fg="yellow"))


def _show_results(results: dict, package_path: Path):
    click.echo()
    table = Table(title="打包结果")
    table.add_column("统计项", style="cyan")
    table.add_column("内容", style="green")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)
    click.echo(f"\n交付包位置: {package_path}")

    success = sum(1 for item in results["items"] if item["status"] == "success")
    if success > 0:
        click.echo(click.style(f"\n✓ 成功打包 {success} 个文件", fg="green"))
    else:
        click.echo(click.style("\n✗ 打包失败", fg="red"))
