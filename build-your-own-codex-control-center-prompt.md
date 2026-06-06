# Build Your Own Local AI Agent Control Center Prompt

Use this public-safe prompt in Codex to build a local dashboard inspired by
Codex Control Center.

It can also be adapted for Claude Code, Cursor, or other coding LLMs. Before
building with another tool, ask the assistant to adapt the CLI commands, local
session paths, event formats, and sandbox controls for that environment while
preserving the privacy rules below.

Safety note: review any generated code before running it. Do not give the
assistant private logs, credentials, raw prompts, account files, API keys,
production data, or private screenshots. Start with fake fixtures first.

---

Build a local-first AI agent control center inspired by Codex Control Center.

If you are running in Codex, use Codex-specific paths and commands. If you are
running in Claude Code, Cursor, or another coding LLM, adapt the implementation
to that tool's CLI, local session format, sandbox model, and metadata paths.
Keep the same local-first, metadata-only, approval-gated privacy model.

Requirements:

- No OpenAI API key is required for local observation.
- The dashboard itself must not call OpenAI.
- Observe Mode reads local Codex metadata from `~/.codex/sessions`.
- Control Mode launches approved tasks through `codex exec --json --ephemeral`.
- Never read or store `~/.codex/auth.json`.
- Store metadata only by default.
- Do not store prompt text, assistant output, raw command output, `.env`, tokens,
  or absolute local paths.
- Redact project paths to basename plus a stable local hash.
- Bind to `127.0.0.1`.
- Use Python, FastAPI, SQLite WAL, Vite, React, TypeScript, Tailwind,
  TanStack Router, React Query, and lucide icons.
- Tasks start as `awaiting_approval`.
- Default sandbox is `read-only`.
- Allow `workspace-write` only when explicitly selected.
- Block `danger-full-access` in v1.
- Emergency stop may kill only dashboard-launched child PIDs.
- Include fake fixtures and a public-safety checklist for GitHub sharing.

Public-sharing rules:

- Use fake demo data only.
- Do not include private project names, client names, account identifiers,
  local usernames, raw prompts, logs, databases, exports, or screenshots with
  private UI.
- Document which data is read, which data is stored, and which data is never
  touched.
- Add a scanner or checklist that flags secrets, local paths, databases, logs,
  and raw session files before publishing.

Deliver:

- A working local app.
- Public-safe docs.
- Fake test fixtures.
- Parser, API, and frontend tests.
- A clear README stating: "No API key required for local observation."
