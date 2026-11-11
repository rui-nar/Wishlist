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
| `<prod-host>` | PROD's public hostname (for now a subdomain of TraxJourney's domain, until Wishlist has its own) |
| `<top-private-domain>` | The registered domain that `<val-host>` and `<prod-host>` are subdomains of |
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
| `<brevo-api-key>` | an API key of the Brevo account that sends Wishlist's emails ([Release-specific steps](#release-specific-steps)). Secret: pasted at a prompt, never typed into a command or committed |
| `<sender-address>` | the address emails come from, a sender verified in that Brevo account. Never committed |
| `<owner-address>` | the owner's own email address, the one their account on VAL signs in with. Never committed |
| `<stripe-secret-key>` | the secret API key of the Stripe sandbox (VAL) or of the live account (PROD), `sk_test_…` or `sk_live_…`. Secret: pasted at a prompt, never typed into a command or committed |
| `<stripe-webhook-secret>` | the signing secret Stripe shows for a webhook endpoint, `whsec_…`, a different one per endpoint. Secret, handled like the key |
| `<stripe-price-id>` | the id of Wishlist's yearly price, `price_…`, which belongs to one Stripe account and mode. Never committed |
| `<price-amount>` | that price's amount in major units, as it is in Stripe: digits, a dot, two decimals. Never committed |
| `<apple-services-id>` | the identifier of Wishlist's Services ID in Apple Developer, in reverse-domain form ([step 12](#12-apple-sign-in)). Public, not a secret, but never committed |
| `<ios-bundle-id>` | the bundle ID of the PROD iOS app, registered as an App ID ([step 12](#12-apple-sign-in)), and Android's PROD application id too ([step 13](#the-bundle-id)). Never committed |
| `<ios-bundle-id-val>` | the bundle ID of the VAL iOS app, `<ios-bundle-id>.val` ([step 13](#the-bundle-id)). Never committed |
| `<apple-team-id>` | the 10-character Team ID of the Apple Developer membership ([step 13](#the-sign-in-with-apple-key)). Not a secret, but never committed |
| `<apple-key-id>` | the 10-character ID of the Sign in with Apple key; its file is `AuthKey_<apple-key-id>.p8`, a secret ([step 13](#the-sign-in-with-apple-key)). Never committed |
| `<asc-key-id>`, `<asc-issuer-id>` | the ID and the issuer ID of the App Store Connect API key; its file is `AuthKey_<asc-key-id>.p8`, a secret ([step 13](#the-app-store-connect-api-key)). Never committed |
| `<apple-product-id>` | the id of the yearly subscription, the same in both apps ([Billing, Part 3](BILLING.md#2-create-the-subscription-in-each-app)). Never committed |
| `<apple-iap-issuer-id>`, `<apple-iap-key-id>` | the issuer ID and the key ID of an In-App Purchase key; its file is `SubscriptionKey_<apple-iap-key-id>.p8`, a secret ([Billing, Part 3](BILLING.md#3-create-the-in-app-purchase-key)). Never committed |
| `<apple-app-apple-id>` | the PROD app's Apple ID in App Store Connect, digits only ([Billing, Part 3](BILLING.md#9-fill-in-prod)). Never committed |
| `<demo-account-id>`, `<demo-account-address>` | the id and the address of the account given to Apple's review ([Billing, Part 3](BILLING.md#6-create-the-app-review-demo-account)). Never committed |
| `<google-ios-client-id>`, `<google-ios-client-id-val>` | the IDs of the PROD and VAL apps' iOS OAuth clients, one per bundle id, ending in `.apps.googleusercontent.com` ([step 13](#google-ios-oauth-client)). Public, not secrets, but never committed |
| `<android-application-id>` | the Android applicationId of the PROD app, the same value as `<ios-bundle-id>` ([step 14](#the-two-apps)); it is also what the PROD server's `APPLE_ANDROID_PACKAGE` holds ([step 12](#12-apple-sign-in), [step 11](#android-oauth-client)). Never committed |
| `<android-application-id-val>` | the Android applicationId of the VAL app, `<android-application-id>.val` ([step 14](#the-two-apps)); the VAL server's `APPLE_ANDROID_PACKAGE`. Never committed |
| `<upload-key-sha1>`, `<play-signing-sha1>`, `<play-signing-sha1-val>`, `<debug-sha1>` | the SHA-1 fingerprints of the upload key, the PROD and the VAL app's Play App Signing keys, and a dev machine's debug key ([step 11](#android-oauth-client)). Never committed |
| `<play-upload-service-account-email>`, `<play-server-service-account-email>`, `<pubsub-push-service-account-email>` | the email addresses of the service accounts that upload builds ([step 14](#the-service-account-for-uploads)), read subscriptions for the server ([Billing, Part 4](BILLING.md#3-create-the-servers-service-account)) and sign the Pub/Sub push ([Billing, Part 4](BILLING.md#4-create-the-pubsub-topic-and-the-push-subscription)). Never committed |
| `<service-account-key-file>` | the downloaded JSON key of a service account, a secret. Never committed |
| `<google-product-id>` | the id of the yearly Google Play subscription, the same in both apps ([Billing, Part 4](BILLING.md#2-create-the-subscription-in-each-app)). Never committed |
| `<gcp-project-id>`, `<pubsub-topic>` | the id of Wishlist's Google Cloud project and the id of an environment's Pub/Sub topic ([Billing, Part 4](BILLING.md#4-create-the-pubsub-topic-and-the-push-subscription)). Never committed |
| `<owner-account-id>` | the id of the owner's own Wishlist account, for `GOOGLE_PLAY_TEST_ACCOUNT_IDS` ([Billing, Part 4](BILLING.md#9-fill-in-prod-for-android)). Never committed |
| `<account-address>` | the email address of an account, when it has to be looked up. Never committed |
| `<user-id>` | an account's id, printed by the query that looked it up |
| `<admin-user-id>` | the id of the account that is admin, found in [Admin](#admin). Never committed |
| `<entitlement-id>` | the row id in a log line `entitlement past its grace` |
| `<subscription-id>`, `<customer-id>`, `<event-id>`, `<webhook-endpoint-id>`, `<test-clock-id>`, `<good-card-id>`, `<failing-card-id>` | Stripe's ids, shown in its dashboard or printed by the command that creates them. Never committed |

Four placeholders are also the literal text of files in `deploy/`:
`<prod-host>` and `<val-host>` in `Caddyfile.snippet`, `<deploy-user>` in
`wishlist-webhook.service`, and `<postgres-password>` in the `.env.example`
files. Inside the `sed` and `grep` patterns that fill in or check those files
(each marked `# literal placeholder`), leave them as they are.

Commands are marked **[VPS]** (bash, logged in as `<deploy-user>`),
**[dev]** (PowerShell in the repository checkout on the Windows dev machine),
**[GitHub]** (the web UI of `rui-nar/Wishlist`), **[Brevo]** (the console of
the Brevo account that sends the emails), **[Stripe]** (the dashboard of the
Stripe account selling Wishlist: a sandbox for VAL, live mode for PROD),
**[Google Cloud]** (the Google Cloud console, in Wishlist's project) or
**[Apple]** (the Apple Developer account, at
<https://developer.apple.com/account/resources>, or App Store Connect, at
<https://appstoreconnect.apple.com>, as the step says) or **[Play]** (the
Google Play Console, at <https://play.google.com/console>).

## What Wishlist adds to the VPS

| Path or item | Owner | Mode | What |
|---|---|---|---|
| `/opt/wishlist/` | `<deploy-user>` | 755 | PROD: `docker-compose.yml` (644), `.env` (600) |
| `/opt/wishlist/backup/` | `<deploy-user>` | 755 | `backup.sh`, `healthcheck.sh` (644), mounted read-only into the `backup` service |
| `/opt/wishlist/backups/` | `999:10001` | 750 | the nightly dumps (600 each); uid 999 is the `postgres` user of the official image (D14); group 10001 lets PROD's app list them for the media purge, not read them ([Backups](#backups)) |
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
free -m                 # "available": more than 1150 MB
swapon --show
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'
df -h /                 # at least 5 GB available
docker system df
```

Wishlist's memory limits add up to 1088 MB (PROD app 320, PROD Postgres 256,
VAL app 256, VAL Postgres 192, backup 64). The app limits leave room for image
processing (gift images plan; measured idle ≈121 MB + ≈89 MB per image; idle
RSS measured in a Linux container, 2026-11-08, to be refined on VAL). Limits
are caps, not reservations, but if less than 1150 MB (the total plus a small
margin) is available with TraxJourney running, stop and decide first: a peak on either project would then push the host into swap or the
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
sudo install -d -o 999 -g 10001 -m 750 /opt/wishlist/backups
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
configured". `PUBLIC_BASE_URL` stays empty until Caddy serves the hosts
([step 6](#6-caddy)). Email stays off until its variables are filled in
([Release-specific steps](#release-specific-steps)): the app runs without
them. Billing stays off the same way ([Billing with Stripe](#billing-with-stripe)).
Never add `MEDIA_DIR` or `APP_VERSION`: the image sets both, and
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
sudo journalctl -u caddy -n 200 --no-pager | grep '"logger":"tls'   # "certificate obtained successfully" for both hosts
curl -sI https://<val-host>/ | head -n 1     # 502 until VAL runs (step 8); no TLS error
```

`NXDOMAIN` in those lines means the host has no DNS record yet: add it, and
Caddy retries on its own. The new names appear in the public certificate
logs within minutes, and scanners start probing them (`/.env`, `/.git/config`,
…): until the apps run, Caddy logs each probe as a 502 `connection refused`,
which is expected.

The VAL site routes `/gh-webhook/*` to the webhook on 9998 (with the prefix
stripped) and everything else to the app on 8011. PROD's site never exposes
the hook.

**[VPS]** Now that the hosts are served, give each app its public address,
which share links are built on (`<PUBLIC_BASE_URL>/join#<token>`). The web
client would fall back to its own address; the mobile apps cannot, and no
email is sent while it is empty:

```bash
# literal placeholder: <val-host>, <prod-host> are this document's, replace them
cd /opt/wishlist-val
grep -n '^PUBLIC_BASE_URL=' .env        # PUBLIC_BASE_URL= (empty)
sed -i 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://<val-host>|' .env
cd /opt/wishlist
grep -n '^PUBLIC_BASE_URL=' .env
sed -i 's|^PUBLIC_BASE_URL=.*|PUBLIC_BASE_URL=https://<prod-host>|' .env
```

If `grep` prints nothing, the `.env` predates this setting: add the line
from `.env.example` first. The apps pick it up when they start (step 8 for
VAL, step 9 for PROD); one already running needs `docker compose up -d`
in its directory. Check with `curl -s https://<val-host>/api/config`:
`"public_base_url":"https://<val-host>"`.

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
tail -F /opt/wishlist-val/webhook/deploy.log
```

`-F` waits for the file: the script creates it on its first delivery.

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

**[VPS]** Memory within the limits (about 1.1 GB in total):

```bash
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' | grep -E 'NAME|wishlist'
free -m
```

Each `MemUsage` reads `used / limit`, with limits 320 MiB (PROD app), 256 MiB (PROD db and
VAL app), 192 MiB (VAL db) and 64 MiB (backup). An idle app reads about 121 MiB. A container that reaches its
limit is killed and restarted; it does not take memory from TraxJourney.

**[dev]** TraxJourney still answers, as it did before:

```powershell
curl.exe -s https://<traxjourney-prod-host>/api/version
curl.exe -s https://<traxjourney-val-host>/api/version
```

**[dev]** No secret was committed. Every secret generated here is 64 hex digits
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

### Everything to do in the Google Cloud console

All of it is in one project, at <https://console.cloud.google.com>. Google
sign-in is the only thing Wishlist uses there. Everything is free, and no API
has to be enabled. Details of rows 6 and 7 follow below.

| # | Where | What | When |
|---|---|---|---|
| 1 | Project selector → New project | One project for Wishlist. Its id can never change, so choose it as if it were public | Once |
| 2 | Google Auth Platform → Branding | App name `Wishlist`, a user support email, a developer contact email. **No logo**: a logo makes Google review the branding first | Once |
| 3 | Branding → Authorised domains | `<top-private-domain>`. Google requires it before accepting the origins of row 6 or the links of row 8 | Once, and again when Wishlist gets its own domain |
| 4 | Google Auth Platform → Audience | User type **External**. Add your own account under Test users | Once |
| 5 | Google Auth Platform → Data Access | Add nothing. Sign-in asks only for `openid`, `email` and `profile`, and any other scope changes what Google demands | Never |
| 6 | Google Auth Platform → Clients | The web client `Wishlist web`, with the origin of each environment ([below](#web-oauth-client)) | Once, then a line per environment |
| 7 | Google Auth Platform → Clients | One Android client per app and signing key ([below](#android-oauth-client)) | Once each app has its first upload to Play ([step 14](#14-android-app)); a debug client for a dev machine |
| 8 | Branding → App domain | Home page `https://<prod-host>/welcome`, privacy policy the address of `LEGAL_PRIVACY_URL`, terms of service the address of `LEGAL_TERMS_URL` | Before row 9 |
| 9 | Audience → **Publish app** | Status **In production**: open to any Google account | Before PROD serves the public |
| 10 | Verification Centre | Only for showing the name `Wishlist` or a logo on Google's screen. It needs the ownership of `<top-private-domain>` proven in Google Search Console | Optional |
| 11 | Google Auth Platform → Clients | Two iOS clients, one per iOS app's bundle id ([step 13](#google-ios-oauth-client)) | Once the bundle ids are chosen |

- **Row 8:** Google requires the home page to be public, to describe the app
  and to link the same privacy policy. The welcome page does not link a privacy
  policy yet, and needs one before you publish.
- **Row 9:** while the app is unverified, Google's screen shows the domain
  only, so people see `<top-private-domain>`, not `Wishlist`.
- **Testing status:** Google's documentation says an app asking only for
  `openid`, `email` and `profile` is not limited to its test users and its
  sign-ins do not expire, even in Testing. Keep your own account listed anyway.
- **A change to rows 2, 3 or 8 of a verified app** creates a draft that Google
  must verify again before it applies.

### Web OAuth client

If it does not exist yet, create it as in
[DEVELOPMENT](DEVELOPMENT.md#google-sign-in-in-dev), step 3.

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

The real application ids now exist, through the two flavours of the Android
app ([step 14](#14-android-app)): `<android-application-id-val>` for the VAL
app and `<android-application-id>` for the PROD app. Each client has one
package name and one SHA-1, so **each app needs several**, one per key that
can sign an installed copy:

| Key | Its SHA-1 | Known |
|---|---|---|
| Play App Signing key, which signs what Play delivers: the internal testers' installs and the public ones. A different one per app | `<play-signing-sha1-val>`, `<play-signing-sha1>` | After the app's first upload to Play |
| The upload key, which signs the bundle (the same key for both apps) | `<upload-key-sha1>` | Once the key is made ([step 14](#the-upload-key)) |
| The debug key of a dev machine, which signs `flutter run` | `<debug-sha1>` | At once, on each machine |

**[Play]** The Play App Signing key's SHA-1 is in the app's Test and release →
App integrity → App signing (the path is from memory and was not checked),
under the app signing key certificate. Take the SHA-1, not the SHA-256.

**[dev]** The upload key's and the debug key's SHA-1 (`keytool` comes with the
JDK Flutter uses):

```powershell
keytool -list -v -keystore $HOME\wishlist-upload.keystore -alias upload
keytool -list -v -keystore $HOME\.android\debug.keystore -alias androiddebugkey -storepass android
```

**[Google Cloud]** Google Auth Platform → Clients → Create client, once per
row of this table:

| Name | Package name | SHA-1 |
|---|---|---|
| `Wishlist Android VAL (Play)` | `<android-application-id-val>` | `<play-signing-sha1-val>` |
| `Wishlist Android VAL (upload)` | `<android-application-id-val>` | `<upload-key-sha1>` |
| `Wishlist Android (Play)` | `<android-application-id>` | `<play-signing-sha1>` |
| `Wishlist Android (upload)` | `<android-application-id>` | `<upload-key-sha1>` |
| `Wishlist Android debug` | the id of the build you run: `com.example.wishlist.val` with no `-P wishlistAppId`, or `<android-application-id-val>` with it | `<debug-sha1>` |

For all of them the application type is **Android**. Only the Play App Signing
row is needed for testers installing from Play; the upload row covers a bundle
installed another way, signed with the upload key. A client registered with
the old placeholder `com.example.wishlist` stops matching any build: replace
it with the debug row. A new client can take a few minutes to reach Google,
and none of these values goes in a file of the repository.

**[VPS]** `APPLE_ANDROID_PACKAGE` is the id of the Android app the server
hands Apple's sign-in back to, so each environment has its own: VAL's ends in
`.val`, PROD's does not. It follows [step 12](#12-apple-sign-in), which
filled it in with the build's id:

```bash
cd /opt/wishlist-val                     # VAL; PROD in /opt/wishlist with <android-application-id>
sed -i 's/^APPLE_ANDROID_PACKAGE=.*/APPLE_ANDROID_PACKAGE=<android-application-id-val>/' .env
grep -n '^APPLE_ANDROID_PACKAGE=' .env   # VAL: the id ending .val
docker compose up -d --wait --wait-timeout 300
```

**[dev]** None of it was committed:

```powershell
git grep -n -F -e <android-application-id> -e <play-signing-sha1> -e <upload-key-sha1> -e <debug-sha1>   # nothing
```

## 12. Apple sign-in

Apple sign-in is optional: without `APPLE_CLIENT_IDS` the Apple button is
absent and nothing else changes (Apple and email sign-in plan, D15 to D18).
VAL comes first. The server keeps only Apple's account id and the address; it
holds no Apple key.

**[Apple]** At <https://developer.apple.com/account/resources>:

1. **Enrol** in the Apple Developer Program (paid, yearly). Every step below
   stays in the **same team**: Apple's account id (`sub`) is per team, so
   another team would make every Apple user a new account.
2. Certificates, Identifiers & Profiles → Identifiers → **+** → App IDs → App:
   the app's bundle ID, `<ios-bundle-id>`. Tick **Sign in with Apple**.
3. Identifiers → **+** → Services IDs: a reverse-domain identifier,
   `<apple-services-id>`, and a description (people see it at sign-in).
   Register, then open it and tick **Sign in with Apple** → Configure:

   | Field | Value |
   |---|---|
   | Primary App ID | the one from step 2 |
   | Domains and Subdomains | `<val-host>` and `<prod-host>` (no scheme) |
   | Return URLs | `https://<val-host>/api/auth/apple/callback` and `https://<prod-host>/api/auth/apple/callback` |

   Save.
4. People who hide their address get a relay address, and Apple relays email
   only from registered senders. Certificates, Identifiers & Profiles →
   Services → **Sign in with Apple for Email Communication** → Configure: add
   the domain or the address of `EMAIL_SENDER_ADDRESS`, which must pass SPF.
   Otherwise their notifications bounce silently.

**[VPS]** Set the two values in the environment's `.env` (VAL first, then the
same in `/opt/wishlist`), then recreate the app. `<android-application-id>`
is the Android applicationId of the build:

```bash
cd /opt/wishlist-val                     # then the same in /opt/wishlist
grep -n '^APPLE_' .env                   # APPLE_CLIENT_IDS= and APPLE_ANDROID_PACKAGE= (empty)
sed -i 's/^APPLE_CLIENT_IDS=.*/APPLE_CLIENT_IDS=<apple-services-id>/' .env
sed -i 's/^APPLE_ANDROID_PACKAGE=.*/APPLE_ANDROID_PACKAGE=<android-application-id>/' .env
grep -n '^APPLE_' .env                   # both set
docker compose up -d --wait --wait-timeout 300
```

If `grep` prints nothing, the `.env` predates these settings: add the lines
from `.env.example` first ([Release-specific steps](#release-specific-steps)).
`docker compose restart` would not re-read `.env` ([step 5](#5-env-files)).

**[dev]** Check on VAL, then on PROD:

```powershell
curl.exe -s https://<val-host>/api/config    # "apple_client_id":"<apple-services-id>"
```

The sign-in page shows the Apple button. A first sign-in creates an account, a
second one finds it.

The iOS app adds its bundle ID to the comma-separated `APPLE_CLIENT_IDS`
([step 13](#apple-sign-in-for-the-app)). The first entry must stay the
Services ID, since `/api/config` hands it to the web and Android.

### Email sign-in

Sign-in by email and password follows the email turn-on steps of
[Release-specific steps](#release-specific-steps) (the release with comments
and email notifications) and needs nothing more. `NOTIFICATIONS_WORKER` must
stay on: the links it mails expire in an hour.

## 13. iOS app

The iOS app is built and signed on GitHub's macOS runners and delivered by
TestFlight (iOS app plan, D1 to D7). There are **two apps**: the VAL app,
"Wishlist VAL", built from the `validation` tag and talking to VAL, which
testers use; and the PROD app, built from a release tag and talking to PROD.
Until the secrets of [GitHub secrets and
variables](#github-secrets-and-variables) exist, the `iOS release` workflow
ends with a notice and builds nothing.

This step needs [step 12](#12-apple-sign-in) done first, at least on VAL: its
membership, its App ID and its Services ID.

### Enrolment

**[Apple]** The Apple Developer Program membership of [step
12](#12-apple-sign-in), point 1. Everything below stays in that **same
team**: Apple's account ids, the keys and the apps all belong to it. An
individual membership shows the owner's legal name as the seller on the App
Store; an organisation needs a D-U-N-S number. Nothing below can start before
Apple has accepted the enrolment.

### The bundle id

`<ios-bundle-id>` is the PROD app's identity, and **cannot change** once an
App Store Connect app uses it. Android uses the same value as its PROD
application id (`ANDROID_RELEASE_PLAN.md` D1), which cannot change once the
app is on Google Play either, so one choice serves both:

- reverse-domain, on a domain the owner controls for good, such as
  `<top-private-domain>` reversed, then `.wishlist`. Never the placeholder
  `com.example.wishlist`, which the release workflow refuses;
- lowercase letters, digits and dots only, each part starting with a letter:
  Apple forbids `_`, Android forbids `-`, and only this set is valid on both.

`<ios-bundle-id-val>` is `<ios-bundle-id>.val`, as Android's VAL app adds
`.val` to its application id.

### App IDs

**[Apple]** Certificates, Identifiers & Profiles → Identifiers. Register both
before the first run: Xcode's automatic signing would otherwise register a
missing one itself, with only the capabilities of the app's entitlements.

| | PROD | VAL |
|---|---|---|
| Identifier | `<ios-bundle-id>`, from [step 12](#12-apple-sign-in), point 2 | **+** → App IDs → App: `<ios-bundle-id-val>`, explicit |
| Description | `Wishlist` | `Wishlist VAL` |
| Sign in with Apple | ticked, **Enable as a primary App ID** | ticked, then Edit: **Group with an existing primary App ID**, the PROD one |
| In-App Purchase | ticked (Apple ticks it by default: check it) | ticked |

Nothing else: no push notifications, no associated domains (plan D8).

VAL is grouped with PROD because one Sign in with Apple key signs for its
primary App ID's group only, and VAL's server exchanges the codes of both the
Services ID (in PROD's group since step 12) and the VAL app. VAL and PROD
already share the Services ID, so the group adds nothing they did not share:
a person signs in to both with one Apple consent.

### Apple sign-in for the app

The native sheet's ID token is issued for the bundle id, not the Services ID,
so each server accepts its own app's bundle id. The server also exchanges
Apple's one-time code for the token it revokes when the account is deleted
(plan D5), which needs a key.

#### The Sign in with Apple key

**[Apple]** Certificates, Identifiers & Profiles:

1. Membership details (top right): the **Team ID**, `<apple-team-id>`.
2. Keys → **+**: name `Wishlist Sign in with Apple`, tick **Sign in with
   Apple** → Configure → Primary App ID: `<ios-bundle-id>`. Register.
3. Note the **Key ID**, `<apple-key-id>`, and **Download**
   `AuthKey_<apple-key-id>.p8`. Apple offers the file once only. Keep it in
   the password manager, never in the checkout.

One key serves both environments: both `.env` files are on the same host and
read by the same user, so a second key would separate nothing. If it leaks,
revoke it there (Keys → the key → Revoke), create another, and replace the
three values in both `.env`.

**[dev]** The key on one line, with each line break written `\n`, as the
`.env` takes it, copied to the clipboard (`'\n'` in single quotes is the two
characters, not a line break):

```powershell
(Get-Content $HOME\Downloads\AuthKey_<apple-key-id>.p8) -join '\n' | Set-Clipboard
```

#### The server's values

**[VPS]** Fill in VAL. `APPLE_CLIENT_IDS` gets the VAL app's bundle id after
the Services ID, which stays first. `APPLE_PRIVATE_KEY` is written with
`printf`, not `sed`: `sed` would turn its `\n` into line breaks.

```bash
cd /opt/wishlist-val
grep -n '^APPLE_' .env                   # APPLE_CLIENT_IDS=<apple-services-id>, APPLE_ANDROID_PACKAGE=…, then APPLE_TEAM_ID=, APPLE_KEY_ID=, APPLE_PRIVATE_KEY= (empty)
sed -i 's/^APPLE_CLIENT_IDS=.*/APPLE_CLIENT_IDS=<apple-services-id>,<ios-bundle-id-val>/' .env
sed -i 's/^APPLE_TEAM_ID=.*/APPLE_TEAM_ID=<apple-team-id>/' .env
sed -i 's/^APPLE_KEY_ID=.*/APPLE_KEY_ID=<apple-key-id>/' .env
read -rs APPLE_KEY                       # paste the key's one line, then Enter: nothing is shown or kept in the history
sed -i '/^APPLE_PRIVATE_KEY=/d' .env
printf 'APPLE_PRIVATE_KEY=%s\n' "$APPLE_KEY" >> .env
unset APPLE_KEY
grep -c '^APPLE_PRIVATE_KEY=-----BEGIN PRIVATE KEY-----\\n.*\\n-----END PRIVATE KEY-----$' .env   # 1
grep -E '^APPLE_(CLIENT_IDS|TEAM_ID|KEY_ID)=' .env                                              # the three, no secret
ls -l .env                               # -rw-------
docker compose up -d --wait --wait-timeout 300
docker compose logs app | grep 'Apple token revocation is off'                                  # nothing
```

A line printed by the last `grep` names what is missing or does not load as
a key. If the first `grep` shows no `APPLE_TEAM_ID`, the `.env` predates the
setting: add the three lines from `.env.example` first ([Release-specific
steps](#release-specific-steps)). The PEM form, with its real line breaks, also
works, but a `.env` value cannot hold it unquoted.

**[VPS]** PROD the same, before the first PROD build, in `/opt/wishlist` with
`<ios-bundle-id>`:

```bash
sed -i 's/^APPLE_CLIENT_IDS=.*/APPLE_CLIENT_IDS=<apple-services-id>,<ios-bundle-id>/' .env
```

**[dev]** `/api/config` still hands out the Services ID:

```powershell
curl.exe -s https://<val-host>/api/config    # "apple_client_id":"<apple-services-id>"
```

**[dev]** None of it was committed:

```powershell
git grep -n -F -e <ios-bundle-id> -e <apple-team-id> -e <apple-key-id>   # nothing
```

### App Store Connect

**[Apple]** At <https://appstoreconnect.apple.com>, Apps → **+** → New App,
once per app:

| Field | PROD | VAL |
|---|---|---|
| Platforms | iOS | iOS |
| Name | `Wishlist` | `Wishlist VAL` |
| Primary language | English | English |
| Bundle ID | `<ios-bundle-id>` | `<ios-bundle-id-val>` |
| SKU | `wishlist-prod` | `wishlist-val` |
| User Access | Full Access | Full Access |

An App Store name is unique across the store, even for an app never
released: if one is taken, add a word; the name under the icon comes from the
build, not from here. The VAL app is never submitted for review: it lives in
TestFlight only.

Create the PROD app before the first release tag after the secrets below: a
release tag then builds the PROD app, and its upload fails without it.

#### The App Store Connect API key

The workflow signs with **automatic signing and cloud-managed certificates**:
Xcode asks Apple for the certificate and the profile with this key at each
run, and no certificate is kept anywhere. Apple lets a team API key use
cloud-managed distribution certificates only with the **Admin** role: with
App Manager or Developer, the run fails with a cloud signing permission
error. If Apple's page on cloud-managed certificates names another role when
you read it, follow Apple's page.

**[Apple]** Users and Access → Integrations → App Store Connect API → Team
Keys. The first time, **Request Access**, which the Account Holder accepts.
Then **+**:

1. Name `GitHub iOS release`, Access **Admin**. Generate.
2. Note the **Issuer ID** above the list, `<asc-issuer-id>`, and the key's
   **Key ID**, `<asc-key-id>`.
3. **Download** `AuthKey_<asc-key-id>.p8`, offered once only. It goes into
   GitHub below, then into the password manager, never into the checkout.

An Admin key can do nearly anything in App Store Connect. It lives in the
repository's secrets only, which no pull request's workflow reads. If it
leaks, revoke it on this page and create another.

### GitHub secrets and variables

The release workflow reads these from the repository (Settings → Secrets and
variables → Actions), not from an environment. It starts when the first four
of the table exist, and fails, naming what is missing, when only some of them
do: set them all in one sitting, before any tag is pushed.

| Name | Kind | Value |
|---|---|---|
| `ASC_KEY_ID` | secret | `<asc-key-id>` |
| `ASC_ISSUER_ID` | secret | `<asc-issuer-id>` |
| `ASC_KEY_P8` | secret | the whole content of `AuthKey_<asc-key-id>.p8`, its line breaks included |
| `APPLE_TEAM_ID` | variable | `<apple-team-id>` |
| `IOS_BUNDLE_ID` | variable | `<ios-bundle-id>` |
| `IOS_BUNDLE_ID_VAL` | variable | `<ios-bundle-id-val>`; the workflow refuses it equal to `IOS_BUNDLE_ID` |
| `API_BASE_URL_VAL` | secret | `https://<val-host>`, no trailing slash. A secret so the hostname stays out of the logs |
| `API_BASE_URL_PROD` | secret | `https://<prod-host>`, the same way |
| `GOOGLE_IOS_CLIENT_ID` | variable | `<google-ios-client-id>`, the PROD app's iOS client ([below](#google-ios-oauth-client)). Unset: the PROD app offers Apple and email only |
| `GOOGLE_IOS_CLIENT_ID_VAL` | variable | `<google-ios-client-id-val>`, the VAL app's iOS client, the same way; the workflow refuses it equal to `GOOGLE_IOS_CLIENT_ID` |

**[dev]** With the GitHub CLI, in the checkout. The key file is piped, never
pasted:

```powershell
gh secret set ASC_KEY_ID --body <asc-key-id>
gh secret set ASC_ISSUER_ID --body <asc-issuer-id>
Get-Content -Raw $HOME\Downloads\AuthKey_<asc-key-id>.p8 | gh secret set ASC_KEY_P8
gh variable set APPLE_TEAM_ID --body <apple-team-id>
gh variable set IOS_BUNDLE_ID --body <ios-bundle-id>
gh variable set IOS_BUNDLE_ID_VAL --body <ios-bundle-id-val>
gh secret set API_BASE_URL_VAL --body https://<val-host>
gh secret set API_BASE_URL_PROD --body https://<prod-host>
gh variable set GOOGLE_IOS_CLIENT_ID --body <google-ios-client-id>
gh variable set GOOGLE_IOS_CLIENT_ID_VAL --body <google-ios-client-id-val>
gh secret list                           # ASC_KEY_ID, ASC_ISSUER_ID, ASC_KEY_P8, API_BASE_URL_VAL, API_BASE_URL_PROD, among the others
gh variable list                         # APPLE_TEAM_ID, IOS_BUNDLE_ID, IOS_BUNDLE_ID_VAL, GOOGLE_IOS_CLIENT_ID, GOOGLE_IOS_CLIENT_ID_VAL
```

Then delete `AuthKey_<asc-key-id>.p8` and `AuthKey_<apple-key-id>.p8` from
Downloads once both are in the password manager.

### Google iOS OAuth client

Google sign-in on iOS needs an **iOS** OAuth client, in the same project as
the web client of [step 11](#11-google-sign-in). Google registers an iOS
client with one bundle id, so each app has its own: two clients. The app
passes the web client's ID from `/api/config` as its server client ID, so the
ID token is still issued for the web client and `GOOGLE_CLIENT_IDS` needs
nothing more (plan D3). The iOS client's ID goes into the build, and its
reversed form becomes the app's URL scheme.

**[Google Cloud]** Google Auth Platform → Clients → Create client, once per
app:

| Field | PROD | VAL |
|---|---|---|
| Application type | **iOS** | **iOS** |
| Name | `Wishlist iOS` | `Wishlist iOS VAL` |
| Bundle ID | `<ios-bundle-id>` | `<ios-bundle-id-val>` |
| App Store ID, Team ID | empty | empty |

The PROD client's ID is `<google-ios-client-id>`, set as the
`GOOGLE_IOS_CLIENT_ID` variable above; the VAL client's is
`<google-ios-client-id-val>`, set as `GOOGLE_IOS_CLIENT_ID_VAL`. No client
secret is involved. An app whose variable is unset is built without Google
sign-in.

### TestFlight testers

Internal testers get every VAL build without Apple's review. Each one is a
member of the team in App Store Connect (up to 100).

**[Apple]** In App Store Connect:

1. Users and Access → **+**: the tester's name and Apple Account address,
   role **Developer**, without access to Certificates, Identifiers &
   Profiles, and Apps: **Wishlist VAL** only. TestFlight takes internal
   testers with the Admin, App Manager, Developer or Marketing role only.
   They accept the email invitation.
2. Apps → Wishlist VAL → TestFlight → Internal Testing → **+**: a group named
   `Testers`, with **Enable automatic distribution** ticked. Add the testers.
3. On their iPhone, testers install Apple's **TestFlight** app and accept the
   invitation it shows.

Testers use the VAL app, never the PROD one (plan D1): VAL is seeded from PROD
and what they do there is lost at the next seed ([Seeding VAL from
PROD](#seeding-val-from-prod)).

### Privacy labels

**[Apple]** Apps → Wishlist → App Privacy. Apple requires this before the PROD
app goes to review; the VAL app does not need it. Privacy Policy URL: the
address of `LEGAL_PRIVACY_URL`. Then Get Started → **Yes, we collect data**:

| Data type | Purpose | Linked to the user | Used for tracking |
|---|---|---|---|
| Contact Info → Email Address | App Functionality | Yes | No |
| Contact Info → Name | App Functionality | Yes | No |
| Identifiers → User ID (the account's id) | App Functionality | Yes | No |
| User Content → Photos or Videos (gift images) | App Functionality | Yes | No |
| User Content → Other User Content (lists, gifts, comments) | App Functionality | Yes | No |
| Purchases → Purchase History (the Premium subscription) | App Functionality | Yes | No |

Nothing else: no analytics, no advertising, no location, no tracking. Publish.

### Selling Premium in the app

Premium bought on iPhone, through Apple's in-app purchase, is set up once both
apps exist in App Store Connect, in [Billing, Part
3](BILLING.md#part-3-selling-on-iphone): the agreements, the subscription of
each app, the In-App Purchase key, the notification URLs and the test on VAL.
The apps offer no purchase until the variables of the [release with Apple
purchases](#release-specific-steps) are filled in.

### First build from the validation tag

Before it: VAL runs the release with Apple's token revocation (its migration
adds `apple_tokens`), and its `.env` is filled in as [above](#the-servers-values).

**[dev]** Push the `validation` tag as in [step 8](#8-first-val-deploy). It
deploys VAL, as always, and starts the iOS release of the VAL app.

**[GitHub]** Actions → "iOS release" for `validation`: the `gate` job, then
`release` on macOS, about 20 minutes. Its notice says `validation-<short sha>,
build <n>`. The run's log shows no hostname: the secrets are masked.

**[Apple]** Apps → Wishlist VAL → TestFlight: the build appears as
Processing, then becomes available to the `Testers` group, usually within half
an hour. No export compliance question: the app declares it uses no
encryption beyond HTTPS (plan D6).

**[dev]** On an iPhone, in the VAL app installed from TestFlight:

1. The name under the icon is "Wishlist VAL", and the app shows the version
   `validation-<short sha>`.
2. Sign in with Apple, with Google, then with email: each one signs in.
3. A gift's photo can be taken with the camera and picked from the library,
   each after the system's permission prompt.

#### An Apple sign-in leaves a token

The check of review R1-4: nothing else shows whether Apple's code exchange
works. **[VPS]** After the Apple sign-in on the iPhone:

```bash
cd /opt/wishlist-val
docker compose exec -T -u postgres db sh -c \
    'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select client_id, updated_at from apple_tokens order by updated_at desc limit 5"'
# a row for <ios-bundle-id-val>, updated at the sign-in. Never select refresh_token: it is a secret
docker compose logs app | grep 'apple: code not exchanged'   # nothing
```

No row, or a `code not exchanged` line, meets R1-4's "Revisit when": record it
in `docs/reviews/IOS_APP_PLAN.md` and take it through the adversarial review,
since the deletions of these accounts then revoke nothing. The `reason=` of
the log line says which part failed.

An Apple sign-in on `https://<val-host>` in a browser leaves a row for
`<apple-services-id>` the same way.

### Certificates after the first two runs

The check of review R1-6: automatic signing on a fresh runner may create a
new certificate at each run, and Apple limits how many a team has.

**[Apple]** Certificates, Identifiers & Profiles → Certificates. Note the
count and the types before the first run, after it, and after the second (the
second `validation` push, or a manual run of "iOS release" for `val`).

- The second run added nothing: done.
- Each run added one (an Apple Development or Apple Distribution certificate
  created that day): R1-6's "Revisit when" is met. Record it in
  `docs/reviews/IOS_APP_PLAN.md` and take it through the adversarial review.
  Do not revoke certificates by hand to make room: that is for the triage to
  decide.

## 14. Android app

The Android app is built and signed on GitHub's Linux runners and uploaded to
Google Play's internal testing track (Android release plan, D1 to D4). There
are **two apps**, as on iOS: the VAL app, "Wishlist VAL", built from the
`validation` tag and talking to VAL, which testers use; and the PROD app,
built from a release tag and talking to PROD. Until the secrets of [GitHub
variables and secrets](#github-variables-and-secrets-for-android) exist, the
`Android release` workflow ends with a notice and builds nothing.

This step needs [step 11](#11-google-sign-in) done first, at least on VAL: its
web client. It also needs the application id of the [bundle
id](#the-bundle-id) chosen, since Android shares it with iOS.

**The Play Console's menu names below were written from memory of Google's
documentation and were not checked against the Play Console on 2026-11-11.**
Google renames its menus from time to time, so follow the meaning when a name
differs. A detail that could not be confirmed is marked "unconfirmed".

### Play developer registration

**[Play]** At <https://play.google.com/console>, with a Google account that
the owner will keep for good: it is the developer account, and the apps belong
to it.

- A one-time registration fee, and an identity check by Google (unconfirmed:
  the amount and the documents asked). An organisation account also needs a
  D-U-N-S number; a personal account shows the owner's legal name to buyers.
- Google's rules for accounts created recently require a closed test with a
  minimum number of testers over a minimum number of days before an app can go
  to production (from memory: 12 testers for 14 days, and these numbers have
  changed before; unconfirmed). This does not affect the internal track used
  below, but it sets how soon the PROD app can reach the public: check it
  before planning that date.
- Selling needs a merchant account, set up in [Billing, Part 4, step
  1](BILLING.md#1-set-up-the-merchant-account). Registration does not need it.

Nothing below can start before Google has accepted the registration.

### The two apps

`<android-application-id>` is the PROD app's identity, the value chosen in
[The bundle id](#the-bundle-id) (the same as `<ios-bundle-id>`), and **cannot
change** once Google Play uses it. The VAL app's is `<android-application-id-val>`,
which is `<android-application-id>.val`: the `val` flavour adds that suffix
(`client/android/app/build.gradle.kts`).

**[Play]** All apps → Create app, once for each app:

| Field | VAL app | PROD app |
|---|---|---|
| App name | Wishlist VAL | Wishlist |
| Default language | the language of the store listing | the same |
| App or game | **App** | **App** |
| Free or paid | **Free** (Premium is an in-app subscription; a free app cannot be made paid later, unconfirmed) | the same |

Tick the declarations (developer programme policies, US export laws).

Creating the app does not give it an application id: the **first bundle
uploaded** does, and it can never change afterwards. That is why the next
steps matter before anything is uploaded. Do VAL first.

### The upload key

The upload key signs the bundle that CI sends to Play (plan D3). With **Play
App Signing**, Google holds the key that signs what users install, and the
upload key is only a credential for sending: if it is lost or leaked, Google
can reset it from the Play Console, and the app is never stuck. The same
upload key serves both apps.

**[dev]** Create it once, outside the repository (the file is `*.keystore`,
and ignored by Git, but a checkout is the wrong place anyway):

```powershell
keytool -genkeypair -v -storetype PKCS12 -keystore $HOME\wishlist-upload.keystore -alias upload -keyalg RSA -keysize 2048 -validity 10000
```

`keytool` asks for a keystore password, then for the key's, and a name and
organisation for the certificate: neither shows in the app. Answer both
passwords with the same long random value, which a PKCS12 keystore requires
(unconfirmed), and write down the file, the alias `upload` and the passwords
in the password manager, with a second copy of the file somewhere else. Note
its SHA-1 for [step 11](#android-oauth-client), `<upload-key-sha1>`:

```powershell
keytool -list -v -keystore $HOME\wishlist-upload.keystore -alias upload
```

**Keep it safe:** whoever has the file and its passwords can upload to your
apps, though only to the track the service account may use. A lost upload key
is replaceable through Google (the Play Console's app signing page offers an
upload key reset; the path is unconfirmed); a lost app signing key is not,
and Google holds that one.

**[Play]** Play App Signing is on for a new app, and the first upload (below)
enrols it: the key signing the first bundle becomes the upload key, and Google
generates the app signing key (from memory; unconfirmed). Once the first
bundle is uploaded, the Console shows the app signing key's SHA-1 under
Test and release → App integrity → App signing: `<play-signing-sha1-val>` for
the VAL app, `<play-signing-sha1>` for the PROD app. They differ, and
[step 11](#android-oauth-client) needs both.

### The service account for uploads

CI sends the bundle through the Play Developer API as a Google service
account, which the workflow signs in as with its JSON key.

**[Google Cloud]** In Wishlist's project, IAM & Admin → Service Accounts →
Create service account, such as `wishlist-play-upload`, with no project role.
Keys → Add key → Create new key → **JSON**; the file downloads once, and it
is a secret. Make sure the Google Play Android Developer API is enabled in
the project (APIs & Services → Library; unconfirmed).

**[Play]** Users and permissions → Invite new users: the service account's
email address, `<play-upload-service-account-email>`. Under App permissions,
add both apps, and tick (names unconfirmed):

- **View app information and download bulk reports (read-only)**;
- **Release to testing tracks**.

Nothing at the account level, no permission to release to production, and no
permission to manage orders: the server's account of [Billing, Part 4, step
3](BILLING.md#3-create-the-servers-service-account) is separate. Send the
invitation; access can take some time to start working (unconfirmed).

### GitHub variables and secrets for Android

The release workflow reads these from the repository (Settings → Secrets and
variables → Actions), not from an environment. It builds when all of the
first six of the table exist, ends with a notice and builds nothing when none
exist, and fails, naming what is missing, when only some do: set them in one
sitting, before any tag is pushed. The two server addresses
are the ones iOS uses ([step 13](#github-secrets-and-variables)).

| Name | Kind | Value |
|---|---|---|
| `ANDROID_APP_ID` | variable | `<android-application-id>`, the PROD app's. The workflow adds `.val` for the VAL app itself, and refuses the `com.example` placeholder |
| `ANDROID_UPLOAD_KEYSTORE_B64` | secret | the keystore file, base64 on one line |
| `ANDROID_UPLOAD_KEYSTORE_PASSWORD` | secret | the keystore's password |
| `ANDROID_UPLOAD_KEY_ALIAS` | secret | `upload` |
| `ANDROID_UPLOAD_KEY_PASSWORD` | secret | the key's password |
| `PLAY_SERVICE_ACCOUNT_JSON` | secret | the whole JSON key of the upload service account |
| `API_BASE_URL_VAL` | secret | `https://<val-host>`, as in step 13 |
| `API_BASE_URL_PROD` | secret | `https://<prod-host>`, as in step 13 |

**[dev]** With the GitHub CLI, in the checkout. The key and the keystore are
piped, and the passwords are typed at the prompt `gh` shows, never pasted into
a command:

```powershell
gh variable set ANDROID_APP_ID --body <android-application-id>
[Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\wishlist-upload.keystore")) | gh secret set ANDROID_UPLOAD_KEYSTORE_B64
gh secret set ANDROID_UPLOAD_KEYSTORE_PASSWORD
gh secret set ANDROID_UPLOAD_KEY_ALIAS --body upload
gh secret set ANDROID_UPLOAD_KEY_PASSWORD
Get-Content -Raw $HOME\Downloads\<service-account-key-file>.json | gh secret set PLAY_SERVICE_ACCOUNT_JSON
gh secret list                           # the five ANDROID_ and PLAY_ secrets, among the others
gh variable list                         # ANDROID_APP_ID, among the others
```

Then delete the service account's key file from Downloads once it is in the
password manager.

### The first upload, by hand

Google Play refuses the Developer API an app that has no upload made by hand
in the Play Console: the API cannot make the first release, and subscription
products need one too (review R1-6 of the plan). So **each app's first signed
bundle is uploaded manually**, once, using the bundle the workflow builds
itself.

**[dev]** Push the `validation` tag as in [step 8](#8-first-val-deploy) for the
VAL app. The PROD app waits for its own `vX.Y.Z` tag (or a manual run of
"Android release" from a tag, for `prod`).

**[GitHub]** Actions → "Android release" for that run. The `gate` job passes,
the bundle builds, then the step "Upload to the internal track" **fails** with
Google's message: that is the expected refusal. Only on that failure, the run
keeps the signed bundle as the artefact `android-bundle`, for 7 days. Download
it (Artifacts, at the bottom of the run's page) and unzip it: it holds
`app-val-release.aab` (`app-prod-release.aab` for PROD).

**[Play]** Wishlist VAL → Test and release → Testing → Internal testing →
Create new release: if the Console asks, accept Play App Signing. Upload the
`.aab`, give the release a name, save, review and roll it out to internal
testing. The Console may ask for a testers list before it lets the release
go: do the next section first, then return. The app now has its application id
and its first upload; Billing, Part 4 can create its subscription.

**[GitHub]** Delete the artefact from the run's page. A public repository's
artefacts can be downloaded by anyone, and the bundle holds the server's
address, which is kept out of the logs.

Later runs upload through the API by themselves. While an app has never been
published, Play accepts only a draft release from the API: the workflow then
prints the notice "Draft release", and the release has to be rolled out from
the Play Console, as above (this restriction is the workflow author's
reading of Play's message). Each build's version code is the run's number,
which only grows.

### Internal testers

Internal testers get every VAL build in minutes, without Google's review.

**[Play]** Wishlist VAL → Test and release → Testing → Internal testing →
Testers tab:

1. Create an email list named `Testers`, and add the testers' Google accounts,
   as the accounts on their phones. Tick the list for the track. The number of
   internal testers is limited (100, from memory; unconfirmed).
2. Copy the **opt-in link** under "How testers join your test". It is private
   to the testers: never commit it.
3. On their phone, each tester opens the link signed in with that account,
   accepts, and installs "Wishlist VAL" from Play.

Testers use the VAL app, never the PROD one (plan D1): VAL is seeded from PROD
and what they do there is lost at the next seed ([Seeding VAL from
PROD](#seeding-val-from-prod)). Buying Premium needs license testers on top:
[Billing, Part 4, step 6](BILLING.md#6-add-license-testers).

### Selling Premium on Android

Premium bought on Android, through Google Play Billing, is set up once both
apps exist in the Play Console with their first upload, in [Billing, Part
4](BILLING.md#part-4-selling-on-android): the merchant account, the
subscription of each app, the service account, Pub/Sub, the license testers
and the test on VAL. The apps offer no purchase until the variables of the
[release with Android and Google
purchases](#release-specific-steps) are filled in.

### First Android build from the validation tag

Before it: the VAL app exists in the Play Console with its first upload and an
internal testers list; VAL's web client and Android OAuth clients are
registered ([step 11](#android-oauth-client)); and VAL's `.env` has
`APPLE_ANDROID_PACKAGE=<android-application-id-val>`.

**[dev]** Push the `validation` tag again as in [step 8](#8-first-val-deploy).
It deploys VAL, as always, and starts the Android release of the VAL app.

**[GitHub]** Actions → "Android release" for `validation`: the `gate` job, then
`release`, which this time ends green. Its notice says `Android val app:
validation-<short sha>, build <n>`. The run's log shows no hostname: the
secrets are masked.

**[Play]** Wishlist VAL → Test and release → Testing → Internal testing: the
new release is there, completed (or a draft, to roll out, as above). It
reaches the testers' phones within minutes to an hour (unconfirmed).

**[dev]** On an Android phone, with the VAL app updated from Play:

1. The name under the icon is "Wishlist VAL", and the app shows the version
   `validation-<short sha>`.
2. Sign in with Google, with Apple, then with email: each one signs in. A
   Google button that fails with a developer error means the Android OAuth
   client does not match the installed key: compare the SHA-1 of
   [step 11](#android-oauth-client) with the one the Console shows (unconfirmed
   error text).
3. A gift's photo can be taken with the camera and picked from the library,
   each after the system's permission prompt.

## Admin

One account sees the admin panel: the users with their plan, lists, photo
space and gift counts, a manual Premium, and the deletion of an account
(admin panel plan, `plans/ADMIN_PANEL_PLAN.md`). Which account is set by
`ADMIN_USER_IDS` in the environment's `.env`, an account id and never an
address. Empty, nobody is admin and `/api/admin` answers 404 to everyone.
VAL first, then PROD: each has its own ids, since VAL's accounts are copied
from PROD only by a seed.

1. Sign in to the app once, on the environment, with the account that should
   be admin.
2. **[VPS]** Find its id, with the `pg` function of
   [Billing with Stripe](#billing-with-stripe), in the directory of the
   environment:

   ```bash
   pg <<'SQL'
   select id, created_at from users where email = '<owner-address>' order by created_at;
   SQL
   ```

   Several rows are possible, one per way of signing in (Google, Apple,
   email). Pick the account you use, which is the one you sign in with:
   the address alone does not say which.
3. **[VPS]** Put the id in `.env` as `ADMIN_USER_IDS=<admin-user-id>`, then
   start the app again with the new value (`restart` would not read it):

   ```bash
   docker compose up -d --wait --wait-timeout 300
   ```

4. Check. **[VPS]** This prints nothing (a line would name the positions of
   entries that are not ids, and ignore them):

   ```bash
   docker compose logs app | grep ADMIN_USER_IDS
   ```

   In the browser, signed in as that account, the account screen shows
   "Admin", and the response of `GET /api/me` (network tab) says
   `"is_admin": true`. If no "Admin" appears, reload the page once and look
   at the answer of `GET /api/me` in the network tab before changing
   `ADMIN_USER_IDS`: a failed read at sign-in hides the entry too.
5. **The 12-hour rule.** Changing a plan or deleting an account needs a
   sign-in less than 12 hours old: past that the panel asks to sign in again,
   and the change is made after it.
6. **What the panel shows, and never shows.** Counts only: lists owned, gifts
   per list, the number of owners, photos and their space. Never a gift, a
   reservation, a pledge, a comment or an occasion's members. Photos count
   only on gifts the recipient can see, so a giver's preparation of a surprise
   moves nothing; hidden gifts count for no one.
7. **The record.** Every change is kept. **[VPS]**

   ```bash
   pg <<'SQL'
   select created_at, action, target_user_id, detail from admin_actions order by created_at desc limit 50;
   SQL
   ```

8. **Removing the admin.** Empty the variable (`ADMIN_USER_IDS=`) and run
   `docker compose up -d --wait --wait-timeout 300` again.

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
- PROD's media purge ran in the last day, with a horizon
  ([Media](#media)):

  ```bash
  docker compose -f /opt/wishlist/docker-compose.yml logs --since 25h app | grep 'media purge:'
  ```

  Expect at least one `media purge: horizon=<date> ...` line. `horizon=none` or
  `skipped` means nothing is purged and media only grow: check the backups
  directory's owner and mode, and that `backup` is healthy.
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
- **Access:** the directory is `999:10001` mode 750 and each dump 600. The
  dumps hold every user's data, so the deploy user cannot read or even list
  them: use `sudo`. PROD's app (uid and gid 10001) has the directory mounted
  read-only at `/app/backups`: through the group it lists the dumps and reads
  their names and dates for the [media purge](#media), and cannot open one
  (gift images plan D10). Keep every dump 600: a copy made readable to the
  group is readable by the app.
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
mode changed (it must be `999:10001` 750). Once fixed, `restart backup` dumps
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
30 kept dumps reach further back than 30 days. The [media purge](#media)
follows the oldest kept dump, so it moves back with them (review finding
R2-5).

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

Gift images are `gifts/<id>.webp` and `gifts/<id>.thumb.webp`, where `<id>`
is the image's random id, not a content hash: written once under a temporary
name, renamed into place, never modified (gift images plan D3, amending D18;
seeding's hard links need only that files never change). Replacing or
removing a gift's image, or deleting a gift, a list or an account, only
changes database rows; files leave the disk late, through the media purge.

**The media purge** (gift images plan
[D9, D10](plans/GIFT_IMAGES_PLAN.md)) runs inside PROD's app, 10 minutes
after it starts and then every 24 hours. It deletes an image's two files only
once no database row has pointed at them since before the **oldest kept
dump** was taken: no dump still in `/opt/wishlist/backups` can reference
them, so restoring any of them finds its images. The horizon is the oldest
`*.dump` in that directory, by its file date and the date in its name,
whichever is earlier, minus a day. So:

- it counts dumps, not days: after a backup outage the 30 kept dumps reach
  further back, and so does the purge;
- manual copies in the directory (`kept_<YYYY-MM-DD>.dump`,
  `before-restore.dump`, `before-pg<new-major>.dump`) count while they are
  there: an old one holds back every purge until it is deleted;
- copies taken off the host do not count: restoring one older than the oldest
  dump on the host may find some images gone;
- with no dump it can list (a missing or unreadable directory, or an empty
  one), nothing is purged at all.

Each run logs one line in the app's logs:

```bash
docker compose -f /opt/wishlist/docker-compose.yml logs app | grep 'media purge:'
# media purge: horizon=<iso|none> orphans=<n> purged=<n> rows_released=<n>
# media purge: skipped (<reason>)
```

`horizon=none` or `skipped` means nothing was purged. If the backups
directory lost its group or mode, put back `999:10001` 750
([Backups](#backups)).

VAL has no backups, so `BACKUP_DIR` is not set there and VAL's media are never
purged; reseeding only adds files. If `/opt/wishlist-media/val` grows past
1 GB, that is an open decision of the gift images plan.

**What that protects against:** logical errors. A bad migration, a bug that
deletes gifts, an accidental deletion through the app: restoring any kept
dump finds every file it references, without keeping 30 copies of the images.

**What it does not protect against:**

- Losing the VPS or its disk: the media, like the dumps, are on the same
  disk. Off-site copies are an [open item](#open-items).
- Deleting or changing files on the host by hand, or a bug in the purge
  itself.
- A full disk: there is no per-account limit yet. Free space is part of the
  [daily check](#daily-check).

The deploy user cannot list these directories (mode 750, another owner). To
see their size: `sudo du -sh /opt/wishlist-media/prod /opt/wishlist-media/val`.
In one `du` run, a file hard-linked into both (by seeding) is counted once.

## Restoring PROD from a dump

This replaces PROD's database with a dump's content. Everything written since
that dump is lost. PROD is down from step 1 to step 4. Media need no step:
files are never modified and purged after the oldest kept dump, so every file
a dump on the host references is still there ([Media](#media)). That holds
after rolling back to `before-restore.dump` too: the purge also goes by each
file's modification time, which every run sets while a row references the
file, so a record the rollback brings back cannot make it go early. Never
set those times to an earlier date by hand.

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

**Subscriptions of accounts the dump does not have.** A restore loses the
accounts created since the dump. If billing is live, a subscription of such an
account is cancelled at its next Stripe event, which for a renewal comes after
the charge: a subscription with no account must not keep billing, so this stays
as it is. Right after a restore, compare the subscriptions active in the Stripe
dashboard with the `entitlements` rows and refund by hand the ones with no
account. The WARNING `stripe: cancelling subscription … of a gone account` names
each one
the app cancels.

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
- PROD's purchases stay on PROD: `entitlements` and `billing_customers` are
  emptied right after the restore, before VAL's app starts (premium plan
  D16). Their ids mean nothing to VAL's Stripe test account.
- Media: PROD's files are hard-linked (no extra disk; safe because files are
  never modified), by uid 10001 in a one-shot container that mounts
  `/opt/wishlist-media` once. Files VAL already has are kept.
- It ends with `done: VAL is up on wishlist_<YYYY-MM-DD>.dump`, after VAL's
  app migrated the database and reported healthy.

If it fails, it says `FAILED: VAL may be left stopped`. Fix the cause and run
it again. A failure while hard-linking a media file that no longer exists
means PROD's daily [media purge](#media) deleted it during the copy: just run
it again (gift images review R1-10). To bring VAL back empty instead:
`docker compose -f /opt/wishlist-val/docker-compose.yml up -d`. Only if it
failed before `database restored`: later, that database is PROD's, and
before `PROD's purchases removed` it still holds PROD's purchases. Run the
script again in that case.

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

### Release-specific steps

Run these on the host **before** deploying the release named, once.

- **The release with gift images** (the first with `BACKUP_DIR` in PROD's
  compose file). **[VPS]** Give PROD's app the right to list the dumps, then
  update the compose file (below):

  ```bash
  sudo chgrp 10001 /opt/wishlist/backups && sudo chmod 750 /opt/wishlist/backups
  sudo stat -c '%u:%g %a' /opt/wishlist/backups              # 999:10001 750
  sudo find /opt/wishlist/backups -type f ! -perm 600       # nothing: every dump stays 600
  ```

  Without it the release still runs: the purge logs `skipped` and deletes
  nothing.

  The same release raises the app memory limits (PROD 320M, VAL 256M; total
  1088 MB). **[VPS]** On an existing host, with both stacks running, check
  that `free -m` shows "available" of at least 1150 MB; if not, stop and
  decide before deploying.

- **The release with comments and email notifications** (the first with
  `NOTIFICATION_SECRET` in the `.env.example` files).

  **The migrations of this release run on deploy, by themselves.** The
  image's entrypoint applies them before the app starts: on VAL when its image
  arrives, on PROD during `.\deploy.ps1 -Target Prod`. Nothing is run by hand.
  If one fails the app does not start: `docker compose logs app` in its
  directory says why. To see which ones:
  `git diff --name-only <previous-release> <release> -- server/alembic/versions`.

  Email is off until the steps below are done. The release runs normally
  without them and they can come later, but the emails due until then are
  dropped, never sent afterwards. VAL first, checked, then PROD.

  **[Brevo]** The owner has a sending key (`<brevo-api-key>`) and a verified
  sender (`<sender-address>`, with SPF and DKIM on its domain). Setting up the
  account and the DNS records is not part of this runbook.

  **[VPS]** `PUBLIC_BASE_URL` must be set in **both** `.env`, VAL's and
  PROD's. Email stays off in an environment where it is empty, even with
  everything below filled in:

  ```bash
  grep -n '^PUBLIC_BASE_URL=' /opt/wishlist-val/.env /opt/wishlist/.env   # each with its https:// origin
  ```

  If one is empty or missing, run the commands of [step 6](#6-caddy) that set
  it.

  **[VPS]** Each `.env` gets the new lines if it predates them, from the
  examples at the release (step 2 with `REF=<release>`). The first `grep` keeps
  a second run from adding them twice:

  ```bash
  cd /opt/wishlist-val
  grep -q '^NOTIFICATION_SECRET=' .env || \
      grep -E '^(BREVO_API_KEY|EMAIL_|NOTIFICATION)' "$SRC/deploy/val/.env.example" >> .env
  cd /opt/wishlist
  grep -q '^NOTIFICATION_SECRET=' .env || \
      grep -E '^(BREVO_API_KEY|EMAIL_|NOTIFICATION)' "$SRC/deploy/prod/.env.example" >> .env
  grep -c -E '^(BREVO_API_KEY|EMAIL_|NOTIFICATION)' /opt/wishlist-val/.env /opt/wishlist/.env   # :6 for VAL, :5 for PROD
  ```

  `EMAIL_SENDER_NAME` and `NOTIFICATIONS_WORKER` keep the examples' values.
  Never leave `NOTIFICATIONS_WORKER` empty: the app would refuse to start.
  `false` stops the worker, and activity waits until it is back on.

  **[VPS]** Fill in VAL. `NOTIFICATION_SECRET` signs the unsubscribe links:
  each environment generates its own, never shared (VAL holds PROD's accounts,
  so a shared secret would make VAL's links work on PROD), and it is never
  rotated without reason, because that invalidates every unsubscribe link
  already sent. The `sed` below only fills an empty line, so running it again
  cannot rotate it.

  `EMAIL_ALLOWED_RECIPIENTS` is VAL's safety: VAL is seeded from PROD and holds
  real people's addresses, so it emails only those listed (comma-separated, no
  spaces). Put the owner's own address and nobody who has not agreed to it. An
  empty list emails nobody.

  ```bash
  cd /opt/wishlist-val
  sed -i "s/^NOTIFICATION_SECRET=$/NOTIFICATION_SECRET=$(openssl rand -hex 32)/" .env
  read -rs BREVO_KEY                                 # paste <brevo-api-key>, then Enter: nothing is shown or kept in the history
  sed -i "s|^BREVO_API_KEY=.*|BREVO_API_KEY=$BREVO_KEY|" .env
  unset BREVO_KEY
  sed -i 's|^EMAIL_SENDER_ADDRESS=.*|EMAIL_SENDER_ADDRESS=<sender-address>|' .env
  sed -i 's|^EMAIL_ALLOWED_RECIPIENTS=.*|EMAIL_ALLOWED_RECIPIENTS=<owner-address>|' .env
  grep -c -E '^(BREVO_API_KEY=.|NOTIFICATION_SECRET=[0-9a-f]{64}$)' .env   # 2
  grep -E '^EMAIL_' .env                             # the sender, its name, the allow-list; no secret
  ls -l .env                                         # -rw-------
  docker compose up -d --wait --wait-timeout 300
  ```

  **[VPS]** Once VAL runs this release (`/api/version`), the line it logs at
  start naming missing variables is gone:

  ```bash
  docker compose -f /opt/wishlist-val/docker-compose.yml logs app |
      grep -E 'BREVO_API_KEY|EMAIL_SENDER_ADDRESS|NOTIFICATION_SECRET|PUBLIC_BASE_URL'   # nothing
  ```

  Any line printed names what is still missing.

  **[dev]** A comment on VAL reaches the allowed address. On
  `https://<val-host>`, sign in with the `<owner-address>` account, in an
  occasion where it is a giver (the recipient of a "for me" list is never
  notified), and press **Follow** on a gift. From another account of that
  occasion, comment on the gift. Within about two minutes one email arrives at
  `<owner-address>`, its links on `https://<val-host>`; the author of the
  comment gets none. If nothing arrives, see why (counts only, no address):

  ```bash
  cd /opt/wishlist-val
  docker compose exec -T -u postgres db sh -c \
      'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select status, skip_reason, count(*) from email_digests group by 1, 2"'
  ```

  `not_configured` is a missing variable, `not_allowed` an address outside the
  allow-list, `opted_out` an account with notifications off, and `failed` a
  send Brevo refused: the app's logs have the reason.

  **[VPS]** Then PROD, once VAL's check has passed: the same commands in
  `/opt/wishlist`, without the `EMAIL_ALLOWED_RECIPIENTS` line, which PROD
  does not have. **From then on every account with notifications on receives
  its emails.** If PROD does not run this release yet, leave out `up -d` too:
  `.\deploy.ps1 -Target Prod` recreates the app with the new `.env`. After it,
  run the log check above on `/opt/wishlist/docker-compose.yml`, and check that
  the two secrets differ:

  ```bash
  [ "$(sed -n 's/^NOTIFICATION_SECRET=//p' /opt/wishlist/.env)" != \
    "$(sed -n 's/^NOTIFICATION_SECRET=//p' /opt/wishlist-val/.env)" ] && echo different   # different
  ```

  **[dev]** The addresses were not committed:

  ```powershell
  git grep -n -F -e <sender-address> -e <owner-address>     # nothing
  ```

- **The release with premium** (the first with `STRIPE_SECRET_KEY` in the
  `.env.example` files).

  Its migration runs on deploy, by itself, and only adds two tables. Nothing
  is sold, limited or charged until the owner fills in the variables below:
  the release runs normally without them, and
  [Billing with Stripe](#billing-with-stripe) says how, VAL first.

  **[VPS]** Each `.env` gets the new lines, from the examples at the release
  (step 2 with `REF=<release>`). The first `grep` keeps a second run from
  adding them twice. The new `seed-from-prod.sh` goes in **before the next
  seed**: the old one would bring PROD's purchases to VAL once PROD has any.

  ```bash
  cd /opt/wishlist-val
  grep -q '^BILLING_ENFORCE_LIMITS=' .env || \
      grep -E '^(BILLING_|FREE_MAX_|STRIPE_|LEGAL_)' "$SRC/deploy/val/.env.example" >> .env
  cd /opt/wishlist
  grep -q '^BILLING_ENFORCE_LIMITS=' .env || \
      grep -E '^(BILLING_|FREE_MAX_|STRIPE_|LEGAL_)' "$SRC/deploy/prod/.env.example" >> .env
  grep -c -E '^(BILLING_|FREE_MAX_|STRIPE_|LEGAL_)' /opt/wishlist-val/.env /opt/wishlist/.env   # :15 for both
  install -m 755 "$SRC/deploy/val/seed-from-prod.sh" /opt/wishlist-val/
  ```

  Nothing needs `docker compose up -d` yet: every value is its default.

- **The release with Apple and email sign-in** (the first with
  `APPLE_CLIENT_IDS` in the `.env.example` files).

  Its migration runs on deploy, by itself, and only adds three tables. The
  previous release ignores them, so a rollback stays image-only. Apple sign-in
  stays absent until the owner fills in the variables below
  ([Apple sign-in](#12-apple-sign-in), VAL first); email sign-in needs the
  email set-up of the comments release and nothing more.

  **[VPS]** Each `.env` gets the new lines, from the examples at the release
  (step 2 with `REF=<release>`). The first `grep` keeps a second run from
  adding them twice.

  ```bash
  cd /opt/wishlist-val
  grep -q '^APPLE_CLIENT_IDS=' .env || \
      grep -E '^APPLE_' "$SRC/deploy/val/.env.example" >> .env
  cd /opt/wishlist
  grep -q '^APPLE_CLIENT_IDS=' .env || \
      grep -E '^APPLE_' "$SRC/deploy/prod/.env.example" >> .env
  grep -c -E '^APPLE_' /opt/wishlist-val/.env /opt/wishlist/.env   # :2 for both
  ```

  Nothing needs `docker compose up -d` yet: both are empty.

- **The release with the admin panel** (the first with `ADMIN_USER_IDS` in the
  `.env.example` files).

  Its migration runs on deploy, by itself. It adds `images.bytes` and the
  `admin_actions` table, and allows the `manual` source on purchases. The
  previous release ignores the column and the table, so a rollback stays
  image-only. The photo sizes of older photos are measured by the media thread
  after the deploy, a few hundred per run: the panel says "measuring" until
  then.

  **[VPS]** Each `.env` gets the new line, from the examples at the release
  (step 2 with `REF=<release>`). The first `grep` keeps a second run from
  adding it twice.

  ```bash
  cd /opt/wishlist-val
  grep -q '^ADMIN_USER_IDS=' .env || \
      grep -E '^ADMIN_USER_IDS=' "$SRC/deploy/val/.env.example" >> .env
  cd /opt/wishlist
  grep -q '^ADMIN_USER_IDS=' .env || \
      grep -E '^ADMIN_USER_IDS=' "$SRC/deploy/prod/.env.example" >> .env
  grep -c -E '^ADMIN_USER_IDS=' /opt/wishlist-val/.env /opt/wishlist/.env   # :1 for both
  ```

  Nothing needs `docker compose up -d` yet: it is empty, and no one is admin
  until [Admin](#admin) is followed.

- **The release with Apple purchases** (the first with `APPLE_PRODUCT_ID` in
  the `.env.example` files).

  It has no migration: Apple's entitlements use the existing `entitlements`
  table, so a rollback stays image-only. Selling on iPhone stays absent until
  the owner fills in the variables ([Billing, Part
  3](BILLING.md#part-3-selling-on-iphone), VAL first).

  **[VPS]** Each `.env` gets the new lines, from the examples at the release
  (step 2 with `REF=<release>`). The first `grep` keeps a second run from
  adding them twice. VAL gets five lines, PROD seven: the two more are
  `APPLE_APP_APPLE_ID` and `APPLE_SANDBOX_ACCOUNT_IDS`.

  ```bash
  cd /opt/wishlist-val
  grep -q '^APPLE_PRODUCT_ID=' .env || \r
      grep -E '^APPLE_(PRODUCT_ID|BUNDLE_ID|IAP_)' "$SRC/deploy/val/.env.example" >> .env
  cd /opt/wishlist
  grep -q '^APPLE_PRODUCT_ID=' .env || \r
      grep -E '^APPLE_(PRODUCT_ID|BUNDLE_ID|APP_APPLE_ID|IAP_|SANDBOX_ACCOUNT_IDS)' "$SRC/deploy/prod/.env.example" >> .env
  grep -c -E '^APPLE_(PRODUCT_ID|BUNDLE_ID|APP_APPLE_ID|IAP_|SANDBOX_ACCOUNT_IDS)' /opt/wishlist-val/.env /opt/wishlist/.env   # :5 for VAL, :7 for PROD
  ```

  Nothing needs `docker compose up -d` yet: all are empty.

- **The release with Android and Google purchases** (the first with
  `GOOGLE_PLAY_PRODUCT_ID` in the `.env.example` files).

  Its migration runs on deploy, by itself. It widens `entitlements.external_id`
  from 255 characters to text, because a Google purchase token can be longer.
  The previous release reads and writes the column as a string whatever its
  length, so a rollback stays image-only. Rolling back across it leaves the
  schema at the wider type. Only a downgrade of the database, which nothing
  here asks for, would delete the Google rows whose id is longer than 255
  characters. Selling on Android stays absent until the owner fills in the
  variables below ([Billing, Part
  4](BILLING.md#part-4-selling-on-android), VAL first).

  **While the previous release runs after a rollback,** it has no Google
  route: Pub/Sub's pushes are refused and retried, and **deleting an account
  does not cancel its Google subscription**: it keeps charging. If Google
  purchases exist, keep the rollback short, and cancel by hand, in the Play
  Console (Order management), the subscription of any account deleted
  meanwhile.

  **[VPS]** Each `.env` gets the new lines, from the examples at the release
  (step 2 with `REF=<release>`). The first `grep` keeps a second run from
  adding them twice. VAL gets five lines, PROD six: the one more is
  `GOOGLE_PLAY_TEST_ACCOUNT_IDS`.

  ```bash
  cd /opt/wishlist-val
  grep -q '^GOOGLE_PLAY_PRODUCT_ID=' .env || \
      grep -E '^GOOGLE_PLAY_' "$SRC/deploy/val/.env.example" >> .env
  cd /opt/wishlist
  grep -q '^GOOGLE_PLAY_PRODUCT_ID=' .env || \
      grep -E '^GOOGLE_PLAY_' "$SRC/deploy/prod/.env.example" >> .env
  grep -c '^GOOGLE_PLAY_' /opt/wishlist-val/.env /opt/wishlist/.env   # :5 for VAL, :6 for PROD
  ```

  Nothing needs `docker compose up -d` yet: all are empty. `APPLE_ANDROID_PACKAGE`
  is already in the `.env` files since the Apple sign-in release; its value
  for each environment is set in [Android OAuth
  client](#android-oauth-client).

  **Never clear these while a Google subscription runs:** its renewals would go
  unrecorded, Premium would end for someone who paid, and deleting their
  account would be refused, since it cancels the subscription first.

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

**Rolling back across the hidden gifts and comments release.** The rollback is
image-only, as above: the previous release runs on this schema and never shows
a hidden gift. During the rollback:

- received gifts show on their lists again; hidden and revealed gifts are
  invisible to everyone, and comments and follows are unreachable;
- no notification event is written and no email is sent; events already
  waiting are processed when this release runs again;
- deleting an occasion deletes its bought hidden gifts instead of revealing
  them;
- gifts deleted during the rollback leave their activity unreachable, and the
  worker removes it when this release runs again.

**The surprise is not fully kept across this rollback.** The previous release
does not maintain `occasions.latest_date`, so a recipient who moves an
occasion's date into the past during the rollback sees that occasion's bought
hidden gifts early, once this release runs again. Keep the rollback short and,
on the way forward, check the occasions whose date moved earlier during it.

A client of this release fails the occasion page against a rolled-back server,
because `/hidden-gifts` answers 404. The web client is served by the server and
rolls back with it; the mobile release must revisit this before builds are
installed.

**Rolling back across the premium release.** The rollback is image-only. The
previous release has no webhook and no billing routes, so while it runs Stripe
events fail and are retried for up to three days, and **deleting an account
does not cancel its subscription**: it keeps charging. If billing is live, keep
the rollback within Stripe's retries, and cancel by hand in the Stripe
dashboard the subscription of any account deleted meanwhile. Limits are not
applied.

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
tail -F /opt/wishlist-val/webhook/deploy.log
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

## Billing with Stripe

Premium is sold on the web through Stripe Checkout and managed in Stripe's
Customer Portal (premium plan, `plans/PREMIUM_PLAN.md`). The app has two
states: the **gateway**, the two secrets, receives webhooks, opens the portal
and cancels at account deletion; **selling**, the gateway plus the rest,
offers the purchase and lets limits apply. Every variable is described in the
`.env.example` files. VAL always comes first, in a Stripe sandbox of its own (one
sandbox per environment: a webhook cancels subscriptions it finds no account
for, so DEV and VAL sharing one would cancel each other's tests), with test
keys.

**[VPS]** The queries below use this function, in the directory of the
environment (`/opt/wishlist-val`, or `/opt/wishlist` on PROD). A new shell
needs it again:

```bash
pg() { docker compose exec -T -u postgres db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1'; }
```

### Stripe test on VAL

VAL must run this release, with `PUBLIC_BASE_URL` set ([step 6](#6-caddy)).

**[Stripe]** In a sandbox of the Stripe account chosen for Wishlist (sandboxes
are separate accounts: everything below has to be set in each one):

1. A product with one **yearly, tax-inclusive** price, in the currency of
   `BILLING_PRICE_CURRENCY`. The app refuses to sell any other shape of price.
   Note `<stripe-price-id>` and `<price-amount>`.
2. Settings → Public details → Terms of service: `https://<val-host>/legal/terms`.
   Checkout fails without it, and the server cannot check it ahead of time.
3. The Customer Portal configuration: cancellation **at period end**, updating
   the card and reading invoices allowed, **no plan change**.
4. The Checkout setting **Limit customers to one subscription**.
5. The failed-payment setting in the subscription settings, under revenue
   recovery, "if all retries fail": **cancel the subscription or mark it
   unpaid, never leave it past due**. `past_due` keeps Premium, so a
   subscription left past due goes on granting it to a card that never pays
   (plan D2).
6. A webhook endpoint at `https://<val-host>/api/billing/webhook`, subscribed
   to exactly these four events: `checkout.session.completed`,
   `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted`. It shows `<stripe-webhook-secret>`.
7. The secret key of the sandbox, `<stripe-secret-key>`. VAL refuses a live
   key: only test keys belong here.

**[VPS]** Fill in VAL. `BILLING_ENFORCE_LIMITS=true` is what lets the limits be
tested. The legal and consent variables stay empty: VAL shows placeholders.

```bash
cd /opt/wishlist-val
grep -n '^PUBLIC_BASE_URL=' .env                   # its https:// origin
read -rs STRIPE_KEY                                # paste <stripe-secret-key>, then Enter
sed -i "s|^STRIPE_SECRET_KEY=.*|STRIPE_SECRET_KEY=$STRIPE_KEY|" .env
unset STRIPE_KEY
read -rs STRIPE_WEBHOOK                            # paste <stripe-webhook-secret>, then Enter
sed -i "s|^STRIPE_WEBHOOK_SECRET=.*|STRIPE_WEBHOOK_SECRET=$STRIPE_WEBHOOK|" .env
unset STRIPE_WEBHOOK
sed -i 's|^STRIPE_PRICE_ID=.*|STRIPE_PRICE_ID=<stripe-price-id>|' .env
sed -i 's|^BILLING_PRICE_AMOUNT=.*|BILLING_PRICE_AMOUNT=<price-amount>|' .env
sed -i 's|^BILLING_ENFORCE_LIMITS=.*|BILLING_ENFORCE_LIMITS=true|' .env
grep -c -E '^(STRIPE_SECRET_KEY=(sk|rk)_test_|STRIPE_WEBHOOK_SECRET=whsec_)' .env   # 2
ls -l .env                                         # -rw-------
docker compose up -d --wait --wait-timeout 300
docker compose logs app | grep -E 'STRIPE_|BILLING_|LEGAL_|PUBLIC_BASE_URL'         # nothing
```

Any line printed names what is still missing. `docker compose restart` would
not re-read `.env` ([step 5](#5-env-files)).

**[dev]** The purchase, on `https://<val-host>`, signed in with a free account.
`GET /api/billing` is in the browser's developer tools (Network), since it
needs the signed-in session:

1. The account screen shows "Your plan". `GET /api/billing`: `plan` is `free`,
   `offer` has the amount, `enforced` is `true`.
2. A second list, and a 21st gift on a list, are refused with the limit
   message, and what was typed stays in the form.
3. See Premium → Continue to payment. Card `4242 4242 4242 4242`, any future
   date, any CVC. Tick the terms box.
4. Back on the plan page, Premium appears once the webhook has landed. The
   endpoint's event deliveries in Stripe answer 204. `GET /api/billing`: `plan`
   is `premium`, `status` `active`, `renews_at` a year away. The limits are
   gone.
5. Manage subscription → cancel in the portal. `status` is `canceling`,
   `ends_at` is the end of the year paid: Premium stays until then.
6. To see it end now, cancel that subscription **immediately** in the Stripe
   dashboard. `plan` is `free`, nothing was deleted, the lists stay readable,
   shareable and editable, and the limit message is back.

**[Stripe]** Try one resend ([below](#after-a-webhook-delivery-gap)) on an
event of that subscription: it is accepted (204) and nothing changes.

### A failed renewal, on VAL

This settles what plan D2 leaves open: how `current_period_end` moves on a
failed renewal, and that a card that never pays ends Premium. Use an account
with no subscription in force. Stripe's clock is simulated and the app's is
real, so Premium cannot end by date during this test: only `status` proves it.

**[VPS]** The account's id on VAL:

```bash
cd /opt/wishlist-val
pg <<'SQL'
select id from users where email = '<account-address>';
SQL
```

**[dev]** A customer on a test clock, with the Stripe CLI logged in to the
sandbox (`stripe login`). Each command prints the id the next one needs. The
first card must pay: with a failing one the subscription would start
`incomplete` instead of renewing. Hence the swap before the renewal:

```powershell
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
stripe test_helpers test_clocks create --frozen-time $now --name wishlist-renewal      # <test-clock-id>
stripe customers create --test-clock <test-clock-id> --name "Renewal test"             # <customer-id>
stripe payment_methods attach pm_card_visa --customer <customer-id>                    # <good-card-id>
stripe customers update <customer-id> -d "invoice_settings[default_payment_method]=<good-card-id>"
stripe subscriptions create --customer <customer-id> -d "items[0][price]=<stripe-price-id>" -d "metadata[user_id]=<user-id>"   # <subscription-id>

stripe payment_methods attach pm_card_chargeCustomerFail --customer <customer-id>      # <failing-card-id>
stripe customers update <customer-id> -d "invoice_settings[default_payment_method]=<failing-card-id>"
```

**[VPS]** Record `status` and `period_end` now, and again after the advance
below:

```bash
pg <<'SQL'
select status, period_end from entitlements where external_id = '<subscription-id>';
SQL
```

**[dev]** Past the renewal. The two hours cover its invoice, which stays a
draft for about an hour before it is charged:

```powershell
$renewal = [DateTimeOffset]::FromUnixTimeSeconds($now).AddYears(1).AddHours(2).ToUnixTimeSeconds()
stripe test_helpers test_clocks advance <test-clock-id> --frozen-time $renewal
stripe test_helpers test_clocks retrieve <test-clock-id>                               # repeat until status is "ready"
```

**[VPS]** The same query again: this is the row during `past_due`.

**[dev]** With that account signed in, `GET /api/billing` during `past_due`:
`plan` is `premium`, `status` `past_due`. Then past the last retry, whatever
the retry schedule is:

```powershell
$end = [DateTimeOffset]::FromUnixTimeSeconds($now).AddYears(1).AddMonths(3).ToUnixTimeSeconds()
stripe test_helpers test_clocks advance <test-clock-id> --frozen-time $end
stripe test_helpers test_clocks retrieve <test-clock-id>                               # repeat until status is "ready"
```

The row is `ended` and `GET /api/billing` says `plan` `free`. Delete the clock
when done: `stripe test_helpers test_clocks delete <test-clock-id>`.

**Record the result in `docs/reviews/PREMIUM_PLAN.md`:** whether `period_end`
advanced during `past_due`, and that Premium ended past the last retry. If
`period_end` does not advance, say so there: the plan relies on the
failed-payment setting because that is expected, and it needs revisiting.

### After a webhook delivery gap

The endpoint was unreachable for longer than Stripe's retries (up to 3 days in
live mode, a few hours in test mode), or a line `entitlement past its grace`
appears in the app's logs. That line is logged where a status or a limit is
read, and holds a row id and a source, no personal data. Nothing repairs itself
until the subscription's next event, perhaps a year away.

**[VPS]** The subscription of a logged row (read-only):

```bash
docker compose logs app | grep 'entitlement past its grace'
pg <<'SQL'
select source, external_id, status, period_end from entitlements where id = '<entitlement-id>';
SQL
```

**[Stripe]** The failed events: in the webhook endpoint's event deliveries, or
with `delivery_success=false` (the last 30 days only). Resend **one per
affected subscription**, a `customer.subscription.*` event, whose
`data.object.id` is the subscription. The handler only re-reads the
subscription, so any of its events repairs the row, in any order:

```powershell
stripe events list --delivery-success=false --limit 100                         # add --live on PROD
stripe events resend <event-id> --webhook-endpoint <webhook-endpoint-id>        # add --live on PROD
```

The Dashboard's resend button does the same. The delivery answers 204, and
the row then shows Stripe's current `status` and `period_end`.

**Older than 30 days**, events cannot be resent. Any change to the
subscription emits a new one: in the Dashboard, add a metadata key (`resync`,
with the date) to the subscription. **Never edit `user_id`**, which links it to
its account. A subscription that has already ended cannot be edited, so its row
goes on logging the WARNING; the person is rightly not premium (review R2-2,
deferred).

### Turning enforcement on

`BILLING_ENFORCE_LIMITS=true` applies the limits, while the app is selling.
Anyone already past a limit cannot grow, and keeps everything. **[VPS]** First,
on PROD, how many are already past them (read-only, counts only). `1` and `20`
are `FREE_MAX_LISTS` and `FREE_MAX_GIFTS_PER_LIST`; accounts a premium owner
covers are counted too, so these are upper bounds:

```bash
cd /opt/wishlist
pg <<'SQL'
select count(*) as accounts_over_the_list_limit from (
    select user_id from list_owners group by user_id having count(*) > 1
) as o;
select count(*) as lists_over_the_gift_limit from (
    select list_id from gifts
    where list_id is not null and received_at is null
    group by list_id having count(*) > 20
) as g;
SQL
```

Then set `BILLING_ENFORCE_LIMITS=true` in `.env` and run
`docker compose up -d --wait --wait-timeout 300`.

### Withdrawing the offer

Clear `STRIPE_PRICE_ID` or `BILLING_PRICE_AMOUNT` and run
`docker compose up -d --wait --wait-timeout 300`: sales and limits stop, and
existing subscribers go on being recorded, managed and cancellable. Never
clear `PUBLIC_BASE_URL` for that (the portal, share links and emails need it),
and **never the two secrets while a subscription runs**: its renewals would go
unrecorded, and its owner could not delete their account
([below](#account-deletion-refused-with-409)).

### Before live keys, on PROD

No live key goes into PROD before all of this:

- OSS VAT registration, and Stripe Tax set up in live mode.
- The price, currency and every other row of the plan's Open decisions marked
  before live keys, in-app withdrawal and refund among them.
- The owner's texts and URLs. In production the offer stays withdrawn without
  each of `STRIPE_AUTOMATIC_TAX=true`, `BILLING_TERMS_VERSION`,
  `BILLING_CONSENT_TEXT_EN`, `BILLING_CONSENT_TEXT_FR`, `LEGAL_TERMS_URL`,
  `LEGAL_PRIVACY_URL` and `LEGAL_WITHDRAWAL_URL`. A live key is required
  there too: a test key is refused.
- The dashboard settings of [Stripe test on VAL](#stripe-test-on-val), steps 1
  to 6, in live mode, with `https://<prod-host>` in the webhook endpoint, and
  the address of `LEGAL_TERMS_URL` as the terms URL: the app's own
  `/legal/terms` is only ever a placeholder. The endpoint has its own secret.

**[VPS]** Set them in `/opt/wishlist/.env` as on VAL, with the texts in an
editor (`nano .env`): each on one line, not quoted, never with ` #` inside,
which would cut the value there. Leave `BILLING_ENFORCE_LIMITS=false` until
[the count](#turning-enforcement-on). Run
`docker compose up -d --wait --wait-timeout 300`, then check that the same log
line as on VAL prints nothing.

### Account deletion refused with 409

`DELETE /api/me` answers 409 `billing_unavailable` when an account's purchase
may still bill and this deployment has no Stripe keys, so it can neither ask
Stripe nor cancel anything. It happens when the two secrets were cleared after
the account subscribed. There is deliberately no force-delete.

Put the two secrets back if possible (`.env`, then `docker compose up -d`):
the deletion then cancels at Stripe by itself. Otherwise, confirm at Stripe
that nothing bills any more, then record it here:

1. **[VPS]** Find the account's rows (several accounts can have one address:
   check `user_id`):

   ```bash
   cd /opt/wishlist
   pg <<'SQL'
   select e.user_id, e.external_id, e.status, c.customer_id
   from users u
   join entitlements e on e.user_id = u.id
   left join billing_customers c on c.user_id = u.id and c.source = e.source
   where u.email = '<account-address>';
   SQL
   ```

2. **[Stripe]** In the account this deployment used, open the customer
   `customer_id` (or search for `external_id`) and make sure **every**
   subscription is cancelled. Cancel any that is not, immediately, and expire
   any open Checkout session.
3. **[VPS]** Only then, after a dump (`docker compose restart backup`, which
   replaces today's file: see [Backups](#backups)):

   ```bash
   pg <<'SQL'
   update entitlements set status = 'ended', updated_at = now()
   where user_id = '<user-id>' and status <> 'ended';
   SQL
   ```

4. **[dev]** Ask the person to delete their account again. With every row
   ended, deletion no longer needs the gateway.

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
| `docker stats` shows Wishlist's containers within their limits (about 1.1 GB) | [10. Verifying](#10-verifying-the-installation), memory |
| No secret, host name or key is committed | [10. Verifying](#10-verifying-the-installation), last block |

## Open items

- [ ] **Wishlist's own domain.** PROD and VAL run for now on two subdomains
      of TraxJourney's domain. Moving to an own domain means: DNS records,
      the Caddy blocks ([step 6](#6-caddy)), `PUBLIC_BASE_URL` in both `.env`,
      the Google sign-in origins ([step 11](#11-google-sign-in)), and the old
      hosts redirecting to the new ones so share links already sent keep
      working.
- [ ] **Off-site backups** of the dumps **and** the media directory (shared
      problem with TraxJourney). Today both are lost with the VPS, its disk or
      OVH's datacenter. Needed before PROD holds real users' data.
      Two constraints from the media purge: the copy's retention joins the
      purge horizon, and media restored from it must get the current time as
      modification time (copy without preserving times, or touch after), since
      the purge reads an old modification time as "not live". The purge also
      touches every live image daily, so a time-based sync sees every file
      change each day.
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
- [x] **R2-5, media purge vs. dump retention**: the purge follows the oldest
      kept dump, not a number of days (gift images plan
      [D9](plans/GIFT_IMAGES_PLAN.md)); see [Media](#media).
- [ ] **Memory on a shared 4 GB host.** Wishlist's limits keep its own
      containers in bounds, but a TraxJourney peak can still exhaust the host.
