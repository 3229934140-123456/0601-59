import os
import sys
from pathlib import Path

import click
from rich.console import Console

from brand_kit.config import find_project_root, get_project_dir, ConfigManager
from brand_kit.logger import Logger
from brand_kit.report import ReportGenerator

console = Console()


def get_context_objs(ctx: click.Context):
    project_root = find_project_root()
    if project_root is None:
        project_root = Path.cwd()
    config_mgr = ConfigManager(project_root)
    logger = Logger(project_root)
    reporter = ReportGenerator(project_root)
    return {
        "project_root": project_root,
        "config_mgr": config_mgr,
        "config": config_mgr.config,
        "logger": logger,
        "reporter": reporter,
    }


pass_brand = click.make_pass_decorator(dict, ensure=True)


@click.group(invoke_without_command=True)
@click.version_option(version="1.0.0", prog_name="brand-kit")
@click.pass_context
def main(ctx):
    """创意设计平台命令行工具 - 批量整理品牌素材"""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
    else:
        ctx.obj = get_context_objs(ctx)


def register_commands():
    from brand_kit.commands.init_cmd import init_cmd
    from brand_kit.commands.import_cmd import import_cmd
    from brand_kit.commands.rename_cmd import rename_cmd
    from brand_kit.commands.palette_cmd import palette_cmd
    from brand_kit.commands.resize_cmd import resize_cmd
    from brand_kit.commands.check_cmd import check_cmd
    from brand_kit.commands.pack_cmd import pack_cmd
    from brand_kit.commands.undo_cmd import undo_cmd

    main.add_command(init_cmd)
    main.add_command(import_cmd)
    main.add_command(rename_cmd)
    main.add_command(palette_cmd)
    main.add_command(resize_cmd)
    main.add_command(check_cmd)
    main.add_command(pack_cmd)
    main.add_command(undo_cmd)


register_commands()


if __name__ == "__main__":
    main()
