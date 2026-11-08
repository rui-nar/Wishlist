# ── Wishlist golden tests, rendered in a Linux container ──────────────────────
# Usage (see docs/DEVELOPMENT.md, "Golden tests"):
#   .\goldens.ps1          — regenerate the golden images (flutter test
#                            --update-goldens --tags golden in client/)
#   .\goldens.ps1 -Check   — compare against them instead, as CI does
# Goldens render on Linux only (plan D10): the same Flutter version draws text
# slightly differently on Windows, so they are never generated on the host.
param([switch]$Check)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# The Flutter tag is the Dockerfile's FLUTTER_TAG and test.yml's
# flutter-version: move all three together.
$flutterTag = '3.47.1'

function Invoke-Native([string]$What, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: $What failed (exit code $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host 'ERROR: docker not found on PATH (Docker Desktop).' -ForegroundColor Red
    exit 1
}

# ── Image: the Dockerfile's web stage base and packages, without the SDK ──────
# Built locally and cached by Docker, so later runs skip apt. One RUN line: the
# Dockerfile arrives on stdin, where line continuations would carry CRLFs.
$image = 'wishlist-goldens'
$dockerfile = @(
    'FROM debian:bookworm-slim'
    'RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git unzip xz-utils zip && rm -rf /var/lib/apt/lists/*'
) -join "`n"
Write-Host 'Building the goldens image...' -ForegroundColor Cyan
Invoke-Native 'docker build' { $dockerfile | docker build --quiet --tag $image - | Out-Null }

# ── Script run in the container ───────────────────────────────────────────────
# The SDK volume is cloned once, and again only when it holds another tag (or
# a clone that was interrupted). The script has no double quotes, so Windows
# argument quoting cannot mangle it, and no CRs, which bash would choke on.
$script = @'
set -eu
if [ $(git -C /opt/flutter describe --tags --exact-match 2>/dev/null || echo none) != $FLUTTER_TAG ]; then
  echo Cloning Flutter $FLUTTER_TAG into the SDK volume...
  find /opt/flutter -mindepth 1 -delete
  git clone --depth 1 --branch $FLUTTER_TAG https://github.com/flutter/flutter.git /opt/flutter
fi
git config --global --add safe.directory /opt/flutter
export PATH=/opt/flutter/bin:$PATH
flutter config --no-analytics --no-cli-animations > /dev/null
cd /repo/client
flutter pub get --enforce-lockfile
flutter test $@ --tags golden
'@ -replace "`r", ''

# @() around the if: an if expression unrolls a one-element array into a bare
# string, which @testArgs would then splat one character at a time.
$testArgs = @(if (-not $Check) { '--update-goldens' })

# ── Run ───────────────────────────────────────────────────────────────────────
# The repository is mounted at /repo. Named volumes cache the SDK and the pub
# cache between runs. client/.dart_tool and client/build get container-only
# volumes, and client/android and client/ios empty tmpfs mounts, so the
# container never writes Linux paths (package_config.json, local.properties,
# Generated.xcconfig) into the Windows tree, and the host's flutter keeps
# working without a pub get (review R1-2). Docker Desktop writes files into a
# Windows bind mount as the Windows user, so the goldens are not root-owned.
$mode = if ($Check) { 'Comparing' } else { 'Regenerating' }
Write-Host "$mode the goldens with Flutter $flutterTag on Linux..." -ForegroundColor Cyan
Invoke-Native 'flutter test --tags golden' {
    docker run --rm `
        --env "FLUTTER_TAG=$flutterTag" `
        --env PUB_CACHE=/pub-cache `
        --volume "${root}:/repo" `
        --volume wishlist-goldens-flutter:/opt/flutter `
        --volume wishlist-goldens-pub-cache:/pub-cache `
        --volume wishlist-goldens-dart-tool:/repo/client/.dart_tool `
        --volume wishlist-goldens-build:/repo/client/build `
        --tmpfs /repo/client/android `
        --tmpfs /repo/client/ios `
        $image bash -c $script goldens @testArgs
}
