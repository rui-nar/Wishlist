#!/bin/sh
set -e
# Migrations run on every start, before the app serves anything, so a release
# never runs against a schema older than its code. A database at a revision
# this image does not know is ahead of it (a rollback, or VAL seeded from a
# newer PROD): app.migrate logs a warning and starts without migrating (accounts
# plan D13). That is safe because every migration keeps the previous release
# working (DevOps plan D15), so a rollback needs no downgrade. Any other
# failure stops the start, as `set -e` does here.
python -m app.migrate
# --timeout-keep-alive must exceed Caddy's upstream idle timeout (2 min by
# default). uvicorn's default of 5 s makes it the side that closes a pooled
# connection first, and when Caddy reuses that connection at the same instant
# the request fails with a 502 ("EOF" / "connection reset by peer" in Caddy's
# log). GETs are retried transparently by Go's HTTP client; POST/PUT/DELETE are
# not. TraxJourney reproduced it (its #400) and proved this value.
#
# --forwarded-allow-ips: which peers' X-Forwarded-For the client address is
# taken from. Inside the container the reverse proxy's connection arrives from
# the Docker network's gateway (it comes in through the published port), not
# from 127.0.0.1, so uvicorn's default trusts nothing and every request would
# seem to come from the gateway. Set FORWARDED_ALLOW_IPS in .env to the proxy's
# address or network, never "*": any client could then choose the address it
# is seen under, in the logs and by the app. The shell fallback is deliberate: a
# blank .env line reaches uvicorn as an empty string, which it reads as "trust
# nobody", not as unset.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300 --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-127.0.0.1}"
