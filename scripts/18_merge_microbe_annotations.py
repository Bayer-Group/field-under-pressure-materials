"""Merge the LLM annotation chunks into the knowledge base files, then report coverage and blind agreement.

Reads data/annotation_chunks/c*_roles.csv and c*_desc.csv (written by the annotators, see
rules/microbe_annotation_prompt.md) and data/processed/microbe_taxa.csv. Validates them and fails loudly, listing every
problem, before writing anything. Trivial fixes (whitespace trimming, dropping exact duplicate rows) are applied and
reported. Writes rules/microbe_annotations.csv (LLM role rows) and rules/microbe_genera.csv (one description per genus).

Then prints a coverage report by summary class (docs/microbe_roles.md section 2, counted rows only, no fungal curated
override), the doubtful/unknown genera with most reads, and a blind agreement test of the LLM rows against FUNGuild
(data/processed/fungal_guilds.parquet). The full comparison goes to data/processed/microbe_roles_agreement.csv.

Run from the repo root: .venv/bin/python scripts/18_merge_microbe_annotations.py
"""
import csv
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import pandas as pd  # noqa: E402

from cropfit.config import PROCESSED  # noqa: E402

CHUNKS = ROOT / "data" / "annotation_chunks"
ONTO_PATH = ROOT / "rules" / "microbe_ontology.csv"
TAXA_PATH = PROCESSED / "microbe_taxa.csv"
GUILDS_PATH = PROCESSED / "fungal_guilds.parquet"
OUT_ANN = ROOT / "rules" / "microbe_annotations.csv"
OUT_GEN = ROOT / "rules" / "microbe_genera.csv"
OUT_AGREE = PROCESSED / "microbe_roles_agreement.csv"

ROLE_COLS = ["domain", "genus", "term_id", "confidence", "evidence", "source", "species_examples", "note"]
DESC_COLS = ["domain", "genus", "description"]
DOMAINS = {"Bacteria", "Archaea", "Fungi"}
CONFIDENCE = {"high", "medium", "low"}
EVIDENCE = {"well_known_genus", "some_species", "inferred"}
SOURCE_RE = re.compile(r"^llm:[^\s;+]+(\+reviewed)?$")
BINOMIAL_RE = re.compile(r"^(Candidatus )?[A-Z][a-z]+ [a-z][a-z-]+$")
HARMFUL_TERMS_NEED_SPECIES = {"plant_pathogen", "root_soilborne_pathogen", "foliar_pathogen",
                              "mycotoxin_producer", "animal_human_pathogen"}
PLANT_PATHOGEN_SUBTREE = {"plant_pathogen", "root_soilborne_pathogen", "foliar_pathogen"}
DESC_MAX_CHARS = 220
DESC_MAX_SENTENCES = 2
NOTE_MAX_CHARS = 120
GROUPS = {"Bacteria": "Bacteria+Archaea", "Archaea": "Bacteria+Archaea", "Fungi": "Fungi"}

problems: list[str] = []
warnings: list[str] = []
fixed: Counter = Counter()


# ---------------------------------------------------------------- ontology and taxa
onto = pd.read_csv(ONTO_PATH, dtype=str, keep_default_na=False)
ORDER = {t: i for i, t in enumerate(onto.term_id)}
PARENT = dict(zip(onto.term_id, onto.parent_id))
POLARITY = dict(zip(onto.term_id, onto.polarity))
ROOTS_OK = {"unknown"}


def ancestors(term: str) -> set[str]:
    out = set()
    t = term
    while PARENT.get(t):
        t = PARENT[t]
        out.add(t)
    return out


def under(term: str, ancestor: str) -> bool:
    return term == ancestor or ancestor in ancestors(term)


taxa = pd.read_csv(TAXA_PATH, dtype=str, keep_default_na=False)
for c in ("domain", "genus", "reads"):
    taxa[c] = taxa[c].str.strip()
taxa["reads"] = taxa["reads"].astype("int64")
TAXA_KEYS = set(zip(taxa.domain, taxa.genus))
if len(TAXA_KEYS) != len(taxa):
    problems.append("microbe_taxa.csv: duplicate (domain, genus) rows")
READS = {(d, g): r for d, g, r in zip(taxa.domain, taxa.genus, taxa.reads)}


