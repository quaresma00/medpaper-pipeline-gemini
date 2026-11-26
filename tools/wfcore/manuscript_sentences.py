"""Shared clinical prose sentence splitter (preserves abbreviations like vs., et al., Fig.)."""
from __future__ import annotations

import re

_ABBR_DOT_RE = re.compile(
    r"\b(vs|et\s+al|e\.g|i\.e|Fig|Figs|No|Ref|Refs|Dr|Prof|approx|ca)\.\s+",
    re.I,
)
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'“])")


def split_prose_sentences(block: str) -> list[str]:
    out: list[str] = []
    for para in re.split(r"\n\s*\n", block or ""):
        stripped = para.strip()
        if not stripped or re.match(r"^#{1,6}\s+", stripped):
            continue
        compact = re.sub(r"\s*\n\s*", " ", stripped)
        protected = _ABBR_DOT_RE.sub(lambda m: m.group(0).replace(". ", ".\u0000"), compact)
        for piece in _SENT_SPLIT_RE.split(protected):
            sent = piece.replace(".\u0000", ". ").strip()
            if sent:
                out.append(sent)
    return out
