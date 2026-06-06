# Browser Walkthrough Storyboard

Target: 90-120 seconds
Visual style: clean browser frame, dark technical UI, JQAI logo top-left
Primary visuals: screenshots captured from a temporary demo app instance

| Time | Scene | Visual | Caption | Safety notes |
| --- | --- | --- | --- | --- |
| 0:00-0:08 | Hook | Title card with clean browser frame outline | `A browser walkthrough of the safe local workflow` | No live data. |
| 0:08-0:25 | Dashboard | Demo Dashboard capture | `Dashboard: mode, usage, readiness, sessions` | Fake DB, fake Codex home. |
| 0:25-0:43 | Tasks | Demo Tasks capture with callouts | `Choose a workspace, start read-only` | Safe labels only. |
| 0:43-1:01 | Results | Demo Results capture | `Results: safe summaries and next actions` | No raw logs or prompts. |
| 1:01-1:18 | Vault Health Report | Demo Health Report capture | `Vault report: relative paths by default` | Do not click reveal paths. |
| 1:18-1:33 | Skills | Demo Skills capture | `Skills stay visible without exposing full paths` | Do not click reveal path. |
| 1:33-1:48 | Publish Readiness | Demo Publish capture | `Publish checks without publishing anything` | Show does-not-publish warning. |
| 1:48-1:52 | Close | Branded closing card | `Local-first. Metadata-only. Approval-gated.` | Public repo only. |

## Capture Setup

- Run the backend on `127.0.0.1:8766`.
- Use ignored temporary folders under `video-output/` for `CCC_HOME`,
  `CCC_DB_PATH`, `CODEX_HOME`, fake browser profile data, and fake workspace
  content.
- Use a fake `codex.cmd` on `PATH` so System Health never exposes a real Codex
  account or login status.
- Capture viewport screenshots only; the HyperFrames composition supplies the
  safe browser frame.
