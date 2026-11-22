"""Tworzy tabele PostGIS i — gdy public.fields jest pusta — ładuje granice pól.

Przy każdym nowym polu wstawia też wiersz field_profile z tym samym id:
area_ha z GeoJSON granic, crop z crop_type w pliku upraw, gleba z profilu
SoilGrids (soilTexture → texture, oraz permeability i water_retention).
Brak pliku albo brak dopasowania daje NULL.
as_of ustawia baza na bieżący dzień.

Połączenie bierze z .env (PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD).
GeoJSON data/fields/{POWIAT}_fields.geojson jest w WGS84; do bazy trafia
EPSG:2180, bo telegram_alerts liczy otoczkę pola w metrach (ST_Expand 150).

    python dbseed.py
    python dbseed.py --powiat lowicki
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from shapely import to_wkb

from env_config import load_env_file

ROOT = Path(__file__).parent
FIELDS_SRID = os.environ.get("FIELDS_SRID", 2180)

FIELD_PROFILE_SQL = """
CREATE TABLE IF NOT EXISTS public.field_profile (
    field_id          integer PRIMARY KEY,
    area_ha           double precision,
    crop              text,
    texture           text,
    sand_pct          double precision,
    silt_pct          double precision,
    clay_pct          double precision,
    ph                double precision,
    klasa_bonitacyjna text,
    bonitation_source text,
    permeability      text,
    water_retention   text,
    as_of             date,
    updated_at        timestamptz DEFAULT now()
)
"""

FIELD_CALENDAR_SQL = """
CREATE TABLE IF NOT EXISTS public.field_calendar (
    id                 serial PRIMARY KEY,
    field_id           integer NOT NULL,
    day                date NOT NULL,
    fertilizer         text NOT NULL,
    crop               text,
    status             text,
    fert_reasons       text,
    irrigation_risk    text,
    irrigation_reasons text,
    temp_mean_c        double precision,
    precip_24h_mm      double precision,
    precip_72h_mm      double precision,
    sm_l1              double precision,
    sm_l2              double precision,
    sm_l3              double precision,
    ndvi               double precision,
    ndmi               double precision,
    UNIQUE (field_id, day, fertilizer)
)
"""

FIELDS_SQL = f"""
CREATE TABLE public.fields (
    id       integer PRIMARY KEY,
    geometry geometry(Geometry, {FIELDS_SRID})
)
"""


def _connect():
    missing = [key for key in ("PGHOST", "PGPORT", "PGDATABASE", "PGUSER", "PGPASSWORD") if not os.environ.get(key)]
    if missing:
        raise SystemExit(f"Brak w .env: {', '.join(missing)}")
    print(
        f"łączę z PostgreSQL {os.environ['PGUSER']}@{os.environ['PGHOST']}:"
        f"{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )
    return psycopg2.connect(
        host=os.environ["PGHOST"],
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


def _ensure_table(cur, name: str, sql: str) -> None:
    cur.execute("SELECT to_regclass(%s)", (f"public.{name}",))
    existed = cur.fetchone()[0] is not None
    cur.execute(sql)
    print(f"public.{name}: {'już istnieje' if existed else 'utworzono'}")


def _num(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return float(value)


def _text(value):
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    text = str(value).strip()
    return text or None


def _soil_row_index(raw) -> int | None:
    """field_0 z profilu gleby to wiersz 0 GeoJSON, w tej samej kolejności co granice."""
    text = _text(raw)
    if text is None:
        return None
    if text.startswith("field_"):
        text = text.removeprefix("field_")
    if text.isdigit():
        return int(text)
    return None


def _crops_by_row(path: Path, count: int) -> list:
    crops: list[str | None] = [None] * count
    if not path.exists():
        print(f"brak upraw: {path.name} — crop = NULL")
        return crops
    table = gpd.read_file(path)
    column = "crop_type" if "crop_type" in table.columns else "crop" if "crop" in table.columns else None
    if column is None:
        print(f"{path.name} nie ma kolumny crop_type — crop = NULL")
        return crops
    if len(table) != count:
        print(f"uwaga: {path.name} ma {len(table)} pól, granice mają {count} — dopasowanie po pozycji")
    for index, value in enumerate(table[column]):
        if index >= count:
            break
        crops[index] = _text(value)
    return crops


def _soil_by_row(path: Path, indexes: list[int]) -> dict[int, dict]:
    """Tylko kolumny profilu i tylko pola z indexes. Reszty pliku DuckDB nie zaciąga do Pythona."""
    if not path.exists():
        print(f"brak profili gleby: {path.name} — sand/silt/clay/ph/texture/permeability/water_retention = NULL")
        return {}
    if not indexes:
        return {}

    con = duckdb.connect()
    try:
        columns = {row[0] for row in con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()}
        if "field_id" not in columns:
            print(f"{path.name} nie ma kolumny field_id — gleba = NULL")
            return {}
        def _col(name: str, cast: str) -> str:
            if name not in columns:
                return f"CAST(NULL AS {cast})"
            return '"' + name.replace('"', '""') + '"'

        texture_name = "soilTexture" if "soilTexture" in columns else "texture" if "texture" in columns else None
        texture_sql = _col(texture_name, "VARCHAR") if texture_name else "CAST(NULL AS VARCHAR)"
        wanted = [f"field_{index}" for index in indexes] + [str(index) for index in indexes]
        con.execute("CREATE TEMP TABLE wanted (field_id VARCHAR)")
        con.executemany("INSERT INTO wanted VALUES (?)", [(value,) for value in wanted])
        rows = con.execute(
            f"""
            SELECT
                field_id,
                {_col("sand_pct", "DOUBLE")} AS sand_pct,
                {_col("silt_pct", "DOUBLE")} AS silt_pct,
                {_col("clay_pct", "DOUBLE")} AS clay_pct,
                {_col("ph", "DOUBLE")} AS ph,
                {texture_sql} AS texture,
                {_col("permeability", "VARCHAR")} AS permeability,
                {_col("water_retention", "VARCHAR")} AS water_retention
            FROM read_parquet(?)
            WHERE field_id IN (SELECT field_id FROM wanted)
            """,
            [str(path)],
        ).fetchall()
    finally:
        con.close()

    found: dict[int, dict] = {}
    for field_id, sand, silt, clay, ph, texture_value, permeability, water_retention in rows:
        index = _soil_row_index(field_id)
        if index is None:
            continue
        found[index] = {
            "sand_pct": sand,
            "silt_pct": silt,
            "clay_pct": clay,
            "ph": ph,
            "soilTexture": texture_value,
            "permeability": permeability,
            "water_retention": water_retention,
        }
    print(f"profile gleby: {len(found)} z {path.name}")
    return found


def _insert_profiles(cur, fields: gpd.GeoDataFrame, powiat: str) -> None:
    cur.execute("SELECT id FROM public.fields")
    present = {row[0] for row in cur.fetchall()}
    cur.execute("SELECT field_id FROM public.field_profile")
    profiled = {row[0] for row in cur.fetchall()}
    pending = [
        int(index)
        for index in range(len(fields))
        if (int(index) + 1) in present and (int(index) + 1) not in profiled
    ]
    if not pending:
        print("public.field_profile: profile już są — pomijam")
        return

    crops = _crops_by_row(ROOT / "data" / "fields" / f"{powiat}_fields_crops.geojson", len(fields))
    soils = _soil_by_row(ROOT / "data" / "soil" / "fields_soil_profiles.parquet", pending)
    rows = []
    for index in pending:
        field = fields.iloc[index]
        soil = soils.get(index, {})
        rows.append(
            (
                index + 1,
                _num(field.get("area_ha")),
                crops[index],
                _text(soil.get("soilTexture", soil.get("texture"))),
                _num(soil.get("sand_pct")),
                _num(soil.get("silt_pct")),
                _num(soil.get("clay_pct")),
                _num(soil.get("ph")),
                _text(soil.get("permeability")),
                _text(soil.get("water_retention")),
            )
        )
    execute_values(
        cur,
        """
        INSERT INTO public.field_profile
            (field_id, area_ha, crop, texture, sand_pct, silt_pct, clay_pct, ph,
             permeability, water_retention, as_of)
        VALUES %s
        ON CONFLICT (field_id) DO NOTHING
        """,
        rows,
        template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_DATE)",
        page_size=200,
    )
    print(f"public.field_profile: wstawiono {len(rows)} profili")


def _load_fields(cur, powiat: str) -> None:
    cur.execute("SELECT to_regclass('public.fields')")
    existed = cur.fetchone()[0] is not None
    if existed:
        cur.execute("SELECT count(*) FROM public.fields")
        count = cur.fetchone()[0]
        if count:
            print(f"public.fields: {count} wierszy — pomijam geometrie")
        else:
            print("public.fields: pusta — wczytuję GeoJSON")
    else:
        cur.execute(FIELDS_SQL)
        count = 0
        print("public.fields: utworzono")

    path = ROOT / "data" / "fields" / f"{powiat}_fields.geojson"
    if not path.exists():
        raise FileNotFoundError(f"Brak pliku granic pól: {path}")

    fields = gpd.read_file(path).reset_index(drop=True)
    if fields.crs is None:
        fields = fields.set_crs(4326)
    fields = fields.to_crs(FIELDS_SRID)

    if not existed or count == 0:
        cur.execute("CREATE INDEX IF NOT EXISTS fields_geometry_gix ON public.fields USING GIST (geometry)")
        rows = [
            (index + 1, to_wkb(geom))
            for index, geom in enumerate(fields.geometry)
            if geom is not None and not geom.is_empty
        ]
        execute_values(
            cur,
            "INSERT INTO public.fields (id, geometry) VALUES %s",
            rows,
            template=f"(%s, ST_SetSRID(ST_GeomFromWKB(%s), {FIELDS_SRID}))",
            page_size=200,
        )
        print(f"public.fields: wstawiono {len(rows)} pól z {path.name}")

    _insert_profiles(cur, fields, powiat)


def seed(powiat: str) -> None:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS postgis")
        _ensure_table(cur, "field_profile", FIELD_PROFILE_SQL)
        _ensure_table(cur, "field_calendar", FIELD_CALENDAR_SQL)
        _load_fields(cur, powiat)
    print("gotowe")