from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .privacy import stable_hash


FRONTMATTER_RE = re.compile(r"^---\s*\n(?P<body>.*?)\n---", re.S)


def _read_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    match = FRONTMATTER_RE.match(text)
    data: dict[str, str] = {}
    if not match:
        data["name"] = path.parent.name
        data["description"] = ""
        return data
    for line in match.group("body").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip().strip("\"'")
        data[key.strip()] = value
    data.setdefault("name", path.parent.name)
    data.setdefault("description", "")
    return data


def _skill_roots(codex_home: Path, repo_root: Path) -> list[tuple[str, Path]]:
    home = Path.home()
    return [
        ("repo", repo_root / ".agents" / "skills"),
        ("user-agents", home / ".agents" / "skills"),
        ("user-codex", codex_home / "skills"),
        ("plugin-cache", codex_home / "plugins" / "cache"),
    ]


def discover_skills(codex_home: Path, repo_root: Path) -> list[dict[str, Any]]:
    discovered: list[dict[str, Any]] = []
    for scope, root in _skill_roots(codex_home, repo_root):
        if not root.exists():
            continue
        pattern = "**/SKILL.md" if scope == "plugin-cache" else "*/SKILL.md"
        for skill_file in root.glob(pattern):
            try:
                meta = _read_frontmatter(skill_file)
                stat = skill_file.stat()
                skill_path = str(skill_file.resolve())
            except (OSError, RuntimeError):
                continue
            plugin_name = None
            if scope == "plugin-cache":
                parts = skill_file.parts
                plugin_name = parts[-4] if len(parts) >= 4 else None
            discovered.append(
                {
                    "name": meta.get("name") or skill_file.parent.name,
                    "scope": scope,
                    "description": meta.get("description") or "",
                    "path_label": f"{scope}/{skill_file.parent.name}#{stable_hash(str(skill_file), 6)}",
                    "skill_path": skill_path,
                    "plugin_name": plugin_name,
                    "enabled": 1,
                    "last_modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    return discovered


def sync_skills(conn: sqlite3.Connection, codex_home: Path, repo_root: Path) -> dict[str, int]:
    skills = discover_skills(codex_home, repo_root)
    conn.execute("DELETE FROM skills")
    for skill in skills:
        conn.execute(
            """
            INSERT INTO skills(name, scope, description, path_label, skill_path, plugin_name, enabled, last_modified, synced_at)
            VALUES (:name, :scope, :description, :path_label, :skill_path, :plugin_name, :enabled, :last_modified, datetime('now'))
            """,
            skill,
        )
    conn.commit()
    return {"skills": len(skills)}
