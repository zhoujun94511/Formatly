"""Locate the Vue build in this checkout.

Frontend files stay in frontend/dist. This project is not installed as a library.
"""
from __future__ import annotations

from pathlib import Path


def frontend_directory() -> Path:
    source_frontend = Path(__file__).resolve().parents[2] / "frontend"
    if (source_frontend / "package.json").is_file():
        return source_frontend / "dist"
    raise FileNotFoundError("未找到 Formatly 前端资源，请在 frontend 运行 npm run build")
