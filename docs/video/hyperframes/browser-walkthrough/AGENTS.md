# Browser Walkthrough HyperFrames Project

This project renders the compact Codex Control Center browser walkthrough demo.

## Commands

```powershell
npm run lint
npm run validate
npm run inspect
npm run render
```

`npm run render` writes a draft MP4 to the ignored `video-output/` folder at
the repository root.

## Safety

- Use screenshots captured only from the temporary demo database and fake Codex
  home.
- Keep the JQAI Systems logo small in the top-left corner.
- Do not show private browser chrome, account menus, profile data, full local
  paths, raw prompts, raw logs, `.env` contents, auth files, or tokens.
- Do not reveal skill paths or health report full paths in the video.
- This project does not publish, upload, commit, stage, or push anything.
