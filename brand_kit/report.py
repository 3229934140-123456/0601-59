import os
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional


STATUS_LABELS = {
    "generated": "\u65b0\u589e",
    "overwritten": "\u8986\u76d6",
    "skipped": "\u8df3\u8fc7",
    "failed": "\u5931\u8d25",
    "success": "\u6210\u529f",
    "error": "\u9519\u8bef",
}


def _get_status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


class ReportGenerator:
    def __init__(self, project_dir: Path):
        self.project_dir = Path(project_dir)
        self.report_dir = self.project_dir / ".brand-kit" / "reports"

    def generate_review_report(self, command: str, results: Dict[str, Any],
                               output_file: Optional[str] = None) -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = f"review_{command}_{timestamp}.html"
        report_path = self.report_dir / output_file
        html = self._render_html(command, results)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)
        return report_path

    def _render_html(self, command: str, results: Dict[str, Any]) -> str:
        summary = results.get("summary", {})
        items = results.get("items", [])
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        summary_html = ""
        for key, value in summary.items():
            summary_html += f"<div class='summary-item'><span class='label'>{key}</span><span class='value'>{value}</span></div>"

        items_html = ""
        for item in items:
            status = item.get("status", "unknown")
            status_label = _get_status_label(status)
            status_class = f"status-{status}"
            source = item.get("source", "")
            target = item.get("target", "")
            name_display = item.get("name", target or source or "")
            if source and target and source != target:
                name_display = f"{source} &rarr; {target}"

            items_html += f"""
            <tr class="{status_class}">
                <td>{name_display}</td>
                <td>{item.get('type', '')}</td>
                <td>{item.get('size', '')}</td>
                <td><span class="status-badge {status_class}">{status_label}</span></td>
                <td>{item.get('notes', '')}</td>
            </tr>
            """

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>品牌素材复核报告 - {command}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: #f5f7fa;
            color: #333;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: #fff;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.08);
            overflow: hidden;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #fff;
            padding: 30px 40px;
        }}
        .header h1 {{
            font-size: 24px;
            margin-bottom: 8px;
        }}
        .header .subtitle {{
            opacity: 0.9;
            font-size: 14px;
        }}
        .summary-section {{
            padding: 30px 40px;
            border-bottom: 1px solid #eee;
        }}
        .summary-section h2 {{
            font-size: 18px;
            margin-bottom: 20px;
            color: #2c3e50;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 16px;
        }}
        .summary-item {{
            background: #f8f9fa;
            padding: 16px;
            border-radius: 8px;
            text-align: center;
        }}
        .summary-item .label {{
            display: block;
            font-size: 12px;
            color: #7f8c8d;
            margin-bottom: 8px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .summary-item .value {{
            display: block;
            font-size: 24px;
            font-weight: bold;
            color: #2c3e50;
        }}
        .table-section {{
            padding: 30px 40px;
        }}
        .table-section h2 {{
            font-size: 18px;
            margin-bottom: 20px;
            color: #2c3e50;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        th, td {{
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }}
        th {{
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .status-badge {{
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 500;
        }}
        .status-generated, .status-success {{
            background: #d4edda;
            color: #155724;
        }}
        .status-overwritten {{
            background: #fff3cd;
            color: #856404;
        }}
        .status-skipped {{
            background: #d1ecf1;
            color: #0c5460;
        }}
        .status-failed, .status-error {{
            background: #f8d7da;
            color: #721c24;
        }}
        .status-warning {{
            background: #fff3cd;
            color: #856404;
        }}
        .status-info {{
            background: #d1ecf1;
            color: #0c5460;
        }}
        .footer {{
            padding: 20px 40px;
            text-align: center;
            color: #999;
            font-size: 12px;
            border-top: 1px solid #eee;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>品牌素材复核报告</h1>
            <div class="subtitle">命令: {command} | 生成时间: {generated_at}</div>
        </div>
        <div class="summary-section">
            <h2>统计概览</h2>
            <div class="summary-grid">
                {summary_html}
            </div>
        </div>
        <div class="table-section">
            <h2>详细列表</h2>
            <table>
                <thead>
                    <tr>
                        <th>文件</th>
                        <th>类型</th>
                        <th>大小</th>
                        <th>状态</th>
                        <th>备注</th>
                    </tr>
                </thead>
                <tbody>
                    {items_html}
                </tbody>
            </table>
        </div>
        <div class="footer">
            由 Brand Kit 工具自动生成 | 创意设计平台命令行工具 v1.0.0
        </div>
    </div>
</body>
</html>"""
