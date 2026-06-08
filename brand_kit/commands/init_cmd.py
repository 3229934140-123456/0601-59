import os
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from brand_kit.config import ConfigManager, ProjectConfig, get_project_dir
from brand_kit.logger import Logger

console = Console()


PROJECT_DIRS = [
    "source/images",
    "source/fonts",
    "source/icons",
    "source/raw",
    "assets/images",
    "assets/fonts",
    "assets/icons",
    "output/resized",
    "output/palettes",
    "output/delivery",
    ".brand-kit/logs",
    ".brand-kit/reports",
    ".brand-kit/cache",
]


README_TEMPLATE = """# {project_name}

品牌素材项目 - 由 Brand Kit 工具初始化

## 目录结构

```
{project_name}/
├── source/              # 原始素材源文件
│   ├── images/          # 原始图片
│   ├── fonts/           # 字体文件
│   ├── icons/           # 图标源文件
│   └── raw/             # 原始未处理文件
├── assets/              # 整理后的资产文件
│   ├── images/          # 整理后的图片
│   ├── fonts/           # 整理后的字体
│   └── icons/           # 整理后的图标
├── output/              # 输出文件
│   ├── resized/         # 多尺寸输出
│   ├── palettes/        # 色板文件
│   └── delivery/        # 最终交付包
└── .brand-kit/          # 工具内部文件
    ├── config.json      # 项目配置
    ├── logs/            # 操作日志
    ├── reports/         # 报告文件
    └── cache/           # 缓存文件
```

## 可用命令

- `brand-kit init`    - 初始化项目
- `brand-kit import`  - 导入图片、字体和图标
- `brand-kit rename`  - 按规则重命名文件
- `brand-kit palette` - 提取主色并生成色板
- `brand-kit resize`  - 批量输出多尺寸
- `brand-kit check`   - 检查素材质量
- `brand-kit pack`    - 生成交付包和清单
"""

NAMESPEC_TEMPLATE = """# {project_name} 命名规范

## 命名规则

- 使用小写字母和下划线 (snake_case)
- 格式: `{{theme}}_{{name}}_{{index:03d}}.{{ext}}`
- 示例: `hero_banner_001.jpg`

## 主题分类

{themes_list}

## 文件格式规范

### 图片
- 支持格式: {image_formats}
- 推荐格式: PNG (透明背景), JPG (照片), WebP (网页)
- 最小分辨率: {min_resolution}

### 字体
- 支持格式: {font_formats}
- 推荐格式: WOFF2, TTF

### 图标
- 支持格式: {icon_formats}
- 推荐格式: SVG (矢量), PNG (位图)
"""


@click.command("init")
@click.argument("project_name", required=False)
@click.option("--path", "-p", default=".", help="项目路径")
@click.option("--template", "-t", default="default",
              type=click.Choice(["default", "minimal", "full"]),
              help="项目模板")
@click.option("--force", "-f", is_flag=True, help="强制覆盖已有项目")
@click.option("--preview", is_flag=True, help="预览模式，不实际创建文件")
def init_cmd(project_name, path, template, force, preview):
    """初始化品牌素材项目，创建目录结构和规范文件"""
    project_dir = get_project_dir(path)

    if project_name is None:
        project_name = project_dir.name or "brand-project"

    config_file = project_dir / ".brand-kit" / "config.json"
    if config_file.exists() and not force:
        click.echo(click.style("✗ 项目已存在，使用 --force 强制重新初始化", fg="red"))
        return

    config = ProjectConfig(project_name=project_name)

    if preview:
        _show_preview(project_dir, config, template)
        return

    _create_project(project_dir, config, template, force)
    click.echo(click.style(f"✓ 项目 '{project_name}' 初始化成功", fg="green"))
    click.echo(f"  位置: {project_dir}")
    click.echo(f"  模板: {template}")


def _show_preview(project_dir: Path, config: ProjectConfig, template: str):
    table = Table(title=f"项目预览: {config.project_name}")
    table.add_column("目录", style="cyan")
    table.add_column("说明", style="green")

    dirs_to_create = _get_dirs_for_template(template)
    for d in dirs_to_create:
        table.add_row(d, _get_dir_description(d))

    console.print(table)
    click.echo(click.style("\n预览模式 - 不会创建任何文件", fg="yellow"))


def _get_dirs_for_template(template: str) -> list:
    if template == "minimal":
        return [
            "source/images",
            "source/fonts",
            "source/icons",
            "assets/images",
            "assets/fonts",
            "assets/icons",
            "output/delivery",
            ".brand-kit/logs",
            ".brand-kit/reports",
        ]
    elif template == "full":
        return PROJECT_DIRS + [
            "source/videos",
            "source/audio",
            "assets/videos",
            "assets/audio",
            "output/exports",
            "docs",
        ]
    else:
        return PROJECT_DIRS


def _get_dir_description(dir_path: str) -> str:
    descriptions = {
        "source": "原始素材源文件",
        "source/images": "原始图片素材",
        "source/fonts": "原始字体文件",
        "source/icons": "原始图标文件",
        "source/raw": "未处理的原始文件",
        "assets": "整理后的资产文件",
        "assets/images": "整理后的图片",
        "assets/fonts": "整理后的字体",
        "assets/icons": "整理后的图标",
        "output": "输出文件目录",
        "output/resized": "多尺寸调整输出",
        "output/palettes": "色板输出文件",
        "output/delivery": "最终交付包",
        ".brand-kit": "工具内部数据",
        ".brand-kit/logs": "操作日志记录",
        ".brand-kit/reports": "复核报告输出",
        ".brand-kit/cache": "缓存文件",
    }
    return descriptions.get(dir_path, "")


def _create_project(project_dir: Path, config: ProjectConfig, template: str, force: bool):
    dirs = _get_dirs_for_template(template)

    for d in dirs:
        dir_path = project_dir / d
        dir_path.mkdir(parents=True, exist_ok=True)

    config_mgr = ConfigManager(project_dir)
    config_mgr.save(config)

    readme_content = README_TEMPLATE.format(project_name=config.project_name)
    with open(project_dir / "README.md", "w", encoding="utf-8") as f:
        f.write(readme_content)

    themes_list = "\n".join([f"- {t}" for t in config.themes])
    namespec_content = NAMESPEC_TEMPLATE.format(
        project_name=config.project_name,
        themes_list=themes_list,
        image_formats=", ".join(config.image_formats),
        font_formats=", ".join(config.font_formats),
        icon_formats=", ".join(config.icon_formats),
        min_resolution=f"{config.min_resolution[0]}x{config.min_resolution[1]}",
    )
    with open(project_dir / "NAMING_SPEC.md", "w", encoding="utf-8") as f:
        f.write(namespec_content)

    with open(project_dir / ".gitignore", "w", encoding="utf-8") as f:
        f.write(".brand-kit/cache/\n")
        f.write(".DS_Store\n")
        f.write("*.log\n")

    logger = Logger(project_dir)
    logger.start_session("init")
    logger.log_action("init", str(project_dir), status="success",
                      details=f"项目 '{config.project_name}' 初始化完成，模板: {template}")
    logger.end_session()
