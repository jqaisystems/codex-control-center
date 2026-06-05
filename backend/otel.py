from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from .privacy import redact_text


def _attr_value(value: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return value
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            return value[key]
    if "arrayValue" in value:
        return value["arrayValue"]
    if "kvlistValue" in value:
        return value["kvlistValue"]
    return value


def _attributes(items: list[dict[str, Any]] | None) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for item in items or []:
        key = item.get("key")
        if key:
            attrs[key] = _attr_value(item.get("value") or {})
    return attrs


def _now() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _safe_attrs(attrs: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in attrs.items():
        key_lower = key.lower()
        if any(word in key_lower for word in ("prompt", "content", "output", "message", "token", "secret")):
            if key_lower.endswith("tokens") or key_lower in {"input_tokens", "output_tokens"}:
                safe[key] = value
            elif isinstance(value, (int, float, bool)):
                safe[key] = value
            else:
                safe[f"{key}_redacted"] = True
        else:
            safe[key] = redact_text(str(value)) if isinstance(value, str) else value
    return safe


def ingest_logs(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, int]:
    inserted = 0
    dropped = 0
    for resource in payload.get("resourceLogs", []):
        for scope in resource.get("scopeLogs", []):
            for record in scope.get("logRecords", []):
                try:
                    attrs = _attributes(record.get("attributes"))
                    body = record.get("body") or {}
                    body_value = _attr_value(body)
                    event_name = attrs.get("event.name") or attrs.get("event_name")
                    if not event_name and isinstance(body_value, str):
                        event_name = body_value[:120]
                    safe_attrs = _safe_attrs(attrs)
                    conn.execute(
                        """
                        INSERT INTO otel_events(
                          event_name, session_id, model, tool_name, tool_success, duration_ms,
                          input_tokens, output_tokens, timestamp, received_at, attributes_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(event_name or "unknown"),
                            attrs.get("conversation.id") or attrs.get("session_id") or attrs.get("session.id"),
                            attrs.get("model"),
                            attrs.get("tool.name") or attrs.get("tool_name"),
                            int(bool(attrs.get("success"))) if "success" in attrs else None,
                            int(attrs.get("duration_ms") or attrs.get("duration.ms") or 0) or None,
                            int(attrs.get("input_tokens") or attrs.get("input.tokens") or 0),
                            int(attrs.get("output_tokens") or attrs.get("output.tokens") or 0),
                            record.get("timeUnixNano") or record.get("observedTimeUnixNano"),
                            _now(),
                            json.dumps(safe_attrs, separators=(",", ":")),
                        ),
                    )
                    inserted += 1
                except Exception:
                    dropped += 1
    conn.commit()
    return {"inserted": inserted, "dropped": dropped}


def ingest_metrics(conn: sqlite3.Connection, payload: dict[str, Any]) -> dict[str, int]:
    inserted = 0
    dropped = 0
    for resource in payload.get("resourceMetrics", []):
        for scope in resource.get("scopeMetrics", []):
            for metric in scope.get("metrics", []):
                try:
                    metric_name = metric.get("name") or "unknown"
                    metric_type = next((key for key in ("sum", "gauge", "histogram") if key in metric), "unknown")
                    points = metric.get(metric_type, {}).get("dataPoints", [])
                    for point in points:
                        attrs = _safe_attrs(_attributes(point.get("attributes")))
                        value = point.get("asDouble", point.get("asInt", 0))
                        conn.execute(
                            """
                            INSERT INTO otel_metrics(metric_name, metric_type, value, timestamp, received_at, attributes_json)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                metric_name,
                                metric_type,
                                float(value or 0),
                                point.get("timeUnixNano"),
                                _now(),
                                json.dumps(attrs, separators=(",", ":")),
                            ),
                        )
                        inserted += 1
                except Exception:
                    dropped += 1
    conn.commit()
    return {"inserted": inserted, "dropped": dropped}