# ---------------------------------------------------------------- read chunks
def read_chunks(pattern: str, cols: list[str]) -> list[dict]:
    recs = []
    files = sorted(CHUNKS.glob(pattern))
    if not files:
        problems.append(f"no files match {pattern} in {CHUNKS}")
    for f in files:
        with open(f, newline="", encoding="utf-8") as fh:
            rd = csv.reader(fh)
            header = next(rd, None)
            if header != cols:
                problems.append(f"{f.name}: header {header} != expected {cols}")
                continue
            for i, row in enumerate(rd, start=2):
                if not any(c.strip() for c in row):
                    continue
                if len(row) != len(cols):
                    problems.append(f"{f.name}:{i}: {len(row)} fields, expected {len(cols)}")
                    continue
                rec = {}
                for c, v in zip(cols, row):
                    s = v.strip()
                    if s != v:
                        fixed["whitespace trimmed in cells"] += 1
                    rec[c] = s
                rec["_where"] = f"{f.name}:{i}"
                recs.append(rec)
    return recs


def dedupe(recs: list[dict], key: tuple, cols: list[str], what: str) -> dict:
    """Drop exact duplicate rows; report differing duplicates as problems. Returns key -> record."""
    out: dict = {}
    for r in recs:
        k = tuple(r[c] for c in key)
        if k not in out:
            out[k] = r
            continue
        if all(out[k][c] == r[c] for c in cols):
            fixed[f"exact duplicate {what} rows dropped"] += 1
        else:
            problems.append(f"{what}: duplicate key {k} with different content ({out[k]['_where']} vs {r['_where']})")
    return out


roles_raw = read_chunks("c*_roles.csv", ROLE_COLS)
desc_raw = read_chunks("c*_desc.csv", DESC_COLS)

# Review files (review_*_roles.csv / review_*_desc.csv, same columns) replace the chunk rows of every genus they
# name: all of its role rows, or its description. Reviewed role rows carry source llm:<model>+reviewed.
review_roles = read_chunks("review_*_roles.csv", ROLE_COLS) if any(CHUNKS.glob("review_*_roles.csv")) else []
review_desc = read_chunks("review_*_desc.csv", DESC_COLS) if any(CHUNKS.glob("review_*_desc.csv")) else []
_reviewed = {(r["domain"], r["genus"]) for r in review_roles}
_redesc = {(r["domain"], r["genus"]) for r in review_desc}
roles_raw = [r for r in roles_raw if (r["domain"], r["genus"]) not in _reviewed] + review_roles
desc_raw = [r for r in desc_raw if (r["domain"], r["genus"]) not in _redesc] + review_desc
print(f"Review overrides: {len(_reviewed)} genera re-annotated, {len(_redesc)} descriptions replaced")

# exact duplicate roles rows are fixed; the same (domain, genus, term_id) with other content is a problem
roles_by_key: dict = defaultdict(list)
seen_full = set()
for r in roles_raw:
    full = tuple(r[c] for c in ROLE_COLS)
    if full in seen_full:
        fixed["exact duplicate roles rows dropped"] += 1
        continue
    seen_full.add(full)
    roles_by_key[(r["domain"], r["genus"], r["term_id"])].append(r)
roles = []
for k, rs in roles_by_key.items():
    if len(rs) > 1:
        problems.append(f"roles: duplicate (domain, genus, term_id) {k} with different content "
                        f"({', '.join(x['_where'] for x in rs)})")
    roles.append(rs[0])

descs = dedupe(desc_raw, ("domain", "genus"), DESC_COLS, "desc")


