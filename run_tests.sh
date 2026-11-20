#!/usr/bin/env bash
set -e

echo "=========================================================="
echo " Uruchamianie testów jednostkowych (PyQGIS Bridge)"
echo "=========================================================="

python3 -m unittest discover -s tests -p "test_*.py" -v

echo ""
echo "[SUKCES] Wszystkie testy przeszły pomyślnie!"
