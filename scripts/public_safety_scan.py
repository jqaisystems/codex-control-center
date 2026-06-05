from __future__ import annotations

import argparse
import os
import re
from pathlib import Path


PATTERNS = {
    "secret-assignment": re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|auth[_-]?token|password|secret|cookie)\s*[:=]\s*['\"]?(?!YOUR_|replace-with|test-|sk-thisisnotarealkey)[^'\"\s]{12,}"
    ),
    "secret-value": re.compile(r"sk-[A-Za-z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9._\-]{16,}"),
    "local-path": re.compile(r"[A-Za-z]:\\Users\\(?!Example\\|you\\)[^\\\s]+|/Users/(?!Example/|you/)[^/\s]+|/home/(?!example/|you/)[^/\s]+"),
    "private-db": re.compile(r"(?i)\.(sqlite|db|wal|shm)$"),
}

ALLOWLIST = {
    "Do not paste secrets",
    "auth.json ignored",
    "never reads auth token files",
    "CCC_CONTROL_TOKEN",
    "CCC_OTEL_TOKEN",
    "No API key required",
    "API key is optional",
    "auth.json, API keys",
    "C:\\Users\\Example",
    "thisisnotarealkey",
    "OPENAI_API_KEY=sk-thisisnotarealkey",
}


def scan(root: Path) -> list[str]:
    findings: list[str] = []
    skip_dirs = {"node_modules", ".git", ".venv", "__pycache__", "dist", ".pytest_cache", "logs"}
    screenshot_exts = {".png", ".jpg", ".jpeg", ".webp"}
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in skip_dirs]
        for filename in filenames:
            path = Path(current) / filename
            rel = path.relative_to(root)
            rel_posix = rel.as_posix()
            if rel_posix.startswith("docs/screenshots/") and path.suffix.lower() in screenshot_exts:
                continue
            if PATTERNS["private-db"].search(path.name):
                findings.append(f"{rel}: risky database-like file")
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                findings.append(f"{rel}: binary or non-UTF8 file")
                continue
            except OSError:
                continue
            for name, pattern in PATTERNS.items():
                if name == "private-db":
                    continue
                for match in pattern.finditer(text):
                    line = text.count("\n", 0, match.start()) + 1
                    sample = text[max(0, match.start() - 40) : match.end() + 40]
                    if name == "local-path" and str(rel).replace("\\", "/") in {
                        "backend/privacy.py",
                        "scripts/public_safety_scan.py",
                    }:
                        continue
                    if any(allowed in sample for allowed in ALLOWLIST):
                        continue
                    findings.append(f"{rel}:{line}: {name}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Scan public candidate files for obvious private material.")
    parser.add_argument("path", nargs="?", default=".")
    args = parser.parse_args()
    findings = scan(Path(args.path).resolve())
    if findings:
        print("BLOCK")
        for finding in findings:
            print(f"- {finding}")
        return 1
    print("READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
