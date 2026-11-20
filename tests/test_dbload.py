"""Tests for scripts/dbload on synthetic data. Run:  python -I -m unittest discover -s tests -v

The shipped backend is PostGIS, which needs a server. The pipeline logic is exercised through a SQLite
double (tests/sqlite_double.py) on a SQLite rendition of the `fup` DDL. PostGIS-specific code
(COPY, EWKT parsing by the server, schema/search_path, information_schema lookups) is NOT covered here.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "scripts")]

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from affine import Affine

from dbload import transforms as T
from dbload.backends import register_backend
from dbload.config import Settings, parse_months
from dbload.fields import load_fields, to_ewkt
from dbload.pipeline import Pipeline
from dbload.raster_agg import field_class_counts
from dbload.sources import parse_parquet_path
from sqlite_double import SQLiteBackend

register_backend("sqlite", SQLiteBackend)

DDL = """
CREATE TABLE grid_cell (grid_id TEXT PRIMARY KEY, lat REAL NOT NULL, lon REAL NOT NULL, geom TEXT NOT NULL,
                        geohash4 TEXT, time_zone TEXT);
CREATE TABLE weather_hourly (grid_id TEXT NOT NULL REFERENCES grid_cell (grid_id), date TEXT NOT NULL,
    utc_time TEXT NOT NULL, local_time TEXT NOT NULL, temperature REAL, dew_point_temperature REAL,
    precipitation REAL, wind_speed REAL, eto REAL, PRIMARY KEY (grid_id, utc_time));
CREATE TABLE crop_class (code INTEGER PRIMARY KEY, name TEXT NOT NULL);
INSERT INTO crop_class VALUES (0, 'No cropland'), (1110, 'Wheat'), (65535, 'Outside area');
CREATE TABLE field (field_id TEXT PRIMARY KEY, name TEXT, source TEXT, geom TEXT NOT NULL);
CREATE TABLE field_crop_share (field_id TEXT NOT NULL REFERENCES field (field_id) ON DELETE CASCADE,
    year INTEGER NOT NULL, class_code INTEGER NOT NULL REFERENCES crop_class (code),
    pixel_count INTEGER NOT NULL, share REAL NOT NULL CHECK (share >= 0 AND share <= 1),
    PRIMARY KEY (field_id, year, class_code));
CREATE TABLE ingest_log (id INTEGER PRIMARY KEY AUTOINCREMENT, dataset TEXT NOT NULL, source_file TEXT,
    source_year INTEGER, row_count INTEGER, time_shift TEXT, loaded_at TEXT DEFAULT CURRENT_TIMESTAMP, note TEXT);
