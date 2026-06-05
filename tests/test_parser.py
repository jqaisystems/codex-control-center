from pathlib import Path

from backend.codex_parser import parse_session_file


def test_parse_fake_codex_session_metadata() -> None:
    root = Path(__file__).resolve().parents[1]
    fixture = root / "fixtures" / "codex-session-sample.jsonl"
    parsed = parse_session_file(fixture, root)
    session = parsed["session"]

    assert session["session_id"] == "demo-session-0001"
    assert session["model"] == "gpt-5-codex"
    assert session["project_label"].startswith("demo-app#")
    assert session["total_tokens"] == 1380
    assert session["tool_count"] == 1
    assert parsed["tools"][0]["tool_name"] == "shell_command"

    usage = parsed["usage_limit"]
    assert usage["limit_id"] == "codex"
    assert usage["plan_type"] == "example"
    assert usage["primary_used_percent"] == 55.0
    assert usage["primary_remaining_percent"] == 45.0
    assert usage["secondary_remaining_percent"] == 75.0
    assert usage["source_session_id"] == "demo-session-0001"


def test_parse_multiple_usage_limit_observations(tmp_path) -> None:
    codex_home = tmp_path / "codex"
    session_dir = codex_home / "sessions"
    session_dir.mkdir(parents=True)
    session_file = session_dir / "demo-session.jsonl"
    session_file.write_text(
        "\n".join(
            [
                '{"timestamp":"2026-06-03T10:00:00Z","type":"session_meta","payload":{"id":"demo-session-0002","cwd":"C:\\\\Users\\\\Example\\\\Projects\\\\demo-app","source":"cli"}}',
                '{"timestamp":"2026-06-03T10:05:00Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":100}},"rate_limits":{"limit_id":"codex","plan_type":"example","primary":{"used_percent":40,"window_minutes":300,"resets_at":1780486936},"secondary":{"used_percent":20,"window_minutes":10080,"resets_at":1780859825},"rate_limit_reached_type":null}}}',
                '{"timestamp":"2026-06-03T11:05:00Z","type":"event_msg","payload":{"type":"token_count","info":{"total_token_usage":{"total_tokens":200}},"rate_limits":{"limit_id":"codex","plan_type":"example","primary":{"used_percent":55,"window_minutes":300,"resets_at":1780486936},"secondary":{"used_percent":25,"window_minutes":10080,"resets_at":1780859825},"rate_limit_reached_type":"primary"}}}',
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_session_file(session_file, codex_home)

    observations = parsed["usage_observations"]
    assert len(observations) == 2
    assert observations[0]["primary_remaining_percent"] == 60.0
    assert observations[1]["primary_remaining_percent"] == 45.0
    assert observations[1]["rate_limit_reached_type"] == "primary"
    assert observations[0]["dedupe_key"] != observations[1]["dedupe_key"]
    assert "source_session_id" not in observations[0]
    assert "source_session_id" not in observations[1]
    assert parsed["usage_limit"]["source_session_id"] == "demo-session-0002"
