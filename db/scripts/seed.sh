#!/usr/bin/env bash
set -euo pipefail

# Manually run the idempotent MongoDB collection seed script.
# Usage:
#   ./db/scripts/seed.sh                         # Seeds the running docker compose `mongodb` service
#   MONGO_URI="mongodb://..." ./db/scripts/seed.sh  # Seeds a custom MongoDB URI using local mongosh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEED_JS="${SCRIPT_DIR}/seed.js"

MONGO_ROOT_USER="${MONGO_ROOT_USER:-admin}"
MONGO_ROOT_PASSWORD="${MONGO_ROOT_PASSWORD:-admin123}"
MONGO_DB="${MONGO_DB:-field_under_pressure}"

if [[ -n "${MONGO_URI:-}" ]]; then
  if ! command -v mongosh >/dev/null 2>&1; then
    echo "Error: mongosh is required when MONGO_URI is set." >&2
    exit 1
  fi
  MONGO_DB="${MONGO_DB}" mongosh "${MONGO_URI}" --file "${SEED_JS}"
  exit 0
fi

docker compose exec -T \
  -e MONGO_DB="${MONGO_DB}" \
  mongodb \
  mongosh \
  --username "${MONGO_ROOT_USER}" \
  --password "${MONGO_ROOT_PASSWORD}" \
  --authenticationDatabase admin \
  "${MONGO_DB}" \
  /docker-entrypoint-initdb.d/01-seed-collections.js
