#!/usr/bin/env bash
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # run from the repository root (this script lives in scripts/)

echo "=========================================================="
echo " Uruchamianie testów jednostkowych (PyQGIS Bridge)"
echo "=========================================================="

python3 -m unittest discover -s tests -p "test_*.py" -v

echo ""
echo "[SUKCES] Wszystkie testy przeszły pomyślnie!"
