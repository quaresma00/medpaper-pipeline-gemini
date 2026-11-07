"""Bind reported results to specific executed result objects, not a global number bag.

Labels and numerical correspondence are deterministic. Clinical meaning and whether the
analysis itself is valid still require the existing scientific and reader reviews.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

from .packagefreeze import _safe_path

CONTEXT_KEYS = {"outcome", "population", "comparison", "model", "timepoint", "unit", "denominator"}
PROSE_CONTEXT_KEYS = {"population", "comparison", "model", "timepoint"}

# Controlled effect-measure and summary-scale families.
# Short abbreviations ("OR", "HR", "RR", etc.) MUST match case-sensitively so ordinary
# English conjunctions such as "or" are never misread as an odds ratio.
MEASURE_FAMILIES: dict[str, dict[str, tuple[str, ...]]] = {
    "hazard_ratio": {
        "phrases": (
            "subdistribution hazard ratio", "subdistribution hazard ratios",
            "cause-specific hazard ratio", "cause-specific hazard ratios",
            "cox hazard ratio", "cox hazard ratios",
            "hazard ratio", "hazard ratios",
        ),
        "abbr": ("aHR", "sHR", "csHR", "HRs", "HR"),
    },
    "odds_ratio": {
        "phrases": ("adjusted odds ratio", "crude odds ratio", "odds ratio", "odds ratios"),
        "abbr": ("aOR", "cOR", "ORs", "OR"),
    },
    "risk_ratio": {
        "phrases": (
            "adjusted risk ratio", "relative risk", "relative risks",
            "risk ratio", "risk ratios", "prevalence ratio", "prevalence ratios",
        ),
        "abbr": ("aRR", "RRs", "RR", "aPR", "PR"),
    },
    "rate_ratio": {
        "phrases": (
            "incidence rate ratio", "incidence rate ratios",
            "rate ratio", "rate ratios",
        ),
        "abbr": ("aIRR", "IRRs", "IRR"),
    },
    "risk_difference": {
        "phrases": (
            "absolute risk reduction", "absolute risk difference",
            "risk difference", "risk differences",
        ),
        "abbr": ("ARD", "ARR", "RD"),
    },
    "mean_difference": {
        "phrases": (
            "between-group difference", "difference in means",
            "adjusted difference", "mean difference", "mean differences",
        ),
        "abbr": ("MD",),
    },
    "standardized_mean_difference": {
        "phrases": (
            "standardized mean difference", "standardised mean difference",
            "standardized difference", "standardised difference",
        ),
        "abbr": ("SMD", "ASD"),
    },
    "auc": {
        "phrases": (
            "area under the receiver operating characteristic curve",
            "area under the roc curve", "area under the curve",
            "concordance statistic", "concordance index",
            "c-statistic", "c-index",
        ),
        "abbr": ("AUROC", "AUC"),
    },
    "correlation": {
        "phrases": (
            "pearson correlation", "spearman correlation",
            "correlation coefficient",
        ),
        "abbr": (),
    },
}

UNIT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "years": ("year", "years", "yr", "yrs"),
    "year": ("year", "years", "yr", "yrs"),
    "months": ("month", "months", "mo", "mos"),
    "month": ("month", "months", "mo", "mos"),
    "weeks": ("week", "weeks", "wk", "wks"),
    "week": ("week", "weeks", "wk", "wks"),
    "days": ("day", "days"),
    "day": ("day", "days"),
    "hours": ("hour", "hours", "hr", "hrs"),
    "hour": ("hour", "hours", "hr", "hrs"),
    "percent": ("percent", "percentage", "%"),
    "percentage": ("percent", "percentage", "%"),
}

_EXEMPT_UNIT_RE = re.compile(
    r"^\s*(?:counts?|n|number(?:\s+of\s+\w+)?|events?|patients?|participants?|"
    r"subjects?|observations?|reports?|cases?|records?|episodes?|admissions?|"
    r"proportion|percentage|percent|%|dimensionless|none)"
    r"(?:\s*(?:,?\s*n\s*\(%\)|\(%\)))?\s*$",
    re.I,
)
_GROUP_TAG_RE = re.compile(
    r"\b(group|arm|cohort|stratum|strata|quartile|quintile|tertile|tier|stage|grade|phase|visit|wave)"
    r"\s+([A-Za-z0-9]+)\b",
    re.I,
)
_DURATION_TAG_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*[-\s]?(year|yr|month|mo|week|wk|day|hour|hr)s?\b",
    re.I,
)
_CI_LEVEL_RE = re.compile(
    r"(?<![\d.])(\d{2}(?:\.\d+)?)\s*%\s*(?:CI|confidence\s+intervals?)\b",
    re.I,
)
_P_ONLY_HEADER_RE = re.compile(
    r"^\s*(?:adjusted\s+|crude\s+|two-sided\s+|p\s+for\s+\w+\s*)?"
    r"(?:p(?:\s*[-–]?\s*value)?|q(?:\s*[-–]?\s*value)?|fdr)\s*$",
    re.I,
)
_COUNT_ONLY_HEADER_RE = re.compile(
    r"^\s*(?:n|no\.?|number|events?|cases?|total|participants?|patients?)\s*(?:\([^)]*\))?\s*$",
    re.I,
)


def fingerprint(value):
    """Semantic finding/text identity, not the binary identity of unrelated export rows."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode("utf-8")).hexdigest()


def pointer(document, location):
    if not isinstance(location, str) or (location and not location.startswith("/")):
        raise ValueError("source pointer must use JSON Pointer syntax")
    for token in location.split("/")[1:] if location else []:
        token = token.replace("~1", "/").replace("~0", "~")
        document = document[int(token)] if isinstance(document, list) else document[token]
    return document


def measure_families(text: str) -> set[str]:
    """Return canonical effect-measure families explicitly named in `text`."""
    if not text:
        return set()
    work = str(text)
    found: set[str] = set()
    phrase_items = sorted(
        ((fam, phrase) for fam, spec in MEASURE_FAMILIES.items() for phrase in spec["phrases"]),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for fam, phrase in phrase_items:
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(phrase) + r"(?![A-Za-z0-9])", re.I)
        if pat.search(work):
            found.add(fam)
            work = pat.sub(" ", work)
    abbr_items = sorted(
        ((fam, abbr) for fam, spec in MEASURE_FAMILIES.items() for abbr in spec["abbr"]),
        key=lambda item: len(item[1]),
        reverse=True,
    )
    for fam, abbr in abbr_items:
        pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(abbr) + r"(?![A-Za-z0-9])")
        if pat.search(work):
            found.add(fam)
            work = pat.sub(" ", work)
    return found


def _unit_is_exempt(value: str) -> bool:
    if _not_applicable(value):
        return True
    cleaned = str(value or "").strip()
    if not cleaned:
        return False
    if _EXEMPT_UNIT_RE.match(cleaned):
        return True
    if "(%)" in cleaned and not measure_families(cleaned):
        return True
    return False


def _unit_matches(expected: str, anchor: str) -> bool:
    if not expected or not anchor:
        return False
    if _phrase(expected, anchor):
        return True
    exp_fams = measure_families(expected)
    anc_fams = measure_families(anchor)
    if exp_fams and anc_fams:
        return bool(anc_fams <= exp_fams)
    key = expected.strip().casefold()
    for syn in UNIT_SYNONYMS.get(key, ()):
        if syn == "%":
            if "%" in anchor:
                return True
        elif _phrase(syn, anchor):
            return True
    return False


