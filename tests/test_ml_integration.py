"""Regression checks for the shared weather, layout and satellite application.

Run with a disposable local mongod through SAGE_TEST_MONGO_BIN. All satellite
and weather fixtures are confined to the temporary database created here.
"""

import os
import shutil
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import monotonic, sleep
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, PyMongoError
from rasterio.transform import from_bounds

from backend.field_jobs import claim_job, latest_job
from backend.http_api import create_app
from backend.tree_health import health_status
from ML.soil_moisture import forecast
from ML.soil_moisture.tree_pixel_analysis import FieldAnalysis

ROOT = Path(__file__).resolve().parents[1]
DEMO = ObjectId("6b01933c1dc02a368703a020")
UTC = timezone.utc


@pytest.fixture
def database(tmp_path, monkeypatch, request):
    binary = os.environ.get("SAGE_TEST_MONGO_BIN") or shutil.which("mongod")
    if not binary:
        pytest.skip("Set SAGE_TEST_MONGO_BIN to a local mongod executable")
    tools = Path(binary).parent
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    data = tmp_path / "mongodb"
    data.mkdir()
    process = subprocess.Popen(
        [binary, "--bind_ip", "127.0.0.1", "--port", str(port), "--dbpath", str(data),
         "--logpath", str(tmp_path / "mongod.log")],
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    uri = f"mongodb://127.0.0.1:{port}/"
    client = MongoClient(uri, serverSelectionTimeoutMS=500)
    owned = False
    try:
        deadline = monotonic() + 15
        while monotonic() < deadline and process.poll() is None:
            try:
                owned = client.admin.command("serverStatus")["pid"] == process.pid
                if owned:
                    break
            except PyMongoError:
                sleep(.1)
        assert owned
        restore = tools / ("mongorestore.exe" if os.name == "nt" else "mongorestore")
        archive = getattr(request, "param", "field_under_pressure_20261121_200613.archive.gz")
        subprocess.run([
            str(restore), f"--uri={uri}", "--gzip", "--quiet", "--stopOnError",
            f"--archive={ROOT / 'db/backups' / archive}",
        ], check=True)
        monkeypatch.setenv("MONGO_URI", uri)
        monkeypatch.setenv("MONGO_DB", "field_under_pressure")
        monkeypatch.delenv("EARTHENGINE_PROJECT", raising=False)
        monkeypatch.setattr("backend.soil_moisture_api.earth_engine_project",
                            lambda: (_ for _ in ()).throw(ValueError("Test without GEE credentials")))
        monkeypatch.setattr("requests.get", lambda *a, **kw: pytest.fail("Unexpected external request"))
        yield client.field_under_pressure
    finally:
        if owned and process.poll() is None:
            try:
                client.admin.command("shutdown", timeoutSecs=2)
            except AutoReconnect:
                pass
        client.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=5)


def get(client, path):
    response = client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def test_real_archive_routes_and_missing_analysis(database):
    with TestClient(create_app(database)) as client:
        assert len(get(client, "/api/v1/orchards")) == 6
        catalog = get(client, "/api/analytics/orchards")
        assert sum(item["tree_count"] for item in catalog) == 12
        scene = get(client, f"/api/v1/orchard/scene?orchardId={DEMO}")
        analytics = get(client, f"/api/analytics/orchards/{DEMO}")
        assert len(scene["trees"]) == len(analytics["trees"]) == 12
        assert all(tree["healthScore"] is None for tree in scene["trees"])
        assert {tree["id"] for tree in scene["trees"]} == {tree["id"] for tree in analytics["trees"]}
        for tree in analytics["trees"]:
            stored = database.Tree.find_one({"_id": ObjectId(tree["id"])})
            assert tree["coordinates"] == [stored["coordinates"]["lng"], stored["coordinates"]["lat"]]
            assert tree["risk"]["status"] == "insufficient"
        for period in ("24h", "7d", "30d", "90d", "1y"):
            assert get(client, f"/api/v1/weather/temperature?orchardId={DEMO}&range={period}")["points"]
        assert client.post(f"/api/analytics/orchards/{DEMO}/jobs").status_code == 503
        assert client.get(f"/api/soil-moisture/forecast?orchardId={DEMO}").status_code == 503
        assert client.post("/api/soil-moisture", json={
            "orchardId": str(DEMO), "start": "2025-04-01", "test_start": "2025-06-01", "end": "2025-07-01",
        }).status_code == 503
        for suffix in ("01f", "020", "023"):
            response = client.get(f"/api/v1/orchards/6b01933c1dc02a368703a{suffix}/point-cloud.las",
                                  headers={"Range": "bytes=0-3"})
            assert response.status_code == 206 and response.content == b"LASF"


