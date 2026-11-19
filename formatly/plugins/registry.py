from __future__ import annotations

from importlib.metadata import entry_points
import re

from ..domain import AuditPlugin
from ..privacy import redact_local_paths
from .builtin import GenericPlugin, LegacyPlugin, PackagePlugin


def probe_plugin(plugin: AuditPlugin, input_format: str | None = None) -> tuple[bool, str]:
    """Apply the same availability contract to preflight and execution."""
    format_probe = getattr(plugin, "probe_format", None) if input_format is not None else None
    result = format_probe(input_format) if callable(format_probe) else plugin.probe()
    if not isinstance(result, (tuple, list)) or len(result) != 2:
        raise ValueError("插件预检须返回可用状态和说明")
    available, reason = result
    if type(available) is not bool or not isinstance(reason, str):
        raise ValueError("插件预检须返回布尔状态和文字说明")
    return available, redact_local_paths(reason)


class PluginRegistry:
    def __init__(self, discover: bool = True, *, data_dir=None):
        self._plugins: dict[str, AuditPlugin] = {}
        self._load_errors = []
        for plugin in (PackagePlugin(), GenericPlugin(), LegacyPlugin(data_dir=data_dir)):
            self.register(plugin)
        from .fields import DocumentFieldsPlugin
        self.register(DocumentFieldsPlugin())
        from .academic import AcademicFormatPlugin
        self.register(AcademicFormatPlugin())
        from .structure import AcademicStructurePlugin
        self.register(AcademicStructurePlugin())
        if discover:
            for entry in entry_points(group="formatly.plugins"):
                try:
                    self.register(entry.load()())
                except Exception as exc:
                    self._load_errors.append({"id": entry.name, "name": entry.name, "description": "已安装的第三方插件加载失败",
                                              "available": False, "reason": redact_local_paths(str(exc)),
                                              "error_type": type(exc).__name__})

    def register(self, plugin):
        for attr in ("id", "name", "description"):
            if not isinstance(getattr(plugin, attr, None), str):
                raise ValueError(f"插件缺少字符串属性: {attr}")
        if plugin.id in self._plugins:
            raise ValueError(f"插件ID重复: {plugin.id}")
        if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", plugin.id):
            raise ValueError("插件ID须以小写字母开头，仅含小写字母、数字和连字符")
        if not callable(getattr(plugin, "run", None)) or not callable(getattr(plugin, "probe", None)):
            raise ValueError("插件须实现run与probe")
        self._plugins[plugin.id] = plugin

    def get(self, plugin_id):
        if plugin_id not in self._plugins:
            raise ValueError(f"插件不存在或加载失败: {plugin_id}")
        return self._plugins[plugin_id]

    def list(self):
        items = []
        for plugin in self._plugins.values():
            diagnostic = {}
            try:
                available, reason = probe_plugin(plugin)
            except Exception as exc:
                available, reason = False, redact_local_paths(str(exc))
                diagnostic["error_type"] = type(exc).__name__
            items.append({"id": plugin.id, "name": plugin.name, "description": plugin.description,
                          "available": bool(available), "reason": reason, **diagnostic,
                          "settings_keys": list(getattr(plugin, "settings_keys", ())),
                          "formats": list(getattr(plugin, "formats", ("docx",))),
                          "kinds": list(getattr(plugin, "kinds", ("thesis", "intern", "certificate")))})
        return items + self._load_errors

    def validate_settings(self, profile):
        """Validate plugin-declared settings consumers and capability limits.

        Undeclared external options are readable by their plugins, but are
        explicitly unverified and prevent an unsupported claim of full coverage.
        """
        selected = [self.get(plugin_id) for plugin_id in profile["plugins"]]
        settings = profile.get("settings", {})
        reserved = {"page": "generic-format", "body": "generic-format", "required_headings": "generic-format", "references": "generic-format",
                    "fields": "document-fields", "paragraph": "academic-format", "headings": "academic-format", "section": "academic-format",
                    "structure": "academic-structure"}
        for key, owner in reserved.items():
            if settings.get(key) and owner not in profile["plugins"]:
                raise ValueError(f"settings.{key}需要启用{owner}插件")
        declared = set()
        undeclared = []
        for plugin in selected:
            keys = getattr(plugin, "settings_keys", None)
            if keys is None and plugin.id not in {"docx-package", "generic-format", "legacy-school", "document-fields"}:
                undeclared.append(plugin.id)
            declared.update(keys or ())
            validator = getattr(plugin, "validate_settings", None)
            if callable(validator):
                validator(settings)
        unknown = sorted(set(settings) - declared)
        if unknown and not undeclared:
            raise ValueError("规则参数没有对应消费插件或字段拼写错误：" + ", ".join(unknown))
        return ["以下参数由未声明参数能力的第三方插件处理，覆盖须复核：" + ", ".join(unknown)] if unknown else []

    def preflight(self, profile, kind=None, input_format="docx"):
        if input_format not in {"docx", "pdf", "txt", "md", "json"}:
            raise ValueError("输入格式仅支持 DOCX、PDF、TXT、MD、JSON")
        warnings = self.validate_settings(profile)
        if input_format in {"txt", "md", "json"}:
            warnings.append("此格式仅核验可提取的内容、标题和字段；没有实际纸张、字体或段落排版属性。")
        elif input_format == "pdf":
            from ..documents import probe_ocr
            ocr = probe_ocr()
            warnings.append("PDF 不包含 Word 样式；扫描内容使用本地 OCR 并保留人工复核。" + (" " + redact_local_paths(ocr["reason"]) if not ocr["available"] else ""))
        compatible = kind is None or kind in profile.get("kinds", ["thesis", "intern", "certificate"])
        plugins = []
        for plugin_id in profile["plugins"]:
            plugin = self.get(plugin_id)
            diagnostic = {}
            try:
                available, reason = probe_plugin(plugin, input_format)
            except Exception as exc:
                available, reason = False, redact_local_paths(str(exc))
                diagnostic["error_type"] = type(exc).__name__
            supported = kind is None or kind in getattr(plugin, "kinds", ("thesis", "intern", "certificate"))
            format_supported = input_format in getattr(plugin, "formats", ("docx",))
            plugins.append({"id": plugin_id, "name": plugin.name, "available": bool(available and supported and format_supported),
                            **diagnostic,
                            "reason": "插件不支持 " + input_format.upper() + " 原稿" if not format_supported else reason if supported else "插件不支持所选文档类型"})
        from ..application.profile_capabilities import effective_summary
        return {"available": compatible and all(item["available"] for item in plugins), "plugins": plugins,
                "warnings": warnings, "kind_compatible": compatible, "input_format": input_format,
                "summary": effective_summary(profile, kind, input_format, plugins)}

