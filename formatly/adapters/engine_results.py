"""Classify documented component findings separately from execution failures."""
from __future__ import annotations

import math
import re

_DIGEST = re.compile(r"[0-9a-fA-F]{64}")
_MEASUREMENTS = ("title_top_pt", "title_to_abstract_gap_pt", "abstract_to_body_gap_pt")
_PROFILE_FIELDS = {
    "source_label", "source_registry_key", "source_docx_sha256", "calibration_pdf", "calibration_page",
    "measurement", "title_top_pt", "title_to_abstract_gap_pt", "abstract_to_body_gap_pt", "tolerance_pt", "title_max_lines",
}
_OBSERVATION_FIELDS = {
    "title_lines", "title_text", "title_top_pt", "title_to_abstract_gap_pt", "abstract_to_body_gap_pt",
    "abstract_top_pt", "body_top_pt", "physical_page",
}
_FINDING_FIELDS = {"rule_id", "level", "location", "message", "actual", "expected", "source"}


def _number(value) -> bool:
    try:
        return type(value) in {int, float} and math.isfinite(value)
    except OverflowError:
        return False


def _digest(value) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _positive_int(value) -> bool:
    return type(value) is int and value > 0


def completed_format_findings(name: str, engine: dict, report: dict) -> bool:
    """Recognize only the known paired-PDF abstract measurement return contract.

    This component uses ``error`` for a measured formatting deviation or a
    missing abstract location. Preserve its status and issues; do not reinterpret
    arbitrary component errors, exceptions, or incomplete PDF verification.
    """
    if (name != "abstract_layout_pdf" or engine.get("status") != "error"
            or set(engine) != {"status", "docx_pairing", "profile", "observations", "issues",
                              "english_title", "docx_sha256", "pdf_sha256"}
            or report.get("kind") != "thesis" or report.get("original_unchanged") is not True
            or report.get("snapshot_unchanged") is not True):
        return False
    if (not _digest(engine["docx_sha256"]) or not _digest(engine["pdf_sha256"])
            or not _digest(report.get("sha256"))
            or engine["docx_sha256"].lower() != report["sha256"].lower()):
        return False
    engines = report.get("engines")
    pdf = engines.get("pdf") if isinstance(engines, dict) else None
    if (not isinstance(pdf, dict) or pdf.get("status") != "screened" or not _digest(pdf.get("sha256"))
            or pdf["sha256"].lower() != engine["pdf_sha256"].lower()
            or not isinstance(engine["docx_pairing"], str) or not engine["docx_pairing"].strip()
            or pdf.get("docx_pairing") != engine["docx_pairing"]):
        return False
    profile = engine["profile"]
    if not isinstance(profile, dict) or set(profile) != _PROFILE_FIELDS:
        return False
    if any(not isinstance(profile[field], str) or not profile[field].strip() for field in (
            "source_label", "source_registry_key", "calibration_pdf", "measurement")):
        return False
    if (not _digest(profile["source_docx_sha256"]) or not _positive_int(profile["calibration_page"])
            or not _positive_int(profile["title_max_lines"])
            or not all(_number(profile[field]) for field in (*_MEASUREMENTS, "tolerance_pt"))
            or profile["tolerance_pt"] < 0):
        return False
    observations = engine["observations"]
    title = engine["english_title"]
    issues = engine["issues"]
    report_issues = report.get("issues")
    if (not isinstance(observations, list) or not isinstance(title, str)
            or not isinstance(issues, list) or not issues or not isinstance(report_issues, list)
            or (not title and observations)):
        return False
    for observation in observations:
        if (not isinstance(observation, dict) or set(observation) != _OBSERVATION_FIELDS
                or not _positive_int(observation["title_lines"])
                or observation["title_lines"] > profile["title_max_lines"]
                or not _positive_int(observation["physical_page"])
                or not isinstance(observation["title_text"], str) or not observation["title_text"].strip()
                or not all(_number(observation[field]) for field in (*_MEASUREMENTS, "abstract_top_pt", "body_top_pt"))):
            return False
    for issue in issues:
        if (not isinstance(issue, dict) or set(issue) != _FINDING_FIELDS or issue["level"] != "error"
                or any(not isinstance(issue[field], str) or not issue[field].strip()
                       for field in ("rule_id", "message", "location", "source"))
                or issue["source"] != profile["source_label"] or issue not in report_issues):
            return False
    if len(observations) != 1:
        actual = issues[0]["actual"]
        return (len(issues) == 1 and issues[0]["rule_id"] == "thesis.en_abstract_pdf.location"
                and issues[0]["expected"] is None and isinstance(actual, dict)
                and set(actual) == {"title", "matches"} and actual["title"] == title
                and type(actual["matches"]) is int and actual["matches"] == len(observations))
    if not title.strip():
        return False
    observation = observations[0]
    mismatches = {field for field in _MEASUREMENTS
                  if abs(observation[field] - profile[field]) > profile["tolerance_pt"]}
    if not mismatches or len(issues) != len(mismatches):
        return False
    found = set()
    for issue in issues:
        prefix = "thesis.en_abstract_pdf."
        rule_id = issue["rule_id"]
        field = rule_id[len(prefix):] if rule_id.startswith(prefix) else ""
        expected = issue["expected"]
        if (field not in mismatches or field in found or not _number(issue["actual"])
                or issue["actual"] != observation[field] or not isinstance(expected, dict)
                or set(expected) != {"target_pt", "tolerance_pt"}
                or not all(_number(expected[key]) for key in ("target_pt", "tolerance_pt"))
                or expected["target_pt"] != profile[field] or expected["tolerance_pt"] != profile["tolerance_pt"]):
            return False
        found.add(field)
    return found == mismatches
