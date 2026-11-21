"""Resolve the Google Cloud project for Earth Engine commands and the API."""

import json
import os
from pathlib import Path

PROJECT_FILE = Path(__file__).resolve().parents[2] / "earthengine.json"


def earth_engine_project(explicit=None):
    project = (explicit or os.getenv("EARTHENGINE_PROJECT", "")).strip()
    if project:
        return project
    try:
        config = json.loads(PROJECT_FILE.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as error:
        raise ValueError(
            "Ustaw EARTHENGINE_PROJECT lub wpisz project_id w earthengine.json."
        ) from error
    except (OSError, ValueError) as error:
        raise ValueError("Nie można odczytać earthengine.json.") from error
    project = config.get("project_id") if isinstance(config, dict) else None
    if not isinstance(project, str) or not project.strip():
        raise ValueError("Uzupełnij pole project_id w pliku earthengine.json.")
    return project.strip()
