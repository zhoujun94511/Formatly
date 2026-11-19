"""Safe DOCX repair planning and application."""

from .engine import apply_repair_plan
from .planning import build_repair_plan

__all__ = ["apply_repair_plan", "build_repair_plan"]
