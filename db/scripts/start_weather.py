"""Restore a local MongoDB if needed and launch the orchard weather backend."""

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pymongo import MongoClient
from pymongo.errors import PyMongoError

ROOT = Path(__file__).resolve().parents[2]
DB_NAME = "field_under_pressure"
WINDOWS = os.name == "nt"
ARCHIVE_REF = "refs/remotes/origin/ml"
ARCHIVE_BRANCH = "refs/heads/ml"


def _binary(name: str, directory: Path | None) -> str:
    executable = f"{name}.exe" if WINDOWS else name
    if directory is not None and (directory / executable).is_file():
        return str((directory / executable).resolve())
    resolved = shutil.which(name)
    if resolved is None:
        raise RuntimeError(f"Missing {name}. Add it to PATH or set its binary directory.")
    return resolved


def _default_archive(directory: Path) -> Path:
    subprocess.run(
        ["git", "fetch", "origin", f"{ARCHIVE_BRANCH}:{ARCHIVE_REF}"],
        cwd=ROOT,
        check=True,
    )
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", ARCHIVE_REF, "--", "db/backups"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    latest = max(
        (
            path for path in paths
            if Path(path).name.startswith(f"{DB_NAME}_") and path.endswith(".archive.gz")
        ),
        default=None,
    )
    if latest is None:
        raise RuntimeError(f"No MongoDB archive found in {ARCHIVE_REF}")
    archive = directory / Path(latest).name
    print(f"Using {ARCHIVE_REF}:{latest}", flush=True)
    with archive.open("wb") as output:
        subprocess.run(["git", "show", f"{ARCHIVE_REF}:{latest}"], cwd=ROOT, stdout=output, check=True)
    return archive


def _check_port(port: int) -> None:
    with socket.socket() as listener:
        try:
            listener.bind(("127.0.0.1", port))
        except OSError as error:
            raise RuntimeError(f"Port {port} is already in use on 127.0.0.1") from error


def _wait_for_mongo(client: MongoClient, process: subprocess.Popen) -> None:
    deadline = monotonic() + 25
    while process.poll() is None and monotonic() < deadline:
        try:
            if client.admin.command("serverStatus")["pid"] == process.pid:
                return
            raise RuntimeError("The listening MongoDB is a different process")
        except PyMongoError:
            sleep(0.25)
    raise RuntimeError("MongoDB did not start. See mongod.log in the data directory.")


def _restore(database, uri: str, args: argparse.Namespace) -> None:
    if database.list_collection_names():
        if database.Orchard.find_one({}, {"_id": 1}) is None:
            raise RuntimeError("The existing database has no orchards. Use a fresh --data-dir.")
        return
    with TemporaryDirectory(prefix="orchard-archive-") as directory:
        archive = args.archive or _default_archive(Path(directory))
        with archive.open("rb") as source:
            if source.read(2) != b"\x1f\x8b":
                raise RuntimeError(f"Expected a gzip MongoDB archive at {archive}")
        pending = args.data_dir / ".restore-in-progress"
        pending.touch(exist_ok=False)
        subprocess.run(
            [
                _binary("mongorestore", args.tools_bin or args.mongo_bin),
                f"--uri={uri}",
                f"--archive={archive.resolve()}",
                "--gzip",
                f"--nsInclude={DB_NAME}.*",
                "--stopOnError",
            ],
            check=True,
        )
        if database.Orchard.find_one({}, {"_id": 1}) is None:
            raise RuntimeError("The archive does not contain any orchards")
        pending.unlink()


def _wait_for_chart(
    database, orchard_ids: list, backend: subprocess.Popen, port: int, started: datetime
) -> None:
    query = urlencode({"orchardId": str(orchard_ids[0]), "range": "7d"})
    url = f"http://127.0.0.1:{port}/api/v1/weather/temperature?{query}"
    deadline = monotonic() + 90
    while backend.poll() is None and monotonic() < deadline:
        ready = database.Orchard.count_documents(
            {
                "_id": {"$in": orchard_ids},
                "environmentalData.current.0.fetched_at": {"$gte": started},
                "environmentalData.forecast.0.fetched_at": {"$gte": started},
            }
        )
        if ready == len(orchard_ids):
            try:
                with urlopen(url, timeout=4) as response:
                    chart = json.load(response)
                if chart.get("unit") == "C" and chart.get("points"):
                    print(f"Weather chart ready: {url}", flush=True)
                    return
            except URLError:
                pass
        sleep(0.25)
    raise RuntimeError("The backend did not complete its first synchronization")


