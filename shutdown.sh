#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_PID_FILE="$PROJECT_DIR/.worker.pid"
WEB_PID_FILE="$PROJECT_DIR/.web.pid"

terminate_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [[ ! -f "$pid_file" ]]; then
    echo "$label not running"
    return
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    rm -f "$pid_file"
    echo "$label pid file was empty; cleaned up"
    return
  fi

  if kill -0 "$pid" 2>/dev/null; then
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
    echo "$label stopped (PID $pid)"
  else
    echo "$label process was already gone (PID $pid)"
  fi

  rm -f "$pid_file"
}

terminate_pid_file "$WORKER_PID_FILE" "Worker"
terminate_pid_file "$WEB_PID_FILE" "Web UI"

echo "Shutdown complete"
