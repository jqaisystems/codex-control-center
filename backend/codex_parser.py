from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from .privacy import project_label, safe_relative_path


SESSION_ID_RE = re.compile(r"(019[a-z0-9\-]+|[0-9a-f]{8}-[0-9a-f\-]{27,})", re.I)
USAGE_OBSERVATION_RETENTION_DAYS = 30


def _as_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
    if isinstance(value, str):
        return value
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _remaining_percent(used_percent: float | None) -> float | None:
    if used_percent is None:
        return None
    return max(0.0, min(100.0, 100.0 - used_percent))


def _window_minutes(window: dict[str, Any] | None) -> int | None:
    if not window:
        return None
    minutes = _safe_int(window.get("window_minutes"))
    return minutes or None


def _reset_epoch(window: dict[str, Any] | None) -> int | None:
    if not window:
        return None
    value = _safe_int(window.get("resets_at"))
    return value or None


def parse_rate_limits(rate_limits: dict[str, Any], observed_at: str | None) -> dict[str, Any]:
    primary = rate_limits.get("primary") or {}
    secondary = rate_limits.get("secondary") or {}
    primary_used = _safe_float(primary.get("used_percent"))
    secondary_used = _safe_float(secondary.get("used_percent"))
    return {
        "limit_id": rate_limits.get("limit_id"),
        "plan_type": rate_limits.get("plan_type"),
        "primary_used_percent": primary_used,
        "primary_remaining_percent": _remaining_percent(primary_used),
        "primary_window_minutes": _window_minutes(primary),
        "primary_resets_at": _reset_epoch(primary),
        "secondary_used_percent": secondary_used,
        "secondary_remaining_percent": _remaining_percent(secondary_used),
        "secondary_window_minutes": _window_minutes(secondary),
        "secondary_resets_at": _reset_epoch(secondary),
        "rate_limit_reached_type": rate_limits.get("rate_limit_reached_type"),
        "observed_at": observed_at,
    }


def usage_observation_key(observation: dict[str, Any]) -> str:
    safe_payload = {
        "plan_type": observation.get("plan_type"),
        "primary_used_percent": observation.get("primary_used_percent"),
        "primary_remaining_percent": observation.get("primary_remaining_percent"),
        "primary_window_minutes": observation.get("primary_window_minutes"),
        "primary_resets_at": observation.get("primary_resets_at"),
        "secondary_used_percent": observation.get("secondary_used_percent"),
        "secondary_remaining_percent": observation.get("secondary_remaining_percent"),
        "secondary_window_minutes": observation.get("secondary_window_minutes"),
        "secondary_resets_at": observation.get("secondary_resets_at"),
        "rate_limit_reached_type": observation.get("rate_limit_reached_type"),
        "observed_at": observation.get("observed_at"),
    }
    encoded = json.dumps(safe_payload, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode("utf-8")).hexdigest()[:24]


