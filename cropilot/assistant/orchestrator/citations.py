"""
Citation finalisation: the model cites `[chunk_id]` exactly as given in the <zrodla> block.

* known ids (sources of this answer or shown earlier in the conversation) -> `[1]`, `[2]` in order
  of first appearance; `Reply.citations` gets their `Passage.to_citation()` dicts + `"ref": n`;
* ids that look like chunk ids but were never given -> removed from the text, warning logged;
* brackets that are not chunk ids are left alone;
* fullwidth brackets, 【id】 (gpt-oss writes them), count as [id].
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("assistant.citations")

BRACKET_RE = re.compile(r"\[([^\[\]\n]{3,200})\]")
INVISIBLE_RE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")  # zero-width chars models sometimes emit
# gpt-oss (Groq) writes citations in fullwidth brackets, 【id】; normalised to [id] before parsing
FULLWIDTH_BRACKETS = str.maketrans({"【": "[", "】": "]", "〔": "[", "〕": "]", "［": "[", "］": "]"})
CHUNK_ID_RE = re.compile(r"^[a-z][a-z0-9_]*:[A-Za-z0-9_.\-]+(?::\d{4})?$")


def _known_doc_ids() -> set[str]:
    from assistant.rag import config
    from assistant.rag.docs import REGISTRY
    return {d.doc_id for d in REGISTRY} | {config.EXCEL_DOC_ID}


def finalize(text: str, allowed: dict[str, dict]) -> tuple[str, list[dict], list[str]]:
    """Returns (text with [n], guide citations, unknown ids removed).

    `allowed`: chunk_id -> citation dict (Passage.to_citation() format)."""
    text = INVISIBLE_RE.sub("", text.translate(FULLWIDTH_BRACKETS)).replace("\u202f", " ").replace("\u00a0", " ")
    docs = _known_doc_ids()
    order: list[str] = []
    unknown: list[str] = []

    def repl(m: re.Match) -> str:
        tokens = [t.strip().strip("`'\"") for t in re.split(r"[,;]", m.group(1))]
        chunkish = [t for t in tokens if CHUNK_ID_RE.match(t) and t.split(":")[0] in docs]
        if not chunkish:
            if tokens and all(t.startswith("silnik:") for t in tokens):
                return ""  # engine ids only (also several in one bracket)
            return m.group(0)  # an ordinary bracket, keep
        refs = []
        for t in chunkish:
            if t in allowed:
                if t not in order:
                    order.append(t)
                refs.append(order.index(t) + 1)
            else:
                unknown.append(t)
        refs = sorted(set(refs))
        return f"[{', '.join(map(str, refs))}]" if refs else ""

    # [silnik:<threat code>] marks a fact from the engine's risk (the answer's risk citations list it): no [n]
    text = re.sub(r"\s*\[silnik:[a-z_]+\.[a-z0-9_]+\]", "", text)
    # the model sometimes "cites" a prompt block by its name: [kontekst], [źródła], [silnik]
    text = re.sub(r"\s*\[(kontekst|zrodla|źródła|zródła|silnik|historia|pytanie|brak fragmentów metodyk|brak źródeł)\]", "",
                  text, flags=re.I)
    out = BRACKET_RE.sub(repl, text)
    out = re.sub(r"(\w)\[(\d[\d, ]*)\]", r"\1 [\2]", out)   # "liści【id】" glued to the word -> "liści [1]"
    out = re.sub(r"[ \t]+([.,;:!?])", r"\1", out)          # "tekst ." after removed refs
    out = re.sub(r"[ \t]{2,}", " ", out).strip()
    if unknown:
        log.warning("removed citations of chunks not given to the model: %s", unknown)
    cits = [allowed[c] | {"ref": i + 1} for i, c in enumerate(order)]
    return out, cits, unknown
