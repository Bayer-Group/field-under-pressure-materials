#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Skrypt pakujący wtyczkę QGIS do archiwum .ZIP.
Generuje gotowy pakiet instalacyjny, który można wgrać w QGIS przez:
Wtyczki -> Zarządzaj wtyczkami -> Zainstaluj z pliku ZIP.
"""

import os
import sys
import zipfile

def package_qgis_plugin(output_zip=None):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    plugin_parent = os.path.join(script_dir, "qgis_plugin")
    plugin_dir = os.path.join(plugin_parent, "pyqgis_fastapi_bridge")
    
    if not os.path.exists(plugin_dir):
        print(f"[BŁĄD] Folder wtyczki nie istnieje: {plugin_dir}")
        sys.exit(1)
        
    if not output_zip:
        output_zip = os.path.join(script_dir, "pyqgis_fastapi_bridge.zip")

    print(f"📦 Pakowanie wtyczki QGIS do: {output_zip}...")

    with zipfile.ZipFile(output_zip, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(plugin_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for file in files:
                if file.endswith(".pyc"):
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, plugin_parent)
                zipf.write(full_path, rel_path)

    print(f"✅ Utworzono pakiet: {output_zip} ({os.path.getsize(output_zip)} bajtów)")
    return output_zip

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    package_qgis_plugin(out)
