# Video Production Kit

This folder contains public-safe scripts and storyboards for Codex Control
Center videos.

## Videos

- Website case study:
  [Codex Control Center](https://www.ai.joaoqueiros.com/systems/codex-control-center)
- Blog guide and build prompt:
  [Build Your Own Local AI Agent Control Center](https://www.ai.joaoqueiros.com/blog/build-your-own-local-ai-agent-control-center)
- Interactive demo:
  [GitHub Pages demo](https://jqaisystems.github.io/codex-control-center/demo/)
- Video hub:
  [Embedded video page](https://jqaisystems.github.io/codex-control-center/demo/videos.html)

- Hosted launch video:
  [Codex Control Center v0.1.0 - Official Launch](https://www.youtube.com/watch?v=idyHU9XNNSA)
- Hosted tutorial:
  [Codex Control Center Tutorial v0.1.0](https://www.youtube.com/watch?v=5BC9uaomqr0)
- Hosted browser walkthrough:
  [Codex Control Center: Full Browser Walkthrough v0.1.0](https://www.youtube.com/watch?v=_4W7F5A2NlE)

- `scripts/launch-presentation.md`: 45-60 second overview for GitHub, YouTube,
  LinkedIn, and release notes.
- `scripts/tutorial.md`: 3-4 minute practical install and safe-use tutorial.
- `scripts/browser-walkthrough.md`: 90-120 second browser navigation demo.
- `storyboards/launch-presentation.md`: visual plan for the overview video.
- `storyboards/tutorial.md`: visual plan for the tutorial video.
- `storyboards/browser-walkthrough.md`: visual plan for the browser demo.
- `hyperframes/launch-presentation/`: source project for the launch video.
- `hyperframes/practical-tutorial/`: source project for the tutorial video.
- `hyperframes/browser-walkthrough/`: source project for the browser demo.

## Safety Rules

- Use fake/demo screenshots only.
- Do not show private browser tabs, account menus, local vault contents, raw
  prompts, raw logs, databases, `.env` files, auth files, or tokens.
- Do not record a real private workspace. Use the existing fake screenshots in
  `docs/screenshots/` or a fresh demo workspace with fictional data.
- Browser walkthrough captures must use temporary demo `CCC_HOME`,
  `CCC_DB_PATH`, `CODEX_HOME`, and workspace folders under ignored
  `video-output/` paths.
- Do not include full local paths in captions, voiceover, or overlays.
- Keep rendered videos out of Git. Use `video-output/`, which is ignored.

## Visual Direction

- Format: 16:9, 1920x1080.
- Mood: calm, technical, local-first, safety-aware.
- Palette: dark ink background, muted panels, blue focus accents, white text.
- Motion: clean terminal-style reveals, subtle zooms, short highlights, no
  noisy effects.
- Primary assets: existing fake screenshots from `docs/screenshots/`.

## Output Notes

Suggested local output names:

- `video-output/codex-control-center-launch-v0.1.0.mp4`
- `video-output/codex-control-center-tutorial-v0.1.0.mp4`
- `video-output/codex-control-center-browser-walkthrough-v0.1.0.mp4`
- `video-output/codex-control-center-launch-v0.1.0-draft.mp4`
- `video-output/codex-control-center-tutorial-v0.1.0-draft.mp4`
- `video-output/codex-control-center-browser-walkthrough-v0.1.0-draft.mp4`

After upload, add public hosted links to the README or release notes only after
reviewing the final rendered videos.

## Public Link Block For Video Descriptions

Use this public-safe block in YouTube descriptions and release notes:

```text
Codex Control Center v0.1.0

Website case study:
https://www.ai.joaoqueiros.com/systems/codex-control-center

Blog guide and build prompt:
https://www.ai.joaoqueiros.com/blog/build-your-own-local-ai-agent-control-center

GitHub repository:
https://github.com/jqaisystems/codex-control-center

Interactive demo:
https://jqaisystems.github.io/codex-control-center/demo/

Video hub:
https://jqaisystems.github.io/codex-control-center/demo/videos.html

No API key required for local observation. The dashboard is local-first,
metadata-only by default, and uses approval-gated tasks for Control Mode.
```

## Rendering Drafts

From either HyperFrames project folder:

```powershell
npm run lint
npm run validate
npm run inspect
npm run render
```

Rendered drafts and generated voiceover audio are ignored by Git.