def _expected_interval_level(fact: dict) -> float:
    raw = fact["context"].get("interval_level", fact["values"].get("interval_level"))
    if raw is None or raw == "":
        return 95.0
    if isinstance(raw, str):
        cleaned = raw.strip().rstrip("%").strip()
        val = float(cleaned)
    else:
        val = float(raw)
    if 0 < val < 1:
        val *= 100.0
    return val


def _check_interval_level(fact_key: str, fact: dict, text_snippet: str) -> None:
    expected = _expected_interval_level(fact)
    shown_levels = [float(m.group(1)) for m in _CI_LEVEL_RE.finditer(text_snippet or "")]
    for level in shown_levels:
        if abs(level - expected) > 1e-6:
            raise ValueError(
                f"{fact_key}: confidence interval level {level:g}% does not match source interval level {expected:g}%"
            )
    if not shown_levels and abs(expected - 95.0) > 1e-6:
        if re.search(r"\b(?:CI|confidence\s+intervals?)\b", text_snippet or "", re.I):
            raise ValueError(
                f"{fact_key}: non-95% source interval ({expected:g}%) must state its explicit interval level"
            )


def facts(project):
    data = json.loads((project / "01_protocol/study_facts.json").read_text(encoding="utf-8"))
    catalog = data.get("numeric_facts")
    if not isinstance(catalog, dict) or not catalog:
        raise ValueError("study_facts.numeric_facts must bind reported findings to executed result objects")
    resolved, documents = {}, {}
    for key, row in catalog.items():
        rel, path = _safe_path(project, row["source"])
        if not rel.startswith("03_analysis/results/") or path.suffix != ".json":
            raise ValueError(f"{key}: source must be executed analysis JSON")
        if rel not in documents:
            documents[rel] = json.loads(path.read_text(encoding="utf-8"))
        result = pointer(documents[rel], row["pointer"])
        context = result["context"]
        if (not isinstance(context, dict) or not CONTEXT_KEYS <= context.keys() or
                any(not isinstance(context[k], str) or not context[k].strip() for k in CONTEXT_KEYS)):
            raise ValueError(f"{key}: source needs explicit outcome/population/comparison/model/timepoint/unit/denominator")
        if row.get("context") != context:
            raise ValueError(f"{key}: fact context differs from its analysis source")
        values = result["values"]
        if not isinstance(values, dict) or not values:
            raise ValueError(f"{key}: source has no named numerical values")
        resolved[key] = {"context": context, "values": values,
                         "source": rel, "pointer": row["pointer"]}
        resolved[key]["fingerprint"] = fingerprint(resolved[key])
    return resolved


def _binding_payload(project: Path, rel: str) -> tuple[str, dict]:
    location = ("08_submission/integration/claim_bindings.json" if rel.startswith("08_submission/")
                else "07_manuscript/claim_bindings.json")
    payload = json.loads((project / location).read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("claims"), list):
        raise ValueError(f"{location}: invalid claims schema")
    return location, payload


def bindings(project, rel):
    _, payload = _binding_payload(project, rel)
    return payload["claims"]


def figure_bindings(project: Path, rel: str = "05_figures/out") -> list[dict]:
    location = ("08_submission/integration/claim_bindings.json" if rel.startswith("08_submission/")
                else "07_manuscript/claim_bindings.json")
    path = project / location
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("figure_annotations", [])
    if not isinstance(rows, list):
        raise ValueError(f"{location}: figure_annotations must be a list")
    return rows


def claim_values(claim, catalog, label_text):
    from .checks.numbers import _walk
    strings = set()
    p_values = set()
    ids = claim.get("fact_ids", [])
    if not isinstance(ids, list) or not ids:
        raise ValueError("claim has no fact_ids")
    for key in ids:
        fact = catalog[key]
        # Require the source's actual outcome label, not an unrelated endpoint sharing a number.
        from .clinicalpresentation import label as clinical_label
        label = fact["context"]["outcome"]
        if claim.get("_project") is not None:
            label = clinical_label(label, claim["_project"])
        if label.casefold() not in label_text.casefold():
            raise ValueError(f"{key}: outcome label {label!r} missing from the bound text/label cells")
        _walk(fact["values"], strings)
        for name, value in fact["values"].items():
            if name.casefold() in {"p", "p_value", "pvalue", "adjusted_p", "q_value"}:
                p_values.add(float(value))
    return {float(s) for s in strings}, strings, p_values


def results_text(text, rel, *, include_discussion: bool = False):
    if "full_manuscript" not in rel:
        return text
    # Only our study's quantitative summary/results (and Discussion own-study claims when
    # active) require bindings here. Cited prior-study numbers use source_claims instead.
    chapters = {"abstract", "results"} | ({"discussion"} if include_discussion else set())
    matches = list(re.finditer(r"^#\s+(.+?)\s*$", text, re.M))
    parts = []
    for i, heading in enumerate(matches):
        if heading.group(1).casefold() in chapters:
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            parts.append(text[heading.start():end])
    return "\n\n".join(parts)


def _phrase(value, text):
    value = re.sub(r"\s+", " ", value).strip()
    text = re.sub(r"\s+", " ", text)
    return bool(value and re.search(r"(?<!\w)" + re.escape(value) + r"(?!\w)", text, re.I))


def _section_scopes(text, rel, quote, *, include_discussion: bool = False):
    if "full_manuscript" not in rel:
        return [text]
    chapters = {"abstract", "results"} | ({"discussion"} if include_discussion else set())
    headings = list(re.finditer(r"^#\s+(.+?)\s*$", text, re.M))
    scopes = []
    for i, heading in enumerate(headings):
        if heading[1].casefold() in chapters:
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            section = text[heading.end():end]
            if quote in section:
                scopes.append(section)
    return scopes


