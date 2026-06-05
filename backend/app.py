from __future__ import annotations

import os
import json
import signal
import sqlite3
import subprocess
import sys
import time
from fnmatch import fnmatchcase
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .codex_cli import codex_executable
from .codex_parser import sync_sessions
from .db import connect, init_db, log_activity, row, rows
from .otel import ingest_logs, ingest_metrics
from .privacy import contains_sensitive_text, project_label
from .settings import APP_STARTED_AT, ensure_app_dirs, load_settings
from .skills import sync_skills
from .task_runner import ALLOWED_SANDBOXES, launch_task, now_iso


settings = load_settings()
ensure_app_dirs(settings)
conn = connect(settings.db_path)
init_db(conn)
repo_root = Path(__file__).resolve().parents[1]

app = FastAPI(title="Codex Control Center", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173", "http://127.0.0.1:8765", "http://localhost:8765"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["*"],
)


def _is_loopback(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in {"127.0.0.1", "::1", "localhost"}


def require_control(request: Request) -> None:
    if settings.control_token:
        expected = f"Bearer {settings.control_token}"
        if request.headers.get("authorization") != expected and request.headers.get("x-control-token") != settings.control_token:
            raise HTTPException(status_code=401, detail="Missing or invalid local control token")
    elif not _is_loopback(request):
        raise HTTPException(status_code=403, detail="Control actions are loopback-only")


def require_otel(request: Request) -> None:
    if settings.otel_token:
        expected = f"Bearer {settings.otel_token}"
        if request.headers.get("authorization") != expected:
            raise HTTPException(status_code=401, detail="Missing or invalid OTel token")
    elif not _is_loopback(request):
        raise HTTPException(status_code=403, detail="OTel ingest is loopback-only")


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4000)
    priority: int = Field(default=3, ge=1, le=4)
    sandbox: str = "read-only"
    scheduled_for: str | None = None
    workspace_id: int | None = Field(default=None, ge=1)


class ScheduleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cron_expression: str = Field(min_length=3, max_length=80)
    task_title: str = Field(min_length=1, max_length=160)
    task_description: str = Field(min_length=1, max_length=4000)
    enabled: bool = True
    workspace_id: int | None = Field(default=None, ge=1)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    path: str | None = Field(default=None, min_length=1, max_length=1200)
    browser_token: str | None = Field(default=None, min_length=1, max_length=200)


class WorkspaceBrowserRootCreate(BaseModel):
    path: str = Field(min_length=1, max_length=1200)
    name: str | None = Field(default=None, min_length=1, max_length=120)


class ScheduleToggle(BaseModel):
    enabled: bool


class SystemModeUpdate(BaseModel):
    mode: str = Field(min_length=1, max_length=40)


class HealthReportReviewUpdate(BaseModel):
    workspace_id: int | None = Field(default=None, ge=1)
    review_key: str = Field(min_length=1, max_length=600)
    status: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    scan_mode: str = Field(default="standard", min_length=1, max_length=20)


class HealthReportReviewBulkUpdate(BaseModel):
    workspace_id: int | None = Field(default=None, ge=1)
    review_keys: list[str] = Field(min_length=1, max_length=500)
    status: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    scan_mode: str = Field(default="standard", min_length=1, max_length=20)


CRON_ALIASES = {
    "@hourly": "0 * * * *",
    "@daily": "0 9 * * *",
    "@weekly": "0 9 * * 1",
}

WORKSPACE_RESPONSE_FIELDS = ("id", "name", "path_label", "path_hash", "is_default", "created_at", "updated_at")
ACTIVE_TASK_STATUSES = ("awaiting_approval", "pending", "running")
WORKSPACE_BROWSER_TOKEN_TTL_SECONDS = 1800
WORKSPACE_BROWSER_MAX_CHILDREN = 250
WORKSPACE_SCORE_MAX_ENTRIES = 1000
WORKSPACE_SCORE_MAX_DEPTH = 3
WORKSPACE_DEEP_SCAN_MAX_ENTRIES = 5000
WORKSPACE_DEEP_SCAN_MAX_DEPTH = 5
WORKSPACE_GITIGNORE_MAX_BYTES = 128 * 1024
HEALTH_REVIEW_STATUSES = {"needs_action", "reviewed", "accepted_risk", "ignore_for_now"}
SYSTEM_MODES = {"full", "balanced", "token_saver"}
DEFAULT_SYSTEM_MODE = "full"
SECRET_LIKE_NAMES = {".env", ".env.local", ".env.production", ".env.development", ".env.test", "auth.json"}
DATABASE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
GENERATED_DIR_NAMES = {"node_modules", ".venv", "venv", "dist", "build", ".next", "target", "__pycache__", ".pytest_cache"}
workspace_browser_tokens: dict[str, tuple[Path, Path, float]] = {}


def _workspace_response(item: dict[str, Any] | sqlite3.Row) -> dict[str, Any]:
    data = dict(item)
    return {field: data[field] for field in WORKSPACE_RESPONSE_FIELDS}


def _normalized_path(value: Path) -> str:
    return os.path.normcase(os.path.abspath(str(value)))


def _system_mode() -> str:
    item = row(conn, "SELECT value FROM system_state WHERE key='system_mode'")
    mode = str(item["value"]) if item and item.get("value") else DEFAULT_SYSTEM_MODE
    return mode if mode in SYSTEM_MODES else DEFAULT_SYSTEM_MODE


