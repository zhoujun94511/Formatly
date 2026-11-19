"""Deterministic anonymous input for trying a saved profile through AuditService."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile


def sample_docx() -> bytes:
    namespace = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    paragraphs = []
    for text in ('摘要', '这是用于规则试跑的匿名样例，不包含学校或个人信息。', '关键词：格式检测；样例',
                 'Abstract', 'This is an anonymous formatting sample.', '1 绪论',
                 '这段正文采用宋体十二磅、1.5倍行距。请使用真实原稿进行正式检测。', '参考文献', '[1] 匿名作者. 格式样例说明. 2026.'):
        paragraphs.append(f'<w:p><w:pPr><w:pStyle w:val="Normal"/><w:spacing w:line="360" w:lineRule="auto"/></w:pPr><w:r><w:t>{text}</w:t></w:r></w:p>')
    parts = {
        '[Content_Types].xml': '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
        '_rels/.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        'word/_rels/document.xml.rels': '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
        'word/styles.xml': f'<w:styles xmlns:w="{namespace}"><w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体"/><w:sz w:val="24"/></w:rPr></w:style></w:styles>',
        'word/document.xml': f'<w:document xmlns:w="{namespace}"><w:body>{"".join(paragraphs)}<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:bottom="1440" w:left="1440" w:right="1440"/></w:sectPr></w:body></w:document>'}
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as package:
        for name, value in parts.items():
            # Stable package bytes allow reproducible input hashes between trials.
            from zipfile import ZipInfo
            package.writestr(ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), value.encode('utf-8'))
    return output.getvalue()
