#!/usr/bin/env bash
# Rebuild the static, read-only demo in static_version/.
# Needs the full local data/ pipeline (see README.md) and .venv.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

(cd web && npm install && npm run build:static)
.venv/bin/python scripts/19_bake_static.py "$@"

du -sh static_version