def _outline(text):
    """Actual heading paths and direct introductions, not the first word 'Results'."""
    rows, stack = [], []
    matches = list(re.finditer(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", text, re.M))
    for i, match in enumerate(matches):
        level = len(match[1])
        while stack and rows[stack[-1]]["level"] >= level:
            stack.pop()
        row = {"level": level, "path": [rows[j]["title"] for j in stack] + [match[2]],
               "title": match[2], "start": match.start(), "content": match.end(),
               "end": matches[i + 1].start() if i + 1 < len(matches) else len(text),
               "ancestors": list(stack)}
        rows.append(row)
        stack.append(i)
    return rows


def _locate_claim(body, quote, claim, outline):
    """One current occurrence; sibling/other-summary text is not inherited context."""
    section = claim.get("section")
    if section is not None and (not isinstance(section, list) or not section or
                                any(not isinstance(x, str) or not x.strip() for x in section)):
        raise ValueError("claim section must be an actual nonempty Markdown heading path")
    found = []
    for match in re.finditer(re.escape(quote), body):
        preceding = [i for i, row in enumerate(outline) if row["start"] <= match.start()]
        node = outline[preceding[-1]] if preceding else None
        # A real parent heading is a valid locator scope. Assembly adds the chapter
        # around component subsections; the unique occurrence keeps its leaf context.
        if section is not None and (node is None or node["path"][:len(section)] != section):
            continue
        pieces = []
        if node:
            pieces.extend(body[outline[j]["start"]:outline[j]["end"]] for j in node["ancestors"])
            pieces.append(body[node["start"]:match.end()])
        else:
            pieces.append(body[:match.end()])
        found.append((match.start(), match.end(), "\n\n".join(pieces)))
    occurrence = claim.get("occurrence")
    if occurrence is not None:
        if isinstance(occurrence, bool) or not isinstance(occurrence, int) or occurrence < 1 or occurrence > len(found):
            raise ValueError("claim occurrence must identify an actual 1-based occurrence inside its section")
        found = [found[occurrence - 1]]
    if len(found) != 1:
        raise ValueError("claim text is missing or ambiguous; bind each occurrence with its actual section/occurrence instead of certifying repeated sentences together")
    return found[0]


def _not_applicable(value):
    # Only an explicit, explained source assertion; "none"/unknown is not N/A.
    return bool(re.match(r"^\s*(?:n/?a\b|not applicable\b)", value, re.I) and len(value.strip()) >= 30)


def _check_prose_measure_and_unit(key, fact, all_facts, quote, scopes, label_lookup,
                                  alternatives_by_field, observations, *, unit_required: bool):
    _check_interval_level(key, fact, quote)
    raw_unit = fact["context"]["unit"]
    expected_unit = label_lookup(raw_unit)
    exp_fams = measure_families(expected_unit) | measure_families(raw_unit)
    all_exp_fams = set()
    for other_fact in all_facts:
        u = other_fact["context"]["unit"]
        all_exp_fams |= measure_families(u) | measure_families(label_lookup(u))
    quote_fams = measure_families(quote)
    if exp_fams and quote_fams and not (quote_fams & exp_fams) and not (quote_fams <= all_exp_fams):
        raise ValueError(
            f"{key}: measure/unit label in claim conflicts with source unit {expected_unit!r}"
        )
    if not all_exp_fams and quote_fams:
        raise ValueError(
            f"{key}: claim states effect measure {sorted(quote_fams)[0]!r} for non-effect source unit {expected_unit!r}"
        )
    unit_alts = (alternatives_by_field or {}).get("unit", set())
    expected_words = set(re.findall(r"\w+", expected_unit.casefold()))
    attributed = quote + "\n" + "\n".join(re.findall(r"^\s{0,3}#{1,6}\s+(.+)$", scopes[0], re.M))
    foreign_units = [
        term for term in unit_alts
        if _phrase(term, attributed)
        and not set(re.findall(r"\w+", term.casefold())) <= expected_words
        and not _unit_matches(expected_unit, term)
    ]
    if foreign_units and not _unit_matches(expected_unit, quote):
        raise ValueError(
            f"{key}: unit text names another exported unit {foreign_units[0]!r}; resolve the measure/unit attribution"
        )
    if unit_required and "unit" not in observations:
        if not _unit_is_exempt(raw_unit) and not _unit_is_exempt(expected_unit):
            if not _unit_matches(expected_unit, quote):
                raise ValueError(
                    f"{key}: unit/measure {expected_unit!r} missing from claim; state an accurate measure/unit label "
                    f"(or valid abbreviation) or bind section context in observations['unit']"
                )


def validate_context(project, rel, text, claim, catalog, *, required, label_lookup=None,
                     context_scope=None, alternatives_by_field=None,
                     include_discussion: bool = False, unit_required: bool = False):
    """Bind a scoped executor read-back to the real finding and current prose.

    Literal evidence is checked mechanically. Nonliteral meaning requires an actual,
    substantive executor observation; it is not certified by this numeric gate and is
    still read by the existing S18/S25 reviewer. No independent review is invented here.
    """
    ids = claim.get("fact_ids", [])
    from .clinicalpresentation import label as clinical_label
    label_lookup = label_lookup or (lambda value: clinical_label(value, project))
    quote = claim["text"]
    scopes = ([context_scope] if context_scope is not None
              else _section_scopes(text, rel, quote, include_discussion=include_discussion))
    evidence = claim.get("context_evidence")
    if evidence is None and not required:
        return
    if not isinstance(evidence, dict) or set(evidence) != set(ids):
        raise ValueError("claim context_evidence must bind its own fact_ids; use actual same-sentence/section context, not repeated boilerplate")
    if not scopes:
        raise ValueError("claim has no current Abstract/Results/Discussion context")
    all_facts = [catalog[k] for k in ids]
    for key in ids:
        fact = catalog[key]
        item = evidence[key]
        if not isinstance(item, dict) or item.get("fact_fingerprint") != fact["fingerprint"] or item.get("claim_fingerprint") != fingerprint(quote):
            raise ValueError(f"{key}: stale/missing fact or claim context fingerprint; read the affected finding and current text again")
        observations = item.get("observations")
        applicable = {field for field in PROSE_CONTEXT_KEYS if not _not_applicable(fact["context"][field])}
        if not isinstance(observations, dict) or not applicable <= observations.keys() or set(observations) - CONTEXT_KEYS:
            raise ValueError(f"{key}: context read-back needs applicable population/comparison/model/timepoint observations; source-explained N/A is allowed")
        _check_prose_measure_and_unit(
            key, fact, all_facts, quote, scopes, label_lookup,
            alternatives_by_field, observations, unit_required=unit_required,
        )
        for field, observed in observations.items():
            expected = label_lookup(fact["context"][field])
            # A known alternative exported context is not a free synonym. Inspect only
            # this same claim, not unrelated paragraphs or another study's vocabulary.
            alternatives = alternatives_by_field[field] if alternatives_by_field is not None else {
                label_lookup(other["context"][field]) for other in catalog.values()
                if not _not_applicable(other["context"][field])}
            expected_words = set(re.findall(r"\w+", expected.casefold()))
            attributed_text = quote + "\n" + "\n".join(re.findall(r"^\s{0,3}#{1,6}\s+(.+)$", scopes[0], re.M))
            matcher = _unit_matches if field == "unit" else _phrase
            foreign = [term for term in alternatives if _phrase(term, attributed_text) and
                       not set(re.findall(r"\w+", term.casefold())) <= expected_words and
                       not (field == "unit" and _unit_matches(expected, term))]
            if foreign and not matcher(expected, quote):
                raise ValueError(f"{key}: {field} text names another exported context {foreign[0]!r}; resolve the finding/text attribution")
            if isinstance(observed, str):
                if not observed.strip() or observed not in quote or not matcher(expected, observed):
                    raise ValueError(f"{key}: {field} literal evidence does not align the current claim with source context {expected!r}")
                continue
            if not isinstance(observed, dict):
                raise ValueError(f"{key}: {field} needs literal evidence or a scoped executor read-back")
            mode = observed.get("mode")
            if mode in {"pending", "needs_review", "unknown"}:
                raise ValueError(f"{key}: {field} context remains pending; complete the existing executor/author scientific judgement")
            if mode == "not_applicable":
                ok_na = (_unit_is_exempt(fact["context"][field]) if field == "unit"
                         else _not_applicable(fact["context"][field]))
                if not ok_na or len(str(observed.get("reason", "")).strip()) < 30:
                    raise ValueError(f"{key}: {field} N/A must be explained by the actual analysis source")
                continue
            anchor = observed.get("quote", "")
            scope = observed.get("scope", "claim")
            if not isinstance(anchor, str) or not anchor.strip() or scope not in {"claim", "section"}:
                raise ValueError(f"{key}: {field} needs an exact current-context quote and claim/section scope")
            if scope == "claim":
                present = anchor in quote
            else:
                # A section anchor must actually precede or occur in this finding in
                # every matching scope; Abstract context cannot certify main Results.
                present = all(anchor in part[:part.rindex(quote) + len(quote)] for part in scopes)
            if not present:
                raise ValueError(f"{key}: {field} context anchor is absent, later than the finding or belongs to another section")
            if mode == "literal":
                if not matcher(expected, anchor):
                    raise ValueError(f"{key}: {field} literal context differs from source {expected!r}")
            elif mode == "read_back":
                interpretation = str(observed.get("interpretation", "")).strip()
                reason = str(observed.get("reason", "")).strip()
                if (observed.get("reviewer") != "executor" or len(interpretation) < 30 or len(reason) < 60 or
                        interpretation.casefold() in {anchor.casefold(), expected.casefold()} or
                        reason.casefold() in {anchor.casefold(), expected.casefold(), interpretation.casefold()}):
                    raise ValueError(f"{key}: {field} needs an actual executor interpretation and source-based reasoning, not a copied field or PASS assertion")
            else:
                raise ValueError(f"{key}: {field} unsupported context observation mode; unresolved meaning stays pending")


def _has_discussion_bindings(rows: list[dict], rel: str) -> bool:
    for r in rows:
        if r.get("path") == "07_manuscript/discussion.md":
            return True
        sec = r.get("section")
        if r.get("path") == rel and isinstance(sec, list) and sec and str(sec[0]).casefold() == "discussion":
            return True
    return False


def validate_prose(project, rel, text, *, already_masked: bool = False):
    from .checks.numbers import _offenders, _scrub, NUM_RE
    from .state import State, version_tuple
    is_discussion_file = rel.endswith("discussion.md")
    relevant = rel.endswith(("results.md", "abstract.md", "full_manuscript.md")) or is_discussion_file
    if not relevant:
        return []
    state_file = project / ".wf/state.json"
    state = State(project).load().data if state_file.is_file() else {}
    pin = version_tuple(str(state.get("engine_pin", state.get("pipeline_version", "0"))))
    strict_127 = pin >= (1, 27, 0)
    try:
        rows = bindings(project, rel) if (
            (project / ("08_submission/integration/claim_bindings.json" if rel.startswith("08_submission/")
                        else "07_manuscript/claim_bindings.json")).is_file()
        ) else None
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"{rel}: {exc}"]
    include_discussion = strict_127 or bool(rows and _has_discussion_bindings(rows, rel))
    if is_discussion_file and not include_discussion:
        return []
    if not already_masked and (is_discussion_file or "full_manuscript" in rel):
        from .sourceclaims import mask as mask_external
        masked, ext_problems = mask_external(project, rel, text)
        if ext_problems:
            return [f"{rel}: " + "; ".join(ext_problems[:4])]
        text = masked
    body = results_text(text, rel, include_discussion=include_discussion)
    if not NUM_RE.search(_scrub(body)):
        return []
    try:
        catalog = facts(project)
        if rows is None:
            rows = bindings(project, rel)
        context_required = pin >= (1, 26, 0)
        percentage_required = version_tuple(str(state.get("pipeline_version", "0"))) >= (1, 16, 0)
        label_cache = {}

        def context_label(value):
            from .clinicalpresentation import label as clinical_label
            if value not in label_cache:
                label_cache[value] = clinical_label(value, project)
            return label_cache[value]

        covered = list(body)
        outline = _outline(body)
        used_spans = set()
        alternatives_by_field = None
        count = 0
        for row in rows:
            if row.get("path") != rel:
                continue
            quote = row.get("text", "")
            if not isinstance(quote, str) or not quote.strip() or quote not in body:
                raise ValueError("claim text is missing or changed; update the affected binding")
            floats, strings, p_values = claim_values({**row, "_project": project}, catalog, quote)
            current_context = context_required or row.get("context_evidence") is not None
            if current_context:
                start, end, scope = _locate_claim(body, quote, row, outline)
                if any(start < prior_end and prior_start < end for prior_start, prior_end in used_spans):
                    raise ValueError("duplicate/overlapping bindings target the same claim occurrence")
                if alternatives_by_field is None:
                    alternatives_by_field = {field: {context_label(fact["context"][field]) for fact in catalog.values()
                                                     if not _not_applicable(fact["context"][field])}
                                             for field in CONTEXT_KEYS}
                validate_context(
                    project, rel, text, row, catalog,
                    required=context_required,
                    label_lookup=context_label,
                    context_scope=scope,
                    alternatives_by_field=alternatives_by_field,
                    include_discussion=include_discussion,
                    unit_required=strict_127,
                )
                spans = [(start, end)]
            else:
                for fid in row.get("fact_ids", []):
                    _check_interval_level(fid, catalog[fid], quote)
                spans = [(m.start(), m.end()) for m in re.finditer(re.escape(quote), body)]
            from .proportions import validate as validate_proportions
            proportion_errors = validate_proportions(row, catalog, quote, required=percentage_required)
            if proportion_errors:
                raise ValueError("; ".join(proportion_errors))
            bad = _offenders(quote, floats, strings, set(), p_values)
            if bad:
                raise ValueError(f"claim contains values absent from its own fact(s): {bad[:5]}")
            for start, end in spans:
                covered[start:end] = " " * (end - start)
                used_spans.add((start, end))
            count += 1
        if NUM_RE.search(_scrub("".join(covered))):
            raise ValueError("reported numeric text lacks a source-bound claim; bind each reported finding, not a whole section")
        if not count:
            raise ValueError("no result claims bound")
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        return [f"{rel}: {exc}"]
    return []


def table_unit_constants(project, path, sheet, cell, value):
    """Only a source-bound 'per N' unit in a real header/note, never result-cell amnesty."""
    if not re.search(r"\bper\s+[1-9]\d*", str(value), re.I):
        return set()
    from . import xlsxlite
    rel = path.relative_to(project).as_posix()
    rows = [r for r in bindings(project, rel) if r.get("path") == rel and r.get("sheet") == sheet and r.get("cell") == cell and r.get("kind") == "unit_scale"]
    if not rows:
        return set()
    if len(rows) != 1:
        raise ValueError("Duplicate unit-scale binding")
    row = rows[0]
    if row.get("text") != str(value) or len(str(row.get("reason", ""))) < 20:
        raise ValueError("Unit constant needs exact cell text and scientific unit rationale")
    book = xlsxlite.Workbook(path)
    sh = book.sheet(sheet)
    target = next(c for c in sh.cells if c.ref == cell)
    top = [c.row for c in sh.cells if book.border_of(c).top]
    bottom = [c.row for c in sh.cells if book.border_of(c).bottom]
    if not top or not bottom:
        raise ValueError("Unit constant needs a structured three-line table")
    header = max(r for r in bottom if r < max(bottom)) if len(set(bottom)) > 1 else min(top)
    if not (target.row <= header or target.row > max(bottom)):
        raise ValueError("Result-body cells cannot use a unit-constant exemption")
    source_rel, source = _safe_path(project, row.get("source_path", ""))
    quote = row.get("source_quote", "")
    if not source_rel.startswith(("01_protocol/", "03_analysis/code/")) or not isinstance(quote, str) or len(quote) < 20 or quote not in source.read_text(encoding="utf-8"):
        raise ValueError("Unit constant needs an exact source quote from the real protocol/producer")
    allowed = set(re.findall(r"\bper\s+([1-9]\d*(?:,\d{3})*)\b", str(value), re.I))
    source_units = {v.replace(",", "") for v in re.findall(r"\bper\s+([1-9]\d*(?:,\d{3})*)\b", quote, re.I)}
    normalized = {v.replace(",", "") for v in allowed}
    if not allowed or not normalized <= source_units:
        raise ValueError("Only explicit source-supported 'per N' unit scaling is permitted")
    from .checks.numbers import _scrub, NUM_RE
    remaining = re.sub(r"\bper\s+[1-9]\d*(?:,\d{3})*\b", " ", str(value), flags=re.I)
    if NUM_RE.search(_scrub(remaining)):
        raise ValueError("A unit binding cannot exempt other reported numbers, even if the value equals its unit scale")
    return allowed | normalized


def _strip_sample_size(text: str) -> str:
    cleaned = re.sub(r"\s*\([nN]\s*=\s*[^)]*\)", "", str(text or ""))
    return re.sub(r"\s+", " ", cleaned).strip(" ,;:|")


def _context_candidates(value: str) -> set[str]:
    out = set()
    for candidate in (value, _strip_sample_size(value)):
        c = candidate.strip()
        if len(c) >= 2:
            out.add(c)
    return out


def _group_tags(text: str) -> dict[str, set[str]]:
    tags: dict[str, set[str]] = {}
    for m in _GROUP_TAG_RE.finditer(text or ""):
        prefix = m.group(1).casefold().rstrip("s")
        if prefix == "stratu":
            prefix = "stratum"
        tags.setdefault(prefix, set()).add(m.group(2).casefold())
    for m in re.finditer(r"\bQ([1-5])\b", text or ""):
        tags.setdefault("quartile", set()).add(m.group(1))
    return tags


def _duration_tags(text: str) -> set[tuple[str, str]]:
    unit_map = {
        "yr": "year", "year": "year",
        "mo": "month", "month": "month",
        "wk": "week", "week": "week",
        "day": "day",
        "hr": "hour", "hour": "hour",
    }
    out = set()
    for m in _DURATION_TAG_RE.finditer(text or ""):
        num = str(float(m.group(1))).rstrip("0").rstrip(".")
        u = unit_map.get(m.group(2).casefold(), m.group(2).casefold())
        out.add((num, u))
    return out


def _model_adjustment_state(text: str) -> set[str]:
    states = set()
    if re.search(r"\b(?:unadjusted|crude)\b", text or "", re.I):
        states.add("unadjusted")
    if re.search(r"(?<![A-Za-z])(?:adjusted|multivariable|multivariate)\b", text or "", re.I):
        states.add("adjusted")
    return states


def _demographic_pole(text: str) -> set[str]:
    poles = set()
    if re.search(r"\b(?:adults?|elderly|older\s+adults?)\b", text or "", re.I):
        poles.add("adult")
    if re.search(r"\b(?:children|child|pediatric|paediatric|infants?|neonates?)\b", text or "", re.I):
        poles.add("pediatric")
    return poles


def _validate_table_cell_context(
    project: Path,
    xls_wb,
    workbook,
    sheet: str,
    cell: str,
    value: str,
    row: dict,
    catalog: dict,
    label_lookup,
    alternatives_by_field: dict[str, set[str]],
    *,
    strict_127: bool,
) -> None:
    col_headers = xls_wb.column_headers(sheet, cell)
    group_banner = xls_wb.row_group_header(sheet, cell)
    row_labels = [str(workbook[sheet][c].value or "") for c in row.get("label_cells", [])]
    extra_cells = [str(workbook[sheet][c].value or "") for c in row.get("context_cells", [])]
    header_text = " | ".join(col_headers)
    row_text = " | ".join([*row_labels, *([group_banner] if group_banner else []), *extra_cells])
    combined_ctx = " | ".join(x for x in (row_text, header_text) if x)

    ids = row.get("fact_ids", [])
    bound_facts = [catalog[k] for k in ids]

    # 1. Interval confidence-level check (e.g. 90% CI vs 95% CI).
    for key in ids:
        _check_interval_level(key, catalog[key], header_text + " " + str(value))

    # 2. Effect-measure / unit consistency between headers/labels and bound fact(s).
    leaf_header = col_headers[-1] if col_headers else ""
    is_p_col = bool(_P_ONLY_HEADER_RE.match(leaf_header))
    is_count_col = bool(_COUNT_ONLY_HEADER_RE.match(_strip_sample_size(leaf_header)))
    if not is_p_col and not is_count_col:
        header_fams = measure_families(header_text)
        cell_fams = header_fams or measure_families(row_text)
        expected_fams = set()
        for f in bound_facts:
            u = f["context"]["unit"]
            expected_fams |= measure_families(u) | measure_families(label_lookup(u))
        if cell_fams:
            if expected_fams and not (cell_fams & expected_fams):
                raise ValueError(
                    f"{sheet}!{cell}: table header/row measure {sorted(cell_fams)[0]!r} "
                    f"conflicts with fact unit {[f['context']['unit'] for f in bound_facts]!r}"
                )
            if not expected_fams:
                raise ValueError(
                    f"{sheet}!{cell}: table header/row declares effect measure {sorted(cell_fams)[0]!r} "
                    f"for non-effect fact unit {[f['context']['unit'] for f in bound_facts]!r}"
                )
        elif strict_127 and expected_fams and row.get("context_evidence") is None:
            shown_fams = measure_families(str(value))
            if not shown_fams or not (shown_fams & expected_fams):
                raise ValueError(
                    f"{sheet}!{cell}: effect-estimate cell requires an explicit matching measure label "
                    f"(e.g. HR/OR/RR) in its column/row header"
                )

    # 3. Sibling column-header cross-check: catch Group B fact placed under Group A column
    # even when study_facts.json only exports one of the groups.
    sh_obj = xls_wb.sheet(sheet)
    pos = xls_wb.sheet(sheet) and __import__("wfcore.xlsxlite", fromlist=["parse_cell_ref"]).parse_cell_ref(cell)
    sibling_headers: list[str] = []
    if sh_obj is not None and pos is not None:
        _, target_col = pos
        hdr_rows, _ = xls_wb.header_rows(sh_obj)
        for col_idx in range(1, sh_obj.max_col + 1):
            if col_idx == target_col:
                continue
            parts = []
            for hr in hdr_rows:
                t = _strip_sample_size(sh_obj.cell_text(hr, col_idx))
                if t and t not in parts:
                    parts.append(t)
            if parts:
                sibling_headers.extend(parts)

    all_fact_context_blob = " | ".join(
        f"{v} | {label_lookup(v)}"
        for f in bound_facts
        for k, v in f["context"].items()
        if isinstance(v, str) and not _not_applicable(v)
    )
    all_fact_words = set(re.findall(r"\w+", all_fact_context_blob.casefold()))

    current_col_clean = " | ".join(_strip_sample_size(h) for h in col_headers)
    for sib in sibling_headers:
        if len(sib) >= 2 and _phrase(sib, all_fact_context_blob) and not _phrase(sib, current_col_clean):
            if current_col_clean and not _phrase(current_col_clean, all_fact_context_blob) and not is_p_col:
                raise ValueError(
                    f"{sheet}!{cell}: bound fact belongs to sibling column {sib!r}, not {current_col_clean!r}"
                )

    # 4. Catalog alternative contexts & structural group/model/timepoint conflict checks.
    for field in ("population", "comparison", "model", "timepoint", "denominator"):
        exp_terms = set()
        for f in bound_facts:
            raw_v = f["context"][field]
            if not _not_applicable(raw_v):
                exp_terms |= _context_candidates(raw_v) | _context_candidates(label_lookup(raw_v))
        for alt in alternatives_by_field.get(field, set()):
            if _phrase(alt, combined_ctx):
                alt_words = set(re.findall(r"\w+", alt.casefold()))
                if not alt_words <= all_fact_words and not any(_phrase(et, combined_ctx) for et in exp_terms):
                    raise ValueError(
                        f"{sheet}!{cell}: table header/row names conflicting {field} context {alt!r}"
                    )

    cell_groups = _group_tags(combined_ctx)
    fact_groups = _group_tags(all_fact_context_blob)
    for prefix, cell_ids in cell_groups.items():
        if prefix in fact_groups and not (cell_ids & fact_groups[prefix]):
            raise ValueError(
                f"{sheet}!{cell}: {prefix} label {sorted(cell_ids)[0]!r} conflicts with fact context {sorted(fact_groups[prefix])[0]!r}"
            )

    cell_adj = _model_adjustment_state(combined_ctx)
    fact_adj = _model_adjustment_state(all_fact_context_blob)
    if len(cell_adj) == 1 and len(fact_adj) == 1 and cell_adj != fact_adj:
        raise ValueError(
            f"{sheet}!{cell}: table model label {next(iter(cell_adj))!r} conflicts with fact model {next(iter(fact_adj))!r}"
        )

    cell_demo = _demographic_pole(combined_ctx)
    fact_demo = _demographic_pole(all_fact_context_blob)
    if len(cell_demo) == 1 and len(fact_demo) == 1 and cell_demo != fact_demo:
        raise ValueError(
            f"{sheet}!{cell}: table population label {next(iter(cell_demo))!r} conflicts with fact population {next(iter(fact_demo))!r}"
        )

    cell_dur = _duration_tags(combined_ctx)
    fact_dur = _duration_tags(" | ".join(f["context"]["timepoint"] for f in bound_facts))
    if cell_dur and fact_dur and not (cell_dur & fact_dur):
        # Only flag when the same unit family or explicit follow-up timepoint conflicts,
        # avoiding row labels like "Age, years" colliding with "1-year follow-up".
        time_ctx = _duration_tags(header_text + " | " + group_banner)
        if time_ctx and not (time_ctx & fact_dur):
            raise ValueError(
                f"{sheet}!{cell}: table timepoint {sorted(time_ctx)[0]!r} conflicts with fact timepoint {sorted(fact_dur)[0]!r}"
            )


def validate_tables(project, paths):
    from . import xlsxlite
    from .checks.numbers import _offenders, _scrub, NUM_RE
    from openpyxl import load_workbook
    from .state import State, version_tuple
    state_file = project / ".wf/state.json"
    state = State(project).load().data if state_file.is_file() else {}
    pin = version_tuple(str(state.get("engine_pin", state.get("pipeline_version", "0"))))
    strict = pin >= (1, 26, 0)
    strict_127 = pin >= (1, 27, 0)
    problems = []
    catalog = None
    label_cache = {}

    def context_label(value):
        from .clinicalpresentation import label as clinical_label
        if value not in label_cache:
            label_cache[value] = clinical_label(value, project)
        return label_cache[value]

    alternatives_by_field = None
    for path in paths:
        rel = path.relative_to(project).as_posix()
        cells = [(s, c, v) for s, c, v in xlsxlite.numeric_cell_values(path) if NUM_RE.search(_scrub(str(v)))]
        if not cells:
            continue
        try:
            rows = [r for r in bindings(project, rel) if r.get("path") == rel]
            index = {(r.get("sheet"), r.get("cell")): r for r in rows}
            if len(index) != len(rows):
                raise ValueError("duplicate table-cell bindings")
            xls_wb = xlsxlite.Workbook(path)
            workbook = load_workbook(path, read_only=True, data_only=True)
            try:
                for sheet, cell, value in cells:
                    row = index.get((sheet, cell))
                    if row is None or row.get("text") != str(value):
                        raise ValueError(f"{sheet}!{cell}: missing/stale exact-value binding")
                    if row.get("kind") == "unit_scale":
                        allowed = table_unit_constants(project, path, sheet, cell, value)
                        if _offenders(str(value), set(), set(), allowed):
                            raise ValueError("Unit binding cannot hide additional result values")
                        continue
                    if catalog is None:
                        catalog = facts(project)
                        alternatives_by_field = {}
                        for field in CONTEXT_KEYS:
                            terms = set()
                            for f in catalog.values():
                                if not _not_applicable(f["context"][field]):
                                    terms |= _context_candidates(f["context"][field])
                                    terms |= _context_candidates(context_label(f["context"][field]))
                            alternatives_by_field[field] = terms
                    labels = " ".join(str(workbook[sheet][c].value or "") for c in row.get("label_cells", []))
                    col_hdrs = " ".join(xls_wb.column_headers(sheet, cell))
                    floats, strings, p_values = claim_values(
                        {**row, "_project": project},
                        catalog,
                        " ".join(x for x in (labels, col_hdrs, str(value)) if x),
                    )
                    if strict or row.get("context_cells") is not None or row.get("context_evidence") is not None:
                        _validate_table_cell_context(
                            project, xls_wb, workbook, sheet, cell, value, row,
                            catalog, context_label, alternatives_by_field,
                            strict_127=strict_127,
                        )
                    from .proportions import validate as validate_proportions, table_percentage_text
                    header = " ".join(xls_wb.column_headers(sheet, cell)) or workbook[sheet].cell(2, workbook[sheet][cell].column).value
                    shown = table_percentage_text(value, header)
                    issues = validate_proportions(row, catalog, shown, required=strict or bool(row.get("proportions")))
                    if issues:
                        raise ValueError(f"{sheet}!{cell}: " + "; ".join(issues))
                    if _offenders(str(value), floats, strings, set(), p_values):
                        raise ValueError(f"{sheet}!{cell}: value not from its own fact(s)")
            finally:
                workbook.close()
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            problems.append(f"{rel}: {exc}")
    return problems


# ---------------------------------------------------------------------------
# S11 explicit figure statistical annotation bindings (v1.27+)
# ---------------------------------------------------------------------------
_EXPLICIT_STAT_ABBR_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:a?HR|sHR|csHR|a?OR|cOR|a?RR|a?IRR|a?PR|ARD|ARR|RD|MD|SMD|ASD|AUC|AUROC)"
    r"\s*(?:[=:<>≤≥(]|\s*[+\-−]?\d)"
)
_EXPLICIT_STAT_PHRASE_RE = re.compile(
    r"\b(?:hazard\s+ratios?|odds\s+ratios?|risk\s+ratios?|relative\s+risks?|"
    r"incidence\s+rate\s+ratios?|rate\s+ratios?|mean\s+differences?|"
    r"area\s+under\s+the\s+(?:roc\s+)?curve|c-index|c-statistic|log-rank)\b",
    re.I,
)
_EXPLICIT_SAMPLE_RE = re.compile(r"\b[nN]\s*=\s*\d")
_EXPLICIT_CORR_RE = re.compile(r"(?<![A-Za-z0-9])[rR]\s*=\s*[+\-−]?(?:0?\.\d+|\d+\.\d+)")


