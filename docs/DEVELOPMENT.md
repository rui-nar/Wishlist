# Development

How to run Wishlist on the Windows dev machine: PostgreSQL in Docker, the
FastAPI server and the Flutter web client on the host, started by `dev.ps1`.

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Windows Terminal (`wt`) and PowerShell 7 (`pwsh`) | any recent | `dev.ps1` opens the API and the client in two panes |
| Docker Desktop with Compose | Docker 29, Compose v5 | PostgreSQL (`docker-compose.dev.yml`) |
| uv | 0.13 or later | Python dependencies and running the server |
| Python | 3.14, installed system-wide | uv prefers it over a downloaded one (`server/pyproject.toml`) |
| Flutter | 3.47, on `PATH` | the client |
| Google Chrome | any recent | `flutter run -d chrome` |

Ports used on the dev machine: `127.0.0.1:5432` (Postgres), `8000` (API) and
`5500` (client). `dev.ps1` stops with an error if 8000 or 5500 is taken (for
example by TraxJourney's dev server, which uses the same ports) instead of
killing whatever holds them.

## First run

```powershell
Copy-Item .env.example .env   # the defaults work as they are
.\dev.ps1
```

`.env` holds every setting (see the comments in `.env.example`). It is
gitignored and never committed, here or on the VPS (plan D10).

On first run the Postgres container boots on an empty volume and creates two
databases: `wishlist` (dev) and `wishlist_test` (tests).

## Daily use

```powershell
.\dev.ps1
```

1. Loads `.env` into the environment (`Load-DotEnv.ps1`).
2. Starts Postgres with `docker compose -f docker-compose.dev.yml up -d --wait`,
   which returns once the healthcheck passes.
3. Runs `alembic upgrade head` on the dev database.
4. Opens a Windows Terminal tab with two panes:
   - **API**: `uvicorn app.main:app --reload --port 8000`, from `server/`. It
     reloads when you save Python code. Check it with
     <http://localhost:8000/api/health>.
   - **Client**: `flutter run -d chrome --web-port 5500
     --dart-define=API_BASE_URL=http://localhost:8000`, from `client/`. Press
     `r` for hot reload, `R` for hot restart and `q` to quit.

The client's port is fixed because the API only accepts cross-origin calls
from `FRONTEND_ORIGIN` (`http://localhost:5500`). If you change one, change
the other.

To stop, press `q` in the client pane and Ctrl+C in the API pane. Postgres
keeps running between sessions. To stop it:

```powershell
docker compose -f docker-compose.dev.yml stop
```

After pulling a change that adds a migration, run `.\dev.ps1` again: it
applies the migrations before starting the API.

## Tests

```powershell
.\dev.ps1 -Test
```

This starts Postgres if needed and runs `pytest` in `server/` with
`DATABASE_URL` set to `TEST_DATABASE_URL` (the `wishlist_test` database).
Tests always run against real PostgreSQL, never SQLite (plan D12). The
migration test creates and drops scratch databases, so the user needs the
CREATEDB privilege. `POSTGRES_USER` is a superuser in the official image.

The other server checks from `docs/DELIVERY.md` §2 can be run by hand, with
`.env` loaded:

```powershell
. .\Load-DotEnv.ps1; Import-DotEnv
uv run --directory server ruff check
uv run --directory server alembic upgrade head
uv run --directory server alembic check
```

The client's checks are `flutter analyze` and `flutter test` in `client/`.

## Golden tests

A golden test renders a widget and compares it pixel by pixel with a
reference PNG, the golden, committed next to the test. They are tagged
`golden` and catch visual regressions that a widget test does not see: a
colour, a spacing, a one-pixel border.

**They render on Linux only** (design-system plan D10). The same Flutter
version draws text slightly differently on Windows and Linux, so a golden made
on one fails on the other. CI compares them on Linux as part of `flutter
test`; on Windows the golden tests are skipped with a reason, so `flutter
test` on the host still passes.

To regenerate them, with Docker Desktop running:

```powershell
.\goldens.ps1          # rewrites the PNGs: flutter test --update-goldens --tags golden
.\goldens.ps1 -Check   # compares against them instead, as CI does
```

The script runs the tests in a `debian:bookworm-slim` container with Flutter
at the `Dockerfile`'s `FLUTTER_TAG`. The repository is mounted, so the PNGs
land in the working tree. The first run clones the SDK and downloads the
packages into Docker volumes (`wishlist-goldens-*`), which takes a few
minutes; later runs reuse them. `client/.dart_tool`, `client/build`,
`client/android` and `client/ios` are hidden behind container-only mounts, so
the container writes no Linux paths into the Windows tree and the host's
`flutter test` keeps working without a `flutter pub get`. To start from a
clean SDK, delete the volumes:

```powershell
docker volume rm wishlist-goldens-flutter wishlist-goldens-pub-cache wishlist-goldens-dart-tool wishlist-goldens-build
```

When a golden comparison fails in CI, the `client` job uploads the diff images
as the `golden-failures` artifact, on the run's summary page. For each failed
test it holds the master image, the test image and the differences between
them (`*_masterImage.png`, `*_testImage.png`, `*_isolatedDiff.png`,
`*_maskedDiff.png`). `.\goldens.ps1 -Check` writes the same files to
`failures/` next to the test locally; they are not gitignored, so delete them
once read.

**A golden changes only with a stated reason.** Regenerating hides any
difference, wanted or not, so a commit that changes a PNG says why in its
body (for example "the button's corner radius moves from 8 to 12"). An
unexplained golden change is a review finding.

## Resetting the database

```powershell
.\dev.ps1 -Reset                   # asks for confirmation, then starts as usual
.\dev.ps1 -Reset -Test             # reset, then run the tests
.\dev.ps1 -Reset -Confirm:$false   # without the prompt
```

`-Reset` deletes the `wishlist-dev_pgdata` volume, which holds **all dev and
test data**. The next start boots Postgres on an empty volume, as on a first
run. Do this after changing `POSTGRES_USER`, `POSTGRES_PASSWORD` or
`POSTGRES_DB` in `.env`, because the image reads them only on first boot.

The volume is mounted at `/var/lib/postgresql`, not `/var/lib/postgresql/data`.
From Postgres 18 the official image keeps its data in
`/var/lib/postgresql/18/docker` and refuses to start with a mount at the old
path.
