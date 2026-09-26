#!/bin/sh
# Start as root only long enough to make /data writable for the app user, then
# drop privileges. PUID/PGID (default 1000) choose that user, so files in a
# bind-mounted ./data belong to you on the host. Started with --user, it just runs.
set -e
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"
DATA="${EXLIBRIS_DATA:-/data}"
if [ "$(id -u)" = "0" ]; then
  mkdir -p "$DATA"
  if [ "$(stat -c %u "$DATA")" != "$PUID" ] || [ "$(stat -c %g "$DATA")" != "$PGID" ]; then
    chown -R "$PUID:$PGID" "$DATA" 2>/dev/null || echo "ex-libris: couldn't change owner of $DATA; continuing"
  fi
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups -- "$@"
fi
exec "$@"
