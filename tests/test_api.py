import importlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


def load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("CCC_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CCC_DB_PATH", str(tmp_path / "home" / "test.sqlite"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CCC_CONTROL_TOKEN", "test-control-token")
    import backend.app as app_module

    return importlib.reload(app_module)


def test_health_no_api_key_required(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["api_key_required"] is False
    assert data["auth_json_read"] is False
    assert data["db_label"]
    assert data["session_files_scanned"] == 0
    assert data["control_mode_reason"]
    assert data["otel"]["status"] in {"off", "configured", "receiving"}


def test_system_mode_defaults_and_persists(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    default = client.get("/api/system-mode")
    assert default.status_code == 200
    assert default.json()["mode"] == "full"

    updated = client.post("/api/system-mode", json={"mode": "token_saver"})
    assert updated.status_code == 200
    assert updated.json()["mode"] == "token_saver"
    assert updated.json()["token_saver_active"] is True

    persisted = client.get("/api/system-mode")
    assert persisted.json()["mode"] == "token_saver"

    invalid = client.post("/api/system-mode", json={"mode": "private"})
    assert invalid.status_code == 400


def test_default_workspace_is_safe_to_display(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.get("/api/workspaces")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    workspace = data["items"][0]
    assert workspace["is_default"] == 1
    assert "#" in workspace["path_label"]
    assert "root_path" not in workspace
    assert str(app_module.repo_root) not in json.dumps(workspace)


def test_publish_readiness_is_safe_to_display(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.get("/api/publish-readiness")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"ready", "needs_review", "blocked"}
    assert data["does_not_publish"] is True
    assert data["package"]["path_label"]
    assert "root_path" not in json.dumps(data)
    assert str(app_module.repo_root) not in json.dumps(data)
    assert data["safety_scan"]["status"] in {"READY", "BLOCK"}
    assert data["checks"]


def test_publish_readiness_treats_ignored_local_artifacts_as_ok(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    package = tmp_path / "public-package"
    package.mkdir()
    for name in [
        "README.md",
        "ARCHITECTURE.md",
        "SECURITY.md",
        "PUBLICATION_CHECKLIST.md",
        "LICENSE",
        ".env.example",
        "requirements.txt",
        "start-control-center.ps1",
    ]:
        (package / name).write_text("example public file\n", encoding="utf-8")
    (package / "README.md").write_text(
        "No API key required for local observation. Tested on Windows 11. Runs on 127.0.0.1.\n",
        encoding="utf-8",
    )
    (package / ".gitignore").write_text(
        "\n".join([
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
        ]),
        encoding="utf-8",
    )
    for dirname in ["backend", "scripts", "tests", "fixtures", "ui", "docs", ".venv", "logs", "ui/node_modules", "ui/dist"]:
        (package / dirname).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(app_module, "repo_root", package)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.get("/api/publish-readiness")

    assert response.status_code == 200
    data = response.json()
    checks = {check["id"]: check for check in data["checks"]}
    assert checks["readme-positioning"]["status"] == "ok"
    assert checks["local-artifacts"]["status"] == "ok"
    assert "covered by .gitignore" in checks["local-artifacts"]["detail"]


def test_add_workspace_returns_label_not_path(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "vault"
    vault.mkdir()

    response = client.post("/api/workspaces", json={"name": "My Vault", "path": str(vault)})

    assert response.status_code == 200
    workspace = response.json()["workspace"]
    assert workspace["name"] == "My Vault"
    assert workspace["path_label"].startswith("vault#")
    assert "root_path" not in workspace
    assert str(vault) not in str(workspace)
    listed = client.get("/api/workspaces").json()["items"]
    assert any(item["id"] == workspace["id"] for item in listed)


def test_workspace_rejects_invalid_paths(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    missing = client.post("/api/workspaces", json={"name": "Missing", "path": str(tmp_path / "missing")})
    assert missing.status_code == 400

    file_path = tmp_path / "file.txt"
    file_path.write_text("not a folder", encoding="utf-8")
    file_response = client.post("/api/workspaces", json={"name": "File", "path": str(file_path)})
    assert file_response.status_code == 400

    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    codex_response = client.post("/api/workspaces", json={"name": "Codex Home", "path": str(codex_home)})
    assert codex_response.status_code == 400


def test_health_score_default_workspace_returns_safe_labels(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.get("/api/health-score")

    assert response.status_code == 200
    data = response.json()
    assert 0 <= data["overall_score"] <= 100
    assert 0 <= data["system_score"] <= 100
    assert 0 <= data["workspace_score"] <= 100
    assert data["workspace"]["name"]
    assert data["workspace"]["path_label"]
    assert data["findings"]
    payload = json.dumps(data)
    assert "root_path" not in payload
    assert str(app_module.repo_root) not in payload


def test_health_score_risky_workspace_lowers_score_without_paths(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "risky-vault"
    vault.mkdir()
    (vault / ".env").write_text("example only", encoding="utf-8")
    (vault / "logs").mkdir()
    (vault / "data.sqlite").write_text("example only", encoding="utf-8")
    workspace = client.post("/api/workspaces", json={"name": "Risky Vault", "path": str(vault)}).json()["workspace"]

    response = client.get(f"/api/health-score?workspace_id={workspace['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["workspace"]["path_label"].startswith("risky-vault#")
    assert data["workspace_score"] < 100
    assert any(item["level"] in {"bad", "warn"} for item in data["findings"])
    payload = json.dumps(data)
    assert "root_path" not in payload
    assert str(vault) not in payload
    assert str(vault).replace("\\", "\\\\") not in payload


def test_health_score_report_lists_safe_risky_locations(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "report-vault"
    (vault / "logs").mkdir(parents=True)
    (vault / "sessions").mkdir()
    (vault / "node_modules").mkdir()
    (vault / ".env").write_text("example only", encoding="utf-8")
    (vault / "auth.json").write_text("example only", encoding="utf-8")
    (vault / "data.sqlite").write_text("example only", encoding="utf-8")
    (vault / "logs" / "app.log").write_text("example only", encoding="utf-8")
    (vault / "sessions" / "demo-session.jsonl").write_text("example only", encoding="utf-8")
    workspace = client.post("/api/workspaces", json={"name": "Report Vault", "path": str(vault)}).json()["workspace"]

    response = client.get(f"/api/health-score/report?workspace_id={workspace['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["workspace"]["path_label"].startswith("report-vault#")
    assert data["scan"]["matched_locations"] >= 5
    categories = {match["category"] for match in data["matches"]}
    assert {"secret-like", "database-like", "log-like", "raw-session-like", "generated-folder"} <= categories
    secret_match = next(match for match in data["matches"] if match["category"] == "secret-like")
    assert secret_match["level"] == "bad"
    assert secret_match["kind"] == "file"
    assert secret_match["relative_path"] in {".env", "auth.json"}
    assert secret_match["ignore_coverage"]["status"] == "unknown"
    assert "full_path" not in secret_match
    payload = json.dumps(data)
    assert "root_path" not in payload
    assert str(vault) not in payload
    assert str(vault).replace("\\", "\\\\") not in payload


def test_health_score_report_checks_gitignore_coverage(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "ignored-vault"
    (vault / "logs").mkdir(parents=True)
    (vault / "nested").mkdir()
    (vault / ".gitignore").write_text(".env\nlogs/\n*.db\n", encoding="utf-8")
    (vault / ".env").write_text("example only", encoding="utf-8")
    (vault / "logs" / "app.log").write_text("example only", encoding="utf-8")
    (vault / "data.db").write_text("example only", encoding="utf-8")
    (vault / "auth.json").write_text("example only", encoding="utf-8")
    (vault / "nested" / ".env").write_text("example only", encoding="utf-8")
    workspace = client.post("/api/workspaces", json={"name": "Ignored Vault", "path": str(vault)}).json()["workspace"]

    response = client.get(f"/api/health-score/report?workspace_id={workspace['id']}")

    assert response.status_code == 200
    data = response.json()
    by_path = {match["relative_path"]: match for match in data["matches"]}
    assert by_path[".env"]["ignore_coverage"]["status"] == "protected"
    assert by_path["logs"]["ignore_coverage"]["status"] == "protected"
    assert by_path["logs/app.log"]["ignore_coverage"]["status"] == "protected"
    assert by_path["data.db"]["ignore_coverage"]["status"] == "protected"
    assert by_path["nested/.env"]["ignore_coverage"]["status"] == "protected"
    assert by_path["auth.json"]["ignore_coverage"]["status"] == "not_ignored"
    coverage = data["scan"]["gitignore_coverage"]
    assert coverage["protected"] >= 5
    assert coverage["not_ignored"] >= 1
    assert coverage["unknown"] == 0
    assert coverage["ignore_files_read"] == 1
    payload = json.dumps(data)
    assert str(vault) not in payload
    assert str(vault).replace("\\", "\\\\") not in payload


def test_health_score_report_review_status_is_local_and_safe(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "review-vault"
    vault.mkdir()
    (vault / ".env").write_text("example only", encoding="utf-8")
    workspace = client.post("/api/workspaces", json={"name": "Review Vault", "path": str(vault)}).json()["workspace"]
    report = client.get(f"/api/health-score/report?workspace_id={workspace['id']}").json()
    match = next(item for item in report["matches"] if item["category"] == "secret-like")
    assert match["review"]["status"] == "needs_action"
    assert report["scan"]["review_summary"]["needs_action"] == len(report["matches"])

    saved = client.post(
        "/api/health-score/reviews",
        json={"workspace_id": workspace["id"], "review_key": match["review_key"], "status": "reviewed"},
    )

    assert saved.status_code == 200
    updated = client.get(f"/api/health-score/report?workspace_id={workspace['id']}").json()
    updated_match = next(item for item in updated["matches"] if item["review_key"] == match["review_key"])
    assert updated_match["review"]["status"] == "reviewed"
    assert updated["scan"]["review_summary"]["reviewed"] == 1
    payload = json.dumps(updated)
    assert str(vault) not in payload
    assert str(vault).replace("\\", "\\\\") not in payload

    bad_status = client.post(
        "/api/health-score/reviews",
        json={"workspace_id": workspace["id"], "review_key": match["review_key"], "status": "private"},
    )
    assert bad_status.status_code == 400

    missing_key = client.post(
        "/api/health-score/reviews",
        json={"workspace_id": workspace["id"], "review_key": "secret-like|file|missing.env", "status": "reviewed"},
    )
    assert missing_key.status_code == 404


def test_health_score_report_bulk_review_status(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "bulk-review-vault"
    (vault / "logs").mkdir(parents=True)
    (vault / ".env").write_text("example only", encoding="utf-8")
    (vault / "logs" / "app.log").write_text("example only", encoding="utf-8")
    workspace = client.post("/api/workspaces", json={"name": "Bulk Review Vault", "path": str(vault)}).json()["workspace"]
    report = client.get(f"/api/health-score/report?workspace_id={workspace['id']}").json()
    keys = [match["review_key"] for match in report["matches"][:2]]

    saved = client.post(
        "/api/health-score/reviews/bulk",
        json={"workspace_id": workspace["id"], "review_keys": keys, "status": "accepted_risk"},
    )

    assert saved.status_code == 200
    assert saved.json()["updated"] == 2
    updated = client.get(f"/api/health-score/report?workspace_id={workspace['id']}").json()
    statuses = {match["review_key"]: match["review"]["status"] for match in updated["matches"]}
    assert all(statuses[key] == "accepted_risk" for key in keys)
    assert updated["scan"]["review_summary"]["accepted_risk"] == 2

    invalid = client.post(
        "/api/health-score/reviews/bulk",
        json={"workspace_id": workspace["id"], "review_keys": [keys[0], "secret-like|file|missing.env"], "status": "reviewed"},
    )
    assert invalid.status_code == 404


def test_health_score_report_reveals_full_paths_only_on_demand(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    authed_client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    unauthenticated_client = TestClient(app_module.app)
    vault = tmp_path / "reveal-vault"
    vault.mkdir()
    (vault / ".env.local").write_text("example only", encoding="utf-8")
    workspace = authed_client.post("/api/workspaces", json={"name": "Reveal Vault", "path": str(vault)}).json()["workspace"]

    blocked = unauthenticated_client.get(f"/api/health-score/report/paths?workspace_id={workspace['id']}")
    assert blocked.status_code == 401

    revealed = authed_client.get(f"/api/health-score/report/paths?workspace_id={workspace['id']}")

    assert revealed.status_code == 200
    data = revealed.json()
    assert data["workspace"]["root_path"] == str(vault)
    paths = {item["full_path"] for item in data["matches"]}
    assert str(vault / ".env.local") in paths


def test_health_score_rejects_missing_or_deleted_workspace(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "gone"
    vault.mkdir()
    workspace = client.post("/api/workspaces", json={"name": "Gone", "path": str(vault)}).json()["workspace"]
    vault.rmdir()

    missing_folder = client.get(f"/api/health-score?workspace_id={workspace['id']}")

    assert missing_folder.status_code == 400
    missing_report = client.get(f"/api/health-score/report?workspace_id={workspace['id']}")
    assert missing_report.status_code == 400

    app_module.conn.execute("DELETE FROM workspaces WHERE id=?", (workspace["id"],))
    app_module.conn.commit()
    deleted = client.get(f"/api/health-score?workspace_id={workspace['id']}")
    assert deleted.status_code == 404
    deleted_report = client.get(f"/api/health-score/report?workspace_id={workspace['id']}")
    assert deleted_report.status_code == 404


def test_health_score_report_marks_truncated_scans(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "WORKSPACE_SCORE_MAX_ENTRIES", 1)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "large-vault"
    (vault / "first").mkdir(parents=True)
    (vault / "second").mkdir()
    workspace = client.post("/api/workspaces", json={"name": "Large Vault", "path": str(vault)}).json()["workspace"]

    response = client.get(f"/api/health-score/report?workspace_id={workspace['id']}")

    assert response.status_code == 200
    data = response.json()
    assert data["scan"]["truncated"] is True
    assert any(finding["title"] == "Workspace: Large folder sampled" for finding in data["findings"])


def test_health_score_report_deep_scan_expands_metadata_sample(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "WORKSPACE_SCORE_MAX_ENTRIES", 100)
    monkeypatch.setattr(app_module, "WORKSPACE_SCORE_MAX_DEPTH", 1)
    monkeypatch.setattr(app_module, "WORKSPACE_DEEP_SCAN_MAX_ENTRIES", 100)
    monkeypatch.setattr(app_module, "WORKSPACE_DEEP_SCAN_MAX_DEPTH", 4)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "deep-vault"
    secret_dir = vault / "nested" / "sub" / "private"
    secret_dir.mkdir(parents=True)
    (secret_dir / ".env").write_text("example only", encoding="utf-8")
    workspace = client.post("/api/workspaces", json={"name": "Deep Vault", "path": str(vault)}).json()["workspace"]

    standard = client.get(f"/api/health-score/report?workspace_id={workspace['id']}")
    deep = client.get(f"/api/health-score/report?workspace_id={workspace['id']}&scan_mode=deep")

    assert standard.status_code == 200
    assert deep.status_code == 200
    standard_data = standard.json()
    deep_data = deep.json()
    assert standard_data["scan"]["scan_mode"] == "standard"
    assert standard_data["scan"]["max_depth"] == 1
    assert not any(match["relative_path"].endswith(".env") for match in standard_data["matches"])
    assert deep_data["scan"]["scan_mode"] == "deep"
    assert deep_data["scan"]["max_depth"] == 4
    deep_secret = next(match for match in deep_data["matches"] if match["relative_path"] == "nested/sub/private/.env")
    assert deep_secret["category"] == "secret-like"
    assert "full_path" not in deep_secret
    payload = json.dumps(deep_data)
    assert str(vault) not in payload
    assert str(vault).replace("\\", "\\\\") not in payload

    saved = client.post(
        "/api/health-score/reviews",
        json={"workspace_id": workspace["id"], "review_key": deep_secret["review_key"], "status": "reviewed", "scan_mode": "deep"},
    )
    assert saved.status_code == 200


def test_health_score_report_rejects_unknown_scan_mode(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "scan-mode-vault"
    vault.mkdir()
    workspace = client.post("/api/workspaces", json={"name": "Scan Mode Vault", "path": str(vault)}).json()["workspace"]

    response = client.get(f"/api/health-score/report?workspace_id={workspace['id']}&scan_mode=private")

    assert response.status_code == 400


def test_workspace_browser_roots_return_safe_tokens(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.get("/api/workspace-browser/roots")

    assert response.status_code == 200
    data = response.json()
    assert data["items"]
    first = data["items"][0]
    assert first["label"]
    assert first["token"]
    assert "path" not in first
    assert "root_path" not in first
    labels = {item["label"] for item in data["items"]}
    assert "Home" not in labels
    assert not any(label.startswith("Drive ") for label in labels)
    assert str(Path.home()) not in json.dumps(data)


def test_workspace_browser_folder_listing_returns_safe_labels(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    parent = tmp_path / "browse-parent"
    child = parent / "child-folder"
    child.mkdir(parents=True)
    token = app_module._register_browser_path(parent)

    response = client.get(f"/api/workspace-browser/folders?token={token}")

    assert response.status_code == 200
    data = response.json()
    assert data["current"]["label"] == parent.name
    assert [item["label"] for item in data["breadcrumbs"]] == [parent.name]
    assert any(item["label"] == child.name for item in data["children"])
    assert str(parent) not in json.dumps(data)
    assert all("path" not in item for item in data["children"])


def test_workspace_browser_add_root_from_path(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    alternate = tmp_path / "alternate-root"
    nested = alternate / "nested"
    nested.mkdir(parents=True)

    root_response = client.post("/api/workspace-browser/roots", json={"path": str(alternate), "name": "Alternate"})

    assert root_response.status_code == 200
    root = root_response.json()["root"]
    assert root["label"] == "Alternate"
    assert "path" not in root
    assert str(alternate) not in json.dumps(root_response.json())

    folder_response = client.get(f"/api/workspace-browser/folders?token={root['token']}")
    assert folder_response.status_code == 200
    data = folder_response.json()
    assert [item["label"] for item in data["breadcrumbs"]] == [alternate.name]
    assert any(item["label"] == nested.name for item in data["children"])


def test_workspace_browser_hides_codex_home(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    visible = tmp_path / "visible"
    visible.mkdir()
    token = app_module._register_browser_path(tmp_path)

    response = client.get(f"/api/workspace-browser/folders?token={token}")

    assert response.status_code == 200
    labels = {item["label"] for item in response.json()["children"]}
    assert "visible" in labels
    assert "codex" not in labels


def test_create_workspace_from_browser_token(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "browsed"
    vault.mkdir()
    token = app_module._register_browser_path(vault)

    response = client.post("/api/workspaces", json={"name": "Browsed", "browser_token": token})

    assert response.status_code == 200
    workspace = response.json()["workspace"]
    assert workspace["path_label"].startswith("browsed#")
    assert str(vault) not in json.dumps(response.json())


def test_workspace_browser_rejects_invalid_or_blocked_tokens(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    codex_home = tmp_path / "codex"
    codex_home.mkdir()
    blocked_token = app_module._register_browser_path(codex_home)

    invalid = client.post("/api/workspaces", json={"name": "Bad", "browser_token": "expired-token"})
    assert invalid.status_code == 404

    blocked = client.post("/api/workspaces", json={"name": "Blocked", "browser_token": blocked_token})
    assert blocked.status_code == 400


def test_task_creation_uses_selected_workspace_label(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "selected"
    vault.mkdir()
    workspace = client.post("/api/workspaces", json={"name": "Selected", "path": str(vault)}).json()["workspace"]

    response = client.post(
        "/api/tasks",
        json={
            "title": "Workspace task",
            "description": "Inspect public-safe files only.",
            "sandbox": "read-only",
            "workspace_id": workspace["id"],
        },
    )

    assert response.status_code == 200
    task = client.get("/api/tasks").json()["items"][0]
    assert task["workspace_id"] == workspace["id"]
    assert task["cwd_label"] == workspace["path_label"]
    assert str(vault) not in str(task)


def test_schedule_materializes_selected_workspace(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "scheduled"
    vault.mkdir()
    workspace = client.post("/api/workspaces", json={"name": "Scheduled", "path": str(vault)}).json()["workspace"]

    created = client.post(
        "/api/schedules",
        json={
            "name": "Workspace schedule",
            "cron_expression": "@daily",
            "task_title": "Scheduled workspace task",
            "task_description": "Inspect public-safe files only.",
            "enabled": True,
            "workspace_id": workspace["id"],
        },
    )
    assert created.status_code == 200
    schedule_id = created.json()["schedule_id"]
    app_module.conn.execute(
        "UPDATE ops_schedules SET next_run_at=? WHERE id=?",
        ("2000-01-01T00:00:00+00:00", schedule_id),
    )
    app_module.conn.commit()

    response = client.post("/api/schedules/materialize-due")

    assert response.status_code == 200
    task = client.get("/api/tasks").json()["items"][0]
    schedule = client.get("/api/schedules").json()["items"][0]
    assert task["workspace_id"] == workspace["id"]
    assert task["cwd_label"] == workspace["path_label"]
    assert schedule["workspace_id"] == workspace["id"]


def test_workspace_delete_is_blocked_for_active_use(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "active"
    vault.mkdir()
    workspace = client.post("/api/workspaces", json={"name": "Active", "path": str(vault)}).json()["workspace"]

    client.post(
        "/api/tasks",
        json={
            "title": "Active task",
            "description": "Inspect public-safe files only.",
            "sandbox": "read-only",
            "workspace_id": workspace["id"],
        },
    )

    blocked = client.delete(f"/api/workspaces/{workspace['id']}")
    assert blocked.status_code == 409

    task = client.get("/api/tasks").json()["items"][0]
    client.post(f"/api/tasks/{task['id']}/archive")
    deleted = client.delete(f"/api/workspaces/{workspace['id']}")
    assert deleted.status_code == 200
    assert all(item["id"] != workspace["id"] for item in client.get("/api/workspaces").json()["items"])


def test_workspace_delete_is_blocked_for_enabled_schedule(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    vault = tmp_path / "scheduled-active"
    vault.mkdir()
    workspace = client.post("/api/workspaces", json={"name": "Scheduled Active", "path": str(vault)}).json()["workspace"]
    schedule = client.post(
        "/api/schedules",
        json={
            "name": "Enabled schedule",
            "cron_expression": "@daily",
            "task_title": "Scheduled safe task",
            "task_description": "Inspect public-safe files only.",
            "enabled": True,
            "workspace_id": workspace["id"],
        },
    ).json()

    blocked = client.delete(f"/api/workspaces/{workspace['id']}")
    assert blocked.status_code == 409

    client.post(f"/api/schedules/{schedule['schedule_id']}/toggle", json={"enabled": False})
    deleted = client.delete(f"/api/workspaces/{workspace['id']}")
    assert deleted.status_code == 200


def test_task_rejects_secret_like_text(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    response = client.post(
        "/api/tasks",
        json={"title": "bad", "description": "token=sk-thisisnotarealkeybutlookslong", "sandbox": "read-only"},
    )
    assert response.status_code == 400


def test_approve_task_stays_approval_gated(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "codex_login_status", lambda: {"available": True, "status": "Logged in using test"})
    launched = []
    monkeypatch.setattr(app_module, "launch_task", lambda conn, task_id, repo_root: launched.append(task_id))
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    created = client.post(
        "/api/tasks",
        json={"title": "demo", "description": "safe fake task", "sandbox": "read-only"},
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]
    listed = client.get("/api/tasks").json()["items"][0]
    assert listed["status"] == "awaiting_approval"

    approved = client.post(f"/api/tasks/{task_id}/approve")
    assert approved.status_code == 200
    assert launched == [task_id]


def test_token_saver_blocks_task_approval(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    monkeypatch.setattr(app_module, "codex_login_status", lambda: {"available": True, "status": "Logged in using test"})
    launched = []
    monkeypatch.setattr(app_module, "launch_task", lambda conn, task_id, repo_root: launched.append(task_id))
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    client.post("/api/system-mode", json={"mode": "token_saver"})
    created = client.post(
        "/api/tasks",
        json={"title": "demo", "description": "safe fake task", "sandbox": "read-only"},
    )
    task_id = created.json()["task_id"]

    approved = client.post(f"/api/tasks/{task_id}/approve")

    assert approved.status_code == 409
    assert "Token Saver" in approved.text
    assert launched == []
    task = client.get(f"/api/tasks/{task_id}").json()["task"]
    assert task["status"] == "awaiting_approval"


def test_archive_hides_task_from_board(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    created = client.post(
        "/api/tasks",
        json={"title": "archive me", "description": "safe fake task", "sandbox": "read-only"},
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    archived = client.post(f"/api/tasks/{task_id}/archive")
    assert archived.status_code == 200
    assert archived.json()["archived"] is True

    listed = client.get("/api/tasks")
    assert listed.status_code == 200
    assert listed.json()["items"] == []

    details = client.get(f"/api/tasks/{task_id}")
    assert details.status_code == 200
    assert details.json()["task"]["archived"] == 1


def test_task_history_filters_and_stats(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    app_module.conn.executemany(
        """
        INSERT INTO ops_tasks(
          title, description, status, priority, sandbox, cwd_label, cwd_hash,
          completed_at, duration_ms, exit_code, event_count, tool_count,
          archived, output_summary, created_at, updated_at
        ) VALUES (?, ?, ?, 3, 'read-only', 'demo#abc123', 'abc123', ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "Successful result",
                "safe task",
                "done",
                "2026-06-03T12:00:00+00:00",
                1500,
                0,
                4,
                1,
                0,
                "Safe summary",
                "2026-06-03T11:59:00+00:00",
                "2026-06-03T12:00:00+00:00",
            ),
            (
                "Failed result",
                "safe task",
                "failed",
                "2026-06-03T12:05:00+00:00",
                2500,
                1,
                3,
                0,
                1,
                "Safe failure",
                "2026-06-03T12:04:00+00:00",
                "2026-06-03T12:05:00+00:00",
            ),
        ],
    )
    app_module.conn.commit()
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    history = client.get("/api/tasks/history")
    assert history.status_code == 200
    data = history.json()
    assert len(data["items"]) == 2
    assert data["stats"]["done"] == 1
    assert data["stats"]["failed"] == 1
    assert data["stats"]["total_tools"] == 1

    failed = client.get("/api/tasks/history?status=failed")
    assert failed.status_code == 200
    assert [item["title"] for item in failed.json()["items"]] == ["Failed result"]

    visible_only = client.get("/api/tasks/history?include_archived=false")
    assert visible_only.status_code == 200
    assert len(visible_only.json()["items"]) == 1

    searched = client.get("/api/tasks/history?query=Successful")
    assert searched.status_code == 200
    assert [item["title"] for item in searched.json()["items"]] == ["Successful result"]

    invalid = client.get("/api/tasks/history?status=private")
    assert invalid.status_code == 400


def test_task_token_usage_endpoint_returns_safe_aggregates(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    app_module.conn.executemany(
        """
        INSERT INTO ops_tasks(
          title, description, status, priority, sandbox, cwd_label, cwd_hash,
          approved_at, started_at, completed_at, duration_ms, exit_code, event_count, tool_count,
          input_tokens, cached_input_tokens, output_tokens, reasoning_output_tokens, total_tokens,
          archived, output_summary, thread_id, created_at, updated_at
        ) VALUES (?, ?, ?, 3, 'read-only', 'demo#abc123', 'abc123', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        """,
        [
            (
                "Private-ish title stays out of token endpoint",
                "safe task",
                "done",
                "2026-06-03T11:59:00+00:00",
                "2026-06-03T11:59:10+00:00",
                "2026-06-03T12:00:00+00:00",
                1500,
                0,
                4,
                1,
                100,
                20,
                40,
                5,
                140,
                "Safe summary",
                "thread-private",
                "2026-06-03T11:59:00+00:00",
                "2026-06-03T12:00:00+00:00",
            ),
            (
                "Unknown tokens",
                "safe task",
                "failed",
                "2026-06-04T11:59:00+00:00",
                "2026-06-04T11:59:10+00:00",
                "2026-06-04T12:00:00+00:00",
                1500,
                1,
                3,
                0,
                None,
                None,
                None,
                None,
                None,
                "Safe failure",
                "thread-private-2",
                "2026-06-04T11:59:00+00:00",
                "2026-06-04T12:00:00+00:00",
            ),
        ],
    )
    app_module.conn.commit()
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.get("/api/tasks/token-usage?days=30")

    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "dashboard-launched-tasks"
    assert data["totals"]["launched_tasks"] == 2
    assert data["totals"]["total_tokens"] == 140
    assert data["totals"]["unknown_task_count"] == 1
    assert data["latest_task"]["id"]
    payload = json.dumps(data)
    assert "Private-ish title" not in payload
    assert "Safe summary" not in payload
    assert "thread-private" not in payload


def test_create_schedule_computes_next_run(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.post(
        "/api/schedules",
        json={
            "name": "Daily repo check",
            "cron_expression": "@daily",
            "task_title": "Review public files",
            "task_description": "Summarize safe public project files only.",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    schedule_id = response.json()["schedule_id"]
    assert response.json()["next_run_at"]
    schedules = client.get("/api/schedules").json()["items"]
    assert schedules[0]["next_run_at"] == response.json()["next_run_at"]
    assert schedules[0]["materialized_count"] == 0

    disabled = client.post(f"/api/schedules/{schedule_id}/toggle", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["next_run_at"] is None
    assert client.get("/api/schedules").json()["items"][0]["enabled"] == 0

    enabled = client.post(f"/api/schedules/{schedule_id}/toggle", json={"enabled": True})
    assert enabled.status_code == 200
    assert enabled.json()["next_run_at"]

    deleted = client.post(f"/api/schedules/{schedule_id}/delete")
    assert deleted.status_code == 200
    assert client.get("/api/schedules").json()["items"] == []


def test_schedule_rejects_invalid_cron(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.post(
        "/api/schedules",
        json={
            "name": "Bad cron",
            "cron_expression": "sometimes",
            "task_title": "Nope",
            "task_description": "Safe text.",
            "enabled": True,
        },
    )

    assert response.status_code == 400


def test_materialize_due_schedule_creates_approval_gated_task(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    app_module.conn.execute(
        """
        INSERT INTO ops_schedules(
          name, cron_expression, task_title, task_description, enabled,
          next_run_at, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?)
        """,
        (
            "Due schedule",
            "@daily",
            "Scheduled safe task",
            "Inspect public-safe files only.",
            "2000-01-01T00:00:00+00:00",
            "2000-01-01T00:00:00+00:00",
            "2000-01-01T00:00:00+00:00",
        ),
    )
    app_module.conn.commit()
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.post("/api/schedules/materialize-due")

    assert response.status_code == 200
    data = response.json()
    assert data["created"] == 1
    task = client.get("/api/tasks").json()["items"][0]
    assert task["status"] == "awaiting_approval"
    assert task["sandbox"] == "read-only"
    assert task["scheduled_for"] == "2000-01-01T00:00:00+00:00"
    schedule = client.get("/api/schedules").json()["items"][0]
    assert schedule["materialized_count"] == 1
    assert schedule["last_task_id"] == task["id"]


def test_token_saver_blocks_schedule_materialization(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})
    client.post("/api/system-mode", json={"mode": "token_saver"})
    app_module.conn.execute(
        """
        INSERT INTO ops_schedules(
          name, cron_expression, task_title, task_description, enabled,
          next_run_at, created_at, updated_at
        ) VALUES (
          'Due schedule', '@daily', 'Safe scheduled task', 'Inspect public-safe files only.', 1,
          '2000-01-01T00:00:00+00:00', '1999-12-31T00:00:00+00:00', '1999-12-31T00:00:00+00:00'
        )
        """
    )
    app_module.conn.commit()

    response = client.post("/api/schedules/materialize-due")

    assert response.status_code == 409
    assert "Token Saver" in response.text
    assert client.get("/api/tasks").json()["items"] == []


def test_usage_limits_endpoint_returns_latest_local_metadata(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    app_module.conn.execute(
        """
        INSERT INTO usage_limits(
          id, limit_id, plan_type,
          primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
          secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
          rate_limit_reached_type, source_session_id, observed_at, synced_at
        ) VALUES (
          1, 'codex', 'example',
          55, 45, 300, 1780486936,
          25, 75, 10080, 1780859825,
          NULL, 'demo-session-0001', '2026-06-03T12:00:04+00:00', '2026-06-03T12:00:05+00:00'
        )
        """
    )
    app_module.conn.commit()
    client = TestClient(app_module.app)

    response = client.get("/api/usage/limits")
    assert response.status_code == 200
    data = response.json()
    assert data["available"] is True
    assert data["source"] == "local-session-rate-limits"
    assert data["limit"]["primary_remaining_percent"] == 45
    assert data["limit"]["secondary_remaining_percent"] == 75
    assert "insights" in data


def test_usage_limits_endpoint_returns_local_insights(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    now = datetime.now(tz=timezone.utc)
    observed = [now - timedelta(days=2), now - timedelta(days=1), now]
    primary_reset = int((now + timedelta(hours=3)).timestamp())
    secondary_reset = int((now + timedelta(days=4)).timestamp())
    app_module.conn.execute(
        """
        INSERT INTO usage_limits(
          id, limit_id, plan_type,
          primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
          secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
          rate_limit_reached_type, source_session_id, observed_at, synced_at
        ) VALUES (
          1, 'codex', 'example',
          55, 45, 300, ?,
          30, 70, 10080, ?,
          'primary', 'demo-session-0001', ?, ?
        )
        """,
        (primary_reset, secondary_reset, observed[-1].isoformat(), observed[-1].isoformat()),
    )
    for index, (stamp, primary_remaining, secondary_remaining, hit_type) in enumerate(
        [
            (observed[0], 70, 80, None),
            (observed[1], 55, 75, None),
            (observed[2], 45, 70, "primary"),
        ],
        start=1,
    ):
        app_module.conn.execute(
            """
            INSERT INTO usage_limit_observations(
              dedupe_key, plan_type,
              primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
              secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
              rate_limit_reached_type, observed_at, synced_at
            ) VALUES (?, 'example', ?, ?, 300, ?, ?, ?, 10080, ?, ?, ?, ?)
            """,
            (
                f"usage-{index}",
                100 - primary_remaining,
                primary_remaining,
                primary_reset,
                100 - secondary_remaining,
                secondary_remaining,
                secondary_reset,
                hit_type,
                stamp.isoformat(),
                stamp.isoformat(),
            ),
        )
    app_module.conn.commit()
    client = TestClient(app_module.app)

    response = client.get("/api/usage/limits")

    assert response.status_code == 200
    data = response.json()
    insights = data["insights"]
    assert insights["freshness_quality"] == "fresh"
    assert insights["task_advice"] == "normal"
    assert insights["trend_direction"] == "falling"
    assert insights["observation_count"] == 3
    assert insights["burn_rate"]["primary"]["available"] is True
    assert insights["burn_rate"]["primary"]["percent_spent"] == 25
    assert insights["burn_rate"]["secondary"]["available"] is True
    assert insights["limit_hits"][0]["rate_limit_reached_type"] == "primary"
    assert "source_session_id" not in json.dumps(insights)
    assert "demo-session-0001" not in json.dumps(insights)


def test_usage_burn_rate_ignores_reset_boundaries(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    now = datetime.now(tz=timezone.utc)
    current_reset = int((now + timedelta(hours=3)).timestamp())
    old_reset = int((now - timedelta(hours=1)).timestamp())
    app_module.conn.execute(
        """
        INSERT INTO usage_limits(
          id, limit_id, plan_type,
          primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
          secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
          rate_limit_reached_type, source_session_id, observed_at, synced_at
        ) VALUES (
          1, 'codex', 'example',
          5, 95, 300, ?,
          20, 80, 10080, 999,
          NULL, 'demo-session-0001', ?, ?
        )
        """,
        (current_reset, now.isoformat(), now.isoformat()),
    )
    app_module.conn.execute(
        """
        INSERT INTO usage_limit_observations(
          dedupe_key, plan_type,
          primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
          secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
          rate_limit_reached_type, observed_at, synced_at
        ) VALUES ('old-window', 'example', 80, 20, 300, ?, 20, 80, 10080, 999, NULL, ?, ?)
        """,
        (old_reset, (now - timedelta(hours=2)).isoformat(), (now - timedelta(hours=2)).isoformat()),
    )
    app_module.conn.commit()
    client = TestClient(app_module.app)

    response = client.get("/api/usage/limits")

    assert response.status_code == 200
    data = response.json()
    assert data["insights"]["burn_rate"]["primary"]["available"] is False
    assert data["insights"]["burn_rate"]["primary"]["reason"] == "not_enough_local_history"


def test_usage_observations_pruned_on_sync(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    old_stamp = (datetime.now(tz=timezone.utc) - timedelta(days=31)).isoformat()
    app_module.conn.execute(
        """
        INSERT INTO usage_limit_observations(
          dedupe_key, plan_type,
          primary_used_percent, primary_remaining_percent, primary_window_minutes, primary_resets_at,
          secondary_used_percent, secondary_remaining_percent, secondary_window_minutes, secondary_resets_at,
          rate_limit_reached_type, observed_at, synced_at
        ) VALUES ('old-observation', 'example', 50, 50, 300, 1, 20, 80, 10080, 2, NULL, ?, ?)
        """,
        (old_stamp, old_stamp),
    )
    app_module.conn.commit()
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    response = client.post("/api/sync")

    assert response.status_code == 200
    remaining = app_module.conn.execute("SELECT COUNT(*) FROM usage_limit_observations").fetchone()[0]
    assert remaining == 0


def test_skills_list_hides_full_paths_and_reveal_returns_on_demand(monkeypatch, tmp_path) -> None:
    app_module = load_test_app(monkeypatch, tmp_path)
    skill_file = tmp_path / "demo-skill" / "SKILL.md"
    skill_file.parent.mkdir()
    skill_file.write_text("---\nname: Demo Skill\ndescription: Public safe fixture\n---\n", encoding="utf-8")
    app_module.conn.execute("DELETE FROM skills")
    app_module.conn.execute(
        """
        INSERT INTO skills(
          name, scope, description, path_label, skill_path, plugin_name,
          enabled, last_modified, synced_at
        ) VALUES (?, ?, ?, ?, ?, NULL, 1, ?, ?)
        """,
        (
            "Demo Skill",
            "user-codex",
            "Public safe fixture",
            "user-codex/demo-skill#abc123",
            str(skill_file),
            "2026-06-03T12:00:00+00:00",
            "2026-06-03T12:00:00+00:00",
        ),
    )
    app_module.conn.commit()
    client = TestClient(app_module.app, headers={"x-control-token": "test-control-token"})

    listed = client.get("/api/skills")

    assert listed.status_code == 200
    payload_text = listed.text
    assert "skill_path" not in payload_text
    assert str(skill_file) not in payload_text
    assert str(skill_file).replace("\\", "\\\\") not in payload_text
    skill = listed.json()["items"][0]
    assert "id" in skill
    assert "path" not in skill
    assert skill["path_label"] == "user-codex/demo-skill#abc123"

    revealed = client.get(f"/api/skills/{skill['id']}/path")

    assert revealed.status_code == 200
    revealed_data = revealed.json()
    assert revealed_data["id"] == skill["id"]
    assert revealed_data["path"] == str(skill_file)
    assert revealed_data["path_label"] == "user-codex/demo-skill#abc123"

    missing = client.get("/api/skills/999999/path")
    assert missing.status_code == 404
