#!/usr/bin/env bash
# Linux smoke test of the VPS setup (plan D17), run by
# .github/workflows/deploy-smoke.yml on a throwaway runner with passwordless
# sudo: builds the image, lays out PROD and VAL as docs/DEPLOYMENT.md does,
# boots both from empty volumes, takes a backup and seeds VAL from it.
#
# Never run it on the VPS: it creates /opt/shushgift*, a user and containers on
# the real ports. It refuses to start when those directories exist.
#
#   bash deploy/smoke/run.sh
set -euo pipefail

repo=$(cd "$(dirname "$0")/../.." && pwd)
# Nothing below depends on the caller's directory, and the deploy user could
# not enter the runner's checkout anyway.
cd /

prod=/opt/shushgift
val=/opt/shushgift-val
media=/opt/shushgift-media
# Stands in for the runbook's <deploy-user>: not root, in the docker group.
deploy_user=shushgift-deploy
version=smoke

log() { printf '\n==> %s\n' "$*"; }
fail() { echo "FAIL: $*" >&2; exit 1; }

as_deploy() { sudo -u "$deploy_user" -H "$@"; }
compose_prod() { as_deploy docker compose -f "$prod/docker-compose.yml" "$@"; }
compose_val() { as_deploy docker compose -f "$val/docker-compose.yml" "$@"; }

on_exit() {
    local status=$?
    if [ "$status" -ne 0 ]; then
        log "failed (exit $status): containers and logs"
        docker ps -a || true
        compose_prod logs --no-color || true
        compose_val logs --no-color || true
    fi
}
trap on_exit EXIT

# Asserts that "$2" equals "$3"; $1 says what was compared.
expect() {
    [ "$2" = "$3" ] || fail "$1: expected '$3', got '$2'"
    echo "ok: $1 = $3"
}

# /api/health with every part ok, and /api/version from this build in this
# environment.
check_app() {
    local port=$1 env=$2 health=
    for _ in $(seq 60); do
        health=$(curl -sS "http://127.0.0.1:$port/api/health" || true)
        if jq -e '.status == "ok" and .database == "ok" and .media == "ok"' \
                <<<"$health" >/dev/null 2>&1; then
            break
        fi
        sleep 2
    done
    jq -e '.status == "ok" and .database == "ok" and .media == "ok"' \
        <<<"$health" >/dev/null || fail "port $port: /api/health is '$health'"
    echo "ok: port $port: $health"
    curl -fsS "http://127.0.0.1:$port/api/version" |
        jq -e --arg v "$version" --arg e "$env" '.version == $v and .env == $e' >/dev/null ||
        fail "port $port: /api/version is not $version/$env (the GHCR image ran instead of this build?)"
}

# Only the app is published, on loopback, and the database not at all (D3, D8).
check_ports() {
    local compose=$1 port=$2
    expect "$compose app ports" "$($compose port app 8000)" "127.0.0.1:$port"
    expect "$compose db published ports" "$(docker port "$($compose ps -q db)")" ""
}

psql_in() {
    local compose=$1 db=$2 sql=$3
    $compose exec -T -u postgres db psql -U "$db" -d "$db" -v ON_ERROR_STOP=1 -tAc "$sql"
}

for dir in "$prod" "$val" "$media"; do
    [ ! -e "$dir" ] || fail "$dir exists: this is for a throwaway machine, never the VPS"
done

log "Caddy snippet validates"
prod_host=prod.shushgift.test
www_host=www.$prod_host
caddy_dir=$(mktemp -d)
sed -e "s/<prod-host>/$prod_host/g" -e 's/<val-host>/val.shushgift.test/g' \
    "$repo/deploy/caddy/Caddyfile.snippet" >"$caddy_dir/Caddyfile"
docker run --rm -v "$caddy_dir:/etc/caddy:ro" caddy:2 \
    caddy validate --adapter caddyfile --config /etc/caddy/Caddyfile

log "Caddy sends www to the apex, and never elsewhere (Shush Gift plan D1)"
# The snippet as the VPS runs it, with certificates from Caddy's own CA: the
# test hosts have no public DNS. Only the www site is requested, so the other
# sites' upstreams need not be up.
{ printf '{\n\tlocal_certs\n\tskip_install_trust\n}\n\n'; cat "$caddy_dir/Caddyfile"; } \
    >"$caddy_dir/Caddyfile.run"
caddy_port=8443
docker run -d --name shushgift-smoke-caddy -p "127.0.0.1:$caddy_port:443" \
    -v "$caddy_dir:/etc/caddy:ro" caddy:2 \
    caddy run --adapter caddyfile --config /etc/caddy/Caddyfile.run >/dev/null
