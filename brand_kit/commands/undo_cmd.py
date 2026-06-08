from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from brand_kit.cli import pass_brand
from brand_kit.logger import Logger
from brand_kit.utils import format_size

console = Console()


@click.group("undo")
def undo_cmd():
    """撤销上次操作（重命名、导入等）"""
    pass


@undo_cmd.command("rename")
@click.option("--preview", is_flag=True, help="预览模式，只显示将撤销的操作")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def undo_rename(brand, preview, report):
    """撤销上次重命名操作"""
    project_root = brand["project_root"]
    logger = brand["logger"]

    from brand_kit.commands.rename_cmd import load_last_rename, undo_last_rename

    last_rename = load_last_rename(project_root)

    if not last_rename:
        click.echo(click.style("✗ 没有找到上次重命名记录", fg="yellow"))
        return

    files = last_rename.get("files", [])
    timestamp = last_rename.get("timestamp", "未知时间")

    if preview:
        _show_rename_preview(files, timestamp)
        return

    logger.start_session("undo_rename")

    results = {
        "items": [],
        "summary": {
            "原操作文件数": len(files),
            "撤销成功": 0,
            "撤销失败": 0,
        },
    }

    success, msg = undo_last_rename(project_root, logger, results)

    logger.end_session()

    _show_undo_results(results, "重命名")

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("undo_rename", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


@undo_cmd.command("import")
@click.option("--preview", is_flag=True, help="预览模式，只显示将撤销的操作")
@click.option("--report", is_flag=True, help="生成复核报告")
@pass_brand
def undo_import(brand, preview, report):
    """撤销上次导入操作"""
    project_root = brand["project_root"]
    logger = brand["logger"]

    from brand_kit.commands.import_cmd import load_last_import, undo_last_import

    last_import = load_last_import(project_root)

    if not last_import:
        click.echo(click.style("✗ 没有找到上次导入记录", fg="yellow"))
        return

    files = last_import.get("files", [])
    timestamp = last_import.get("timestamp", "未知时间")

    if preview:
        _show_import_preview(files, timestamp)
        return

    if not click.confirm(
        f"\n确认要撤销上次导入的 {len(files)} 个文件吗？\n"
        "这些文件将被移至回收站，此操作不可撤销。",
        default=False
    ):
        click.echo(click.style("已取消撤销操作", fg="cyan"))
        return

    logger.start_session("undo_import")

    results = {
        "items": [],
        "summary": {
            "原操作文件数": len(files),
            "撤销成功": 0,
            "撤销失败": 0,
        },
    }

    success, msg = undo_last_import(project_root, logger, results)

    logger.end_session()

    _show_undo_results(results, "导入")

    if report:
        reporter = brand["reporter"]
        report_path = reporter.generate_review_report("undo_import", results)
        click.echo(click.style(f"\n报告已生成: {report_path}", fg="green"))


@undo_cmd.command("list")
@pass_brand
def undo_list(brand):
    """查看可撤销的操作记录"""
    project_root = brand["project_root"]

    from brand_kit.commands.rename_cmd import load_last_rename
    from brand_kit.commands.import_cmd import load_last_import

    table = Table(title="可撤销操作")
    table.add_column("操作类型", style="cyan")
    table.add_column("时间", style="green")
    table.add_column("文件数", style="yellow", justify="right")
    table.add_column("状态", style="magenta")

    last_rename = load_last_rename(project_root)
    if last_rename:
        table.add_row(
            "重命名",
            last_rename.get("timestamp", "-"),
            str(len(last_rename.get("files", []))),
            "可撤销",
        )
    else:
        table.add_row("重命名", "-", "0", "无记录")

    last_import = load_last_import(project_root)
    if last_import:
        table.add_row(
            "导入",
            last_import.get("timestamp", "-"),
            str(len(last_import.get("files", []))),
            "可撤销",
        )
    else:
        table.add_row("导入", "-", "0", "无记录")

    console.print(table)


def _show_rename_preview(files: list, timestamp: str):
    table = Table(title=f"撤销重命名预览 - {len(files)} 个文件")
    table.add_column("#", style="yellow", width=4)
    table.add_column("当前名称", style="cyan", overflow="fold")
    table.add_column("还原为", style="green", overflow="fold")

    for i, item in enumerate(files[:20], 1):
        table.add_row(str(i), Path(item["new"]).name, Path(item["old"]).name)

    if len(files) > 20:
        table.add_row("...", f"... 还有 {len(files) - 20} 个文件", "")

    console.print(table)
    click.echo(f"\n操作时间: {timestamp}")
    click.echo(click.style("\n预览模式 - 不会实际撤销", fg="yellow"))


def _show_import_preview(files: list, timestamp: str):
    table = Table(title=f"撤销导入预览 - {len(files)} 个文件将被删除")
    table.add_column("#", style="yellow", width=4)
    table.add_column("文件路径", style="cyan", overflow="fold")
    table.add_column("大小", style="green")

    for i, item in enumerate(files[:20], 1):
        target = Path(item["target"])
        size = format_size(target.stat().st_size) if target.exists() else "N/A"
        table.add_row(str(i), str(target), size)

    if len(files) > 20:
        table.add_row("...", f"... 还有 {len(files) - 20} 个文件", "")

    console.print(table)
    click.echo(f"\n操作时间: {timestamp}")
    click.echo(click.style("\n预览模式 - 不会实际删除文件", fg="yellow"))


def _show_undo_results(results: dict, op_name: str):
    click.echo()
    table = Table(title=f"撤销{op_name}结果")
    table.add_column("统计项", style="cyan")
    table.add_column("数量", style="green", justify="right")

    for key, value in results["summary"].items():
        table.add_row(key, str(value))

    console.print(table)

    success_count = results["summary"].get("撤销成功", 0)
    if success_count > 0:
        click.echo(click.style(f"\n✓ 成功撤销 {success_count} 个{op_name}", fg="green"))
    else:
        click.echo(click.style(f"\n✗ 没有成功撤销任何{op_name}", fg="yellow"))
