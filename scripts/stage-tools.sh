#!/usr/bin/env bash
# Stage valgrind and perf into an unprivileged prefix. No sudo required.
# Usage: scripts/stage-tools.sh [prefix]
set -euo pipefail
PREFIX="${1:-$PWD/.tools}"
mkdir -p "$PREFIX"

if command -v valgrind >/dev/null && command -v perf >/dev/null; then
  echo "valgrind and perf already on PATH; nothing to stage"
  exit 0
fi

cat <<'NOTE'
Stage the distribution packages into the prefix without installing them
system-wide. On Arch:

  cd "$PREFIX"
  for p in valgrind perf; do
    pkg=$(pacman -Sp --noconfirm "$p" 2>/dev/null | tail -1)
    curl -sLO "$pkg"
  done
  for f in *.pkg.tar.zst; do tar --use-compress-program=unzstd -xf "$f"; done

Then export:
  VALGRIND_LIB=$PREFIX/usr/lib/valgrind
  LD_LIBRARY_PATH=$PREFIX/usr/lib

Or point AUTOPSY_TOOL_PREFIX at the prefix and autopsy will find them:
  AUTOPSY_TOOL_PREFIX=$PREFIX .venv/bin/autopsy diagnose bench.c
NOTE
