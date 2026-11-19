"""Optional local Docling layout, table and OCR benchmark adapter."""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


def extract(path: Path, artifacts: Path, tesseract: Path, languages: list[str]) -> dict[str, Any]:
    if not artifacts.is_dir() or not any(artifacts.iterdir()):
        raise ValueError("Docling完整管线需要显式非空本地模型目录；比较期间不会下载模型")
    if not tesseract.is_file() or not languages:
        raise ValueError("Docling完整管线需要显式本地Tesseract与语言列表")
    try:
        options = importlib.import_module("docling.datamodel.pipeline_options")
        converters = importlib.import_module("docling.document_converter")
        base = importlib.import_module("docling.datamodel.base_models")
    except ImportError as error:
        raise ValueError("完整管线需要独立环境中的docling；docling-parse不能替代") from error
    pipeline = options.PdfPipelineOptions(
        artifacts_path=artifacts, enable_remote_services=False, allow_external_plugins=False,
        do_ocr=True, do_table_structure=True, document_timeout=120,
        ocr_options=options.TesseractCliOcrOptions(tesseract_cmd=str(tesseract), lang=languages),
    )
    converter = converters.DocumentConverter(
        allowed_formats=[base.InputFormat.PDF],
        format_options={base.InputFormat.PDF: converters.PdfFormatOption(pipeline_options=pipeline)},
    )
    conversion = converter.convert(path, max_num_pages=250, max_file_size=40 * 1024 * 1024)
    document = conversion.document
    pages: dict[int, dict[str, Any]] = {
        int(number): {"number": int(number), "width_pt": doc_page.size.width,
                      "height_pt": doc_page.size.height, "spans": [], "text": "", "method": "layout-ocr"}
        for number, doc_page in document.pages.items()}
    entries, structures = [], []
    for item, _level in document.iterate_items():
        label = str(item.label)
        provenance = getattr(item, "prov", [])
        cells = getattr(getattr(item, "data", None), "table_cells", None)
        texts = [(cell.text, getattr(cell, "bbox", None), provenance[0].page_no if provenance else None)
                 for cell in cells] if cells is not None else [
                     (getattr(item, "text", ""), prov.bbox, prov.page_no) for prov in provenance]
        structures.append({"label": label, "reference": item.self_ref,
                           "rows": getattr(getattr(item, "data", None), "num_rows", None),
                           "columns": getattr(getattr(item, "data", None), "num_cols", None),
                           "cell_count": len(cells) if cells is not None else None})
        if cells is not None and provenance:
            rows: dict[int, list[Any]] = {}
            for cell in cells:
                rows.setdefault(cell.start_row_offset_idx, []).append(cell)
            for row in rows.values():
                ordered = sorted(row, key=lambda cell: cell.start_col_offset_idx)
                if len(ordered) == 2:
                    entries.append({"text": "：".join(cell.text for cell in ordered),
                                    "location": f"PDF第{provenance[0].page_no}页表格行",
                                    "page": provenance[0].page_no, "table_pair": True,
                                    "method": "table-structure", "reference": item.self_ref})
        for text, box, number in texts:
            if not text or number not in pages:
                continue
            record = pages[number]
            observation = {"text": text, "location": f"PDF第{number}页", "page": number,
                           "method": "layout-ocr", "label": label}
            if box is not None:
                actual = box.to_top_left_origin(page_height=record["height_pt"])
                observation["bbox"] = [actual.l, actual.t, actual.r, actual.b]
            record["spans"].append(observation)
            entries.append(observation)
    for record in pages.values():
        record["text"] = "\n".join(span["text"] for span in record["spans"])
    completed = str(conversion.status.value) == "success"
    return {"format": "pdf", "text": "\n".join(item["text"] for item in entries if not item.get("table_pair")),
            "entries": entries, "pages": list(pages.values()), "structures": structures,
            "page_count": len(pages), "processed_pages": len(pages), "complete": completed,
            "requires_review": True, "warnings": ["本地布局、表格与OCR模型观察；不证明学校格式或公式语义"],
            "conversion_status": str(conversion.status.value)}
