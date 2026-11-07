"""Discussion context isolation, outline-first gate, anti-restatement & review checks (v1.28+).

Enforces four workflow guarantees for the Discussion:
1. Context isolation (``07_manuscript/discussion_brief.md``): the writing brief handed to
   S16 contains NO result tables and NO table/figure callout numbers — only prose summaries
   of principal findings, deep-read literature comparisons, candidate mechanisms, and
   limitations/bias notes.
2. Outline before prose (``07_manuscript/discussion_outline.md`` + receipt): before writing
   ``07_manuscript/discussion.md``, a short 6-part outline must be completed and locked:
   Principal findings; Comparison with prior studies and reasons for differences; Potential
   mechanisms; Clinical implications; Limitations and direction of bias; Conclusion.
3. Automated checks: blocks excessive supplementary table/figure callouts (and main display
   number dumping) in the Discussion, and blocks sentences that are near-duplicates of
   sentences in Results.
4. Dedicated review audit: S18, S19, S24, and S25 independent review reports must include a
   substantive ``Discussion audit`` section verifying results non-restatement, literature
   comparison + reasons for differences, mechanisms, and clinical implications.
"""
from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .packagefreeze import _safe_path, _sha256
from .readiness import atomic_json

BRIEF_REL = "07_manuscript/discussion_brief.md"
OUTLINE_REL = "07_manuscript/discussion_outline.md"
DISCUSSION_REL = "07_manuscript/discussion.md"
RESULTS_REL = "07_manuscript/results.md"
RECEIPT_REL = ".wf/discussion_outline_receipt.json"

BRIEF_SECTIONS = (
    "Principal findings summary",
    "Deep-read comparison points",
    "Candidate mechanisms",
    "Limitations and bias notes",
)
OUTLINE_SECTIONS = (
    "Principal findings",
    "Comparison with prior studies and reasons for differences",
    "Potential mechanisms",
    "Clinical implications",
    "Limitations and direction of bias",
    "Conclusion",
)

FENCE_RE = re.compile(r"```.*?```", re.S)
PLACEHOLDER_RE = re.compile(r"\b(?:TODO|TBD|FIXME|XXX)\b|<[^>\n]{2,50}>", re.I)
PIPE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
GRID_TABLE_RE = re.compile(r"^\s*\+[=-]{3,}(?:\+[=-]{3,})+\+\s*$", re.M)

ANY_DISPLAY_NUMBER_RE = re.compile(
    r"\b(?:"
    r"(?:supplementary|supplemental)\s+(?:tables?|figures?|figs?\.?|files?|materials?|appendi(?:x|ces))(?:\s+S?\d+[A-Za-z]?)?"
    r"|(?:tables?|figures?|figs?\.?|etables?|efigures?)\s+S?\d+[A-Za-z]?"
    r")\b",
    re.I,
)
FORBIDDEN_BRIEF_PATHS_RE = re.compile(
    r"(?:04_tables|05_figures/out|artifact_plan\.json|\.xlsx\b)",
    re.I,
)

SUPP_CALLOUT_RE = re.compile(
    r"\b(?:"
    r"(?:supplementary|supplemental)\s+(?:tables?|figures?|figs?\.?|files?|appendi(?:x|ces))(?:\s+S?\d+[A-Za-z]?)?"
    r"|(?:tables?|figures?|figs?\.?|etables?|efigures?)\s+S\d+[A-Za-z]?"
    r")\b",
    re.I,
)
MAIN_CALLOUT_RE = re.compile(
    r"(?<!supplementary\s)(?<!supplemental\s)\b(?:tables?|figures?|figs?\.?)\s+[1-9]\d*[A-Za-z]?\b",
    re.I,
)

