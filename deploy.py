#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wieloplatformowy skrypt wdrażający wtyczkę QGIS (PyQGIS FastAPI Bridge).
Działa na Windows, macOS i Linux.
"""

import os
import sys
import platform
import subprocess

PLUGIN_NAME = "pyqgis_fastapi_bridge"
PROFILE_NAME = "default"

def get_qgis_plugin_dir():
    system = platform.system()
    home = os.path.expanduser("~")

    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = os.path.join(home, "AppData", "Roaming")
        return os.path.join(appdata, "QGIS", "QGIS3", "profiles", PROFILE_NAME, "python", "plugins")
    elif system == "Darwin":
        return os.path.join(home, "Library", "Application Support", "QGIS", "QGIS3", "profiles", PROFILE_NAME, "python", "plugins")
    else:
        return os.path.join(home, ".local", "share", "QGIS", "QGIS3", "profiles", PROFILE_NAME, "python", "plugins")

def link_plugin():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    source_dir = os.path.join(script_dir, "qgis_plugin", PLUGIN_NAME)
    target_dir = os.path.join(get_qgis_plugin_dir(), PLUGIN_NAME)

    print("=" * 60)
    print(f" Wdrażanie wtyczki QGIS: {PLUGIN_NAME}")
    print(f" System operacyjny: {platform.system()} ({platform.release()})")
    print(f" Źródło: {source_dir}")
    print(f" Cel (QGIS): {target_dir}")
    print("=" * 60)

    if not os.path.exists(source_dir):
        print(f"[BŁĄD] Folder wtyczki nie istnieje: {source_dir}")
        sys.exit(1)

    plugins_parent = os.path.dirname(target_dir)
    os.makedirs(plugins_parent, exist_ok=True)

    if os.path.lexists(target_dir):
        print(f"Usuwanie starego powiązania w: {target_dir}")
        if os.path.islink(target_dir):
            os.unlink(target_dir)
        elif os.path.isdir(target_dir):
            if platform.system() == "Windows":
                try:
                    os.rmdir(target_dir)
                except OSError:
                    import shutil
                    shutil.rmtree(target_dir)
            else:
                import shutil
                shutil.rmtree(target_dir)

    try:
        if platform.system() == "Windows":
            cmd = f'mklink /J "{target_dir}" "{source_dir}"'
            ret = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            if ret.returncode != 0:
                os.symlink(source_dir, target_dir, target_is_directory=True)
        else:
            os.symlink(source_dir, target_dir, target_is_directory=True)

        print("\n[SUKCES] Wtyczka została pomyślnie podlinkowana do QGIS!")
        print("Uruchom QGIS i włącz wtyczkę: Wtyczki -> Zarządzaj wtyczkami -> PyQGIS FastAPI Bridge.")
    except Exception as e:
        print(f"\n[BŁĄD] Nie udało się utworzyć powiązania: {e}")
        sys.exit(1)

if __name__ == "__main__":
    link_plugin()
