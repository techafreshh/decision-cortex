#!/usr/bin/env bash
# Factory verification entrypoint for the Decision Cortex API.
#
#   scripts/run_scenario_api.sh <scratch_dir> <port>
#
# Boots the API from a scratch virtualenv and blocks until GET /healthz answers
# 200, leaving uvicorn running detached for the caller to probe. Exits non-zero
# (with the last log lines on stderr) if the service never comes up.
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "usage: $(basename "$0") <scratch_dir> <port>" >&2
    exit 2
fi

SCRATCH_DIR="$1"
PORT="$2"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

VENV="$SCRATCH_DIR/venv"
PIDFILE="$SCRATCH_DIR/api.pid"
LOGFILE="$SCRATCH_DIR/api.log"
READY_TIMEOUT_SECS=120

mkdir -p "$SCRATCH_DIR"

# Refuse to report readiness for a listener this invocation did not start: if
# the port already answers /healthz, a foreign process owns it and the uvicorn
# launched below would die on bind (Errno 98) while the probe still saw that 200.
if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
    echo "refusing to start: port ${PORT} already serves /healthz before launch" >&2
    exit 1
fi

if command -v uv >/dev/null 2>&1; then
    uv venv "$VENV"
    uv pip install --python "$VENV/bin/python" -e "$REPO_ROOT"
else
    python3 -m venv "$VENV"
    "$VENV/bin/python" -m pip install --upgrade pip
    "$VENV/bin/pip" install -e "$REPO_ROOT"
fi

cd "$REPO_ROOT"
nohup "$VENV/bin/uvicorn" api.main:app --host 127.0.0.1 --port "$PORT" \
    >"$LOGFILE" 2>&1 &
API_PID=$!
echo "$API_PID" >"$PIDFILE"

deadline=$((SECONDS + READY_TIMEOUT_SECS))
while [ "$SECONDS" -lt "$deadline" ]; do
    if ! kill -0 "$API_PID" 2>/dev/null; then
        echo "uvicorn (pid $API_PID) exited before /healthz answered on port ${PORT}" >&2
        tail -n 5 "$LOGFILE" >&2
        exit 1
    fi
    if curl -fsS "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1; then
        echo "healthz ok on port ${PORT} (pid $API_PID)"
        exit 0
    fi
    sleep 1
done

echo "healthz never came up on port ${PORT} within ${READY_TIMEOUT_SECS}s" >&2
tail -n 5 "$LOGFILE" >&2
exit 1
