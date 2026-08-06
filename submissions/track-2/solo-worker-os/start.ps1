# Solo Worker OS - Dev Launcher
# Called by start.bat - do not rename or move this file

$ErrorActionPreference = "Continue"

function ok($m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function info($m) { Write-Host "  [..] $m" -ForegroundColor Yellow }
function fail($m) { Write-Host "  [!!] $m" -ForegroundColor Red }
function dim($m)  { Write-Host "       $m" -ForegroundColor DarkGray }
function sep()    { Write-Host "  ------------------------------------------" -ForegroundColor DarkYellow }

function Pause-Exit($code) {
    Write-Host ""
    Read-Host "  Press Enter to exit"
    exit $code
}

try { $Host.UI.RawUI.WindowTitle = "Solo Worker OS" } catch {}

# Resolve script directory
$root = $PSScriptRoot
if (-not $root -or $root -eq "") {
    $root = Split-Path -Parent $MyInvocation.MyCommand.Path
}
if (-not $root -or $root -eq "") {
    $root = (Get-Location).Path
}

try {
    Set-Location $root
} catch {
    fail "Cannot set working directory: $root"
    Pause-Exit 1
}

# ── Banner ────────────────────────────────────────────────────
Clear-Host
Write-Host ""
Write-Host "  +------------------------------------------+" -ForegroundColor Yellow
Write-Host "  |   Solo Worker OS  -  Dev Launcher        |" -ForegroundColor Yellow
Write-Host "  +------------------------------------------+" -ForegroundColor Yellow
Write-Host ""
Write-Host "  Root: $root" -ForegroundColor DarkGray
Write-Host ""

# ── 1. Node.js ────────────────────────────────────────────────
$nodePath = ""
try {
    $nodePath = (Get-Command node -ErrorAction Stop).Source
    $nodeVer  = (& node --version 2>&1).ToString().Trim()
    ok "Node.js $nodeVer  ($nodePath)"
} catch {
    fail "Node.js not found in PATH."
    dim "Download: https://nodejs.org  (choose LTS, restart terminal after install)"
    Pause-Exit 1
}

try {
    $npmVer = (& npm --version 2>&1).ToString().Trim()
    ok "npm v$npmVer"
} catch {
    fail "npm not found. Reinstall Node.js."
    Pause-Exit 1
}

# ── 2. .env.local ─────────────────────────────────────────────
Write-Host ""
$envFile    = Join-Path $root ".env.local"
$envExample = Join-Path $root ".env.example"

if (-not (Test-Path $envFile)) {
    info ".env.local not found - creating from .env.example..."

    if (Test-Path $envExample) {
        Copy-Item $envExample $envFile -Force
        ok "Created .env.local"
    } else {
        fail ".env.example not found either. Cannot create .env.local."
        dim "Create $envFile manually and fill in your API keys."
        Pause-Exit 1
    }

    Write-Host ""
    Write-Host "  Required keys in .env.local:" -ForegroundColor White
    dim "  ANTHROPIC_API_KEY            = sk-ant-..."
    dim "  NEXT_PUBLIC_SUPABASE_URL     = https://xxx.supabase.co"
    dim "  NEXT_PUBLIC_SUPABASE_ANON_KEY"
    dim "  SUPABASE_SERVICE_ROLE_KEY"
    Write-Host ""

    try { Start-Process $envFile } catch {}

    Read-Host "  Edit .env.local then press Enter to continue"
    Write-Host ""
} else {
    ok ".env.local found"

    # Check for unedited placeholder values
    try {
        $raw = Get-Content $envFile -Raw -ErrorAction SilentlyContinue
        if ($raw -match "sk-ant-xxxxxxxx|YOUR-PROJECT|your-anon-key|your-service-role") {
            Write-Host ""
            info ".env.local still has placeholder values!"
            dim "Open .env.local and replace with real keys."
            $ans = Read-Host "  Continue anyway? [y/N]"
            if ($ans -notin @("y","Y")) {
                try { Start-Process $envFile } catch {}
                Pause-Exit 0
            }
        }
    } catch {}
}

# ── 3. node_modules ───────────────────────────────────────────
$nmDir = Join-Path $root "node_modules"
if (-not (Test-Path $nmDir)) {
    Write-Host ""
    info "Installing dependencies (first run only)..."
    Write-Host ""

    & cmd /c "npm install"
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        fail "npm install failed (exit code $LASTEXITCODE)."
        dim "Try running: npm install  manually in this folder."
        Pause-Exit 1
    }

    Write-Host ""
    ok "Dependencies installed"
} else {
    ok "node_modules ready"
}

# ── 4. Clear stale .next cache ────────────────────────────────
$nextDir = Join-Path $root ".next"
if (Test-Path $nextDir) {
    info "Clearing .next cache for clean start..."
    try {
        Remove-Item $nextDir -Recurse -Force -ErrorAction SilentlyContinue
        ok ".next cache cleared"
    } catch {
        dim "Could not clear .next — continuing anyway"
    }
}

# ── 5. Start server ───────────────────────────────────────────
Write-Host ""
sep
Write-Host "  Starting Next.js dev server..." -ForegroundColor White
Write-Host "  URL  : http://localhost:3000/dashboard" -ForegroundColor Yellow
Write-Host "  Stop : Ctrl + C" -ForegroundColor DarkGray
sep
Write-Host ""

# Open browser 5 s after server starts (background)
$launchUrl = "http://localhost:3000/dashboard"
$null = Start-Job -ScriptBlock {
    param($u)
    # Poll port 3000 up to 120 seconds, then open browser
    $ready = $false
    for ($i = 0; $i -lt 120; $i++) {
        Start-Sleep -Seconds 1
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("127.0.0.1", 3000)
            $tcp.Close()
            $ready = $true
            break
        } catch {}
    }
    if ($ready) { Start-Process $u }
} -ArgumentList $launchUrl

# Foreground - blocks until Ctrl+C
& cmd /c "npm run dev"