# ---------------------------------------------------------------- validate roles rows
for r in roles:
    where = f"{r['_where']} {r['domain']}/{r['genus']}"
    if r["domain"] not in DOMAINS:
        problems.append(f"{where}: domain {r['domain']!r} not in {sorted(DOMAINS)}")
    if (r["domain"], r["genus"]) not in TAXA_KEYS:
        problems.append(f"{where}: genus not in microbe_taxa.csv")
    if r["term_id"] not in ORDER:
        problems.append(f"{where}: term_id {r['term_id']!r} not in microbe_ontology.csv")
    elif PARENT[r["term_id"]] == "" and r["term_id"] not in ROOTS_OK:
        problems.append(f"{where}: root term {r['term_id']!r} may not be used directly")
    if r["confidence"] not in CONFIDENCE:
        problems.append(f"{where}: confidence {r['confidence']!r} not high|medium|low")
    if r["evidence"] not in EVIDENCE:
        problems.append(f"{where}: evidence {r['evidence']!r} not well_known_genus|some_species|inferred")
    if not SOURCE_RE.match(r["source"]):
        problems.append(f"{where}: source {r['source']!r} is not llm:<model id>[+reviewed]")
    species = [s.strip() for s in r["species_examples"].split(";") if s.strip()]
    if len(species) > 3:
        problems.append(f"{where}: {len(species)} species_examples (max 3)")
    for s in species:
        if not BINOMIAL_RE.match(s):
            problems.append(f"{where}: species example {s!r} is not a binomial")
    if r["evidence"] == "some_species" and not species:
        problems.append(f"{where}: some_species without species_examples")
    if r["evidence"] == "inferred" and r["confidence"] == "high":
        problems.append(f"{where}: inferred row marked high")
    if r["term_id"] in HARMFUL_TERMS_NEED_SPECIES or any(
            under(r["term_id"], t) for t in ("plant_pathogen", "mycotoxin_producer", "animal_human_pathogen")):
        if r["confidence"] in {"high", "medium"} and r["evidence"] == "inferred":
            problems.append(f"{where}: harmful row at medium/high must be well_known_genus or some_species")
    if len(r["note"]) > NOTE_MAX_CHARS:
        warnings.append(f"{where}: note {len(r['note'])} chars (max {NOTE_MAX_CHARS})")

by_genus: dict = defaultdict(list)
for r in roles:
    by_genus[(r["domain"], r["genus"])].append(r)
for (d, g), rs in by_genus.items():
    terms = {r["term_id"] for r in rs}
    if len(rs) > 4:
        problems.append(f"{d}/{g}: {len(rs)} rows (max 4)")
    if terms & {"unknown", "doubtful_assignment"} and len(terms) > 1:
        problems.append(f"{d}/{g}: unknown/doubtful_assignment must stand alone, has {sorted(terms)}")
    for t in terms:
        if ancestors(t) & terms:
            problems.append(f"{d}/{g}: {t} together with its ancestor {sorted(ancestors(t) & terms)}")


# ---------------------------------------------------------------- validate coverage and descriptions
role_keys = set(by_genus)
desc_keys = set(descs)
for k in sorted(TAXA_KEYS - role_keys):
    problems.append(f"no roles row for {k[0]}/{k[1]}")
for k in sorted(TAXA_KEYS - desc_keys):
    problems.append(f"no desc row for {k[0]}/{k[1]}")
for k in sorted(role_keys - TAXA_KEYS):
    problems.append(f"roles row for genus not in microbe_taxa: {k[0]}/{k[1]}")
for k in sorted(desc_keys - TAXA_KEYS):
    problems.append(f"desc row for genus not in microbe_taxa: {k[0]}/{k[1]}")

ABBREV = re.compile(r"\b(e\.g|i\.e|etc|spp|sp|incl|cf|vs)\.|\b[A-Z]\.")
long_desc, many_sent = [], []
for k, r in sorted(descs.items()):
    s = r["description"]
    if not s:
        problems.append(f"{r['_where']} {k[0]}/{k[1]}: empty description")
        continue
    if "\n" in s or "\r" in s:
        problems.append(f"{r['_where']} {k[0]}/{k[1]}: line break in description")
    if len(s) > DESC_MAX_CHARS:
        long_desc.append(f"{k[0]}/{k[1]} ({len(s)} chars)")
    if len(re.findall(r"[.!?](?=\s+[A-Z(]|\s*$)", ABBREV.sub("X", s))) > DESC_MAX_SENTENCES:
        many_sent.append(f"{k[0]}/{k[1]}")
    if s.startswith(k[1] + " "):
        warnings.append(f"{k[0]}/{k[1]}: description starts with the genus name")

sources = sorted({r["source"] for r in roles})
print(f"Chunks read: {len(roles)} role rows, {len(descs)} description rows, {len(TAXA_KEYS)} genera in microbe_taxa.csv")
print(f"Sources seen: {sources}")
print("Fixed automatically:")
for msg, n in fixed.items():
    print(f"  {n} x {msg}")
if not fixed:
    print("  (nothing)")
print(f"Warnings ({len(warnings)}):")
for w in warnings[:60]:
    print("  " + w)
if len(warnings) > 60:
    print(f"  ... {len(warnings) - 60} more")
