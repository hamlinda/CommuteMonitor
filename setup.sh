#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
PYTHON_BIN="python3"
PORT="8585"
HOST="0.0.0.0"
CONFIG_PATH="$PROJECT_DIR/config.yaml"
DB_PATH="$PROJECT_DIR/travel_data.db"
WORKER_PID_FILE="$PROJECT_DIR/.worker.pid"
WEB_PID_FILE="$PROJECT_DIR/.web.pid"
WORKER_LOG="$PROJECT_DIR/.worker.log"
WEB_LOG="$PROJECT_DIR/.web.log"

check_python_version() {
  if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "python3 is required but was not found on PATH" >&2
    exit 1
  fi
  local version
  version="$($PYTHON_BIN - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
  local major minor
  IFS='.' read -r major minor <<<"$version"
  if [[ "$major" -lt 3 || ("$major" -eq 3 && "$minor" -lt 10) ]]; then
    echo "Python 3.10+ is required; found $version" >&2
    exit 1
  fi
}

stop_stale_process() {
  local pid_file="$1"
  local expected_pattern="$2"
  if [[ -f "$pid_file" ]]; then
    local pid
    pid="$(cat "$pid_file" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      local cmd
      cmd="$(ps -p "$pid" -o args= 2>/dev/null || true)"
      if [[ "$cmd" == *"$expected_pattern"* ]]; then
        kill "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5; do
          if ! kill -0 "$pid" 2>/dev/null; then
            break
          fi
          sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
          kill -9 "$pid" 2>/dev/null || true
        fi
      fi
    fi
    rm -f "$pid_file"
  fi
}

check_python_version
cd "$PROJECT_DIR"

if [[ ! -d "$VENV_DIR" ]]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

python - <<PY
from database import initialize_database
initialize_database(r"$DB_PATH")
PY

python tracker.py --config "$CONFIG_PATH" --once

stop_stale_process "$WORKER_PID_FILE" "tracker.py"
stop_stale_process "$WEB_PID_FILE" "streamlit run app.py"

nohup python tracker.py --config "$CONFIG_PATH" --daemon --no-initial > "$WORKER_LOG" 2>&1 &
echo $! > "$WORKER_PID_FILE"

nohup streamlit run app.py --server.port "$PORT" --server.address "$HOST" --server.headless true --browser.gatherUsageStats false > "$WEB_LOG" 2>&1 &
echo $! > "$WEB_PID_FILE"

sleep 2

echo "Travel Tracker setup complete"
echo "Web UI: http://localhost:$PORT"
echo "LAN access: http://<your-machine-ip>:$PORT"
echo "Worker PID: $(cat "$WORKER_PID_FILE")"
echo "Web PID: $(cat "$WEB_PID_FILE")"
echo "Logs: $WORKER_LOG and $WEB_LOG"
