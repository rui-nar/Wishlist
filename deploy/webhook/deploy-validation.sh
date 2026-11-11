#!/bin/bash
# Triggered by the `shushgift-webhook` service (hooks.yaml) whenever the
# "Build and publish Docker image" workflow finishes successfully off the
# `validation` tag (plan D6). Runs locally on the VPS as the deploy user: the
# same pull and up -d that deploy.ps1 -Target Val does over SSH, minus the
# human, then checks that VAL really serves the build that triggered it.
#
#   deploy-validation.sh <workflow_run.head_sha>
#
# Installed as /opt/shushgift-val/webhook/deploy-validation.sh (plan D7).
set -euo pipefail

VAL_DIR=/opt/shushgift-val
HOOK_DIR="$VAL_DIR/webhook"
LOG_FILE="$HOOK_DIR/deploy.log"
LOCK_FILE="$HOOK_DIR/deploy.lock"
LOCK_WAIT=900
# VAL's app on the loopback port of plan D8.
VERSION_URL=http://127.0.0.1:8011/api/version
# 60 x 5 s: up to 5 minutes for the new container to start and migrate.
VERIFY_ATTEMPTS=60
VERIFY_INTERVAL=5

# The file is for `tail -f`; stdout reaches the journal, where webhook -verbose
# logs the command's output once it exits.
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$LOG_FILE"; }

sha="${1:-}"
if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
  log "FAILED: expected the built commit's full sha as the only argument, got '$sha'"
  exit 2
fi
short="${sha:0:7}"
log "delivery for $sha received"

# Wait for a deploy already running rather than skip this one: that deploy may
# have pulled before this build's image was pushed, and skipping would leave
# VAL on the older build with nothing left to fix it.
exec 9>"$LOCK_FILE"
if ! flock -w "$LOCK_WAIT" 9; then
  log "FAILED $short: another deploy still held $LOCK_FILE after ${LOCK_WAIT}s"
  exit 1
fi

cd "$VAL_DIR"

# No `docker compose down`: the pull runs while the old containers keep
# serving, so a failed pull leaves VAL as it was.
if ! docker compose pull >>"$LOG_FILE" 2>&1; then
  log "FAILED $short: docker compose pull"
  exit 1
fi

if ! docker compose up -d >>"$LOG_FILE" 2>&1; then
  log "FAILED $short: docker compose up -d"
  exit 1
fi

# The workflow bakes APP_VERSION=validation-$(git rev-parse --short <sha>)
# (plan D11). --short gives 7 hex digits unless git needs more to stay
# unambiguous, so any prefix of 7 or more digits of the built sha is a match.
# Keep polling until the deadline: the new container needs time to start and
# migrate.
reported=""
for ((attempt = 1; attempt <= VERIFY_ATTEMPTS; attempt++)); do
  body="$(curl -fsS --max-time 5 "$VERSION_URL" 2>/dev/null || true)"
  reported="$(printf '%s' "$body" | sed -n 's/.*"version" *: *"\([^"]*\)".*/\1/p')"
  if [[ "$reported" =~ ^validation-([0-9a-f]{7,40})$ ]]; then
    if [[ "$sha" == "${BASH_REMATCH[1]}"* ]]; then
      log "SUCCESS $short: $VERSION_URL reports $reported"
      # Drop the images the pull left untagged, or every build adds one to a
      # disk shared with TraxJourney. Only after success, so a failed deploy
      # keeps the previous image to go back to. Dangling only: nothing a tag
      # or container still uses.
      if ! docker image prune -f >>"$LOG_FILE" 2>&1; then
        log "WARNING $short: docker image prune failed; old images stay on disk"
      fi
      exit 0
    fi
  fi
  if ((attempt < VERIFY_ATTEMPTS)); then
    sleep "$VERIFY_INTERVAL"
  fi
done

log "FAILED $short: $VERSION_URL reports '${reported:-no version}', expected validation-$short"
exit 1
