param(
  [Parameter(Position = 0)]
  [ValidateSet("start", "doctor", "sync", "build-ui")]
  [string]$Command = "start"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

switch ($Command) {
  "start" {
    Set-Location $Root
    python -m backend
  }
  "doctor" {
    Set-Location $Root
    python scripts/public_safety_scan.py .
    codex --version
    codex login status
  }
  "sync" {
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8765/api/sync"
  }
  "build-ui" {
    Set-Location (Join-Path $Root "ui")
    npm install
    npm run build
  }
}
