"""Document-part addresses bound to an unchanged DOCX snapshot."""
from __future__ import annotations

import hashlib
from xml.etree.ElementTree import Element, tostring


class DocxLocations:
    def __init__(self, document: Element, input_sha256: str):
        self.input_sha256 = input_sha256
        self.paths: dict[Element, list[int]] = {}
        pending = [(document, [])]
        while pending:
            element, path = pending.pop()
            self.paths[element] = path
            pending.extend((child, path + [index]) for index, child in enumerate(element))

    def locate(self, element: Element, **details: str) -> dict:
        return {"version": 1, "part": "word/document.xml", "input_sha256": self.input_sha256,
                "path": self.paths[element], "tag": element.tag,
                "node_sha256": hashlib.sha256(tostring(element, encoding="utf-8")).hexdigest(), **details}
