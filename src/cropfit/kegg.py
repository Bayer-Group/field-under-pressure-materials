"""KEGG modules: definitions from the KEGG REST API and their completeness in a set of KEGG genes (KOs).

A KEGG module is a named functional unit ("Denitrification, nitrate => nitrogen") defined as a sequence of steps.
The DEFINITION is a small expression over KO identifiers:
    space     separates steps (inside parentheses too: a sub-sequence, all needed)
    ,         alternatives (any one is enough)
    +         members of a complex (all needed)
    -         optional member of a complex (not needed)
    ( )       grouping;  --  a step with no known KO (counted as satisfied: it cannot be measured)
    Mxxxxx    another module (satisfied when that module is complete)
Completeness = steps satisfied / steps, at the top level of the definition (as KEGG's own module mapper and
MGnify's kegg-pathways-completeness do). A step needs only one KO copy here; copy numbers are kept elsewhere.

KO_ALIASES covers KEGG renumbering since NMDC annotated our samples: the old K10944 "pmoA-amoA" (ammonia *or*
methane monooxygenase) is now methane monooxygenase only, and ammonia monooxygenase got new IDs. Without the
alias, nitrification would always look incomplete; with it, the step is flagged as ambiguous.

KEGG REST is free for academic use (https://www.kegg.jp/kegg/rest/); responses are cached under data/cache/kegg/.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from . import http

REST = "https://rest.kegg.jp"
# new KO in a current definition -> older KO(s) that satisfy it in older annotations, with the reason
KO_ALIASES: dict[str, tuple[list[str], str]] = {
    "K28504": (["K10944"], "amoA: annotated as K10944 'pmoA-amoA', cannot tell ammonia from methane oxidisers"),
    "K28505": (["K10945"], "amoB: annotated as K10945 'pmoB-amoB'"),
    "K28506": (["K10946"], "amoC: annotated as K10946 'pmoC-amoC'"),
}


# ------------------------------------------------------------------ fetching
def _get(path: str) -> str:
    return http.cached("kegg", path, lambda: http.get(f"{REST}/{path}", timeout=120).text, as_text=True)


def hierarchy() -> pd.DataFrame:
    """Module -> name and class (A pathway/signature modules, B e.g. 'Energy metabolism', C e.g. 'Nitrogen
    metabolism') from the KEGG BRITE hierarchy br:ko00002."""
    rows, a, b, c = [], None, None, None
    for line in _get("get/br:ko00002").splitlines():
        if line.startswith("A"):
            a = re.sub(r"<[^>]+>", "", line[1:]).strip()
        elif line.startswith("B"):
            b = re.sub(r"<[^>]+>", "", line[1:]).strip()
        elif line.startswith("C"):
            c = line[1:].strip()
        elif line.startswith("D"):
            m = re.match(r"D\s+(M\d{5})\s+(.*?)(\s+\[.*\])?$", line)
            if m:
                rows.append(dict(module=m.group(1), name=m.group(2).strip(), class_a=a, class_b=b, class_c=c))
    return pd.DataFrame(rows).drop_duplicates("module")


def definitions(modules: list[str], batch: int = 10) -> dict[str, str]:
    """Module -> DEFINITION string (continuation lines joined), fetched 10 entries per request."""
    out: dict[str, str] = {}
    for i in range(0, len(modules), batch):
        text = _get("get/" + "+".join(modules[i:i + batch]))
        for entry in text.split("///"):
            m = re.search(r"^ENTRY\s+(M\d{5})", entry, re.M)
            d = re.search(r"^DEFINITION\s+(.*?)(?=^\S)", entry + "\nEND", re.M | re.S)
            if m and d:
                out[m.group(1)] = " ".join(x.strip() for x in d.group(1).splitlines() if x.strip())
    return out


def module_table() -> pd.DataFrame:
    h = hierarchy()
    defs = definitions(h["module"].tolist())
    h["definition"] = h["module"].map(defs)
    h = h[h["definition"].notna()].copy()
    h["n_steps"] = h["definition"].map(lambda d: len(parse(d)[1]))
    return h.reset_index(drop=True)


# ------------------------------------------------------------------ parsing
TOKEN = re.compile(r"K\d{5}|M\d{5}|--|[(),+\- ]")


@dataclass
class Node:
    op: str                     # ko | module | none | and | or
    value: str = ""
    kids: tuple = ()


def _tokens(definition: str) -> list[str]:
    s = re.sub(r"\s+", " ", definition.strip())
    toks = TOKEN.findall(s)
    if "".join(toks) != s:
        raise ValueError(f"unparsed characters in definition: {definition!r}")
    return toks


def parse(definition: str) -> tuple[Node, list[Node]]:
    """Return (whole expression, top-level steps)."""
    toks, pos = _tokens(definition), 0

    def peek():
        return toks[pos] if pos < len(toks) else None

    def take():
        nonlocal pos
        pos += 1
        return toks[pos - 1]

    def seq() -> Node:
        items = [alt()]
        while peek() == " ":
            take()
            if peek() in (None, ")"):
                break
            items.append(alt())
        return items[0] if len(items) == 1 else Node("and", kids=tuple(items))

    def alt() -> Node:
        items = [comp()]
        while peek() == ",":
            take()
            items.append(comp())
        return items[0] if len(items) == 1 else Node("or", kids=tuple(items))

    def comp() -> Node:
        if peek() == "-" and pos + 1 < len(toks) and toks[pos + 1] != "-":
            take()                                      # leading optional member: ignore it
            factor()
            return Node("none")
        req = [factor()]
        while peek() in ("+", "-"):
            op = take()
            f = factor()
            if op == "+":
                req.append(f)
        return req[0] if len(req) == 1 else Node("and", kids=tuple(req))

    def factor() -> Node:
        t = take()
        if t == "(":
            n = seq()
            if take() != ")":
                raise ValueError(f"unbalanced parentheses in {definition!r}")
            return n
        if t == "--":
            return Node("none")
        if t.startswith("K"):
            return Node("ko", t)
        if t.startswith("M"):
            return Node("module", t)
        raise ValueError(f"unexpected token {t!r} in {definition!r}")

    root = seq()
    if pos != len(toks):
        raise ValueError(f"trailing tokens in {definition!r}")
    steps = list(root.kids) if root.op == "and" else [root]
    return root, steps


def kos_in(node: Node) -> set[str]:
    if node.op == "ko":
        return {node.value}
    return set().union(*(kos_in(k) for k in node.kids)) if node.kids else set()


# ------------------------------------------------------------------ evaluation
def present_with_aliases(kos: set[str]) -> tuple[set[str], set[str]]:
    """Add current KO IDs that older annotations satisfy (KO_ALIASES); also return the IDs added that way."""
    added = {new for new, (old, _) in KO_ALIASES.items() if new not in kos and any(o in kos for o in old)}
    return kos | added, added


def satisfied(node: Node, kos: set[str], complete_modules: set[str]) -> bool:
    if node.op == "ko":
        return node.value in kos
    if node.op == "module":
        return node.value in complete_modules
    if node.op == "none":
        return True
    if node.op == "or":
        return any(satisfied(k, kos, complete_modules) for k in node.kids)
    return all(satisfied(k, kos, complete_modules) for k in node.kids)


def completeness(definition: str, kos: set[str], complete_modules: set[str] | None = None) -> tuple[int, int, list[int]]:
    """(steps satisfied, steps, indices of missing steps) for one module and a set of present KOs."""
    _, steps = parse(definition)
    ok = [satisfied(s, kos, complete_modules or set()) for s in steps]
    return sum(ok), len(steps), [i for i, v in enumerate(ok) if not v]


def step_texts(definition: str) -> list[str]:
    """The top-level steps as text, for showing which step is missing."""
    parts, depth, cur = [], 0, ""
    for ch in re.sub(r"\s+", " ", definition.strip()):
        if ch == " " and depth == 0:
            parts.append(cur)
            cur = ""
            continue
        depth += ch == "("
        depth -= ch == ")"
        cur += ch
    return parts + [cur] if cur else parts


def score_sample(modules: pd.DataFrame, kos: set[str]) -> pd.DataFrame:
    """Completeness of every module for one sample's KO set. Modules that reference other modules are scored
    after those (two passes are enough for KEGG's shallow nesting)."""
    present, aliased = present_with_aliases(kos)
    complete: set[str] = set()
    rows = {}
    for _ in range(2):
        for r in modules.itertuples():
            found, n, missing = completeness(r.definition, present, complete)
            rows[r.module] = (found, n, missing)
            if found == n:
                complete.add(r.module)
    out = []
    for r in modules.itertuples():
        found, n, missing = rows[r.module]
        steps = step_texts(r.definition)
        used_alias = sorted(aliased & kos_in(parse(r.definition)[0]))
        out.append(dict(module=r.module, steps_found=found, n_steps=n, completeness=found / n if n else 0.0,
                        missing_steps="; ".join(steps[i] for i in missing if i < len(steps)),
                        via_alias=", ".join(used_alias)))
    return pd.DataFrame(out)
