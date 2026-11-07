#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Deploy the image CI published to VAL or PROD on the VPS, then check that
    the environment really serves it.

.DESCRIPTION
    Nothing is built here: CI's "Build and publish Docker image" workflow
    publishes ghcr.io/rui-nar/wishlist (plan D6). This script only makes the
    VPS run it.

    -Target Val  -> /opt/wishlist-val, :validation, DEPLOY_VAL_URL.
                    The webhook usually does this by itself; this is the manual
                    way, e.g. after the webhook failed.
    -Target Prod -> /opt/wishlist, :latest, DEPLOY_PROD_URL. Asks for
                    confirmation first: the manual gate before PROD is
                    deliberate (plan D6).

    Steps:
      1. git fetch the tags, and work out the version the image must report
         (plan D11): the newest vX.Y.Z tag for Prod, validation-<sha of the
         `validation` tag> for Val.
      2. Over ONE SSH connection (a passphrase-protected key asks once):
         a. the host's compose file must run the image being deployed;
         b. docker compose pull;
         c. the pulled image's APP_VERSION must be the version from step 1;
            for Prod, a vX.Y.Z release and nothing else;
         d. docker compose up -d.
         It stops before (d), with the running containers untouched, when (a),
         (b) or (c) fails. No "docker compose down": the old containers keep
         serving during the pull, and up -d recreates only what changed.
      3. <url>/api/version must report that version within 120 s, then
         <url>/api/health must answer "ok" (database and media).

    -WhatIf prints the commands, including the script run on the host,
    without connecting to GitHub or the VPS. Without deploy.env it shows the
    missing settings as <KEY>.

    CONFIGURATION
    Host details live in deploy.env next to this script (gitignored). Copy
    deploy.env.example to deploy.env and fill it in.

.PREREQUISITES
    - deploy.env filled in.
    - OpenSSH (ssh on PATH) and key auth to DEPLOY_HOST as DEPLOY_USER.
    - Docker on the host logged in to GHCR, and docker-compose.yml plus .env
      in /opt/wishlist and /opt/wishlist-val.

.PARAMETER Target
    Val or Prod.

.EXAMPLE
    .\deploy.ps1 -Target Val

.EXAMPLE
    .\deploy.ps1 -Target Prod -WhatIf
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Val', 'Prod')]
    [string]$Target
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# The repository's image and the VPS layout, not host settings: plan D6, D7, D8.
$Image = 'ghcr.io/rui-nar/wishlist'
if ($Target -eq 'Prod') {
    $Dir = '/opt/wishlist'
    $ImageRef = "${Image}:latest"
    $UrlKey = 'DEPLOY_PROD_URL'
} else {
    $Dir = '/opt/wishlist-val'
    $ImageRef = "${Image}:validation"
    $UrlKey = 'DEPLOY_VAL_URL'
}
$VerifySeconds = 120

function Die([string]$msg) {
    Write-Host ''
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

function Step([string]$msg) {
    Write-Host ''
    Write-Host $msg -ForegroundColor Cyan
}

# ── Configuration ─────────────────────────────────────────────────────────────
# Read into a table, not $env:, so a stray variable in the calling shell can
# neither leak in nor stand in for a value missing from the file.
. (Join-Path $PSScriptRoot 'Load-DotEnv.ps1')
$ConfigFile = Join-Path $PSScriptRoot 'deploy.env'
$Config = [ordered]@{}
if (Test-Path $ConfigFile) {
    $Config = Read-DotEnv -Path $ConfigFile
} elseif (-not $WhatIfPreference) {
    Die "deploy.env not found at '$ConfigFile'. Copy deploy.env.example to deploy.env and fill it in."
}

$RequiredKeys = @('DEPLOY_HOST', 'DEPLOY_SSH_PORT', 'DEPLOY_USER', 'DEPLOY_SSH_KEY', $UrlKey)
$missing = @($RequiredKeys | Where-Object { -not $Config.Contains($_) })
if ($missing.Count -gt 0) {
    if (-not $WhatIfPreference) { Die "deploy.env is missing: $($missing -join ', '). See deploy.env.example." }
    foreach ($key in $missing) { $Config[$key] = "<$key>" }
    Write-Host "(WhatIf: not set in deploy.env, shown as <KEY>: $($missing -join ', '))" -ForegroundColor DarkYellow
}

$DeployHost = $Config['DEPLOY_HOST']
$SshPort = $Config['DEPLOY_SSH_PORT']
$DeployUser = $Config['DEPLOY_USER']
$SshKey = $Config['DEPLOY_SSH_KEY']
$Url = $Config[$UrlKey].TrimEnd('/')

if ($SshKey.StartsWith('~')) { $SshKey = $HOME + $SshKey.Substring(1) }
if (-not $WhatIfPreference) {
    if (-not (Test-Path $SshKey)) { Die "DEPLOY_SSH_KEY '$SshKey' does not exist." }
    if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) { Die 'ssh not found on PATH (Windows OpenSSH client).' }
}

