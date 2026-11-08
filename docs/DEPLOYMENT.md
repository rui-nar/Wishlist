# Deployment (VAL and PROD on the VPS)

Runbook for installing, deploying, backing up and restoring Wishlist on the
OVH VPS that already runs TraxJourney. The decisions behind it (D1…D18) are in
[`plans/DEVOPS_FOUNDATION_PLAN.md`](plans/DEVOPS_FOUNDATION_PLAN.md); the
local DEV environment is in [DEVELOPMENT](DEVELOPMENT.md).

- **PROD**: `/opt/wishlist`, image `ghcr.io/rui-nar/wishlist:latest`,
  `127.0.0.1:8010`, deployed by hand with `deploy.ps1 -Target Prod`.
- **VAL**: `/opt/wishlist-val`, image `:validation`, `127.0.0.1:8011`,
  redeployed by itself through the `wishlist-webhook` unit on `127.0.0.1:9998`.

**Status:** not installed yet. Replace this line with the date once every
item of [Definition of done](#definition-of-done) has been checked.

The repository is public. Nothing from the VPS goes into it: no host name, no
user name, no IP, no secret, no dump. This document uses the placeholders
below; replace them as you run the commands.

## Placeholders

| Placeholder | What to put there |
|---|---|
| `<prod-host>` | PROD's public hostname (open decision: the domain) |
| `<val-host>` | VAL's public hostname |
| `<vps-host>` | the VPS's SSH address (`DEPLOY_HOST` in `deploy.env`) |
| `<deploy-user>` | the VPS account `deploy.ps1` connects as, in the `docker` group (TraxJourney's runbook §1) |
| `<traxjourney-prod-host>`, `<traxjourney-val-host>` | TraxJourney's hostnames, to check it still answers |
| `<release>` | a release tag, `vX.Y.Z` (the first is `v0.1.0`) |
| `<previous-release>` | the release before `<release>` |
| `<sha>` | a full 40-digit commit sha |
| `<short sha>` | the first 7 hex digits of a commit, as `git rev-parse --short` prints it |
| `<YYYY-MM-DD>` | the date in a dump's name, `wishlist_<YYYY-MM-DD>.dump` |
| `<old-major>`, `<new-major>` | Postgres major versions, e.g. `18` and `19` ([Postgres major upgrade](#postgres-major-upgrade)) |
| `<old-postgres-tag>` | the exact Postgres image tag before a major upgrade, e.g. `18.6` |
| `<postgres-password>` | never typed: the text in `deploy/*/.env.example` that [step 5](#5-env-files) replaces with a generated password |
| `<google-web-client-id>` | the ID of Wishlist's web OAuth client in the Google Cloud console, ending in `.apps.googleusercontent.com` ([step 11](#11-google-sign-in)). Public, not a secret, but never committed |

Four placeholders are also the literal text of files in `deploy/`:
`<prod-host>` and `<val-host>` in `Caddyfile.snippet`, `<deploy-user>` in
`wishlist-webhook.service`, and `<postgres-password>` in the `.env.example`
files. Inside the `sed` and `grep` patterns that fill in or check those files
(each marked `# literal placeholder`), leave them as they are.

Commands are marked **[VPS]** (bash, logged in as `<deploy-user>`),
**[dev]** (PowerShell in the repository checkout on the Windows dev machine),
**[GitHub]** (the web UI of `rui-nar/Wishlist`) or **[Google Cloud]** (the
Google Cloud console, in Wishlist's project).

## What Wishlist adds to the VPS

| Path or item | Owner | Mode | What |
|---|---|---|---|
| `/opt/wishlist/` | `<deploy-user>` | 755 | PROD: `docker-compose.yml` (644), `.env` (600) |
| `/opt/wishlist/backup/` | `<deploy-user>` | 755 | `backup.sh`, `healthcheck.sh` (644), mounted read-only into the `backup` service |
| `/opt/wishlist/backups/` | `999:999` | 700 | the nightly dumps (600 each); uid 999 is the `postgres` user of the official image (D14) |
| `/opt/wishlist-val/` | `<deploy-user>` | 755 | VAL: `docker-compose.yml` (644), `.env` (600), `seed-from-prod.sh` (755) |
| `/opt/wishlist-val/webhook/` | `<deploy-user>` | 755 | `deploy-validation.sh` (755), `hooks.yaml` (600, holds the secret), `deploy.log`, `deploy.lock` |
| `/opt/wishlist-media/` | `root` | 755 | parent of both media directories, so one mount covers both when seeding (D18) |
| `/opt/wishlist-media/prod/`, `/opt/wishlist-media/val/` | `10001:10001` | 750 | uploaded files; uid 10001 is the app's fixed user (D18) |
| `/etc/systemd/system/wishlist-webhook.service` | `root` | 644 | the VAL auto-deploy listener, `127.0.0.1:9998` (D7) |
| `/etc/caddy/Caddyfile` | | | two site blocks appended, `<prod-host>` and `<val-host>` |
| Docker volumes `wishlist-prod_pgdata`, `wishlist-val_pgdata` | | | each environment's Postgres data (D2, D14) |

The owners and modes are exactly the ones `deploy/smoke/run.sh` creates, and
the `Deploy smoke test` workflow proves on Linux that both stacks boot, back up
and seed with them (D17). Never run `deploy/smoke/run.sh` on the VPS: it
creates a user and these directories, and refuses to start when they exist.

Nothing of TraxJourney's is edited apart from appending to the Caddyfile.

## 1. Prerequisites

### What TraxJourney's setup already provides

TraxJourney's runbook (`docs/DEPLOYMENT_VPS.md` in its repository) set up the
host. Wishlist relies on all of it and installs none of it again:

| Provided | Used by Wishlist for |
|---|---|
| Debian 12 with Docker Engine and the Compose plugin | both stacks |
| `<deploy-user>` in the `docker` group, key-only SSH, `sudo` with a password | every step here; `deploy.ps1`; the webhook unit's `User=` |
| `ufw` allowing only 22, 80 and 443 | nothing else needs opening: every Wishlist port is on loopback |
| Caddy from its official apt repository, default `:80` block removed | the two new site blocks |
| `webhook` 2.8.0 from Debian's package | `wishlist-webhook.service` runs the same binary |
| `<deploy-user>` logged in to `ghcr.io` with a read-only token | pulls, if the package stays private ([step 3](#3-the-ghcr-package)) |

### Checks before installing

**[VPS]** The deploy user can run Docker and sudo:

```bash
id                     # groups include docker and sudo
docker ps              # TraxJourney's containers, no permission error
sudo -v                # asks for the password, no error
```

**[VPS]** Versions:

```bash
docker version --format '{{.Server.Version}}'   # 25 or later (healthcheck start_interval)
docker compose version
webhook -version                                # 2.8.0 or later (payload-hmac-sha256)
caddy version
```

**[VPS]** No default ACL on `/opt`. A default ACL replaces the umask for every
file and directory created below it. GitHub's Ubuntu runners have one on `/opt`
granting everyone `rwx`, which is how the smoke test found the problem. The
backup script and every command in this runbook set modes explicitly, so the
layout is right either way, but check:

```bash
command -v getfacl || sudo apt install -y acl
getfacl -p /opt
```

The expected output has only `user::`, `group::` and `other::` lines. If it
also has `default:` lines, remove them before creating anything (step 4):
`sudo setfacl -k /opt`. That only changes what new entries under `/opt` inherit;
TraxJourney's existing directories keep their own permissions.

**[VPS]** Wishlist's ports are free, and its directories do not exist yet:

```bash
ss -ltn | grep -E ':(8010|8011|9998)\b'          # nothing
docker ps --format '{{.Names}} {{.Ports}}' | grep -E ':(8010|8011|9998)-' # nothing
ss -ltn | grep -E ':(8000|8001|9999)\b'          # TraxJourney's, on 127.0.0.1 only
ls -d /opt/wishlist* 2>/dev/null                 # nothing
```

If 8010, 8011 or 9998 is taken, stop: the ports are fixed by D8 in the compose
files, `deploy-validation.sh`, the Caddy snippet and the webhook unit, and
changing them is a plan change.

**[VPS]** Free memory and disk:

```bash
free -m                 # "available": more than 1000 MB
swapon --show
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'
df -h /                 # at least 5 GB available
docker system df
```

Wishlist's memory limits add up to 960 MB (PROD app 256, PROD Postgres 256,
VAL app 192, VAL Postgres 192, backup 64). Limits are caps, not reservations,
but if less than that is available with TraxJourney running, stop and decide
first: a peak on either project would then push the host into swap or the
kernel's OOM killer, which may pick a TraxJourney process.

The 5 GB of disk covers two app images plus the previous one each during a
pull, the Postgres image, 30 dumps and the first media. If there is less,
`docker image prune -f` removes untagged images (never one a tag or container
uses).

**[GitHub]** CI is green on `master`: the `Tests` workflow, and the
`Deploy smoke test` workflow (Actions → Deploy smoke test → Run workflow, on
`master`). The smoke test boots both stacks from empty volumes on Linux with
the layout above, takes a backup and seeds VAL from it.

## 2. Getting the files onto the host

The VPS has no checkout of the repository. The files come from GitHub's raw
URLs (the repository is public), into a temporary directory, and are installed
from there with explicit owners and modes.

**[VPS]**

```bash
REF=master    # first install (once this plan is merged); when updating, the release tag
SRC=$(mktemp -d)
for f in \
    deploy/prod/docker-compose.yml deploy/prod/.env.example \
    deploy/backup/backup.sh deploy/backup/healthcheck.sh \
    deploy/val/docker-compose.yml deploy/val/.env.example deploy/val/seed-from-prod.sh \
    deploy/webhook/deploy-validation.sh deploy/webhook/hooks.yaml.example \
    deploy/webhook/wishlist-webhook.service \
    deploy/caddy/Caddyfile.snippet
do
    curl -fsSL --create-dirs -o "$SRC/$f" \
        "https://raw.githubusercontent.com/rui-nar/Wishlist/$REF/$f" || echo "FAILED: $f"
done
find "$SRC" -type f | wc -l     # 11
```

Keep this shell open: steps 4 to 8 use `$SRC`. In a new shell, run the block
again.

## 3. The GHCR package

CI pushes the image to `ghcr.io/rui-nar/wishlist` with the workflow's built-in
`GITHUB_TOKEN` (owner's decision): there is no push token to create, store or
renew. The package does not exist until the first image is pushed, so publish
one first.

**[dev]** Publish the first `:validation` image:

```powershell
git fetch origin
git tag -f validation origin/master
git push origin validation --force
```

**[GitHub]** Actions → "Build and publish Docker image" for `validation`
succeeds. The package then appears under the owner's profile → Packages →
`wishlist`, linked to the repository through the image's
`org.opencontainers.image.source` label. In its Package settings:

- **Manage Actions access** lists `rui-nar/Wishlist` with the **Write** role.
  The first push adds it; if a later build fails with
  `denied: permission_denied: write_package`, add it there.
- **Danger Zone → visibility**: check it rather than assume it. A package a
  workflow creates under a personal account usually starts **private**.

### Private or public: how the VPS pulls

Decide once, now:

| | Keep it private | Make it public |
|---|---|---|
| How the VPS pulls | with `<deploy-user>`'s existing `ghcr.io` login: TraxJourney's read-only classic token (`read:packages` covers every package the account can read). Docker keeps one login per registry and user, so a separate Wishlist token would replace TraxJourney's rather than sit next to it. | without a login |
| Who can pull | only that account | anyone. The image is built from the public repository and holds nothing it does not (no secret is passed to the build, only `APP_VERSION`) |
| Coupling with TraxJourney | when its token expires or is revoked, Wishlist's pulls fail too, until TraxJourney's runbook renews it | none on the token itself, but see below |
| Reversible | yes | **no**: GitHub does not let a public package go back to private |

Docker sends the stored `ghcr.io` login with every `ghcr.io` pull, public
images included, and GHCR rejects an expired token instead of falling back to
an anonymous pull. Either way, then, an expired TraxJourney token stops
Wishlist's pulls until it is renewed or removed (`docker logout ghcr.io` makes
the public image pullable again, and TraxJourney's private one not). A failed
pull is safe: `deploy.ps1` and the webhook stop before touching the running
containers.

**Recommended: make it public.** The source is already public, so the image
discloses nothing new; Wishlist then needs no credential of its own, and does
not depend on TraxJourney's token existing at all. The cost is that the choice
is permanent.

**[GitHub]** To make it public: Package settings → Danger Zone → Change
visibility → Public.

**[VPS]** Either way, the deploy user can now pull:

```bash
docker pull ghcr.io/rui-nar/wishlist:validation
```

## 4. Directories and files

**[VPS]** As `<deploy-user>`, in the shell with `$SRC` from step 2:

```bash
me=$(id -un)
sudo install -d -o "$me" -g "$me" -m 755 \
    /opt/wishlist /opt/wishlist/backup /opt/wishlist-val /opt/wishlist-val/webhook
sudo install -d -o 999 -g 999 -m 700 /opt/wishlist/backups
sudo install -d -o root -g root -m 755 /opt/wishlist-media
sudo install -d -o 10001 -g 10001 -m 750 /opt/wishlist-media/prod /opt/wishlist-media/val

install -m 644 "$SRC/deploy/prod/docker-compose.yml" /opt/wishlist/
install -m 644 "$SRC/deploy/backup/backup.sh" "$SRC/deploy/backup/healthcheck.sh" /opt/wishlist/backup/
install -m 644 "$SRC/deploy/val/docker-compose.yml" /opt/wishlist-val/
install -m 755 "$SRC/deploy/val/seed-from-prod.sh" /opt/wishlist-val/
```

`999` and `10001` are numeric on purpose: they are users inside the
containers. On the host, `ls -l` may show 999 under an unrelated name, or as a
number.

## 5. `.env` files

Each environment gets its own `.env`, created from its example with its own
password from `openssl rand -hex 32` (hex, because it goes into
`DATABASE_URL` unescaped). The file is created empty with mode 600 first, so
the secret is never in a file anyone else can read, whatever the umask.

**[VPS]**

```bash
# literal placeholder: <postgres-password> is the examples' own text
install -m 600 /dev/null /opt/wishlist/.env
sed "s/<postgres-password>/$(openssl rand -hex 32)/g" \
    "$SRC/deploy/prod/.env.example" > /opt/wishlist/.env

install -m 600 /dev/null /opt/wishlist-val/.env
sed "s/<postgres-password>/$(openssl rand -hex 32)/g" \
    "$SRC/deploy/val/.env.example" > /opt/wishlist-val/.env

grep -c '<postgres-password>' /opt/wishlist/.env /opt/wishlist-val/.env   # :0 for both
ls -l /opt/wishlist/.env /opt/wishlist-val/.env                          # -rw------- both
```

Each `sed` generates one password and writes it into both `POSTGRES_PASSWORD`
and `DATABASE_URL`, which must match. The rest of the examples needs no
change: `APP_ENV`, an empty `FRONTEND_ORIGIN` (the web client is served by the
app itself, the mobile apps send no `Origin`), and `FORWARDED_ALLOW_IPS`
(checked after the first start, [step 8](#8-first-val-deploy)).
`GOOGLE_CLIENT_IDS` stays empty until [step 11](#11-google-sign-in): until
then the app runs and answers sign-in with "Google sign-in is not
configured". Never add `MEDIA_DIR` or `APP_VERSION`: the image sets both, and
the comments in `.env.example` say what breaks otherwise.

Things to know about these files:

- `docker compose restart` does not re-read `.env`. After an edit, run
  `docker compose up -d` in the directory, which recreates what changed.
- `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` are read on the
  volume's first boot only. To change the password later, change it in the
  database too, then in both lines of `.env`:

  ```bash
  cd /opt/wishlist                                  # or /opt/wishlist-val
  OLD=$(sed -n 's/^POSTGRES_PASSWORD=//p' .env)
  NEW=$(openssl rand -hex 32)
  echo "ALTER ROLE CURRENT_USER PASSWORD '$NEW';" | docker compose exec -T -u postgres db \
      sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'
  sed -i "s/$OLD/$NEW/g" .env
  docker compose up -d --wait --wait-timeout 300
  ```

  A `.env` whose password no longer matches the database stops the app at its
  migrations and makes every nightly dump fail (the `backup` service turns
  `unhealthy`).
- Nothing else depends on the password: a dump restores into any database, as
  any role (`--no-owner`).

**[VPS]** Both stacks parse with their `.env`:

```bash
docker compose -f /opt/wishlist/docker-compose.yml config -q && echo prod ok
docker compose -f /opt/wishlist-val/docker-compose.yml config -q && echo val ok
docker compose -f /opt/wishlist-val/docker-compose.yml pull     # :validation and postgres
```

**[VPS]** Owners and modes, against the table in
[What Wishlist adds](#what-wishlist-adds-to-the-vps):

```bash
sudo stat -c '%U(%u):%G(%g) %a %n' \
    /opt/wishlist /opt/wishlist/backup /opt/wishlist/backups /opt/wishlist/.env \
    /opt/wishlist/docker-compose.yml /opt/wishlist/backup/*.sh \
    /opt/wishlist-val /opt/wishlist-val/.env /opt/wishlist-val/docker-compose.yml \
    /opt/wishlist-val/seed-from-prod.sh /opt/wishlist-val/webhook \
    /opt/wishlist-media /opt/wishlist-media/prod /opt/wishlist-media/val
sudo getfacl -p /opt/wishlist/backups /opt/wishlist-media/prod /opt/wishlist-val/.env
```

`getfacl` shows only `user::`, `group::` and `other::` lines. Extra entries mean
a default ACL was inherited ([checks](#checks-before-installing)).

## 6. Caddy

This step needs the hostnames (an open decision, D13). Everything before it
can be done without them; see [Before the domain exists](#before-the-domain-exists).

Caddy serves every site on the host from one file. **A reload of a Caddyfile
that does not validate takes down every site, TraxJourney's included.** Hence:
a copy first, `caddy validate` before every reload, and DNS before the reload.

**[VPS]** DNS for both names resolves to the VPS first. Otherwise the
certificate challenge fails and Caddy backs off and retries later:

```bash
getent hosts <prod-host>
getent hosts <val-host>
# If getent is empty but the record is published, ask a public resolver
# (the local one can cache a negative answer):
curl -s "https://dns.google/resolve?name=<val-host>&type=A"
```

**[VPS]** No catch-all `:80` block (the Debian package ships one, and it
intercepts the certificate challenge for a new hostname; TraxJourney's setup
deleted it):

```bash
grep -nE '^\s*(:80|http://)\s*\{' /etc/caddy/Caddyfile     # nothing
```

**[VPS]** Append the snippet once, with the real names, then validate before
reloading:

```bash
PROD_HOST=<prod-host>
VAL_HOST=<val-host>
sudo cp -p /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-wishlist
grep -c '127.0.0.1:801[01]' /etc/caddy/Caddyfile              # 0: not appended yet
# literal placeholder: the two patterns below are the snippet's own text
sed -e "s/<prod-host>/$PROD_HOST/g" -e "s/<val-host>/$VAL_HOST/g" \
    "$SRC/deploy/caddy/Caddyfile.snippet" | sudo tee -a /etc/caddy/Caddyfile >/dev/null
# literal placeholder: 0 means every one was replaced
grep -c -e '<prod-host>' -e '<val-host>' /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

If `caddy validate` fails, nothing was reloaded: put the copy back with
`sudo cp -p /etc/caddy/Caddyfile.before-wishlist /etc/caddy/Caddyfile` and fix
the appended blocks before trying again.

**[VPS]** TraxJourney still answers, and the new sites get certificates:

```bash
curl -s https://<traxjourney-prod-host>/api/version; echo
curl -s https://<traxjourney-val-host>/api/version; echo
sudo journalctl -u caddy -n 50 --no-pager | grep -i -E 'certificate|error'
curl -sI https://<val-host>/ | head -n 1     # 502 until VAL runs (step 8); no TLS error
```

The VAL site routes `/gh-webhook/*` to the webhook on 9998 (with the prefix
stripped) and everything else to the app on 8011. PROD's site never exposes
the hook.

## 7. The VAL webhook

Wishlist has its own `webhook` instance (D7): its own unit, port, hooks file
and secret. TraxJourney's `webhook` unit on 9999 is not touched.

How a build reaches VAL: the "Build and publish Docker image" workflow
finishes; GitHub POSTs a `workflow_run` delivery to
`https://<val-host>/gh-webhook/hooks/deploy-validation`; Caddy passes it to
`127.0.0.1:9998`; `webhook` runs `deploy-validation.sh <sha>` (the built commit) only if the
signature is valid and the run is a successful, completed build of the
`validation` tag in `rui-nar/Wishlist` (every rule in `hooks.yaml.example`).
The script pulls, runs `up -d`, and polls `http://127.0.0.1:8011/api/version`
for up to 5 minutes until it reports `validation-<short sha>` of the built
commit, logging to `/opt/wishlist-val/webhook/deploy.log`.

**[VPS]** Install the script and the examples:

```bash
install -m 755 "$SRC/deploy/webhook/deploy-validation.sh" /opt/wishlist-val/webhook/
install -m 644 "$SRC/deploy/webhook/hooks.yaml.example" \
    "$SRC/deploy/webhook/wishlist-webhook.service" /opt/wishlist-val/webhook/
```

**[VPS]** Create `hooks.yaml` with a new secret, Wishlist's own (never
TraxJourney's):

```bash
cd /opt/wishlist-val/webhook
SECRET=$(openssl rand -hex 32)
install -m 600 /dev/null hooks.yaml
sed "s/secret: \"\"/secret: \"$SECRET\"/" hooks.yaml.example > hooks.yaml
grep -c "secret: \"$SECRET\"" hooks.yaml     # 1
ls -l hooks.yaml                             # -rw------- <deploy-user>
echo "$SECRET"                               # for GitHub, below
```

The example ships with an empty secret on purpose: `webhook` refuses to check
a signature against an empty secret, so a copy nobody filled in rejects every
delivery.

**[VPS]** Install and start the unit, with the deploy user's name in `User=`:

```bash
# literal placeholder: User=<deploy-user> is the unit file's own text
sed "s/^User=<deploy-user>$/User=$(id -un)/" /opt/wishlist-val/webhook/wishlist-webhook.service \
    | sudo tee /etc/systemd/system/wishlist-webhook.service >/dev/null
grep '^User=' /etc/systemd/system/wishlist-webhook.service    # User=<deploy-user>, the real name
sudo systemctl daemon-reload
sudo systemctl enable --now wishlist-webhook
systemctl status wishlist-webhook --no-pager
sudo journalctl -u wishlist-webhook -n 20 --no-pager   # "loaded: deploy-validation",
                                                       # "serving hooks on http://127.0.0.1:9998/hooks/{id}"
ss -ltn | grep ':9998\b'                               # 127.0.0.1:9998 only
systemctl is-active webhook                            # TraxJourney's: still active
curl -s -X POST http://127.0.0.1:9998/hooks/deploy-validation \
    -H 'Content-Type: application/json' -d '{}'; echo # Hook rules were not satisfied.
```

`Hook not found.` from that `curl` means `hooks.yaml` did not load; the
journal says why. The unit runs as the deploy user, with its `docker` group
and its `~/.docker/config.json` (the GHCR login, if any).

**[VPS]** Through Caddy (needs step 6):

```bash
curl -s -X POST https://<val-host>/gh-webhook/hooks/deploy-validation \
    -H 'Content-Type: application/json' -d '{}'; echo # Hook rules were not satisfied.
```

**[GitHub]** `rui-nar/Wishlist` → Settings → Webhooks → Add webhook:

| Field | Value |
|---|---|
| Payload URL | `https://<val-host>/gh-webhook/hooks/deploy-validation` |
| Content type | `application/json` (a form-encoded delivery has none of the fields the rules read) |
| Secret | the `$SECRET` printed above |
| SSL verification | enabled |
| Which events | "Let me select individual events" → **Workflow runs** only (untick Pushes) |
| Active | ticked |

**[GitHub]** Adding it sends a `ping`. The webhook → Recent Deliveries → the
`ping` → Response: **200** `Hook rules were not satisfied.` That proves the
route and the secret (the signature is checked first) and that a ping does not
deploy. A **500** means the secrets differ.

## 8. First VAL deploy

**[dev]** Push the `validation` tag:

```powershell
git fetch origin
git tag -f validation origin/master
git push origin validation --force
git rev-parse --short origin/master          # the <short sha> to expect
```

If `master` has not moved since step 3, the tag is already there: the push
changes nothing and no build starts in Actions. Delete the remote tag and push
it again, which starts one:

```powershell
git push origin :refs/tags/validation
git push origin validation
```

VAL then gets the same commit as the image from step 3, which still proves the
whole chain (delivery, rules, pull, start, version check). The next real
change proves it again on a new version.

**[VPS]** Watch it arrive:

```bash
tail -f /opt/wishlist-val/webhook/deploy.log
```

Within 5 minutes of the build finishing, without any manual step:

- **[GitHub]** Actions: "Build and publish Docker image" for `validation`
  succeeds. Recent Deliveries: `requested` and `in_progress` answer
  `Hook rules were not satisfied.`; `completed` answers
  `Deploying validation...`.
- **[VPS]** `deploy.log`: `delivery for <sha> received`, the pull and `up -d`
  output, then `SUCCESS <short sha>: http://127.0.0.1:8011/api/version reports
  validation-<short sha>`. On an empty volume this run is VAL's first boot:
  Postgres initialises, then the app migrates it.
- **[dev]** The public URL answers:

  ```powershell
  curl.exe -s https://<val-host>/api/version    # {"version":"validation-<short sha>","env":"validation"}
  curl.exe -s https://<val-host>/api/health     # {"status":"ok","database":"ok","media":"ok"}
  ```

**[VPS]** Both containers are healthy, and Caddy's traffic arrives from a
gateway `FORWARDED_ALLOW_IPS` trusts:

```bash
docker compose -f /opt/wishlist-val/docker-compose.yml ps     # app and db (healthy)
docker network inspect wishlist-val_default -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}'
```

The gateway must be a `172.16.0.0/12` address (`172.16.x.x` to `172.31.x.x`).
Docker's default pools move to `192.168.x.x` once the 172 ones are used up; if
it is there, add that network to `FORWARDED_ALLOW_IPS` in `.env` (never `*`)
and run `docker compose up -d`. Otherwise every request is logged as coming
from the gateway.

**[dev]** Set up `deploy.env` and check it on VAL before PROD needs it:

```powershell
Copy-Item deploy.env.example deploy.env
# Fill in DEPLOY_HOST=<vps-host>, DEPLOY_USER=<deploy-user>,
# DEPLOY_SSH_KEY (the key you log in as <deploy-user> with),
# DEPLOY_VAL_URL=https://<val-host>, DEPLOY_PROD_URL=https://<prod-host>.
.\deploy.ps1 -Target Val
```

It ends with `Deployed and verified validation-<short sha> (Val)`. This is
also how to deploy VAL by hand when the webhook did not.

## 9. First PROD release

**[dev]** Tag the release:

```powershell
git fetch origin
git tag v0.1.0 origin/master
git push origin v0.1.0
```

**[GitHub]** "Build and publish Docker image" for `v0.1.0` succeeds and
publishes `:latest`, `:<sha>` and `:v0.1.0`. Its `completed` delivery to
the webhook answers `Hook rules were not satisfied.`: releases never deploy by
themselves (D6).

**[dev]** Deploy it:

```powershell
.\deploy.ps1 -Target Prod
```

It asks for confirmation, checks that `/opt/wishlist/docker-compose.yml` runs
`:latest`, pulls, refuses an image whose `APP_VERSION` is not the newest
`vX.Y.Z` tag (a build still running), runs `up -d`, then waits for
`https://<prod-host>/api/version` to report `v0.1.0` and for `/api/health` to
be `ok`. It ends with `Deployed and verified v0.1.0 (Prod)` and
`/api/health: ok (database ok, media ok)`. This first run is PROD's first
boot. If the 120 s check runs out while Postgres initialises, run it again:
the pull is then a no-op.

**[VPS]** All three services healthy, and the first dump written (the backup
service dumps once when it starts):

```bash
docker compose -f /opt/wishlist/docker-compose.yml ps    # app, db, backup: (healthy)
docker network inspect wishlist-prod_default -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}'   # 172.16-31.x.x, as in step 8
sudo ls -l /opt/wishlist/backups/                        # wishlist_<YYYY-MM-DD>.dump, 999 999, -rw-------
```

**[VPS]** Restore test: seed VAL from that dump
([Seeding VAL](#seeding-val-from-prod)):

```bash
/opt/wishlist-val/seed-from-prod.sh       # ends with "done: VAL is up on wishlist_<YYYY-MM-DD>.dump"
```

### Before the domain exists

Steps 1 to 5 need no hostname. Without one:

- Start a stack by hand and check it on loopback:

  ```bash
  docker compose -f /opt/wishlist-val/docker-compose.yml up -d --wait --wait-timeout 300
  curl -s http://127.0.0.1:8011/api/health; echo
  ```

  PROD's `:latest` exists only once a `v*` tag has been built.
- `deploy.ps1` checks the public URL. It can be pointed at a tunnel instead:
  run `ssh -N -L 8011:127.0.0.1:8011 <deploy-user>@<vps-host>` in another
  window and set `DEPLOY_VAL_URL=http://localhost:8011` (8010 for PROD).
- The webhook cannot be reached by GitHub until Caddy serves `<val-host>`.

## 10. Verifying the installation

**[VPS]** No Wishlist port outside loopback, no Postgres port published at all
(D3, D8):

```bash
docker ps --filter name=wishlist --format 'table {{.Names}}\t{{.Ports}}'
ss -ltn | grep -E ':(8010|8011|9998)\b'
```

The apps show `127.0.0.1:8010->8000/tcp` and `127.0.0.1:8011->8000/tcp`; `db`
and `backup` show `5432/tcp` with no `->` (exposed to their compose network,
not published). `ss` lists the three ports on `127.0.0.1` only.

**[dev]** From outside, the ports do not answer:

```powershell
curl.exe -m 5 http://<vps-host>:8010/api/version   # fails: connection refused or timed out
curl.exe -m 5 http://<vps-host>:8011/api/version   # same
```

**[VPS]** Memory within the limits (about 1 GB in total):

```bash
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' | grep -E 'NAME|wishlist'
free -m
```

Each `MemUsage` reads `used / limit`, with limits 256 MiB (PROD app and db),
192 MiB (VAL app and db) and 64 MiB (backup). A container that reaches its
limit is killed and restarted; it does not take memory from TraxJourney.

**[dev]** TraxJourney still answers, as it did before:

```powershell
curl.exe -s https://<traxjourney-prod-host>/api/version
curl.exe -s https://<traxjourney-val-host>/api/version
```

**[dev]** No secret was committed. Every Wishlist secret is 64 hex digits
(`openssl rand -hex 32`); the only such strings in the repository are the
package hashes in the two lock files:

```powershell
git grep -I -n -E '\b[0-9a-f]{64}\b' -- . ':!server/uv.lock' ':!client/pubspec.lock'   # nothing
git log --all --oneline -G '[0-9a-f]{64}' -- . ':!server/uv.lock' ':!client/pubspec.lock'  # nothing
git grep -n -i -F -e <prod-host> -e <val-host> -e <vps-host> -e <deploy-user>   # nothing
```

The last command takes the real names. (The placeholders themselves are
expected in this document and in `deploy/`.)

## 11. Google sign-in

Sign-in uses one web OAuth client for every environment: the one created for
DEV in [DEVELOPMENT](DEVELOPMENT.md#google-sign-in-in-dev), in the same Google
Cloud project. VAL and PROD add their origins to it and put its ID in their
`.env`. This step needs the hostnames ([step 6](#6-caddy)): Google accepts
only `https` origins, apart from `localhost`.

**[Google Cloud]** Google Auth Platform → Clients → `Wishlist web` →
Authorised JavaScript origins. Add, next to `http://localhost:5500`:

| Origin | For |
|---|---|
| `https://<val-host>` | VAL |
| `https://<prod-host>` | PROD |

An origin is the scheme and host only: no path, no trailing slash. Redirect
URIs stay empty (accounts plan D2: the client sends Google's ID token to the
server, nothing redirects). The client secret is not used anywhere: it goes
into no `.env` and no GitHub secret.

**[Google Cloud]** Google Auth Platform → Audience. While the publishing
status is **Testing**, only the listed test users can sign in, which is
enough for VAL. Before PROD serves anyone else, **Publish app**. Sign-in asks
only for `openid`, `email` and `profile`, which need no Google review; adding
a logo to the branding does.

**[VPS]** Set the ID in each `.env` (it is the same in both), then recreate
the app:

```bash
cd /opt/wishlist-val                     # then the same in /opt/wishlist
grep -n '^GOOGLE_CLIENT_IDS=' .env       # GOOGLE_CLIENT_IDS= (empty)
sed -i 's/^GOOGLE_CLIENT_IDS=.*/GOOGLE_CLIENT_IDS=<google-web-client-id>/' .env
grep -n '^GOOGLE_CLIENT_IDS=' .env       # GOOGLE_CLIENT_IDS=<google-web-client-id>
docker compose up -d --wait --wait-timeout 300
```

If `grep` prints nothing, the `.env` predates this setting (an install made
before the accounts plan): add the line from `.env.example` first
([Updating the files on the host](#updating-the-files-on-the-host), last row).
`docker compose restart` would not re-read `.env` ([step 5](#5-env-files)).

**[dev]** Each environment hands the ID to its clients:

```powershell
curl.exe -s https://<val-host>/api/config    # {"google_client_id":"<google-web-client-id>"}
curl.exe -s https://<prod-host>/api/config   # the same
```

`{"google_client_id":null}` means the app did not get the value: check the
line in `.env`, then `docker compose up -d` again. Then sign in on
`https://<val-host>` in a browser. An origin error from Google's button means
the origin in the table above differs from the address in the browser, or was
added a few minutes ago and has not reached Google's servers yet.

**[dev]** The ID was not committed:

```powershell
git grep -n -F <google-web-client-id>     # nothing
```

### Android OAuth client

The Android app gets the web client's ID from `/api/config` and passes it to
Google as its server client ID, so the ID token it receives is issued for the
web client and `GOOGLE_CLIENT_IDS` needs nothing more (accounts plan D2, D12).
Google also requires an **Android** OAuth client in the same project,
registered with the app's package name and the SHA-1 of the key that signed
the installed app. Without it, the Google button fails on the device; the web
is not affected. No client secret is involved, and its client ID goes
nowhere: Google matches the installed app against the registration.

**Not possible for VAL and PROD yet**, for two reasons:

- **The package name is a placeholder.** The Android application id is
  `com.example.wishlist` (`client/android/app/build.gradle.kts`, and
  `client/README.md`, "Placeholder application id"). The real one is an open
  decision of the DevOps plan. A registration made with the placeholder stops
  matching when the id changes and has to be replaced then.
- **There is no release key.** Release builds are signed with the debug key
  for now (`build.gradle.kts`). The release key is the app's identity: an
  update signed with another key cannot be installed over an existing copy,
  and a published app cannot be re-keyed.

Until then, a client registered with the placeholder and the debug key lets
debug builds sign in on the dev machine. Each key needs its own Android
client (one package name and one SHA-1 each), and every machine has its own
debug key.

**[dev]** The debug key's SHA-1 (`keytool` comes with the JDK Flutter uses):

```powershell
keytool -list -v -keystore $HOME\.android\debug.keystore -alias androiddebugkey -storepass android
```

**[Google Cloud]** Google Auth Platform → Clients → Create client:

| Field | Value |
|---|---|
| Application type | **Android** |
| Name | `Wishlist Android debug` (and later `Wishlist Android release`) |
| Package name | the application id: `com.example.wishlist` today, the real one once chosen |
| SHA-1 certificate fingerprint | the `SHA1:` line printed by `keytool` |

Once the real application id and the release key exist, register a second
client with the release key's SHA-1 (`keytool -list -v -keystore` on the
release keystore). If Google Play ends up signing the app with a key other
than the release key (a key Google generated for Play App Signing), register
that key's SHA-1 too, as Play Console shows it under App integrity.

## Daily check

**[VPS]** (or over `ssh <deploy-user>@<vps-host>` from the dev machine):

```bash
docker ps --filter name=wishlist --format 'table {{.Names}}\t{{.Status}}'
df -h /
```

- Every Wishlist container says `(healthy)`. `wishlist-prod-backup-1` turns
  `unhealthy` when no dump is newer than 26 hours: a failed backup shows here
  without reading logs ([Backups](#backups)). An app turns `unhealthy` when
  `/api/health` fails: the database is unreachable or its media directory is
  not writable.
- At least 5 GB available on `/`. Media grow with use and have no per-account
  limit yet (open in `docs/NEEDS.md`), so this check is the only guard against
  the disk filling. If it drops, see what grew:

  ```bash
  sudo du -sh /opt/wishlist-media /opt/wishlist/backups
  docker system df
  ```

## Backups

- **What:** `pg_dump -Fc` of PROD's database, by the `backup` service in
  `/opt/wishlist/docker-compose.yml` (D9). VAL has no backup: it is
  disposable, and re-seeded from PROD.
- **When:** once when the service starts, then every night at 02:00 UTC. A
  failed dump is logged and the next attempt is the next 02:00.
- **Where:** `/opt/wishlist/backups/wishlist_<YYYY-MM-DD>.dump`, one per day.
  A second dump on the same day (a restart) replaces that day's file.
- **Rotation:** the 30 newest `wishlist_*.dump` files are kept, the rest
  deleted after each successful dump. Other names in the directory are never
  deleted.
- **Access:** the directory is `999:999` mode 700 and each dump 600. The
  dumps hold every user's data, so the deploy user cannot read or even list
  them: use `sudo`.
- **Health:** the service's healthcheck fails when no dump is newer than 26
  hours. It is the [daily check](#daily-check).

**[VPS]** Common commands:

```bash
sudo ls -l /opt/wishlist/backups/                                   # the dumps
docker compose -f /opt/wishlist/docker-compose.yml logs --tail 20 backup
docker compose -f /opt/wishlist/docker-compose.yml restart backup  # dump now (replaces today's file)
```

**When `backup` is `unhealthy`:** read its logs. Likely causes: the password
in `/opt/wishlist/.env` no longer matches the database
([step 5](#5-env-files)), a full disk, or the backups directory's owner or
mode changed (it must be `999:999` 700). Once fixed, `restart backup` dumps
at once and the service turns healthy within a minute.

**[VPS → dev]** Copying a dump off the host. Copy it to the deploy user's home
with `sudo`, download it, delete the copy:

```bash
sudo install -o "$(id -un)" -g "$(id -un)" -m 600 \
    /opt/wishlist/backups/wishlist_<YYYY-MM-DD>.dump ~/
```

```powershell
scp <deploy-user>@<vps-host>:wishlist_<YYYY-MM-DD>.dump $HOME\
```

```bash
rm ~/wishlist_<YYYY-MM-DD>.dump
```

Keep it outside the repository checkout (`*.dump` is gitignored, but a dump
is every user's data) and delete it when done.

The dumps never leave the VPS by themselves. Losing the VPS, its disk or OVH's
datacenter loses them with the database: off-site copies are an
[open item](#open-items).

Rotation counts dumps, not days: after a backup outage of several nights the
30 kept dumps reach further back than 30 days. Review finding R2-5 (deferred
to the gifts feature) is about matching the media purge to that.

## Media

Uploaded files (gift images, `docs/NEEDS.md`) are on disk, one directory per
environment (D18):

| Environment | Host directory | In the container |
|---|---|---|
| PROD | `/opt/wishlist-media/prod` | `/app/media` |
| VAL | `/opt/wishlist-media/val` | `/app/media` |

Both are owned by `10001:10001` (the app's fixed uid) with mode 750, created
in [step 4](#4-directories-and-files). If an app's `/api/health` reports
`"media": "not writable"`, the ownership changed: put it back with
`sudo chown 10001:10001 /opt/wishlist-media/prod` (or `val`). The image sets
`MEDIA_DIR=/app/media` and no `.env` may override it, or uploads would land in
the container and vanish on the next `up -d`.

The binding rules for the feature that writes them: a file is named by its
content hash and never modified; deleting a gift only removes the database
reference; a file is purged only after being unreferenced for longer than the
dump retention.

**What that protects against:** logical errors. A bad migration, a bug that
deletes gifts, an accidental deletion through the app: restoring any kept
dump finds every file it references, without keeping 30 copies of the images.

**What it does not protect against:**

- Losing the VPS or its disk: the media, like the dumps, are on the same
  disk. Off-site copies are an [open item](#open-items).
- Deleting or changing files on the host by hand, or a bug in the future purge
  itself.
- A full disk: there is no per-account limit yet. Free space is part of the
  [daily check](#daily-check).

The deploy user cannot list these directories (mode 750, another owner). To
see their size: `sudo du -sh /opt/wishlist-media/prod /opt/wishlist-media/val`.
In one `du` run, a file hard-linked into both (by seeding) is counted once.

## Restoring PROD from a dump

This replaces PROD's database with a dump's content. Everything written since
that dump is lost. PROD is down from step 1 to step 4. Media need no step:
files are never modified and purged late, so every file a kept dump references
is still there (D18; see R2-5 above).

**[VPS]**

```bash
cd /opt/wishlist
sudo ls -l backups/                                  # choose wishlist_<YYYY-MM-DD>.dump

# 1. Nothing writes to the database any more.
docker compose stop app backup

# 2. Keep the current state, whatever it is, under a name the rotation never deletes.
docker compose run --rm --no-deps -T --entrypoint sh backup -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
         -f /backups/before-restore.dump && chmod 600 /backups/before-restore.dump'

# 3. An empty database, then the dump restored into it in one transaction.
docker compose exec -T -u postgres db sh -c '
    dropdb -U "$POSTGRES_USER" --force "$POSTGRES_DB" &&
    createdb -U "$POSTGRES_USER" -O "$POSTGRES_USER" "$POSTGRES_DB"'
docker compose run --rm --no-deps -T --entrypoint cat backup /backups/wishlist_<YYYY-MM-DD>.dump |
    docker compose exec -T -u postgres db sh -c '
        pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            --no-owner --no-privileges --exit-on-error --single-transaction'

# 4. The app migrates the restored database to its own head on start.
docker compose up -d --wait --wait-timeout 300
curl -s http://127.0.0.1:8010/api/health; echo
```

The single-quoted variables are expanded inside the containers, from `.env`.
The dumps are read in a one-shot container of the `backup` service, which runs
as uid 999, their owner. These are the same commands `seed-from-prod.sh` runs
for VAL, which the smoke test and every seed exercise.

If step 3's `pg_restore` fails, the database is left empty (one transaction).
Restore `before-restore.dump` the same way to get back to where you started.
Delete `before-restore.dump` (`sudo rm`) once PROD is confirmed good; it is not
rotated.

Step 4 starts the `backup` service, which dumps at once and replaces today's
`wishlist_<YYYY-MM-DD>.dump`. If today's 02:00 dump may still be needed,
copy it under another name before step 4:
`sudo cp -p backups/wishlist_<YYYY-MM-DD>.dump backups/kept_<YYYY-MM-DD>.dump`.

If the running image is older than the dump's Alembic revision, the app starts
without migrating and logs the `app.migrate` warning (see
[Rollback](#rollback), with the same limit for images older than
`app.migrate`). Restoring an older dump with the current image is fine: the
migrations bring it forward.

## Seeding VAL from PROD

`/opt/wishlist-val/seed-from-prod.sh` replaces VAL's database with PROD's
newest dump and hard-links PROD's media files into VAL's directory (D9, D18).
It is also the regular proof that PROD's dumps restore.

**VAL's image may be older than PROD's database.** VAL's app then starts
without migrating and logs the `app.migrate` warning described in
[Rollback](#rollback); it serves PROD's data on the newer schema (D15). The
next `validation` build that contains the release PROD runs migrates it as
usual. To validate on the same schema as PROD, deploy VAL's image first: the
`validation` tag must contain the release PROD runs.

**[dev]**

```powershell
git fetch origin --tags --force
git merge-base --is-ancestor <release> validation && echo "VAL is at or after <release>"
```

If nothing is printed and you want VAL on PROD's schema, move the `validation`
tag forward
(`git tag -f validation origin/master; git push origin validation --force`)
and wait for the webhook's `SUCCESS` in `deploy.log` first.

An image older than `app.migrate` (built before the accounts plan) still stops
at start with "Can't locate revision" against a newer database, and VAL stays
down: with such an image on VAL, deploy VAL's image first.

**[VPS]** Run it as the deploy user, never as root:

```bash
/opt/wishlist-val/seed-from-prod.sh
```

What it does, and what to expect:

- It finds the newest `wishlist_*.dump` first; with none, it changes nothing
  and exits 1. For a fresher dump, `restart backup` in `/opt/wishlist` first.
- VAL is down from the moment its database is dropped until the end, and
  everything written to VAL since the last seed is lost.
- PROD's role does not exist in VAL (its own role and password, D2):
  objects are restored with `--no-owner --no-privileges` and belong to
  VAL's role.
- Media: PROD's files are hard-linked (no extra disk; safe because files are
  never modified), by uid 10001 in a one-shot container that mounts
  `/opt/wishlist-media` once. Files VAL already has are kept.
- It ends with `done: VAL is up on wishlist_<YYYY-MM-DD>.dump`, after VAL's
  app migrated the database and reported healthy.

If it fails, it says `FAILED: VAL may be left stopped`. Fix the cause and run
it again. To bring VAL back empty instead:
`docker compose -f /opt/wishlist-val/docker-compose.yml up -d`.

## Later releases

**[dev]**

1. Tag and push: `git tag <release> origin/master; git push origin <release>`.
   Release numbers follow `CLAUDE.md`: `x.y.z`, `y` for features, `z` for
   patches.
2. If `deploy/` changed since the release PROD runs, update the host's files
   first (below): `git diff --stat <previous-release> <release> -- deploy/`.
3. `.\deploy.ps1 -Target Prod` once the build has finished. It refuses an
   image that is not the newest `vX.Y.Z` tag, which also catches a build still
   running.

`deploy.ps1` never runs `docker compose down`: the old containers keep serving
during the pull, so a failed pull leaves PROD as it was. A failed check after
`up -d` leaves the containers as they are, for inspection.

### Updating the files on the host

`deploy.ps1` and the webhook only pull images. Changes to the compose files,
the backup scripts, `seed-from-prod.sh` or the webhook files reach the VPS
only by hand.

**[VPS]** Fetch them at the release (step 2 with `REF=<release>`), compare,
install the changed ones with the same modes as in step 4, then apply:

```bash
diff -u /opt/wishlist/docker-compose.yml "$SRC/deploy/prod/docker-compose.yml"
install -m 644 "$SRC/deploy/prod/docker-compose.yml" /opt/wishlist/
```

| Changed | Then |
|---|---|
| a compose file | `docker compose up -d --wait` in its directory (recreates what changed), with the [cluster check](#checking-the-database-cluster-is-unchanged) before and after. A Postgres **patch or minor** bump (Dependabot) is just this; a **major** one is [below](#postgres-major-upgrade). |
| `deploy/backup/*.sh` | `docker compose restart backup` in `/opt/wishlist` (it reads the script on start) |
| `deploy/webhook/deploy-validation.sh` | nothing: read on each delivery |
| `deploy/webhook/hooks.yaml.example` | re-create `hooks.yaml` as in step 7, keeping the secret: `SECRET=$(sed -n 's/^ *secret: "\(.*\)"$/\1/p' hooks.yaml)` first, then `sudo systemctl restart wishlist-webhook` |
| `deploy/webhook/wishlist-webhook.service` | install it as in step 7, then `sudo systemctl daemon-reload && sudo systemctl restart wishlist-webhook` |
| `deploy/caddy/Caddyfile.snippet` | edit the Wishlist blocks in `/etc/caddy/Caddyfile` by hand, then `caddy validate` before the reload, as in step 6 |
| an `.env.example` | compare with the host's `.env` and add what is new; `docker compose up -d` |

#### Checking the database cluster is unchanged

For any compose file change, prove that the same Postgres cluster still
serves. Its system identifier changes only when a new cluster is created.

1. **[VPS]** In the compose file's directory, before applying, record the value:

   ```bash
   docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "select system_identifier from pg_control_system()"'
   ```

2. Run `docker compose up -d --wait`.
3. Run the same command again and compare. If the value changed, stop and
   follow [If it happened anyway](#if-it-happened-anyway).

## Rollback

PROD runs `:latest`, which only ever moves forward. Going back means pointing
the host's compose file at the previous release's tag, by hand: `deploy.ps1`
only deploys the newest release.

**Safe one version back (D15), across a migration too.** Every migration
keeps the previous release working (expand now, contract in a later release),
so the previous image can run on the newer schema without `alembic downgrade`.
A release that cannot follow this says so in its plan and here; do not roll
back across it.

The image's entrypoint runs `python -m app.migrate` (accounts plan D13). When
the database is at a revision the image does not know, which is what a
rollback across a migration leaves, it does not migrate and logs one line:

```text
WARNING [app.migrate] database at revision …, unknown to this image (head …): starting without migrating; see docs/DEPLOYMENT.md Rollback
```

The first revision is the database's, the second the newest one the image
has. The app then starts and serves on the newer schema; the database is left
as it is, nothing is downgraded. This line is expected after a rollback, or on
VAL after [seeding](#seeding-val-from-prod) from a PROD that runs a newer
release. The next forward release knows the database's revision again and
migrates as usual. Seen at any other time, it means the host runs an older
image than intended: compare `/api/version` with the release you deployed.

**Not to an image older than `app.migrate`.** Images built before the
accounts plan run `alembic upgrade head`, which stops with "Can't locate
revision" against a database migrated by a newer release: the app restarts in
a loop. Check that the release you go back to has it:

```powershell
git cat-file -e <previous-release>:server/app/migrate.py   # prints nothing when it has it
```

If it prints an error, roll back to it only across releases that added no
migration:

```powershell
git diff --name-only <previous-release> <release> -- server/alembic/versions   # must print nothing
```

If that prints a file, do not roll back: fix forward with a new release.

**[VPS]**

```bash
cd /opt/wishlist
sed -i 's#ghcr.io/rui-nar/wishlist:latest#ghcr.io/rui-nar/wishlist:<previous-release>#' docker-compose.yml
grep -n 'image: ghcr.io' docker-compose.yml          # :<previous-release>
docker compose pull app
docker compose up -d --wait --wait-timeout 300
curl -s http://127.0.0.1:8010/api/version; echo      # <previous-release>
```

**Afterwards, before the next deploy,** point the compose file back to
`:latest`. Otherwise the next `deploy.ps1 -Target Prod` stops with
"does not run ghcr.io/rui-nar/wishlist:latest" (before touching anything):

```bash
sed -i 's#ghcr.io/rui-nar/wishlist:<previous-release>#ghcr.io/rui-nar/wishlist:latest#' /opt/wishlist/docker-compose.yml
```

Do this as part of deploying the fixed release, not earlier: `:latest` is
still the bad release until the fix is built.

VAL follows the `validation` tag. To take it back, move the tag to an older
commit; the same limits apply (D15, and an image without `app.migrate`), and
[seeding](#seeding-val-from-prod) resets it anyway.

## Postgres major upgrade

The Postgres image is pinned to one exact version everywhere (D2), and a
major version moves only by hand (D16): Dependabot ignores majors. The volume is
mounted at `/var/lib/postgresql`, the parent of the per-major data directory,
so a new major finds its own empty data directory there and silently starts an
empty database instead of refusing to start; this is why majors are never
bumped by a plain compose change ([if it happened anyway](#if-it-happened-anyway)). The procedure is dump, new
volume, restore. Upgrade VAL first: its seed from PROD's dump into the new
major is the rehearsal of PROD's restore.

**[dev]** One pull request moves the image tag to `postgres:<new-major>.x` in
`docker-compose.dev.yml`, `deploy/prod/docker-compose.yml`,
`deploy/val/docker-compose.yml` and the service image in
`.github/workflows/test.yml`; CI (including the smoke test) passes on it.
Release it. On the dev machine, `.\dev.ps1 -Reset` recreates the dev volume
on the new major (dev data is lost; see `docs/DEVELOPMENT.md`).

**[VPS]** Fetch the files at that release (step 2 with `REF=<release>`).

**[VPS]** VAL (its data is disposable):

```bash
cd /opt/wishlist-val
docker compose down                                   # never -v here: see PROD
docker volume rm wishlist-val_pgdata
install -m 644 "$SRC/deploy/val/docker-compose.yml" /opt/wishlist-val/
docker compose up -d --wait --wait-timeout 300        # first boot on <new-major>
./seed-from-prod.sh                                   # PROD's <old-major> dump into <new-major>
```

**[VPS]** PROD. Down from step 1 to step 5:

```bash
cd /opt/wishlist

# 1. Nothing writes; a final dump under a name the rotation never deletes.
docker compose stop app backup
docker compose run --rm --no-deps -T --entrypoint sh backup -c \
    'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
         -f /backups/before-pg<new-major>.dump && chmod 600 /backups/before-pg<new-major>.dump'
sudo ls -l backups/before-pg<new-major>.dump

# 2. Keep the old data directory, in a copy of the volume, until the new one has proven itself.
docker compose down                                   # containers only; NEVER `down -v`
docker volume create wishlist-prod_pgdata-pg<old-major>
docker run --rm --entrypoint cp \
    -v wishlist-prod_pgdata:/from:ro -v wishlist-prod_pgdata-pg<old-major>:/to \
    postgres:<old-postgres-tag> -a /from/. /to/
docker volume rm wishlist-prod_pgdata

# 3. The new compose file (the old one kept for going back); Postgres boots on
#    an empty volume with the .env credentials.
cp -p docker-compose.yml docker-compose.yml.pg<old-major>
install -m 644 "$SRC/deploy/prod/docker-compose.yml" /opt/wishlist/
docker compose up -d --wait --wait-timeout 300 db

# 4. The final dump restored into it.
docker compose run --rm --no-deps -T --entrypoint cat backup /backups/before-pg<new-major>.dump |
    docker compose exec -T -u postgres db sh -c '
        pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
            --no-owner --no-privileges --exit-on-error --single-transaction'

# 5. The app and the backup.
docker compose up -d --wait --wait-timeout 300
curl -s http://127.0.0.1:8010/api/health; echo
docker compose ps                                     # app, db, backup: (healthy)
```

In step 2, `postgres:<old-postgres-tag>` is the image PROD ran until now
(already on the host); the copy runs as the image's root, the one place this
runbook runs a container as root, to keep the files' owners. Step 3's empty
database is created by the image from `POSTGRES_*` in `.env`, so step 4 needs
no `createdb`. A newer `pg_restore` reads an older major's dump.

**Going back** (if step 3 or 4 fails):

```bash
cd /opt/wishlist
docker compose down
docker volume rm wishlist-prod_pgdata
docker volume create wishlist-prod_pgdata
docker run --rm --entrypoint cp \
    -v wishlist-prod_pgdata-pg<old-major>:/from:ro -v wishlist-prod_pgdata:/to \
    postgres:<old-postgres-tag> -a /from/. /to/
install -m 644 docker-compose.yml.pg<old-major> docker-compose.yml
docker compose up -d --wait --wait-timeout 300
```

Once PROD has run on the new major for a while and the nightly dumps are
healthy: `docker volume rm wishlist-prod_pgdata-pg<old-major>`,
`rm docker-compose.yml.pg<old-major>` and
`sudo rm /opt/wishlist/backups/before-pg<new-major>.dump`.

### If it happened anyway

If a Postgres major was changed by a plain compose change, the
[system identifier check](#checking-the-database-cluster-is-unchanged) shows a different
value after `up -d --wait`, and `/api/health` is 200 all the same: the app
migrated an empty schema and serves an empty database. Writes users make in
that state land in the new cluster and are lost when the old one is put back.
Recovery: put the previous exact image tag back in the compose file and run
`docker compose up -d --wait`. The old cluster is untouched in the volume
(unless the volume was removed).

## The webhook: pausing and troubleshooting

**Pausing:** `sudo systemctl stop wishlist-webhook` (resume with `start`).
Deliveries then fail with a 502 and nothing deploys; redeliver the last
`completed` delivery after starting it if VAL should catch up. To stop GitHub
sending anything, untick **Active** on the webhook instead.

**Watching:**

```bash
tail -f /opt/wishlist-val/webhook/deploy.log
sudo journalctl -u wishlist-webhook -f
```

GitHub's Recent Deliveries shows each response:

| Response | Meaning |
|---|---|
| 502 | Caddy cannot reach `127.0.0.1:9998`: `systemctl status wishlist-webhook`. |
| 404 `Hook not found.` | `hooks.yaml` did not load (the journal says why), or the URL path is wrong. |
| 500 `Error occurred while evaluating hook rules.` | Signature mismatch: GitHub's secret and `hooks.yaml`'s differ, or `hooks.yaml` still has the empty secret. |
| 200 `Hook rules were not satisfied.` | Signature fine, a field did not match. Expected for `ping`, `requested`, `in_progress`, failed builds and `v*` builds. On a successful `completed` validation build: compare the payload with the rules (`repository.full_name` after a rename, the workflow name, the content type). |
| 200 `Deploying validation...` | The script started. The outcome is in `deploy.log`, not in GitHub. |

In `deploy.log`, `FAILED <short sha>: ... reports 'validation-...'` with another sha
usually means a newer `validation` build was pushed meanwhile; its own
delivery follows and logs `SUCCESS`. `reports 'no version'` means VAL did not
answer within 5 minutes:
`docker compose -f /opt/wishlist-val/docker-compose.yml logs app`.
`FAILED <short sha>: docker compose pull` is usually the GHCR login
([step 3](#3-the-ghcr-package)).

## Definition of done

Each item of the plan's Definition of done, and where it is checked:

| Definition-of-done item | Checked by |
|---|---|
| `.\dev.ps1` serves the client against a local Postgres; `.\dev.ps1 -Test` passes | [DEVELOPMENT](DEVELOPMENT.md): First run, Tests |
| The `deploy-smoke` workflow passes | [Checks before installing](#checks-before-installing), last item |
| A pull request runs server and client tests in CI against PostgreSQL | the `Tests` workflow on any pull request ([checks](#checks-before-installing)) |
| Pushing `validation` publishes `:validation` and `https://<val-host>/api/version` reports `validation-<short sha>` within 5 minutes with no manual step | [8. First VAL deploy](#8-first-val-deploy) |
| Pushing `v0.1.0` publishes `:latest`, `:<sha>`, `:v0.1.0`; `deploy.ps1 -Target Prod` reports `v0.1.0` and `/api/health` 200 with `media: ok` | [9. First PROD release](#9-first-prod-release) |
| `docker ps` shows no Wishlist port outside `127.0.0.1` and no Postgres port published | [10. Verifying](#10-verifying-the-installation), first block |
| TraxJourney prod and val answer `/api/version` as before throughout | [6. Caddy](#6-caddy) after the reload, and [10. Verifying](#10-verifying-the-installation) |
| A nightly dump exists after the first night; at most 30 kept; `backup` healthy; seeding VAL from it succeeds | the day after step 9: `sudo ls -l /opt/wishlist/backups/` shows a dump written at 02:00 UTC, the [daily check](#daily-check) shows `backup` healthy, then [Seeding VAL](#seeding-val-from-prod). The rotation to 30 is proven by the smoke test (31 old dumps, 30 kept). |
| `docker stats` shows Wishlist's containers within their limits (about 1 GB) | [10. Verifying](#10-verifying-the-installation), memory |
| No secret, host name or key is committed | [10. Verifying](#10-verifying-the-installation), last block |

## Open items

- [ ] **Domain and hostnames** for PROD and VAL. Needed for [step 6](#6-caddy)
      onwards, including the Google sign-in origins of
      [step 11](#11-google-sign-in).
- [ ] **Off-site backups** of the dumps **and** the media directory (shared
      problem with TraxJourney). Today both are lost with the VPS, its disk or
      OVH's datacenter. Needed before PROD holds real users' data.
- [ ] **Observability**: logs and metrics for VAL and PROD (reusing
      TraxJourney's Loki/Prometheus on the NAS is the candidate). A later plan;
      until then, the [daily check](#daily-check) and `docker compose logs`.
- [ ] **Access logs contain client IPs.** uvicorn logs every request with the
      client's address (taken from `X-Forwarded-For`, which is why
      `FORWARDED_ALLOW_IPS` matters), into Docker's json-file logs (3 × 10 MB
      per container). Personal data: retention and purpose need a decision
      before real users.
- [x] **R2-2, rollback and seeding across a migration**: fixed by
      `app.migrate` (accounts plan D13); see [Rollback](#rollback) and
      [Seeding VAL](#seeding-val-from-prod). Images older than it still
      cannot start against a newer database.
- [ ] **R2-5, media purge vs. dump retention** (deferred): the purge rule must
      be stated relative to the oldest kept dump when the gifts feature
      implements it.
- [ ] **Memory on a shared 4 GB host.** Wishlist's limits keep its own
      containers in bounds, but a TraxJourney peak can still exhaust the host.
