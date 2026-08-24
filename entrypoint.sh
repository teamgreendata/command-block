#!/bin/sh
# Runs as root just long enough to self-heal the cb_data volume (older images
# created it owned by uid 10001), then drops to dash (uid 1000 — matching the
# minecraft data files, whose playerdata .dat are mode 600).
chown -R dash /cb-data 2>/dev/null || true
exec setpriv --reuid dash --regid dash --init-groups \
  uvicorn app.main:app --host 0.0.0.0 --port "${DASH_PORT:-8300}"
