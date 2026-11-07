# DevOps foundation — DEV, VAL and PROD

## Problem

Wishlist is restarting from an empty repository. Before any feature is built,
the owner wants the full path from a laptop to production to work: a local
development environment, a validation environment (VAL) and production (PROD)
on the existing OVH VPS that already serves TraxJourney. Building features
first and deployment later would mean the first deploy happens under feature
pressure, with migrations and data already at stake.

The deliverable is a **walking skeleton**: a server and a client that do almost
nothing (report their version and whether the database is reachable), but go
through every stage — local run, tests, CI, image build, VAL auto-deploy,
manual PROD deploy, nightly backup and restore — exactly as real features will.

## Current state

- This repository: only the working setup (`.claude/`, `docs/`, `CLAUDE.md`).
  No code. The need description (`docs/NEEDS.md`) is a draft.
- The VPS (documented in `E:\Dev\TraxJourney\docs\DEPLOYMENT_VPS.md`): OVH
  VPS-1, 2 vCore, 4 GB RAM, 40 GB NVMe, Debian 12 with Docker. Hardened (key-only
  SSH, `ufw` allowing 22/80/443, a `<deploy-user>` in the `docker` group, GHCR
  login with a read-only PAT). Caddy is the reverse proxy for every hostname,
  from `/etc/caddy/Caddyfile`.
- Already in use on the VPS: TraxJourney prod (`/opt/traxjourney`,
  `127.0.0.1:8000`), val (`/opt/traxjourney-val`, `127.0.0.1:8001`), and the
  `webhook` systemd unit on `127.0.0.1:9999` that auto-deploys TraxJourney val.
- TraxJourney's pipeline, which this plan reuses in shape:
  - `.github/workflows/docker-build.yml`: a `validation` tag builds
    `:validation`; a `v*` tag builds `:latest`, `:<sha>` and `:<tag>`.
  - `vps/webhook/` (`hooks.yaml.example`, `deploy-validation.sh`,
    `webhook.service`): GitHub's `workflow_run` delivery triggers a pull and
    restart of val, then the script polls `/api/version` for the built commit.
  - `deploy.ps1` + `deploy.env.example`: manual, verified deploys from the
    Windows dev machine.
  - `Dockerfile` + `entrypoint.sh`: one image serving the API and the Flutter
    web build; migrations run on start.
  - Backups: an in-app nightly job writes database copies to
    `/opt/traxjourney/db/backups/` (02:00 UTC, last 30 kept). They stay on the
    VPS: off-site backups are an open item in its runbook.
- Local machine: Docker 29.9 with Compose v5.6, uv 0.13.4, Python 3.14,
  Flutter 3.47 (stable).

## Decisions

- **D1 — Stack.** Python 3.14, FastAPI, SQLAlchemy 2.0 (typed declarative,
  synchronous sessions) with psycopg 3, Alembic, PostgreSQL; Flutter for web,
  Android and iOS; uv for Python dependencies. Chosen by the owner ahead of the
  need description converging, to reuse TraxJourney's experience and VPS.
  Sync sessions rule out async SQLAlchemy: FastAPI runs sync endpoints in a
  thread pool, which is ample at the envelope's scale and simpler to test.
  Feature work still waits for `docs/NEEDS.md` to be agreed.
- **D2 — PostgreSQL, one container per environment.** DEV (local), VAL and
  PROD each run their own Postgres container, defined in their own compose
  file, with their own volume and credentials. The image tag is pinned to one
  exact version, identical in DEV, CI, VAL and PROD. Rules out SQLite
  (concurrent reservations need row-level locking) and a shared Postgres server
  (VAL would share a process, upgrades and a failure domain with PROD).
- **D3 — Postgres is never published on the VPS.** The VAL and PROD database
  containers have no `ports:`; the app reaches them over the compose network.
  Only DEV publishes Postgres, on `127.0.0.1`. Rules out a host-reachable
  database, which Docker's iptables rules would expose past `ufw`.
- **D4 — Repository layout.** `server/` (FastAPI app, Alembic, tests,
  `pyproject.toml`, `uv.lock`), `client/` (Flutter project), `deploy/` (VPS
  compose files, Caddy snippet, webhook, backup), and the `Dockerfile` and dev
  scripts at the root. Keeps client and server work separable (DELIVERY.md S3).
  Rules out TraxJourney's server-at-root layout.
