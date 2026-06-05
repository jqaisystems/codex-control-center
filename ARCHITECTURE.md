# Architecture

Codex Control Center is a local-only dashboard with a FastAPI backend, SQLite
storage, and a React frontend. It is designed for local observation first and
approval-gated Codex CLI control second.

## Runtime Shape

- Backend: Python, FastAPI, SQLite WAL, raw SQL.
- Frontend: Vite, React, TypeScript, Tailwind, React Query, TanStack Router.
- Default bind: `127.0.0.1:8765`.
- App data: `~/.codex-control-center/` unless overridden by environment
  variables.
- Frontend build output: `ui/dist/`, served by the FastAPI app.

## Data Flow

1. Session sync scans local Codex session JSONL files under
   `~/.codex/sessions/YYYY/MM/DD/*.jsonl`.
2. The parser extracts metadata only: timestamps, models, event counts, tool
   names, token counts, safe project labels, and usage-limit percentages where
   available.
3. Optional Codex OTel can post local logs and metrics to `/v1/logs` and
   `/v1/metrics`.
4. Skill sync discovers local Codex skills and plugin-provided skills.
5. The frontend polls `/api/*` endpoints every 15-60 seconds.
6. Approved dashboard tasks launch through `codex exec --json --ephemeral`.
7. Task results are stored as metadata plus redacted summaries, not raw streams.

## Storage

Runtime data is stored in `~/.codex-control-center/control-center.sqlite` unless
`CCC_DB_PATH` is set.

Tables:

- `sessions`
- `tool_events`
- `usage_limits`
- `otel_events`
- `otel_metrics`
- `skills`
- `ops_tasks`
- `task_processes`
- `ops_schedules`
- `activities`
- `system_state`

## Frontend Routes

- `/`: dashboard, health, usage remaining, activity, security, context health.
- `/tasks`: approval-gated task queue and schedule management.
- `/results`: searchable run history and task-result metadata.
- `/skills`: skill and plugin registry.

## Control Mode

Tasks are always created as `awaiting_approval`. Approval starts a child
`codex exec --json --ephemeral` process with either `read-only` or
`workspace-write` sandbox. V1 does not allow `danger-full-access`.

Schedules never auto-run Codex. They only materialize due definitions into
`awaiting_approval` tasks. A human must still approve each task.

The emergency stop endpoint only targets PIDs recorded in `task_processes`, so
interactive Codex sessions are intentionally spared.

## Launcher

`start-control-center.ps1` is the Windows-first entry point and has been tested
on Windows 11. It checks for a running dashboard, creates `.venv` if needed,
installs missing Python dependencies, builds the frontend when needed, starts
the backend, waits for health, and opens the browser. macOS and Linux may work
through the manual setup flow, but they are not fully tested in V1.

## V2 Ideas

- Background schedule materialization that still creates approval-gated tasks
  only.
- Codex App Server integration for richer live steering.
- Optional local-only prompt/output search with explicit opt-in.
- Notification plugins.
