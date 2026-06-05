import io
import json

from backend import task_runner
from backend.db import connect, init_db


def test_task_runner_uses_selected_workspace_for_cd(monkeypatch, tmp_path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    init_db(conn)
    default_repo = tmp_path / "default"
    workspace_root = tmp_path / "workspace"
    default_repo.mkdir()
    workspace_root.mkdir()
    conn.execute(
        """
        INSERT INTO workspaces(name, root_path, path_label, path_hash, is_default, created_at, updated_at)
        VALUES ('Workspace', ?, 'workspace#abc123', 'abc123', 0, ?, ?)
        """,
        (str(workspace_root), task_runner.now_iso(), task_runner.now_iso()),
    )
    workspace_id = conn.execute("SELECT id FROM workspaces").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO ops_tasks(
          title, description, status, priority, sandbox, workspace_id, cwd_label, cwd_hash,
          created_at, updated_at
        ) VALUES ('Safe task', 'Inspect public-safe files only.', 'pending', 3, 'read-only', ?, 'workspace#abc123', 'abc123', ?, ?)
        """,
        (workspace_id, task_runner.now_iso(), task_runner.now_iso()),
    )
    task_id = conn.execute("SELECT id FROM ops_tasks").fetchone()["id"]
    conn.commit()
    captured = {}

    class FakeProcess:
        pid = 12345

        def __init__(self, cmd, cwd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = cwd
            self.stdout = io.StringIO(
                json.dumps({"type": "thread.started", "thread_id": "thread-test"}) + "\n"
                + json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Safe result."}}) + "\n"
            )

        def wait(self):
            return 0

    monkeypatch.setattr(task_runner, "codex_executable", lambda: "codex")
    monkeypatch.setattr(task_runner.subprocess, "Popen", FakeProcess)

    task_runner._run_task(conn, task_id, default_repo)

    cd_index = captured["cmd"].index("--cd")
    assert captured["cmd"][cd_index + 1] == str(workspace_root)
    assert captured["cwd"] == str(workspace_root)
    task = conn.execute("SELECT * FROM ops_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "done"
    assert task["output_summary"] == "Safe result."


def test_task_runner_fails_safely_when_workspace_missing(tmp_path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    init_db(conn)
    default_repo = tmp_path / "default"
    default_repo.mkdir()
    missing_root = tmp_path / "missing"
    conn.execute(
        """
        INSERT INTO workspaces(name, root_path, path_label, path_hash, is_default, created_at, updated_at)
        VALUES ('Missing', ?, 'missing#abc123', 'abc123', 0, ?, ?)
        """,
        (str(missing_root), task_runner.now_iso(), task_runner.now_iso()),
    )
    workspace_id = conn.execute("SELECT id FROM workspaces").fetchone()["id"]
    conn.execute(
        """
        INSERT INTO ops_tasks(
          title, description, status, priority, sandbox, workspace_id, cwd_label, cwd_hash,
          created_at, updated_at
        ) VALUES ('Safe task', 'Inspect public-safe files only.', 'pending', 3, 'read-only', ?, 'missing#abc123', 'abc123', ?, ?)
        """,
        (workspace_id, task_runner.now_iso(), task_runner.now_iso()),
    )
    task_id = conn.execute("SELECT id FROM ops_tasks").fetchone()["id"]
    conn.commit()

    task_runner._run_task(conn, task_id, default_repo)

    task = conn.execute("SELECT * FROM ops_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "failed"
    assert task["output_summary"] == "Selected workspace folder is unavailable."
    assert str(missing_root) not in task["output_summary"]


def test_task_runner_records_token_usage_when_emitted(monkeypatch, tmp_path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    init_db(conn)
    default_repo = tmp_path / "default"
    default_repo.mkdir()
    conn.execute(
        """
        INSERT INTO ops_tasks(
          title, description, status, priority, sandbox, cwd_label, cwd_hash,
          created_at, updated_at
        ) VALUES ('Token task', 'Inspect public-safe files only.', 'pending', 3, 'read-only', 'default#abc123', 'abc123', ?, ?)
        """,
        (task_runner.now_iso(), task_runner.now_iso()),
    )
    task_id = conn.execute("SELECT id FROM ops_tasks").fetchone()["id"]
    conn.commit()

    class FakeProcess:
        pid = 12346

        def __init__(self, *args, **kwargs):
            self.stdout = io.StringIO(
                json.dumps({"type": "thread.started", "thread_id": "thread-test"}) + "\n"
                + json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "token_count",
                            "info": {
                                "total_token_usage": {
                                    "input_tokens": 120,
                                    "cached_input_tokens": 20,
                                    "output_tokens": 40,
                                    "reasoning_output_tokens": 5,
                                    "total_tokens": 160,
                                }
                            },
                        },
                    }
                ) + "\n"
                + json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Safe result."}}) + "\n"
            )

        def wait(self):
            return 0

    monkeypatch.setattr(task_runner, "codex_executable", lambda: "codex")
    monkeypatch.setattr(task_runner.subprocess, "Popen", FakeProcess)

    task_runner._run_task(conn, task_id, default_repo)

    task = conn.execute("SELECT * FROM ops_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "done"
    assert task["input_tokens"] == 120
    assert task["cached_input_tokens"] == 20
    assert task["output_tokens"] == 40
    assert task["reasoning_output_tokens"] == 5
    assert task["total_tokens"] == 160


def test_task_runner_leaves_token_usage_unknown_when_missing(monkeypatch, tmp_path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    init_db(conn)
    default_repo = tmp_path / "default"
    default_repo.mkdir()
    conn.execute(
        """
        INSERT INTO ops_tasks(
          title, description, status, priority, sandbox, cwd_label, cwd_hash,
          created_at, updated_at
        ) VALUES ('No token task', 'Inspect public-safe files only.', 'pending', 3, 'read-only', 'default#abc123', 'abc123', ?, ?)
        """,
        (task_runner.now_iso(), task_runner.now_iso()),
    )
    task_id = conn.execute("SELECT id FROM ops_tasks").fetchone()["id"]
    conn.commit()

    class FakeProcess:
        pid = 12347

        def __init__(self, *args, **kwargs):
            self.stdout = io.StringIO(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Safe result."}}) + "\n")

        def wait(self):
            return 0

    monkeypatch.setattr(task_runner, "codex_executable", lambda: "codex")
    monkeypatch.setattr(task_runner.subprocess, "Popen", FakeProcess)

    task_runner._run_task(conn, task_id, default_repo)

    task = conn.execute("SELECT * FROM ops_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "done"
    assert task["total_tokens"] is None


def test_task_runner_ignores_unexpected_json_event_shapes(monkeypatch, tmp_path) -> None:
    conn = connect(tmp_path / "test.sqlite")
    init_db(conn)
    default_repo = tmp_path / "default"
    default_repo.mkdir()
    conn.execute(
        """
        INSERT INTO ops_tasks(
          title, description, status, priority, sandbox, cwd_label, cwd_hash,
          created_at, updated_at
        ) VALUES ('Odd event task', 'Inspect public-safe files only.', 'pending', 3, 'read-only', 'default#abc123', 'abc123', ?, ?)
        """,
        (task_runner.now_iso(), task_runner.now_iso()),
    )
    task_id = conn.execute("SELECT id FROM ops_tasks").fetchone()["id"]
    conn.commit()

    class FakeProcess:
        pid = 12348

        def __init__(self, *args, **kwargs):
            self.stdout = io.StringIO(
                json.dumps({"type": "thread.started", "thread_id": "thread-test"}) + "\n"
                + json.dumps(["unexpected", "array", "event"]) + "\n"
                + json.dumps({"type": "item.completed", "item": ["unexpected", "item"]}) + "\n"
                + json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "Safe result."}}) + "\n"
            )

        def wait(self):
            return 0

    monkeypatch.setattr(task_runner, "codex_executable", lambda: "codex")
    monkeypatch.setattr(task_runner.subprocess, "Popen", FakeProcess)

    task_runner._run_task(conn, task_id, default_repo)

    task = conn.execute("SELECT * FROM ops_tasks WHERE id=?", (task_id,)).fetchone()
    assert task["status"] == "done"
    assert task["output_summary"] == "Safe result."
    assert task["event_count"] == 3