def _check_chart_contract(orchard_id, port: int) -> None:
    origin = "http://localhost:5173"
    for period in ("24h", "7d", "30d", "90d", "1y"):
        query = urlencode({"orchardId": str(orchard_id), "range": period})
        url = f"http://127.0.0.1:{port}/api/v1/weather/temperature?{query}"
        with urlopen(Request(url, headers={"Origin": origin}), timeout=4) as response:
            chart = json.load(response)
            if response.headers.get("Access-Control-Allow-Origin") != origin:
                raise RuntimeError("Temperature endpoint did not allow the UI origin")
        if (
            chart.get("orchardId") != str(orchard_id)
            or chart.get("range") != period
            or chart.get("unit") != "C"
            or not chart.get("points")
        ):
            raise RuntimeError(f"Unexpected temperature response for {period}")
        for point in chart["points"]:
            if (
                not isinstance(point.get("timestamp"), str)
                or not isinstance(point.get("label"), str)
                or type(point.get("minTempC")) not in (int, float)
                or type(point.get("maxTempC")) not in (int, float)
                or point["minTempC"] > point["maxTempC"]
            ):
                raise RuntimeError(f"Invalid temperature point for {period}")
        print(f"HTTP 200, range={period}, points={len(chart['points'])}", flush=True)


def _stop_backend(backend: subprocess.Popen) -> None:
    if backend.poll() is not None:
        return
    if WINDOWS:
        # On Windows a venv can launch a second Python process.
        subprocess.run(
            ["taskkill", "/PID", str(backend.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        os.killpg(backend.pid, signal.SIGTERM)
    backend.wait(timeout=20)


def _start(args: argparse.Namespace) -> int:
    pending = args.data_dir / ".restore-in-progress"
    if pending.exists():
        raise RuntimeError("A prior restore was interrupted in this data directory. Use a fresh --data-dir.")
    for port in (args.mongo_port, args.api_port):
        _check_port(port)
    args.data_dir.mkdir(parents=True, exist_ok=True)
    mongo = subprocess.Popen(
        [
            _binary("mongod", args.mongo_bin), "--bind_ip", "127.0.0.1",
            "--port", str(args.mongo_port), "--dbpath", str(args.data_dir),
            "--logpath", str(args.data_dir / "mongod.log"), "--logappend",
        ],
        creationflags=subprocess.CREATE_NO_WINDOW if WINDOWS else 0,
    )
    uri = f"mongodb://127.0.0.1:{args.mongo_port}/"
    environment = {**os.environ, "MONGO_URI": uri, "MONGO_DB": DB_NAME}
    options = ["--point-field", args.point_field, "--timezone", args.timezone]
    command = [sys.executable, "-m", "backend.main"]
    with MongoClient(uri, serverSelectionTimeoutMS=800) as client:
        owns_server = False
        try:
            _wait_for_mongo(client, mongo)
            owns_server = True
            database = client[DB_NAME]
            _restore(database, uri, args)
            for mode in ("migrate", "backfill"):
                subprocess.run(command + [mode] + options, cwd=ROOT, env=environment, check=True)

            orchard_ids = database.Orchard.distinct("_id", {"environmentalData.history.0": {"$exists": True}})
            if not orchard_ids:
                raise RuntimeError("The database has no orchard with imported weather history")
            started = datetime.now(timezone.utc)
            backend = subprocess.Popen(
                command + ["run", "--port", str(args.api_port)] + options,
                cwd=ROOT,
                env=environment,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
                start_new_session=not WINDOWS,
            )
            try:
                _wait_for_chart(database, orchard_ids, backend, args.api_port, started)
                if args.check:
                    _check_chart_contract(orchard_ids[0], args.api_port)
                    return 0
                return backend.wait()
            finally:
                _stop_backend(backend)
        finally:
            if owns_server and mongo.poll() is None:
                try:
                    client.admin.command("shutdown", timeoutSecs=5)
                except PyMongoError:
                    pass
            try:
                mongo.wait(timeout=12)
            except subprocess.TimeoutExpired:
                mongo.terminate()
                mongo.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Local gzip archive; defaults to the latest on origin/ml")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data" / "weather-mongodb")
    parser.add_argument("--mongo-bin", type=Path, help="Directory containing mongod")
    parser.add_argument("--tools-bin", type=Path, help="Directory containing mongorestore")
    parser.add_argument("--mongo-port", type=int, default=27018)
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--point-field", default="centroid")
    parser.add_argument("--timezone", default="auto")
    parser.add_argument("--check", action="store_true", help="Verify the UI contract and stop both services")
    args = parser.parse_args()
    if not all(1 <= port <= 65535 for port in (args.mongo_port, args.api_port)):
        parser.error("Ports must be between 1 and 65535")
    if args.mongo_port == args.api_port:
        parser.error("MongoDB and API require different ports")
    args.data_dir = args.data_dir.resolve()
    try:
        return _start(args)
    except KeyboardInterrupt:
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError, PyMongoError) as error:
        print(f"Weather startup failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
