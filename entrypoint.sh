#!/usr/bin/env bash
set -euo pipefail

# Backend (port 8000) — the only port cloudflared ever tunnels.
python -m uvicorn backend:app --host 0.0.0.0 --port 8000 &
PID_8000=$!

CF_PID=""
if [ "${ENABLE_CLOUDFLARE_TUNNEL:-false}" = "true" ]; then
    echo "[entrypoint] starting cloudflared quick tunnel -> http://localhost:8000"
    cloudflared tunnel --url http://localhost:8000 --no-autoupdate &
    CF_PID=$!
fi

shutdown() {
    echo "[entrypoint] shutting down"
    kill "$PID_8000" 2>/dev/null || true
    [ -n "$CF_PID" ] && kill "$CF_PID" 2>/dev/null || true
}
trap shutdown TERM INT

# If the backend dies, tear down and exit so the container's restart policy
# can bring it back. cloudflared is best-effort and is not part of the wait
# set — losing the tunnel shouldn't kill the container.
wait "$PID_8000"
EXIT_CODE=$?
echo "[entrypoint] backend process exited (code $EXIT_CODE)"
shutdown
exit "$EXIT_CODE"
