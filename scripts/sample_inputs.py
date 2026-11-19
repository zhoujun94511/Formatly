"""Anonymous five-format samples shared by browser checks."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile, ZipInfo


def fixtures() -> dict[str, bytes]:
    stream = BytesIO()
    word = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    parts = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<w:document xmlns:w="{word}"><w:body><w:p><w:r><w:t>Formatly installation sample</w:t></w:r></w:p><w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>',
    }
    with ZipFile(stream, "w") as archive:
        for name, value in parts.items():
            archive.writestr(ZipInfo(name), value)
    content = b"BT /F1 12 Tf 50 790 Td (Formatly installation sample) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Count 1 /Kids [4 0 R] >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595.276 841.89] /Resources << /Font << /F1 3 0 R >> >> /Contents 5 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream"]
    pdf, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(pdf)); pdf.extend(str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n")
    start = len(pdf)
    pdf.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode())
    return {"docx": stream.getvalue(), "pdf": bytes(pdf), "txt": b"Formatly installation sample\n",
            "md": b"# Formatly installation sample\n", "json": b'{"schema":"formatly.document.v1","paragraphs":["Formatly installation sample"]}'}