- **D5 — One image.** A multi-stage `Dockerfile` builds the Flutter web client
  and serves it from the FastAPI app, next to `/api/*`. Same as TraxJourney:
  one artefact per version, so the client and the server can never be out of
  step on the web. Rules out a separate web container or CDN.
- **D6 — Pipeline identical to TraxJourney's.** Images go to
  `ghcr.io/rui-nar/wishlist`. Pushing the floating `validation` tag builds
  `:validation`, and VAL redeploys itself through a webhook. Pushing `v*` builds
  `:latest`, `:<sha>` and `:<version>`; PROD is deployed by hand with
  `deploy.ps1 -Target Prod`, which verifies `/api/version` afterwards. The
  manual gate before PROD is deliberate.
- **D7 — Separate webhook instance.** Wishlist gets its own systemd unit
  (`wishlist-webhook`, `127.0.0.1:9998`) with its own `hooks.yaml` and secret
  under `/opt/wishlist-val/webhook/`. Rules out adding a hook to TraxJourney's
  instance, which would couple the two projects' deploys, secrets and restarts.
- **D8 — Ports on the VPS.** PROD app `127.0.0.1:8010`, VAL app
  `127.0.0.1:8011`, webhook `127.0.0.1:9998`. Always bound to loopback (§1 of
  TraxJourney's runbook). The owner confirms they are free before installing.
- **D9 — Backups like TraxJourney's.** A `backup` service in the PROD compose
  file (the same pinned Postgres image) runs `pg_dump -Fc` once when it starts
  and then every night at 02:00 UTC, into
  `/opt/wishlist/backups/wishlist_<YYYY-MM-DD>.dump`, and keeps the last 30.
  Its loop sleeps until the next 02:00 and survives a failed dump (it logs and
  waits for the next run). A sidecar rather than an in-app job: the dump needs
  the Postgres client tools, which belong in the Postgres image rather than the
  app's. A failure must be visible without reading logs: the service's
  healthcheck fails when no dump is newer than 26 hours, so `docker ps` shows
  it `unhealthy` (review R1-1). VAL can be seeded from the newest dump (a
  documented one-shot), and that seed is also the restore test. Off-site
  copies remain open, as for TraxJourney.
- **D14 — Postgres data in named volumes; backups in a bind mount owned by
  uid 999.** The database directory is a Docker named volume (the image sets
  its own ownership on it). The backups directory must be reachable from the
  host, so it is a bind mount, created by the runbook as `999:999` (the
  `postgres` user of the official image), and the `backup` service runs with
  `user: "999:999"`. Rules out bind-mounted PGDATA, whose ownership the
  Windows acceptance runs could never exercise (review R1-5).
- **D15 — Migrations keep the previous release working.** Every migration is
  backward-compatible with the release before it (expand, then contract in a
  later release), so rolling PROD back one version never needs
  `alembic downgrade`. A release that cannot follow this says so in its plan
  and in the runbook's rollback notes (review R1-6).
- **D16 — Postgres major versions move only by hand.** Dependabot ignores
  major updates of the Postgres image; a major upgrade follows the runbook's
  dump-and-restore procedure (review R1-7).
- **D17 — A Linux smoke test of the VPS setup in CI.** A workflow builds the
  image and runs the PROD and VAL compose files on an Ubuntu runner, with the
  directories created exactly as the runbook says: first boot, a backup,
  seeding VAL from it. Windows Docker Desktop cannot reproduce Linux
  ownership or the Postgres first-boot sequence (reviews R1-2, R1-4, R1-5).
- **D18 — Uploaded files on disk, immutable, purged late.** Gift images
  (`docs/NEEDS.md`) live in a media directory per environment,
  `/opt/wishlist-media/prod` and `/opt/wishlist-media/val` (one parent, so a
  single mount covers both when seeding, review R2-3), bind-mounted at
  `/app/media` and owned by the app's fixed uid `10001`. The image sets
  `MEDIA_DIR=/app/media`, and no deploy `.env` overrides it, so the app writes
  where the mount is (review R2-1). Binding rules for the
  feature that will write them:
  - a file is never modified: it is named by its content hash;
  - deleting a gift removes only the database reference; a file is purged
    only once it has been unreferenced for longer than the dump retention
    (30 days), so restoring any kept dump finds every file it references.

  That makes the media directory its own protection against logical errors (a
  bad migration, an accidental deletion) without keeping 30 copies of the
  images on a 40 GB disk. Like the dumps, it does not survive losing the VPS
  (off-site copies stay open). Seeding VAL hard-links PROD's files into VAL's
  directory (same filesystem, no extra space; safe because files are never
  modified). The link step runs as uid `10001` in a one-shot container that
  mounts `/opt/wishlist-media` once: Debian's `fs.protected_hardlinks=1`
  forbids the deploy user from linking files it does not own, and links
  across two separate mounts fail (review R2-3). This plan provisions the directory, its ownership, the
  configuration, a writability check and the runbook; uploading, fetching and
  purging belong to the gifts feature. Rules out images in PostgreSQL (each
  nightly dump would carry them all, 30 times) and object storage (a new
  external service and cost, worth revisiting for off-site copies).
- **D10 — Configuration.** Every environment reads its settings from
  environment variables (`pydantic-settings`); `.env.example` lists them all.
  Real `.env` files are never committed, on the dev machine or the VPS, and
  compose files reference them with `env_file:`, never with values inline.
  `APP_ENV` is `dev`, `validation` or `production`.
- **D11 — Version.** The image is built with `APP_VERSION` (`v1.2.3`, or
  `validation-<short sha>`; `dev` locally). `/api/version` returns it with
  `APP_ENV`. The client shows it. Deploy checks compare it with what was built.
- **D12 — Tests against real Postgres.** Server tests run against PostgreSQL,
  never SQLite: the local DEV database locally, a Postgres service container in
  CI. The reservation logic later depends on Postgres semantics.
- **D13 — Hostnames are placeholders.** Until the domain is chosen, files use
  `<prod-host>` and `<val-host>`. Everything except the go-live steps of the
  runbook can be built and tested without them.

## Review envelope

REVIEW.md defaults apply, with these additions:

- **Co-tenancy.** The VPS also runs TraxJourney prod and val. Wishlist must
  not take their ports, change their compose projects, reuse their secrets or
  webhook, or break the shared Caddyfile. A Caddy reload that fails validation
  takes down every site on the host, TraxJourney's included.
- **Resources.** 4 GB RAM and 40 GB disk shared with TraxJourney (API, workers,
  Alloy). Wishlist's memory limits add up to about 1 GB (owner's decision):
  PROD app 256 MB, PROD Postgres 256 MB, VAL app 192 MB, VAL Postgres 192 MB,
  backup 64 MB. Postgres is configured to fit its limit (`shared_buffers`,
  `max_connections`). Hitting a limit kills only that container, which
  restarts; a TraxJourney peak exhausting the host is outside what Wishlist
  can prevent. Backups rotate so the disk cannot fill. Media grow with use:
  per-account image limits are open in `docs/NEEDS.md`, so until they exist
  the runbook's daily check includes free disk space.
