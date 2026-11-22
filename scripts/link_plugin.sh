#!/usr/bin/env bash
set -e

PLUGIN_NAME="pyqgis_fastapi_bridge"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)/qgis_plugin/${PLUGIN_NAME}"   # this script lives in scripts/

if [[ "$OSTYPE" == "darwin"* ]]; then
    TARGET_DIR="${HOME}/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/${PLUGIN_NAME}"
else
    TARGET_DIR="${HOME}/.local/share/QGIS/QGIS3/profiles/default/python/plugins/${PLUGIN_NAME}"
fi

echo "=========================================================="
echo " Podlinkowanie wtyczki QGIS (${OSTYPE})"
echo " Źródło: ${SOURCE_DIR}"
echo " Cel:    ${TARGET_DIR}"
echo "=========================================================="

mkdir -p "$(dirname "${TARGET_DIR}")"

if [ -L "${TARGET_DIR}" ] || [ -e "${TARGET_DIR}" ]; then
    rm -rf "${TARGET_DIR}"
fi

ln -s "${SOURCE_DIR}" "${TARGET_DIR}"

echo ""
echo "[SUKCES] Wtyczka PyQGIS FastAPI Bridge zostala podlinkowana!"
echo "Wlacz wtyczke w QGIS: Wtyczki -> Zarzadzaj wtyczkami."
