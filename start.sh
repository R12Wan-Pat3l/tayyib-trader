#!/bin/sh
# tayyib-trader: open the dashboard without Claude Code, on Mac or Linux (v0.2.7). Run: ./start.sh
# The same as start.bat on Windows. Your files live in ~/tayyib-live/trader unless TAYYIB_DIR names
# another trader folder. It places no order: the dashboard reads your files, and its buttons run the
# daily list or a backtest. Extra arguments go to the dashboard (for example: ./start.sh --port 8800).
HERE=$(cd "$(dirname "$0")" && pwd)
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY=$c
    break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.8 or newer was not found (python3). Install it from https://www.python.org/downloads/"
  echo "(Mac: the installer there, or 'brew install python'; Linux: your package manager), then run ./start.sh again."
  exit 1
fi
if [ -z "$TAYYIB_DIR" ]; then
  TAYYIB_DIR="$HOME/tayyib-live/trader"
fi
export TAYYIB_DIR
mkdir -p "$TAYYIB_DIR" || exit 1
cd "$TAYYIB_DIR/.." || exit 1
echo "tayyib-trader: your files are in $TAYYIB_DIR"
echo "The dashboard opens in your browser. Keep this window open while you use it; press Ctrl+C to stop."
exec "$PY" "$HERE/tayyib-dashboard/dashboard.py" "$@"
