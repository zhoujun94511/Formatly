"""A standalone plugin: only the public domain contract is imported."""
from __future__ import annotations

import json
from xml.etree import ElementTree
from zipfile import ZipFile

from formatly.domain import AuditContext, Issue, PluginResult


class PlaceholderPlugin:
    id = "example-placeholders"
    name = "示例 · 占位文本检查"
    description = "演示外部插件注册、方案参数、定位问题及独立证据目录。"

    @staticmethod
    def probe() -> tuple[bool, str]:
        return True, "仅使用 Python 标准库"

    def run(self, context: AuditContext) -> PluginResult:
        options = context.settings.get("example_placeholders", {})
        if not isinstance(options, dict):
            raise ValueError("example_placeholders 必须为对象")
        tokens = options.get("tokens", ["此处填写", "TODO", "待补充"])
        if (not isinstance(tokens, list) or not tokens or len(tokens) > 100
                or any(not isinstance(token, str) or not token.strip() for token in tokens)):
            raise ValueError("tokens 必须包含 1 至 100 个非空文本")
        level = options.get("level", "warning")
        if level not in {"error", "warning", "manual"}:
            raise ValueError("level 必须为 error、warning 或 manual")

        # docx-package must precede this plugin, so malformed/oversized input is
        # rejected by the core before the plugin reads any document part.
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with ZipFile(context.input_path) as package:
            document = ElementTree.fromstring(package.read("word/document.xml"))
        issues = []
        for index, paragraph in enumerate(document.findall(".//w:p", ns), 1):
            text = "".join(node.text or "" for node in paragraph.findall(".//w:t", ns))
            for token in dict.fromkeys(tokens):
                if token in text:
                    issues.append(Issue(
                        rule_id="example.placeholder",
                        level=level,
                        message="发现方案中配置的占位文本，请核对是否需要补全",
                        location=f"XML段{index}：{text[:80]}",
                        expected="无待处理的占位文本",
                        actual=token,
                        source="方案 settings.example_placeholders；示例规则，非学校规范",
                    ))

        # Namespace artifacts so this plugin cannot overwrite another engine's
        # report. Do not save or edit context.input_path.
        destination = context.output_dir / self.id
        destination.mkdir(parents=True, exist_ok=True)
        evidence = {"matched_count": len(issues), "tokens": tokens,
                    "scope": "word/document.xml 内段落文本，不覆盖图片、页眉脚或文本真实性"}
        (destination / "evidence.json").write_text(
            json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
        return PluginResult(issues=issues, evidence=evidence)

