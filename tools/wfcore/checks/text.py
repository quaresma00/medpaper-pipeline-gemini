"""Markdown / source-text checks."""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import Ctx, Result, check

CITE_RE = re.compile(r"\[(@[^\]]+)\]")
FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", re.M)

# Hard stops: text that must never survive into a deliverable.
PLACEHOLDERS = [
    "TODO", "TBD", "FIXME", "XXX", "PLACEHOLDER", "VERIFY:", "[insert",
    "lorem ipsum", "as an ai", "i cannot provide", "<your ", "xx.x", "N.NN",
]

# Soft flags: phrasing that reads as machine-generated. Reported, not blocking.
AI_TELLS = [
    "delve into", "it is worth noting", "it is important to note",
    "plays a crucial role", "plays a vital role", "paves the way",
    "in today's rapidly evolving", "ever-evolving", "landscape of",
    "tapestry", "underscores the importance", "holds immense promise",
    "cutting-edge", "seamlessly", "a testament to", "navigating the complexities",
    "unlock the potential", "revolutionize", "game-changer",
    "it is crucial to understand", "multifaceted approach", "delves",
    "in the realm of", "shedding light upon", "robust and comprehensive",
]

FORBIDDEN_VISIBLE_SYMBOLS = {
    "\u2193": "down arrow (use words such as 'lower' or 'decreased')",
}


def _body(text: str) -> str:
    text = FENCE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    return text


def _wordcount(text: str) -> int:
    t = _body(text)
    t = CITE_RE.sub(" ", t)
    t = HEADING_RE.sub(" ", t)
    t = re.sub(r"^\s*>.*$", " ", t, flags=re.M)          # blockquotes
    t = re.sub(r"[*_#>|`~\[\]()]", " ", t)
    return len([w for w in t.split() if any(ch.isalnum() for ch in w)])


def _headings(text: str) -> list[str]:
    return [h.strip() for h in HEADING_RE.findall(text)]


@check("forbidden_symbols_absent")
def forbidden_symbols_absent(ctx: Ctx) -> Result:
    paths = ctx.spec.get("paths", [])
    present = [rel for rel in paths if ctx.p(rel).is_file()]
    if not present:
        return Result(False, "forbidden_symbols_absent", "none of the target files exist")
    problems = []
    for rel in present:
        value = ctx.read(rel)
        for symbol, description in FORBIDDEN_VISIBLE_SYMBOLS.items():
            if symbol in value:
                problems.append(f"{rel}: contains {description}")
    if problems:
        return Result(False, "forbidden_symbols_absent", "; ".join(problems[:8]))
    return Result(True, "forbidden_symbols_absent",
                  f"{len(present)} source file(s) contain no forbidden visible control symbols")


