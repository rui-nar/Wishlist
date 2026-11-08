#!/bin/sh
# The `backup` service's healthcheck (plan D9, review R1-1): fails when no
# wishlist_*.dump in /backups is newer than 26 hours, so a backup that stopped
# working shows as `unhealthy` in `docker ps` without anyone reading its logs.
# 26 hours: a day between two nightly dumps, plus slack for a slow one.
set -eu

find /backups -maxdepth 1 -name 'wishlist_*.dump' -mmin -1560 | grep -q .