def is_explicit_stat_annotation(text: str) -> bool:
    """True when rendered figure text displays an explicit statistical finding/count."""
    from .checks.numbers import _scrub, NUM_RE, P_RE
    raw = str(text or "").strip()
    if not raw or not NUM_RE.search(_scrub(raw)):
        return False
    if P_RE.search(raw):
        return True
    if _EXPLICIT_STAT_ABBR_RE.search(raw) or _EXPLICIT_STAT_PHRASE_RE.search(raw):
        return True
    if _EXPLICIT_SAMPLE_RE.search(raw) or _EXPLICIT_CORR_RE.search(raw):
        return True
    return False


def _verify_shown_field_value(raw_val, shown: str, digits: int | None, op: str | None) -> None:
    from .checks.numbers import normalize_grouping
    if isinstance(raw_val, bool) or not isinstance(raw_val, (int, float)):
        raise ValueError(f"target JSON field is not numeric: {raw_val!r}")
    actual = float(raw_val)
    cleaned = normalize_grouping(str(shown).strip()).replace("−", "-")
    ineq = re.fullmatch(r"([<>=≤≥])\s*(0?\.\d+(?:[eE][+\-]?\d+)?)", cleaned)
    if ineq or op in {"<", "<=", "≤", ">", ">=", "≥"}:
        symbol = ineq.group(1) if ineq else str(op)
        threshold = float(ineq.group(2) if ineq else cleaned)
        ok = (
            (0 <= actual < threshold) if symbol == "<" else
            (0 <= actual <= threshold) if symbol in {"<=", "≤"} else
            (actual > threshold) if symbol == ">" else
            (actual >= threshold)
        )
        if not ok:
            raise ValueError(f"threshold {symbol}{threshold} incompatible with source value {actual}")
        return
    shown_float = float(cleaned)
    if digits is not None:
        if isinstance(digits, bool) or not isinstance(digits, int) or digits < 0 or digits > 10:
            raise ValueError("digits must be an integer between 0 and 10")
        dec = Decimal(cleaned)
        shown_dp = max(0, -dec.as_tuple().exponent)
        if shown_dp != digits:
            raise ValueError(f"shown value {shown!r} has {shown_dp} decimal place(s), declared digits={digits}")
        if round(actual, digits) != round(shown_float, digits) and f"{actual:.{digits}f}" != f"{shown_float:.{digits}f}":
            raise ValueError(f"shown value {shown!r} does not match source {actual} at digits={digits}")
    else:
        dp = max(0, -Decimal(cleaned).as_tuple().exponent)
        if round(actual, dp) != shown_float and not (dp == 0 and abs(actual - shown_float) < 0.5 and actual != 0):
            raise ValueError(f"shown value {shown!r} does not match source {actual}")


