"""Process, rendering and temporary-directory helpers for document workers."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import math
import os
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, TypedDict
import uuid

if TYPE_CHECKING:
    from pypdfium2 import PdfBitmap


class HiddenProcessOptions(TypedDict, total=False):
    creationflags: int


def hidden_process_options() -> HiddenProcessOptions:
    options: HiddenProcessOptions = {}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    return options


def render_pdf_bitmap(page: object, scale: float) -> PdfBitmap:
    """Render at a positive fractional scale; callers bound the pixel budget."""
    from pypdfium2 import PdfBitmap

    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("PDF 渲染比例必须为有限正数")
    render = getattr(page, "render", None)
    if not callable(render):
        raise TypeError("PDF 页面缺少可调用的 render 方法")
    # PDFium documents scale as float, although its unannotated default is 1.
    bitmap = render(scale=scale)
    if not isinstance(bitmap, PdfBitmap):
        raise TypeError("PDF 渲染未返回有效位图")
    return bitmap


@contextmanager
def pdf_working_directory(parent: Path) -> Iterator[Path]:
    # Inherit the task directory's permissions for restricted Windows workers.
    directory = parent / (".formatly-pdf-" + uuid.uuid4().hex)
    directory.mkdir()
    try:
        yield directory
    finally:
        if not directory.resolve().is_relative_to(parent.resolve()) or directory.is_symlink():
            raise RuntimeError("拒绝清理 PDF 临时目录之外的路径")
        shutil.rmtree(directory)
