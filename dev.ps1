# ── Wishlist development launcher ─────────────────────────────────────────────
# Usage (see docs/DEVELOPMENT.md):
#   .\dev.ps1                      — Postgres, migrations, then the API (:8000,
#                                    reload) and the Flutter web client (:5500)
#                                    in a new Windows Terminal tab
#   .\dev.ps1 -Test                — Postgres, then the server tests against
#                                    the wishlist_test database
#   .\dev.ps1 -Reset               — drop the dev database volume (asks first),
#                                    then start as above; combine with -Test
#   .\dev.ps1 -Reset -Confirm:$false — the same without the prompt
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param([switch]$Test, [switch]$Reset)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$composeFile = Join-Path $root 'docker-compose.dev.yml'

function Invoke-Native([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $What failed (exit code $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

# ── Settings from .env (single source of truth; see .env.example) ─────────────
. (Join-Path $root 'Load-DotEnv.ps1')
if (-not (Import-DotEnv)) { exit 1 }

# ── Reset: drop the volume; the next `up` boots Postgres on an empty one ──────
if ($Reset) {
    if (-not $PSCmdlet.ShouldProcess('volume wishlist-dev_pgdata (all dev and test data)', 'Delete')) {
        Write-Host 'Reset cancelled.'
        exit 1
    }
    Invoke-Native 'docker compose down' { docker compose -f $composeFile down --volumes }
}

# ── Postgres: --wait returns once the healthcheck passes ──────────────────────
Write-Host 'Starting Postgres...' -ForegroundColor Cyan
Invoke-Native 'docker compose up' { docker compose -f $composeFile up -d --wait }

# ── Tests: the same DATABASE_URL variable the app reads, pointed at the test DB
if ($Test) {
    if (-not $env:TEST_DATABASE_URL) {
        Write-Host 'ERROR: TEST_DATABASE_URL missing from .env.' -ForegroundColor Red
        exit 1
    }
    $env:DATABASE_URL = $env:TEST_DATABASE_URL
    Write-Host 'Running server tests against TEST_DATABASE_URL...' -ForegroundColor Cyan
    uv run --directory (Join-Path $root 'server') pytest
    exit $LASTEXITCODE
}

# ── Migrations on the dev database ────────────────────────────────────────────
Write-Host 'Migrating the dev database...' -ForegroundColor Cyan
Invoke-Native 'alembic upgrade head' { uv run --directory (Join-Path $root 'server') alembic upgrade head }

# ── API and client ────────────────────────────────────────────────────────────
# The client's port is fixed: FRONTEND_ORIGIN (CORS) must name it (review R1-3).
# A busy port is reported, not freed: it may be another project's dev server.
foreach ($port in 8000, 5500) {
    $listener = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($listener) {
        $name = (Get-Process -Id $listener.OwningProcess -ErrorAction SilentlyContinue).ProcessName
        Write-Host "ERROR: port $port is already in use by $name (PID $($listener.OwningProcess)). Stop it and retry." -ForegroundColor Red
        exit 1
    }
}

$flutter = (Get-Command flutter -ErrorAction SilentlyContinue).Source
if (-not $flutter) {
    Write-Host 'ERROR: flutter not found on PATH.' -ForegroundColor Red
    exit 1
}
if (-not (Get-Command wt -ErrorAction SilentlyContinue)) {
    Write-Host 'ERROR: Windows Terminal (wt) not found.' -ForegroundColor Red
    exit 1
}

# Each pane loads .env itself: wt may open the tab in an already running
# Windows Terminal, which does not inherit this shell's environment, and the
# settings then never appear on a command line. For the same reason each pane
# gets this shell's PATH: on the owner's machine wt started the panes with a
# PATH missing System32, Git and uv.
$pathLiteral = $env:Path -replace "'", "''"
$loadEnv = "`$env:Path = '$pathLiteral'; . '$root\Load-DotEnv.ps1'; if (-not (Import-DotEnv)) { return }"
$apiCmd = "Set-Location '$root\server'; $loadEnv; uv run uvicorn app.main:app --reload --port 8000"
$clientCmd = "Set-Location '$root\client'; $loadEnv; & '$flutter' run -d chrome --web-port 5500 --dart-define=API_BASE_URL=http://localhost:8000"

# Base64 so wt's argument parsing cannot mangle quotes or semicolons.
function ConvertTo-Base64Command([string]$cmd) {
    [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($cmd))
}

# The panes run the same PowerShell as this script, by full path: wt launched
# a bare `pwsh` with "The system cannot find the file specified" on the owner's
# machine.
$pwsh = (Get-Process -Id $PID).Path

# Start-Process joins these with spaces and quotes nothing: a value containing
# a space (the titles, a path) needs its own quotes, or wt reads its second
# word as the command to run.
Start-Process wt -ArgumentList @(
    'new-tab', '--title', '"Wishlist API"', '-d', "`"$root`"",
    "`"$pwsh`"", '-NoExit', '-EncodedCommand', (ConvertTo-Base64Command $apiCmd),
    ';',
    'split-pane', '-H', '--title', '"Wishlist client"', '-d', "`"$root`"",
    "`"$pwsh`"", '-NoExit', '-EncodedCommand', (ConvertTo-Base64Command $clientCmd)
)

Write-Host ''
Write-Host 'API:     http://localhost:8000 (health: /api/health)'
Write-Host 'Client:  http://localhost:5500'
Write-Host 'Stop:    q in the client pane, Ctrl+C in the API pane.'
Write-Host '         Postgres keeps running: docker compose -f docker-compose.dev.yml stop'
