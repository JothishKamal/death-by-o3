#!/usr/bin/env bash
# Launch demo servers fully detached from the calling shell.
set -eu
REPO="$(cd "$(dirname "$0")/.." && pwd)"
RUN_DIR="${TMPDIR:-/tmp}/optimization-autopsy-demo"
mkdir -p "$RUN_DIR"
cd "$REPO"

export AUTOPSY_TOOL_PREFIX="$REPO/.tools"
setsid "$REPO/.venv/bin/autopsy" serve benchmarks/tierA/A12_simplifycfg_cmov.c \
  --top 3 -o "$RUN_DIR/run" > "$RUN_DIR/api.log" 2>&1 < /dev/null &
disown

cd "$REPO/web"
setsid ./node_modules/.bin/vite --port 5173 --strictPort > "$RUN_DIR/vite.log" 2>&1 < /dev/null &
disown

echo "launched; logs are in $RUN_DIR"
