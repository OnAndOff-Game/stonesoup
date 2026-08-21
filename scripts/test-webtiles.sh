#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/bin:/ucrt64/bin:$PATH"

script_dir="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"

source "$project_root/.webtiles-runtime/venv/bin/activate"
cd "$project_root/crawl-ref/source/webserver"

python -m unittest webtiles.multiplayer_test webtiles.room_lobby_test -v
python -m compileall -q webtiles
