"""File discovery and path parsing for data/raw."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .names import voiv_slug


@dataclass
class SourceFile:
    """One loadable unit: usually one file, sometimes a folder of files or a virtual unit."""
    path: Path
    year: int | None = None
    voivodeship: str | None = None
    paths: tuple[Path, ...] = ()                  # multi-file units (cropland year, external views)
    extra: dict = field(default_factory=dict)
    sig_override: tuple[int, int] | None = None   # virtual units (derived tables)

    def files(self) -> tuple[Path, ...]:
        return self.paths or (self.path,)

    def signature(self) -> tuple[int, int]:
        if self.sig_override is not None:
            return self.sig_override
        stats = [p.stat() for p in self.files() if p.exists()]
        return (sum(s.st_size for s in stats), max((s.st_mtime_ns for s in stats), default=0))

    def key(self, raw: Path) -> str:
        try:
            return self.path.relative_to(raw).as_posix()
        except ValueError:
            return self.path.as_posix()


def parse_hive(path: Path) -> dict:
    out: dict = {}
    for part in path.parts:
        if part.startswith("year=") and part[5:].isdigit():
            out["year"] = int(part[5:])
        elif part.startswith("voivodeship="):
            out["voivodeship"] = voiv_slug(part.split("=", 1)[1])
    return out


_NAME_YEAR_VOIV = re.compile(r"_(\d{4})_(.+?)(?:_part\d+)?$")


def parse_parquet_path(path: Path) -> tuple[int | None, str | None]:
    """(year, voivodeship slug) from Hive folders, falling back to the file name, then the parent folder."""
    info = parse_hive(path)
    year, voiv = info.get("year"), info.get("voivodeship")
    m = _NAME_YEAR_VOIV.search(path.stem)
    if m:
        year = year or int(m.group(1))
        voiv = voiv or voiv_slug(m.group(2))
    if voiv is None and (m2 := re.match(r"(.+?)_isric", path.stem)):
        voiv = voiv_slug(m2.group(1))
    if year is None and path.parent.name.isdigit():
        year = int(path.parent.name)
    return year, voiv


def discover_parquet(root: Path) -> list[SourceFile]:
    if not root.exists():
        return []
    units = []
    for p in sorted(root.rglob("*.parquet")):
        year, voiv = parse_parquet_path(p)
        units.append(SourceFile(p, year=year, voivodeship=voiv))
    return units


def apply_filters(units: list[SourceFile], years: set[int] | None, voiv: set[str] | None) -> list[SourceFile]:
    out = []
    for u in units:
        if years and u.year is not None and u.year not in years:
            continue
        if voiv and u.voivodeship is not None and u.voivodeship not in voiv:
            continue
        out.append(u)
    return out
