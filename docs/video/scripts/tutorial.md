# Practical Tutorial Script

Target length: 3-4 minutes
Format: 16:9
Style: compact walkthrough with generated draft voiceover and captions
Safety: fake/demo screenshots only, no private paths, no real account data

## Voiceover

### 0:00-0:18 - Introduction

Run Codex Control Center and use the safest first workflow: observe local Codex
metadata without needing an API key, then only launch Codex work through an
approval gate.

Caption: `Install, observe, queue safely`

### 0:18-0:46 - Clone the Repository

Start from the public repository. Clone it, enter the folder, and keep the demo
environment clean.

```powershell
git clone https://github.com/jqaisystems/codex-control-center.git
cd codex-control-center
```

Use command cards and fake screenshots so no private tabs, account menus, vault
contents, prompts, logs, or local paths appear on screen.

Caption: `Clone the public repo`

### 0:46-1:16 - Run the Windows Launcher

```powershell
.\start-control-center.ps1
```

The launcher prepares the local environment, installs missing dependencies,
builds the React interface when needed, starts the backend, waits for health,
and opens the browser.

Everything runs on `127.0.0.1:8765`.

Caption: `Runs locally on 127.0.0.1:8765`

### 1:16-1:49 - Understand the Safety Model

Observe Mode reads local metadata and does not call OpenAI. It can show
sessions, tool activity, usage signals, skills, readiness, and publish checks
without reading Codex auth files.

Control Mode uses your installed Codex CLI only after approval.

Caption: `Observe Mode does not call OpenAI`

### 1:49-2:24 - Read the Dashboard

System Mode gives Full, Balanced, and Token Saver options.

Usage Remaining is best-effort local metadata. Readiness Score explains setup
and workspace health using metadata-only checks. Recent Sessions are grouped by
week by default.

Caption: `Dashboard: health, usage, readiness, sessions`

### 2:24-3:02 - Queue a Safe Task

Open Tasks. Register only the folder you want Codex to inspect. The app stores
the real path locally, but the UI shows safe labels instead of full paths.

Choose a Safe Starter Task, keep the sandbox on read-only, queue it, and approve
only after reviewing the task.

Caption: `Read-only first. Approval required.`

### 3:02-3:32 - Review Results and Publish Readiness

After a task completes, open Results. Review the safe summary, duration, tool
count, category, and follow-up actions.

Before sharing, open Publish Readiness. It checks local safety status and does
not publish, commit, stage, push, upload, or contact GitHub.

Caption: `Safe summaries, not raw logs`

### 3:32-3:45 - Close

That is the safe first workflow: observe locally, choose one workspace, start
read-only, review results, and share only after the safety checks are ready.

Caption: `Local-first. Metadata-only. Approval-gated.`
