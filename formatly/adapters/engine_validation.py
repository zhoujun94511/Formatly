"""Static validation of a configured engine without importing its code."""
from __future__ import annotations

import ast
import hashlib
import inspect
import json
from pathlib import Path
import re

REQUIRED_FILES = (
    "scripts/run_audit.py", "scripts/check_document.py", "configs/sources.json",
    "configs/vendor_lock.json", "configs/thesis.yaml", "configs/intern.yaml",
)
_MAX_CONFIG_BYTES = 4 * 1024 * 1024
_SHA256 = re.compile(r"[0-9a-fA-F]{64}")


def _read_json(path: Path) -> dict:
    if path.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("配置文件超过大小限制")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("配置文件必须为对象")
    return value


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_sources(root: Path) -> None:
    """Verify source bytes, keeping all source names and paths private."""
    sources = _read_json(root / "configs/sources.json")
    if not sources:
        raise ValueError("规则依据清单为空")
    for entry in sources.values():
        if (not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
                or not entry["path"].strip() or not isinstance(entry.get("sha256"), str)
                or not _SHA256.fullmatch(entry["sha256"])):
            raise ValueError("规则依据清单结构无效")
        path = Path(entry["path"]).expanduser()
        path = (path if path.is_absolute() else root / path).resolve()
        if not path.is_file() or _sha(path) != entry["sha256"].lower():
            raise ValueError("规则依据缺失或 SHA256 不一致")


def validate_vendor(root: Path) -> None:
    lock = _read_json(root / "configs/vendor_lock.json")
    files = lock.get("files")
    if not isinstance(files, dict) or not files or not isinstance(lock.get("commits"), dict):
        raise ValueError("vendor 版本清单结构无效或为空")
    vendor = (root.parent / "vendor").resolve()
    for name, digest in files.items():
        if (not isinstance(name, str) or not name.strip() or not isinstance(digest, str)
                or not _SHA256.fullmatch(digest)):
            raise ValueError("vendor 版本清单结构无效")
        path = (vendor / name.replace("\\", "/")).resolve()
        if not path.is_relative_to(vendor) or not path.is_file() or _sha(path) != digest.lower():
            raise ValueError("vendor 文件缺失、越界或 SHA256 不一致")


def _signature(node: ast.FunctionDef) -> inspect.Signature:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    required = len(positional) - len(args.defaults)
    parameters = [inspect.Parameter(
        item.arg,
        inspect.Parameter.POSITIONAL_ONLY if index < len(args.posonlyargs) else inspect.Parameter.POSITIONAL_OR_KEYWORD,
        default=inspect.Parameter.empty if index < required else None,
    ) for index, item in enumerate(positional)]
    if args.vararg is not None:
        parameters.append(inspect.Parameter(args.vararg.arg, inspect.Parameter.VAR_POSITIONAL))
    parameters.extend(inspect.Parameter(item.arg, inspect.Parameter.KEYWORD_ONLY,
                      default=inspect.Parameter.empty if default is None else None)
                      for item, default in zip(args.kwonlyargs, args.kw_defaults))
    if args.kwarg is not None:
        parameters.append(inspect.Parameter(args.kwarg.arg, inspect.Parameter.VAR_KEYWORD))
    return inspect.Signature(parameters)


def validate_entrypoints(root: Path) -> None:
    """Bind the actual adapter calls against AST signatures; execute no engine."""
    path = root / "scripts/run_audit.py"
    if path.stat().st_size > _MAX_CONFIG_BYTES:
        raise ValueError("专项入口文件超过大小限制")
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    entries = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    if not {"audit_one", "write_summary"}.issubset(entries):
        raise ValueError("专项入口缺少 audit_one 或 write_summary")
    try:
        _signature(entries["audit_one"]).bind(None, None, None, None,
            pdf=None, pair_status="", render_word=False)
        _signature(entries["write_summary"]).bind(None, None, None)
    except TypeError as exc:
        raise ValueError("专项入口函数签名与适配器不匹配") from exc


def valid_yaml_rules(value, kind):
    """Check fields consumed by the engine's document formatting configuration."""
    if not isinstance(value, dict):
        return False
    if not isinstance(value.get("template_name"), str) or not value["template_name"].strip():
        return False
    for field in ("style_checks_warning", "global_format", "headings", "header_footer", "numbering", "structure"):
        if not isinstance(value.get(field), dict):
            return False
    if not value["headings"] or not any(isinstance(item, dict) and item for item in value["headings"].values()):
        return False
    if type(value["numbering"].get("enabled")) is not bool:
        return False
    structure = value["structure"]
    if any(not isinstance(structure.get(field), list) for field in ("void_categories", "skip_children_categories")):
        return False
    header_footer = value["header_footer"]
    if type(header_footer.get("enabled")) is not bool:
        return False
    page = header_footer.get("page_setup")
    if not isinstance(page, dict) or not all(field in page for field in (
            "top_margin", "bottom_margin", "left_margin", "right_margin", "page_size")):
        return False
    if kind == "thesis" and any(not isinstance(value.get(field), dict) or not value[field]
                                for field in ("abstract", "body", "references")):
        return False
    return True


def runtime_probe_script() -> str:
    """Use the selected Python's YAML parser, never any engine implementation."""
    return "import importlib, json, pathlib, sys\n" + inspect.getsource(valid_yaml_rules) + '''
dependencies = True
for name in ("docx", "yaml", "lxml", "pdfplumber", "PIL", "pydantic", "rich", "loguru"):
    try:
        importlib.import_module(name)
    except Exception:
        dependencies = False
rules = False
if dependencies:
    try:
        import yaml
        root = pathlib.Path(sys.argv[1])
        rules = True
        for kind in ("thesis", "intern"):
            path = root / "configs" / (kind + ".yaml")
            if path.stat().st_size > 4 * 1024 * 1024:
                rules = False
                break
            value = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            if not valid_yaml_rules(value, kind):
                rules = False
                break
    except Exception:
        rules = False
print(json.dumps({"dependencies": dependencies, "rules": rules}))
'''