def figure_annotations_fingerprint(project: Path, figure_id: str, *, journal: bool = False) -> str | None:
    rel_prefix = "08_submission/integration" if journal else "05_figures/out"
    rows = [r for r in figure_bindings(project, rel_prefix) if str(r.get("figure_id")) == str(figure_id)]
    if not rows:
        return None
    facts_file = project / "01_protocol/study_facts.json"
    catalog = facts(project) if facts_file.is_file() else {}
    bound_fps = {}
    for r in rows:
        if r.get("fact_id") in catalog:
            bound_fps[r["fact_id"]] = catalog[r["fact_id"]]["fingerprint"]
        field_list = r.get("fields") if isinstance(r.get("fields"), list) else (r.get("values") if isinstance(r.get("values"), list) else [])
        for fspec in field_list:
            if isinstance(fspec, dict) and fspec.get("fact_id") in catalog:
                bound_fps[fspec["fact_id"]] = catalog[fspec["fact_id"]]["fingerprint"]
    return fingerprint({"annotations": rows, "facts": bound_fps})


def validate_figure_entry(project: Path, entry: dict, art: dict | None = None, *,
                          require_complete: bool | None = None) -> tuple[list[str], str | None]:
    """Validate explicit statistical labels on one rendered figure against study_facts & JSON."""
    from .checks.numbers import _scrub, NUM_RE, P_RE, normalize_grouping
    from .state import State, version_tuple

    fid = str(entry.get("id", "?"))
    png_rel = str(entry.get("file") or entry.get("png") or "")
    journal = png_rel.startswith("08_submission/")
    if art is None:
        qc_dir = project / ("08_submission/integration/figure_qc" if journal else "05_figures/qc")
        sidecar = qc_dir / f"{Path(png_rel).stem}.artist.json"
        if not sidecar.is_file():
            return [f"{fid}: missing artist sidecar {sidecar.relative_to(project).as_posix()}"], None
        art = json.loads(sidecar.read_text(encoding="utf-8"))

    state_file = project / ".wf/state.json"
    state = State(project).load().data if state_file.is_file() else {}
    pin = version_tuple(str(state.get("engine_pin", state.get("pipeline_version", "0"))))
    strict_127 = pin >= (1, 27, 0)
    has_study_facts = (project / "01_protocol/study_facts.json").is_file()
    if require_complete is None:
        require_complete = strict_127 and has_study_facts

    try:
        all_rows = figure_bindings(project, png_rel or "05_figures/out")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"{fid}: {exc}"], None

    fig_rows = [r for r in all_rows if str(r.get("figure_id")) == fid]
    candidate_texts = set(art.get("non_tick_text") or art.get("figure_text") or [])
    all_rendered_texts = set(art.get("figure_text") or []) | candidate_texts
    explicit_texts = {t for t in candidate_texts if is_explicit_stat_annotation(t)}

    if not fig_rows and not require_complete:
        return [], None
    if not fig_rows and not explicit_texts:
        return [], fingerprint({"annotations": [], "facts": {}})

    problems: list[str] = []
    if require_complete and explicit_texts:
        mapped_texts = {str(r.get("text", "")).strip() for r in fig_rows}
        unmapped = sorted(explicit_texts - mapped_texts)
        if unmapped:
            problems.append(
                f"{fid}: unmapped explicit statistical figure text {unmapped[:3]!r}; "
                f"bind each label in claim_bindings.json figure_annotations"
            )
    if not fig_rows:
        return problems, None

    try:
        catalog = facts(project)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"{fid}: {exc}"], None

    from .clinicalpresentation import label as clinical_label
    seen_labels: set[str] = set()
    declared_sources = set(entry.get("source_results", []))
    documents: dict[str, dict] = {}

    for idx, r in enumerate(fig_rows, start=1):
        label_id = str(r.get("label_id") or f"ann_{idx}").strip()
        text = str(r.get("text", "")).strip()
        if label_id in seen_labels:
            problems.append(f"{fid}: duplicate figure annotation label_id {label_id!r}")
            continue
        seen_labels.add(label_id)
        if not text or text not in all_rendered_texts:
            problems.append(f"{fid} ({label_id}): bound text {text!r} absent from rendered figure_text")
            continue
        fields = r.get("fields") if r.get("fields") is not None else r.get("values")
        if not isinstance(fields, list) or not fields:
            problems.append(f"{fid} ({label_id}): fields must be a nonempty list of field mappings")
            continue

        involved_facts = []
        consumed_tokens: list[str] = []
        for fspec in fields:
            if not isinstance(fspec, dict):
                problems.append(f"{fid} ({label_id}): invalid field spec")
                continue
            fk = fspec.get("fact_id") or r.get("fact_id")
            src = fspec.get("source") or r.get("source")
            ptr = fspec.get("pointer") or r.get("pointer")
            fname = fspec.get("field")
            raw_shown = fspec.get("shown") if fspec.get("shown") is not None else fspec.get("reported", "")
            shown = str(raw_shown).strip()
            if not fk or fk not in catalog:
                problems.append(f"{fid} ({label_id}): unknown fact_id {fk!r}")
                continue
            fact = catalog[fk]
            involved_facts.append((fk, fact))
            if src != fact["source"] or ptr != fact["pointer"]:
                problems.append(
                    f"{fid} ({label_id}): source/pointer {src!r}{ptr!r} does not match fact {fk!r}"
                )
                continue
            if declared_sources and src not in declared_sources:
                problems.append(
                    f"{fid} ({label_id}): annotation source {src!r} not declared in figure source_results"
                )
                continue
            if src not in documents:
                _, spath = _safe_path(project, src)
                documents[src] = json.loads(spath.read_text(encoding="utf-8"))
            target_obj = pointer(documents[src], ptr)
            vals = target_obj.get("values", {}) if isinstance(target_obj, dict) else {}
            if fname not in vals:
                problems.append(f"{fid} ({label_id}): field {fname!r} missing from {src}{ptr}/values")
                continue
            if not shown or shown not in text:
                problems.append(f"{fid} ({label_id}): shown value {shown!r} absent from annotation text {text!r}")
                continue
            try:
                _verify_shown_field_value(vals[fname], shown, fspec.get("digits"), fspec.get("op"))
            except ValueError as exc:
                problems.append(f"{fid} ({label_id}.{fname}): {exc}")
                continue
            for m in NUM_RE.finditer(normalize_grouping(shown)):
                consumed_tokens.append(m.group(1).replace("−", "-"))

        if involved_facts:
            try:
                for fk, fact in involved_facts:
                    _check_interval_level(fk, fact, text)
            except ValueError as exc:
                problems.append(f"{fid} ({label_id}): {exc}")
            txt_fams = measure_families(text)
            exp_fams = set()
            for _, fact in involved_facts:
                u = fact["context"]["unit"]
                exp_fams |= measure_families(u) | measure_families(clinical_label(u, project))
            if txt_fams and exp_fams and not (txt_fams <= exp_fams):
                problems.append(
                    f"{fid} ({label_id}): annotation measure {sorted(txt_fams)[0]!r} "
                    f"conflicts with fact unit(s) {[f['context']['unit'] for _, f in involved_facts]!r}"
                )
            elif txt_fams and not exp_fams:
                problems.append(
                    f"{fid} ({label_id}): annotation states measure {sorted(txt_fams)[0]!r} "
                    f"for non-effect fact unit(s)"
                )

        # Ensure every numeric token in the scrubbed annotation text was explicitly mapped.
        scrubbed = _scrub(text)
        scrubbed = P_RE.sub(lambda m: " " + m.group(2) + " ", scrubbed)
        remaining = [m.group(1).replace("−", "-") for m in NUM_RE.finditer(scrubbed)]
        pool = list(consumed_tokens)
        unaccounted = []
        for tok in remaining:
            if tok in pool:
                pool.remove(tok)
            else:
                unaccounted.append(tok)
        if unaccounted:
            problems.append(
                f"{fid} ({label_id}): unmapped numeric token(s) {unaccounted!r} in annotation {text!r}"
            )

    fp = figure_annotations_fingerprint(project, fid, journal=journal) if not problems else None
    return problems, fp


