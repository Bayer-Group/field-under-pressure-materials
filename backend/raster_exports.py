"""Find and stream the Drive files belonging to an Earth Engine raster task."""

import re
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from requests import RequestException
from starlette.background import BackgroundTask

from ML.soil_moisture.earth_engine import RASTER_TASK_NAME

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
RASTER_NAME_PATTERN = re.compile(rf"{RASTER_TASK_NAME}_[0-9a-f]{{32}}")


def is_raster_file(export_name, filename):
    return bool(re.fullmatch(rf"{export_name}(?:-\d+-\d+)?\.tiff?", filename))


@contextmanager
def drive_errors():
    try:
        yield
    except (RequestException, GoogleAuthError) as error:
        response = getattr(error, "response", None)
        code = response.status_code if response is not None else None
        if code == 404:
            raise HTTPException(
                404, "Plik eksportu nie jest dostępny na Dysku Google."
            ) from error
        if isinstance(error, GoogleAuthError) or code in (401, 403):
            raise HTTPException(
                502,
                "Brak dostępu do Google Drive. Sprawdź, czy Google Drive API jest włączone i konto Earth Engine ma dostęp do eksportu.",
            ) from error
        raise HTTPException(
            502, "Nie udało się pobrać wyniku z Google Drive."
        ) from error


def list_rasters(credentials, export_name):
    files = []
    params = {
        "q": f"trashed = false and name contains '{export_name}'",
        "fields": "nextPageToken,files(id,name)",
        "pageSize": 100,
    }
    with drive_errors(), AuthorizedSession(credentials) as client:
        while True:
            response = client.get(DRIVE_FILES, params=params, timeout=(5, 15))
            response.raise_for_status()
            payload = response.json()
            files.extend(
                file
                for file in payload.get("files", [])
                if is_raster_file(export_name, file["name"])
            )
            token = payload.get("nextPageToken")
            if not token:
                return sorted(files, key=lambda file: file["name"])
            params["pageToken"] = token


def stream_raster(credentials, export_name, file_id):
    client = AuthorizedSession(credentials)
    url = f"{DRIVE_FILES}/{file_id}"
    with drive_errors():
        try:
            metadata = client.get(
                url, params={"fields": "name,trashed"}, timeout=(5, 15)
            )
            metadata.raise_for_status()
            file = metadata.json()
            if file.get("trashed") or not is_raster_file(export_name, file["name"]):
                raise HTTPException(404, "Nie znaleziono rastra dla tego zadania.")
            response = client.get(
                url, params={"alt": "media"}, stream=True, timeout=(5, 60)
            )
            try:
                response.raise_for_status()
            except RequestException:
                response.close()
                raise
        except Exception:
            client.close()
            raise

    def close():
        response.close()
        client.close()

    def chunks():
        try:
            yield from response.iter_content(chunk_size=128 * 1024)
        finally:
            close()

    return StreamingResponse(
        chunks(),
        media_type="image/tiff",
        headers={"Cache-Control": "private, no-store"},
        background=BackgroundTask(close),
    )
