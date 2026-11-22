"""Find and stream the Drive files belonging to an Earth Engine raster task."""

import re
from contextlib import contextmanager

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from gridfs import GridFS
from requests import RequestException
from starlette.background import BackgroundTask

from ML.soil_moisture.earth_engine import RASTER_TASK_NAME

DRIVE_FILES = "https://www.googleapis.com/drive/v3/files"
RASTER_NAME_PATTERN = re.compile(rf"{RASTER_TASK_NAME}_[0-9a-f]{{32}}")
RASTER_BUCKET = "AnalysisRaster"


def save_local_raster(database, path):
    """Keep validated exports in the database so a dump includes map layers."""
    files = GridFS(database, collection=RASTER_BUCKET)
    if not files.exists(path.name):
        with path.open("rb") as stream:
            files.put(stream, _id=path.name, filename=path.name, contentType="image/tiff")


def local_raster(database, name):
    if database is None:
        return None
    files = GridFS(database, collection=RASTER_BUCKET)
    return files.get(name) if files.exists(name) else None


def stream_local_raster(database, name):
    raster = local_raster(database, name)
    if raster is None:
        return None

    def chunks():
        try:
            while chunk := raster.read(128 * 1024):
                yield chunk
        finally:
            raster.close()

    return StreamingResponse(chunks(), media_type="image/tiff",
                             headers={"Cache-Control": "private, no-store"})


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


def download_raster(credentials, file, destination):
    path = destination / file["name"]
    with (
        drive_errors(),
        AuthorizedSession(credentials) as client,
        client.get(
            f"{DRIVE_FILES}/{file['id']}",
            params={"alt": "media"},
            stream=True,
            timeout=(5, 60),
        ) as response,
    ):
        response.raise_for_status()
        with path.open("wb") as stream:
            for chunk in response.iter_content(chunk_size=128 * 1024):
                stream.write(chunk)
    return path


def stream_raster(credentials, export_name, file_id):
    return stream_drive_raster(
        credentials, file_id, lambda name: is_raster_file(export_name, name)
    )


def find_saved_raster(credentials, name):
    if not re.fullmatch(r"[A-Za-z0-9_. -]+\.tiff?", name, re.IGNORECASE):
        raise HTTPException(404, "Nie znaleziono zapisanego pliku GeoTIFF.")
    with drive_errors(), AuthorizedSession(credentials) as client:
        response = client.get(
            DRIVE_FILES,
            params={
                "q": f"trashed = false and name = '{name}'",
                "fields": "files(id,name),nextPageToken",
            },
            timeout=(5, 15),
        )
        response.raise_for_status()
        result = response.json()
        files = result.get("files", [])
    if not files:
        raise HTTPException(404, "Plik eksportu nie jest dostępny na Dysku Google.")
    if len(files) != 1 or result.get("nextPageToken"):
        raise HTTPException(409, "Nazwa rastra na Dysku nie jest jednoznaczna.")
    return files[0]


def stream_saved_raster(credentials, name):
    file = find_saved_raster(credentials, name)
    return stream_drive_raster(
        credentials, file["id"], lambda filename: filename == name
    )


def stream_drive_raster(credentials, file_id, name_matches):
    client = AuthorizedSession(credentials)
    url = f"{DRIVE_FILES}/{file_id}"
    with drive_errors():
        try:
            metadata = client.get(
                url, params={"fields": "name,trashed"}, timeout=(5, 15)
            )
            metadata.raise_for_status()
            file = metadata.json()
            if file.get("trashed") or not name_matches(file["name"]):
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