- **New public endpoint.** `https://<val-host>/gh-webhook/...` accepts POSTs
  from anyone. Only deliveries with a valid `X-Hub-Signature-256` for the
  Wishlist secret, from `rui-nar/Wishlist`'s build workflow, may deploy.
- **External services.** GitHub Actions (pushes to GHCR with the workflow's
  own `GITHUB_TOKEN`, no stored push token) and GHCR (the VPS pulls with a read-only token). The
  repository is **public**: nothing committed may contain a secret, a real
  host name of the deploy user, or a key.
- **Trusted.** The VPS host, its `.env` files, the deploy user and the owner.

## Boundaries crossed

- **Shared VPS configuration:** new blocks in `/etc/caddy/Caddyfile`, a new
  systemd unit, three new directories under `/opt`
  (`/opt/wishlist`, `/opt/wishlist-val`, `/opt/wishlist-media`). TraxJourney's files are not
  edited apart from appending the Caddy blocks.
- **Schema:** an initial, empty Alembic revision becomes the root every later
  migration descends from. No tables.
- **API contract:** `/api/version` and `/api/health` become the first
  endpoints shipped clients may call. Their response shape is kept stable.
- **Stored data:** none yet.

## Conventions

- Every file that runs on the VPS (`deploy/`, scripts it calls) is LF-only;
  `.gitattributes` enforces it. A CRLF shebang broke TraxJourney (its #190).
- Nothing on the VPS runs as root except the one-time setup steps in the
  runbook, and the official Postgres image's own entrypoint (it drops to the
  `postgres` user itself).