@check("md_sections")
def md_sections(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        return Result(False, "md_sections", f"{rel} missing")
    text = ctx.read(rel)
    present = [h.lower() for h in _headings(text)]
    required = ctx.spec.get("headings", [])
    missing = [h for h in required if not any(h.lower() in p for p in present)]
    if missing:
        return Result(
            False,
            "md_sections",
            f"{rel} lacks heading(s): " + "; ".join(missing),
            [f"Required headings for this stage: {', '.join(required)}"],
        )
    return Result(True, "md_sections", f"{rel}: {len(required)} required heading(s) present")


@check("md_wordcount")
def md_wordcount(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        return Result(False, "md_wordcount", f"{rel} missing")
    n = _wordcount(ctx.read(rel))
    soft = not ctx.stage.id.startswith(("S20_","S21_","S22_","S23_","S24_","S25_"))
    lo = ctx.spec_bound("min")
    hi = ctx.spec_bound("max")
    if lo is not None and n < lo:
        return Result(False, "md_wordcount", f"{rel}: {n} words, target >= {lo}",severity="warn" if soft else "fail")
    if hi is not None and n > hi:
        return Result(
            False,
            "md_wordcount",
            f"{rel}: {n} words, target <= {hi}",
            ["Cut, do not compress into denser jargon. Adjust the target with `wf config set` if the journal differs."],
            severity="warn" if soft else "fail",
        )
    return Result(True, "md_wordcount", f"{rel}: {n} words (target {lo}-{hi})")


@check("notes_populated")
def notes_populated(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        return Result(False, "notes_populated", f"{rel} missing")
    text = ctx.read(rel)
    required = ctx.spec.get("headings", [])
    min_chars = ctx.spec.get("min_chars_per_section", 120)
    # split on headings and measure each block
    blocks: dict[str, str] = {}
    parts = re.split(r"^\s{0,3}#{1,6}\s+", text, flags=re.M)
    for chunk in parts[1:]:
        head, _, rest = chunk.partition("\n")
        blocks[head.strip().lower()] = rest
    thin, absent = [], []
    for h in required:
        key = next((k for k in blocks if h.lower() in k), None)
        if key is None:
            absent.append(h)
        elif len(blocks[key].strip()) < min_chars:
            thin.append(f"{h} ({len(blocks[key].strip())} chars)")
    if absent or thin:
        bits = []
        if absent:
            bits.append("absent: " + ", ".join(absent))
        if thin:
            bits.append(f"under {min_chars} chars: " + ", ".join(thin))
        return Result(
            False,
            "notes_populated",
            f"{rel} -> " + "; ".join(bits),
            ["notes.md is what Introduction and Discussion are built from. Thin notes now means invented prose later."],
        )
    return Result(True, "notes_populated", f"{rel}: all {len(required)} note section(s) substantive")


@check("no_ai_boilerplate")
def no_ai_boilerplate(ctx: Ctx) -> Result:
    rel = ctx.spec["path"]
    if not ctx.p(rel).exists():
        if ctx.spec.get("optional", False):
            return Result(True, "no_ai_boilerplate", f"{rel}: optional file absent")
        return Result(False, "no_ai_boilerplate", f"{rel} missing")
    raw = ctx.read(rel)
    low = _body(raw).lower()
    hard = [ph for ph in PLACEHOLDERS if ph.lower() in low]
    if hard:
        return Result(
            False,
            "no_ai_boilerplate",
            f"{rel} still contains placeholder text: " + ", ".join(sorted(set(hard))),
            ["Resolve every placeholder from real data or delete the sentence."],
        )
    soft = [ph for ph in AI_TELLS if ph in low]
    from ..medicalstyle import diagnose
    risks=diagnose(raw,rel)
    if risks:
        return Result(False,"no_ai_boilerplate",f"{rel}: medical-reader review needed: "+"; ".join(sorted({r['kind'] for r in risks})),
                      ["Review this section now, including clinical labels and real post-hoc status. These are context-sensitive prompts, not forbidden medical terms or permission to weaken science."],severity="warn")
    if soft:
        return Result(
            False,
            "no_ai_boilerplate",
            f"{rel}: machine-sounding phrasing -> " + "; ".join(soft[:8]),
            ["Rewrite these clauses in plain clinical prose. Warning only; it does not block."],
            severity="warn",
        )
    return Result(True, "no_ai_boilerplate", f"{rel}: no placeholders, no stock phrasing")


@check("no_plot_calls")
def no_plot_calls(ctx: Ctx) -> Result:
    """Exploratory analysis must not produce figures."""
    banned = [
        "matplotlib", "seaborn", "plotly", "savefig", "plt.", "ggplot",
        "ggsave", "pyplot", "altair", "bokeh",
    ]
    hits = []
    for p in ctx.glob(ctx.spec["glob"]):
        try:
            src = p.read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
        found = sorted({b for b in banned if b in src})
        if found:
            hits.append(f"{p.name}: {', '.join(found)}")
    if hits:
        return Result(
            False,
            "no_plot_calls",
            "plotting code in the exploratory stage -> " + "; ".join(hits),
            ["Exploratory analysis is numbers only. Figures are built in S11 from the approved artifact plan."],
        )
    return Result(True, "no_plot_calls", "exploratory code contains no plotting")


@check("section_polished")
def section_polished(ctx: Ctx) -> Result:
    """Require immediate per-section de-AI, anti-defensive, and clinical polish receipts."""
    if ctx.state.pin_excludes(ctx.stage.id, ctx.spec.get("since")):
        return Result(True, "section_polished", "section-level polish gate not retroactive to pinned completed stage")
    from ..packagefreeze import _sha256
    from ..medicalstyle import diagnose
    from text.polish import AI_TIER_A, allowlist, facts, lint_structure
    rel = ctx.spec.get("path", "")
    if not rel:
        return Result(False, "section_polished", "stage spec missing path for section_polished")
    target = ctx.p(rel)
    if not target.is_file():
        return Result(False, "section_polished", f"missing section {rel}")
    raw = target.read_text(encoding="utf-8")
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", rel.strip("/")).strip("_")
    receipt_path = ctx.p(f".wf/section_polish/{slug}.json")
    if not receipt_path.is_file():
        return Result(
            False,
            "section_polished",
            f"{rel} has not completed per-section de-AI & clinical polish yet",
            [f"1. Run BEFORE polishing edits: uv run python tools/text/polish.py section --file project/{rel} --snapshot",
             f"2. Apply reference/clinical-deai-antidefensive-writing.md rules (preserve all numbers/citekeys/displays).",
             f"3. Verify & seal receipt: uv run python tools/text/polish.py section --file project/{rel} --verify"],
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Result(False, "section_polished", f"corrupt polish receipt for {rel}: {exc}")
    current_hash = _sha256(target)
    if receipt.get("verified_sha256") != current_hash:
        return Result(
            False,
            "section_polished",
            f"{rel} changed after per-section polish verification; re-verify section polish",
            [f"Run: uv run python tools/text/polish.py section --file project/{rel} --verify"],
        )
    if not receipt.get("fact_preserving") or receipt.get("blocking_total", 1) != 0:
        return Result(
            False,
            "section_polished",
            f"{rel} polish receipt failed fact-preservation or blocking style checks: {receipt.get('summary', '')}",
        )
    risks = [r["kind"] for r in diagnose(raw, rel) if r["kind"] in {"engineering_jargon", "lablog_chronology", "defensive_self_weakening", "assistant_voice", "workflow_metadata"}]
    if risks:
        return Result(
            False,
            "section_polished",
            f"{rel} still contains clinical-style violations ({', '.join(sorted(set(risks)))}); polish in medical language and re-verify",
        )
    struct_blocking = [x for x in lint_structure(rel, raw) if x.get("severity") == "blocking"]
    if struct_blocking:
        return Result(False, "section_polished", f"{rel} has blocking prose structure defects: {struct_blocking[0]['kind']}")
    return Result(True, "section_polished", f"{rel}: per-section de-AI, anti-defensive, and clinical polish verified")