# "<status> <Location>" of a request to the www site; the arguments shape it.
www_request() {
    curl -ksS -o /dev/null -w '%{http_code} %header{location}' \
        --resolve "$www_host:$caddy_port:127.0.0.1" "$@"
}
www_url="https://$www_host:$caddy_port"
for _ in $(seq 30); do
    [ "$(www_request "$www_url/" 2>/dev/null || true)" = "301 https://$prod_host/" ] && break
    sleep 1
done
expect "www redirect" "$(www_request "$www_url/shared/x?gift=y")" "301 https://$prod_host/shared/x?gift=y"
# Whatever a request carries, a Location it gets names the apex, followed by a
# path: never another host.
expect_apex_only() {
    local what=$1 result location
    shift
    result=$(www_request "$@") || fail "$what: no answer"
    location=${result#* }
    case $location in
        "" | "https://$prod_host/"*) echo "ok: $what: $result" ;;
        *) fail "$what: redirects to '$location'" ;;
    esac
}
expect_apex_only "another Host" -H "Host: evil.example" "$www_url/"
expect_apex_only "a Host ending in another domain" -H "Host: $www_host.evil.example" "$www_url/"
expect_apex_only "X-Forwarded-Host" -H "X-Forwarded-Host: evil.example" "$www_url/"
expect_apex_only "a path starting with //" --path-as-is "$www_url//evil.example/"
expect_apex_only "a path starting with /\\" --request-target '/\evil.example/' "$www_url/"
expect_apex_only "a target in absolute form" --request-target "https://evil.example/" "$www_url/"
expect_apex_only "a target in absolute form naming www" \
    --request-target "https://$www_host/x" "$www_url/"
expect_apex_only "a target with user info" --request-target "https://$www_host@evil.example/" "$www_url/"
expect_apex_only "a path with an encoded line break" \
    --request-target "/%0d%0aLocation:%20https://evil.example/" "$www_url/"
docker rm -f shushgift-smoke-caddy >/dev/null

log "Build the image, tagged as both stacks expect it"
docker build --build-arg APP_VERSION="$version" -t shushgift:smoke "$repo"
# The compose files name the GHCR tags. With these local tags present, compose
# does not pull them; check_app's version check proves it.
docker tag shushgift:smoke ghcr.io/rui-nar/shushgift:latest
docker tag shushgift:smoke ghcr.io/rui-nar/shushgift:validation

log "Deploy user and directories, as the runbook creates them"
sudo useradd --create-home --groups docker "$deploy_user"
sudo install -d -o "$deploy_user" -g "$deploy_user" -m 755 "$prod" "$prod/backup" "$val"
sudo install -d -o 999 -g 10001 -m 750 "$prod/backups"
sudo install -d -o root -g root -m 755 "$media"
sudo install -d -o 10001 -g 10001 -m 750 "$media/prod" "$media/val"
# Not a runbook step: shows whether this host has default ACLs, which replace
# the umask for new files. Every mode above and below is set explicitly, so
# the result must not depend on them.
sudo getfacl -p /opt "$prod/backups" "$media/prod" 2>&1 || true

as_file() { sudo install -o "$deploy_user" -g "$deploy_user" -m "$1" "${@:2}"; }
as_file 644 "$repo/deploy/prod/docker-compose.yml" "$prod/"
as_file 644 "$repo/deploy/backup/backup.sh" "$repo/deploy/backup/healthcheck.sh" "$prod/backup/"
as_file 644 "$repo/deploy/val/docker-compose.yml" "$val/"
as_file 755 "$repo/deploy/val/seed-from-prod.sh" "$val/"
# Each .env from its example, with its own generated password.
env_dir=$(mktemp -d)
sed "s/<postgres-password>/$(openssl rand -hex 32)/g" "$repo/deploy/prod/.env.example" >"$env_dir/prod"
sed "s/<postgres-password>/$(openssl rand -hex 32)/g" "$repo/deploy/val/.env.example" >"$env_dir/val"
as_file 600 "$env_dir/prod" "$prod/.env"
as_file 600 "$env_dir/val" "$val/.env"

log "PROD database and app from an empty volume"
compose_prod up -d --wait --wait-timeout 300 db app
check_app 8010 production
check_ports compose_prod 8010
# The .env value is quoted for its space; compose hands it over unquoted.
expect "PROD sender name" "$(compose_prod exec -T app printenv EMAIL_SENDER_NAME)" "Shush Gift"