- Every service in every compose file has `restart: unless-stopped`, and every
  Postgres healthcheck is `pg_isready -h localhost -U "$POSTGRES_USER" -d
  "$POSTGRES_DB"`: without `-h localhost` it reports healthy while the image's
  first-boot init server listens on the unix socket only (review R1-4).
- Each unit adds or updates its section of `docs/DEVELOPMENT.md` or
  `docs/DEPLOYMENT.md` only where its Scope lists them.
- Where a TraxJourney file is the example, copy its *reasons* (comments that
  explain a constraint) when the same constraint applies, and drop
  TraxJourney-specific parts (Strava, rail data, workers, SQLite, the NAS).

## Open decisions

| Decision | Affects | Needed by |
|---|---|---|
| Domain and hostnames for PROD and VAL | Caddy, CORS origin, OAuth redirect URIs later | Go-live steps of the runbook (U8); nothing else |
| Off-site backups (shared problem with TraxJourney) | Recovery if the VPS or OVH datacenter is lost | Before PROD holds real users' data |
| Android application id and iOS bundle id (`<reverse-domain>.wishlist`) | Cannot change after the first store upload | Before the first store build; U2 uses a placeholder |
| Observability (reuse TraxJourney's Loki/Prometheus on the NAS) | Logs and metrics for VAL/PROD | A later plan |

Before delivery starts, a separate commit updates the policies for the chosen
stack (REVIEW.md E1/E4; DELIVERY.md §2 folders, sensitive paths and checks;
CLAUDE.md's current stage), as REVIEW.md §8 and DELIVERY.md §7 require.

## Execution units

### Wave 1

#### U1 — Server skeleton

- **Goal:** A FastAPI app in `server/` with `/api/version` and `/api/health`,
  settings from the environment, and Alembic initialised against PostgreSQL.
- **Scope:** `server/**`, `.python-version`, `.gitattributes`, `.gitignore`.
- **Context:** `E:\Dev\TraxJourney\pyproject.toml`, `alembic.ini`, `alembic/env.py`
  for the uv and Alembic setup; D1, D10, D11, D12 of this plan.
- **Do:**
  1. `server/pyproject.toml` managed by uv: fastapi, uvicorn, sqlalchemy 2,
     psycopg 3 (binary), alembic, pydantic-settings; dev group: pytest, httpx.
     Commit `server/uv.lock`. `.python-version` at the root: `3.14`.
  2. `server/app/settings.py`: `DATABASE_URL`, `APP_ENV`, `APP_VERSION`
     (default `dev`), `FRONTEND_ORIGIN` (comma-separated list of origins),
     `MEDIA_DIR` (D18; default `./media` locally). The app creates
     `MEDIA_DIR` on startup when it is missing (a no-op on the VPS, where it is
     a mount; review R2-4).
     `CORSMiddleware` allows exactly those origins (none when empty), so the
     DEV client served by `flutter run` on its own port can call the API
     (review R1-3).
  3. `server/app/db.py`: engine and session factory; a typed declarative
     `Base` for future models.
  4. `server/app/main.py`: the app; `GET /api/version` →
     `{"version": ..., "env": ...}`; `GET /api/health` → 200
     `{"status": "ok", "database": "ok", "media": "ok"}` after a `SELECT 1`
     and a write-then-delete of a temporary file in `MEDIA_DIR`; otherwise 503
     with `"status": "error"` and the failing part (`"database":
     "unreachable"` or `"media": "not writable"`), without leaking the error
     text.
  5. Alembic in `server/alembic/`, `env.py` reading `DATABASE_URL` and the
     `Base` metadata; one empty baseline revision.
  6. `.gitattributes`: `* text=auto`, and `eol=lf` for `*.sh`, `deploy/**`,
     `Dockerfile`.
  7. Extend the root `.gitignore`: Python caches (`__pycache__/`,
     `.pytest_cache/`, `.ruff_cache/`, `.venv/`), `client/build/`,
     `*.dump` (review R1-10), `media/` (review R2-4).
- **Acceptance:** with a Postgres reachable at `DATABASE_URL`:
  `uv run --directory server pytest` passes, including
  `tests/test_version.py`, `tests/test_health.py` (DB up → 200; unreachable
  URL → 503 with no exception text in the body; read-only `MEDIA_DIR` → 503
  `media: not writable`) and
  `tests/test_migrations.py` (`alembic upgrade head` then `alembic check`
  on an empty database) and `tests/test_cors.py` (an allowed origin gets
  `Access-Control-Allow-Origin`; another origin does not).
  `uv run --directory server ruff check` passes (add ruff to the dev group).
  `git status` after the test run shows no cache files.
- **Out of scope:** models, auth, serving the web client (U4), logging setup.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3); Python 3.14 lacks a
  wheel for a dependency.
- **Depends on:** —

#### U2 — Client skeleton

- **Goal:** A Flutter project in `client/` that shows its own version and the
  server's `/api/version`.
- **Scope:** `client/**`.
- **Context:** `E:\Dev\TraxJourney\flutter_client\` for project structure and
  `--dart-define` use; D5, D11.
- **Do:**
  1. `flutter create --project-name wishlist --org <placeholder> --platforms
     web,android,ios client`. Note the placeholder org in `client/README.md`.
  2. `API_BASE_URL` (default empty = same origin) and `APP_VERSION`
     (default `dev`) from `--dart-define`.
  3. One screen: app version, server version and env, or a clear error when the
     server is unreachable. `http` package for the call.
  4. `analysis_options.yaml` with `flutter_lints`.
- **Acceptance:** `flutter analyze` (no issues) and `flutter test` pass in
  `client/`, including a widget test with a mocked HTTP client for the success
  and unreachable cases; `flutter build web --release` succeeds.
- **Out of scope:** state management libraries, routing, theming, sign-in,
  store configuration.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** —

### Wave 2

#### U3 — Local DEV environment

- **Goal:** One command starts Postgres, the API with reload and the Flutter
  client against it on the Windows dev machine.
- **Scope:** `docker-compose.dev.yml`, `dev.ps1`, `Load-DotEnv.ps1`,
  `.env.example`, `docs/DEVELOPMENT.md`, `docs/README.md`.
- **Context:** `E:\Dev\TraxJourney\dev.ps1`, `Load-DotEnv.ps1`,
  `.env.example`; D2, D10, D12.
- **Do:**
  1. `docker-compose.dev.yml`: the pinned Postgres image, named volume,
     `127.0.0.1:5432`, the healthcheck and restart policy from Conventions; a
     second database `wishlist_test` for tests created by an init script.
  2. `.env.example` with every setting from U1 and comments, including
     `FRONTEND_ORIGIN=http://localhost:5500`; `.env` is already ignored.
  3. `dev.ps1`: load `.env`, `docker compose -f docker-compose.dev.yml up -d
     --wait`, `alembic upgrade head`, uvicorn with `--reload` on `:8000`, and
     `flutter run -d chrome --web-port 5500` with
     `API_BASE_URL=http://localhost:8000` (the fixed port matches
     `FRONTEND_ORIGIN`, review R1-3);
     `-Test` runs the server tests against `wishlist_test`; `-Reset` drops and
     recreates the dev volume after a confirmation prompt.
  4. `docs/DEVELOPMENT.md`: prerequisites, first run, daily use, tests,
     resetting; link from `docs/README.md`.
- **Acceptance:** from a fresh clone with `.env` copied from `.env.example`:
  `.\dev.ps1 -Test` passes; `.\dev.ps1` serves `GET
  http://localhost:8000/api/health` → 200 with `database: ok`; and the client
  at `http://localhost:5500` shows the server's version (checked by hand, or
  with `curl -H "Origin: http://localhost:5500"` showing the allow-origin
  header). Repeat after `.\dev.ps1 -Reset` to cover a first boot.
