# Safe Task Templates

Codex Control Center includes starter tasks for people who are not sure what to
write in the queue form. These templates are public-safe examples only. They do
not contain private paths, secrets, account data, raw prompts, or logs.

## Task Flow

1. Choose a workspace.
2. Pick a safe starter task or write your own task.
3. Keep the sandbox on `read-only` unless the task must edit files.
4. Queue the task for approval.
5. Review the queued task before approving it.
6. Read the result summary on the task board or Results page.

Schedules follow the same safety model: they create approval-gated tasks, but
they do not auto-run Codex.

## Built-In Starters

### Full safe workspace audit

Inspect the selected workspace in read-only mode and produce a full safe audit.
Cover workspace purpose and main structure, public documentation quality,
setup/build/test hints, security and publishing risks based on safe metadata,
missing README, docs, `.gitignore`, `AGENTS.md`, or safety notes, generated
folders that should stay ignored, and suggested next safe tasks. Do not edit
files. Do not read auth files, `.env` files, databases, raw logs, raw prompts,
private session files, or secrets. Do not include full local paths. Use file or
folder names only when safe.

### Summarize public files

Inspect the selected workspace in read-only mode and summarize the public-safe
files. Focus on README, docs, configuration examples, and source structure. Do
not read auth files, `.env` files, databases, logs, raw prompts, or secrets. Do
not edit files.

### Inspect repository structure

Inspect the selected workspace in read-only mode and explain its folder
structure, main entry points, build/test commands, and likely ownership
boundaries. Do not include full local paths. Do not read secrets, raw logs, or
auth files. Do not edit files.

### Find documentation gaps

Review the selected workspace in read-only mode and identify missing or unclear
public documentation. Suggest safe improvements for setup, usage, testing, and
security notes. Do not expose private local paths, secrets, raw prompts, logs, or
account data. Do not edit files.

### Run read-only security review

Perform a read-only security review of the selected workspace. Look for risky
public files, accidental secret patterns, unsafe scripts, overbroad permissions,
and publishing risks. Report findings with file names only when safe. Do not
read auth files, databases, raw logs, or private prompt content. Do not edit
files.

## Writing Your Own Safe Task

A good task includes:

- Goal: what Codex should inspect or answer.
- Expected output: summary, findings, checklist, or recommendations.
- Boundaries: what Codex should not read, expose, or modify.

Avoid pasting secrets, tokens, private local paths, raw logs, prompt history,
database contents, or account data into the task details.
