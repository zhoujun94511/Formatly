"""Cooperative job control at boundaries where document workers have returned."""
from __future__ import annotations

from ..domain import AuditContext


class JobCancelled(Exception):
    """Execution stopped at a safe checkpoint after a cancellation request."""


def checkpoint(context: AuditContext, stage: str, detail: str = "") -> None:
    if context.is_cancelled is not None and context.is_cancelled():
        raise JobCancelled("任务已取消，未形成完整检测结论")
    if context.on_progress is not None:
        context.on_progress(stage, detail)
