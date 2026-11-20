"""SQLite stand-in for the PostGIS backend, used ONLY by the tests to exercise the pipeline logic."""
from __future__ import annotations

import sqlite3
from typing import Iterable

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.types as pat

from dbload.backends.base import Backend, to_table


class SQLiteBackend(Backend):
    name = "sqlite"

    def connect(self) -> None:
        self.con = sqlite3.connect(self.dsn, isolation_level=None)   # autocommit; explicit BEGIN/COMMIT

    def close(self) -> None:
        if self.con is not None:
            self.con.close()
            self.con = None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.con.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self.con.execute(sql, params).fetchall()

    def table_exists(self, name: str) -> bool:
        return bool(self.query("SELECT COUNT(*) FROM sqlite_master WHERE name = ?", (self.phys(name),))[0][0])

    def table_columns(self, table: str) -> list[str]:
        return [r[1] for r in self.query(f"PRAGMA table_info({self.tq(table)})")]

    def ingest(self, table: str, chunks: Iterable) -> int:
        n = 0
        for chunk in chunks:
            t = to_table(chunk)
            if t.num_rows == 0:
                continue
            cols = []
            for col in t.columns:   # dates/timestamps as ISO text
                if pat.is_timestamp(col.type):
                    col = pc.strftime(col.cast(pa.timestamp("s")), "%Y-%m-%d %H:%M:%S")
                elif pat.is_date(col.type):
                    col = col.cast(pa.string())
                cols.append(col.to_pylist())
            names = ", ".join(self.qi(c) for c in t.column_names)
            marks = ", ".join("?" * t.num_columns)
            self.con.executemany(f"INSERT INTO {self.tq(table)} ({names}) VALUES ({marks})", zip(*cols))
            n += t.num_rows
        return n
