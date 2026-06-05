param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8765,
    [switch]$Install,
    [switch]$Rebuild,
    [switch]$SkipBuild,
    [switch]$NoBrowser,
    [switch]$Foreground,
    [switch]$StopExisting
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host "[codex-control-center] $Message"
}

function Test-Command {
    param([string]$Name)
    return $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-Health {
    param([string]$Url)
    try {
        $health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 2
        return $health.ok -eq $true
    } catch {
        return $false
    }
}

function Import-LocalEnv {
    param([string]$EnvPath)
    if (-not (Test-Path -LiteralPath $EnvPath)) {
        return
    }
    Write-Step "Loading local .env values without printing them."
    foreach ($line in Get-Content -LiteralPath $EnvPath) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
            continue
        }
        $name, $value = $trimmed.Split("=", 2)
        $name = $name.Trim()
        $value = $value.Trim().Trim('"').Trim("'")
        if ($name -match "^[A-Za-z_][A-Za-z0-9_]*$") {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Wait-ForHealth {
    param(
        [string]$Url,
        [int]$Seconds = 30
    )
    $deadline = (Get-Date).AddSeconds($Seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Health -Url $Url) {
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$Url = "http://${HostAddress}:${Port}"
$LogDir = Join-Path $ProjectRoot "logs"
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$UiDir = Join-Path $ProjectRoot "ui"
$UiDist = Join-Path $UiDir "dist\index.html"

Import-LocalEnv -EnvPath (Join-Path $ProjectRoot ".env")

$env:CCC_HOST = $HostAddress
$env:CCC_PORT = [string]$Port

if (Test-Health -Url $Url) {
    Write-Step "Dashboard is already running at $Url"
    if (-not $NoBrowser) {
        Start-Process $Url | Out-Null
    }
    exit 0
}

$listener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($listener) {
    if (-not $StopExisting) {
        Write-Error "Port $Port is already in use by process $($listener.OwningProcess). Re-run with -StopExisting only if that process is safe to stop."
    }
    Write-Step "Stopping existing listener on port $Port."
    Stop-Process -Id $listener.OwningProcess -Force -ErrorAction Stop
    Start-Sleep -Milliseconds 700
}

if (-not (Test-Command "python")) {
    Write-Error "Python was not found on PATH. Install Python 3.11+ and try again."
}

$CreatedVenv = $false
if (-not (Test-Path -LiteralPath $VenvPython)) {
    Write-Step "Creating Python virtual environment."
    python -m venv $VenvDir
    $CreatedVenv = $true
}

if ($Install -or $CreatedVenv) {
    Write-Step "Installing Python dependencies."
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
} else {
    $checkOut = Join-Path $env:TEMP "codex-control-center-deps-$PID.out"
    $checkErr = Join-Path $env:TEMP "codex-control-center-deps-$PID.err"
    $check = Start-Process -FilePath $VenvPython `
        -ArgumentList @("-c", "import fastapi, uvicorn, pydantic") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru `
        -RedirectStandardOutput $checkOut `
        -RedirectStandardError $checkErr
    Remove-Item -LiteralPath $checkOut, $checkErr -Force -ErrorAction SilentlyContinue
    if ($check.ExitCode -ne 0) {
        Write-Step "Python dependencies missing; installing requirements."
        & $VenvPython -m pip install -r (Join-Path $ProjectRoot "requirements.txt")
    }
}

if (-not $SkipBuild) {
    if (-not (Test-Command "npm")) {
        Write-Error "npm was not found on PATH. Install Node.js LTS and try again, or run with -SkipBuild if ui/dist already exists."
    }
    if ($Install -or -not (Test-Path -LiteralPath (Join-Path $UiDir "node_modules"))) {
        Write-Step "Installing frontend dependencies."
        Push-Location -LiteralPath $UiDir
        npm install
        Pop-Location
    }
    if ($Rebuild -or -not (Test-Path -LiteralPath $UiDist)) {
        Write-Step "Building frontend."
        Push-Location -LiteralPath $UiDir
        npm run build
        Pop-Location
    }
}

if (-not (Test-Path -LiteralPath $UiDist)) {
    Write-Error "Frontend build was not found at ui\dist\index.html. Re-run without -SkipBuild."
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

Write-Step "Starting backend at $Url"
if ($Foreground) {
    if (-not $NoBrowser) {
        Start-Process $Url | Out-Null
    }
    & $VenvPython -m backend
    exit $LASTEXITCODE
}

$outLog = Join-Path $LogDir "server.out.log"
$errLog = Join-Path $LogDir "server.err.log"
$process = Start-Process -FilePath $VenvPython `
    -ArgumentList @("-m", "backend") `
    -WorkingDirectory $ProjectRoot `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $outLog `
    -RedirectStandardError $errLog

if (-not (Wait-ForHealth -Url $Url -Seconds 30)) {
    Write-Host ""
    Write-Host "Backend did not become healthy. Recent error log:"
    if (Test-Path -LiteralPath $errLog) {
        Get-Content -Tail 40 -LiteralPath $errLog
    }
    Write-Error "Startup failed."
}

Write-Step "Ready at $Url (pid $($process.Id)). Logs are in $LogDir."
if (-not $NoBrowser) {
    Start-Process $Url | Out-Null
}
