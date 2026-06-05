# Publication Checklist

Use this before publishing to GitHub.

## 1. Confirm Public-Only Files

Do not publish:

- `.env`
- `.venv/`
- `ui/node_modules/`
- `ui/dist/`
- `logs/`
- SQLite databases, WAL files, or SHM files
- raw Codex session files
- `~/.codex/auth.json`
- screenshots made from private local data

## 2. Run Verification

V1 has been tested on Windows 11. Run these checks from the Windows-first setup
before publishing.

```powershell
python -m pytest
cd ui
npm run build
cd ..
python scripts/public_safety_scan.py .
```

The public safety scanner must print `READY`.

## 3. Review Git State

```powershell
git status --short
git diff
```

Review every changed file before staging. Screenshots must be fake-data demo
screenshots only.

## 4. Stage Explicit Files Only

Use named paths rather than `git add .`.

Example:

```powershell
git add README.md ARCHITECTURE.md SECURITY.md PUBLICATION_CHECKLIST.md
git add start-control-center.ps1 requirements.txt pytest.ini LICENSE
git add backend scripts tests fixtures ui docs
```

## 5. Inspect Staged Diff

```powershell
git diff --cached
git status --short
```

Do not commit if staged files include private paths, logs, databases, raw
session files, `.env`, screenshots with private UI, or generated dependency
folders.

## 6. Commit Only After Human Review

Suggested first commit:

```powershell
git commit -m "Initial Codex Control Center"
```

Do not push until the GitHub target repository and visibility have been reviewed.