log "Old dumps for the rotation, and the healthcheck failing on them"
# The runner's shell cannot list the backups directory (999:10001, mode 750),
# so a glob there would stay literal: every path under it is named in full and
# reached through sudo (or a container), here and below.
for day in $(seq -w 1 31); do
    old="$prod/backups/shushgift_2000-01-$day.dump"
    sudo touch -d '40 days ago' "$old"
    sudo chown 999:999 "$old"
done
if compose_prod run --rm --no-deps -T --entrypoint sh backup /backup/healthcheck.sh; then
    fail "the backup healthcheck passes with no dump newer than 26 hours"
fi
echo "ok: healthcheck fails with only old dumps"

log "A row in PROD, which the dump must carry to VAL"
psql_in compose_prod shushgift \
    "CREATE TABLE smoke_marker (note text); INSERT INTO smoke_marker VALUES ('from-prod');"

log "Backup service: dumps on start, rotates, turns healthy"
compose_prod up -d --wait --wait-timeout 300
expect "backup health" "$(docker inspect -f '{{.State.Health.Status}}' "$(compose_prod ps -q backup)")" healthy
today="$prod/backups/shushgift_$(date -u +%F).dump"
expect "dump owner and mode" "$(sudo stat -c '%u:%g %a' "$today")" "999:999 600"
expect "dumps kept" "$(sudo find "$prod/backups" -name 'shushgift_*.dump' | wc -l)" 30
expect "partial dumps left" "$(sudo find "$prod/backups" -name '*.partial' | wc -l)" 0
sudo test ! -e "$prod/backups/shushgift_2000-01-02.dump" || fail "the oldest dumps were not deleted"
sudo test -e "$prod/backups/shushgift_2000-01-03.dump" || fail "a dump among the 30 newest was deleted"

log "PROD's app lists the dumps and cannot read them (gift images plan D10)"
expect "backups owner and mode" "$(sudo stat -c '%u:%g %a' "$prod/backups")" "999:10001 750"
# Prints how many dumps the app sees; exits non-zero if it can open or create a
# file there.
backups_probe='
import os, sys
d = os.environ["BACKUP_DIR"]
dumps = [n for n in os.listdir(d) if n.startswith("shushgift_") and n.endswith(".dump")]
dump = os.path.join(d, sys.argv[1])
os.stat(dump)
try:
    open(dump, "rb").close()
    sys.exit("the app can read " + dump)
except PermissionError:
    pass
try:
    open(os.path.join(d, "smoke-probe"), "x").close()
    sys.exit("the app can write to " + d)
except OSError:
    pass
print(len(dumps))
'
expect "dumps the app lists"     "$(compose_prod exec -T app python -c "$backups_probe" "$(basename "$today")")" 30

log "A file written through PROD's app lands on the host, owned by 10001"
# shellcheck disable=SC2016 # $MEDIA_DIR is the container's
compose_prod exec -T app sh -c 'echo probe > "$MEDIA_DIR/smoke-probe"'
expect "probe owner on the host" "$(sudo stat -c '%u' "$media/prod/smoke-probe")" 10001

log "VAL from an empty volume"
compose_val up -d --wait --wait-timeout 300
check_app 8011 validation
check_ports compose_val 8011
expect "VAL sender name" "$(compose_val exec -T app printenv EMAIL_SENDER_NAME)" "Shush Gift"

log "Seed VAL from PROD as the deploy user, twice (the second finds VAL's files there)"
as_deploy "$val/seed-from-prod.sh"
as_deploy "$val/seed-from-prod.sh"

log "VAL is healthy and has PROD's data and files"
check_app 8011 validation
expect "VAL row" "$(psql_in compose_val shushgift_val 'SELECT note FROM smoke_marker')" from-prod
expect "VAL table owner" \
    "$(psql_in compose_val shushgift_val "SELECT tableowner FROM pg_tables WHERE tablename = 'smoke_marker'")" \
    shushgift_val
expect "VAL alembic revisions" "$(psql_in compose_val shushgift_val 'SELECT count(*) FROM alembic_version')" 1
expect "probe hard-linked" "$(sudo stat -c '%i %h' "$media/val/smoke-probe")" \
    "$(sudo stat -c '%i' "$media/prod/smoke-probe") 2"
# shellcheck disable=SC2016 # $MEDIA_DIR is the container's
expect "probe seen by VAL's app" "$(compose_val exec -T app sh -c 'cat "$MEDIA_DIR/smoke-probe"')" probe

log "deploy smoke test passed"
