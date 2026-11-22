"""PostgreSQL + PostGIS backend (psycopg 3). The one shipped target.

Connection string: env LOAD_DB_DSN (preferred) or --dsn, e.g.
    postgresql://user:password@host:5432/dbname
Never put credentials in config/load_db.toml or in git.

- Loads into EXISTING tables: columns are matched by name on COPY; nothing is created or altered.
- `schema` option => `SET search_path TO <schema>, public` (the DDL uses `SET search_path = fup, public`).
- Session time zone is forced to UTC so naive UTC strings land correctly in `timestamptz` columns.
- Bulk load = COPY ... FORMAT csv fed by pyarrow's CSV writer. Geometry columns are passed as EWKT text
  (`SRID=4326;POINT(...)`), which PostGIS parses on input.
- Autocommit connection; the pipeline wraps each source file in an explicit BEGIN/COMMIT.
"""
from __future__ import annotations

import io
import os
from itertools import chain
from typing import Iterable

from .base import Backend, to_table


class PostgisBackend(Backend):
    name = "postgis"

    def connect(self) -> None:
        import psycopg
        dsn = os.environ.get("LOAD_DB_DSN") or self.dsn
        if not dsn:
            raise RuntimeError("no connection string: set env LOAD_DB_DSN or pass --dsn "
                               "(postgresql://user:password@host:5432/dbname)")
        self.con = psycopg.connect(dsn, autocommit=True)
        self.execute("SET TIME ZONE 'UTC'")
        self.execute("SET synchronous_commit = off")   # a crash can only lose the last files, together with their ledger rows
        schema = self.options.get("schema")
        if schema:
            self.execute(f"SET search_path TO {self.qi(schema)}, public")

    def close(self) -> None:
        if self.con is not None:
            self.con.close()
            self.con = None

    @staticmethod
    def _fix(sql: str) -> str:
        return sql.replace("?", "%s")        # internal SQL only; no literal '?' in our statements

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.con.execute(self._fix(sql), params)

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self.con.execute(self._fix(sql), params).fetchall()

    def _where(self, table: str) -> tuple[str, tuple]:
        parts = self.phys(table).split(".")
        if len(parts) == 2:
            return "table_name = ? AND table_schema = ?", (parts[1], parts[0])
        return "table_name = ? AND table_schema = current_schema()", (parts[0],)

    def table_exists(self, name: str) -> bool:
        where, p = self._where(name)
        return bool(self.query(f"SELECT COUNT(*) FROM information_schema.tables WHERE {where}", p)[0][0])

    def table_columns(self, table: str) -> list[str]:
        where, p = self._where(table)
        rows = self.query(f"SELECT column_name FROM information_schema.columns WHERE {where} "
                          "AND is_generated = 'NEVER' ORDER BY ordinal_position", p)
        return [r[0] for r in rows]

    def analyze(self, table: str) -> None:
        self.execute(f"ANALYZE {self.tq(table)}")

    def ingest(self, table: str, chunks: Iterable) -> int:
        import pyarrow.csv as pacsv
        tables = (t for t in map(to_table, chunks) if t.num_rows)
        first = next(tables, None)
        if first is None:
            return 0
        cols = ", ".join(self.qi(c) for c in first.column_names)
        n = 0
        opts = pacsv.WriteOptions(include_header=False)
        with self.con.cursor() as cur, cur.copy(f"COPY {self.tq(table)} ({cols}) FROM STDIN WITH (FORMAT csv)") as cp:
            for t in chain([first], tables):
                buf = io.BytesIO()
                pacsv.write_csv(t, buf, opts)
                cp.write(buf.getvalue())
                n += t.num_rows
        return n