print(f"Descriptions over {DESC_MAX_CHARS} chars ({len(long_desc)}): " + ("; ".join(long_desc) or "none"))
print(f"Descriptions over {DESC_MAX_SENTENCES} sentences ({len(many_sent)}): " + ("; ".join(many_sent) or "none"))

if problems:
    print(f"\nVALIDATION FAILED: {len(problems)} problem(s). Nothing written.")
    for p in problems:
        print("  - " + p)
    sys.exit(1)
print("\nValidation OK.")


# ---------------------------------------------------------------- write outputs
roles.sort(key=lambda r: (r["domain"], r["genus"], ORDER[r["term_id"]]))
with open(OUT_ANN, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(ROLE_COLS)
    for r in roles:
        w.writerow([r[c] for c in ROLE_COLS])

gen_rows = sorted(((k[0], k[1], r["description"]) for k, r in descs.items()))
with open(OUT_GEN, "w", newline="", encoding="utf-8") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(DESC_COLS)
    w.writerows(gen_rows)
print(f"Wrote {OUT_ANN.relative_to(ROOT)} ({len(roles)} rows) and {OUT_GEN.relative_to(ROOT)} ({len(gen_rows)} genera)")


# ---------------------------------------------------------------- summary classes
def counted_terms(d: str, g: str) -> list[str]:
    return [r["term_id"] for r in by_genus.get((d, g), []) if r["confidence"] in {"high", "medium"}]


def summary_class(terms: list[str]) -> str:
    P = {POLARITY[t] for t in terms}
    if "useful" in P and "harmful" in P:
        return "mixed"
    if "harmful" in P:
        return "harmful"
    if "useful" in P:
        return "useful"
    if "context" in P:
        return "context"
    if "background" in P:
        return "background"
    return "unknown"


CLASS_ORDER = ["useful", "mixed", "harmful", "context", "background", "unknown"]
CLASS_LABEL = {"useful": "Useful", "mixed": "Mixed", "harmful": "Potentially harmful", "context": "Nitrogen cyclers",
               "background": "Neutral / background", "unknown": "Role unknown"}

gen_class = {}
for d, g in TAXA_KEYS:
    terms = counted_terms(d, g)
    gen_class[(d, g)] = (summary_class(terms), terms)

print("\n=== Coverage: share of reads by summary class (counted rows only, LLM only) ===")
for group in ["Bacteria+Archaea", "Fungi"]:
    keys = [k for k in TAXA_KEYS if GROUPS[k[0]] == group]
    total = sum(READS[k] for k in keys)
    cls_reads: Counter = Counter()
    cls_n: Counter = Counter()
    for k in keys:
        c = gen_class[k][0]
        cls_reads[c] += READS[k]
        cls_n[c] += 1
    print(f"\n{group}: {len(keys)} genera, {total:,} reads")
    for c in CLASS_ORDER:
        print(f"  {CLASS_LABEL[c]:<22} {100 * cls_reads[c] / total:6.2f}% of reads  {cls_n[c]:5d} genera")

    dk = [k for k in keys if "doubtful_assignment" in gen_class[k][1]]
    dreads = sum(READS[k] for k in dk)
    print(f"  doubtful_assignment (counted): {100 * dreads / total:.3f}% of reads, {len(dk)} genera")

print("\n=== 20 most abundant genera that are doubtful_assignment or unknown ===")
flag = []
for k in TAXA_KEYS:
    c, terms = gen_class[k]
    if "doubtful_assignment" in terms or c == "unknown":
        status = "doubtful_assignment" if "doubtful_assignment" in terms else "unknown"
        all_terms = ", ".join(f"{r['term_id']}({r['confidence']})" for r in by_genus.get(k, []))
        flag.append((READS[k], k[0], k[1], status, all_terms or "no rows"))
flag.sort(reverse=True)
print(f"  {'rank':>4} {'domain':<9} {'genus':<32} {'reads':>12}  status / rows")
for i, (rd, d, g, status, terms) in enumerate(flag[:20], 1):
    print(f"  {i:>4} {d:<9} {g:<32} {rd:>12,}  {status}: {terms}")


# ---------------------------------------------------------------- blind agreement on fungi
def kappa(pairs: list[tuple[bool, bool]], weights: list[float]) -> float:
    """Cohen's kappa for binary labels, optionally weighted."""
    n = sum(weights)
    if n == 0:
        return float("nan")
    a = sum(w for (x, y), w in zip(pairs, weights) if x and y)
    d = sum(w for (x, y), w in zip(pairs, weights) if not x and not y)
    b = sum(w for (x, y), w in zip(pairs, weights) if x and not y)
    c = sum(w for (x, y), w in zip(pairs, weights) if not x and y)
    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    return float("nan") if pe == 1 else (po - pe) / (1 - pe)


guilds = pd.read_parquet(GUILDS_PATH)
guilds["genus"] = guilds["genus"].astype(str).str.strip()
guilds = guilds.drop_duplicates("genus").set_index("genus")
llm_fungi = {g for (d, g) in by_genus if d == "Fungi"}
common = sorted(llm_fungi & set(guilds.index))
print(f"\n=== Blind agreement on fungi (LLM vs FUNGuild): {len(common)} genera in both "
      f"({len(llm_fungi)} LLM fungal genera, {len(guilds)} FUNGuild genera) ===")

rows = []
for g in common:
    reads = READS.get(("Fungi", g), 0)
    gl = guilds.loc[g]
    terms = counted_terms("Fungi", g)
    rows.append({
        "genus": g,
        "reads": reads,
        "fungal_category": gl["category"],
        "fungal_can_be_plant_pathogen": bool(gl["can_be_plant_pathogen"]),
        "llm_counted_terms": ";".join(sorted(set(terms))),
        "llm_plant_pathogen": any(under(t, "plant_pathogen") for t in terms),
        "llm_decomposer": "decomposer" in terms,
        "llm_mycorrhizal": "mycorrhizal_partner" in terms,
        "fungal_saprotroph": gl["category"] == "saprotroph",
        "fungal_arbuscular": gl["category"] == "arbuscular_mycorrhizal",
    })
cmp = pd.DataFrame(rows)
tests = [
    ("(a) plant pathogen", "fungal_can_be_plant_pathogen", "llm_plant_pathogen"),
    ("(b) saprotroph/decomposer", "fungal_saprotroph", "llm_decomposer"),
    ("(c) arbuscular mycorrhizal", "fungal_arbuscular", "llm_mycorrhizal"),
]
for label, fcol, lcol in tests:
    cmp[f"agree_{lcol}"] = cmp[fcol] == cmp[lcol]
    pairs = list(zip(cmp[fcol].astype(bool), cmp[lcol].astype(bool)))
    unw = [1.0] * len(cmp)
    wt = cmp["reads"].astype(float).tolist()
    n = len(cmp)
    agree = cmp[f"agree_{lcol}"].mean() * 100
    w_agree = 100 * sum(w for w, ok in zip(wt, cmp[f"agree_{lcol}"]) if ok) / sum(wt) if sum(wt) else float("nan")
    k_unw = kappa(pairs, unw)
    k_wt = kappa(pairs, wt)
    n_fung = int(cmp[fcol].sum())
    n_llm = int(cmp[lcol].sum())
    print(f"{label}: n={n}  agree={agree:.1f}%  kappa={k_unw:.3f}  | read-weighted agree={w_agree:.1f}%  "
          f"kappa={k_wt:.3f}  | FUNGuild positives={n_fung}, LLM positives={n_llm}")

cmp = cmp.sort_values("reads", ascending=False)
out_cols = ["genus", "reads", "fungal_category", "fungal_can_be_plant_pathogen", "llm_counted_terms",
            "llm_plant_pathogen", "llm_decomposer", "llm_mycorrhizal", "agree_llm_plant_pathogen",
            "agree_llm_decomposer", "agree_llm_mycorrhizal"]
cmp[out_cols].to_csv(OUT_AGREE, index=False)
print(f"Saved full comparison to {OUT_AGREE}")

dis = cmp[~cmp["agree_llm_plant_pathogen"]].head(15)
print("\n15 most abundant disagreements on (a) plant pathogen:")
print(f"  {'genus':<28} {'reads':>12}  {'FUNGuild category':<22} {'FG can_pp':<9} LLM counted terms")
for r in dis.itertuples():
    print(f"  {r.genus:<28} {r.reads:>12,}  {r.fungal_category:<22} {str(r.fungal_can_be_plant_pathogen):<9} "
          f"{r.llm_counted_terms or '(none counted)'}")