def _set_system_mode(mode: str) -> str:
    normalized = mode.strip().lower()
    if normalized not in SYSTEM_MODES:
        raise HTTPException(status_code=400, detail="Unknown system mode")
    conn.execute(
        """
        INSERT INTO system_state(key, value, updated_at)
        VALUES ('system_mode', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (normalized, now_iso()),
    )
    conn.commit()
    return normalized


def _system_mode_payload() -> dict[str, Any]:
    mode = _system_mode()
    return {
        "mode": mode,
        "presets": [
            {"id": "full", "label": "Full", "description": "All dashboard features and current refresh cadence."},
            {"id": "balanced", "label": "Balanced", "description": "All features available with slower noncritical polling."},
            {"id": "token_saver", "label": "Token Saver", "description": "Blocks dashboard task launches and pauses heavier dashboard refreshes."},
        ],
        "token_saver_active": mode == "token_saver",
    }


def _is_codex_config_path(path: Path) -> bool:
    codex_home = settings.codex_home.expanduser().resolve(strict=False)
    path_norm = _normalized_path(path.expanduser().resolve(strict=False))
    codex_norm = _normalized_path(codex_home).rstrip("\\/")
    return path_norm == codex_norm or path_norm.startswith(f"{codex_norm}{os.sep}")


def _folder_label(path: Path) -> str:
    if path.name:
        return path.name
    if path.drive:
        return path.drive
    return "Root"


def _cleanup_workspace_browser_tokens() -> None:
    now = time.time()
    expired = [token for token, (_, _, expires_at) in workspace_browser_tokens.items() if expires_at <= now]
    for token in expired:
        workspace_browser_tokens.pop(token, None)


def _is_path_inside_root(path: Path, root: Path) -> bool:
    path_norm = _normalized_path(path).rstrip("\\/")
    root_norm = _normalized_path(root).rstrip("\\/")
    return path_norm == root_norm or path_norm.startswith(f"{root_norm}{os.sep}")


def _register_browser_path(path: Path, root: Path | None = None) -> str:
    _cleanup_workspace_browser_tokens()
    resolved_path = path.expanduser().resolve(strict=True)
    resolved_root = (root or resolved_path).expanduser().resolve(strict=True)
    if not _is_path_inside_root(resolved_path, resolved_root):
        raise HTTPException(status_code=400, detail="Folder is outside the selected browse root")
    token = uuid4().hex
    workspace_browser_tokens[token] = (
        resolved_path,
        resolved_root,
        time.time() + WORKSPACE_BROWSER_TOKEN_TTL_SECONDS,
    )
    return token


def _browser_token_path(token: str) -> tuple[Path, Path]:
    _cleanup_workspace_browser_tokens()
    item = workspace_browser_tokens.get(token)
    if not item:
        raise HTTPException(status_code=404, detail="Folder selection expired; choose the folder again")
    path, root, expires_at = item
    if expires_at <= time.time():
        workspace_browser_tokens.pop(token, None)
        raise HTTPException(status_code=404, detail="Folder selection expired; choose the folder again")
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail="Folder is unavailable")
    if _is_codex_config_path(path):
        raise HTTPException(status_code=400, detail="Codex auth/config folders cannot be selected")
    if not _is_path_inside_root(path, root):
        raise HTTPException(status_code=400, detail="Folder is outside the selected browse root")
    return path, root


def _browser_item(path: Path, label: str | None = None, *, kind: str = "folder", root: Path | None = None) -> dict[str, Any]:
    return {"label": label or _folder_label(path), "token": _register_browser_path(path, root), "kind": kind}


def _workspace_browser_roots() -> list[dict[str, Any]]:
    candidates: list[tuple[str | None, Path, str]] = []
    configured = os.environ.get("CCC_WORKSPACE_BROWSER_ROOTS")
    if configured:
        for raw_path in configured.split(os.pathsep):
            if raw_path.strip():
                candidates.append((None, Path(raw_path.strip()), "folder"))
    else:
        default_root = repo_root.parents[2] if len(repo_root.parents) >= 3 else repo_root.parent
        candidates.append((None, default_root, "folder"))

    seen: set[str] = set()
    roots: list[dict[str, Any]] = []
    for label, path, kind in candidates:
        try:
            resolved = path.expanduser().resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        if not resolved.is_dir() or _is_codex_config_path(resolved):
            continue
        normalized = _normalized_path(resolved)
        if normalized in seen:
            continue
        seen.add(normalized)
        roots.append(_browser_item(resolved, label or _folder_label(resolved), kind=kind, root=resolved))
    return roots


def _default_workspace_root() -> Path:
    configured = os.environ.get("CCC_DEFAULT_WORKSPACE_PATH") or os.environ.get("CCC_WORKSPACE_BROWSER_ROOTS", "").split(os.pathsep)[0]
    if configured:
        return _safe_resolve_existing_dir(configured)
    if len(repo_root.parents) >= 3:
        return repo_root.parents[2].resolve(strict=True)
    return repo_root.resolve(strict=True)


def _workspace_browser_folder(token: str) -> dict[str, Any]:
    current, root = _browser_token_path(token)
    breadcrumb_paths = []
    cursor = current
    while True:
        breadcrumb_paths.append(cursor)
        if _normalized_path(cursor) == _normalized_path(root):
            break
        parent = cursor.parent
        if parent == cursor or not _is_path_inside_root(parent, root):
            break
        cursor = parent
    breadcrumbs = [_browser_item(path, root=root) for path in reversed(breadcrumb_paths)]
    children: list[dict[str, Any]] = []
    try:
        candidates = sorted(
            (child for child in current.iterdir() if child.is_dir()),
            key=lambda child: child.name.lower(),
        )
    except OSError:
        candidates = []
    for child in candidates:
        if len(children) >= WORKSPACE_BROWSER_MAX_CHILDREN:
            break
        try:
            resolved = child.resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        if _is_codex_config_path(resolved):
            continue
        children.append(_browser_item(resolved, root=root))
    return {
        "current": _browser_item(current, root=root),
        "breadcrumbs": breadcrumbs,
        "children": children,
        "truncated": len(children) >= WORKSPACE_BROWSER_MAX_CHILDREN,
    }


def _safe_resolve_existing_dir(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail="Workspace path does not exist") from exc
    except OSError as exc:
        raise HTTPException(status_code=400, detail="Workspace path could not be resolved") from exc
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="Workspace path must be a directory")
    if _is_codex_config_path(resolved):
        raise HTTPException(status_code=400, detail="Codex auth/config folders cannot be registered as workspaces")
    return resolved


def _ensure_default_workspace() -> dict[str, Any]:
    workspace_root = _default_workspace_root()
    label, path_hash = project_label(str(workspace_root))
    existing = row(conn, "SELECT * FROM workspaces WHERE root_path=?", (str(workspace_root),))
    timestamp = now_iso()
    name = f"{_folder_label(workspace_root)} Vault"
    if existing:
        conn.execute(
            """
            UPDATE workspaces
            SET name=?, path_label=?, path_hash=?, is_default=1, updated_at=?
            WHERE id=?
            """,
            (name, label, path_hash, timestamp, existing["id"]),
        )
        workspace_id = int(existing["id"])
    else:
        cur = conn.execute(
            """
            INSERT INTO workspaces(name, root_path, path_label, path_hash, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (name, str(workspace_root), label, path_hash, timestamp, timestamp),
        )
        workspace_id = int(cur.lastrowid)
    conn.execute("UPDATE workspaces SET is_default=0, updated_at=? WHERE id<>? AND is_default=1", (timestamp, workspace_id))
    conn.commit()
    workspace = row(conn, "SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    if workspace is None:
        raise HTTPException(status_code=500, detail="Default workspace could not be loaded")
    return workspace


def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _publish_check(check_id: str, label: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "label": label, "status": status, "detail": detail}


def _git_status_counts() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "changed": 0, "staged": 0, "untracked": 0}
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    return {
        "available": result.returncode == 0,
        "changed": len(lines),
        "staged": sum(1 for line in lines if len(line) >= 1 and line[0] not in {" ", "?"}),
        "untracked": sum(1 for line in lines if line.startswith("??")),
    }


def _public_safety_scan_findings() -> list[str]:
    try:
        from scripts.public_safety_scan import scan

        return scan(repo_root)
    except Exception as exc:
        return [f"scanner unavailable: {type(exc).__name__}"]


def _publish_readiness_payload() -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    required_files = [
        "README.md",
        "ARCHITECTURE.md",
        "SECURITY.md",
        "PUBLICATION_CHECKLIST.md",
        "LICENSE",
        ".gitignore",
        ".env.example",
        "requirements.txt",
        "start-control-center.ps1",
    ]
    required_dirs = ["backend", "scripts", "tests", "fixtures", "ui", "docs"]
    missing_files = [name for name in required_files if not (repo_root / name).is_file()]
    missing_dirs = [name for name in required_dirs if not (repo_root / name).is_dir()]
    checks.append(
        _publish_check(
            "required-files",
            "Required public files",
            "block" if missing_files or missing_dirs else "ok",
            "Missing: " + ", ".join(missing_files + missing_dirs) if missing_files or missing_dirs else "Core public package files and folders are present.",
        )
    )

    readme = _read_text_file(repo_root / "README.md")
    readme_ok = "No API key required for local observation" in readme and "Windows 11" in readme and "127.0.0.1" in readme
    checks.append(
        _publish_check(
            "readme-positioning",
            "README positioning",
            "ok" if readme_ok else "review",
            "README states local observation needs no API key and includes Windows-first setup." if readme_ok else "Review README for no-API and Windows setup wording.",
        )
    )

    gitignore = _read_text_file(repo_root / ".gitignore")
    required_ignores = [
        ".env",
        ".env.*",
        "!.env.example",
        "auth.json",
        "*.sqlite",
        "*.sqlite-shm",
        "*.sqlite-wal",
        "*.db",
        "*.db-shm",
        "*.db-wal",
        "*.log",
        "logs/",
        "ui/node_modules/",
        "ui/dist/",
        ".venv/",
    ]
    missing_ignores = [pattern for pattern in required_ignores if pattern not in gitignore]
    checks.append(
        _publish_check(
            "gitignore-coverage",
            ".gitignore coverage",
            "block" if missing_ignores else "ok",
            "Missing ignore rules: " + ", ".join(missing_ignores) if missing_ignores else "Risky local runtime and generated paths are covered.",
        )
    )

    blocked_root_names = [name for name in [".env", "auth.json"] if (repo_root / name).exists()]
    root_databases = [path.name for path in repo_root.glob("*.sqlite*")]
    checks.append(
        _publish_check(
            "blocked-root-files",
            "Blocked root files",
            "block" if blocked_root_names or root_databases else "ok",
            "Remove before publishing: " + ", ".join(blocked_root_names + root_databases) if blocked_root_names or root_databases else "No blocked root files were found.",
        )
    )

    local_artifact_patterns = {
        ".venv": ".venv/",
        "logs": "logs/",
        "ui/node_modules": "ui/node_modules/",
        "ui/dist": "ui/dist/",
    }
    local_artifacts = [name for name in local_artifact_patterns if (repo_root / name).exists()]
    uncovered_artifacts = [name for name in local_artifacts if local_artifact_patterns[name] not in gitignore]
    checks.append(
        _publish_check(
            "local-artifacts",
            "Local-only artifacts",
            "review" if uncovered_artifacts else "ok",
            "Present locally but covered by .gitignore: " + ", ".join(local_artifacts) if local_artifacts and not uncovered_artifacts else "Present locally and need ignore coverage: " + ", ".join(uncovered_artifacts) if uncovered_artifacts else "No common local-only artifact folders were found.",
        )
    )

    fixtures_present = any((repo_root / "fixtures").glob("*"))
    checks.append(
        _publish_check(
            "fake-fixtures",
            "Fake fixtures",
            "ok" if fixtures_present else "review",
            "Fixture folder contains sample files for tests and demos." if fixtures_present else "Add fake fixtures before publishing examples.",
        )
    )

    scan_findings = _public_safety_scan_findings()
    checks.append(
        _publish_check(
            "public-safety-scan",
            "Public safety scan",
            "block" if scan_findings else "ok",
            "Scanner findings need review." if scan_findings else "Scanner returned READY.",
        )
    )

    git_status = _git_status_counts()
    checks.append(
        _publish_check(
            "git-review",
            "Git diff review",
            "review" if (not git_status["available"] or git_status["changed"] > 0) else "ok",
            "Manual git review remains before staging or committing." if git_status["changed"] > 0 else "No changed files reported by git." if git_status["available"] else "Git status unavailable; run manual review.",
        )
    )

    status = "ready"
    if any(check["status"] == "block" for check in checks):
        status = "blocked"
    elif any(check["status"] == "review" for check in checks):
        status = "needs_review"
    label, path_hash = project_label(str(repo_root))
    return {
        "generated_at": now_iso(),
        "status": status,
        "package": {"name": repo_root.name, "path_label": label, "path_hash": path_hash},
        "summary": {
            "checks": len(checks),
            "ok": sum(1 for check in checks if check["status"] == "ok"),
            "review": sum(1 for check in checks if check["status"] == "review"),
            "block": sum(1 for check in checks if check["status"] == "block"),
        },
        "safety_scan": {
            "status": "BLOCK" if scan_findings else "READY",
            "finding_count": len(scan_findings),
        },
        "git": git_status,
        "checks": checks,
        "next_steps": [
            "Review every item marked review or block.",
            "Run python -m pytest, npm run build, and python scripts/public_safety_scan.py . before commit.",
            "Inspect git status and staged diff manually.",
            "Stage named files only; do not use git add . for this package.",
            "Commit and push only after an explicit human approval.",
        ],
        "does_not_publish": True,
    }


def _workspace_or_default(workspace_id: int | None) -> dict[str, Any]:
    _ensure_default_workspace()
    if workspace_id is None:
        workspace = row(conn, "SELECT * FROM workspaces WHERE is_default=1 ORDER BY id LIMIT 1")
    else:
        workspace = row(conn, "SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    root_path = Path(workspace["root_path"])
    if not root_path.exists() or not root_path.is_dir():
        raise HTTPException(status_code=400, detail="Workspace folder is unavailable")
    return workspace


def _clamped_score(value: int | float) -> int:
    return max(0, min(100, int(round(value))))


def _deduct(score: int, findings: list[dict[str, str]], points: int, level: str, title: str, detail: str) -> int:
    findings.append({"level": level, "title": title, "detail": detail})
    return max(0, score - points)


def _ok(findings: list[dict[str, str]], title: str, detail: str) -> None:
    findings.append({"level": "ok", "title": title, "detail": detail})


def _age_seconds_from_iso(value: Any) -> int | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int(time.time() - parsed.timestamp()))
    except ValueError:
        return None


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _codex_config_text() -> str:
    config_path = settings.codex_home / "config.toml"
    if not config_path.exists():
        return ""
    try:
        return config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _usage_metadata_age_seconds() -> int | None:
    limit = row(conn, "SELECT observed_at FROM usage_limits WHERE id=1")
    if not limit:
        return None
    return _age_seconds_from_iso(limit.get("observed_at"))


def _system_readiness_score() -> tuple[int, list[dict[str, str]]]:
    score = 100
    findings: list[dict[str, str]] = []
    version = codex_version()
    login = codex_login_status()
    config_text = _codex_config_text()

    if settings.codex_home.exists():
        _ok(findings, "System: Codex home found", "Local Codex metadata folder is present.")
    else:
        score = _deduct(score, findings, 10, "bad", "System: Codex home missing", "Local Codex metadata folder was not found.")

    if version:
        _ok(findings, "System: Codex CLI found", "Codex CLI version is available.")
    else:
        score = _deduct(score, findings, 20, "bad", "System: Codex CLI missing", "Control Mode needs the local Codex CLI.")

    if login.get("available"):
        _ok(findings, "System: Control Mode available", "Codex can launch approval-gated local tasks.")
    else:
        score = _deduct(score, findings, 10, "warn", "System: Control Mode unavailable", "Task launching is unavailable until Codex login is ready.")

    if settings.metadata_only:
        _ok(findings, "System: Metadata-only mode", "Prompt and assistant output storage is disabled by default.")
    else:
        score = _deduct(score, findings, 8, "warn", "System: Content opt-in mode", "Review privacy settings before publishing or sharing output.")

    last_sync = _last_sync()
    sync_age = _age_seconds_from_iso(last_sync.get("created_at") if last_sync else None)
    if sync_age is None:
        score = _deduct(score, findings, 10, "warn", "System: No sync yet", "Run sync so dashboard metadata is current.")
    elif sync_age > 3600:
        score = _deduct(score, findings, 6, "warn", "System: Sync is stale", "Local metadata was last synced more than 1 hour ago.")
    else:
        _ok(findings, "System: Sync is fresh", "Local metadata was synced recently.")

    if _session_file_count() == 0:
        score = _deduct(score, findings, 5, "info", "System: No sessions parsed", "Run Codex once so local activity metadata can be observed.")
    else:
        _ok(findings, "System: Sessions available", "Local Codex session metadata is available.")

    usage_age = _usage_metadata_age_seconds()
    if usage_age is None:
        score = _deduct(score, findings, 4, "info", "System: Usage metadata missing", "Usage Remaining appears after Codex emits local rate-limit metadata.")
    elif usage_age > 3600:
        score = _deduct(score, findings, 4, "warn", "System: Usage metadata stale", "Usage Remaining metadata is older than 1 hour.")
    else:
        _ok(findings, "System: Usage metadata fresh", "Usage Remaining metadata is available from local sessions.")

    if "danger-full-access" in config_text:
        score = _deduct(score, findings, 8, "warn", "System: Full-access config mention", "Review Codex sandbox defaults before enabling unattended tasks.")
    if "log_user_prompt = true" in config_text:
        score = _deduct(score, findings, 8, "warn", "System: Prompt logging enabled", "Disable prompt logging if you want metadata-only telemetry.")

    _ok(findings, "System: auth.json ignored", "The dashboard does not read Codex auth token files.")
    _ok(findings, "System: API key not required", "The dashboard does not call OpenAI directly.")
    return _clamped_score(score), findings


def _scan_limits(scan_mode: str | None) -> tuple[str, int, int]:
    mode = (scan_mode or "standard").strip().lower()
    if mode == "standard":
        return "standard", WORKSPACE_SCORE_MAX_ENTRIES, WORKSPACE_SCORE_MAX_DEPTH
    if mode == "deep":
        return "deep", WORKSPACE_DEEP_SCAN_MAX_ENTRIES, WORKSPACE_DEEP_SCAN_MAX_DEPTH
    raise HTTPException(status_code=400, detail="Unknown scan mode")


def _workspace_metadata_entries(root: Path, *, max_entries: int | None = None, max_depth: int | None = None) -> tuple[list[dict[str, Any]], bool]:
    max_entries = max_entries or WORKSPACE_SCORE_MAX_ENTRIES
    max_depth = max_depth or WORKSPACE_SCORE_MAX_DEPTH
    entries: list[dict[str, Any]] = []
    stack: list[tuple[Path, int]] = [(root, 0)]
    truncated = False
    while stack and len(entries) < max_entries:
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda child: child.name.lower())
        except OSError as exc:
            if current == root:
                raise HTTPException(status_code=400, detail="Workspace folder cannot be read") from exc
            continue
        for child in children:
            if len(entries) >= max_entries:
                truncated = True
                break
            try:
                is_dir = child.is_dir()
                is_symlink = child.is_symlink()
            except OSError:
                continue
            try:
                relative_path = child.relative_to(root)
                parts = tuple(part.lower() for part in relative_path.parts)
            except ValueError:
                relative_path = Path(child.name)
                parts = (child.name.lower(),)
            entries.append(
                {
                    "name": child.name.lower(),
                    "display_name": child.name,
                    "parts": parts,
                    "relative_path": relative_path.as_posix(),
                    "full_path": str(child),
                    "depth": depth + 1,
                    "is_dir": is_dir,
                    "is_symlink": is_symlink,
                    "suffix": child.suffix.lower(),
                }
            )
            if is_dir and not is_symlink and depth + 1 < max_depth:
                stack.append((child, depth + 1))
    if stack:
        truncated = True
    return entries, truncated


