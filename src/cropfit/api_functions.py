"""GUI API: the story one soil sample tells about its microbes. Treats the sample on its own, as if it were the
only one we had: no ranking against other plots or sites.

Three sources, all from the same soil:
  * bacteria and archaea: KEGG genes of the NMDC metagenome (rules/ko_panel.csv panel), read as which steps of
    known pathways (KEGG modules) this soil's microbes carry, and the balance between steps;
  * fungi: NEON ITS reads of the same soil cores (joined_fungi_genus; else the same plot within MATCH_DAYS),
    each genus given its ecological role from FUNGuild (fungal_guilds, scripts/16_fetch_funguild.py);
  * measurements NEON made in that soil at that visit (inorganic nitrogen, pH, carbon, nitrogen, moisture).

From these it writes *cards*: what is there, and what that can mean (possible upsides and risks), each with what
it rests on and how sure it is, most trustworthy first. Statements are of three kinds, none of which needs other
samples: measured values against textbook thresholds; presence of a pathway step (with the sequencing-depth
caveat); balances within the sample (e.g. genes that make N2O vs genes that remove it). Genes are capacity, not
activity; a genus's role is the typical role of that genus, not of every species in it.

Reads ko_panel, metagenomes (scripts/05), neon_inorganic_n, neon_chem, its_genus (scripts/02b),
joined_fungi_genus (scripts/06) and fungal_guilds (scripts/14).
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import api as core

MATCH_DAYS = 7          # a NEON measurement within this many days of the metagenome counts as the same visit
MIN_COUNT = 5           # fewer gene copies than this is a trace
MIN_RATIO_GENES = 20    # within-sample balances need at least this many gene copies in total
MIN_FUNGAL_READS = 5_000
# When a gene or fungal card is coloured "worth noticing" (rules on the sample alone, stated on the card):
N2O_FLAG_RATIO = 10     # N2O-making genes (norB) per N2O-removing gene (nosZ), or no remover at all
PATHOGEN_GENUS_FLAG = 15.0   # one genus that includes plant pathogens makes up this % of named fungal DNA

# function_group in rules/ko_panel.csv -> (title, what it does, theme); used for the gene list
GROUPS: dict[str, tuple[str, str, str]] = {
    "n_fixation": ("Nitrogen fixation", "Turn nitrogen gas from the air into ammonium.", "nitrogen"),
    "nitrification": ("Nitrification", "Turn ammonium into nitrate (genes shared with methane oxidisers).", "nitrogen"),
    "denitrification": ("Denitrification", "Turn nitrate into gas, partly the greenhouse gas N2O.", "nitrogen"),
    "nosZ": ("N2O reduction", "Turn N2O into harmless nitrogen gas.", "nitrogen"),
    "dnra": ("Nitrate to ammonium", "Turn nitrate back into ammonium, which stays in the soil.", "nitrogen"),
    "urease": ("Urea breakdown", "Release ammonium from urea (manure, urea fertiliser).", "nitrogen"),
    "p_mobilisation": ("Phosphorus release", "Free phosphorus from organic matter and minerals.", "phosphorus"),
    "acdS": ("Plant stress relief", "ACC deaminase lowers the stress hormone ethylene in roots.", "plant"),
    "chitinase": ("Chitin breakdown", "Digest chitin of fungal walls and insects.", "plant"),
    "phlD": ("Antifungal DAPG", "Make the antifungal compound DAPG.", "plant"),
    "hcnA": ("Hydrogen cyanide", "Make hydrogen cyanide.", "plant"),
    "copper_resistance": ("Copper resistance", "Pump out or neutralise copper.", "pressure"),
}

# Nitrogen pathways as KEGG modules, step by step; a step is carried out by any of its genes (names as in the panel).
PATHWAYS: list[tuple[str, str, list[tuple[str, list[str]]], str | None]] = [
    ("Denitrification", "M00529", [("nitrate → nitrite", ["narG/nxrA", "napA"]), ("nitrite → NO", ["nirK", "nirS"]),
                                   ("NO → N2O", ["norB"]), ("N2O → N2", ["nosZ"])],
     "nitrate → nitrite is shared with DNRA; nosZ here is clade I only"),
    ("Nitrate kept as ammonium (DNRA)", "M00530", [("nitrate → nitrite", ["narG/nxrA", "napA"]),
                                                   ("nitrite → ammonium", ["nrfA"])],
     "only nrfA is used for the second step: nirB also serves the cell's own nitrogen uptake"),
    ("Nitrification", "M00528", [("ammonia → hydroxylamine", ["pmoA-amoA"]), ("hydroxylamine → nitrite", ["hao"]),
                                 ("nitrite → nitrate", ["narH/nxrB"])],
     "amoA cannot be told from methane-oxidiser pmoA in this annotation; nxrB not from nitrate-reducing narH"),
    ("Nitrogen fixation", "M00175", [("N2 → ammonia", ["nifH", "nifD", "nifK"])],
     "rare genes, often missed by assembly; nodule rhizobia of legumes are not covered"),
    ("Urea breakdown", "—", [("urea → ammonium", ["ureC"])], None),
]

FUNGAL_ROLE = {  # FUNGuild category -> label
    "saprotroph": "Decomposers", "plant_pathogen": "Genera that include plant pathogens",
    "arbuscular_mycorrhizal": "Arbuscular mycorrhizal (crop root partners)",
    "other_mycorrhizal": "Other mycorrhizal (mostly tree partners)", "fungal_parasite": "Parasites of other fungi",
    "endophyte": "Endophytes (live inside plants)", "animal_or_lichen": "Animal or lichen associates",
    "other": "Other roles", "unknown": "Role unknown", "no_guild": "Genus not in FUNGuild",
}

# Late-spring / pre-sidedress soil nitrate test for corn (Magdoff et al. 1984; Iowa State, Blackmer et al.).
NITRATE_ENOUGH, NITRATE_LOW = 25.0, 10.0
CN_IMMOBILISE = 20.0    # C:N above this: microbes tend to lock up nitrogen while breaking residues down
# Textbook ranges for arable topsoils (general soil fertility, e.g. Brady & Weil, The Nature and Properties of Soils).
PH_BANDS = [(5.5, "strongly acidic", "risk", "phosphorus binds to iron and aluminium and aluminium can harm roots"),
            (6.0, "moderately acidic", "neutral", "phosphorus is starting to bind to iron and aluminium"),
            (7.0, "slightly acidic to neutral", "upside", "the range where phosphorus and most nutrients are most available"),
            (7.5, "neutral to slightly alkaline", "neutral", "phosphorus is starting to bind to calcium"),
            (99, "alkaline", "risk", "phosphorus binds to calcium and iron, zinc and manganese are harder for roots to take up")]
OC_BANDS = [(1.0, "low", "risk", "little organic matter to hold water and nutrients and to feed soil life"),
            (2.0, "moderate", "neutral", "an average store of organic matter for an arable soil"),
            (99, "high", "upside", "a good store of organic matter that holds water and nutrients")]


# ---------------------------------------------------------------- response models
class FunctionSample(BaseModel):
    sample_id: str                   # same ids as the soil microbes view (mg-...)
    date: dt.date
    year: int
    n_genes: int                     # genes assembled and annotated
    deep_enough: bool                # enough genes to read absences and balances at all


class GeneCount(BaseModel):
    gene: str
    ko: str
    count: int
    caveat: str | None


class FunctionGroup(BaseModel):
    group: str
    title: str
    meaning: str
    theme: str                       # nitrogen | phosphorus | plant | pressure
    status: str                      # found | trace | not_found | too_few_genes
    genes: list[GeneCount]


class PathwayStep(BaseModel):
    step: str
    genes: list[str]
    copies: int
    status: str                      # found | trace | not_found | too_few_genes


class Pathway(BaseModel):
    name: str
    kegg_module: str
    steps: list[PathwayStep]
    complete: bool                   # every step found
    note: str | None


class FungalRole(BaseModel):
    role: str
    label: str
    pct: float                       # share of fungal reads with a genus name
    top: list[str]                   # largest genera, "Fusarium 11.6%"


class Fungi(BaseModel):
    date: dt.date
    same_cores: bool                 # from exactly the cores of the metagenome (else same plot, nearest visit)
    reads: int | None
    named_pct: float                 # share of fungal reads that have a genus name
    roles: list[FungalRole]


class Measured(BaseModel):
    date: dt.date
    ammonium_n_mgkg: float | None
    nitrate_n_mgkg: float | None
    net_n_min_mgkg_d: float | None
    net_nitrif_mgkg_d: float | None
    ph_water: float | None
    organic_c_pct: float | None
    total_n_pct: float | None
    cn_ratio: float | None
    soil_moisture: float | None      # g water per g dry soil


class Implication(BaseModel):
    kind: str                        # upside | risk | neutral
    text: str


class DecisionCard(BaseModel):
    card: str                        # n_now | n_release | soil | nitrogen | fungi | p_release | copper | root_health
    title: str
    status: str                      # good | watch | act (measured threshold) | notice (sample rule) | info | unknown
    headline: str                    # one short line for the card face
    flag: str | None                 # why the card is coloured, when it is
    finding: str                     # what is there, one or two sentences
    implications: list[Implication]  # what that can mean: possible upsides and risks, no prescriptions
    basis: str                       # measured | genes | fungi
    confidence: str                  # high | medium | low
    evidence: list[str]              # the numbers and rules behind the finding


class FunctionProfile(BaseModel):
    sample_id: str
    plot_id: str
    date: dt.date
    n_genes: int
    deep_enough: bool
    cards: list[DecisionCard]
    pathways: list[Pathway]
    fungi: Fungi | None
    groups: list[FunctionGroup]
    measured: Measured | None
    notes: list[str]


# ---------------------------------------------------------------- data
def _has(name: str) -> bool:
    return (core.PROCESSED / f"{name}.parquet").exists()


def _sample_id(key: str) -> str:
    return "mg-" + key.replace("nmdc:", "")


def _metagenomes() -> pd.DataFrame:
    mg = core.table("metagenomes").copy()
    keys = set(core.table("ko_panel")["metagenome_key"])
    mg = mg[mg["metagenome_key"].isin(keys)].copy()
    mg["sample_id"] = mg["metagenome_key"].map(_sample_id)
    mg["date"] = pd.to_datetime(mg["date"]).dt.date
    mg["n_ko_genes"] = mg["n_ko_genes"].fillna(0).astype(int)
    mg["ko_depth_ok"] = mg["ko_depth_ok"].fillna(False).astype(bool)
    return mg.sort_values("date")


def _nearest(df: pd.DataFrame, plot_id: str, date: dt.date, date_col: str) -> pd.Series | None:
    d = df[df["plotID"] == plot_id].copy()
    if d.empty:
        return None
    d["_gap"] = (pd.to_datetime(d[date_col]) - pd.Timestamp(date)).abs().dt.days
    d = d[d["_gap"] <= MATCH_DAYS].sort_values("_gap")
    return None if d.empty else d.iloc[0]


def _measured(plot_id: str, date: dt.date) -> Measured | None:
    n = _nearest(core.table("neon_inorganic_n"), plot_id, date, "collectDate") if _has("neon_inorganic_n") else None
    c = _nearest(core.table("neon_chem"), plot_id, date, "collectDate") if _has("neon_chem") else None
    if n is None and c is None:
        return None
    num = lambda s, k: None if s is None or k not in s or pd.isna(s[k]) else round(float(s[k]), 3)  # noqa: E731
    when = pd.to_datetime((n if n is not None else c)["collectDate"]).date()
    return Measured(date=when, ammonium_n_mgkg=num(n, "ammonium_n_mgkg"), nitrate_n_mgkg=num(n, "nitrate_n_mgkg"),
                    net_n_min_mgkg_d=num(n, "net_n_min_mgkg_d"), net_nitrif_mgkg_d=num(n, "net_nitrif_mgkg_d"),
                    ph_water=num(c, "ph_water"), organic_c_pct=num(c, "organic_c_pct"),
                    total_n_pct=num(c, "total_n_pct"), cn_ratio=num(c, "cn_ratio"), soil_moisture=num(c, "soil_moisture"))


def _status(copies: int, deep: bool) -> str:
    return "found" if copies >= MIN_COUNT else "trace" if copies > 0 else "not_found" if deep else "too_few_genes"


def _pathways(copies: dict[str, int], deep: bool) -> list[Pathway]:
    out = []
    for name, module, steps, note in PATHWAYS:
        st = [PathwayStep(step=s, genes=g, copies=sum(copies.get(x, 0) for x in g),
                          status=_status(sum(copies.get(x, 0) for x in g), deep)) for s, g in steps]
        out.append(Pathway(name=name, kegg_module=module, steps=st, note=note,
                           complete=all(s.status == "found" for s in st)))
    return out


def _fungi(r) -> Fungi | None:
    """Fungal genera of the same soil cores (else nearest NEON visit to the plot), grouped by FUNGuild role."""
    same, g = False, None
    if _has("joined_fungi_genus"):
        j = core.table("joined_fungi_genus")
        j = j[j["metagenome_key"] == r.metagenome_key]
        if len(j):
            same, g, date = True, j[["genus", "rel_abund_pct"]], r.date
    if g is None and _has("its_genus"):
        its = core.table("its_genus")
        near = _nearest(its.drop_duplicates(["plotID", "collectDate"]), r.plotID, r.date, "collectDate")
        if near is None:
            return None
        g = its[(its["plotID"] == r.plotID) & (its["collectDate"] == near["collectDate"])][["genus", "rel_abund_pct"]]
        date = pd.to_datetime(near["collectDate"]).date()
    if g is None or g.empty:
        return None
    reads = None
    if _has("its_genus"):
        its = core.table("its_genus")
        hit = its[(its["plotID"] == r.plotID) & (pd.to_datetime(its["collectDate"]).dt.date == date)]
        reads = int(hit["total_reads"].iloc[0]) if len(hit) else None
    g = g[g["rel_abund_pct"] > 0]
    unnamed = g["genus"].str.startswith("unclassified") | g["genus"].str.contains("Incertae_sedis", regex=False)
    named = g[~unnamed].copy()                          # placeholders count as "no genus name", as in the microbes view
    total = float(named["rel_abund_pct"].sum())
    if total <= 0:
        return None
    guilds = core.table("fungal_guilds").set_index("genus") if _has("fungal_guilds") else pd.DataFrame()
    named["role"] = named["genus"].map(guilds["category"]) if len(guilds) else "no_guild"
    named["role"] = named["role"].fillna("no_guild")
    named["pct"] = 100 * named["rel_abund_pct"] / total
    roles = []
    for role, sub in named.groupby("role"):
        sub = sub.sort_values("pct", ascending=False)
        roles.append(FungalRole(role=role, label=FUNGAL_ROLE.get(role, role), pct=round(float(sub["pct"].sum()), 2),
                                top=[f"{x.genus} {x.pct:.1f}%" if x.pct >= 0.05 else f"{x.genus} <0.1%"
                                     for x in sub.head(4).itertuples()]))
    roles.sort(key=lambda x: -x.pct)
    return Fungi(date=date, same_cores=same, reads=reads, named_pct=round(total / float(g["rel_abund_pct"].sum()) * 100, 1),
                 roles=roles)


# ---------------------------------------------------------------- cards
def _p(v: float) -> str:
    """Share for text: '<1%' for small non-zero shares, so 'present' and '0%' never meet."""
    return "0%" if v <= 0 else "<1%" if v < 0.5 else f"{v:.0f}%"


def _band(value: float, bands: list) -> tuple[str, str, str]:
    return next((name, kind, text) for top, name, kind, text in bands if value < top)


def _cards(copies: dict[str, int], pathways: list[Pathway], fungi: Fungi | None, m: Measured | None,
           deep: bool, guilds: pd.DataFrame) -> list[DecisionCard]:
    U, R, N = "upside", "risk", "neutral"
    imp = lambda kind, text: Implication(kind=kind, text=text)  # noqa: E731
    c = lambda *genes: sum(copies.get(x, 0) for x in genes)  # noqa: E731
    P = {p.name: p for p in pathways}
    cards: list[DecisionCard] = []

    # ---- measured: nitrogen available now (soil nitrate test)
    if m and m.nitrate_n_mgkg is not None:
        no3 = m.nitrate_n_mgkg
        st = "good" if no3 >= NITRATE_ENOUGH else "watch" if no3 >= NITRATE_LOW else "act"
        cards.append(DecisionCard(
            card="n_now", title="Nitrogen available now", status=st,
            headline=f"{no3:.1f} mg/kg nitrate · {m.ammonium_n_mgkg or 0:.1f} mg/kg ammonium",
            flag=None if st == "good" else f"Below the {NITRATE_ENOUGH:.0f} mg/kg soil-test level for corn"
            + (f" (and below {NITRATE_LOW:.0f})" if st == "act" else ""),
            finding=f"Soil nitrate is {no3:.1f} mg N/kg (ammonium {m.ammonium_n_mgkg or 0:.1f}).",
            implications=[
                imp(U, "Above the 25 mg/kg level of the soil nitrate test: for corn, the soil alone usually covers "
                       "the rest of the season's nitrogen.") if st == "good" else
                imp(R, "Between 10 and 25 mg/kg: for corn, the soil alone is usually not enough for the rest of the "
                       "season.") if st == "watch" else
                imp(R, "Below 10 mg/kg: for corn, the soil supplies little of the nitrogen the crop still needs."),
                imp(R if no3 >= NITRATE_LOW else N, "Nitrate moves with water: heavy rain can wash part of it below the "
                                                    "roots." if no3 >= NITRATE_LOW else
                    "Little nitrate means little to wash out with heavy rain."),
            ],
            basis="measured", confidence="medium",
            evidence=[f"Nitrate {no3:.2f} and ammonium {m.ammonium_n_mgkg or 0:.2f} mg N/kg, {m.date}",
                      "Rule: late-spring soil nitrate test for corn (25 and 10 mg/kg; 0-30 cm, corn 15-30 cm tall). "
                      "NEON's timing and depth are close to, not exactly, that protocol, and the test is calibrated "
                      "for corn, not for other crops."]))
    else:
        cards.append(DecisionCard(card="n_now", title="Nitrogen available now", status="unknown",
                                  headline="Not measured at this visit", flag=None, finding="NEON did not measure soil nitrate within a week of this sample.",
                                  implications=[], basis="measured", confidence="low", evidence=[]))

    # ---- measured: nitrogen from organic matter (net mineralisation, C:N)
    if m and (m.net_n_min_mgkg_d is not None or m.cn_ratio is not None):
        nm, cn = m.net_n_min_mgkg_d, m.cn_ratio
        locking = (nm is not None and nm < 0) or (cn is not None and cn > CN_IMMOBILISE)
        parts = ([f"net mineralisation {nm:+.2f} mg N/kg/day"] if nm is not None else []) + (
            [f"C:N {cn:.1f}"] if cn is not None else [])
        cards.append(DecisionCard(
            card="n_release", title="Nitrogen from organic matter", status="watch" if locking else "good",
            headline="Microbes are locking nitrogen up" if locking else "Organic matter is releasing nitrogen",
            flag=("Negative net mineralisation" if nm is not None and nm < 0 else f"C:N above {CN_IMMOBILISE:.0f}")
            if locking else None,
            finding=("Microbes were taking nitrogen up rather than releasing it" if locking else
                     "Microbes were releasing nitrogen from organic matter") + f" ({', '.join(parts)}).",
            implications=[imp(R, "While microbes lock nitrogen up, little of the crop's nitrogen comes from the soil "
                                 "itself; the crop depends more on fertiliser or manure in that period.")
                          if locking else
                          imp(U, "Organic matter is turning into plant-available nitrogen: part of the crop's need is "
                                 "met by the soil itself."),
                          imp(N, "This is one incubation at one visit: it changes with season, moisture and fresh "
                                 "residues.")],
            basis="measured", confidence="medium",
            evidence=parts + ["Rule: negative net mineralisation, or C:N above 20, means nitrogen lock-up."]))

    # ---- measured: soil character against textbook ranges
    if m and (m.ph_water is not None or m.organic_c_pct is not None):
        facts, imps, risks, short = [], [], [], []
        if m.ph_water is not None:
            name, kind, text = _band(m.ph_water, PH_BANDS)
            facts.append(f"pH {m.ph_water:.1f} ({name})")
            short.append(f"pH {m.ph_water:.1f}")
            imps.append(imp(kind, f"pH {m.ph_water:.1f}: {text}."))
            if kind == "risk":
                risks.append(f"pH {m.ph_water:.1f} is {name}")
        if m.organic_c_pct is not None:
            name, kind, text = _band(m.organic_c_pct, OC_BANDS)
            facts.append(f"organic carbon {m.organic_c_pct:.2f}% ({name})")
            short.append(f"organic carbon {m.organic_c_pct:.2f}% ({name})")
            imps.append(imp(kind, f"Organic carbon {m.organic_c_pct:.2f}%: {text}."))
            if kind == "risk":
                risks.append(f"organic carbon is {name}")
        if m.cn_ratio is not None and m.cn_ratio <= CN_IMMOBILISE:
            imps.append(imp(N, f"C:N {m.cn_ratio:.1f} is usual for arable soil: residues break down without locking "
                               "much nitrogen up."))
        cards.append(DecisionCard(
            card="soil", title="Soil character", status="watch" if risks else "info", headline=" · ".join(short),
            flag=("; ".join(risks)[:1].upper() + "; ".join(risks)[1:]) if risks else None, finding="Measured: " + ", ".join(facts) + ".",
            implications=imps, basis="measured", confidence="medium",
            evidence=["Ranges for arable topsoils from general soil fertility texts (pH 6-7 most nutrients "
                      "available; organic carbon below 1% low, above 2% high). Approximate, not crop-specific."]))

    # ---- fungi (ITS, FUNGuild roles) - independent of metagenome depth
    if fungi:
        R_ = {x.role: x for x in fungi.roles}
        share = lambda role: R_[role].pct if role in R_ else 0.0  # noqa: E731
        top_role = fungi.roles[0]
        finding = (f"Of the fungal DNA with a genus name, {_p(share('saprotroph'))} is from decomposers, "
                   f"{_p(share('plant_pathogen'))} from genera that include plant pathogens, "
                   f"{_p(share('arbuscular_mycorrhizal') + share('other_mycorrhizal'))} from mycorrhizal fungi and "
                   f"{_p(share('fungal_parasite'))} from parasites of other fungi.")
        imps = []
        if "plant_pathogen" in R_:
            imps.append(imp(R, f"Genera that include crop pathogens are present ({', '.join(R_['plant_pathogen'].top[:3])}). "
                               "Disease also needs a susceptible crop and suitable weather, and these genera hold "
                               "harmless species too."))
        enemies = []
        if len(guilds):
            fp = guilds[guilds["can_parasitise_fungi"]].index
            for role in fungi.roles:
                enemies += [t for t in role.top if t.split(" ")[0] in fp]
        if enemies:
            imps.append(imp(U, f"Fungi that attack other fungi, some of them pathogens, are present ({', '.join(enemies[:3])})."))
        if share("arbuscular_mycorrhizal") > 0:
            imps.append(imp(U, f"Arbuscular mycorrhizal fungi are present ({_p(share('arbuscular_mycorrhizal'))} of fungal "
                               "DNA, an under-count with this method): they extend roots' reach for phosphorus and water."))
        else:
            imps.append(imp(N, "No arbuscular mycorrhizal fungi detected; the ITS method misses most of them, so this "
                               "says little."))
        if top_role.role == "saprotroph":
            imps.append(imp(U, "Decomposers dominate: crop residues and organic matter are being broken down, "
                               "releasing nutrients."))
        if share("other_mycorrhizal") >= 5:
            imps.append(imp(N, f"{share('other_mycorrhizal'):.0f}% of fungal DNA is from fungi that partner with trees: "
                               "unusual for a field, possibly from field edges or earlier land use."))
        flags = []
        if share("plant_pathogen") > share("saprotroph"):
            flags.append(f"Pathogen-including genera ({_p(share('plant_pathogen'))}) outweigh decomposers "
                         f"({_p(share('saprotroph'))})")
        if "plant_pathogen" in R_:
            name, pct = R_["plant_pathogen"].top[0].rsplit(" ", 1)
            value = float(pct.strip("<%"))
            if value >= PATHOGEN_GENUS_FLAG:
                flags.append(f"{name} alone is {value:.0f}% of fungal DNA")
        ev = [f"{x.label}: {x.pct:.1f}% ({', '.join(x.top)})" for x in fungi.roles[:6]]
        ev.append(f"Coloured when genera that include plant pathogens outweigh decomposers, or one of them makes up "
                  f"{PATHOGEN_GENUS_FLAG:.0f}% or more of the fungal DNA with a genus name.")
        ev.append(f"Roles from FUNGuild at genus level; {fungi.named_pct:.0f}% of fungal reads have a genus name"
                  + (f"; {fungi.reads:,} fungal reads" if fungi.reads else "") + ". "
                  + ("Same soil cores as the gene data." if fungi.same_cores else
                     f"From the NEON visit on {fungi.date}, not the exact cores of the gene data."))
        few = fungi.reads is not None and fungi.reads < MIN_FUNGAL_READS
        headline = (f"{_p(share('saprotroph'))} decomposers · {_p(share('plant_pathogen'))} pathogen-including genera"
                    f" · {_p(share('arbuscular_mycorrhizal') + share('other_mycorrhizal'))} mycorrhizal")
        cards.append(DecisionCard(card="fungi", title="Fungi in this soil", status="notice" if flags else "info",
                                  headline=headline, flag="; ".join(flags) or None, finding=finding,
                                  implications=imps, basis="fungi", confidence="low", evidence=ev
                                  + (["Few fungal reads: small shares may be noise."] if few else [])))

    if not deep:
        for card, title in [("nitrogen", "Nitrogen cycle microbes"), ("p_release", "Phosphorus release by microbes"),
                            ("root_health", "Root protection and stress relief")]:
            cards.append(DecisionCard(card=card, title=title, status="unknown", headline="Too few genes to tell",
                                      flag=None, finding="Too few genes were assembled from this sample to describe its microbes.",
                                      implications=[], basis="genes", confidence="low", evidence=[]))
        return cards

    # ---- genes: the nitrogen story, pathway by pathway
    den, dnra, nit, fix, urea = (P["Denitrification"], P["Nitrate kept as ammonium (DNRA)"], P["Nitrification"],
                                 P["Nitrogen fixation"], P["Urea breakdown"])
    has = lambda p, i: p.steps[i].status == "found"  # noqa: E731
    carried = []
    if den.complete:
        carried.append("the full denitrification pathway (nitrate to N2)")
    elif any(s.status == "found" for s in den.steps):
        carried.append("denitrification up to " + next(s.step.split(" → ")[1] for s in reversed(den.steps) if s.status == "found"))
    if has(dnra, 1):
        carried.append("nitrate-to-ammonium (DNRA)")
    if has(nit, 0):
        carried.append("ammonia (or methane) oxidation")
    if has(urea, 0):
        carried.append("urea breakdown")
    missing = [p.name.lower() for p in (fix,) if not any(s.status == "found" for s in p.steps)]
    finding = ("Microbes here carry " + ", ".join(carried) + "." if carried else "Few nitrogen-cycle genes found.") + (
        f" No {', '.join(missing)} genes found." if missing else "")
    imps, nflag = [], None
    makers, cleaners, keepers, gas = c("norB"), c("nosZ"), c("nrfA"), c("nirK", "nirS")
    if makers >= MIN_COUNT and cleaners == 0:
        nflag = "N2O-making genes but no N2O-removing gene found"
    elif cleaners and makers / cleaners >= N2O_FLAG_RATIO:
        nflag = f"{makers / cleaners:.0f}× more N2O-making than N2O-removing genes"
    short = (["full denitrification" if den.complete else "partial denitrification"]
             if any(s.status == "found" for s in den.steps) else []) + (
        ["nitrate kept as ammonium"] if has(dnra, 1) else []) + (["nitrification"] if has(nit, 0) else []) + (
        ["urea breakdown"] if has(urea, 0) else []) + (["no N fixation found"] if missing else [])
    if makers + cleaners >= MIN_RATIO_GENES:
        if cleaners:
            per = makers / cleaners
            imps.append(imp(R if per > 1 else U,
                            f"About {per:.0f} genes that make N2O for every gene that removes it: when the soil is wet "
                            "and holds nitrate, part of the nitrogen lost as gas can leave as N2O, a greenhouse gas."
                            if per > 1 else "N2O made here can largely be turned into harmless N2."))
        else:
            imps.append(imp(R, "Genes that make N2O but none that remove it: nitrogen lost as gas can leave as N2O."))
    if keepers:
        imps.append(imp(U, f"Some microbes can keep nitrate in the soil as ammonium instead (about 1 such gene per "
                           f"{gas / keepers:.0f} that start turning nitrate into gas)."))
    if has(nit, 0):
        imps.append(imp(N, "Ammonium from fertiliser or manure can be turned into nitrate, which crops use but water "
                           "can wash away (if these genes are from ammonia rather than methane oxidisers)."))
    if has(urea, 0) and m and m.ph_water is not None and m.ph_water >= 7.0:
        imps.append(imp(R, f"Urea is quickly turned into ammonium; at pH {m.ph_water:.1f}, urea left on the surface can "
                           "lose part of its nitrogen to the air as ammonia."))
    if m and m.nitrate_n_mgkg is not None and m.nitrate_n_mgkg >= NITRATE_LOW and makers:
        imps.append(imp(N, f"At this visit the soil held {m.nitrate_n_mgkg:.1f} mg/kg nitrate: the raw material for "
                           "denitrification is there; whether it runs depends on how wet the soil gets."))
    if missing:
        imps.append(imp(N, "Nitrogen-fixation genes are rare and easily missed; legume nodule bacteria are not "
                           "covered either, so this does not mean no fixation."))
    cards.append(DecisionCard(
        card="nitrogen", title="Nitrogen cycle microbes", status="notice" if nflag else "info",
        headline=(" · ".join(short)[:1].upper() + " · ".join(short)[1:]) or "Few nitrogen-cycle genes", flag=nflag,
        finding=finding,
        implications=imps,
        basis="genes", confidence="low",
        evidence=[f"{p.name} (KEGG {p.kegg_module}): " + ", ".join(f"{s.step} {s.copies}" for s in p.steps)
                  for p in pathways]
                 + ["Gene copies found in this sample; capacity, not activity.",
                    f"Coloured when N2O-making genes (norB) are found with no N2O-removing gene (nosZ), or outnumber "
                    f"them {N2O_FLAG_RATIO}:1 or more."]))

    # ---- genes: phosphorus from organic matter vs minerals
    org, mineral = c("phoD", "phoA", "appA"), c("gcd", "pqqC")
    if org + mineral >= MIN_RATIO_GENES:
        share = 100 * org / (org + mineral)
        imps = [imp(N, f"About {share:.0f}% of the phosphorus-freeing genes target organic phosphorus (phosphatases, "
                       f"phytase) and {100 - share:.0f}% phosphorus bound in minerals (acids that dissolve it).")]
        if m and m.organic_c_pct is not None:
            name, _, _ = _band(m.organic_c_pct, OC_BANDS)
            imps.append(imp(R if name == "low" else U if name == "high" else N,
                            f"Organic phosphorus release draws on organic matter, which is {name} here "
                            f"({m.organic_c_pct:.2f}% organic carbon)."))
        if m and m.ph_water is not None and m.ph_water >= 7.5:
            imps.append(imp(U, "In alkaline soil phosphorus binds to calcium; microbes that dissolve mineral phosphate "
                               "are the ones that can free it."))
        imps.append(imp(N, "NEON does not measure plant-available phosphorus in these samples, so only a soil P test "
                           "can say whether there is enough."))
        cards.append(DecisionCard(
            card="p_release", title="Phosphorus release by microbes", status="info", flag=None,
            headline="Frees P from organic matter and minerals" + (", about equally" if 40 <= share <= 60 else
                     f", mostly from {'organic matter' if share > 60 else 'minerals'}"),
            finding="Microbes here can free phosphorus from organic matter and from minerals, "
                    + ("about equally." if 40 <= share <= 60 else
                       f"mostly from {'organic matter' if share > 60 else 'minerals'}."),
            implications=imps, basis="genes", confidence="low",
            evidence=[f"Organic-P genes (phoD, phoA, appA) {org}, mineral-P genes (gcd, pqqC) {mineral} copies"]))

    # ---- genes: copper resistance (presence of mobile resistance genes)
    plasmid, pumps = c("pcoB/copB", "pcoC/copC", "pcoD/copD"), c("cusA", "cusB", "cusC", "cusF")
    if plasmid + pumps >= MIN_COUNT:
        cards.append(DecisionCard(
            card="copper", title="Copper resistance", status="info", flag=None,
            headline=f"{plasmid + pumps} copper-resistance gene copies",
            finding=f"Copper-resistance genes found: {plasmid} copies of pco/cop genes (often carried on plasmids) and "
                    f"{pumps} of the cus copper pump.",
            implications=[imp(N, "Resistance genes on plasmids can pass between bacteria and spread where copper builds "
                                 "up (copper fungicides, some manures); they also occur in soils without extra copper."),
                          imp(N, "NEON does not measure soil copper here, so a soil test is the way to check it.")],
            basis="genes", confidence="low",
            evidence=["Only resistance genes (pco, cus) are counted, not the copper handling every bacterium has."]))

    # ---- genes: root protection and stress relief (presence)
    protect = [n for n, g in (("DAPG", "phlD"), ("hydrogen cyanide", "hcnA")) if c(g) > 0]
    imps = [imp(U, f"Genes for disease-suppressing compounds found: {', '.join(protect)}.") if protect else
            imp(R, "No genes for DAPG or hydrogen cyanide were found: no sign of the Pseudomonas groups that make some "
                   "soils suppress root diseases such as take-all.")]
    if c("acdS") >= MIN_COUNT:
        imps.append(imp(U, "Microbes with ACC deaminase are present: they can ease plant stress from drought, heat or "
                           "salt by lowering the stress hormone ethylene in roots."))
    if c("chiA") >= MIN_COUNT:
        imps.append(imp(N, "Chitin-digesting microbes are present; chitinases can attack fungal walls but are common "
                           "and not a sign of disease control on their own."))
    cards.append(DecisionCard(
        card="root_health", title="Root protection and stress relief", status="info", flag=None,
        headline=("Disease-suppressing genes found" if protect else "No disease-suppressing genes")
        + (" · stress-relief genes present" if c("acdS") >= MIN_COUNT else ""),
        finding="Disease-suppressing genes " + ("found" if protect else "not found") + "; stress-relief genes "
                + ("present." if c("acdS") >= MIN_COUNT else "not found."),
        implications=imps, basis="genes", confidence="low",
        evidence=[f"phlD {c('phlD')}, hcnA {c('hcnA')}, acdS {c('acdS')}, chiA {c('chiA')} copies",
                  "Not found means not found at this sequencing depth, not absent."]))
    return cards


CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def _rank(cards: list[DecisionCard]) -> list[DecisionCard]:
    """One list, most trustworthy first: by confidence, cards without data last; rule order within a rank."""
    return sorted(cards, key=lambda c: (c.status == "unknown", CONF_RANK.get(c.confidence, 3)))


# ---------------------------------------------------------------- routes
router = APIRouter(prefix="/api")


@router.get("/plots/{plot_id}/functions", response_model=list[FunctionSample])
def plot_functions(plot_id: str):
    """Metagenomes of the plot that have a gene panel, oldest first."""
    core.plot_rows("plot_geometry", plot_id)            # 404 for an unknown plot
    mg = _metagenomes()
    mg = mg[mg["plotID"] == plot_id]
    return [FunctionSample(sample_id=r.sample_id, date=r.date, year=r.date.year, n_genes=r.n_ko_genes,
                           deep_enough=r.ko_depth_ok) for r in mg.itertuples()]


@router.get("/functions/{sample_id}", response_model=FunctionProfile)
def function_profile(sample_id: str):
    mg = _metagenomes()
    hit = mg[mg["sample_id"] == sample_id]              # looked up in the tables, never parsed into a path
    if hit.empty:
        raise HTTPException(404, f"unknown metagenome sample {sample_id}")
    r = next(hit.itertuples())
    deep = bool(r.ko_depth_ok)
    panel = core.table("ko_panel")
    mine = panel[panel["metagenome_key"] == r.metagenome_key]
    copies = mine.groupby("gene")["count"].sum().astype(int).to_dict()

    rules = core.ROOT / "rules" / "ko_panel.csv"
    caveats = {}
    if rules.exists():
        k = pd.read_csv(rules)
        caveats = {g: (c if isinstance(c, str) else None) for g, c in zip(k["gene"], k["caveat"])}
    groups = []
    for g, (title, meaning, theme) in GROUPS.items():
        genes = mine[mine["function_group"] == g]
        groups.append(FunctionGroup(group=g, title=title, meaning=meaning, theme=theme,
                                    status=_status(int(genes["count"].sum()), deep),
                                    genes=[GeneCount(gene=x.gene, ko=x.ko, count=int(x.count),
                                                     caveat=caveats.get(x.gene)) for x in genes.itertuples()]))

    pathways = _pathways(copies, deep)
    fungi = _fungi(r)
    guilds = core.table("fungal_guilds").set_index("genus") if _has("fungal_guilds") else pd.DataFrame()
    measured = _measured(r.plotID, r.date)
    notes = [f"This sample on its own: {r.n_ko_genes:,} genes were assembled from its DNA. Genes show what the "
             "microbes are equipped to do, not how active they are."]
    if not deep:
        notes.insert(0, "Too few genes were assembled from this sample to say which functions are missing: most "
                        "genes are never found at this depth.")
    notes.append(f"Fewer than {MIN_COUNT} gene copies count as a trace. Not found means not found at this depth, "
                 "never absent.")
    if fungi is None:
        notes.append("No NEON fungal (ITS) data for this soil within a week of the sample.")
    elif not _has("fungal_guilds"):
        notes.append("Fungal roles need FUNGuild: run scripts/16_fetch_funguild.py.")
    return FunctionProfile(sample_id=r.sample_id, plot_id=r.plotID, date=r.date, n_genes=r.n_ko_genes,
                           deep_enough=deep, cards=_rank(_cards(copies, pathways, fungi, measured, deep, guilds)),
                           pathways=pathways, fungi=fungi, groups=groups, measured=measured, notes=notes)
