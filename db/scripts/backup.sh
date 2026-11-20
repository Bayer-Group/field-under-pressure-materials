#!/usr/bin/env bash
set -euo pipefail

# Export the entire project database (all collections, documents, indexes, and validators)
# into a single compressed archive (.archive.gz) for sharing between developers.
#
# Usage:
#   ./db/scripts/backup.sh                              # Saves to db/backups/field_under_pressure.archive.gz
#   ./db/scripts/backup.sh path/to/custom.archive.gz    # Saves to a custom path
#   MONGO_URI="mongodb://..." ./db/scripts/backup.sh    # Dumps from a custom URI (requires local mongodump)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/backups"

MONGO_ROOT_USER="${MONGO_ROOT_USER:-admin}"
MONGO_ROOT_PASSWORD="${MONGO_ROOT_PASSWORD:-admin123}"
MONGO_DB="${MONGO_DB:-field_under_pressure}"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  sed -n '3,10p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

OUT_FILE="${1:-${BACKUP_DIR}/${MONGO_DB}.archive.gz}"

mkdir -p "$(dirname "${OUT_FILE}")"

TMP_FILE="${OUT_FILE}.tmp.$$"
cleanup() {
  rm -f "${TMP_FILE}"
}
trap cleanup EXIT

if [[ -n "${MONGO_URI:-}" ]]; then
  if ! command -v mongodump >/dev/null 2>&1; then
    echo "Error: mongodump is required when MONGO_URI is set." >&2
    exit 1
  fi
  mongodump \
    --uri="${MONGO_URI}" \
    --db "${MONGO_DB}" \
    --archive \
    --gzip > "${TMP_FILE}"
else
  docker compose exec -T mongodb \
    mongodump \
    --username "${MONGO_ROOT_USER}" \
    --password "${MONGO_ROOT_PASSWORD}" \
    --authenticationDatabase admin \
    --db "${MONGO_DB}" \
    --archive \
    --gzip > "${TMP_FILE}"
fi

mv "${TMP_FILE}" "${OUT_FILE}"
trap - EXIT

SIZE="$(du -h "${OUT_FILE}" | cut -f1)"
echo "[backup] Database '${MONGO_DB}' exported to: ${OUT_FILE} (${SIZE})"
