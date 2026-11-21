#!/usr/bin/env bash
# Executed automatically by the official mongo Docker entrypoint during first initialization.
# Restores the latest database archive from /backups (collections, documents, indexes, validators).
# Wrapped in a subshell because docker-entrypoint.sh sources *.sh files.
(
  set -euo pipefail

  BACKUP_DIR="${MONGO_INITDB_BACKUP_DIR:-/backups}"
  DB_NAME="${MONGO_INITDB_DATABASE:-field_under_pressure}"
  ARCHIVE_FILE=""

  shopt -s nullglob
  CANDIDATES=("${BACKUP_DIR}/${DB_NAME}_"*.archive.gz)
  shopt -u nullglob

  if [[ ${#CANDIDATES[@]} -gt 0 ]]; then
    ARCHIVE_FILE="${CANDIDATES[$(( ${#CANDIDATES[@]} - 1 ))]}"
  elif [[ -f "${BACKUP_DIR}/${DB_NAME}.archive.gz" ]]; then
    ARCHIVE_FILE="${BACKUP_DIR}/${DB_NAME}.archive.gz"
  else
    echo "[init-restore] No archive found in ${BACKUP_DIR} for '${DB_NAME}' — skipping."
    exit 0
  fi

  echo "[init-restore] Restoring database '${DB_NAME}' from ${ARCHIVE_FILE}..."

  RESTORE_ARGS=(
    --host 127.0.0.1
    --port "${MONGO_INITDB_PORT:-27017}"
    --archive
    --gzip
    --nsInclude "${DB_NAME}.*"
    --stopOnError
  )

  if [[ -n "${MONGO_INITDB_ROOT_USERNAME:-}" && -n "${MONGO_INITDB_ROOT_PASSWORD:-}" ]]; then
    RESTORE_ARGS+=(
      --username "${MONGO_INITDB_ROOT_USERNAME}"
      --password "${MONGO_INITDB_ROOT_PASSWORD}"
      --authenticationDatabase admin
    )
  fi

  mongorestore "${RESTORE_ARGS[@]}" < "${ARCHIVE_FILE}"
  echo "[init-restore] Done."
)
