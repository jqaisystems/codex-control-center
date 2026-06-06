# Practical Tutorial Storyboard

Target length: 3-4 minutes
Format: 16:9
Primary visuals: fake screenshots, terminal-style command cards, and safety
checklists
Branding: small JQAI Systems logo top-left throughout

| Time | Scene | Visual | On-screen text | Notes |
| --- | --- | --- | --- | --- |
| 0:00-0:18 | Intro | Title card | `Install, observe, queue safely` | Establish safety promise. |
| 0:18-0:46 | Clone repo | Command card | `git clone ...` | No real terminal capture. |
| 0:46-1:16 | Run launcher | Command card | `.\start-control-center.ps1` | Show local host only. |
| 1:16-1:49 | Safety model | Checklist panel | `Observe Mode does not call OpenAI` | Mention auth files are never read. |
| 1:49-2:24 | Dashboard | `dashboard.png` | `Health, usage, readiness, sessions` | Use fake/demo values. |
| 2:24-3:02 | Tasks | `tasks.png` | `Read-only first. Approval required.` | Emphasize selected workspace and sandbox. |
| 3:02-3:32 | Results + publish | `results.png` and safety wording | `Safe summaries, not raw logs` | No private task output. |
| 3:32-3:45 | Close | End card | `Local-first. Metadata-only. Approval-gated.` | Include public repo URL. |

## Acceptance Notes

- Commands match the README.
- Captions and narration contain no private paths.
- Rendered MP4 stays in `video-output/`.