# ── 1. The version the deploy must serve ──────────────────────────────────────
# --force: `validation` is a floating tag, and a moved one is otherwise
# rejected as "would clobber existing tag", leaving a stale local tag that
# would make the checks expect the wrong commit.
Step '[1/3] Fetching tags...'
if ($PSCmdlet.ShouldProcess('origin', 'git fetch --tags --force')) {
    git -C $PSScriptRoot fetch origin --tags --force | Out-Null
    if ($LASTEXITCODE -ne 0) { Die 'git fetch failed.' }
}

if ($Target -eq 'Prod') {
    # CI publishes :latest from the newest release tag only.
    $Release = @(git -C $PSScriptRoot tag --list 'v*' --sort=-v:refname |
            Where-Object { $_ -match '^v\d+\.\d+\.\d+$' }) | Select-Object -First 1
    if (-not $Release) {
        if (-not $WhatIfPreference) { Die 'No vX.Y.Z release tag found: PROD only runs releases.' }
        $Release = '<newest vX.Y.Z tag>'
    }
    $Expected = $Release
} else {
    $ValSha = git -C $PSScriptRoot rev-parse --verify --quiet 'refs/tags/validation^{commit}'
    if ($LASTEXITCODE -ne 0 -or -not $ValSha) {
        if (-not $WhatIfPreference) { Die 'No `validation` tag found: nothing has been published to :validation.' }
        $ValSha = '<sha of the validation tag>'
        $Expected = 'validation-<short sha>'
    } else {
        $ValSha = $ValSha.Trim()
        $Expected = "validation-$($ValSha.Substring(0, 7))"
    }
}

# True when /api/version (or the image's APP_VERSION) is the expected build.
# CI names VAL builds with `git rev-parse --short`, which gives 7 hex digits
# unless more are needed to stay unambiguous: any prefix of 7 or more matches.
function Test-ExpectedVersion([string]$reported) {
    if ($Target -eq 'Prod') { return $reported -ceq $Release }
    if ($reported -cmatch '^validation-([0-9a-f]{7,40})$') { return $ValSha.StartsWith($Matches[1]) }
    return $false
}

Write-Host ''
Write-Host '--------------------------------------------' -ForegroundColor Green
Write-Host "  Wishlist  -  deploy $Expected ($Target)" -ForegroundColor Green
Write-Host "  -> $ImageRef" -ForegroundColor Green
Write-Host "  -> ${DeployHost}:$Dir  ($Url)" -ForegroundColor Green
Write-Host '--------------------------------------------' -ForegroundColor Green

if ($Target -eq 'Prod' -and -not $WhatIfPreference) {
    $answer = Read-Host "Deploy $Release to PROD ($Url)? [y/N]"
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host 'Cancelled. Nothing was done.'
        exit 1
    }
}

# ── 2. Pull, check and start on the host ──────────────────────────────────────
# Runs on the host as bash. Values are inserted as tokens: every one is a
# constant above or was checked by a pattern, so none can break the quoting.
# Exit code 3 means it stopped before touching the running containers.
$RemoteScript = @'
set -euo pipefail
cd '__DIR__'
# The pull fetches whatever the HOST's compose file names, so a file naming
# another image would make every check below test the wrong thing.
images="$(docker compose config --images)" || exit 3
if ! grep -qxF '__IMAGE__' <<<"$images"; then
  echo "FAIL: __DIR__/docker-compose.yml does not run __IMAGE__ (it runs: ${images//$'\n'/ })" >&2
  exit 3
fi
docker compose pull || exit 3
version="$(docker image inspect --format '{{range .Config.Env}}{{println .}}{{end}}' '__IMAGE__' | sed -n 's/^APP_VERSION=//p')"
echo "pulled __IMAGE__: APP_VERSION=$version"
__CHECK__
docker compose up -d
'@

