# Build Your Own Codex Control Center Prompt

Use this prompt in Codex to build a local dashboard similar to this project.

---

Build a local-first Codex Control Center.

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

Deliver:

- A working local app.
- Public-safe docs.
- Fake test fixtures.
- Parser, API, and frontend tests.
- A clear README stating: "No API key required for local observation."
