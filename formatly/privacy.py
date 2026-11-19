"""Remove local filesystem identities from public diagnostic text."""
from __future__ import annotations

import re
from os import PathLike, fspath


def redact_local_paths(value: str, *paths: str | PathLike[str] | None) -> str:
    text = str(value)
    replacements: set[str] = set()
    for path in paths:
        if path is not None:
            raw = fspath(path)
            replacements.update((raw, raw.replace('\\', '/'), raw.replace('/', '\\')))
    for raw in sorted(replacements, key=len, reverse=True):
        if raw:
            text = re.sub(re.escape(raw), '<local-path>', text, flags=re.IGNORECASE)
    # Consume quoted paths first: an apostrophe is a valid directory character
    # inside a double-quoted filename (and conversely for a double quote).
    text = re.sub(r'''(?P<quote>["'])(?:[a-zA-Z]:[\\/]|\\\\|/)(?:\\[^\r\n]|(?!(?P=quote))[^\\\r\n])*(?P=quote)''',
                  lambda match: match.group("quote") + '<local-path>' + match.group("quote"), text)
    # Unquoted filenames have no reliable terminator: spaces and either quote
    # can belong to a POSIX path. Omit the remainder of that diagnostic line;
    # quoted tracebacks above retain their line number and exception details.
    text = re.sub(r'''(?i)(?<!\w)(?:[a-z]:[\\/]|\\\\[^\\\s]+\\)[^\r\n]*''',
                  '<local-path>', text)
    text = re.sub(r'''(?<![\w:/])/(?!/)(?=\S)[^\r\n]*''', '<local-path>', text)
    return text


def public_ocr_information(value: dict) -> dict:
    """Expose OCR capability/evidence without process paths or private fields."""
    public = {key: value[key] for key in ("available", "languages", "selected_languages", "processed_pages")
              if key in value}
    executable = value.get("executable")
    public["reason"] = redact_local_paths(value.get("reason", ""),
                                          executable if isinstance(executable, (str, PathLike)) else None)
    return public