- **Out of scope:** the production image, CI.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U1, U2.

#### U4 — Container image

- **Goal:** A production image that serves the API and the web client, and
  migrates the database on start.
- **Scope:** `Dockerfile`, `entrypoint.sh`, `.dockerignore`,
  `server/app/main.py` (static file mount only), `server/tests/test_static.py`.
- **Context:** `E:\Dev\TraxJourney\Dockerfile` and `entrypoint.sh` (keep the
  uv pinning, keep-alive and forwarded-IPs reasoning); D5, D11.
- **Do:**
  1. Multi-stage: a Flutter stage builds `client/` for web with
     `APP_VERSION` and `--no-web-resources-cdn`; a `python:3.14-slim` stage
     installs `server/` with `uv sync --locked --no-default-groups` and copies
     the web build in.
  2. `entrypoint.sh`: `alembic upgrade head`, then uvicorn with
     `--timeout-keep-alive 300 --proxy-headers --forwarded-allow-ips
     "${FORWARDED_ALLOW_IPS:-127.0.0.1}"`. Runs as a non-root user with the
     fixed uid and gid `10001`, `/app/media` exists and belongs to it, and
     the Dockerfile sets `ENV MEDIA_DIR=/app/media` (D18, review R2-1).
  3. The app serves the web build at `/` when the directory exists, `/api/*`
     taking precedence; unknown non-API paths return `index.html`.
  4. OCI label `org.opencontainers.image.source=https://github.com/rui-nar/Wishlist`.
