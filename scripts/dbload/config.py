"""Settings: config/load_db.toml merged with CLI overrides."""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DATASETS = ("grid_cell", "weather_hourly", "field", "field_crop_share")


def _abs(root: Path, p) -> Path:
    p = Path(p)
    return p if p.is_absolute() else root / p


def parse_months(text: str | None) -> set[int] | None:
    """'4-9' -> {4..9}; '4,5,9' -> {4,5,9}."""
    if not text:
        return None
    out: set[int] = set()
    for part in str(text).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out.update(range(int(a), int(b) + 1))
        elif part:
            out.add(int(part))
    bad = [m for m in out if not 1 <= m <= 12]
    if bad:
        raise ValueError(f"invalid month(s): {bad}")
    return out


@dataclass
class Settings:
    root: Path = ROOT
    raw: Path = ROOT / "data" / "raw"
    report: Path = ROOT / "data" / "db" / "load_report.json"
    backend: str = "postgis"
    dsn: str = ""                                # normally empty: the DSN comes from env LOAD_DB_DSN
    db_options: dict = field(default_factory=dict)
    table_map: dict = field(default_factory=dict)   # logical name -> real table ("schema.table" ok)
    enabled: tuple[str, ...] = DEFAULT_DATASETS
    datasets: tuple[str, ...] | None = None      # CLI selection; None = enabled
    fields: Path | None = None                   # GeoJSON with the farmer's fields (-> field, field_crop_share)
    fields_source: str | None = None             # text for field.source (default: the file name)
    batch_size: int = 1_000_000
    mode: str = "resume"                         # resume | replace
    years: set[int] | None = None
    voiv: set[str] | None = None
    months: set[int] | None = None
    limit_files: int | None = None
    dry_run: bool = False
    validate_only: bool = False
    no_validate: bool = False

    @property
    def selected(self) -> list[str]:
        return list(self.datasets if self.datasets else self.enabled)

    @classmethod
    def from_toml(cls, path: Path | None, root: Path = ROOT) -> "Settings":
        s = cls(root=root)
        if path and Path(path).exists():
            with open(path, "rb") as fh:
                cfg = tomllib.load(fh)
            db, paths = cfg.get("database", {}), cfg.get("paths", {})
            ds, opt, inp = cfg.get("datasets", {}), cfg.get("options", {}), cfg.get("inputs", {})
            s.backend = db.get("backend", s.backend)
            s.dsn = str(db.get("dsn", s.dsn))
            s.db_options = dict(db.get("options", {}))
            s.table_map = {k: str(v) for k, v in cfg.get("tables", {}).items()}
            s.raw = _abs(root, paths.get("raw", s.raw))
            s.report = _abs(root, paths.get("report", s.report))
            if "enabled" in ds:
                s.enabled = tuple(ds["enabled"])
            s.batch_size = int(opt.get("batch_size", s.batch_size))
            if inp.get("fields"):
                s.fields = _abs(root, inp["fields"])
            s.fields_source = inp.get("fields_source", s.fields_source)
        return s

    def resolved_dsn(self) -> str:
        """Env LOAD_DB_DSN wins over the config/CLI value (keeps credentials out of files and history)."""
        import os
        return os.environ.get("LOAD_DB_DSN") or self.dsn
