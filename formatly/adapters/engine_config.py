"""Private, host-local configuration for the optional document engine."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from ..files import write_json
from ..persistence.locks import write_lock

_CONFIG_LOCK = Lock()
_MAX_CONFIG_BYTES = 64 * 1024


def _read_document(data_dir: Path) -> dict:
    path = data_dir / "integrations.json"
    if not path.exists():
        return {"version": 1}
    try:
        if path.stat().st_size > _MAX_CONFIG_BYTES:
            raise ValueError("集成配置超过大小限制")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError("本机集成配置无法读取；请在运行主机备份并修复 integrations.json") from exc
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("本机集成配置结构或版本无效；请修复 integrations.json")
    return value


def _validated_paths(root: str | Path, python: str | Path, *, require_exists: bool = True) -> dict[str, str]:
    try:
        if not isinstance(root, (str, Path)) or not isinstance(python, (str, Path)):
            raise ValueError("专项引擎目录和 Python 必须为路径")
        if not str(root).strip() or not str(python).strip():
            raise ValueError("专项引擎目录和 Python 不能为空")
        engine_root = Path(root).expanduser().resolve()
        interpreter = Path(python).expanduser().resolve()
        if require_exists and (not engine_root.is_dir() or not interpreter.is_file()):
            raise ValueError("专项引擎目录或 Python 文件不存在")
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError("专项引擎目录或 Python 路径无效；请使用本机存在的目录和解释器") from exc
    return {"root": str(engine_root), "python": str(interpreter)}


def load_engine_config(data_dir: str | Path | None) -> dict[str, str]:
    """Read configured paths for local use; never expose this value over HTTP."""
    if data_dir is None:
        return {}
    document = _read_document(Path(data_dir))
    config = document.get("external_engine")
    if config is None:
        return {}
    if not isinstance(config, dict) or set(config) != {"root", "python"}:
        raise ValueError("本机专项引擎配置无效；请重新配置")
    # Existence belongs to preflight after env/explicit overrides are selected.
    # A removed saved interpreter must not block a valid interpreter override.
    return _validated_paths(config["root"], config["python"], require_exists=False)


def save_engine_config(data_dir: str | Path, root: str | Path, python: str | Path) -> dict[str, str]:
    """Persist validated paths atomically after a successful local preflight."""
    config = _validated_paths(root, python)
    directory = Path(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    with write_lock(directory, _CONFIG_LOCK):
        document = _read_document(directory)
        document["external_engine"] = config
        write_json(directory / "integrations.json", document)
    return config


def clear_engine_config(data_dir: str | Path) -> bool:
    """Remove only this integration, preserving other local integrations."""
    directory = Path(data_dir)
    if not (directory / "integrations.json").exists():
        return False
    with write_lock(directory, _CONFIG_LOCK):
        document = _read_document(directory)
        if "external_engine" not in document:
            return False
        del document["external_engine"]
        write_json(directory / "integrations.json", document)
    return True