if ($Target -eq 'Prod') {
    $Check = @'
if [[ ! "$version" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "FAIL: __IMAGE__ is '$version', not a vX.Y.Z release: PROD runs releases only." >&2
  exit 3
fi
if [[ "$version" != '__EXPECTED__' ]]; then
  echo "FAIL: __IMAGE__ is $version, but the newest release tag is __EXPECTED__ (is its build still running?)." >&2
  exit 3
fi
'@
} else {
    $Check = @'
if [[ ! "$version" =~ ^validation-([0-9a-f]{7,40})$ || '__SHA__' != "${BASH_REMATCH[1]}"* ]]; then
  echo "FAIL: __IMAGE__ is '$version', but the validation tag is on __SHA__ (is its build still running?)." >&2
  exit 3
fi
'@
}

# LF only: this file may be checked out with CRLF, and bash reads a trailing
# carriage return as part of the command.
$RemoteScript = $RemoteScript.Replace('__CHECK__', $Check.TrimEnd()) -replace "`r", ''
$RemoteScript = $RemoteScript.Replace('__DIR__', $Dir).Replace('__IMAGE__', $ImageRef)
if ($Target -eq 'Prod') {
    $RemoteScript = $RemoteScript.Replace('__EXPECTED__', $Release)
} else {
    $RemoteScript = $RemoteScript.Replace('__SHA__', $ValSha)
}

# Sent base64-encoded as the SSH command: no quoting for the remote shell to
# reinterpret, and stdin stays free for a passphrase prompt.
$Encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($RemoteScript + "`n"))
$SshArgs = @('-p', $SshPort, '-i', $SshKey, "$DeployUser@$DeployHost", "echo $Encoded | base64 -d | bash")

Step "[2/3] Deploying $ImageRef on $DeployHost..."
if ($WhatIfPreference) {
    Write-Host "  ssh -p $SshPort -i $SshKey $DeployUser@$DeployHost `"echo <the script below, base64> | base64 -d | bash`""
    Write-Host '  ---- script run on the host ----' -ForegroundColor DarkGray
    foreach ($line in $RemoteScript -split "`n") { Write-Host "  | $line" -ForegroundColor DarkGray }
}
if ($PSCmdlet.ShouldProcess("${DeployHost}:$Dir", 'ssh: check the compose image, docker compose pull, check APP_VERSION, docker compose up -d')) {
    & ssh @SshArgs
    $code = $LASTEXITCODE
    if ($code -eq 3) { Die 'Stopped before the running containers were touched (see FAIL above).' }
    if ($code -eq 255) { Die "ssh could not connect to $DeployHost, or lost the connection." }
    if ($code -ne 0) { Die "docker compose up -d failed on the host (exit code $code)." }
}

# ── 3. Verify through the public URL ──────────────────────────────────────────
# A container that crash-loops still counts as started, so a clean up -d
# proves nothing: the environment must answer with the new version.
Step "[3/3] Verifying $Url..."
if ($PSCmdlet.ShouldProcess($Url, "GET /api/version until it reports $Expected (${VerifySeconds} s), then GET /api/health")) {
    $deadline = (Get-Date).AddSeconds($VerifySeconds)
    $reported = $null
    while ($true) {
        try {
            $reported = (Invoke-RestMethod -Uri "$Url/api/version" -TimeoutSec 10).version
        } catch {
            $reported = $null # not up yet: keep polling until the deadline
        }
        if (Test-ExpectedVersion $reported) { break }
        if ((Get-Date) -ge $deadline) {
            Die "$Url/api/version reports '$reported' after ${VerifySeconds} s, expected $Expected."
        }
        Start-Sleep -Seconds 5
    }
    Write-Host "  /api/version: $reported"

    try {
        $health = Invoke-RestMethod -Uri "$Url/api/health" -TimeoutSec 10
    } catch {
        $details = if ($_.ErrorDetails) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        Die "$Url/api/health is not healthy: $details"
    }
    if ($health.status -ne 'ok') { Die "$Url/api/health reports status '$($health.status)'." }
    Write-Host "  /api/health: ok (database $($health.database), media $($health.media))"

    Write-Host ''
    Write-Host '===========================================' -ForegroundColor Green
    Write-Host "  Deployed and verified $reported ($Target)" -ForegroundColor Green
    Write-Host "  App : $Url" -ForegroundColor Green
    Write-Host '===========================================' -ForegroundColor Green
}
