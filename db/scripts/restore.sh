#!/usr/bin/env bash
set -euo pipefail

# Restore the entire project database (all collections, documents, indexes, and validators)
# from a shared compressed archive (.archive.gz).
#
# By default, replaces the local database cleanly (1:1 mirror of the archive).
# Pass --no-drop to restore without dropping existing local data first.
#
# Usage:
#   ./db/scripts/restore.sh                             # Restores latest db/backups/field_under_pressure_*.archive.gz
#   ./db/scripts/restore.sh path/to/custom.archive.gz   # Restores from a specific archive path
#   ./db/scripts/restore.sh --no-drop [archive_file]    # Restores without dropping existing database
#   MONGO_URI="mongodb://..." ./db/scripts/restore.sh   # Restores to a custom URI (requires local mongorestore)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/backups"

MONGO_ROOT_USER="${MONGO_ROOT_USER:-admin}"
MONGO_ROOT_PASSWORD="${MONGO_ROOT_PASSWORD:-admin123}"
MONGO_DB="${MONGO_DB:-field_under_pressure}"

DROP_EXISTING=true
ARCHIVE_FILE=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-drop)
      DROP_EXISTING=false
      shift
      ;;
    -h|--help)
      sed -n '3,13p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    -*)
      echo "Error: Unknown option '$1'" >&2
      exit 1
      ;;
    *)
      if [[ -z "${ARCHIVE_FILE}" ]]; then
        ARCHIVE_FILE="$1"
      else
        echo "Error: Unexpected argument '$1'" >&2
        exit 1
      fi
      shift
      ;;
  esac
done

if [[ -z "${ARCHIVE_FILE}" ]]; then
  shopt -s nullglob
  CANDIDATES=("${BACKUP_DIR}/${MONGO_DB}_"*.archive.gz)
  shopt -u nullglob
  if [[ ${#CANDIDATES[@]} -gt 0 ]]; then
    # Filenames end with YYYYMMDD_HHMMSS, so the last lexicographical entry is the newest archive
    ARCHIVE_FILE="${CANDIDATES[$(( ${#CANDIDATES[@]} - 1 ))]}"
  elif [[ -f "${BACKUP_DIR}/${MONGO_DB}.archive.gz" ]]; then
    ARCHIVE_FILE="${BACKUP_DIR}/${MONGO_DB}.archive.gz"
  else
    echo "Error: No archive found in ${BACKUP_DIR} matching '${MONGO_DB}_*.archive.gz'." >&2
    echo "Create one first with: ./db/scripts/backup.sh" >&2
    exit 1
  fi
fi

if [[ ! -f "${ARCHIVE_FILE}" ]]; then
  echo "Error: Archive file not found: ${ARCHIVE_FILE}" >&2
  echo "Create it first with: ./db/scripts/backup.sh" >&2
  exit 1
fi

echo "[restore] Using archive: ${ARCHIVE_FILE}"

RESTORE_ARGS=(--archive --nsInclude "${MONGO_DB}.*")
if [[ "${ARCHIVE_FILE}" == *.gz ]]; then
  RESTORE_ARGS+=(--gzip)
fi
if [[ "${DROP_EXISTING}" == "true" ]]; then
  RESTORE_ARGS+=(--drop)
fi

if [[ -n "${MONGO_URI:-}" ]]; then
  if ! command -v mongorestore >/dev/null 2>&1; then
    echo "Error: mongorestore is required when MONGO_URI is set." >&2
    exit 1
  fi
  if [[ "${DROP_EXISTING}" == "true" ]] && command -v mongosh >/dev/null 2>&1; then
    mongosh --quiet "${MONGO_URI}" --eval "db.getSiblingDB('${MONGO_DB}').dropDatabase()" >/dev/null
  fi
  mongorestore \
    --uri="${MONGO_URI}" \
    "${RESTORE_ARGS[@]}" < "${ARCHIVE_FILE}"
else
  if [[ "${DROP_EXISTING}" == "true" ]]; then
    docker compose exec -T mongodb \
      mongosh --quiet \
      --username "${MONGO_ROOT_USER}" \
      --password "${MONGO_ROOT_PASSWORD}" \
      --authenticationDatabase admin \
      "${MONGO_DB}" \
      --eval "db.dropDatabase()" >/dev/null
  fi
  docker compose exec -T mongodb \
    mongorestore \
    --username "${MONGO_ROOT_USER}" \
    --password "${MONGO_ROOT_PASSWORD}" \
    --authenticationDatabase admin \
    "${RESTORE_ARGS[@]}" < "${ARCHIVE_FILE}"
fi

echo "[restore] Database '${MONGO_DB}' restored from: ${ARCHIVE_FILE}"