def iter_session_files(codex_home: Path, limit: int = 500) -> list[Path]:
    sessions_dir = codex_home / "sessions"
    if not sessions_dir.exists():
        return []
    files = sorted(sessions_dir.rglob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def parse_session_file(path: Path, codex_home: Path) -> dict[str, Any]:
    session_id = None
    cwd = None
    source = "local"
    model = None
    started_at = None
    updated_at = None
    event_count = 0
    tools_by_call: dict[str, dict[str, Any]] = {}
    input_tokens = 0
    cached_input_tokens = 0
    output_tokens = 0
    reasoning_output_tokens = 0
    total_tokens = 0
    latest_usage_limit: dict[str, Any] | None = None
    usage_observations: list[dict[str, Any]] = []

    match = SESSION_ID_RE.search(path.stem)
    if match:
        session_id = match.group(1)

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_count += 1
            payload = event.get("payload") or {}
            ts = _as_iso(event.get("timestamp") or payload.get("timestamp"))
            if ts and (started_at is None or ts < started_at):
                started_at = ts
            if ts and (updated_at is None or ts > updated_at):
                updated_at = ts

            if event.get("type") == "session_meta":
                session_id = str(payload.get("id") or session_id or path.stem)
                cwd = payload.get("cwd") or cwd
                source = payload.get("source") or payload.get("originator") or source
                model = payload.get("model") or model

            if event.get("type") == "turn_context":
                cwd = payload.get("cwd") or cwd
                model = payload.get("model") or model

            payload_type = payload.get("type")
            if payload_type == "token_count":
                usage = ((payload.get("info") or {}).get("total_token_usage") or {})
                input_tokens = max(input_tokens, _safe_int(usage.get("input_tokens")))
                cached_input_tokens = max(cached_input_tokens, _safe_int(usage.get("cached_input_tokens")))
                output_tokens = max(output_tokens, _safe_int(usage.get("output_tokens")))
                reasoning_output_tokens = max(reasoning_output_tokens, _safe_int(usage.get("reasoning_output_tokens")))
                total_tokens = max(total_tokens, _safe_int(usage.get("total_tokens")))
                rate_limits = payload.get("rate_limits")
                if isinstance(rate_limits, dict):
                    usage_observation = parse_rate_limits(rate_limits, ts)
                    usage_observations.append(usage_observation)
                    latest_usage_limit = dict(usage_observation)

            if payload_type == "function_call":
                call_id = str(payload.get("call_id") or payload.get("id") or f"call-{event_count}")
                tools_by_call[call_id] = {
                    "call_id": call_id,
                    "tool_name": str(payload.get("name") or "unknown"),
                    "started_at": ts,
                    "completed_at": None,
                    "duration_ms": None,
                    "success": None,
                }
            elif payload_type == "function_call_output":
                call_id = str(payload.get("call_id") or payload.get("id") or "")
                if call_id in tools_by_call:
                    tools_by_call[call_id]["completed_at"] = ts
                    tools_by_call[call_id]["success"] = 0 if payload.get("error") else 1

    stat = path.stat()
    if updated_at is None:
        updated_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    if started_at is None:
        started_at = updated_at
    session_id = session_id or path.stem
    label, cwd_hash = project_label(cwd)

    if latest_usage_limit:
        latest_usage_limit["source_session_id"] = session_id
    for observation in usage_observations:
        if not observation.get("observed_at"):
            observation["observed_at"] = updated_at
        observation["dedupe_key"] = usage_observation_key(observation)

    return {
        "session": {
            "session_id": session_id,
            "relative_path": safe_relative_path(str(path), str(codex_home / "sessions")),
            "source": str(source),
            "model": str(model or "unknown"),
            "project_label": label,
            "project_hash": cwd_hash,
            "started_at": started_at,
            "updated_at": updated_at,
            "status": "recent" if (datetime.now(tz=timezone.utc).timestamp() - stat.st_mtime) <= 300 else "complete",
            "event_count": event_count,
            "tool_count": len(tools_by_call),
            "input_tokens": input_tokens,
            "cached_input_tokens": cached_input_tokens,
            "output_tokens": output_tokens,
            "reasoning_output_tokens": reasoning_output_tokens,
            "total_tokens": total_tokens,
        },
        "tools": list(tools_by_call.values()),
        "usage_limit": latest_usage_limit,
        "usage_observations": usage_observations,
    }


def sync_sessions(conn: sqlite3.Connection, codex_home: Path, limit: int = 500) -> dict[str, int]:
    synced = 0
    tool_rows = 0
    usage_observation_rows = 0
    latest_usage_limit: dict[str, Any] | None = None
    for path in iter_session_files(codex_home, limit=limit):
        parsed = parse_session_file(path, codex_home)
        session = parsed["session"]
        usage_limit = parsed.get("usage_limit")
        usage_observations = parsed.get("usage_observations") or []
        if usage_limit and (
            latest_usage_limit is None
            or str(usage_limit.get("observed_at") or "") > str(latest_usage_limit.get("observed_at") or "")
        ):
            latest_usage_limit = usage_limit
        for observation in usage_observations:
            if not observation.get("observed_at"):
                continue
            conn.execute(
                """
                INSERT INTO usage_limit_observations (
                  dedupe_key, plan_type,
                  primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
                  secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
                  rate_limit_reached_type, observed_at, synced_at
                ) VALUES (
                  :dedupe_key, :plan_type,
                  :primary_used_percent, :primary_remaining_percent, :primary_window_minutes, :primary_resets_at,
                  :secondary_used_percent, :secondary_remaining_percent, :secondary_window_minutes, :secondary_resets_at,
                  :rate_limit_reached_type, :observed_at, datetime('now')
                )
                ON CONFLICT(dedupe_key) DO UPDATE SET
                  plan_type=excluded.plan_type,
                  primary_used_percent=excluded.primary_used_percent,
                  primary_remaining_percent=excluded.primary_remaining_percent,
                  primary_window_minutes=excluded.primary_window_minutes,
                  primary_resets_at=excluded.primary_resets_at,
                  secondary_used_percent=excluded.secondary_used_percent,
                  secondary_remaining_percent=excluded.secondary_remaining_percent,
                  secondary_window_minutes=excluded.secondary_window_minutes,
                  secondary_resets_at=excluded.secondary_resets_at,
                  rate_limit_reached_type=excluded.rate_limit_reached_type,
                  observed_at=excluded.observed_at,
                  synced_at=datetime('now')
                """,
                observation,
            )
            usage_observation_rows += 1
        conn.execute(
            """
            INSERT INTO sessions (
              session_id, relative_path, source, model, project_label, project_hash,
              started_at, updated_at, status, event_count, tool_count, input_tokens,
              cached_input_tokens, output_tokens, reasoning_output_tokens, total_tokens, last_synced_at
            ) VALUES (
              :session_id, :relative_path, :source, :model, :project_label, :project_hash,
              :started_at, :updated_at, :status, :event_count, :tool_count, :input_tokens,
              :cached_input_tokens, :output_tokens, :reasoning_output_tokens, :total_tokens, datetime('now')
            )
            ON CONFLICT(session_id) DO UPDATE SET
              relative_path=excluded.relative_path,
              source=excluded.source,
              model=excluded.model,
              project_label=excluded.project_label,
              project_hash=excluded.project_hash,
              started_at=excluded.started_at,
              updated_at=excluded.updated_at,
              status=excluded.status,
              event_count=excluded.event_count,
              tool_count=excluded.tool_count,
              input_tokens=excluded.input_tokens,
              cached_input_tokens=excluded.cached_input_tokens,
              output_tokens=excluded.output_tokens,
              reasoning_output_tokens=excluded.reasoning_output_tokens,
              total_tokens=excluded.total_tokens,
              last_synced_at=datetime('now')
            """,
            session,
        )
        conn.execute("DELETE FROM tool_events WHERE session_id = ?", (session["session_id"],))
        for tool in parsed["tools"]:
            conn.execute(
                """
                INSERT INTO tool_events(session_id, call_id, tool_name, started_at, completed_at, duration_ms, success)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    tool.get("call_id"),
                    tool.get("tool_name"),
                    tool.get("started_at"),
                    tool.get("completed_at"),
                    tool.get("duration_ms"),
                    tool.get("success"),
                ),
            )
            tool_rows += 1
        synced += 1
    if latest_usage_limit:
        conn.execute(
            """
            INSERT INTO usage_limits (
              id, limit_id, plan_type,
              primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
              secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
              rate_limit_reached_type, source_session_id, observed_at, synced_at
            ) VALUES (
              1, :limit_id, :plan_type,
              :primary_used_percent, :primary_remaining_percent, :primary_window_minutes, :primary_resets_at,
              :secondary_used_percent, :secondary_remaining_percent, :secondary_window_minutes, :secondary_resets_at,
              :rate_limit_reached_type, :source_session_id, :observed_at, datetime('now')
            )
            ON CONFLICT(id) DO UPDATE SET
              limit_id=excluded.limit_id,
              plan_type=excluded.plan_type,
              primary_used_percent=excluded.primary_used_percent,
              primary_remaining_percent=excluded.primary_remaining_percent,
              primary_window_minutes=excluded.primary_window_minutes,
              primary_resets_at=excluded.primary_resets_at,
              secondary_used_percent=excluded.secondary_used_percent,
              secondary_remaining_percent=excluded.secondary_remaining_percent,
              secondary_window_minutes=excluded.secondary_window_minutes,
              secondary_resets_at=excluded.secondary_resets_at,
              rate_limit_reached_type=excluded.rate_limit_reached_type,
              source_session_id=excluded.source_session_id,
              observed_at=excluded.observed_at,
              synced_at=datetime('now')
            """,
            latest_usage_limit,
        )
    cutoff = (datetime.now(tz=timezone.utc) - timedelta(days=USAGE_OBSERVATION_RETENTION_DAYS)).isoformat()
    conn.execute("DELETE FROM usage_limit_observations WHERE observed_at < ?", (cutoff,))
    conn.commit()
    return {"sessions": synced, "tool_events": tool_rows, "usage_limits": 1 if latest_usage_limit else 0, "usage_limit_observations": usage_observation_rows}
