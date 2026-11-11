# One image per version: the API and the web client it was released with
# (plan D5), so the two can never be out of step on the web.

# uv, pinned to an exact version so every build installs with the same tool.
# Dependabot's docker updates move this tag; the setup-uv `version:` in the CI
# workflows must move with it.
FROM ghcr.io/astral-sh/uv:0.13.4 AS uv

# --- Web client -------------------------------------------------------------
# The Flutter SDK is cloned at a git tag rather than taken from
# ghcr.io/cirruslabs/flutter: that image lagged real stable by months and
# publishes no exact version tags (TraxJourney's experience). Keep the tag
# equal to the SDK on the dev machine, and move both together.
FROM debian:bookworm-slim AS web

ARG FLUTTER_TAG=3.47.1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git unzip xz-utils zip \
 && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch "${FLUTTER_TAG}" \
        https://github.com/flutter/flutter.git /opt/flutter \
 && git config --global --add safe.directory /opt/flutter
ENV PATH="/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:${PATH}"
RUN flutter config --no-analytics --no-cli-animations \
 && flutter precache --web

WORKDIR /client
# The pub files first, so the dependency layer is cached across code changes.
COPY client/pubspec.yaml client/pubspec.lock ./
# pubspec.yaml depends on the vendored packages in third_party/ by path, so
# pub get needs them present; they change rarely, so the layer stays cached.
COPY client/third_party/ third_party/
RUN flutter pub get --enforce-lockfile
COPY client/ ./

# The version the client shows (plan D11): v1.2.3, validation-<short sha>, or
# dev for a local build. Declared after the SDK and pub layers so a new version
# reuses them.
ARG APP_VERSION=dev
# --no-web-resources-cdn: CanvasKit comes from this build, not www.gstatic.com.
RUN flutter build web --release --no-web-resources-cdn \
        --dart-define=APP_VERSION="${APP_VERSION}"

# --- Server -----------------------------------------------------------------
FROM python:3.14-slim

# The source label is what links a package pushed to ghcr.io back to its
# repository.
LABEL org.opencontainers.image.source="https://github.com/rui-nar/shushgift" \
      org.opencontainers.image.title="Shush Gift" \
      org.opencontainers.image.description="Shush Gift server: the API and the web client"

# Python dependencies come from uv.lock. --locked fails the build if the lock
# does not match pyproject.toml instead of resolving afresh, and
# --no-default-groups leaves the dev group (pytest, ruff) out. The venv is
# /app/server/.venv on the base image's own Python; putting its bin first on
# PATH makes `alembic` and `uvicorn` in entrypoint.sh, and
# `docker run --entrypoint python`, use it. The lock files are copied before
# the code so this layer is cached across code-only changes.
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_NO_CACHE=1 \
    PATH="/app/server/.venv/bin:$PATH"
WORKDIR /app/server
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --locked --no-default-groups

COPY server/alembic.ini ./
COPY server/alembic/ alembic/
COPY server/app/ app/
# app.main serves this directory at / (/app/web, next to /app/server).
COPY --from=web /client/build/web/ /app/web/

# The app runs as a fixed uid and gid, 10001, not root: the VPS media
# directories are chowned to that uid, so it must not move between releases
# (plan D18). The code and the venv stay root-owned, read-only to the app.
# /app/media is where the VPS mounts the environment's media directory; the
# directory created here is what a run without a mount writes to.
RUN groupadd --gid 10001 shushgift \
 && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin shushgift \
 && mkdir /app/media \
 && chown 10001:10001 /app/media
# Set here, and by no deploy .env, so the app always writes where the mount is
# (plan D18).
ENV MEDIA_DIR=/app/media

# Build-time version, reported by /api/version (plan D11). Last, so a new
# version reuses every layer above.
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION

COPY --chmod=0755 entrypoint.sh /entrypoint.sh
USER 10001:10001
EXPOSE 8000
CMD ["/entrypoint.sh"]
