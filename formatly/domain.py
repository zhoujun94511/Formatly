"""Stable contracts shared by engines and delivery adapters; no web/storage imports."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol


@dataclass
class Issue:
    rule_id: str
    level: str
    message: str
    location: str = "文件"
    expected: Any = None
    actual: Any = None
    source: str = "规则方案"
    plugin: str = ""
    category: str = "format"

    def to_dict(self) -> dict:
        if self.level not in {"error", "warning", "manual"}:
            raise ValueError(f"无效问题级别: {self.level}")
        return asdict(self)


@dataclass
class AuditContext:
    input_path: Path
    kind: str
    output_dir: Path
    settings: dict
    pdf_path: Path | None = None
    render_word: bool = False
    cache: dict = field(default_factory=dict)
    on_progress: Callable[[str, str], None] | None = field(default=None, repr=False)
    is_cancelled: Callable[[], bool] | None = field(default=None, repr=False)


@dataclass
class PluginResult:
    issues: list[Issue] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)
    status: str = "completed"
    checks: list[dict] = field(default_factory=list)


class AuditPlugin(Protocol):
    id: str
    name: str
    description: str

    def probe(self) -> tuple[bool, str]: ...
    def run(self, context: AuditContext) -> PluginResult: ...

