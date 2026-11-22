"""Conversation state kept in Conversation.state (JSON): pending observation draft, chunks shown."""
from __future__ import annotations

import re

MAX_SEEN = 120
HISTORY_EXCHANGES = 3
HISTORY_MSG_CHARS = 700  # enough of an earlier answer for "nie powtarzaj" to work


class State:
    def __init__(self, conversation):
        self.conversation = conversation
        self.data = dict(conversation.state or {}) if conversation is not None else {}

    # -- pending observation draft
    @property
    def draft(self) -> dict | None:
        return self.data.get("pending_draft")

    def set_draft(self, draft: dict | None) -> None:
        if draft is None:
            self.data.pop("pending_draft", None)
        else:
            self.data["pending_draft"] = draft

    # -- chunks shown in this conversation (valid citation targets)
    @property
    def seen(self) -> dict[str, dict]:
        return self.data.setdefault("seen_chunks", {})

    def remember(self, citations_by_chunk: dict[str, dict]) -> None:
        seen = self.seen
        seen.update(citations_by_chunk)
        if len(seen) > MAX_SEEN:
            for k in list(seen)[: len(seen) - MAX_SEEN]:
                seen.pop(k)

    def save(self) -> None:
        if self.conversation is not None and self.conversation.pk:
            self.conversation.state = self.data
            self.conversation.save(update_fields=["state"])


def history(conversation, exclude_last_user: bool = True) -> list[dict]:
    """Last HISTORY_EXCHANGES exchanges as [{role, text}], without citation markers."""
    if conversation is None or not conversation.pk:
        return []
    msgs = list(conversation.messages.order_by("-created_at", "-id")[: 2 * HISTORY_EXCHANGES + 1])
    msgs.reverse()
    if exclude_last_user and msgs and msgs[-1].role == "user":
        msgs = msgs[:-1]
    out = []
    for m in msgs[-2 * HISTORY_EXCHANGES:]:
        text = re.sub(r"\s*\[\d+(?:,\s*\d+)*\]", "", m.text or "").strip()
        out.append({"role": m.role, "text": text[:HISTORY_MSG_CHARS] + ("…" if len(text) > HISTORY_MSG_CHARS else "")})
    return out
