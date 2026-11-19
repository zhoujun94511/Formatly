"""Data exports and assembly of the Vue-built standalone HTML report."""
from __future__ import annotations

import html
import json
from pathlib import Path
import re

from ..files import atomic_write
from ..interfaces.assets import frontend_directory

LABELS = {"passed": "已覆盖属性通过", "needs_changes": "发现格式偏差", "review_required": "待人工复核", "incomplete": "检测未完成"}
REPORT_TEMPLATE = frontend_directory() / "report-template.html"


def _html_report(result: dict, filename: str) -> str:
    try:
        template = REPORT_TEMPLATE.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError("缺少 Vue 报告模板，请在 frontend 运行 npm run build 或安装完整的 Formatly 发布包") from exc
    title_marker = "__FORMATLY_REPORT_TITLE__"
    data_marker = "__FORMATLY_REPORT_DATA__"
    if template.count(title_marker) != 1 or template.count(data_marker) != 1:
        raise ValueError("Vue 报告模板无效，请重新构建前端")
    payload = json.dumps({"filename": filename, "result": result}, ensure_ascii=False, allow_nan=False)
    # Keep document text inside the inert JSON script, including closing-script
    # spellings, HTML characters and JavaScript line separators.
    for character, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                               ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        payload = payload.replace(character, escaped)
    # Replace both markers in one pass: filenames and report text may themselves
    # contain either marker and must never be interpreted as template syntax.
    values = {title_marker: html.escape(filename, quote=True), data_marker: payload}
    return re.sub(f"{title_marker}|{data_marker}", lambda match: values[match.group()], template)


def render_reports(result: dict, output: Path, filename: str):
    page = _html_report(result, filename)
    counts = result["counts"]
    summary = f"错误 {counts['error']} · 警告 {counts['warning']} · 人工复核 {counts['manual']}"
    text = lambda value: (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value if value is not None else "未设置"))
    cell = lambda value: text(value).replace("|", "∣").replace("\n", " ")
    lines = ["# Formatly · 论文格式检测报告", "", "Academic formatting, checked.", "", f"文件：{filename}", f"方案：{result['profile_id']}",
             f"结果：{LABELS[result['status']]}", summary, "", f"输入格式：{result.get('input_format', '历史结果未记录')}",
             f"输入SHA256：{result['input_sha256']}",
             f"检测快照未变：{result['input_unchanged']}", "", "人工复核和未完成项不计为通过。", "",
             "| 级别 | 规则 | 位置 | 预期 | 实际 | 说明 | 来源 |", "|---|---|---|---|---|---|---|"]
    for issue in result["issues"]:
        values = [issue.get(key) for key in ("level", "rule_id", "location", "expected", "actual", "message", "source")]
        lines.append("| " + " | ".join(cell(v) for v in values) + " |")
    repair = result.get("repair")
    if repair:
        lines += ["", "## 本次修复", "", f"来源文件：{text(repair.get('source_filename'))}",
                  f"已应用修改：{repair.get('applied_count', 0)} 项", "",
                  "| 项目 | 位置 | 修改前 | 修改后 |", "|---|---|---|---|"]
        for change in repair.get("changes", []):
            lines.append("| " + " | ".join(cell(change.get(key)) for key in ("label", "location", "actual", "expected")) + " |")
    coverage = result.get("coverage", {})
    lines += ["", "## 规则执行与覆盖", "", "覆盖范围仅限本次方案；未执行、不支持、人工复核与执行失败均不计为通过。",
              f"格式属性执行数：{coverage.get('format_checks', '历史结果未记录')}",
              f"覆盖完整：{coverage.get('complete', False)}", f"状态计数：{text(coverage.get('summary', {}))}", "",
              "| 规则/要求 | 状态 | 位置 | 预期 | 实际/证据 | 来源/说明 |", "|---|---|---|---|---|---|"]
    for check in coverage.get("checks", []):
        values = [check.get("label", check.get("rule_id")), check.get("status"), check.get("location"),
                  check.get("expected"), check.get("actual"), {"source": check.get("source"), "reason": check.get("reason")}]
        lines.append("| " + " | ".join(cell(value) for value in values) + " |")
    lines += ["", "## 文档读取与来源", "", "```json", json.dumps(result.get("document_extraction"), ensure_ascii=False, indent=2), "```",
              "", "## 方案快照", "", f"规则 SHA256：{result.get('profile_sha256', '历史结果未记录')}", "",
              "```json", json.dumps(result.get("profile_snapshot", {}), ensure_ascii=False, indent=2), "```", "",
              "## 输入完整性", "", "原稿为 PDF 时，原稿哈希使用上方输入 SHA256。下列 PDF 字段仅表示 DOCX 的可选配对附件。",
              f"配对 PDF SHA256：{result.get('pdf_sha256') or '未提供'}",
              f"配对 PDF 快照未变：{result.get('pdf_unchanged', '未记录')}",
              f"原始文件未变：{result.get('original_unchanged', 'Web 上传不访问宿主原件')}",
              f"原始配对 PDF 未变：{result.get('original_pdf_unchanged', '未记录或未提供')}", "", "## 引擎执行", ""]
    for engine in result["engines"]:
        lines += [f"- {engine['id']}：{engine['status']}（{engine['duration_ms']}ms）", "", "```json",
                  json.dumps(engine.get("evidence", {}), ensure_ascii=False, indent=2), "```", ""]
    atomic_write(output / "report.md", "\n".join(lines).encode("utf-8"))
    atomic_write(output / "report.html", page.encode("utf-8"))

