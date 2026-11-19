"""Deterministic anonymous source bytes for the compatibility risk matrix."""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import json
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from scripts.evaluate_public_school_corpus import make_pdf

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A4 = '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:bottom="1440" w:left="1440" w:right="1440"/></w:sectPr>'
BASE_STYLE = ('<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="正文"/>'
              '<w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr>'
              '<w:rPr><w:rFonts w:eastAsia="宋体"/><w:sz w:val="24"/></w:rPr></w:style>')
PROFILE: dict[str, Any] = {"id": "compatibility-dataset", "name": "Formatly 兼容性数据集",
           "description": "匿名固定风险样本，不代表任何学校正式要求。",
           "plugins": ["docx-package", "generic-format", "document-fields"],
           "settings": {"page": {"width_mm": 210, "height_mm": 297, "tolerance_mm": 1,
                                    "margins_mm": {"top": 25, "bottom": 25, "left": 25, "right": 25}},
                        "required_headings": ["摘要", "参考文献"],
                        "body": {"style_ids": ["Normal"], "font": "宋体", "size_pt": 12, "line_spacing": 1.5}}}


def paragraph(text: str, *, style: str = "Normal", properties: str = "", runs: str | None = None) -> str:
    return ('<w:p><w:pPr><w:pStyle w:val="' + escape(style) + '"/></w:pPr>'
            + (runs if runs is not None else '<w:r>' + properties + '<w:t>' + escape(text) + '</w:t></w:r>') + '</w:p>')


def document_package(body: str, styles: str, extras: dict[str, str] | None = None) -> bytes:
    parts = {"[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
             '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
             '<Default Extension="xml" ContentType="application/xml"/>'
             '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
             '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
             "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
             "word/_rels/document.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
             '<Relationship Id="styles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
             "word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>',
             "word/styles.xml": f'<w:styles xmlns:w="{W}">{styles}</w:styles>', **(extras or {})}
    stream = BytesIO()
    with ZipFile(stream, "w") as package:
        for name, content in parts.items():
            entry = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            package.writestr(entry, content.encode("utf-8"))
    return stream.getvalue()


def docx_fixture(variant: str) -> bytes:
    if variant == "corrupt-package":
        return b"PK\x03\x04not-a-valid-zip-package"
    styles, section, style = BASE_STYLE, A4, "Normal"
    properties, extra_body = "", ""
    if variant == "format-errors":
        styles = styles.replace('w:eastAsia="宋体"', 'w:eastAsia="黑体"').replace('w:val="24"', 'w:val="28"').replace('w:line="360"', 'w:line="480"')
        section = section.replace('w:h="16838"', 'w:h="15838"').replace('w:top="1440"', 'w:top="2160"')
    elif variant == "style-inheritance":
        styles += '<w:style w:type="paragraph" w:styleId="Parent"><w:basedOn w:val="Normal"/></w:style><w:style w:type="paragraph" w:styleId="LocalBody"><w:basedOn w:val="Parent"/></w:style>'
        style = "LocalBody"
    elif variant == "direct-override":
        properties = '<w:rPr><w:rFonts w:eastAsia="黑体"/><w:sz w:val="28"/></w:rPr>'
    elif variant == "second-section":
        extra_body = '<w:p><w:pPr>' + A4 + '</w:pPr></w:p>' + paragraph("第二节匿名正文")
        section = section.replace('w:left="1440"', 'w:left="2160"')
    elif variant == "table-fields":
        extra_body = '<w:tbl><w:tr><w:tc>' + paragraph("姓名") + '</w:tc><w:tc>' + paragraph("示例学生") + '</w:tc></w:tr></w:tbl>'
    elif variant == "hidden-field":
        extra_body = paragraph("姓名：示例学生", properties='<w:rPr><w:vanish/></w:rPr>')
    elif variant == "theme-font":
        properties = '<w:rPr><w:rFonts w:eastAsiaTheme="minorEastAsia"/></w:rPr>'
    elif variant == "field-instruction":
        extra_body = paragraph("", runs='<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>姓名：示例学生</w:instrText></w:r><w:r><w:fldChar w:fldCharType="end"/></w:r>')
    elif variant != "compliant":
        raise ValueError("未知 DOCX 合成变体：" + variant)
    return document_package(paragraph("摘要") + paragraph("这是用于核验正文格式的匿名示例段落。", style=style, properties=properties)
                            + paragraph("参考文献") + extra_body + section, styles)


def case_profile(case: dict) -> dict:
    value = deepcopy(PROFILE)
    value["id"] += "-" + case["id"]
    for key, changes in case.get("settings", {}).items():
        if isinstance(changes, dict):
            value["settings"].setdefault(key, {}).update(deepcopy(changes))
        else:
            value["settings"][key] = deepcopy(changes)
    return value


def standard_font_pdf() -> bytes:
    """Fixed visible text with the PDF standard Helvetica font and A4 geometry."""
    stream = b"BT /F1 12 Tf 60 780 Td (Abstract) Tj 0 -22 Td (Anonymous body) Tj 0 -22 Td (References) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Count 1 /Kids [4 0 R] >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.276 841.89] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
               f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"\nendstream"]
    data, offsets = bytearray(b"%PDF-1.4\n%Formatly-compatibility\n"), [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode("ascii") + value + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    data.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii"))
    return bytes(data)


def case_input(case: dict) -> tuple[str, str, bytes]:
    """Generate inputs independently of the reader and detection results."""
    extension, fixture = case["format"], case["fixture"]
    if extension == "docx":
        payload = docx_fixture(fixture)
    elif extension == "pdf":
        if fixture == "invalid-signature":
            payload = b"not-a-pdf"
        elif fixture == "truncated":
            payload = b"%PDF-1.4\ntruncated without page tree\n%%EOF"
        elif fixture == "standard-font":
            payload = standard_font_pdf()
        else:
            ruleset = {"kind": case["kind"], "headings": [] if fixture == "missing-headings" else ["摘要", "参考文献"],
                       "document": {"page": {"width_mm": 210, "height_mm": 297}}}
            payload = make_pdf({"overrides": case.get("geometry", {})}, ruleset)
    elif extension in {"txt", "md"}:
        payload = case["text"].encode(case.get("encoding", "utf-8"))
    elif extension == "json":
        text = case["text"] if "text" in case else json.dumps(case["document"], ensure_ascii=False)
        if fixture == "nested-limit":
            text = '{"child":' * 42 + '"摘要"' + '}' * 42
        payload = text.encode(case.get("encoding", "utf-8"))
    else:
        raise ValueError("未知兼容性输入格式")
    return case["id"] + "." + case.get("extension", extension), case["kind"], payload
