from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS sessions (
          session_id TEXT PRIMARY KEY,
          relative_path TEXT,
          source TEXT,
          model TEXT,
          project_label TEXT,
          project_hash TEXT,
          started_at TEXT,
          updated_at TEXT,
          status TEXT,
          event_count INTEGER DEFAULT 0,
          tool_count INTEGER DEFAULT 0,
          input_tokens INTEGER DEFAULT 0,
          cached_input_tokens INTEGER DEFAULT 0,
          output_tokens INTEGER DEFAULT 0,
          reasoning_output_tokens INTEGER DEFAULT 0,
          total_tokens INTEGER DEFAULT 0,
          last_synced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tool_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          session_id TEXT NOT NULL,
          call_id TEXT,
          tool_name TEXT,
          started_at TEXT,
          completed_at TEXT,
          duration_ms INTEGER,
          success INTEGER,
          FOREIGN KEY(session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS usage_limits (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          limit_id TEXT,
          plan_type TEXT,
          primary_used_percent REAL,
          primary_remaining_percent REAL,
          primary_window_minutes INTEGER,
          primary_resets_at INTEGER,
          secondary_used_percent REAL,
          secondary_remaining_percent REAL,
          secondary_window_minutes INTEGER,
          secondary_resets_at INTEGER,
          rate_limit_reached_type TEXT,
          source_session_id TEXT,
          observed_at TEXT,
          synced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS usage_limit_observations (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          dedupe_key TEXT NOT NULL UNIQUE,
          plan_type TEXT,
          primary_used_percent REAL,
          primary_remaining_percent REAL,
          primary_window_minutes INTEGER,
          primary_resets_at INTEGER,
          secondary_used_percent REAL,
          secondary_remaining_percent REAL,
          secondary_window_minutes INTEGER,
          secondary_resets_at INTEGER,
          rate_limit_reached_type TEXT,
          observed_at TEXT NOT NULL,
          synced_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS otel_events (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_name TEXT,
          session_id TEXT,
          model TEXT,
          tool_name TEXT,
          tool_success INTEGER,
          duration_ms INTEGER,
          input_tokens INTEGER DEFAULT 0,
          output_tokens INTEGER DEFAULT 0,
          timestamp TEXT,
          received_at TEXT NOT NULL,
          attributes_json TEXT
        );

        CREATE TABLE IF NOT EXISTS otel_metrics (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          metric_name TEXT NOT NULL,
          metric_type TEXT,
          value REAL,
          timestamp TEXT,
          received_at TEXT NOT NULL,
          attributes_json TEXT
        );

        CREATE TABLE IF NOT EXISTS skills (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          scope TEXT NOT NULL,
          description TEXT,
          path_label TEXT,
          skill_path TEXT,
          plugin_name TEXT,
          enabled INTEGER DEFAULT 1,
          last_modified TEXT,
          synced_at TEXT NOT NULL,
          UNIQUE(name, scope, path_label)
        );

        CREATE TABLE IF NOT EXISTS workspaces (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          root_path TEXT NOT NULL UNIQUE,
          path_label TEXT NOT NULL,
          path_hash TEXT NOT NULL UNIQUE,
          is_default INTEGER DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ops_tasks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          title TEXT NOT NULL,
          description TEXT NOT NULL,
          status TEXT NOT NULL,
          priority INTEGER DEFAULT 3,
          sandbox TEXT NOT NULL DEFAULT 'read-only',
          workspace_id INTEGER,
          cwd_label TEXT,
          cwd_hash TEXT,
          scheduled_for TEXT,
          approved_at TEXT,
          started_at TEXT,
          completed_at TEXT,
          duration_ms INTEGER,
          exit_code INTEGER,
          event_count INTEGER DEFAULT 0,
          tool_count INTEGER DEFAULT 0,
          input_tokens INTEGER,
          cached_input_tokens INTEGER,
          output_tokens INTEGER,
          reasoning_output_tokens INTEGER,
          total_tokens INTEGER,
          thread_id TEXT,
          failure_reason TEXT,
          archived INTEGER DEFAULT 0,
          output_summary TEXT,
          error_message TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS task_processes (
          task_id INTEGER PRIMARY KEY,
          pid INTEGER NOT NULL,
          started_at TEXT NOT NULL,
          FOREIGN KEY(task_id) REFERENCES ops_tasks(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS ops_schedules (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL,
          cron_expression TEXT NOT NULL,
          task_title TEXT NOT NULL,
          task_description TEXT NOT NULL,
          enabled INTEGER DEFAULT 1,
          next_run_at TEXT,
          last_run_at TEXT,
          last_task_id INTEGER,
          materialized_count INTEGER DEFAULT 0,
          workspace_id INTEGER,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE SET NULL,
          FOREIGN KEY(last_task_id) REFERENCES ops_tasks(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS activities (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          event_type TEXT NOT NULL,
          detail TEXT,
          metadata_json TEXT,
          created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS health_report_reviews (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          workspace_id INTEGER NOT NULL,
          review_key TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'needs_action',
          note TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(workspace_id, review_key),
          FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS system_state (
          key TEXT PRIMARY KEY,
          value TEXT,
          updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_updated ON sessions(updated_at);
        CREATE INDEX IF NOT EXISTS idx_tool_events_session ON tool_events(session_id);
        CREATE INDEX IF NOT EXISTS idx_usage_observations_observed ON usage_limit_observations(observed_at);
        CREATE INDEX IF NOT EXISTS idx_otel_events_received ON otel_events(received_at);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON ops_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_workspaces_hash ON workspaces(path_hash);
        CREATE INDEX IF NOT EXISTS idx_health_reviews_workspace ON health_report_reviews(workspace_id);
        """
    )
    _migrate_add_column(conn, "ops_tasks", "workspace_id", "INTEGER")
    _migrate_add_column(conn, "ops_tasks", "thread_id", "TEXT")
    _migrate_add_column(conn, "ops_tasks", "failure_reason", "TEXT")
    _migrate_add_column(conn, "ops_tasks", "archived", "INTEGER DEFAULT 0")
    _migrate_add_column(conn, "ops_tasks", "input_tokens", "INTEGER")
    _migrate_add_column(conn, "ops_tasks", "cached_input_tokens", "INTEGER")
    _migrate_add_column(conn, "ops_tasks", "output_tokens", "INTEGER")
    _migrate_add_column(conn, "ops_tasks", "reasoning_output_tokens", "INTEGER")
    _migrate_add_column(conn, "ops_tasks", "total_tokens", "INTEGER")
    _migrate_add_column(conn, "ops_schedules", "last_task_id", "INTEGER")
    _migrate_add_column(conn, "ops_schedules", "materialized_count", "INTEGER DEFAULT 0")
    _migrate_add_column(conn, "ops_schedules", "workspace_id", "INTEGER")
    _migrate_add_column(conn, "skills", "skill_path", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_workspace ON ops_tasks(workspace_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_schedules_workspace ON ops_schedules(workspace_id)")
    conn.commit()


def _migrate_add_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def rows(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def row(conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    item = conn.execute(sql, params).fetchone()
    return dict(item) if item else None


def log_activity(conn: sqlite3.Connection, event_type: str, detail: str, metadata: dict[str, Any] | None = None) -> None:
    conn.execute(
        "INSERT INTO activities(event_type, detail, metadata_json, created_at) VALUES (?, ?, ?, datetime('now'))",
        (event_type, detail, json.dumps(metadata or {}, separators=(",", ":"))),
    )
    conn.commit()
