"""Confirm a source submission leaves out generated files and secrets."""
from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".txt", ".json", ".vue", ".ts", ".js", ".css", ".toml", ".yml", ".yaml",
                 ".cmd", ".sh", ".html", ".xml", ".mjs", ".svg"}
GENERATED_NAMES = {
    "__pycache__", ".venv", "node_modules", "dist", ".vite", ".vite-temp", ".ruff_cache", ".mypy_cache",
    ".pytest_cache", ".formatly", ".verification", "reports", ".idea", "coverage", "playwright-report",
    "test-results", "blob-report", ".cache",
}
SECRET_PATTERNS = (
    ("私钥", re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----")),
    ("云访问密钥", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("托管令牌", re.compile(r"ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("赋值密钥", re.compile(r"(?i)\b(?:api[_-]?key|client[_-]?secret|password|passwd)\b\s*[:=]\s*['\"][^'\"]{12,}['\"]")),
)
PLACEHOLDER = re.compile(r"(?i)example|changeme|placeholder|redacted|your[-_ ]|todo|anonymous")
LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")


def _rules() -> list[tuple[str, bool, bool]]:
    """Return (pattern, directory-only, match-any-component) ignore rules."""
    loaded = [(ROOT / ".gitignore", "")]
    frontend = ROOT / "frontend" / ".gitignore"
    if frontend.is_file():
        loaded.append((frontend, "frontend/"))
    rules = []
    for path, prefix in loaded:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("!"):
                continue
            anchored = line.startswith("/")
            directory = line.endswith("/")
            pattern = prefix + line.strip("/")
            rules.append((pattern, directory, not anchored and "/" not in pattern))
    return rules


def _ignored(relative: str, is_dir: bool, rules: list[tuple[str, bool, bool]]) -> bool:
    parts = relative.split("/")
    for pattern, directory, anywhere in rules:
        if anywhere:
            names = parts if directory or is_dir else parts[-1:]
            if directory:
                names = parts[:-1] if not is_dir else parts
            if any(fnmatch(name, pattern) for name in names):
                return True
            continue
        if relative == pattern or relative.startswith(pattern + "/"):
            return True
        if directory and is_dir and fnmatch(relative, pattern):
            return True
    return False


def _generated(relative: str) -> bool:
    parts = set(relative.split("/"))
    if parts & GENERATED_NAMES:
        return True
    name = relative.rsplit("/", 1)[-1]
    return name.endswith((".pyc", ".pyo", ".tsbuildinfo")) or ".egg-info" in name


def _secret(text: str) -> str | None:
    for label, pattern in SECRET_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue
        if label == "赋值密钥" and PLACEHOLDER.search(match.group(0)):
            continue
        return label
    return None


def _links(path: Path, text: str) -> list[str]:
    missing = []
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        local = target.split("#", 1)[0]
        if not local:
            continue
        resolved = (path.parent / local).resolve()
        try:
            resolved.relative_to(ROOT)
        except ValueError:
            missing.append(target)
            continue
        if not resolved.exists():
            missing.append(target)
    return missing


def main() -> int:
    rules = _rules()
    problems = []
    tracked = 0
    ignored_generated = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        generated = _generated(relative)
        if _ignored(relative, False, rules):
            ignored_generated += int(generated)
            continue
        tracked += 1
        if generated:
            problems.append(f"生成物未被忽略：{relative}")
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 1_500_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            problems.append(f"文本不是 UTF-8：{relative}")
            continue
        secret = _secret(text)
        if secret:
            problems.append(f"疑似{secret}：{relative}")
        if path.suffix.lower() == ".md":
            problems.extend(f"文档链接不存在：{relative} -> {item}" for item in _links(path, text))
    if problems:
        print("提交前检查未通过：")
        print("\n".join("- " + item for item in problems))
        return 1
    print(f"提交前检查通过：可提交文件 {tracked} 个；本机生成物 {ignored_generated} 个已忽略。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
