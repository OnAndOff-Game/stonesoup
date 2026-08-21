#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/bin:/ucrt64/bin:$PATH"

script_dir="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
runtime_dir="$project_root/.webtiles-runtime"
source_dir="$project_root/crawl-ref/source"

export LANG="C.UTF-8"
export LC_ALL="C.UTF-8"

if [[ ! -f "$source_dir/crawl.exe" ]]; then
    echo "WebTiles binary is missing. Run BUILD_WEB.cmd first." >&2
    exit 2
fi

if [[ ! -f "$runtime_dir/venv/bin/activate" ]]; then
    echo "WebTiles Python environment is missing: $runtime_dir/venv" >&2
    exit 3
fi

mkdir -p "$source_dir/rcs/running" "$source_dir/rcs/ttyrecs" \
         "$source_dir/rcs/sockets" "$runtime_dir"

source "$runtime_dir/venv/bin/activate"
cd "$source_dir"
exec python webserver/server.py --no-daemon --logfile -