def _workspace_readiness_from_entries(entries: list[dict[str, Any]], truncated: bool) -> tuple[int, list[dict[str, str]]]:
    score = 100
    findings: list[dict[str, str]] = []
    names = {entry["name"] for entry in entries}
    root_names = {entry["name"] for entry in entries if entry["depth"] == 1}
    dir_names = {entry["name"] for entry in entries if entry["is_dir"]}

    if entries:
        _ok(findings, "Workspace: Folder readable", "Workspace metadata can be scanned without reading file contents.")
    else:
        score = _deduct(score, findings, 12, "warn", "Workspace: Folder is empty", "No files or folders were found in the selected workspace.")

    if any(name.startswith("readme") for name in names):
        _ok(findings, "Workspace: README present", "A README-style file helps people understand the workspace.")
    else:
        score = _deduct(score, findings, 12, "warn", "Workspace: README missing", "Add a README so the workspace has a clear public entry point.")

    if "docs" in dir_names:
        _ok(findings, "Workspace: Docs folder present", "A docs folder is available for setup, usage, or safety notes.")
    else:
        score = _deduct(score, findings, 6, "info", "Workspace: Docs folder missing", "Add docs if this workspace should be easy to share or revisit.")

    if ".gitignore" in root_names or ".gitignore" in names:
        _ok(findings, "Workspace: .gitignore present", "A .gitignore helps avoid publishing generated or private files.")
    else:
        score = _deduct(score, findings, 10, "warn", "Workspace: .gitignore missing", "Add a .gitignore before treating this folder as publish-ready.")

    if "agents.md" in names:
        _ok(findings, "Workspace: AGENTS.md present", "Project guidance is available for Codex inside the workspace.")
    else:
        score = _deduct(score, findings, 8, "info", "Workspace: AGENTS.md missing", "Add AGENTS.md if this folder needs durable Codex instructions.")

    if any(entry["name"] in SECRET_LIKE_NAMES for entry in entries):
        score = _deduct(score, findings, 22, "bad", "Workspace: Secret-like filenames found", "Metadata scan found secret-like filenames. Keep them private and out of public commits.")

    if any(entry["suffix"] in DATABASE_SUFFIXES or entry["name"].endswith(("-wal", "-shm")) for entry in entries):
        score = _deduct(score, findings, 10, "warn", "Workspace: Database-like files found", "Database-like files should be excluded from public publishing.")

    if any(entry["name"].endswith(".log") or any(part in {"log", "logs"} for part in entry["parts"]) for entry in entries):
        score = _deduct(score, findings, 8, "warn", "Workspace: Log files or folders found", "Logs may contain private traces and should stay out of public releases.")

    if any(entry["name"].endswith(".jsonl") and any("session" in part for part in entry["parts"]) for entry in entries):
        score = _deduct(score, findings, 12, "warn", "Workspace: Raw session-like files found", "Raw session files should not be published.")

    if any(entry["is_dir"] and entry["name"] in GENERATED_DIR_NAMES for entry in entries):
        score = _deduct(score, findings, 6, "info", "Workspace: Generated folders found", "Generated or dependency folders should stay ignored before publishing.")

    if truncated:
        score = _deduct(score, findings, 3, "info", "Workspace: Large folder sampled", "The metadata scan stopped after the first safe sample of entries.")

    _ok(findings, "Workspace: Metadata-only scan", "Score uses filenames, directory names, and existence checks only.")
    return _clamped_score(score), findings


def _workspace_readiness_score(workspace: dict[str, Any]) -> tuple[int, list[dict[str, str]]]:
    root = Path(workspace["root_path"])
    if _is_codex_config_path(root):
        raise HTTPException(status_code=400, detail="Codex auth/config folders cannot be scored")
    entries, truncated = _workspace_metadata_entries(root)
    return _workspace_readiness_from_entries(entries, truncated)


def _workspace_match_kind(entry: dict[str, Any]) -> str:
    if entry.get("is_symlink"):
        return "symlink"
    if entry.get("is_dir"):
        return "folder"
    return "file"


