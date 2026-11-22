"""Orchestration: ordering, resume through the database's own `ingest_log`, one transaction per source file.

The loader writes only rows. It never creates or alters tables, keys, indexes or constraints."""
from __future__ import annotations

import json
import time
import traceback
from datetime import datetime, timezone
from itertools import chain
from pathlib import Path

import pyarrow as pa

from . import __version__
from .backends.base import Backend, to_table
from .config import Settings
from .datasets import REGISTRY, Context, DatasetSpec
from .sources import SourceFile, apply_filters

LEDGER = "ingest_log"      # table from the DDL: dataset, source_file, source_year, row_count, time_shift, loaded_at, note


def order_datasets(names: list[str]) -> list[str]:
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        raise SystemExit(f"unknown dataset(s): {unknown}; available: {list(REGISTRY)}")
    done: list[str] = []
    todo = [n for n in REGISTRY if n in names]            # registry order as the tie-break
    while todo:
        for n in todo:
            if all(d in done or d not in names for d in REGISTRY[n].depends_on):
                done.append(n)
                todo.remove(n)
                break
        else:
            raise SystemExit(f"dependency cycle among {todo}")
    return done


def _fmt_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


class Pipeline:
    def __init__(self, settings: Settings, backend: Backend | None, log=print):
        self.s = settings
        self.backend = backend
        self.log = log
        self.ctx = Context(settings, backend, log)
        self.report: dict = {"loader_version": __version__, "datasets": {}, "validation": []}

    # ---- planning -----------------------------------------------------------------------------------
    def units_for(self, spec: DatasetSpec) -> list[SourceFile]:
        units = apply_filters(spec.discover(self.ctx), self.s.years, self.s.voiv)
        return units[: self.s.limit_files] if self.s.limit_files else units

    def dry_run(self) -> None:
        self.log("DRY RUN: no database access\n")
        for name in order_datasets(self.s.selected):
            try:
                units = self.units_for(REGISTRY[name])
            except Exception as e:
                self.log(f"  {name:18s} cannot discover sources: {e}")
                continue
            size = sum(u.signature()[0] for u in units)
            first = units[0].key(self.s.raw) if units else "-"
            hint = "" if units else "  (no sources: " + (
                "pass --fields <geojson>" if name.startswith("field") and not self.s.fields else "nothing found") + ")"
            self.log(f"  {name:18s} {len(units):4d} unit(s) {_fmt_size(size):>10s}  e.g. {first}{hint}")
        self.log("")

    # ---- ledger (the database's ingest_log) ---------------------------------------------------------------
    def _loaded(self, table: str) -> set[str]:
        b = self.backend
        rows = b.query(f"SELECT source_file FROM {b.tq(LEDGER)} WHERE dataset = ?", (table,))
        return {r[0] for r in rows}

    def _record(self, table: str, key: str, year, rows: int, note: str | None = None) -> None:
        t = pa.table({"dataset": [table], "source_file": [key], "source_year": pa.array([year], pa.int32()),
                      "row_count": pa.array([rows], pa.int64()), "note": pa.array([note], pa.string())})
        self.backend.ingest(LEDGER, [t])           # time_shift stays NULL: dates are loaded unshifted

    # ---- one dataset -----------------------------------------------------------------------------------
    def _run_dataset(self, spec: DatasetSpec) -> None:
        b, s, name = self.backend, self.s, spec.table
        rec = {"units": 0, "loaded": 0, "skipped": 0, "rows": 0, "seconds": 0.0, "status": "ok"}
        self.report["datasets"][name] = rec
        units = self.units_for(spec)
        rec["units"] = len(units)
        if not units:
            rec["status"] = "no-sources"
            self.log(f"[{name}] no source files found - skipping")
            return
        if s.mode == "replace":
            self.log(f"  [{name}] --mode replace: deleting ALL rows from {b.phys(name)!r} and its ingest_log entries")
            b.execute(f"DELETE FROM {b.tq(name)}")
            for t in (name, *spec.dependents):
                b.execute(f"DELETE FROM {b.tq(LEDGER)} WHERE dataset = ?", (t,))
        loaded = self._loaded(name)
        colmap: dict[str, str] | None = None            # lower(source column) -> real column
        t_start = time.time()
        for i, unit in enumerate(units, 1):
            key = unit.key(s.raw)
            if key in loaded:
                rec["skipped"] += 1
                continue
            t0 = time.time()
            if spec.load is not None:                    # own loading path (rasters): same transaction + ledger entry
                with b.transaction():
                    rows = spec.load(unit, self.ctx)
                    self._record(name, key, unit.year, rows)
                rec["loaded"] += 1
                rec["rows"] += rows
                self.log(f"  [{name} {i}/{len(units)}] {key}  {rows:,} rows  {time.time() - t0:.1f}s")
                continue
            gen = (t for t in (to_table(x) for x in spec.produce(unit, self.ctx)) if t.num_rows)
            first = next(gen, None)
            if first is None:
                with b.transaction():
                    self._record(name, key, unit.year, 0, "no rows")
                self.log(f"  [{name} {i}/{len(units)}] {key}: no rows")
                continue
            if colmap is None:                           # match columns by name, once per dataset
                real = b.table_columns(name)
                colmap = {c.lower(): c for c in real}
                src = {c.lower() for c in first.column_names}
                rec["dropped_source_columns"] = [c for c in first.column_names if c.lower() not in colmap]
                rec["unfilled_table_columns"] = [c for c in real if c.lower() not in src]
                if not (src & set(colmap)):
                    raise RuntimeError(f"{name}: no column of {b.phys(name)!r} matches the source "
                                       f"(table has {real}, source has {first.column_names})")
                if rec["dropped_source_columns"]:
                    self.log(f"  [{name}] source columns with no counterpart in the table (not loaded): "
                             f"{rec['dropped_source_columns']}")
                if rec["unfilled_table_columns"]:
                    self.log(f"  [{name}] table columns the source does not provide (default/NULL): "
                             f"{rec['unfilled_table_columns']}")

            def prep(t, colmap=colmap):
                keep = [c for c in t.column_names if c.lower() in colmap]
                return t.select(keep).rename_columns([colmap[c.lower()] for c in keep])

            with b.transaction():                        # rows + ledger entry commit together or not at all
                rows = b.ingest(name, (prep(t) for t in chain([first], gen)))
                self._record(name, key, unit.year, rows)
            rec["loaded"] += 1
            rec["rows"] += rows
            self.log(f"  [{name} {i}/{len(units)}] {key}  {rows:,} rows  {time.time() - t0:.1f}s")
        rec["seconds"] = round(time.time() - t_start, 1)
        if rec["loaded"]:
            b.analyze(name)
        if name in self.ctx.stats:
            rec["stats"] = self.ctx.stats[name]

    # ---- run -----------------------------------------------------------------------------------------------
    def _check_tables(self, names: list[str]) -> list[str]:
        b = self.backend
        need = [*dict.fromkeys([*names, LEDGER])]
        return [f"{n} -> {b.phys(n)}" for n in need if not b.table_exists(n)]

    def run(self) -> int:
        from .validate import run_validation
        s, b = self.s, self.backend
        failed = False
        b.connect()
        try:
            names = order_datasets(s.selected)
            missing = self._check_tables(names)
            if missing:
                self.log("These tables do not exist in the database (the loader never creates tables):\n  "
                         + "\n  ".join(missing)
                         + "\nCreate them from the DDL, or point the loader at the right names with "
                           "config [tables] / --table-map / [database.options] schema.")
                return 2
            if not s.validate_only:
                for name in names:
                    try:
                        self._run_dataset(REGISTRY[name])
                    except Exception as e:
                        failed = True
                        self.report["datasets"][name] = {"status": "failed", "message": f"{type(e).__name__}: {e}"}
                        self.log(f"[{name}] FAILED: {type(e).__name__}: {e}")
                        self.log(traceback.format_exc(limit=4))
            if not s.no_validate:
                results = run_validation(b, s, self.report["datasets"])
                self.report["validation"] = results
                failed = failed or any(r["status"] == "FAIL" for r in results)
        finally:
            b.close()
        self._write_report()
        self._summary()
        return 1 if failed else 0

    def _write_report(self) -> None:
        self.report["built_at"] = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        self.report["backend"] = self.s.backend
        Path(self.s.report).parent.mkdir(parents=True, exist_ok=True)
        Path(self.s.report).write_text(json.dumps(self.report, indent=2, default=str), encoding="utf-8")

    def _summary(self) -> None:
        self.log("\n" + "=" * 78)
        self.log(f"{'dataset':18s}{'status':12s}{'units':>7s}{'loaded':>8s}{'skipped':>9s}{'rows':>14s}{'sec':>8s}")
        for name, r in self.report["datasets"].items():
            self.log(f"{name:18s}{r.get('status', '?'):12s}{r.get('units', 0):7d}{r.get('loaded', 0):8d}"
                     f"{r.get('skipped', 0):9d}{r.get('rows', 0):14,d}{r.get('seconds', 0):8.1f}")
        for v in self.report["validation"]:
            if v["status"] != "OK":
                self.log(f"  [{v['status']}] {v['check']}: {v['detail']}")
        self.log(f"report: {self.s.report}")