"""

LAT0, LON0, STEP = 50.0, 17.0, 0.044
CELLS = [(i, j) for i in range(3) for j in range(3)]
GID = {c: f"G{c[0]}{c[1]}" for c in CELLS}
VOIV = {0: "Opolskie", 1: "Małopolskie", 2: "Łódzkie"}
HOURS = [datetime(2024, 1, 1) + timedelta(hours=h) for h in range(48)]


def write(path: Path, table: pa.Table):
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def rect(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def make_raw(raw: Path) -> Path:
    # weather grid (decimal lat/lon like the real file, plus its own WKB geom column)
    write(raw / "weather_grids" / "weather_grids.parquet", pa.table({
        "grid_id": [GID[c] for c in CELLS],
        "lat": pa.array([Decimal(f"{LAT0 + STEP * i:.3f}") for i, j in CELLS], pa.decimal128(38, 9)),
        "lon": pa.array([Decimal(f"{LON0 + STEP * j:.3f}") for i, j in CELLS], pa.decimal128(38, 9)),
        "l1_name": [VOIV[i] for i, j in CELLS], "geom": [b"\x01"] * 9}))
    # hourly weather: Opolskie (with IMERG) and Malopolskie (mangled file name, NO IMERG file)
    for slug, fname, row in (("opolskie", "weather_hourly_2024_Opolskie_part000", 0),
                             ("malopolskie", "weather_hourly_2024_Maopolskie", 1)):
        g = [GID[(row, j)] for j in range(3) for _ in HOURS]
        ut = [h for _ in range(3) for h in HOURS]
        write(raw / "weather_hourly" / "year=2024" / f"voivodeship={slug}" / f"{fname}.parquet", pa.table({
            "grid_id": g, "elevation": [200.0] * len(g), "utc_time": pa.array(ut, pa.timestamp("us")),
            "local_time": pa.array([u + timedelta(hours=1) for u in ut], pa.timestamp("us")),
            "date": pa.array([(u + timedelta(hours=1)).date() for u in ut], pa.date32()),
            "temperature": [1.0] * len(g), "u_component_of_wind_10m": [0.5] * len(g)}))
    g = [GID[(0, j)] for j in range(3) for _ in HOURS]
    ut = [h for _ in range(3) for h in HOURS]
    write(raw / "imerg_hourly" / "hourly" / "2024" / "precip_hourly_2024_Opolskie.parquet", pa.table({
        "grid_id": g + g[:2], "utc_time": pa.array(ut + ut[:2], pa.timestamp("us")),    # 2 duplicated keys
        "local_time": pa.array(ut + ut[:2], pa.timestamp("us")),
        "local_date": pa.array([u.date() for u in ut + ut[:2]], pa.date32()), "precipitation": [0.1] * (len(g) + 2)}))
    # cropland 2024: 40x40 px, 0.0001 deg; left half wheat, right half 0, top-right 4x4 outside area
    arr = np.zeros((40, 40), dtype=np.uint16)
    arr[:, :20] = 1110
    arr[0:4, 36:40] = 65535
    tif = raw / "cropland" / "year=2024" / "CLMS_HRLVLCC_CTY_PL_0.tif"
    tif.parent.mkdir(parents=True)
    with rasterio.open(tif, "w", driver="GTiff", height=40, width=40, count=1, dtype="uint16", crs="EPSG:4326",
                       transform=Affine(0.0001, 0, 17.0, 0, -0.0001, 50.004), nodata=65535) as dst:
        dst.write(arr, 1)
    # fields: A over 30x20 px (15 wheat + 15 no-crop columns), B outside the tiles, C on the outside-area block
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"field_id": "A", "name": "Field A"}, "geometry": rect(17.0005, 50.001, 17.0035, 50.003)},
        {"type": "Feature", "properties": {"field_id": "B"}, "geometry": rect(18.0, 51.0, 18.001, 51.001)},
        {"type": "Feature", "properties": {"id": "C"}, "geometry": rect(17.0036, 50.0036, 17.0040, 50.0040)}]}
    gj = raw.parent / "fields.geojson"
    gj.write_text(json.dumps(fc), encoding="utf-8")
    return gj


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.raw = self.root / "raw"
        self.geojson = make_raw(self.raw)
        self.dsn = str(self.root / "db.sqlite")
        con = sqlite3.connect(self.dsn)
        con.executescript(DDL)
        con.commit()
        con.close()

    def settings(self, **kw) -> Settings:
        s = Settings(root=self.root, raw=self.raw, report=self.root / "report.json", backend="sqlite",
                     dsn=self.dsn, batch_size=50, fields=self.geojson)
        for k, v in kw.items():
            setattr(s, k, v)
        return s

    def run_pipeline(self, **kw):
        s = self.settings(**kw)
        out: list = []
        p = Pipeline(s, SQLiteBackend(s.resolved_dsn(), aliases=s.table_map), log=out.append)
        return p, p.run(), "\n".join(map(str, out))

    def q(self, sql, params=()):
        con = sqlite3.connect(self.dsn)
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()


class UnitTests(unittest.TestCase):
    def test_geohash_reference_value(self):
        self.assertEqual(T.geohash(57.64911, 10.40744, 11), "u4pruydqqvj")        # canonical example
        self.assertEqual(T.geohash(57.64911, 10.40744, 4), "u4pr")

    def test_ewkt(self):
        self.assertEqual(T.ewkt_point(21.006, 50.44), "SRID=4326;POINT(21.006000000 50.440000000)")
        self.assertEqual(to_ewkt(rect(1, 2, 3, 4)), "SRID=4326;POLYGON((1 2, 3 2, 3 4, 1 4, 1 2))")
        mp = {"type": "MultiPolygon", "coordinates": [rect(0, 0, 1, 1)["coordinates"]]}
        self.assertTrue(to_ewkt(mp).startswith("SRID=4326;MULTIPOLYGON(((0 0"))

    def test_path_parsing(self):
        p = Path("raw/weather_hourly/year=2024/voivodeship=kujawsko_pomorskie/weather_hourly_2024_Kujawsko-Pomorskie_part001.parquet")
        self.assertEqual(parse_parquet_path(p), (2024, "kujawsko_pomorskie"))
        self.assertEqual(parse_parquet_path(Path("imerg_hourly/hourly/2020/precip_hourly_2020_odzkie.parquet")), (2020, "lodzkie"))
        self.assertEqual(parse_parquet_path(Path("imerg_hourly/hourly/2020/precip_hourly_2020_Maopolskie.parquet")), (2020, "malopolskie"))

    def test_dedupe_and_months(self):
        out, removed = T.dedupe(pa.table({"k": [1, 1, 2], "v": [1.0, 1.0, 2.0]}), ["k"])
        self.assertEqual((out.num_rows, removed), (2, 1))
        self.assertEqual(parse_months("4-6,9"), {4, 5, 6, 9})

    def test_fields_loader_rejects_non_polygons_and_duplicates(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "f.geojson"
            p.write_text(json.dumps({"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"id": 1}, "geometry": {"type": "Point", "coordinates": [1, 2]}}]}))
            with self.assertRaisesRegex(ValueError, "Polygon"):
                load_fields(p)
            f = {"type": "Feature", "properties": {"id": "x"}, "geometry": rect(0, 0, 1, 1)}
            p.write_text(json.dumps({"type": "FeatureCollection", "features": [f, f]}))
            with self.assertRaisesRegex(ValueError, "duplicate"):
                load_fields(p)

    def test_field_class_counts(self):
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / "raw"
            gj = make_raw(raw)
            counts = field_class_counts([raw / "cropland" / "year=2024" / "CLMS_HRLVLCC_CTY_PL_0.tif"], load_fields(gj), log=lambda *_: None)
            self.assertEqual(dict(counts["A"]), {1110: 300, 0: 300})
            self.assertEqual(dict(counts["C"]), {65535: 16})
            self.assertNotIn("B", counts)


class PipelineTests(Base):
    def test_full_load(self):
        p, code, log = self.run_pipeline()
        self.assertEqual(code, 0, log)
        # grid_cell: geometry as EWKT, geohash computed, time_zone untouched
        g = self.q("SELECT grid_id, lat, lon, geom, geohash4, time_zone FROM grid_cell WHERE grid_id = 'G11'")[0]
        self.assertAlmostEqual(g[1], LAT0 + STEP, places=9)
        self.assertAlmostEqual(g[2], LON0 + STEP, places=9)
        self.assertTrue(g[3].startswith("SRID=4326;POINT(17.044"))
        self.assertEqual(len(g[4]), 4)
        self.assertIsNone(g[5])
        self.assertEqual(self.q("SELECT COUNT(*) FROM grid_cell")[0][0], 9)
        # weather_hourly: both voivodeships, original timestamps, IMERG merged (duplicates did not multiply rows)
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly")[0][0], 288)
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly WHERE precipitation = 0.1")[0][0], 144)
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly WHERE precipitation IS NULL")[0][0], 144)
        r = self.q("SELECT utc_time, local_time, date FROM weather_hourly WHERE grid_id = 'G00' ORDER BY utc_time LIMIT 1")[0]
        self.assertEqual(r, ("2024-01-01 00:00:00", "2024-01-01 01:00:00", "2024-01-01"))
        wh = p.report["datasets"]["weather_hourly"]
        self.assertEqual(sorted(wh["dropped_source_columns"]), ["elevation", "u_component_of_wind_10m"])
        self.assertIn("dew_point_temperature", wh["unfilled_table_columns"])
        self.assertEqual(wh["stats"]["imerg_duplicate_rows_removed"], 2)
        self.assertEqual(wh["stats"]["units_without_precipitation"], 1)
        # fields and shares
        self.assertEqual(self.q("SELECT field_id, name, source FROM field ORDER BY field_id"),
                         [("A", "Field A", "fields.geojson"), ("B", None, "fields.geojson"), ("C", None, "fields.geojson")])
        self.assertTrue(self.q("SELECT geom FROM field WHERE field_id = 'A'")[0][0].startswith("SRID=4326;POLYGON(("))
        shares = self.q("SELECT field_id, year, class_code, pixel_count, share FROM field_crop_share ORDER BY 1, 3")
        self.assertEqual(shares, [("A", 2024, 0, 300, 0.5), ("A", 2024, 1110, 300, 0.5), ("C", 2024, 65535, 16, 1.0)])
        # provenance in the database's own ingest_log; time_shift left NULL
        log_rows = self.q("SELECT dataset, source_year, row_count, time_shift FROM ingest_log ORDER BY id")
        self.assertEqual({r[0] for r in log_rows}, {"grid_cell", "weather_hourly", "field", "field_crop_share"})
        self.assertEqual(sum(r[2] for r in log_rows if r[0] == "weather_hourly"), 288)
        self.assertTrue(all(r[3] is None for r in log_rows))
        self.assertEqual([v for v in p.report["validation"] if v["status"] == "FAIL"], [])
        # the loader changed no schema
        self.assertEqual(len(self.q("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")), 6)

    def test_resume_skips_loaded_files(self):
        self.run_pipeline()
        p, code, _ = self.run_pipeline()
        self.assertEqual(code, 0)
        for name in ("grid_cell", "weather_hourly", "field", "field_crop_share"):
            self.assertEqual(p.report["datasets"][name]["loaded"], 0, name)
            self.assertGreaterEqual(p.report["datasets"][name]["skipped"], 1, name)
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly")[0][0], 288)

    def test_failed_file_rolls_back_and_is_not_logged(self):
        self.run_pipeline(datasets=("grid_cell",))
        self.q("SELECT 1")
        con = sqlite3.connect(self.dsn)
        con.execute("INSERT INTO weather_hourly (grid_id, date, utc_time, local_time) VALUES ('G00', '2024-01-01', '2024-01-01 00:00:00', 'x')")
        con.commit()
        con.close()
        p, code, _ = self.run_pipeline(datasets=("weather_hourly",), voiv={"opolskie"})   # PK clash on the first row
        self.assertEqual(code, 1)
        self.assertEqual(p.report["datasets"]["weather_hourly"]["status"], "failed")
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly")[0][0], 1)               # nothing partial
        self.assertEqual(self.q("SELECT COUNT(*) FROM ingest_log WHERE dataset = 'weather_hourly'")[0][0], 0)

    def test_filters(self):
        self.run_pipeline(datasets=("grid_cell", "weather_hourly"), voiv={"opolskie"})
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly")[0][0], 144)
        self.run_pipeline(datasets=("weather_hourly",), months={2}, mode="replace")
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly")[0][0], 0)              # no February rows in the data

    def test_replace_deletes_rows_and_ledger_only(self):
        self.run_pipeline()
        self.run_pipeline(mode="replace", datasets=("field", "field_crop_share"))
        self.assertEqual(self.q("SELECT COUNT(*) FROM field")[0][0], 3)
        self.assertEqual(self.q("SELECT COUNT(*) FROM field_crop_share")[0][0], 3)
        self.assertEqual(self.q("SELECT COUNT(*) FROM ingest_log WHERE dataset = 'field'")[0][0], 1)
        self.assertEqual(self.q("SELECT COUNT(*) FROM weather_hourly")[0][0], 288)

    def test_missing_tables_are_reported_not_created(self):
        con = sqlite3.connect(self.dsn)
        con.executescript("DROP TABLE field_crop_share; DROP TABLE weather_hourly;")
        con.close()
        p, code, log = self.run_pipeline()
        self.assertEqual(code, 2)
        self.assertIn("weather_hourly -> weather_hourly", log)
        self.assertIn("never creates tables", log)
        self.assertFalse(self.q("SELECT 1 FROM sqlite_master WHERE name = 'weather_hourly'"))

    def test_table_map(self):
        con = sqlite3.connect(self.dsn)
        con.executescript("ALTER TABLE grid_cell RENAME TO gc;")
        con.close()
        p, code, log = self.run_pipeline(datasets=("grid_cell",), table_map={"grid_cell": "gc"})
        self.assertEqual(code, 0, log)
        self.assertEqual(self.q("SELECT COUNT(*) FROM gc")[0][0], 9)

    def test_field_datasets_need_fields_file(self):
        p, code, log = self.run_pipeline(fields=None, datasets=("field", "field_crop_share"))
        self.assertEqual(p.report["datasets"]["field"]["status"], "no-sources")
        self.assertEqual(self.q("SELECT COUNT(*) FROM field")[0][0], 0)

    def test_dry_run_touches_nothing(self):
        out = []
        Pipeline(self.settings(), None, log=out.append).dry_run()
        self.assertIn("weather_hourly", "\n".join(out))
        self.assertEqual(self.q("SELECT COUNT(*) FROM grid_cell")[0][0], 0)


if __name__ == "__main__":
    unittest.main()
