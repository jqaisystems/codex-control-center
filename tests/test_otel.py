import json

from backend.db import connect, init_db, row
from backend.otel import ingest_logs


def test_otel_log_ingest_discards_prompt_content(tmp_path) -> None:
    conn = connect(tmp_path / "otel.sqlite")
    init_db(conn)
    payload = json.loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "fixtures" / "otel-log-sample.json").read_text())
    result = ingest_logs(conn, payload)

    assert result["inserted"] == 1
    stored = row(conn, "SELECT event_name, tool_name, duration_ms, attributes_json FROM otel_events")
    assert stored["event_name"] == "codex.tool_result"
    assert stored["tool_name"] == "shell_command"
    assert stored["duration_ms"] == 42
    assert "prompt" not in stored["attributes_json"].lower()
