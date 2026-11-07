#!/bin/sh
# Nightly dump of PROD's database (plan D9). The entrypoint of the `backup`
# service in deploy/prod/docker-compose.yml, which runs it as uid 999 in the
# pinned Postgres image with /opt/wishlist/backups mounted at /backups.
#
# Dumps once on start, then every day at 02:00 UTC, to
# /backups/wishlist_<YYYY-MM-DD>.dump (custom format, for pg_restore), and
# keeps the 30 newest. A failed dump is logged and the loop goes on: the
# service's healthcheck (healthcheck.sh) reports it once no dump is recent.
set -u

BACKUP_DIR=/backups
KEEP=30

# Dumps hold every user's data: readable by uid 999 only (and chmod-ed so in
# dump()).
umask 077

log() {
    echo "$(date -u '+%Y-%m-%dT%H:%M:%SZ') backup: $*"
}

dump() {
    day=$(date -u +%F)
    final="$BACKUP_DIR/wishlist_$day.dump"
    # A temporary name the healthcheck and the rotation never match, renamed
    # only once complete: a dump cut short never passes for a good one.
    tmp="$BACKUP_DIR/.wishlist_$day.dump.partial"
    # chmod as well as the umask: a default ACL on the host directory
    # replaces the umask for new files, which would then be world-readable.
    if PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" -Fc -f "$tmp" \
        && chmod 600 "$tmp" \
        && mv -f "$tmp" "$final"; then
        log "wrote $final ($(du -h "$final" | cut -f1))"
    else
        rm -f "$tmp"
        log "FAILED, next attempt at the next 02:00 UTC"
        return 1
    fi
}

# Keeps the $KEEP newest dumps. ISO dates in the names sort by age.
rotate() {
    # shellcheck disable=SC2012 # the names are ours, without newlines
    ls -1 "$BACKUP_DIR"/wishlist_*.dump 2>/dev/null | sort -r | tail -n +"$((KEEP + 1))" |
        while read -r old; do
            rm -f "$old" && log "deleted $old"
        done
}

seconds_until_0200() {
    now=$(date -u +%s)
    next=$(date -u -d 'today 02:00' +%s)
    if [ "$next" -le "$now" ]; then
        next=$(date -u -d 'tomorrow 02:00' +%s)
    fi
    echo $((next - now))
}

# `docker compose stop` sends TERM to this script, PID 1. Sleeping in the
# background and waiting lets the trap run at once instead of after the 10 s
# grace period.
trap 'log "stopping"; exit 0' TERM INT

# Leftovers of a dump interrupted by a stop or a crash.
rm -f "$BACKUP_DIR"/.wishlist_*.dump.partial

while true; do
    dump && rotate
    wait_s=$(seconds_until_0200)
    log "next dump in ${wait_s}s"
    sleep "$wait_s" &
    wait $!
done
