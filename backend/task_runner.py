from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .codex_cli import codex_executable
from .privacy import redact_text


ALLOWED_SANDBOXES = {"read-only", "workspace-write"}
MAX_TASK_SUMMARY_CHARS = 2400
SAFE_STDERR_CHARS = 1200


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _creation_flags() -> int:
    return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _candidate_token_usage(event: Any) -> dict[str, Any] | None:
    event = _as_dict(event)
    payload = _as_dict(event.get("payload"))
    payload_info = _as_dict(payload.get("info"))
    event_info = _as_dict(event.get("info"))
    item = _as_dict(event.get("item"))
    item_info = _as_dict(item.get("info"))
    candidates = [
        payload_info.get("total_token_usage"),
        event_info.get("total_token_usage"),
        item_info.get("total_token_usage"),
        event.get("usage"),
        event.get("token_usage"),
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and any(key in candidate for key in ("input_tokens", "output_tokens", "total_tokens")):
            return candidate
    return None


def launch_task(conn: sqlite3.Connection, task_id: int, repo_root: Path) -> None:
    thread = threading.Thread(target=_run_task, args=(conn, task_id, repo_root), daemon=True)
    thread.start()


def _workspace_root_for_task(conn: sqlite3.Connection, task: sqlite3.Row, default_repo_root: Path) -> Path:
    workspace_id = task["workspace_id"] if "workspace_id" in task.keys() else None
    if not workspace_id:
        return default_repo_root
    workspace = conn.execute("SELECT root_path FROM workspaces WHERE id=?", (workspace_id,)).fetchone()
    if not workspace:
        raise RuntimeError("Selected workspace is no longer registered.")
    root = Path(workspace["root_path"])
    if not root.exists() or not root.is_dir():
        raise RuntimeError("Selected workspace folder is unavailable.")
    return root


def _run_task(conn: sqlite3.Connection, task_id: int, repo_root: Path) -> None:
    task = conn.execute("SELECT * FROM ops_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return

    sandbox = task["sandbox"] if task["sandbox"] in ALLOWED_SANDBOXES else "read-only"
    try:
        workspace_root = _workspace_root_for_task(conn, task, repo_root)
    except RuntimeError as exc:
        conn.execute(
            "UPDATE ops_tasks SET status='failed', completed_at=?, updated_at=?, output_summary=?, error_message=?, failure_reason=? WHERE id=?",
            (now_iso(), now_iso(), str(exc), str(exc), str(exc), task_id),
        )
        conn.commit()
        return
    codex = codex_executable()
    if not codex:
        conn.execute(
            "UPDATE ops_tasks SET status='failed', completed_at=?, updated_at=?, output_summary=?, error_message=? WHERE id=?",
            (now_iso(), now_iso(), "Codex CLI was not found.", "codex executable missing", task_id),
        )
        conn.commit()
        return
    prompt = f"{task['title']}\n\n{task['description']}\n\nMetadata-only dashboard task. Do not expose secrets."
    cmd = [
        codex,
        "exec",
        "--json",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        sandbox,
        "--cd",
        str(workspace_root),
        prompt,
    ]
    started = time.time()
    event_count = 0
    tool_count = 0
    exit_code: int | None = None
    final_message: str | None = None
    thread_id: str | None = None
    stderr_lines: list[str] = []
    token_usage_observed = False
    token_usage = {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": 0,
    }

    try:
        conn.execute(
            "UPDATE ops_tasks SET status='running', started_at=?, updated_at=? WHERE id=?",
            (now_iso(), now_iso(), task_id),
        )
        conn.commit()
        proc = subprocess.Popen(
            cmd,
            cwd=str(workspace_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_creation_flags(),
        )
        conn.execute(
            "INSERT OR REPLACE INTO task_processes(task_id, pid, started_at) VALUES (?, ?, ?)",
            (task_id, proc.pid, now_iso()),
        )
        conn.commit()

        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                if line.strip():
                    stderr_lines.append(redact_text(line.strip()) or "")
                continue
            if not isinstance(event, dict):
                continue
            event_count += 1
            if event.get("type") == "thread.started":
                thread_id = event.get("thread_id") or thread_id
            item = _as_dict(event.get("item"))
            item_type = item.get("type") or event.get("type")
            usage = _candidate_token_usage(event)
            if usage:
                token_usage_observed = True
                token_usage["input_tokens"] = max(token_usage["input_tokens"], _safe_int(usage.get("input_tokens")))
                token_usage["cached_input_tokens"] = max(token_usage["cached_input_tokens"], _safe_int(usage.get("cached_input_tokens")))
                token_usage["output_tokens"] = max(token_usage["output_tokens"], _safe_int(usage.get("output_tokens")))
                token_usage["reasoning_output_tokens"] = max(token_usage["reasoning_output_tokens"], _safe_int(usage.get("reasoning_output_tokens")))
                token_usage["total_tokens"] = max(token_usage["total_tokens"], _safe_int(usage.get("total_tokens")))
            if item_type and ("tool" in str(item_type) or "command" in str(item_type) or "mcp" in str(item_type)):
                tool_count += 1
            if event.get("type") == "item.completed" and item.get("type") == "agent_message":
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    final_message = redact_text(text.strip())
        exit_code = proc.wait()
        status = "done" if exit_code == 0 else "failed"
        if final_message:
            summary = final_message[:MAX_TASK_SUMMARY_CHARS]
        else:
            summary = f"Codex task {status}. No final agent message was emitted."
        failure_reason = None
        if exit_code != 0:
            failure_reason = _safe_failure_reason(stderr_lines) or f"codex exec exited with code {exit_code}"
        conn.execute(
            """
            UPDATE ops_tasks
            SET status=?, completed_at=?, updated_at=?, duration_ms=?, exit_code=?,
                event_count=?, tool_count=?,
                input_tokens=?, cached_input_tokens=?, output_tokens=?, reasoning_output_tokens=?, total_tokens=?,
                thread_id=?, failure_reason=?,
                output_summary=?, error_message=?
            WHERE id=?
            """,
            (
                status,
                now_iso(),
                now_iso(),
                int((time.time() - started) * 1000),
                exit_code,
                event_count,
                tool_count,
                token_usage["input_tokens"] if token_usage_observed else None,
                token_usage["cached_input_tokens"] if token_usage_observed else None,
                token_usage["output_tokens"] if token_usage_observed else None,
                token_usage["reasoning_output_tokens"] if token_usage_observed else None,
                token_usage["total_tokens"] if token_usage_observed else None,
                thread_id,
                failure_reason,
                summary,
                None if exit_code == 0 else failure_reason,
                task_id,
            ),
        )
    except Exception as exc:
        conn.execute(
            """
            UPDATE ops_tasks
            SET status='failed', completed_at=?, updated_at=?, duration_ms=?, exit_code=?,
                event_count=?, tool_count=?, failure_reason=?, output_summary=?, error_message=?
            WHERE id=?
            """,
            (
                now_iso(),
                now_iso(),
                int((time.time() - started) * 1000),
                exit_code,
                event_count,
                tool_count,
                type(exc).__name__,
                "Codex task failed before completion.",
                type(exc).__name__,
                task_id,
            ),
        )
    finally:
        conn.execute("DELETE FROM task_processes WHERE task_id=?", (task_id,))
        conn.commit()


def _safe_failure_reason(stderr_lines: list[str]) -> str | None:
    if not stderr_lines:
        return None
    useful = []
    for line in stderr_lines:
        lower = line.lower()
        if "warn " in lower or "warning" in lower:
            continue
        if "reading additional input from stdin" in lower:
            continue
        useful.append(line)
    text = "\n".join(useful or stderr_lines)
    return text[:SAFE_STDERR_CHARS] if text else None