def publish_fixture(database, tmp_path):
    now = datetime.now(UTC)
    job, claimed = claim_job(database, str(DEMO))
    assert claimed
    args = SimpleNamespace(orchard_id=str(DEMO), scene_id="TEST-SCENE", acquired_at=now - timedelta(hours=1),
                           date=now.date(), soil_depth_cm=0, forecast_days=0)
    analysis = FieldAnalysis(database, args, run_id=job["id"])
    xmin, ymin, xmax, ymax = analysis.boundary.bounds
    transform = from_bounds(xmin - .001, ymin - .001, xmax + .001, ymax + .001, 64, 64)
    for kind, values in (("moisture", [-12, -18, .25]), ("ndvi", [.7]), ("ph", [6.5]), ("texture", [6])):
        path = tmp_path / f"{kind}.tif"
        with rasterio.open(path, "w", driver="GTiff", width=64, height=64, count=len(values),
                           dtype="float32", crs="EPSG:4326", transform=transform, nodata=-9999) as raster:
            for index, value in enumerate(values, 1):
                raster.write(np.full((64, 64), value, dtype="float32"), index)
        analysis.collect(kind, path)
    analysis.context = {"date_local": now.date().isoformat(), "timezone": "Europe/Warsaw",
                        "weather": {"mean_temperature_c": 18}, "solar": {"level": "good"}}
    analysis.save_trees(now, ("moisture", "ndvi", "ph", "texture"))
    analysis.save_orchard()
    return analysis


def test_raster_to_tree_health_and_layout_invalidation(database, tmp_path):
    original = list(database.Tree.find({"orchardId": DEMO}).sort("_id", 1))
    analysis = publish_fixture(database, tmp_path)
    assert database.TreePixelAnalysis.count_documents({"analysis_run_id": analysis.run_id}) == 12
    with TestClient(create_app(database)) as client:
        scene = get(client, f"/api/v1/orchard/scene?orchardId={DEMO}")
        detail = get(client, f"/api/analytics/orchards/{DEMO}")
        health = get(client, f"/api/v1/orchard/health?orchardId={DEMO}")
        left = {t["id"]: (t["healthScore"], t["healthStatus"]) for t in scene["trees"]}
        right = {t["id"]: (t["healthScore"], t["healthStatus"]) for t in detail["trees"]}
        assert left == right
        assert health["assessedTrees"] == 12 and sum(health["distribution"].values()) == 12
        assert all(t["healthSource"] == "estimate" for t in scene["trees"])
        assert all(t["healthStatus"] != "dead" for t in scene["trees"])
        for kind in ("moisture", "ndvi", "ph", "texture"):
            response = client.get(f"/api/analytics/orchards/{DEMO}/rasters/{kind}")
            assert response.status_code == 200
            assert response.content == (tmp_path / f"{kind}.tif").read_bytes()
        manual = original[0]["_id"]
        database.Tree.update_one({"_id": manual}, {"$set": {"healthIndex": 0}})
        assert next(t for t in get(client, f"/api/v1/orchard/trees?orchardId={DEMO}") if t["id"] == str(manual))["healthStatus"] == "dead"
        database.Tree.update_one({"_id": original[1]["_id"]}, {"$inc": {"coordinates.lng": .000001}})
        changed = get(client, f"/api/v1/orchard/trees?orchardId={DEMO}")
        assert sum(t["healthScore"] is not None for t in changed) == 1
        with pytest.raises(ValueError, match="Układ"):
            analysis.save_orchard()
        active = [t["_id"] for t in original[1:]]
        database.Orchard.update_one({"_id": DEMO}, {"$set": {"layoutTreeIds": active}})
        assert len(get(client, f"/api/analytics/orchards/{DEMO}")["trees"]) == 11
        assert len(get(client, f"/api/v1/orchard/trees?orchardId={DEMO}")) == 11


