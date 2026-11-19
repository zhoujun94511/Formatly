"""Bounded page rendering in a disposable process."""
from __future__ import annotations

import base64
import io
import json
import math
from pathlib import Path
import sys

from ..files import MAX_FILE_BYTES
from .runtime import render_pdf_bitmap


def main() -> int:
    import pypdfium2 as pdfium
    source, page_value, output = sys.argv[1:]
    source, output = Path(source), Path(output)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_FILE_BYTES:
        return 2
    number = int(page_value)
    with pdfium.PdfDocument(str(source)) as document:
        if not 1 <= number <= min(300, len(document)):
            return 2
        page = document[number - 1]
        try:
            width, height = page.get_size()
            if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                return 2
            media, crop = page.get_mediabox(), page.get_cropbox()
            if media is None or crop is None:
                return 2
            if not all(math.isfinite(value) for value in (*media, *crop)):
                return 2
            # Extraction coordinates use an unrotated, complete page. Do not
            # project those coordinates onto a crop/rotation we cannot prove.
            if page.get_rotation() or any(abs(a - b) > .01 for a, b in zip(media, crop)) or abs(media[0]) > .01 or abs(media[1]) > .01:
                return 2
            scale = min(2.0, 1600 / max(width, height))
            if scale < .05:
                return 2
            bitmap = render_pdf_bitmap(page, scale)
            try:
                image = bitmap.to_pil()
                stream = io.BytesIO()
                image.save(stream, format="PNG")
                raw = stream.getvalue()
            finally:
                bitmap.close()
        finally:
            page.close()
    if len(raw) > 3 * 1024 * 1024:
        return 2
    output.write_text(json.dumps({"image": base64.b64encode(raw).decode("ascii"), "width_pt": width, "height_pt": height}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
