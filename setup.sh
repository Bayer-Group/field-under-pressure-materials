#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

if (( $# > 1 )) || [[ -n "${1:-}" && "${1:-}" != "--relogin" ]]; then
    printf 'Run bash setup.sh [--relogin]\n' >&2
    exit 2
fi

if ! docker compose version >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    printf 'Start Docker Desktop or Docker Engine with Docker Compose.\n' >&2
    exit 1
fi

if [[ ! -x .venv/bin/python && ! -x .venv/Scripts/python.exe ]]; then
    if py -3 -c 'import venv' >/dev/null 2>&1; then
        py -3 -m venv .venv
    elif python3 -c 'import venv' >/dev/null 2>&1; then
        python3 -m venv .venv
    elif python -c 'import venv' >/dev/null 2>&1; then
        python -m venv .venv
    else
        printf 'Install Python with the venv module and add Python to PATH.\n' >&2
        exit 1
    fi
fi

venv_python=.venv/bin/python
if [[ -x .venv/Scripts/python.exe ]]; then
    venv_python=.venv/Scripts/python.exe
fi
if ! "$venv_python" -c 'import ee' >/dev/null 2>&1; then
    "$venv_python" -m pip install earthengine-api
fi

"$venv_python" - <<'PY'
import json
import os
from pathlib import Path

config = Path("earthengine.json")
if not config.exists():
    project_id = os.getenv("EARTHENGINE_PROJECT", "").strip() or "hackathon-515400"
    with config.open("x", encoding="utf-8") as stream:
        json.dump({"project_id": project_id}, stream, indent=2)
        stream.write("\n")
PY

up_args=(-d --build --wait)
if [[ "${1:-}" == "--relogin" ]] || ! "$venv_python" -c '
from pathlib import Path
import ee

if not Path(ee.oauth.get_credentials_path()).is_file():
    raise SystemExit(1)
ee.data.get_persistent_credentials()
' >/dev/null 2>&1; then
    printf 'Sign in with an account that has access to the project and grant access to Google Drive.\n'
    "$venv_python" -c "import ee; ee.Authenticate(auth_mode='localhost:0', force=True)"
    up_args+=(--force-recreate)
fi

"$venv_python" - <<'PY'
import ee
from ML.soil_moisture.project_config import earth_engine_project

project = earth_engine_project()
ee.Initialize(credentials=ee.data.get_persistent_credentials(), project=project)
ee.Number(1).getInfo()
PY
printf 'Connected to Earth Engine.\n'

compose=(docker compose -f docker-compose.yml -f docker-compose.gee.yml)
backup=$("${compose[@]}" config --format json | "$venv_python" -c '
import hashlib
import json
from pathlib import Path
import sys

environment = json.load(sys.stdin)["services"]["mongodb"]["environment"]
database = environment["MONGO_INITDB_DATABASE"]
directory = Path("db/backups")
archives = sorted(directory.glob(f"{database}_*.archive.gz"))
archive = archives[-1] if archives else directory / f"{database}.archive.gz"
if not archive.is_file():
    sys.exit(f"No MongoDB backup found for {database} in {directory}.")
with archive.open("rb") as contents:
    digest = hashlib.sha256()
    for chunk in iter(lambda: contents.read(1024 * 1024), b""):
        digest.update(chunk)
print(f"{archive.name}\t{digest.hexdigest()[:16]}")
')
IFS=$'\t' read -r SAGE_DB_BACKUP_ARCHIVE backup_revision <<< "${backup%$'\r'}"
export SAGE_DB_BACKUP_ARCHIVE
export SAGE_DB_BACKUP_SUFFIX="_${backup_revision}"
printf 'Using MongoDB backup %s.\n' "$SAGE_DB_BACKUP_ARCHIVE"

"${compose[@]}" config --quiet
"${compose[@]}" up "${up_args[@]}"
"${compose[@]}" ps

ui_address=$("${compose[@]}" port ui 8080)
printf '\nOpen the dashboard at http://%s\n' "${ui_address%$'\r'}"
