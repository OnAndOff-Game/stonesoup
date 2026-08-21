#!/usr/bin/env bash
set -euo pipefail

export PATH="/usr/bin:/ucrt64/bin:$PATH"

script_dir="$(cd "$(dirname "$0")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
source_dir="$project_root/crawl-ref/source"

cd "$source_dir"

jobs="$(nproc 2>/dev/null || echo 4)"
make -j"$jobs" WEBTILES=y SOUND= NO_PKGCONFIG=1 \
    EXTERNAL_DEFINES=-DUSE_MULTIPLAYER

./crawl.exe -version
