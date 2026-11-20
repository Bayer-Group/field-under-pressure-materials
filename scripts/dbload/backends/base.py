"""Abstract database backend (kept thin so another engine is one small class).

Logical table names (grid_cell, weather_hourly, ...) are mapped to real table names through `aliases`
(config [tables]); all public methods take LOGICAL names. The loader never creates or alters schema."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Iterable

import pyarrow as pa


def to_table(chunk) -> pa.Table:
    return pa.Table.from_batches([chunk]) if isinstance(chunk, pa.RecordBatch) else chunk


class Backend(ABC):
    name = "base"

    def __init__(self, dsn: str, aliases: dict[str, str] | None = None, **options):
        self.dsn = dsn
        self.aliases = dict(aliases or {})
        self.options = options
        self.con = None

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def close(self) -> None: ...

    @abstractmethod
    def execute(self, sql: str, params: tuple = ()) -> None: ...

    @abstractmethod
    def query(self, sql: str, params: tuple = ()) -> list[tuple]: ...

    @abstractmethod
    def table_exists(self, name: str) -> bool: ...

    @abstractmethod
    def table_columns(self, table: str) -> list[str]:
        """Writable column names of an existing table (generated columns excluded)."""

    @abstractmethod
    def ingest(self, table: str, chunks: Iterable) -> int:
        """Append Arrow tables to `table`, columns matched BY NAME; return the rows written."""

    # ---- shared ---------------------------------------------------------------------------------
    @staticmethod
    def qi(ident: str) -> str:
        return '"' + ident.replace('"', '""') + '"'

    def phys(self, table: str) -> str:
        return self.aliases.get(table, table)

    def tq(self, table: str) -> str:
        """Quoted physical name for SQL ('schema.table' allowed in aliases)."""
        return ".".join(self.qi(p) for p in self.phys(table).split("."))

    def count(self, table: str) -> int:
        return int(self.query(f"SELECT COUNT(*) FROM {self.tq(table)}")[0][0])

    def analyze(self, table: str) -> None:
        """Refresh planner statistics after a bulk load (default: nothing)."""

    @contextmanager
    def transaction(self):
        self.execute("BEGIN")
        try:
            yield
        except BaseException:
            self.execute("ROLLBACK")
            raise
        else:
            self.execute("COMMIT")