LEADING_TRANSITIONS_RE = re.compile(
    r"^(?:in\s+(?:this|our|the\s+present)\s+(?:study|cohort|analysis|trial|investigation)\s*,\s*"
    r"|(?:specifically|notably|moreover|furthermore|additionally|overall|taken\s+together|"
    r"importantly|interestingly|in\s+addition|in\s+summary|first|second|third|finally)\s*,\s*)+",
    re.I,
)
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "between", "both", "by",
    "for", "from", "had", "has", "have", "in", "into", "is", "it", "its", "of", "on", "or",
    "our", "present", "study", "than", "that", "the", "their", "there", "these", "this",
    "those", "to", "was", "we", "were", "which", "while", "with", "within", "without",
}


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+(?:['’-]\w+)*\b", text))


def _h2_sections(text: str) -> list[tuple[str, str]]:
    cleaned = FENCE_RE.sub("", text)
    matches = list(re.finditer(r"(?m)^##\s+([^\n#]+?)\s*#*\s*$", cleaned))
    out: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        heading = match.group(1).strip()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned)
        body = cleaned[match.end():end].strip()
        out.append((heading, body))
    return out


def strip_display_callouts(text: str) -> str:
    """Strip figure/table callouts and table paths when scaffolding a prose-only brief."""
    cleaned = FENCE_RE.sub(" ", text)
    cleaned = re.sub(
        r"\(\s*(?:see\s+|as\s+shown\s+in\s+)?(?:supplementary\s+|supplemental\s+)?"
        r"(?:tables?|figures?|figs?\.?|etables?|efigures?)[^)]*\)",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(
        r"\b(?:as\s+shown\s+in|see|in)\s+(?:supplementary\s+|supplemental\s+)?"
        r"(?:tables?|figures?|figs?\.?)\s+S?\d+[A-Za-z]?(?:\s*(?:and|,|–|-)\s*(?:tables?|figures?|figs?\.?)?\s*S?\d+[A-Za-z]?)*",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = ANY_DISPLAY_NUMBER_RE.sub("", cleaned)
    cleaned = FORBIDDEN_BRIEF_PATHS_RE.sub("", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:!?])", r"\1", cleaned)
    return cleaned.strip()


def _has_table_markup(text: str) -> bool:
    cleaned = FENCE_RE.sub("", text)
    return bool(
        any(PIPE_DIVIDER_RE.match(line) for line in cleaned.splitlines())
        or re.search(r"<table\b", cleaned, re.I)
        or GRID_TABLE_RE.search(cleaned)
    )


def validate_brief(project: Path) -> list[str]:
    """Validate 07_manuscript/discussion_brief.md (no tables, no display numbers)."""
    path = project / BRIEF_REL
    if not path.is_file():
        return [
            f"{BRIEF_REL} missing; build the table-free, number-callout-free Discussion brief first "
            "(uv run python tools/manuscript/discussion_brief.py scaffold)"
        ]
    text = path.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    if PLACEHOLDER_RE.search(text):
        problems.append(f"{BRIEF_REL}: contains unresolved TODO/placeholder text")
    if _has_table_markup(text):
        problems.append(f"{BRIEF_REL}: must not contain any result tables")
    bad_paths = FORBIDDEN_BRIEF_PATHS_RE.findall(text)
    if bad_paths:
        problems.append(f"{BRIEF_REL}: must not reference result table files or artifact_plan ({bad_paths[0]})")
    callouts = [m.group(0) for m in ANY_DISPLAY_NUMBER_RE.finditer(FENCE_RE.sub(" ", text))]
    if callouts:
        problems.append(
            f"{BRIEF_REL}: must not contain table/figure numbers or supplementary display labels "
            f"(found: {', '.join(callouts[:5])})"
        )

    sec_list = _h2_sections(text)
    sec_map = {h.casefold(): body for h, body in sec_list}
    for required in BRIEF_SECTIONS:
        body = sec_map.get(required.casefold(), "")
        if not body:
            problems.append(f"{BRIEF_REL}: missing required section '## {required}'")
        elif len(body) < 40:
            problems.append(f"{BRIEF_REL}: section '## {required}' is too thin ({len(body)} chars; need >= 40)")
    return problems


def validate_outline(project: Path) -> list[str]:
    """Validate the concise 6-part 07_manuscript/discussion_outline.md."""
    path = project / OUTLINE_REL
    if not path.is_file():
        return [
            f"{OUTLINE_REL} missing; write the short 6-part Discussion outline before drafting discussion.md"
        ]
    text = path.read_text(encoding="utf-8", errors="replace")
    problems: list[str] = []
    if PLACEHOLDER_RE.search(text):
        problems.append(f"{OUTLINE_REL}: contains unresolved TODO/placeholder text")
    if _has_table_markup(text):
        problems.append(f"{OUTLINE_REL}: outline must not contain tables")
    callouts = [m.group(0) for m in ANY_DISPLAY_NUMBER_RE.finditer(FENCE_RE.sub(" ", text))]
    if callouts:
        problems.append(
            f"{OUTLINE_REL}: outline must focus on findings/arguments rather than table/figure numbers "
            f"(found: {', '.join(callouts[:4])})"
        )

    words = _word_count(text)
    if words < 50:
        problems.append(f"{OUTLINE_REL}: outline is too skeletal ({words} words; need >= 50)")
    elif words > 650:
        problems.append(
            f"{OUTLINE_REL}: outline must stay concise ({words} words; keep <= 650 words before drafting full prose)"
        )

    sec_list = _h2_sections(text)
    observed_order = [h.casefold() for h, _ in sec_list]
    sec_map = {h.casefold(): body for h, body in sec_list}
    expected_indices: list[int] = []
    for required in OUTLINE_SECTIONS:
        key = required.casefold()
        if key not in sec_map:
            problems.append(f"{OUTLINE_REL}: missing required heading '## {required}'")
            continue
        expected_indices.append(observed_order.index(key))
        body = sec_map[key]
        if len(body) < 25:
            problems.append(f"{OUTLINE_REL}: '## {required}' needs substantive points (>= 25 chars)")

    if len(expected_indices) == len(OUTLINE_SECTIONS) and expected_indices != sorted(expected_indices):
        problems.append(
            f"{OUTLINE_REL}: the 6 required outline sections must appear in canonical order: "
            + " -> ".join(OUTLINE_SECTIONS)
        )

    comp_body = sec_map.get("comparison with prior studies and reasons for differences", "")
    if comp_body and not re.search(
        r"\b(?:differ\w*|discrepan\w*|diverg\w*|contrast\w*|consisten\w*|attribut\w*|because|due\s+to|"
        r"population|cohort|design|definition|assay|exposure|follow-up|adjust\w*|setting)\b",
        comp_body,
        re.I,
    ):
        problems.append(
            f"{OUTLINE_REL}: 'Comparison with prior studies and reasons for differences' must state concrete reasons for agreement/differences"
        )

    lim_body = sec_map.get("limitations and direction of bias", "")
    if lim_body and not re.search(
        r"\b(?:bias\w*|overestimat\w*|underestimat\w*|toward\s+the\s+null|away\s+from\s+the\s+null|"
        r"attenuat\w*|inflat\w*|dilut\w*|conservativ\w*|direction)\b",
        lim_body,
        re.I,
    ):
        problems.append(
            f"{OUTLINE_REL}: 'Limitations and direction of bias' must explicitly state the expected direction of bias"
        )
    return problems


def lock_outline(project: Path, *, reset_draft: bool = False) -> dict:
    """Verify brief + outline and record proof that outline preceded drafting discussion.md."""
    disc_path = project / DISCUSSION_REL
    if disc_path.is_file():
        if reset_draft:
            disc_path.unlink()
        else:
            receipt_path = project / RECEIPT_REL
            existing = {}
            if receipt_path.is_file():
                try:
                    existing = json.loads(receipt_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    existing = {}
            if not existing.get("locked_before_draft"):
                raise ValueError(
                    f"{DISCUSSION_REL} already exists without a prior outline lock; "
                    "the 6-part outline must be written BEFORE drafting discussion.md "
                    "(remove or pass --reset-draft to lock the outline first, then write discussion.md)"
                )

    problems = validate_brief(project) + validate_outline(project)
    if problems:
        raise ValueError("; ".join(problems))

    payload = {
        "schema_version": 1,
        "locked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "locked_before_draft": True,
        "brief_sha256": _sha256(project / BRIEF_REL),
        "outline_sha256": _sha256(project / OUTLINE_REL),
    }
    atomic_json(project / RECEIPT_REL, payload)
    return payload


def validate_discussion_workflow(project: Path) -> list[str]:
    """Verify brief, 6-part outline, and pre-draft outline lock receipt at S16."""
    problems = validate_brief(project) + validate_outline(project)
    if problems:
        return problems
    receipt_path = project / RECEIPT_REL
    if not receipt_path.is_file():
        return [
            f"{RECEIPT_REL} missing; lock the completed brief and 6-part outline BEFORE drafting {DISCUSSION_REL} "
            "via: uv run python tools/manuscript/discussion_brief.py lock-outline"
        ]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{RECEIPT_REL}: invalid JSON ({exc})"]
    if receipt.get("locked_before_draft") is not True:
        problems.append("outline lock receipt does not certify pre-draft completion")
    if receipt.get("brief_sha256") != _sha256(project / BRIEF_REL):
        problems.append(
            f"{BRIEF_REL} changed after locking the outline; run discussion_brief.py lock-outline and reconcile discussion.md"
        )
    if receipt.get("outline_sha256") != _sha256(project / OUTLINE_REL):
        problems.append(
            f"{OUTLINE_REL} changed after locking the outline; run discussion_brief.py lock-outline and reconcile discussion.md"
        )
    return problems


def _extract_h1_section(text: str, heading_names: set[str]) -> str | None:
    cleaned = FENCE_RE.sub("", text)
    matches = list(re.finditer(r"(?m)^#\s+([^\n#]+?)\s*#*\s*$", cleaned))
    for idx, match in enumerate(matches):
        name = match.group(1).strip().casefold()
        if name in heading_names:
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned)
            return cleaned[match.end():end].strip()
    return None


def _split_sentences(text: str) -> list[str]:
    cleaned = FENCE_RE.sub(" ", text)
    cleaned = re.sub(r"(?m)^#{1,6}\s+.*$", " ", cleaned)
    # Protect decimal points and common abbreviations before sentence splitting.
    protected = re.sub(r"(?<=\d)\.(?=\d)", "<DEC>", cleaned)
    protected = re.sub(r"\b(Fig|Figs|et\s+al|vs|e\.g|i\.e|Dr|No)\.", r"\1<DOT>", protected, flags=re.I)
    raw_parts = re.split(r"(?<=[.!?])\s+|\n{2,}", protected)
    out: list[str] = []
    for part in raw_parts:
        restored = part.replace("<DEC>", ".").replace("<DOT>", ".").strip()
        if restored:
            out.append(restored)
    return out


def _normalize_sentence(sentence: str) -> tuple[str, list[str], set[str]]:
    s = re.sub(r"\[[^\]]*@[^\]]*\]", " ", sentence)
    s = re.sub(r"@[A-Za-z][\w:.#$%&+?<>~/-]*", " ", s)
    s = re.sub(r"\([^)]*(?:table|figure|fig\.?)[^)]*\)", " ", s, flags=re.I)
    s = LEADING_TRANSITIONS_RE.sub("", s.strip())
    s = s.casefold()
    tokens = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?%?", s)
    norm_str = " ".join(tokens)
    content = {tok for tok in tokens if tok not in STOPWORDS and (len(tok) >= 3 or any(ch.isdigit() for ch in tok))}
    return norm_str, tokens, content


def _trigrams(tokens: list[str]) -> set[tuple[str, str, str]]:
    if len(tokens) < 3:
        return set()
    return {(tokens[i], tokens[i + 1], tokens[i + 2]) for i in range(len(tokens) - 2)}


def validate_discussion_discipline(
    project: Path,
    target_rel: str,
    *,
    supp_max: int = 1,
    main_max: int = 2,
) -> list[str]:
    """Enforce supplementary-callout limits and block near-duplicate Results sentences."""
    _, target_path = _safe_path(project, target_rel)
    if not target_path.is_file():
        return [f"{target_rel} missing"]

    raw_text = target_path.read_text(encoding="utf-8", errors="replace")
    disc_aliases = {"discussion"}
    res_aliases = {"results"}
    from .journalspec import aliases, load as load_target
    try:
        mapped = aliases(load_target(project))
        if "Discussion" in mapped:
            disc_aliases.add(mapped["Discussion"].strip().casefold())
        if "Results" in mapped:
            res_aliases.add(mapped["Results"].strip().casefold())
    except Exception:  # noqa: BLE001
        pass

    if "full_manuscript" in Path(target_rel).name:
        disc_text = _extract_h1_section(raw_text, disc_aliases)
        res_text = _extract_h1_section(raw_text, res_aliases)
        if disc_text is None:
            return [f"{target_rel}: Discussion section not found"]
        if res_text is None:
            res_file = project / RESULTS_REL
            res_text = res_file.read_text(encoding="utf-8", errors="replace") if res_file.is_file() else ""
    else:
        disc_text = _extract_h1_section(raw_text, disc_aliases) or raw_text
        res_file = project / RESULTS_REL
        res_text = res_file.read_text(encoding="utf-8", errors="replace") if res_file.is_file() else ""

    problems: list[str] = []
    cleaned_disc = FENCE_RE.sub(" ", disc_text)

    # 1. Block excessive supplementary table/figure references (and main table/figure dumping).
    supp_hits = [m.group(0) for m in SUPP_CALLOUT_RE.finditer(cleaned_disc)]
    if len(supp_hits) > supp_max:
        problems.append(
            f"{target_rel}: Discussion cites supplementary tables/figures {len(supp_hits)} time(s) "
            f"(maximum allowed: {supp_max}; found: {', '.join(supp_hits[:6])}); "
            "synthesize findings in prose rather than leaning on supplementary display items"
        )
    main_hits = [m.group(0) for m in MAIN_CALLOUT_RE.finditer(cleaned_disc)]
    if len(main_hits) > main_max:
        problems.append(
            f"{target_rel}: Discussion cites main table/figure numbers {len(main_hits)} time(s) "
            f"(maximum allowed: {main_max}; found: {', '.join(main_hits[:6])}); "
            "discuss clinical meaning without re-indexing Results tables/figures"
        )

    # 2. Block sentences that are near-duplicates of sentences in Results.
    if res_text.strip():
        res_prepared = []
        for r_sent in _split_sentences(res_text):
            r_norm, r_toks, r_content = _normalize_sentence(r_sent)
            if len(r_toks) >= 8:
                res_prepared.append((r_sent, r_norm, r_toks, r_content, _trigrams(r_toks)))

        duplicates: list[str] = []
        for d_sent in _split_sentences(disc_text):
            d_norm, d_toks, d_content = _normalize_sentence(d_sent)
            if len(d_toks) < 8:
                continue
            d_tri = _trigrams(d_toks)
            for r_sent, r_norm, r_toks, r_content, r_tri in res_prepared:
                matched = False
                if d_norm == r_norm or (len(d_toks) >= 8 and (d_norm in r_norm or r_norm in d_norm)):
                    matched = True
                else:
                    ratio = difflib.SequenceMatcher(None, d_norm, r_norm).ratio()
                    if ratio >= 0.72:
                        matched = True
                    elif d_tri and r_tri and len(d_toks) >= 9 and len(r_toks) >= 9:
                        tri_overlap = len(d_tri & r_tri) / min(len(d_tri), len(r_tri))
                        if tri_overlap >= 0.62:
                            matched = True
                    if not matched and len(d_content & r_content) >= 6:
                        jaccard = len(d_content & r_content) / max(1, len(d_content | r_content))
                        if jaccard >= 0.70:
                            matched = True
                if matched:
                    snippet = d_sent[:110] + ("..." if len(d_sent) > 110 else "")
                    duplicates.append(f"near-duplicate of Results sentence: {snippet!r}")
                    break
        if duplicates:
            problems.append(
                f"{target_rel}: Discussion repeats Results wording ({len(duplicates)} sentence(s); "
                f"first: {duplicates[0]}); synthesize principal findings instead of copying Results sentences"
            )
    return problems


def audit_report_discussion_problems(report_text: str, label: str) -> list[str]:
    """Verify that an independent review report contains a substantive Discussion audit."""
    from .reviewfindings import sections
    try:
        bodies = sections(report_text)
    except ValueError as exc:
        return [f"{label}: {exc}"]

    body = ""
    for heading, content in bodies.items():
        if heading.strip().casefold() == "discussion audit":
            body = content.strip()
            break
    if len(body) < 80:
        return [
            f"{label}: requires a substantive '## Discussion audit' section (>= 80 chars) explicitly checking "
            "(1) whether Results were restated, (2) comparison with prior literature and reasons for differences, "
            "(3) candidate mechanisms, and (4) clinical implications"
        ]

    missing: list[str] = []
    if not re.search(r"\b(?:restat\w*|repeat\w*|recapitulat\w*|rehash\w*|duplicat\w*|results)\b", body, re.I):
        missing.append("whether Results were restated")
    if not (
        re.search(r"\b(?:prior|previous|literature|published|compar\w*|studies|trials|cohorts)\b", body, re.I)
        and re.search(r"\b(?:differ\w*|discrepan\w*|diverg\w*|heterogen\w*|reason\w*|why|explain\w*|account\w*|consisten\w*)\b", body, re.I)
    ):
        missing.append("comparison with prior literature and reasons for differences")
    if not re.search(r"\b(?:mechanis\w*|biolog\w*|pathophysiolog\w*|pathway\w*|plausib\w*)\b", body, re.I):
        missing.append("candidate mechanisms")
    if not re.search(r"\b(?:clinical\w*|implicat\w*|significan\w*|practice|translat\w*|decision\w*|utility)\b", body, re.I):
        missing.append("clinical implications")

    if missing:
        return [f"{label}: 'Discussion audit' omits explicit check of: {', '.join(missing)}"]
    return []


def validate_discussion_review(project: Path, stage_id: str) -> list[str]:
    """Verify dedicated Discussion audit across S18, S19, S24, and S25 review reports."""
    from .reviewrounds import latest

    targets: list[tuple[str, Path]] = []
    if stage_id == "S18_independent_review":
        targets.append((
            "07_manuscript/independent_publishability_review.md",
            project / "07_manuscript/independent_publishability_review.md",
        ))
    elif stage_id == "S19_human_review":
        targets.append((
            "07_manuscript/independent_publishability_review.md",
            project / "07_manuscript/independent_publishability_review.md",
        ))
        rec = latest(project, "manuscript")
        if rec and rec.get("report") and rec["report"].get("path"):
            rel = str(rec["report"]["path"])
            targets.append((rel, project / rel))
    elif stage_id == "S24_package_human_review":
        rec = latest(project, "package")
        if rec and rec.get("report") and rec["report"].get("path"):
            rel = str(rec["report"]["path"])
            targets.append((rel, project / rel))
        else:
            return ["no attached package independent review report to verify Discussion audit"]
    elif stage_id == "S25_submission_audit":
        freeze_path = project / "08_submission/package_review_freeze.json"
        audit_path = project / "08_submission/independent_submission_audit.md"
        if freeze_path.is_file() and audit_path.is_file():
            try:
                freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
                audit_txt = audit_path.read_text(encoding="utf-8", errors="replace")
                amendment = freeze.get("presentation_approval", {})
                freeze_id = str(freeze.get("freeze_id", "")).strip()
                if freeze_id and freeze_id not in audit_txt and amendment:
                    rev_path = project / f".wf/revisions/{amendment.get('round', '')}.json"
                    if rev_path.is_file():
                        rev = json.loads(rev_path.read_text(encoding="utf-8"))
                        if (
                            rev.get("status") == "complete"
                            and rev.get("validation", {}).get("ok")
                            and rev.get("content_classification", {}).get("class") == "presentation"
                        ):
                            return []
            except (OSError, json.JSONDecodeError):
                pass
        targets.append(("08_submission/independent_submission_audit.md", audit_path))

    problems: list[str] = []
    for label, path in targets:
        if not path.is_file():
            problems.append(f"{label} missing")
            continue
        problems.extend(
            audit_report_discussion_problems(path.read_text(encoding="utf-8", errors="replace"), label)
        )
    return problems