- **Acceptance:** `docker build --build-arg APP_VERSION=test-1 -t
  wishlist:test .` succeeds; run against the DEV Postgres, `/api/version`
  reports `test-1`, `/` returns the client's `index.html`, `/api/health` is
  200 with `media: ok`; `server/tests/test_static.py` passes;
  `docker run --rm --entrypoint id wishlist:test` prints `uid=10001`;
  `docker run --rm --entrypoint printenv wishlist:test MEDIA_DIR` prints
  `/app/media`.
- **Out of scope:** CI, compose files for the VPS.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U1, U2.

### Wave 3

#### U5 — CI

- **Goal:** Tests on every push and pull request; images published on
  `validation` and `v*` tags.
- **Scope:** `.github/workflows/test.yml`, `.github/workflows/docker-build.yml`,
  `.github/dependabot.yml`.
- **Context:** `E:\Dev\TraxJourney\.github\workflows\test.yml` and
  `docker-build.yml` (tag selection, version naming, GHCR login); D6, D11, D12.
- **Do:**
  1. `test.yml` on push to `master`, on pull requests and on
     `workflow_dispatch` (so any branch can be run by hand): a server job with a
     Postgres service container (same pinned image), `uv sync --locked`,
     `alembic upgrade head` + `alembic check`, ruff, pytest; a client job with
     `flutter analyze` and `flutter test`.
  2. `docker-build.yml` on tags `v*` and `validation`, image
     `ghcr.io/rui-nar/wishlist`, the same tag selection as TraxJourney's
     (`:validation` only for `validation`; `:latest`, `:<sha>`, `:<tag>` for
     `v*`), `APP_VERSION` passed as a build arg. GHCR login uses the built-in
     `GITHUB_TOKEN` with `permissions: packages: write` (owner's decision: no
     personal token to store or renew); the image's OCI source label links
     the package to the repository. Workflow name exactly
     `Build and publish Docker image` (the webhook matches on it).
  3. Dependabot for uv, pub, docker and github-actions, weekly, with major
     updates of the Postgres image ignored (D16).
- **Acceptance:** both workflows pass `actionlint` (run it locally with
  `docker run --rm -v ${PWD}:/repo -w /repo rhysd/actionlint:latest`); the
  test workflow passes on a draft pull request opened from the unit's branch
  (review R1-8). The image build is
  verified at integration by pushing the `validation` tag.
- **Out of scope:** mobile release workflows.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U3, U4.

#### U6 — VPS environments and backup

- **Goal:** Compose files for PROD and VAL, each with its own Postgres, and the
  nightly backup.
- **Scope:** `deploy/prod/**`, `deploy/val/**`, `deploy/caddy/Caddyfile.snippet`,
  `deploy/backup/**`, `deploy/smoke/**`, `.github/workflows/deploy-smoke.yml`.
- **Context:** TraxJourney runbook §1–§3 and §5 (layout, loopback ports,
  forwarded IPs, val seeding); D2, D3, D8, D9, D14, D17, D18; Conventions
  (healthcheck, restart policy); the memory budget in the Review envelope.
