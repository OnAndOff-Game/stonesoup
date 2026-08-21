#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/bin:/ucrt64/bin:$PATH"

script_dir="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
pidfile="$project_root/crawl-ref/source/webserver/webtiles-msys.pid"

if [[ ! -f "$pidfile" ]]; then
    echo "DCSS WebTiles is not running."
    exit 0
fi

pid="$(tr -d '[:space:]' < "$pidfile")"
if [[ ! "$pid" =~ ^[0-9]+$ ]]; then
    echo "Refusing to use an invalid PID file: $pidfile" >&2
    exit 2
fi

if ! kill -0 "$pid" 2>/dev/null; then
    rm -f -- "$pidfile"
    echo "Removed a stale WebTiles PID file."
    exit 0
fi

kill -TERM "$pid"
for _ in {1..50}; do
    if ! kill -0 "$pid" 2>/dev/null; then
        rm -f -- "$pidfile"
        echo "DCSS WebTiles stopped."
        exit 0
    fi
    sleep 0.1
done

kill -KILL "$pid"
rm -f -- "$pidfile"
echo "DCSS WebTiles was force-stopped after the graceful timeout."