def test_stale_health_and_atomic_job_claim(database, tmp_path):
    publish_fixture(database, tmp_path)
    database.Orchard.update_one({"_id": DEMO}, {"$set": {"analysis.observed_at": datetime.now(UTC) - timedelta(days=30)}})
    with TestClient(create_app(database)) as client:
        assert get(client, f"/api/v1/orchard/health?orchardId={DEMO}")["averageScore"] is None
    identity = str(ObjectId())
    with ThreadPoolExecutor(max_workers=4) as pool:
        claims = list(pool.map(lambda _: claim_job(database, identity), range(8)))
    assert sum(claimed for _, claimed in claims) == 1
    assert len({job["id"] for job, _ in claims}) == 1
    database.FieldAnalysisJob.update_one({"_id": identity}, {"$set": {"lease_until": datetime.now(UTC) - timedelta(seconds=1)}})
    assert latest_job(database, identity)["state"] == "failed"
    assert claim_job(database, identity)[1]
    assert health_status(0, estimated=True) == "poor"
    assert health_status(0) == "dead"
    assert health_status(45) == "poor" and health_status(46) == "moderate"
    assert health_status(72) == "moderate" and health_status(73) == "healthy"


def test_ridge_chronological_validation():
    start = datetime(2025, 4, 1, tzinfo=UTC)
    history = {start + timedelta(hours=i): (0., .1, 15., .2 + .00001 * i) for i in range(24 * 20)}
    model, report = forecast.fit_weather_model(history)
    assert report["windows_24h"] > 0
    assert report["mae_24h_m3_m3"] is not None
    assert report["persistence_mae_24h_m3_m3"] is not None
    result, _, _ = forecast.advance(model, np.array([.2]), history, start, start + timedelta(days=1))
    assert np.isfinite(result).all() and 0 <= result[0] <= 1


@pytest.mark.parametrize("database", ["field_under_pressure_20261121_230119.archive.gz"], indirect=True)
def test_real_checkpoint_layers_without_google(database):
    """The shared dump carries real samples and rasters independently of Drive."""
    from rasterio.io import MemoryFile
    from rasterio.warp import transform

    analysis = database.Orchard.find_one({"_id": DEMO})["analysis"]
    rows = list(database.TreePixelAnalysis.find({"analysis_run_id": analysis["run_id"]}))
    assert len(rows) == 12
    assert database.FieldAnalysisJob.find_one({"_id": str(DEMO)})["state"] == "completed"
    with TestClient(create_app(database)) as client:
        assert client.post(f"/api/analytics/orchards/{DEMO}/jobs").status_code == 503
        for kind in ("moisture", "ndvi", "ph", "texture"):
            response = client.get(f"/api/analytics/orchards/{DEMO}/rasters/{kind}")
            assert response.status_code == 200
            with MemoryFile(response.content) as memory, memory.open() as raster:
                for row in rows:
                    tree = database.Tree.find_one({"_id": ObjectId(row["tree_id"])})
                    longitude, latitude = row["tree_coordinates_lon_lat"]
                    assert [longitude, latitude] == [tree["coordinates"]["lng"], tree["coordinates"]["lat"]]
                    x, y = transform("EPSG:4326", raster.crs, [longitude], [latitude])
                    value = next(raster.sample(zip(x, y, strict=True)))[-1 if kind == "moisture" else 0]
                    expected = (row["pixel"]["soil_moisture_estimate_m3_m3"] if kind == "moisture"
                                else row["layers"]["ndvi"]["value"] if kind == "ndvi"
                                else row["layers"]["soil_parameters"][kind]["value"])
                    assert np.isclose(value, expected)
