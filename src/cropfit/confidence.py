"""Confidence of a soil-characteristics card, computed from the data behind it.

Every card lists factors: how many gene copies carry its statement, how deeply the sample was sequenced, how closely
the genes match known genomes, how large the reference is, how many days and cores lie behind a measurement, how far
a measurement sits from the threshold it is compared with, how many fungal or bacterial reads there are. Each factor
is high, medium or low by the cut-offs below, and the card takes the weakest one: the label always names what limits
it. Limits of the method itself (genes show capacity, not activity) are stated in the card text, not here, because
they do not change from sample to sample.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

Level = Literal["high", "medium", "low"]
ORDER = ["low", "medium", "high"]

# cut-offs (high, medium); below medium is low. Chosen from the ranges in the data, see AGENT.md 3.16
GENES = (100, 20)                  # gene copies behind the statement (its weakest step)
DEPTH = (300, 100)                 # genome equivalents: mean copies of 5 single-copy marker genes (deep samples 55-843)
IDENTITY = (75, 60)                # median % protein identity of the genes to their closest known genome
REFERENCE = (20, 8)                # other well-sequenced soils in the comparison
DAYS = (2, 7)                      # days between NEON measurement and DNA sample (at most: high, medium)
CORES = (3, 2)                     # soil cores (or incubation pairs) averaged by NEON
NITRATE_MARGIN = (0.3, 0.1)        # relative distance of nitrate from the nearest threshold
PH_MARGIN = (0.5, 0.2)             # pH units from the nearest band edge
OC_MARGIN = (0.3, 0.1)             # relative distance of organic carbon from the nearest band edge
FUNGAL_READS = (20_000, 5_000)     # ITS reads of the fungal sample (range 576-790k)
NAMED = (70, 40)                   # % of fungal reads with a genus name
BACTERIAL_READS = (5_000_000, 1_000_000)
CLASSIFIED = (50, 25)              # % of reads Kraken2 could classify


class Factor(BaseModel):
    level: Level
    text: str


def cut(value: float, cuts: tuple[float, float]) -> Level:
    return "high" if value >= cuts[0] else "medium" if value >= cuts[1] else "low"


def cut_below(value: float, cuts: tuple[float, float]) -> Level:
    """For quantities where smaller is better (days apart)."""
    return "high" if value <= cuts[0] else "medium" if value <= cuts[1] else "low"


def weakest(factors: list[Factor]) -> Level:
    return min((f.level for f in factors), key=ORDER.index) if factors else "low"


def genes(n: int, what: str = "gene copies behind it") -> Factor:
    if n == 1:
        what = what.replace("copies", "copy", 1)
    return Factor(level=cut(n, GENES), text=f"{n:,} {what}")


def depth(marker_mean: float) -> Factor:
    return Factor(level=cut(marker_mean, DEPTH),
                  text=f"Sequenced to about {marker_mean:.0f} bacterial genomes' worth of DNA")


def identity(pct: float) -> Factor:
    return Factor(level=cut(pct, IDENTITY),
                  text=f"'Who does it': genes match known genomes at about {pct:.0f}% identity")


def reference(n_ref: int, n_sites: int) -> Factor:
    level = cut(n_ref, REFERENCE)
    if n_sites < 2 and level == "high":
        level = "medium"
    return Factor(level=level, text=f"Compared with {n_ref} other well-sequenced soils from "
                                    f"{n_sites} site{'s' if n_sites != 1 else ''}")


def days(gap: int, what: str = "Measured") -> Factor:
    when = "on the day of the DNA sample" if gap == 0 else f"{gap} day{'s' if gap != 1 else ''} from the DNA sample"
    return Factor(level=cut_below(gap, DAYS), text=f"{what} {when}")


def cores(n: int, what: str = "soil cores") -> Factor:
    return Factor(level=cut(n, CORES), text=f"Average of {n} {what}")


def margin(value: float, edges: list[float], cuts: tuple[float, float], name: str, unit: str = "",
           relative: bool = True) -> Factor | None:
    """How far a measurement is from the nearest threshold: close to a line, a second test could land on the other side."""
    if not edges:
        return None
    edge = min(edges, key=lambda e: abs(value - e))
    d = abs(value - edge) / edge if relative else abs(value - edge)
    fmt = lambda v: f"{v:.3g}{unit}"  # noqa: E731
    return Factor(level=cut(d, cuts), text=f"{name} {fmt(value)} is {fmt(abs(value - edge))} from the {edge:g}{unit} line")


def fungal_reads(n: int) -> Factor:
    return Factor(level=cut(n, FUNGAL_READS), text=f"{n:,} fungal DNA reads")


def named(pct: float) -> Factor:
    return Factor(level=cut(pct, NAMED), text=f"{pct:.0f}% of fungal reads named to a genus")


def same_cores(same: bool) -> Factor:
    return Factor(level="high" if same else "medium",
                  text="Fungi from the same soil cores as the genes" if same else
                  "Fungi from the nearest NEON visit to the plot, not the same cores")


def bacterial_reads(n: int) -> Factor:
    return Factor(level=cut(n, BACTERIAL_READS), text=f"{n:,} bacterial DNA reads")


def classified(pct: float) -> Factor:
    return Factor(level=cut(pct, CLASSIFIED), text=f"{pct:.0f}% of DNA reads could be named")


def no_data() -> Factor:
    return Factor(level="low", text="No data for this card")
