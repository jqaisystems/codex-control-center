# Security

## Boundary

Codex Control Center is local-first. It binds to `127.0.0.1` by default and does
not call OpenAI directly. Observe Mode works without an API key. Control Mode
delegates to your installed Codex CLI.

The backend never reads `~/.codex/auth.json`.

## Never Publish

- `~/.codex/auth.json`
- API keys, access tokens, cookies, or ChatGPT session values
- `.env`
- SQLite databases, WAL files, logs, or raw exports
- Raw Codex session files
- Prompt text or assistant output
- Screenshots with private UI, browser tabs, account menus, or local paths
- Absolute local paths or usernames

## Metadata-Only Defaults

The parser stores operational metadata only:

- timestamps
- model names
- event counts
- tool names and failure counts
- token counts where available
- usage-limit percentages and reset timestamps where Codex emits them
- redacted project labels

It deliberately avoids storing user messages, assistant messages, command output,
and raw `codex exec` streams.

## Usage Remaining

The Usage Remaining card uses best-effort local session metadata from
`token_count` events with `rate_limits`. It stores numeric percentages, reset
timestamps, plan label, source session ID, and observation time. It does not call
OpenAI, scrape the Codex app UI, or read auth files.

The Codex app's own Usage Remaining panel remains the source of truth.

## Task Safety

- New tasks require approval.
- Default sandbox is `read-only`.
- `workspace-write` must be chosen explicitly.
- `danger-full-access` is blocked in V1.
- Task descriptions with secret-like values or private paths are rejected.
- Output is reduced to redacted summaries and metadata.
- Emergency stop only targets dashboard-launched child PIDs.

## Schedule Safety

Schedules only create `awaiting_approval` tasks. They do not auto-run Codex and
do not bypass the task approval gate.

## Screenshot Safety

Public screenshots in `docs/screenshots/` must be made with fake demo data. Do
not capture private local sessions, account menus, browser chrome, local paths,
or raw task outputs.

## Reporting

If you find a security issue, contact the maintainer without posting secrets,
tokens, raw logs, screenshots with private UI, or private session data.
