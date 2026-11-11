#!/usr/bin/env bash
# Seeds VAL with PROD's newest nightly dump and PROD's uploaded files (plan D9,
# D18). It is also the test that PROD's dumps restore.
#
# Installed as /opt/wishlist-val/seed-from-prod.sh; run on the VPS as the
# deploy user (in the docker group, never root), from any directory:
#
#   /opt/wishlist-val/seed-from-prod.sh
#
# Replaces VAL's database: everything written to VAL since the last seed is
# lost. VAL's app is down from the moment its database is dropped until the end.
set -euo pipefail

val_dir=/opt/wishlist-val
prod_backups=/opt/wishlist/backups
media_root=/opt/wishlist-media

compose() {
    docker compose -f "$val_dir/docker-compose.yml" "$@"
}

log() {
    echo "seed-from-prod: $*" >&2
}

# The dumps are readable by uid 999 only (mode 700 directory, 600 files), so
# they are read in a one-shot container of VAL's own Postgres service, as 999.
# Its pgdata volume is mounted too but never touched.
prod_dumps() {
    compose run --rm --no-deps -T --user 999:999 \
        -v "$prod_backups:/prod-backups:ro" --entrypoint "$1" db "${@:2}"
}

# 1. Find the dump before touching VAL: no dump, nothing changed.
newest=$(prod_dumps sh -c 'cd /prod-backups && ls -1 wishlist_*.dump 2>/dev/null | sort | tail -n 1')
if [ -z "$newest" ]; then
    log "no wishlist_*.dump in $prod_backups; VAL left as it was"
    exit 1
fi
log "seeding VAL from $newest"

trap 'log "FAILED: VAL may be left stopped. Fix the cause and run this again (or run docker compose up -d in $val_dir for an empty VAL)."' ERR

# 2. No connections left on VAL's database.
compose stop app

# 3 and 4. Inside VAL's db container as `postgres`, over its unix socket, with
# VAL's own role. The single-quoted variables are VAL's, expanded by the
# container's shell from its env_file. --no-owner and --no-privileges: PROD's
# role does not exist here (VAL has its own, plan D2), so every object
# belongs to VAL's role instead. One transaction: a restore that fails leaves
# an empty database, not half of one.
# shellcheck disable=SC2016
compose exec -T -u postgres db sh -c '
    dropdb -U "$POSTGRES_USER" --if-exists --force "$POSTGRES_DB" &&
    createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"'
# shellcheck disable=SC2016
prod_dumps cat "/prod-backups/$newest" |
    compose exec -T -u postgres db sh -c '
        pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            --no-owner --no-privileges --exit-on-error --single-transaction'
log "database restored"

# 4b. PROD's purchases stay on PROD (premium plan D16): their ids mean nothing
# to VAL's Stripe test account. So do PROD's Apple tokens (iOS app plan D5):
# they are real secrets, and an account deleted on VAL would revoke them.
# Before anything else can fail or start the app. A dump can predate these
# tables; the app then creates them empty on start.
# shellcheck disable=SC2016
compose exec -T -u postgres db sh -c '
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' <<'SQL'
DO $$
BEGIN
    IF to_regclass('public.entitlements') IS NOT NULL THEN
        TRUNCATE public.entitlements;
    END IF;
    IF to_regclass('public.billing_customers') IS NOT NULL THEN
        TRUNCATE public.billing_customers;
    END IF;
    IF to_regclass('public.apple_tokens') IS NOT NULL THEN
        TRUNCATE public.apple_tokens;
    END IF;
END
$$;
SQL
log "PROD's purchases and Apple tokens removed"

# 5. PROD's files, hard-linked into VAL's directory: no extra disk, and safe
# because a media file is never modified (D18). Files VAL already has are kept.
# As uid 10001, the files' owner: Debian's fs.protected_hardlinks forbids the
# deploy user to link files it does not own. With /opt/wishlist-media mounted
# once: links across two mounts fail even on one filesystem.
compose run --rm --no-deps -T --user 10001:10001 \
    -v "$media_root:/media" --entrypoint cp app \
    -R -l --update=none /media/prod/. /media/val/
log "media linked"

# 6. VAL's app migrates the restored database to its own head on start (the
# entrypoint runs `alembic upgrade head`), then must report healthy.
compose up -d --wait --wait-timeout 300
log "done: VAL is up on $newest"
