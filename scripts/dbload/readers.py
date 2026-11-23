"""Streaming Parquet reads (never loads a whole dataset)."""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq


def iter_parquet_tables(path: Path, columns: list[str] | None, batch_size: int) -> Iterator[pa.Table]:
    pf = pq.ParquetFile(path)
    for batch in pf.iter_batches(batch_size=batch_size, columns=columns):
        yield pa.Table.from_batches([batch])


def read_parquet_table(path: Path, columns: list[str] | None = None) -> pa.Table:
    return pq.read_table(path, columns=columns)


def slices(table: pa.Table, size: int) -> Iterator[pa.Table]:
    for off in range(0, table.num_rows, size):
        yield table.slice(off, size)