- **Do:**
  1. `deploy/prod/docker-compose.yml`: `app` (`:latest`, `127.0.0.1:8010:8000`,
     `env_file: .env`, depends on `db` healthy), `db` (pinned Postgres, named
     volume, no `ports:`, `shared_buffers` and `max_connections` sized for its
     limit), `backup` (D9, D14). The app mounts `/opt/wishlist-media/prod` at
     `/app/media` (D18); `.env.example` does not set `MEDIA_DIR` and says why. Memory limits as in the Review envelope;
     healthchecks and restart policies as in Conventions.
     `deploy/prod/.env.example`.
  2. `deploy/val/`: the same with `:validation`, `127.0.0.1:8011`, its own
     volume, media directory and credentials (a different database role from
     PROD's) and no `backup`; plus `seed-from-prod.sh`, which stops VAL's app,
     drops and recreates VAL's database, restores the newest PROD dump with
     `pg_restore --no-owner --no-privileges` as VAL's role, hard-links PROD's
     media files into VAL's media directory without overwriting, as uid
     `10001` in a one-shot container mounting `/opt/wishlist-media` once
     (D18, review R2-3), and
     starts the app again so its migrations bring the schema to VAL's head
     (review R1-2).
  3. `deploy/backup/backup.sh` and its loop: dump once on start, then sleep
     until the next 02:00 UTC; `pg_dump -Fc` to a temp name then rename;
     delete all but the 30 newest; on failure log and keep looping.
     `deploy/backup/healthcheck.sh`: fails when no `wishlist_*.dump` is newer
     than 26 hours (review R1-1).
  4. `deploy/caddy/Caddyfile.snippet`: blocks for `<prod-host>` → 8010,
     `<val-host>` → 8011 and `/gh-webhook/*` on val → 9998.
  5. `.github/workflows/deploy-smoke.yml` (pull requests touching
     `deploy/**`, `Dockerfile`, `entrypoint.sh`, `server/alembic/**`; and
     `workflow_dispatch`), driven by `deploy/smoke/run.sh`: build the image,
     create the PROD and VAL directories with the ownership the runbook will
     prescribe, bring both stacks up from a fresh volume, wait for
     `/api/health` on 8010 and 8011 (including `media: ok`, which proves uid
     10001 can write the media directories as the runbook creates them),
     check the backup service turns healthy with a dump present, write a test
     file **through PROD's app container** (`docker compose exec app sh -c
     'echo probe > "$MEDIA_DIR/smoke-probe"'`) and check it appears in
     `/opt/wishlist-media/prod` on the host owned by uid 10001 (review R2-1),
     run `seed-from-prod.sh` (as a non-root user, like the deploy user), and
     check VAL is healthy again and has the test file (D17, D18, review
     R2-3).
- **Acceptance:** `docker compose ... config` succeeds for both stacks with
  the example `.env`; `shellcheck deploy/**/*.sh` is clean; the
  `deploy-smoke` workflow passes on a draft pull request from the unit's
  branch. The run's link is in the report.
- **Out of scope:** installing anything on the VPS (owner steps, U8),
  off-site backup.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3); the memory budget
  cannot hold a healthy stack.
- **Depends on:** U4.

#### U7 — Deploy automation

- **Goal:** VAL redeploys itself on a new `:validation` image; PROD and VAL can
  be deployed and verified by hand from Windows.
- **Scope:** `deploy/webhook/**`, `deploy.ps1`, `deploy.env.example`.
- **Context:** `E:\Dev\TraxJourney\vps\webhook\` (all three files),
  `deploy.ps1`, `deploy.env.example`; this repository's `Load-DotEnv.ps1`
  (from U3, reused as is); D6, D7, D8, D11.
- **Do:**
  1. `deploy/webhook/hooks.yaml.example`: TraxJourney's rules with
     `rui-nar/Wishlist`, empty secret, command
     `/opt/wishlist-val/webhook/deploy-validation.sh`.
  2. `deploy/webhook/deploy-validation.sh`: lock, `docker compose pull`,
     `up -d`, poll `http://127.0.0.1:8011/api/version` for
     `validation-<short sha>` for up to 5 minutes, log to
     `/opt/wishlist-val/webhook/deploy.log`.
  3. `deploy/webhook/wishlist-webhook.service`: port 9998, `<deploy-user>`
     placeholder.
  4. `deploy.ps1 -Target Val|Prod`: SSH to the host from `deploy.env`, check the
     host's compose names the expected image, pull, `up -d`, then check
     `<url>/api/version` and `/api/health`. Prod asks for confirmation and
     refuses an image tag that is not a `v*` release.
- **Acceptance:** `shellcheck deploy/webhook/deploy-validation.sh` clean;
  `webhook -hooks deploy/webhook/hooks.yaml.example -verbose` parses it
  (run in a container); `Invoke-ScriptAnalyzer deploy.ps1` has no errors;
  `deploy.ps1 -WhatIf -Target Prod` prints the commands without connecting.
- **Out of scope:** prod auto-deploy, notifications.
- **Latitude:** decided at routing.
- **Escalate if:** a file outside Scope is needed (X3).
- **Depends on:** U3 (`Load-DotEnv.ps1`), U4. The ports and directories it uses are fixed by D7 and
  D8, not by U6 (review R1-9).

### Wave 4

#### U8 — Deployment runbook

- **Goal:** `docs/DEPLOYMENT.md` lets the owner install VAL and PROD on the VPS
  next to TraxJourney, deploy, back up and restore.
- **Scope:** `docs/DEPLOYMENT.md`, `docs/README.md`.
- **Context:** `E:\Dev\TraxJourney\docs\DEPLOYMENT_VPS.md` (structure and
  gotchas: Caddy default block, DNS before reload, loopback ports, GHCR
  read-only token, webhook checklist); every file from U5–U7.
- **Do:** sections for prerequisites (what TraxJourney's setup already
  provides), checking ports and free RAM/disk, directories and `.env` files
  (secrets generated with `openssl rand -hex 32`), Caddy (append the snippet,
  `caddy validate` before every reload, since a bad reload takes TraxJourney
  down too), the GHCR package (built with `GITHUB_TOKEN`, no secret; its visibility) and the webhook, the first VAL
  deploy, the first PROD release, backups (where, rotation, the `backup`
  container's health as the daily check, `chown 999:999` of the backups
  directory), media (`chown 10001:10001` of both media directories, what D18
  protects against and what it does not, free disk space as part of the daily
  check), restoring and seeding VAL, rollback (one version back is safe by
  D15; point the compose back to `:latest` afterwards, or the next
  `deploy.ps1` refuses), upgrading Postgres across a major version (dump,
  new volume, restore; D16), and an Open items list (domain, off-site
  backups).
- **Acceptance:** every command in the runbook names a file that exists in the
  repository or a standard tool; every placeholder is listed in one table at the
  top; the Definition of done below can be checked by following it.
- **Out of scope:** observability, mobile store releases.
- **Latitude:** decided at routing.
- **Escalate if:** a step needs a file outside Scope (X3).
- **Depends on:** U5, U6, U7.

## Definition of done

- From a fresh clone on the dev machine, `.\dev.ps1` serves the client against a
  local Postgres and the client shows the server's version; `.\dev.ps1 -Test`
  passes.
- The `deploy-smoke` workflow passes: both stacks boot from empty volumes on
  Linux, a backup is taken, and VAL is seeded from it.
- A pull request runs server and client tests in CI against PostgreSQL.
- Pushing the `validation` tag publishes `ghcr.io/rui-nar/wishlist:validation`,
  and within 5 minutes `https://<val-host>/api/version` reports
  `validation-<short sha>` with no manual step.
- Pushing `v0.1.0` publishes `:latest`, `:<sha>` and `:v0.1.0`;
  `deploy.ps1 -Target Prod` deploys it and reports `v0.1.0` from
  `https://<prod-host>/api/version` and 200 from `/api/health`, including
  `media: ok`.
- `docker ps` on the VPS shows no Wishlist port bound outside `127.0.0.1`, and
  no Postgres port published at all.
- TraxJourney prod and val answer `/api/version` as before throughout.
- A nightly dump exists in `/opt/wishlist/backups/` after the first night; at
  most 30 are kept; the `backup` container is `healthy`; seeding VAL from it
  succeeds.
- `docker stats` shows Wishlist's containers within their memory limits
  (about 1 GB in total).
- No secret, host name or key is committed (`git grep` for the `.env` values
  finds nothing).
