from __future__ import annotations

import hashlib
import re
from pathlib import PureWindowsPath


SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)\s*[:=]\s*['\"]?[^'\"\s]+"),
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"),
]

PATH_PATTERNS = [
    re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\[^\n\r\t]+"),
    re.compile(r"/Users/[^/\s]+/[^\n\r\t]+"),
    re.compile(r"/home/[^/\s]+/[^\n\r\t]+"),
]


def stable_hash(value: str, length: int = 10) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:length]


def contains_sensitive_text(value: str | None) -> bool:
    if not value:
        return False
    return any(pattern.search(value) for pattern in SECRET_PATTERNS + PATH_PATTERNS)


def redact_text(value: str | None, replacement: str = "[redacted]") -> str | None:
    if value is None:
        return None
    redacted = value
    for pattern in SECRET_PATTERNS + PATH_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def project_label(cwd: str | None) -> tuple[str, str | None]:
    """Return a safe project label and stable hash without exposing full paths."""
    if not cwd:
        return "unknown", None
    normalized = cwd.replace("/", "\\")
    name = PureWindowsPath(normalized).name or "workspace"
    return f"{name}#{stable_hash(cwd, 6)}", stable_hash(cwd, 16)


def safe_relative_path(path: str, anchor: str) -> str:
    path_norm = path.replace("\\", "/")
    anchor_norm = anchor.replace("\\", "/").rstrip("/")
    if path_norm.startswith(anchor_norm + "/"):
        return path_norm[len(anchor_norm) + 1 :]
    return f"outside-codex-home/{stable_hash(path_norm, 10)}"