def validate_figures(project: Path, *, journal: bool = False) -> list[str]:
    plan_rel = "08_submission/integration/artifact_plan.json" if journal else "01_protocol/artifact_plan.json"
    plan_path = project / plan_rel
    if not plan_path.is_file():
        return [f"{plan_rel} missing"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    entries = list(plan.get("main_figures", [])) + list(plan.get("supp_figures", []))
    problems: list[str] = []
    for entry in entries:
        errs, _ = validate_figure_entry(project, entry, require_complete=True)
        problems.extend(errs)
    return problems


def copy_for_journal(project):
    """Bind unchanged initial journal prose and figure annotations; never overwrite an existing mapping."""
    from .readiness import atomic_json
    source = project / "07_manuscript/claim_bindings.json"
    destination = project / "08_submission/integration/claim_bindings.json"
    if not source.is_file() or destination.exists():
        return
    original = json.loads(source.read_text(encoding="utf-8"))
    rows = [
        {**r, "path": r["path"].replace("07_manuscript/", "08_submission/integration/", 1)}
        for r in original["claims"]
        if r.get("path") == "07_manuscript/full_manuscript.md"
    ]
    external = [
        {**r, "path": r["path"].replace("07_manuscript/", "08_submission/integration/", 1)}
        for r in original.get("source_claims", [])
        if r.get("path") == "07_manuscript/full_manuscript.md"
    ]
    payload = {"schema_version": 1, "claims": rows, "source_claims": external}
    if "figure_annotations" in original:
        payload["figure_annotations"] = json.loads(json.dumps(original["figure_annotations"]))
    atomic_json(destination, payload)


def assembled_bindings(project, text):
    path = project / "07_manuscript/claim_bindings.json"
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    original = [r for r in payload["claims"] if r.get("path") != "07_manuscript/full_manuscript.md"]
    seen, assembled = set(), []
    chapter_map = {
        "07_manuscript/abstract.md": "Abstract",
        "07_manuscript/results.md": "Results",
        "07_manuscript/discussion.md": "Discussion",
    }
    for row in original:
        chapter = chapter_map.get(row.get("path"))
        if not chapter:
            continue
        if row.get("text") and row["text"] in text:
            current = row.get("context_evidence") is not None
            key = json.dumps([row["text"], row.get("fact_ids"),
                              row.get("path") if current else None,
                              row.get("section") if current else None,
                              row.get("occurrence") if current else None], sort_keys=True)
            if key not in seen:
                derived = {**row, "path": "07_manuscript/full_manuscript.md"}
                if current:
                    section = row.get("section", [])
                    derived["section"] = section if section and section[0] == chapter else [chapter] + section
                assembled.append(derived)
                seen.add(key)
    external = [r for r in payload.get("source_claims", []) if r.get("path") != "07_manuscript/full_manuscript.md"]
    derived = [{**r, "path": "07_manuscript/full_manuscript.md"} for r in external if r.get("text") and r["text"] in text]
    return {**payload, "schema_version": 1, "claims": original + assembled, "source_claims": external + derived}