def _workspace_report_matches(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []

    def add(entry: dict[str, Any], level: str, category: str, reason: str) -> None:
        matches.append(
            {
                "level": level,
                "category": category,
                "kind": _workspace_match_kind(entry),
                "name": entry["display_name"],
                "relative_path": entry["relative_path"],
                "depth": entry["depth"],
                "reason": reason,
                "full_path": entry["full_path"],
            }
        )

    for entry in entries:
        name = entry["name"]
        if name in SECRET_LIKE_NAMES:
            add(entry, "bad", "secret-like", "Filename commonly stores secrets or local auth/config values.")
        if entry["suffix"] in DATABASE_SUFFIXES or name.endswith(("-wal", "-shm")):
            add(entry, "warn", "database-like", "Database-like files should stay private unless intentionally sanitized.")
        if name.endswith(".log") or any(part in {"log", "logs"} for part in entry["parts"]):
            add(entry, "warn", "log-like", "Logs can contain private traces and should stay out of public releases.")
        if name.endswith(".jsonl") and any("session" in part for part in entry["parts"]):
            add(entry, "warn", "raw-session-like", "Raw session files may include private prompts, outputs, or traces.")
        if entry["is_dir"] and name in GENERATED_DIR_NAMES:
            add(entry, "info", "generated-folder", "Generated or dependency folders should usually be ignored before publishing.")

    for index, match in enumerate(matches, start=1):
        match["id"] = f"match-{index}"
        match["review_key"] = _health_report_review_key(match)
    return matches


def _health_report_review_key(match: dict[str, Any]) -> str:
    return f"{match['category']}|{match['kind']}|{match['relative_path']}"


def _health_report_review_map(workspace_id: int) -> dict[str, dict[str, Any]]:
    items = rows(
        conn,
        """
        SELECT review_key, status, note, updated_at
        FROM health_report_reviews
        WHERE workspace_id=?
        """,
        (workspace_id,),
    )
    return {item["review_key"]: item for item in items}


def _default_review(review_key: str) -> dict[str, Any]:
    return {"review_key": review_key, "status": "needs_action", "note": None, "updated_at": None}


def _review_summary(matches: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(matches), "needs_action": 0, "reviewed": 0, "accepted_risk": 0, "ignore_for_now": 0}
    for match in matches:
        status = match["review"]["status"]
        if status in summary:
            summary[status] += 1
        else:
            summary["needs_action"] += 1
    return summary


def _gitignore_parent(relative_path: str) -> str:
    path = Path(relative_path)
    parent = path.parent.as_posix()
    return "" if parent == "." else parent


def _relative_to_gitignore_dir(relative_path: str, ignore_dir: str) -> str | None:
    relative_path = relative_path.strip("/")
    ignore_dir = ignore_dir.strip("/")
    if not ignore_dir:
        return relative_path
    if relative_path == ignore_dir:
        return ""
    prefix = f"{ignore_dir}/"
    if relative_path.startswith(prefix):
        return relative_path[len(prefix):]
    return None


def _parse_gitignore_patterns(text: str) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("\\#"):
            line = line[1:]
        elif line.startswith("#"):
            continue
        negated = False
        if line.startswith("\\!"):
            line = line[1:]
        elif line.startswith("!"):
            negated = True
            line = line[1:]
        line = line.strip()
        if not line:
            continue
        patterns.append({"pattern": line.replace("\\", "/"), "negated": negated})
    return patterns


def _gitignore_files(root: Path, entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for entry in entries:
        if entry["name"] != ".gitignore" or entry["is_dir"]:
            continue
        try:
            gitignore_path = (root / entry["relative_path"]).resolve(strict=True)
        except (FileNotFoundError, OSError):
            continue
        if not _is_path_inside_root(gitignore_path, root):
            continue
        try:
            if gitignore_path.stat().st_size > WORKSPACE_GITIGNORE_MAX_BYTES:
                items.append({"relative_path": entry["relative_path"], "dir": _gitignore_parent(entry["relative_path"]), "patterns": [], "readable": False})
                continue
            text = gitignore_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            items.append({"relative_path": entry["relative_path"], "dir": _gitignore_parent(entry["relative_path"]), "patterns": [], "readable": False})
            continue
        items.append(
            {
                "relative_path": entry["relative_path"],
                "dir": _gitignore_parent(entry["relative_path"]),
                "patterns": _parse_gitignore_patterns(text),
                "readable": True,
            }
        )
    return sorted(items, key=lambda item: (item["dir"].count("/"), item["relative_path"]))


def _gitignore_pattern_matches(pattern: str, candidate: str, is_dir: bool) -> bool:
    candidate = candidate.strip("/")
    if not candidate:
        return False
    pattern = pattern.strip()
    if not pattern:
        return False

    directory_only = pattern.endswith("/")
    pattern = pattern.strip("/")
    if not pattern:
        return False

    has_slash = "/" in pattern
    parts = candidate.split("/")
    basename = parts[-1]

    if directory_only:
        if has_slash:
            return candidate == pattern or candidate.startswith(f"{pattern}/") or (is_dir and fnmatchcase(candidate, pattern))
        return any(fnmatchcase(part, pattern) for part in parts[:-1] + ([basename] if is_dir else []))

    if has_slash:
        return fnmatchcase(candidate, pattern)
    return fnmatchcase(basename, pattern)


def _gitignore_coverage(match: dict[str, Any], ignore_files: list[dict[str, Any]]) -> dict[str, Any]:
    applicable = []
    for item in ignore_files:
        candidate = _relative_to_gitignore_dir(match["relative_path"], item["dir"])
        if candidate is not None:
            applicable.append((item, candidate))

    readable = [(item, candidate) for item, candidate in applicable if item["readable"]]
    if not readable:
        return {"status": "unknown", "detail": "No readable applicable .gitignore file was found.", "checked": 0}

    protected = False
    matched = False
    matched_source = None
    for item, candidate in readable:
        for rule in item["patterns"]:
            if _gitignore_pattern_matches(rule["pattern"], candidate, match["kind"] == "folder"):
                matched = True
                protected = not rule["negated"]
                matched_source = item["relative_path"]

    if matched and protected:
        return {
            "status": "protected",
            "detail": "A local .gitignore rule appears to cover this matched location.",
            "checked": len(readable),
            "source_label": matched_source,
        }
    if matched and not protected:
        return {
            "status": "not_ignored",
            "detail": "A later .gitignore negation appears to unignore this location.",
            "checked": len(readable),
            "source_label": matched_source,
        }
    return {"status": "not_ignored", "detail": "No applicable .gitignore rule matched this location.", "checked": len(readable)}


def _coverage_summary(matches: list[dict[str, Any]], ignore_files: list[dict[str, Any]]) -> dict[str, int]:
    protected = sum(1 for match in matches if match["ignore_coverage"]["status"] == "protected")
    not_ignored = sum(1 for match in matches if match["ignore_coverage"]["status"] == "not_ignored")
    unknown = sum(1 for match in matches if match["ignore_coverage"]["status"] == "unknown")
    return {
        "protected": protected,
        "not_ignored": not_ignored,
        "unknown": unknown,
        "ignore_files_read": sum(1 for item in ignore_files if item["readable"]),
        "ignore_files_unreadable": sum(1 for item in ignore_files if not item["readable"]),
    }


def _public_workspace_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": match["id"],
        "level": match["level"],
        "category": match["category"],
        "kind": match["kind"],
        "name": match["name"],
        "relative_path": match["relative_path"],
        "depth": match["depth"],
        "reason": match["reason"],
        "ignore_coverage": match["ignore_coverage"],
        "review_key": match["review_key"],
        "review": match["review"],
    }


def _workspace_report(workspace: dict[str, Any], scan_mode: str | None = None) -> dict[str, Any]:
    root = Path(workspace["root_path"])
    if _is_codex_config_path(root):
        raise HTTPException(status_code=400, detail="Codex auth/config folders cannot be reported")
    resolved_scan_mode, max_entries, max_depth = _scan_limits(scan_mode)
    entries, truncated = _workspace_metadata_entries(root, max_entries=max_entries, max_depth=max_depth)
    workspace_score, workspace_findings = _workspace_readiness_from_entries(entries, truncated)
    ignore_files = _gitignore_files(root, entries)
    matches = _workspace_report_matches(entries)
    review_map = _health_report_review_map(int(workspace["id"]))
    for match in matches:
        match["ignore_coverage"] = _gitignore_coverage(match, ignore_files)
        match["review"] = review_map.get(match["review_key"]) or _default_review(match["review_key"])
    return {
        "workspace_score": workspace_score,
        "workspace_findings": workspace_findings,
        "scan": {
            "scan_mode": resolved_scan_mode,
            "entries_scanned": len(entries),
            "truncated": truncated,
            "max_entries": max_entries,
            "max_depth": max_depth,
            "matched_locations": len(matches),
            "gitignore_coverage": _coverage_summary(matches, ignore_files),
            "review_summary": _review_summary(matches),
        },
        "matches": matches,
    }


def codex_version() -> str | None:
    codex = codex_executable()
    if not codex:
        return None
    try:
        result = subprocess.run([codex, "--version"], capture_output=True, text=True, timeout=5)
        return result.stdout.strip() or result.stderr.strip() or None
    except Exception:
        return None


def codex_login_status() -> dict[str, Any]:
    codex = codex_executable()
    if not codex:
        return {"available": False, "status": "Codex CLI not found"}
    try:
        result = subprocess.run([codex, "login", "status"], capture_output=True, text=True, timeout=8)
        text = (result.stdout or result.stderr).strip()
        return {"available": result.returncode == 0, "status": text or "unknown"}
    except Exception as exc:
        return {"available": False, "status": type(exc).__name__}


def _sync_all() -> dict[str, int]:
    session_result = sync_sessions(conn, settings.codex_home)
    skill_result = sync_skills(conn, settings.codex_home, repo_root)
    log_activity(conn, "sync_completed", "Manual or startup sync completed", {**session_result, **skill_result})
    return {**session_result, **skill_result}


def _last_sync() -> dict[str, Any] | None:
    item = row(conn, "SELECT detail, metadata_json, created_at FROM activities WHERE event_type='sync_completed' ORDER BY created_at DESC LIMIT 1")
    if not item:
        return None
    try:
        item["metadata"] = json.loads(item.get("metadata_json") or "{}")
    except json.JSONDecodeError:
        item["metadata"] = {}
    item.pop("metadata_json", None)
    return item


def _session_file_count() -> int:
    sessions_dir = settings.codex_home / "sessions"
    if not sessions_dir.exists():
        return 0
    return sum(1 for _ in sessions_dir.rglob("*.jsonl"))


def _otel_status() -> dict[str, Any]:
    latest = row(conn, "SELECT received_at FROM otel_events ORDER BY received_at DESC LIMIT 1")
    config_path = settings.codex_home / "config.toml"
    configured = False
    if config_path.exists():
        try:
            text = config_path.read_text(encoding="utf-8", errors="replace")
            configured = "[otel]" in text and "exporter = \"none\"" not in text
        except OSError:
            configured = False
    if latest:
        return {"status": "receiving", "last_event_at": latest["received_at"], "configured": configured}
    return {"status": "configured" if configured else "off", "last_event_at": None, "configured": configured}


def _parse_cron_field(field: str, minimum: int, maximum: int, *, allow_weekday_7: bool = False) -> set[int]:
    values: set[int] = set()
    for raw_part in field.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("empty cron field")
        step = 1
        if "/" in part:
            base, raw_step = part.split("/", 1)
            if not raw_step.isdigit():
                raise ValueError("invalid cron step")
            step = int(raw_step)
            if step < 1:
                raise ValueError("invalid cron step")
        else:
            base = part
        if base == "*":
            start, end = minimum, maximum
        elif "-" in base:
            raw_start, raw_end = base.split("-", 1)
            if not raw_start.isdigit() or not raw_end.isdigit():
                raise ValueError("invalid cron range")
            start, end = int(raw_start), int(raw_end)
        elif base.isdigit():
            start = end = int(base)
        else:
            raise ValueError("invalid cron field")
        if start < minimum or start > maximum or end < minimum or end > maximum or start > end:
            raise ValueError("cron value out of range")
        values.update(range(start, end + 1, step))
    if allow_weekday_7:
        values = {0 if value == 7 else value for value in values}
    return values


def _next_cron_run(cron_expression: str, after: datetime | None = None) -> str:
    expression = CRON_ALIASES.get(cron_expression.strip().lower(), cron_expression.strip())
    fields = expression.split()
    if len(fields) != 5:
        raise ValueError("use a five-field cron expression")
    minutes = _parse_cron_field(fields[0], 0, 59)
    hours = _parse_cron_field(fields[1], 0, 23)
    days = _parse_cron_field(fields[2], 1, 31)
    months = _parse_cron_field(fields[3], 1, 12)
    weekdays = _parse_cron_field(fields[4], 0, 7, allow_weekday_7=True)
    local_tz = datetime.now().astimezone().tzinfo or timezone.utc
    start = after or datetime.now(tz=local_tz)
    if start.tzinfo is None:
        start = start.replace(tzinfo=local_tz)
    candidate = start.astimezone(local_tz).replace(second=0, microsecond=0)
    candidate = candidate.replace(minute=candidate.minute) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        cron_weekday = (candidate.weekday() + 1) % 7
        if (
            candidate.minute in minutes
            and candidate.hour in hours
            and candidate.day in days
            and candidate.month in months
            and cron_weekday in weekdays
        ):
            return candidate.astimezone(timezone.utc).isoformat()
        candidate += timedelta(minutes=1)
    raise ValueError("cron expression has no run inside the next year")


def _create_awaiting_task(
    title: str,
    description: str,
    *,
    priority: int = 3,
    sandbox: str = "read-only",
    scheduled_for: str | None = None,
    output_summary: str | None = None,
    workspace_id: int | None = None,
) -> int:
    if sandbox not in ALLOWED_SANDBOXES:
        raise HTTPException(status_code=400, detail="V1 allows only read-only or workspace-write sandbox")
    if contains_sensitive_text(title) or contains_sensitive_text(description):
        raise HTTPException(status_code=400, detail="Task text looks like it contains a secret or private path")
    workspace = _workspace_or_default(workspace_id)
    cur = conn.execute(
        """
        INSERT INTO ops_tasks(title, description, status, priority, sandbox, workspace_id, cwd_label, cwd_hash,
                              scheduled_for, output_summary, created_at, updated_at)
        VALUES (?, ?, 'awaiting_approval', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            title,
            description,
            priority,
            sandbox,
            workspace["id"],
            workspace["path_label"],
            workspace["path_hash"],
            scheduled_for,
            output_summary,
            now_iso(),
            now_iso(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


@app.on_event("startup")
def startup_sync() -> None:
    try:
        _ensure_default_workspace()
        if _system_mode() == "token_saver":
            log_activity(conn, "sync_skipped", "Startup sync skipped because Token Saver is active", {"system_mode": "token_saver"})
        else:
            _sync_all()
    except Exception as exc:
        log_activity(conn, "sync_failed", type(exc).__name__, {})


@app.get("/api/health")
def health() -> dict[str, Any]:
    login = codex_login_status()
    version = codex_version()
    control_available = bool(version) and login["available"]
    control_reason = "available"
    if not version:
        control_reason = "Codex CLI not found"
    elif not login["available"]:
        control_reason = login["status"]
    return {
        "ok": True,
        "mode": "metadata-only" if settings.metadata_only else "content-opt-in",
        "uptime_seconds": int(time.time() - APP_STARTED_AT),
        "host": settings.host,
        "db_label": f"{settings.db_path.name} in {settings.db_path.parent.name}",
        "codex_home_present": settings.codex_home.exists(),
        "codex_version": version,
        "control_mode_available": control_available,
        "control_mode_reason": control_reason,
        "codex_login_status": login["status"],
        "last_sync": _last_sync(),
        "session_files_scanned": _session_file_count(),
        "otel": _otel_status(),
        "auth_json_read": False,
        "api_key_required": False,
    }


@app.get("/api/publish-readiness")
def publish_readiness() -> dict[str, Any]:
    return _publish_readiness_payload()


@app.post("/api/sync", dependencies=[Depends(require_control)])
def sync_now() -> dict[str, Any]:
    return {"ok": True, **_sync_all()}


@app.get("/api/system-mode")
def system_mode() -> dict[str, Any]:
    return _system_mode_payload()


@app.post("/api/system-mode", dependencies=[Depends(require_control)])
def update_system_mode(payload: SystemModeUpdate) -> dict[str, Any]:
    _set_system_mode(payload.mode)
    return {"ok": True, **_system_mode_payload()}


@app.get("/api/workspace-browser/roots", dependencies=[Depends(require_control)])
def workspace_browser_roots() -> dict[str, Any]:
    return {"items": _workspace_browser_roots()}


@app.post("/api/workspace-browser/roots", dependencies=[Depends(require_control)])
def workspace_browser_add_root(root: WorkspaceBrowserRootCreate) -> dict[str, Any]:
    resolved = _safe_resolve_existing_dir(root.path)
    return {"ok": True, "root": _browser_item(resolved, root.name or _folder_label(resolved), root=resolved)}


@app.get("/api/workspace-browser/folders", dependencies=[Depends(require_control)])
def workspace_browser_folders(token: str) -> dict[str, Any]:
    return _workspace_browser_folder(token)


@app.get("/api/workspaces")
def list_workspaces() -> dict[str, Any]:
    _ensure_default_workspace()
    items = rows(conn, "SELECT * FROM workspaces ORDER BY is_default DESC, name COLLATE NOCASE ASC, id ASC")
    return {"items": [_workspace_response(item) for item in items]}


@app.post("/api/workspaces", dependencies=[Depends(require_control)])
def create_workspace(workspace: WorkspaceCreate) -> dict[str, Any]:
    if contains_sensitive_text(workspace.name):
        raise HTTPException(status_code=400, detail="Workspace name looks like it contains a secret or private path")
    if workspace.browser_token:
        resolved, _ = _browser_token_path(workspace.browser_token)
    elif workspace.path:
        resolved = _safe_resolve_existing_dir(workspace.path)
    else:
        raise HTTPException(status_code=400, detail="Choose a folder or provide a path")
    label, path_hash = project_label(str(resolved))
    existing = row(conn, "SELECT * FROM workspaces WHERE root_path=?", (str(resolved),))
    timestamp = now_iso()
    if existing:
        conn.execute(
            """
            UPDATE workspaces
            SET name=?, path_label=?, path_hash=?, updated_at=?
            WHERE id=?
            """,
            (workspace.name.strip(), label, path_hash, timestamp, existing["id"]),
        )
        workspace_id = int(existing["id"])
    else:
        cur = conn.execute(
            """
            INSERT INTO workspaces(name, root_path, path_label, path_hash, is_default, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            """,
            (workspace.name.strip(), str(resolved), label, path_hash, timestamp, timestamp),
        )
        workspace_id = int(cur.lastrowid)
    conn.commit()
    saved = row(conn, "SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    assert saved is not None
    return {"ok": True, "workspace": _workspace_response(saved)}


@app.delete("/api/workspaces/{workspace_id}", dependencies=[Depends(require_control)])
def delete_workspace(workspace_id: int) -> dict[str, Any]:
    workspace = row(conn, "SELECT * FROM workspaces WHERE id=?", (workspace_id,))
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if workspace["is_default"]:
        raise HTTPException(status_code=400, detail="Default workspace cannot be removed")
    active = row(
        conn,
        """
        SELECT COUNT(*) AS count
        FROM ops_tasks
        WHERE workspace_id=? AND archived=0 AND status IN ('awaiting_approval', 'pending', 'running')
        """,
        (workspace_id,),
    )["count"]
    enabled_schedules = row(
        conn,
        "SELECT COUNT(*) AS count FROM ops_schedules WHERE workspace_id=? AND enabled=1",
        (workspace_id,),
    )["count"]
    if active or enabled_schedules:
        raise HTTPException(status_code=409, detail="Workspace is still used by active tasks or schedules")
    conn.execute("UPDATE ops_tasks SET workspace_id=NULL, updated_at=? WHERE workspace_id=?", (now_iso(), workspace_id))
    conn.execute("UPDATE ops_schedules SET workspace_id=NULL, updated_at=? WHERE workspace_id=?", (now_iso(), workspace_id))
    conn.execute("DELETE FROM workspaces WHERE id=?", (workspace_id,))
    conn.commit()
    return {"ok": True, "workspace_id": workspace_id, "deleted": True}


@app.get("/api/summary")
def summary() -> dict[str, Any]:
    today = rows(
        conn,
        """
        SELECT
          COUNT(*) AS sessions,
          COALESCE(SUM(total_tokens), 0) AS total_tokens,
          COALESCE(SUM(tool_count), 0) AS tools,
          COALESCE(SUM(CASE WHEN status='recent' THEN 1 ELSE 0 END), 0) AS recent_sessions
        FROM sessions
        WHERE date(updated_at) = date('now', 'localtime')
        """,
    )[0]
    tasks = rows(conn, "SELECT status, COUNT(*) AS count FROM ops_tasks WHERE archived=0 GROUP BY status")
    return {"today": today, "tasks": tasks}


def _empty_usage_insights() -> dict[str, Any]:
    return {
        "freshness_quality": "unknown",
        "task_advice": "small_tasks",
        "trend_direction": "unknown",
        "burn_rate": {
            "primary": {"available": False, "reason": "not_enough_local_history"},
            "secondary": {"available": False, "reason": "not_enough_local_history"},
        },
        "trend_points": [],
        "limit_hits": [],
        "observation_count": 0,
    }


def _usage_freshness_quality(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "unknown"
    if age_seconds <= 3600:
        return "fresh"
    if age_seconds <= 21600:
        return "old"
    return "very_stale"


def _usage_task_advice(limit: dict[str, Any], freshness_quality: str) -> str:
    remaining_values = [
        value
        for value in (limit.get("primary_remaining_percent"), limit.get("secondary_remaining_percent"))
        if isinstance(value, (int, float))
    ]
    lowest_remaining = min(remaining_values) if remaining_values else None
    if freshness_quality == "very_stale" or (lowest_remaining is not None and lowest_remaining < 10):
        return "wait_for_reset"
    if freshness_quality in {"old", "unknown"} or (lowest_remaining is not None and lowest_remaining < 20):
        return "small_tasks"
    return "normal"


def _usage_burn_rate(limit: dict[str, Any], observations: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    remaining_key = f"{prefix}_remaining_percent"
    reset_key = f"{prefix}_resets_at"
    window_key = f"{prefix}_window_minutes"
    current_reset = limit.get(reset_key)
    current_window = limit.get(window_key)
    if current_reset is None or current_window is None:
        return {"available": False, "reason": "missing_window_metadata"}
    candidates = []
    for observation in observations:
        if observation.get(reset_key) != current_reset or observation.get(window_key) != current_window:
            continue
        remaining = observation.get(remaining_key)
        observed_at = _parse_iso_datetime(observation.get("observed_at"))
        if not isinstance(remaining, (int, float)) or observed_at is None:
            continue
        candidates.append({"remaining_percent": float(remaining), "observed_at": observed_at})
    if len(candidates) < 2:
        return {"available": False, "reason": "not_enough_local_history"}
    candidates.sort(key=lambda item: item["observed_at"])
    first = candidates[0]
    latest = candidates[-1]
    elapsed_hours = (latest["observed_at"] - first["observed_at"]).total_seconds() / 3600
    if elapsed_hours <= 0:
        return {"available": False, "reason": "not_enough_time_elapsed"}
    percent_spent = max(0.0, first["remaining_percent"] - latest["remaining_percent"])
    return {
        "available": True,
        "percent_spent": round(percent_spent, 2),
        "hours": round(elapsed_hours, 2),
        "percent_per_hour": round(percent_spent / elapsed_hours, 2),
        "observation_count": len(candidates),
    }


def _usage_trend_points(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_date: dict[str, dict[str, Any]] = {}
    for observation in observations:
        observed = _parse_iso_datetime(observation.get("observed_at"))
        if observed is None:
            continue
        date_key = observed.date().isoformat()
        by_date[date_key] = {
            "date": date_key,
            "primary_remaining_percent": observation.get("primary_remaining_percent"),
            "secondary_remaining_percent": observation.get("secondary_remaining_percent"),
        }
    return [by_date[key] for key in sorted(by_date.keys())][-30:]


def _usage_trend_direction(points: list[dict[str, Any]]) -> str:
    values = [point.get("primary_remaining_percent") for point in points if isinstance(point.get("primary_remaining_percent"), (int, float))]
    if len(values) < 2:
        return "unknown"
    delta = float(values[-1]) - float(values[0])
    if delta <= -5:
        return "falling"
    if delta >= 5:
        return "recovering"
    return "stable"


def _usage_limit_hits(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hits = [
        {
            "rate_limit_reached_type": observation.get("rate_limit_reached_type"),
            "observed_at": observation.get("observed_at"),
        }
        for observation in observations
        if observation.get("rate_limit_reached_type")
    ]
    return sorted(hits, key=lambda item: str(item.get("observed_at") or ""), reverse=True)[:3]


def _usage_insights(limit: dict[str, Any], age_seconds: int | None) -> dict[str, Any]:
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=30)).isoformat()
    observations = rows(
        conn,
        """
        SELECT plan_type, primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
               secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
               rate_limit_reached_type, observed_at
        FROM usage_limit_observations
        WHERE observed_at >= ?
        ORDER BY observed_at ASC
        """,
        (cutoff,),
    )
    trend_points = _usage_trend_points(observations)
    freshness_quality = _usage_freshness_quality(age_seconds)
    return {
        "freshness_quality": freshness_quality,
        "task_advice": _usage_task_advice(limit, freshness_quality),
        "trend_direction": _usage_trend_direction(trend_points),
        "burn_rate": {
            "primary": _usage_burn_rate(limit, observations, "primary"),
            "secondary": _usage_burn_rate(limit, observations, "secondary"),
        },
        "trend_points": trend_points,
        "limit_hits": _usage_limit_hits(observations),
        "observation_count": len(observations),
    }


@app.get("/api/usage/limits")
def usage_limits() -> dict[str, Any]:
    limit = row(conn, "SELECT * FROM usage_limits WHERE id = 1")
    if not limit:
        return {"available": False, "limit": None, "insights": _empty_usage_insights()}
    age_seconds = None
    observed_at = limit.get("observed_at")
    if observed_at:
        try:
            observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int(time.time() - observed.timestamp()))
        except ValueError:
            age_seconds = None
    return {
        "available": True,
        "stale": bool(age_seconds is not None and age_seconds > 3600),
        "age_seconds": age_seconds,
        "source": "local-session-rate-limits",
        "limit": limit,
        "insights": _usage_insights(limit, age_seconds),
    }


@app.get("/api/health-score")
def health_score(workspace_id: int | None = None) -> dict[str, Any]:
    workspace = _workspace_or_default(workspace_id)
    system_score, system_findings = _system_readiness_score()
    workspace_score, workspace_findings = _workspace_readiness_score(workspace)
    overall_score = _clamped_score(system_score * 0.4 + workspace_score * 0.6)
    return {
        "generated_at": now_iso(),
        "workspace": {
            "id": workspace["id"],
            "name": workspace["name"],
            "path_label": workspace["path_label"],
            "is_default": workspace["is_default"],
        },
        "overall_score": overall_score,
        "system_score": system_score,
        "workspace_score": workspace_score,
        "findings": system_findings + workspace_findings,
    }


@app.get("/api/health-score/report")
def health_score_report(workspace_id: int | None = None, scan_mode: str = "standard") -> dict[str, Any]:
    workspace = _workspace_or_default(workspace_id)
    system_score, system_findings = _system_readiness_score()
    report = _workspace_report(workspace, scan_mode)
    overall_score = _clamped_score(system_score * 0.4 + report["workspace_score"] * 0.6)
    return {
        "generated_at": now_iso(),
        "workspace": {
            "id": workspace["id"],
            "name": workspace["name"],
            "path_label": workspace["path_label"],
            "is_default": workspace["is_default"],
        },
        "overall_score": overall_score,
        "system_score": system_score,
        "workspace_score": report["workspace_score"],
        "scan": report["scan"],
        "findings": system_findings + report["workspace_findings"],
        "matches": [_public_workspace_match(match) for match in report["matches"]],
    }


@app.get("/api/health-score/report/paths", dependencies=[Depends(require_control)])
def health_score_report_paths(workspace_id: int | None = None, scan_mode: str = "standard") -> dict[str, Any]:
    workspace = _workspace_or_default(workspace_id)
    report = _workspace_report(workspace, scan_mode)
    return {
        "revealed_at": now_iso(),
        "workspace": {
            "id": workspace["id"],
            "name": workspace["name"],
            "path_label": workspace["path_label"],
            "root_path": workspace["root_path"],
        },
        "matches": [
            {
                "id": match["id"],
                "full_path": match["full_path"],
            }
            for match in report["matches"]
        ],
    }


@app.post("/api/health-score/reviews", dependencies=[Depends(require_control)])
def save_health_report_review(payload: HealthReportReviewUpdate) -> dict[str, Any]:
    if payload.status not in HEALTH_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown review status")
    workspace = _workspace_or_default(payload.workspace_id)
    report = _workspace_report(workspace, payload.scan_mode)
    valid_keys = {match["review_key"] for match in report["matches"]}
    if payload.review_key not in valid_keys:
        raise HTTPException(status_code=404, detail="Report finding not found")
    timestamp = now_iso()
    conn.execute(
        """
        INSERT INTO health_report_reviews(workspace_id, review_key, status, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(workspace_id, review_key)
        DO UPDATE SET status=excluded.status, note=excluded.note, updated_at=excluded.updated_at
        """,
        (workspace["id"], payload.review_key, payload.status, payload.note, timestamp, timestamp),
    )
    conn.commit()
    return {"ok": True, "workspace_id": workspace["id"], "review_key": payload.review_key, "status": payload.status, "updated_at": timestamp}


@app.post("/api/health-score/reviews/bulk", dependencies=[Depends(require_control)])
def save_health_report_reviews_bulk(payload: HealthReportReviewBulkUpdate) -> dict[str, Any]:
    if payload.status not in HEALTH_REVIEW_STATUSES:
        raise HTTPException(status_code=400, detail="Unknown review status")
    requested_keys = list(dict.fromkeys(payload.review_keys))
    workspace = _workspace_or_default(payload.workspace_id)
    report = _workspace_report(workspace, payload.scan_mode)
    valid_keys = {match["review_key"] for match in report["matches"]}
    missing_keys = [key for key in requested_keys if key not in valid_keys]
    if missing_keys:
        raise HTTPException(status_code=404, detail="One or more report findings were not found")
    timestamp = now_iso()
    conn.executemany(
        """
        INSERT INTO health_report_reviews(workspace_id, review_key, status, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(workspace_id, review_key)
        DO UPDATE SET status=excluded.status, note=excluded.note, updated_at=excluded.updated_at
        """,
        [(workspace["id"], key, payload.status, payload.note, timestamp, timestamp) for key in requested_keys],
    )
    conn.commit()
    return {"ok": True, "workspace_id": workspace["id"], "updated": len(requested_keys), "status": payload.status, "updated_at": timestamp}


@app.get("/api/sessions")
def list_sessions(limit: int = 40) -> dict[str, Any]:
    limit = min(max(limit, 1), 200)
    return {
        "items": rows(
            conn,
            """
            SELECT session_id, source, model, project_label, started_at, updated_at, status,
                   event_count, tool_count, input_tokens, cached_input_tokens,
                   output_tokens, reasoning_output_tokens, total_tokens
            FROM sessions
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
    }


@app.get("/api/sessions/{session_id}")
def session_details(session_id: str) -> dict[str, Any]:
    session = row(conn, "SELECT * FROM sessions WHERE session_id = ?", (session_id,))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    tools = rows(
        conn,
        "SELECT call_id, tool_name, started_at, completed_at, duration_ms, success FROM tool_events WHERE session_id=? ORDER BY started_at",
        (session_id,),
    )
    return {"session": session, "tools": tools}


@app.get("/api/tools")
def tools() -> dict[str, Any]:
    return {
        "items": rows(
            conn,
            """
            SELECT tool_name, COUNT(*) AS calls, SUM(CASE WHEN success=0 THEN 1 ELSE 0 END) AS failures
            FROM tool_events
            GROUP BY tool_name
            ORDER BY calls DESC
            LIMIT 40
            """,
        )
    }


@app.get("/api/skills")
def skills() -> dict[str, Any]:
    return {
        "items": rows(
            conn,
            "SELECT id, name, scope, description, path_label, plugin_name, enabled, last_modified FROM skills ORDER BY scope, name",
        )
    }


@app.get("/api/skills/{skill_id}/path", dependencies=[Depends(require_control)])
def skill_path(skill_id: int) -> dict[str, Any]:
    item = row(conn, "SELECT id, path_label, skill_path FROM skills WHERE id=?", (skill_id,))
    if not item:
        raise HTTPException(status_code=404, detail="Skill not found")
    if not item.get("skill_path"):
        raise HTTPException(status_code=404, detail="Skill path is not available; run sync again")
    return {"id": item["id"], "path": item["skill_path"], "path_label": item["path_label"]}


@app.get("/api/context-health")
def context_health() -> dict[str, Any]:
    config_path = settings.codex_home / "config.toml"
    agents_count = len(list(repo_root.rglob("AGENTS.md")))
    skill_count = row(conn, "SELECT COUNT(*) AS count FROM skills")["count"]
    automation_dir = settings.codex_home / "automations"
    automation_count = len([p for p in automation_dir.iterdir() if p.is_dir()]) if automation_dir.exists() else 0
    findings = []
    if agents_count == 0:
        findings.append({"level": "info", "title": "No repo AGENTS.md", "detail": "Add one if this repo needs durable Codex instructions."})
    if skill_count > 60:
        findings.append({"level": "warn", "title": "Large skill set", "detail": "Many skills can crowd the initial skill list; keep descriptions tight."})
    return {
        "config_present": config_path.exists(),
        "repo_agents_files": agents_count,
        "skills": skill_count,
        "automations": automation_count,
        "findings": findings,
    }


@app.get("/api/security-posture")
def security_posture() -> dict[str, Any]:
    config_path = settings.codex_home / "config.toml"
    config_text = ""
    if config_path.exists():
        try:
            config_text = config_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            config_text = ""
    findings = [
        {"level": "ok", "title": "API key not required", "detail": "The dashboard does not call OpenAI directly."},
        {"level": "ok", "title": "auth.json ignored", "detail": "The backend uses `codex login status` and never reads auth token files."},
        {"level": "ok", "title": "Loopback first", "detail": "Server defaults to 127.0.0.1 and control actions are loopback-only unless token-protected."},
    ]
    if "danger-full-access" in config_text:
        findings.append({"level": "warn", "title": "Full-access config mention", "detail": "Review Codex sandbox defaults before enabling unattended tasks."})
    if "log_user_prompt = true" in config_text:
        findings.append({"level": "warn", "title": "Prompt logging enabled", "detail": "Disable Codex OTel prompt logging if you want metadata-only telemetry."})
    if "exporter = \"none\"" in config_text or "[otel]" not in config_text:
        findings.append({"level": "info", "title": "OTel not exporting", "detail": "Observe Mode still works from local sessions; OTel is optional."})
    return {"findings": findings}


@app.get("/api/tasks")
def list_tasks() -> dict[str, Any]:
    return {"items": rows(conn, "SELECT * FROM ops_tasks WHERE archived=0 ORDER BY created_at DESC LIMIT 100")}


@app.get("/api/tasks/history")
def task_history(status: str = "all", query: str = "", include_archived: bool = True, limit: int = 200) -> dict[str, Any]:
    limit = min(max(limit, 1), 500)
    allowed_statuses = {"all", "done", "failed", "cancelled", "awaiting_approval", "pending", "running"}
    if status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="Unknown task status filter")

    clauses = []
    params: list[Any] = []
    if status != "all":
        clauses.append("status = ?")
        params.append(status)
    if not include_archived:
        clauses.append("archived = 0")
    search = query.strip()
    if search:
        clauses.append("(title LIKE ? OR description LIKE ? OR output_summary LIKE ? OR failure_reason LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like, like])

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    items = rows(
        conn,
        f"""
        SELECT *
        FROM ops_tasks
        {where}
        ORDER BY COALESCE(completed_at, updated_at, created_at) DESC
        LIMIT ?
        """,
        (*params, limit),
    )
    stats = rows(
        conn,
        f"""
        SELECT
          COUNT(*) AS total,
          COALESCE(SUM(CASE WHEN status='done' THEN 1 ELSE 0 END), 0) AS done,
          COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END), 0) AS failed,
          COALESCE(SUM(CASE WHEN status='cancelled' THEN 1 ELSE 0 END), 0) AS cancelled,
          COALESCE(SUM(CASE WHEN status IN ('awaiting_approval', 'pending', 'running') THEN 1 ELSE 0 END), 0) AS active,
          COALESCE(AVG(CASE WHEN duration_ms IS NOT NULL THEN duration_ms END), 0) AS avg_duration_ms,
          COALESCE(SUM(tool_count), 0) AS total_tools
        FROM ops_tasks
        {where}
        """,
        tuple(params),
    )[0]
    return {"items": items, "stats": stats}


@app.get("/api/tasks/token-usage")
def task_token_usage(days: int = 30) -> dict[str, Any]:
    days = min(max(days, 1), 90)
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=days)).isoformat()
    launched_where = "(approved_at IS NOT NULL OR started_at IS NOT NULL)"
    period_where = f"{launched_where} AND COALESCE(completed_at, updated_at, created_at) >= ?"
    totals = row(
        conn,
        f"""
        SELECT
          COUNT(*) AS launched_tasks,
          COALESCE(SUM(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END), 0) AS unknown_task_count,
          COALESCE(SUM(input_tokens), 0) AS input_tokens,
          COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
          COALESCE(SUM(output_tokens), 0) AS output_tokens,
          COALESCE(SUM(reasoning_output_tokens), 0) AS reasoning_output_tokens,
          COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM ops_tasks
        WHERE {period_where}
        """,
        (cutoff,),
    ) or {}
    today = row(
        conn,
        f"""
        SELECT
          COUNT(*) AS launched_tasks,
          COALESCE(SUM(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END), 0) AS unknown_task_count,
          COALESCE(SUM(total_tokens), 0) AS total_tokens
        FROM ops_tasks
        WHERE {launched_where}
          AND date(COALESCE(completed_at, updated_at, created_at)) = date('now', 'localtime')
        """,
    ) or {}
    latest = row(
        conn,
        f"""
        SELECT id, status, completed_at, updated_at, total_tokens
        FROM ops_tasks
        WHERE {launched_where}
        ORDER BY COALESCE(completed_at, updated_at, created_at) DESC
        LIMIT 1
        """,
    )
    trend = rows(
        conn,
        f"""
        SELECT
          date(COALESCE(completed_at, updated_at, created_at)) AS date,
          COUNT(*) AS task_count,
          COALESCE(SUM(total_tokens), 0) AS total_tokens,
          COALESCE(SUM(CASE WHEN total_tokens IS NULL THEN 1 ELSE 0 END), 0) AS unknown_task_count
        FROM ops_tasks
        WHERE {period_where}
        GROUP BY date(COALESCE(completed_at, updated_at, created_at))
        ORDER BY date ASC
        """,
        (cutoff,),
    )
    return {
        "generated_at": now_iso(),
        "days": days,
        "source": "dashboard-launched-tasks",
        "today": today,
        "totals": totals,
        "latest_task": latest,
        "trend_points": trend,
        "note": "Best-effort token counts from dashboard-launched Codex task metadata only.",
    }


@app.get("/api/tasks/{task_id}")
def task_details(task_id: int) -> dict[str, Any]:
    task = row(conn, "SELECT * FROM ops_tasks WHERE id=?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task": task}


@app.post("/api/tasks", dependencies=[Depends(require_control)])
def create_task(task: TaskCreate) -> dict[str, Any]:
    task_id = _create_awaiting_task(
        task.title,
        task.description,
        priority=task.priority,
        sandbox=task.sandbox,
        scheduled_for=task.scheduled_for,
        workspace_id=task.workspace_id,
    )
    return {"ok": True, "task_id": task_id, "status": "awaiting_approval"}


@app.post("/api/tasks/{task_id}/approve", dependencies=[Depends(require_control)])
def approve_task(task_id: int) -> dict[str, Any]:
    if _system_mode() == "token_saver":
        raise HTTPException(status_code=409, detail="Token Saver is active; dashboard task launching is paused")
    task = row(conn, "SELECT * FROM ops_tasks WHERE id=?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "awaiting_approval":
        raise HTTPException(status_code=400, detail="Only awaiting_approval tasks can be approved")
    if not codex_login_status()["available"]:
        raise HTTPException(status_code=409, detail="Codex is not signed in; run `codex login` first")
    conn.execute(
        "UPDATE ops_tasks SET status='pending', approved_at=?, updated_at=? WHERE id=?",
        (now_iso(), now_iso(), task_id),
    )
    conn.commit()
    launch_task(conn, task_id, repo_root)
    return {"ok": True, "task_id": task_id, "status": "pending"}


@app.post("/api/tasks/{task_id}/cancel", dependencies=[Depends(require_control)])
def cancel_task(task_id: int) -> dict[str, Any]:
    proc = row(conn, "SELECT * FROM task_processes WHERE task_id=?", (task_id,))
    killed = False
    if proc:
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(proc["pid"]), "/T", "/F"], capture_output=True, timeout=5)
            else:
                os.killpg(proc["pid"], signal.SIGTERM)
            killed = True
        except Exception:
            killed = False
    conn.execute(
        "UPDATE ops_tasks SET status='cancelled', completed_at=?, updated_at=?, output_summary=? WHERE id=?",
        (now_iso(), now_iso(), "Cancelled from dashboard. Only dashboard-launched process was targeted.", task_id),
    )
    conn.execute("DELETE FROM task_processes WHERE task_id=?", (task_id,))
    conn.commit()
    return {"ok": True, "task_id": task_id, "process_killed": killed}


@app.post("/api/tasks/{task_id}/rerun", dependencies=[Depends(require_control)])
def rerun_task(task_id: int) -> dict[str, Any]:
    task = row(conn, "SELECT * FROM ops_tasks WHERE id=?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != "failed":
        raise HTTPException(status_code=400, detail="Only failed tasks can be rerun")
    conn.execute(
        """
        UPDATE ops_tasks
        SET status='awaiting_approval', approved_at=NULL, started_at=NULL, completed_at=NULL,
            duration_ms=NULL, exit_code=NULL, event_count=0, tool_count=0,
            input_tokens=NULL, cached_input_tokens=NULL, output_tokens=NULL, reasoning_output_tokens=NULL, total_tokens=NULL,
            thread_id=NULL, failure_reason=NULL,
            output_summary='Rerun requested. Approve again to launch safely.',
            error_message=NULL, updated_at=?
        WHERE id=?
        """,
        (now_iso(), task_id),
    )
    conn.commit()
    return {"ok": True, "task_id": task_id, "status": "awaiting_approval"}


@app.post("/api/tasks/{task_id}/archive", dependencies=[Depends(require_control)])
def archive_task(task_id: int) -> dict[str, Any]:
    task = row(conn, "SELECT status FROM ops_tasks WHERE id=?", (task_id,))
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] == "running":
        raise HTTPException(status_code=400, detail="Running tasks cannot be archived")
    conn.execute("UPDATE ops_tasks SET archived=1, updated_at=? WHERE id=?", (now_iso(), task_id))
    conn.commit()
    return {"ok": True, "task_id": task_id, "archived": True}


@app.post("/api/system/emergency-stop", dependencies=[Depends(require_control)])
def emergency_stop() -> dict[str, Any]:
    processes = rows(conn, "SELECT * FROM task_processes")
    killed = 0
    for proc in processes:
        try:
            if sys.platform.startswith("win"):
                subprocess.run(["taskkill", "/PID", str(proc["pid"]), "/T", "/F"], capture_output=True, timeout=5)
            else:
                os.killpg(proc["pid"], signal.SIGTERM)
            killed += 1
        except Exception:
            pass
    conn.execute("DELETE FROM task_processes")
    conn.execute(
        "UPDATE ops_tasks SET status='cancelled', completed_at=?, updated_at=?, output_summary=? WHERE status='running'",
        (now_iso(), now_iso(), "Emergency stop cancelled dashboard-launched process."),
    )
    conn.commit()
    return {"stopped": True, "processes_killed": killed, "interactive_spared": "all non-dashboard Codex sessions"}


@app.get("/api/schedules")
def schedules() -> dict[str, Any]:
    return {"items": rows(conn, "SELECT * FROM ops_schedules ORDER BY enabled DESC, next_run_at ASC, created_at DESC")}


@app.post("/api/schedules", dependencies=[Depends(require_control)])
def create_schedule(schedule: ScheduleCreate) -> dict[str, Any]:
    if contains_sensitive_text(schedule.name) or contains_sensitive_text(schedule.task_title) or contains_sensitive_text(schedule.task_description):
        raise HTTPException(status_code=400, detail="Schedule text looks like it contains a secret or private path")
    workspace = _workspace_or_default(schedule.workspace_id)
    try:
        next_run_at = _next_cron_run(schedule.cron_expression) if schedule.enabled else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cur = conn.execute(
        """
        INSERT INTO ops_schedules(name, cron_expression, task_title, task_description, enabled, next_run_at,
                                  workspace_id, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            schedule.name,
            schedule.cron_expression.strip(),
            schedule.task_title,
            schedule.task_description,
            1 if schedule.enabled else 0,
            next_run_at,
            workspace["id"],
            now_iso(),
            now_iso(),
        ),
    )
    conn.commit()
    return {"ok": True, "schedule_id": cur.lastrowid, "next_run_at": next_run_at}


@app.post("/api/schedules/materialize-due", dependencies=[Depends(require_control)])
def materialize_due_schedules() -> dict[str, Any]:
    if _system_mode() == "token_saver":
        raise HTTPException(status_code=409, detail="Token Saver is active; schedule materialization is paused")
    now = datetime.now(tz=timezone.utc)
    due_schedules = rows(
        conn,
        """
        SELECT * FROM ops_schedules
        WHERE enabled=1 AND next_run_at IS NOT NULL AND next_run_at <= ?
        ORDER BY next_run_at ASC
        LIMIT 25
        """,
        (now.isoformat(),),
    )
    created: list[dict[str, Any]] = []
    for schedule in due_schedules:
        due_at = schedule["next_run_at"]
        task_id = _create_awaiting_task(
            schedule["task_title"],
            schedule["task_description"],
            sandbox="read-only",
            scheduled_for=due_at,
            output_summary=f"Created from schedule: {schedule['name']}. Awaiting approval.",
            workspace_id=schedule["workspace_id"],
        )
        try:
            next_run_at = _next_cron_run(schedule["cron_expression"], now)
        except ValueError:
            next_run_at = None
        conn.execute(
            """
            UPDATE ops_schedules
            SET last_run_at=?, next_run_at=?, last_task_id=?, materialized_count=COALESCE(materialized_count, 0) + 1,
                updated_at=?
            WHERE id=?
            """,
            (due_at, next_run_at, task_id, now_iso(), schedule["id"]),
        )
        created.append(
            {
                "schedule_id": schedule["id"],
                "task_id": task_id,
                "scheduled_for": due_at,
                "next_run_at": next_run_at,
            }
        )
    conn.commit()
    return {"ok": True, "created": len(created), "items": created}


@app.post("/api/schedules/{schedule_id}/toggle", dependencies=[Depends(require_control)])
def toggle_schedule(schedule_id: int, payload: ScheduleToggle) -> dict[str, Any]:
    schedule = row(conn, "SELECT * FROM ops_schedules WHERE id=?", (schedule_id,))
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    try:
        next_run_at = _next_cron_run(schedule["cron_expression"]) if payload.enabled else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    conn.execute(
        "UPDATE ops_schedules SET enabled=?, next_run_at=?, updated_at=? WHERE id=?",
        (1 if payload.enabled else 0, next_run_at, now_iso(), schedule_id),
    )
    conn.commit()
    return {"ok": True, "schedule_id": schedule_id, "enabled": payload.enabled, "next_run_at": next_run_at}


@app.post("/api/schedules/{schedule_id}/delete", dependencies=[Depends(require_control)])
def delete_schedule(schedule_id: int) -> dict[str, Any]:
    schedule = row(conn, "SELECT id FROM ops_schedules WHERE id=?", (schedule_id,))
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    conn.execute("DELETE FROM ops_schedules WHERE id=?", (schedule_id,))
    conn.commit()
    return {"ok": True, "schedule_id": schedule_id, "deleted": True}


@app.post("/v1/logs", dependencies=[Depends(require_otel)])
async def otel_logs(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = ingest_logs(conn, payload)
        return {"ok": True, **result}
    except Exception:
        return {"ok": True, "inserted": 0, "dropped": 1}


@app.post("/v1/metrics", dependencies=[Depends(require_otel)])
async def otel_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = ingest_metrics(conn, payload)
        return {"ok": True, **result}
    except Exception:
        return {"ok": True, "inserted": 0, "dropped": 1}


dist_dir = repo_root / "ui" / "dist"
if dist_dir.exists():
    app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str) -> FileResponse:
        candidate = dist_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist_dir / "index.html")
