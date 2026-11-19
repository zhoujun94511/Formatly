"""Compare anonymous table typography with an installed Word-compatible renderer.

This optional developer check needs pywin32, python-docx and pdfplumber. It never attaches
to a running application or opens an existing user document.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
from io import BytesIO
import json
from pathlib import Path
import sys
from typing import Any
from xml.etree import ElementTree
from zipfile import ZipFile


def registered_server(progid: str) -> str | None:
    """Record the COM executable name without recording its installation path."""
    if sys.platform != "win32":
        raise ValueError("Word/WPS COM版式核验仅支持Windows")
    pywintypes = importlib.import_module("pywintypes")
    winreg = importlib.import_module("winreg")

    clsid = str(pywintypes.IID(progid))
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, "CLSID\\" + clsid + "\\LocalServer32",
                                0, winreg.KEY_READ | view) as key:
                command = winreg.QueryValue(key, None)
                executable = command.split('"')[1] if command.startswith('"') else command.split(" ")[0]
                return Path(executable).name
        except FileNotFoundError:
            continue
    return None


def _configure_table(path: Path, kind: str) -> None:
    """Write table options through OOXML, preserving the document namespaces."""
    etree = importlib.import_module("lxml.etree")
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"

    def tag(local_name: str) -> str:
        return "{" + namespace + "}" + local_name

    with ZipFile(path) as original:
        document = etree.fromstring(original.read("word/document.xml"))
        table = document.find(".//" + tag("tbl"))
        if table is None:
            raise ValueError("Generated sample has no table")
        table_properties = table.find(tag("tblPr"))
        if table_properties is None:
            table_properties = etree.Element(tag("tblPr"))
            table.insert(0, table_properties)
        look = table_properties.find(tag("tblLook"))
        if look is None:
            look = etree.SubElement(table_properties, tag("tblLook"))
        look.attrib.clear()
        attributes = {
            "firstRow": "1" if kind == "first-row-on" else "0", "lastRow": "0",
            "firstColumn": "0", "lastColumn": "0",
            "noHBand": "0" if kind == "row-banding" else "1", "noVBand": "1",
            "val": "0400" if kind == "row-banding" else "0620" if kind == "first-row-on" else "0600",
        }
        for name, value in attributes.items():
            look.set(tag(name), value)
        if kind == "default-table":
            table_style = table_properties.find(tag("tblStyle"))
            if table_style is not None:
                table_properties.remove(table_style)
        if kind in {"first-row-on", "first-row-off", "row-banding"}:
            for index, row in enumerate(table.findall(tag("tr")), 1):
                paragraph = row.find(tag("tc") + "/" + tag("p"))
                if paragraph is None:
                    raise ValueError("Generated table row has no paragraph")
                properties = paragraph.find(tag("pPr"))
                if properties is None:
                    properties = etree.Element(tag("pPr"))
                    paragraph.insert(0, properties)
                conditional = etree.SubElement(properties, tag("cnfStyle"))
                first_row = kind == "first-row-on" and index == 1
                odd_band = kind == "row-banding" and index % 2 == 1
                conditional.set(tag("firstRow"), "1" if first_row else "0")
                conditional.set(tag("oddHBand"), "1" if odd_band else "0")
                conditional.set(tag("evenHBand"), "1" if kind == "row-banding" and not odd_band else "0")
                conditional.set(tag("val"), ("1" if first_row else "0") + "00000"
                                + ("1" if odd_band else "0") + "00000")
        document_xml = etree.tostring(document, encoding="UTF-8", xml_declaration=True, standalone=True)
        output = BytesIO()
        with ZipFile(output, "w") as changed:
            for entry in original.infolist():
                changed.writestr(entry, document_xml if entry.filename == "word/document.xml"
                                 else original.read(entry.filename))
    path.write_bytes(output.getvalue())


def create_samples(output: Path) -> list[tuple[str, Path]]:
    document_module = importlib.import_module("docx")
    style_module = importlib.import_module("docx.enum.style")
    xml_module = importlib.import_module("docx.oxml")
    xml_namespace = importlib.import_module("docx.oxml.ns")
    units = importlib.import_module("docx.shared")
    qn = xml_namespace.qn
    oxml_element = xml_module.OxmlElement

    samples: list[tuple[str, Path]] = []
    cases = ["table-base", "default-table", "based-on", "first-row-on", "first-row-off",
             "row-banding", "direct-size", "direct-font", "direct-spacing", "paragraph-style",
             "character-style", "inherited-table-base", "inherited-default-table", "inherited-based-on",
             "inherited-first-row-on", "inherited-first-row-off", "inherited-row-banding",
             "inherited-direct-size", "inherited-direct-font", "inherited-direct-spacing",
             "inherited-paragraph-style", "inherited-character-style", "conditional-direct-size"]

    def properties(owner, name, *, size=None, font=None, line=None):
        props = oxml_element("w:" + name)
        if size is not None:
            child = oxml_element("w:sz")
            child.set(qn("w:val"), str(size * 2))
            props.append(child)
        if font:
            child = oxml_element("w:rFonts")
            for slot in ("ascii", "hAnsi", "eastAsia", "cs"):
                child.set(qn("w:" + slot), font)
            props.append(child)
        if line is not None:
            child = oxml_element("w:spacing")
            child.set(qn("w:line"), str(line))
            child.set(qn("w:lineRule"), "auto")
            props.append(child)
        owner.append(props)

    for case in cases:
        kind = case.removeprefix("inherited-")
        if case == "conditional-direct-size":
            kind = "first-row-on"
        document = document_module.Document()
        if not case.startswith("inherited-") and case != "conditional-direct-size":
            document.styles["Normal"].font.name = "Calibri"
            document.styles["Normal"].font.size = units.Pt(12)
            document.styles["Normal"].paragraph_format.line_spacing = 1
        style = document.styles.add_style("FormatlyTable", style_module.WD_STYLE_TYPE.TABLE)
        properties(style.element, "pPr", line=480)
        properties(style.element, "rPr", size=20, font="Arial")
        if kind in {"first-row-on", "first-row-off", "row-banding"}:
            conditional = oxml_element("w:tblStylePr")
            conditional.set(qn("w:type"), "band1Horz" if kind == "row-banding" else "firstRow")
            properties(conditional, "pPr", line=720)
            properties(conditional, "rPr", size=24, font="Courier New")
            style.element.append(conditional)
        table = document.add_table(rows=3, cols=1)
        table.style = style
        if kind == "default-table":
            for node in document.styles.element:
                if node.get(qn("w:type")) == "table":
                    node.attrib.pop(qn("w:default"), None)
            style.element.set(qn("w:default"), "1")
        elif kind == "based-on":
            derived = document.styles.add_style("FormatlyDerived", style_module.WD_STYLE_TYPE.TABLE)
            derived.base_style = style
            table.style = derived
        for index, row in enumerate(table.rows, 1):
            paragraph = row.cells[0].paragraphs[0]
            run = paragraph.add_run(f"Sample {case} row {index}")
            if kind == "direct-size" or case == "conditional-direct-size":
                run.font.size = units.Pt(14)
            elif kind == "direct-font":
                run.font.name = "Courier New"
            elif kind == "direct-spacing":
                paragraph.paragraph_format.line_spacing = 1.5
            elif kind == "paragraph-style":
                if index == 1:
                    paragraph_style = document.styles.add_style("FormatlyParagraph", style_module.WD_STYLE_TYPE.PARAGRAPH)
                    paragraph_style.font.size = units.Pt(16)
                    paragraph_style.font.name = "Times New Roman"
                    paragraph_style.paragraph_format.line_spacing = 2.5
                paragraph.style = "FormatlyParagraph"
            elif kind == "character-style":
                if index == 1:
                    character_style = document.styles.add_style("FormatlyCharacter", style_module.WD_STYLE_TYPE.CHARACTER)
                    character_style.font.size = units.Pt(18)
                    character_style.font.name = "Times New Roman"
                run.style = "FormatlyCharacter"
        path = output / f"{case}.docx"
        document.save(path)
        _configure_table(path, kind)
        samples.append((case, path))
    return samples


def _snapshot(sample: Path) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from formatly.documents.docx_semantics import effective_size_pt, read_docx_content
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with ZipFile(sample) as package:
        document = ElementTree.fromstring(package.read("word/document.xml"))
        styles = ElementTree.fromstring(package.read("word/styles.xml"))
    content = read_docx_content(document, styles)
    return {"sample_sha256": hashlib.sha256(sample.read_bytes()).hexdigest(),
            "guarded_sizes": [effective_size_pt(run.text, run.properties)
                              for paragraph in content.paragraphs for run in paragraph.runs],
            "guarded_properties": [{kind: sorted(name.removeprefix("{" + namespace + "}") for name in names)
                                    for kind, names in paragraph.property_uncertainty.items()}
                                   for paragraph in content.paragraphs if paragraph.text],
            "warnings": content.warnings}


def inspect_pdf(path: Path, case: str, observations: list[dict]) -> dict:
    import pdfplumber

    with pdfplumber.open(path) as pdf:
        characters = [character for page in pdf.pages for character in page.chars]
        sizes = sorted({round(character["size"], 3) for character in characters})
        fonts = sorted({character["fontname"] for character in characters})
        text = "".join("".join(character["text"] for character in characters).split())
        expected_sizes = {observation["size_pt"] for observation in observations}
        return {"page_count": len(pdf.pages), "sizes_pt": sizes, "fonts": fonts,
                "sample_text_complete": all(f"Sample{case}row{index}" in text for index in (1, 2, 3)),
                "sizes_match_com_within_0_1pt": bool(sizes) and
                all(any(abs(size - expected) <= 0.1 for expected in expected_sizes) for size in sizes)}


def render(progid: str, samples: list[tuple[str, Path]], output: Path) -> dict:
    if sys.platform != "win32":
        raise ValueError("Word/WPS COM版式核验仅支持Windows")
    pythoncom = importlib.import_module("pythoncom")
    client = importlib.import_module("win32com.client")

    pythoncom.CoInitialize()
    application = None
    owned = False
    results: dict[str, Any] = {"progid": progid, "registered_server": registered_server(progid), "cases": []}
    try:
        application = client.DispatchEx(progid)
        if int(application.Documents.Count) != 0:
            raise RuntimeError("New application instance is not empty; refusing to use it")
        owned = True
        application.Visible = False
        application.DisplayAlerts = 0
        application.AutomationSecurity = 3
        results["renderer_name"] = str(application.Name)
        results["renderer_version"] = str(application.Version)
        application.Documents.Add()
        for case, path in samples:
            opened = None
            try:
                opened = application.Documents.Open(str(path.resolve()), ReadOnly=True, AddToRecentFiles=False)
                opened.Repaginate()
                observations = []
                for index in range(1, 4):
                    cell_range = opened.Tables.Item(1).Cell(index, 1).Range
                    character = cell_range.Characters.Item(1)
                    observations.append({"row": index, "font": str(character.Font.Name),
                                         "size_pt": float(character.Font.Size),
                                         "line_spacing_rule": int(cell_range.ParagraphFormat.LineSpacingRule),
                                         "line_spacing_pt": float(cell_range.ParagraphFormat.LineSpacing)})
                pdf = output / f"{case}.pdf"
                opened.ExportAsFixedFormat(str(pdf.resolve()), 17)
                results["cases"].append({"case": case, "observations": observations,
                                         "pdf": inspect_pdf(pdf, case, observations), **_snapshot(path),
                                         "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest()})
            except Exception as error:
                results["cases"].append({"case": case, "error_type": type(error).__name__,
                                         "error_code": getattr(error, "hresult", None)})
            finally:
                if opened is not None:
                    try:
                        opened.Close(0)
                    except Exception as error:
                        results["cleanup_error_type"] = type(error).__name__
    except Exception as error:
        results["error_type"] = type(error).__name__
        results["error_code"] = getattr(error, "hresult", None)
    finally:
        if application is not None and owned:
            try:
                application.Quit()
            except Exception as error:
                results["cleanup_error_type"] = type(error).__name__
        pythoncom.CoUninitialize()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--progid", choices=["Word.Application", "KWPS.Application"], default="Word.Application")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Word/WPS COM版式核验仅支持Windows")
    for module in ("docx", "pythoncom", "pywintypes", "win32com.client", "winreg", "pdfplumber"):
        try:
            importlib.import_module(module)
        except ImportError:
            parser.error(f"Optional developer dependency is unavailable: {module}")
    args.output.mkdir(parents=True, exist_ok=True)
    samples = create_samples(args.output)
    results = render(args.progid, samples, args.output)
    (args.output / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"renderer": results.get("renderer_name"), "version": results.get("renderer_version"),
                      "case_count": len(results["cases"]),
                      "failed_count": sum("error_type" in case for case in results["cases"]),
                      "error_type": results.get("error_type")}, ensure_ascii=False))
    return 1 if (results.get("error_type") or results.get("cleanup_error_type")
                 or any("error_type" in case or not case["pdf"]["sample_text_complete"]
                        or not case["pdf"]["sizes_match_com_within_0_1pt"] for case in results["cases"])) else 0


if __name__ == "__main__":
    raise SystemExit(main())
