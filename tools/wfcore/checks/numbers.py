"""Numeric provenance.

Rule enforced here: a number may appear in the manuscript or in a table only if
executed code already wrote it to 03_analysis/results/*.json. This is what stops
plausible-looking statistics from being invented during writing.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal

from .. import xlsxlite
from . import Ctx, Result, check

RESULTS_GLOB = "03_analysis/results/*.json"
ALLOWLIST = "03_analysis/results/number_allowlist.tsv"

# Numbers that are conventions rather than findings.
CONVENTIONS = set()  # A small estimate or denominator is still a scientific finding.

CITE_RE = re.compile(r"\[@[^\]]*\]")
FENCE_RE = re.compile(r"```.*?```", re.S)
ARTIFACT_RE = re.compile(
    r"\b(?:supplementary\s+)?(?:fig(?:ure)?s?|tables?|panels?|appendix|eq(?:uation)?s?)\.?\s*"
    r"[A-Za-z]?\d+[A-Za-z]?(?:\s*[-,and]+\s*[A-Za-z]?\d+[A-Za-z]?)*",
    re.I,
)
NUM_RE = re.compile(r"(?<![\w.])([+\-−]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?)(?![\w])")
P_RE = re.compile(r"\b[Pp]\s*([<>=≤≥])\s*(0?\.\d+(?:[eE][+-]?\d+)?)\b")


def normalize_grouping(text):
    # Strict three-digit groups only: never merge a comma-separated list or round a value.
    pattern = r"(?<![\w.,])([+\-−]?\d{1,3}(?:[,\u00a0\u2009\u202f]\d{3})+(?:\.\d+)?)(?![\w.,])"
    return re.sub(pattern, lambda m: re.sub(r"[,\u00a0\u2009\u202f]", "", m[0]), text)


# ---------------------------------------------------------------------------
# building the pool of legitimate values
# ---------------------------------------------------------------------------
def _walk(obj, sink: set[str]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        sink.add(_norm(obj))
        return
    if isinstance(obj, str):
        for m in NUM_RE.finditer(normalize_grouping(obj)):
            sink.add(_norm(m.group(1)))
        return
    if isinstance(obj, dict):
        for key, v in obj.items():
            if key != "environment":  # Versions, seeds and file hashes are not scientific findings.
                _walk(v, sink)
        return
    if isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, sink)


def _norm(v) -> str:
    try:
        f = float(str(v).replace("−", "-"))
    except (TypeError, ValueError):
        return str(v)
    if f == int(f) and abs(f) < 1e15:
        return str(int(f))
    return repr(round(f, 10))


def results_pool(project) -> tuple[set[float], set[str], list[str]]:
    """-> (float pool, raw-string pool, source file names) for 03_analysis/results/*.json."""
    strings: set[str] = set()
    sources: list[str] = []
    for p in sorted((project / "03_analysis" / "results").glob("*.json")):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        sources.append(p.name)
        _walk(data, strings)
    floats: set[float] = set()
    for s in strings:
        try:
            floats.add(float(s))
        except ValueError:
            pass
    return floats, strings, sources


def _pool(ctx: Ctx) -> tuple[set[float], set[str], list[str]]:
    return results_pool(ctx.project)


def load_allowlist(project) -> set[str]:
    allowed = set(CONVENTIONS)
    p = project / ALLOWLIST
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            columns = line.split("\t")
            if len(columns) != 4 or columns[1] != "constant" or len(columns[3].strip()) < 20:
                continue  # old free-number allowlists cannot authorize invented evidence
            from ..packagefreeze import _safe_path
            try:
                _, source = _safe_path(project, columns[2])
                if source.is_file() and columns[0] in source.read_text(encoding="utf-8"):
                    allowed.add(columns[0])
            except (OSError, ValueError):
                pass
    return allowed


def _allowlist(ctx: Ctx) -> set[str]:
    return load_allowlist(ctx.project)


def _matches(token: str, floats: set[float], strings: set[str]) -> bool:
    if token in strings:
        return True
    try:
        val = float(token.replace("−", "-"))
    except ValueError:
        return False
    if val in floats:
        return True
    # Tolerate rounding to the precision the author displayed.
    dp = -Decimal(token.replace("−", "-")).as_tuple().exponent
    for f in floats:
        if (f < 0) != (val < 0) and f != 0 and val != 0:
            continue
        if round(f, dp) == val:
            return True
        if dp == 0 and abs(f - val) < 0.5 and f != 0:
            return True
    return False


def _scrub(text: str, *, table_non_result: bool = False) -> str:
    text = normalize_grouping(text)
    from ..displayrefs import scrub
    text = scrub(text)
    text = FENCE_RE.sub(" ", text)
    text = CITE_RE.sub(" ", text)
    text = ARTIFACT_RE.sub(" ", text)
    text = re.sub(r"\b[A-Za-z][A-Za-z0-9]*-\d+[A-Za-z]?\b", " ", text)  # codes, not measurements
    text = re.sub(r"^\s*#{1,6}\s.*$", " ", text, flags=re.M)
    text = re.sub(r"(?<![\d.])(?:80|85|90|95|97\.5|98|99)%\s*(?:CI|confidence\s+intervals?)\b", "CI", text, flags=re.I)
    text = re.sub(r"\b(19|20)\d{2}\s*[-\u2013]\s*(19|20)?\d{2}\b", " ", text)  # not scrubbed values
    # Universal biomedical versioning, formal classification/registry codes, standard clinical units/stagings, and hyphenated attributive windows.
    text = re.sub(r"\b(?:version|ver\.?|v)\s*\d+(?:\.\d+)+\b", " ", text, flags=re.I)
    text = re.sub(r"\b1\.73\s*m(?:²|2|\^2)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:CHA2DS2-VASc|CHA₂DS₂-VASc|CHADS2|HAS-BLED)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:c|p|yp)?T[0-4a-cisx]+N[0-3a-cx]+M[0-1a-cx]+\b", " ", text)
    text = re.sub(r"\b(?:ECOG|NYHA|ASA|Killip)\s+(?:class\s+|status\s+|grade\s+|score\s+)?[0-5IV]+(?:\s*[-\u2013]\s*[0-5IV]+)?\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:ICD-(?:9|10|11)(?:-[A-Z0-9.]+)?|NCT\d{6,})\b", " ", text, flags=re.I)
    text = re.sub(
        r"(?:\b|[\(\[])(?:PT|LLT|SMQ|HLT|HLGT|SOC|ATC|CPT|LOINC|SNOMED|Code|ID|Term)[\)\]]?\s*[:#\- ]?\s*\d{4,}\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\b[SE]\d+(?:\s*(?:[-\u2013,]|and|to)\s*[SE]?\d+)*\b", " ", text)
    text = re.sub(
        r"\b\d+-(?:\s*,\s*\d+-)*(?:\s*,?\s*(?:and|or)\s+\d+-)\s*(?:day|week|month|year|yr|mo|wk|hour|hr)s?\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b\d+(?:\.\d+)?-(?:day|week|month|year|yr|mo|wk|hour|hr|minute|min|"
        r"fold|item|point|arm|group|stage|step|phase|level|tier|quartile|"
        r"tertile|quintile|decile|center|centre|site|agent|drug|class|stratum|strata)s?\b",
        " ",
        text,
        flags=re.I,
    )
    if table_non_result:
        # Structural clinical category definitions (age brackets, time windows, model numbers) in
        # table titles, headers, column-A row stubs, and footnotes only — NEVER in body data cells.
        text = re.sub(
            r"(?:<=|>=|<|>|≤|≥)\s*\d+\s*(?:years?|yrs?|yr|y|months?|mos?|mo|weeks?|wks?|wk|days?|d|hours?|hrs?|hr)?\b",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"\b\d+\s*[-\u2013~to]+\s*\d+\s*(?:years?|yrs?|yr|y|months?|mos?|mo|weeks?|wks?|wk|days?|d|hours?|hrs?|hr)\b",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"\bModels?\s+[1-9]\d*[A-Za-z]?(?:\s*[-\u2013,and]+\s*[1-9]?\d*[A-Za-z]?)*\b",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(r"\b(?:version|ver\.?|v)\s*\d+\b", " ", text, flags=re.I)
    return text


def _offenders(text: str, floats, strings, allowed, p_values=None, *, table_non_result: bool = False) -> list[tuple[int, str]]:
    bad: list[tuple[int, str]] = []
    for lineno, raw in enumerate(_scrub(text, table_non_result=table_non_result).splitlines(), start=1):
        def pvalue(match):
            op, token = match.groups()
            threshold = float(token)
            candidates = [f for f in (floats if p_values is None else p_values) if 0 <= f <= 1]
            ok = (any(f < threshold for f in candidates) if op == "<" else
                  any(f <= threshold for f in candidates) if op == "≤" else
                  any(f > threshold for f in candidates) if op == ">" else
                  any(f >= threshold for f in candidates) if op == "≥" else
                  _matches(token, set(candidates), {_norm(p) for p in candidates}))
            if token in allowed:
                ok = True  # Explicit Methods constants; bound findings pass no allowlist.
            if not ok:
                bad.append((lineno, "P" + op + token))
            return " "
        raw = P_RE.sub(pvalue, raw)
        # Formatted table cells use a threshold without the P label.
        if re.fullmatch(r"\s*[<≤]\s*0?\.\d+\s*", raw):
            raw = P_RE.sub(pvalue, "P" + raw.strip())
        for m in NUM_RE.finditer(raw):
            tok = m.group(1)
            if tok in allowed:
                continue
            if _matches(tok, floats, strings):
                continue
            bad.append((lineno, tok))
    return bad


# ---------------------------------------------------------------------------
# checks
# ---------------------------------------------------------------------------
@check("numbers_have_provenance")
def numbers_have_provenance(ctx: Ctx) -> Result:
    source = ctx.spec.get("source", "markdown")
    rel = ""
    if source not in {"tables", "figures"}:
        rel = ctx.spec["path"]
        if not ctx.p(rel).exists():
            if ctx.spec.get("optional", False):
                return Result(True, "numbers_have_provenance", f"{rel}: optional file absent")
            return Result(False, "numbers_have_provenance", f"{rel} missing")

    floats, strings, sources = _pool(ctx)
    if not sources:
        return Result(
            False,
            "numbers_have_provenance",
            f"no result files under {RESULTS_GLOB}",
            ["Analysis code must dump every reported statistic to JSON before any prose is written."],
        )
    allowed = _allowlist(ctx) if (source in {"tables", "figures"} or rel.endswith(("methods.md", "supplementary_methods.md"))) else set()
    if source == "tables":
        only_filter = str(ctx.spec.get("_only") or "").strip().casefold()
        verbose = bool(ctx.spec.get("_verbose"))
        table_paths = ctx.glob("04_tables/main/*.xlsx") + ctx.glob("04_tables/supplementary/*.xlsx")
        if only_filter:
            only_compact = only_filter.replace(" ", "")
            filtered = [
                p for p in table_paths
                if only_filter in p.stem.casefold()
                or only_filter in p.relative_to(ctx.project).as_posix().casefold()
                or only_compact in p.stem.replace(" ", "").casefold()
            ]
            table_paths = filtered or [p for p in table_paths if "supplementary" in p.name.casefold()]
        offenders = []
        for p in table_paths:
            try:
                cells = xlsxlite.numeric_cell_values(p)
                xls_wb = xlsxlite.Workbook(p)
            except PermissionError as exc:
                return Result(False, "numbers_have_provenance", f"Workbook IO pending: {p.name}: {exc}",
                              ["Close or finish saving this workbook in Excel, then rerun the check; do not regenerate data or mark provenance passed."])
            except Exception as exc:  # noqa: BLE001 - report, do not crash the gate
                return Result(False, "numbers_have_provenance", f"cannot read {p.name}: {exc}")
            sheet_zones: dict[str, tuple[int, int]] = {}
            for sh in xls_wb.sheets:
                hdrs, last_body = xls_wb.header_rows(sh)
                sheet_zones[sh.name] = (max(hdrs) if hdrs else 2, last_body)
            for sheet, ref, val in cells:
                if only_filter:
                    only_compact = only_filter.replace(" ", "")
                    if (
                        only_filter not in p.stem.casefold()
                        and only_filter not in sheet.casefold()
                        and only_compact not in sheet.replace(" ", "").casefold()
                    ):
                        continue
                from ..claims import table_unit_constants
                try:
                    constants = table_unit_constants(ctx.project, p, sheet, ref, val)
                except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
                    return Result(False, "numbers_have_provenance", f"{p.name}[{sheet}]!{ref}: {exc}")
                pos = xlsxlite.parse_cell_ref(ref)
                hdr_end, last_body = sheet_zones.get(sheet, (2, 10**9))
                is_result_body = bool(pos is not None and (hdr_end < pos[0] <= last_body) and pos[1] > 1)
                non_result = not is_result_body
                cell_allowed = constants if is_result_body else (allowed | constants)
                if _offenders(str(val), floats, strings, cell_allowed, table_non_result=non_result):
                    offenders.append(f"{p.name}[{sheet}]!{ref}={val}")
        from ..claims import validate_tables
        offenders.extend(validate_tables(ctx.project, table_paths, only=ctx.spec.get("_only")))
        if offenders:
            uniq = sorted(set(offenders))
            limit = len(uniq) if verbose else 8
            return Result(
                False,
                "numbers_have_provenance",
                f"{len(uniq)} table value(s) not traceable to results JSON: " + "; ".join(uniq[:limit]),
                [
                    "Result-body cells must come directly from 03_analysis/results/*.json (via claim_bindings.json).",
                    f"Only documented protocol/code constants in table titles, headers, col-A stubs, or footnotes may use {ALLOWLIST} (token \\t constant \\t source_path \\t reason).",
                ],
            )
        return Result(True, "numbers_have_provenance", f"all table values trace to {len(sources)} result file(s)")

    if source == "figures":
        from ..claims import validate_figures
        journal = ctx.stage.id in {"S23_package", "S24_package_human_review", "S25_submission_audit"} and (
            ctx.project / "08_submission/integration/artifact_plan.json"
        ).is_file()
        problems = validate_figures(ctx.project, journal=journal, only=ctx.spec.get("_only"))
        if problems:
            limit = len(problems) if ctx.spec.get("_verbose") else 6
            return Result(
                False,
                "numbers_have_provenance",
                f"{len(problems)} figure statistical annotation issue(s): " + "; ".join(problems[:limit]),
                [
                    "Bind every explicit statistical label on rendered figures in claim_bindings.json figure_annotations.",
                    "Map each displayed number (estimate, CI bounds, P, n, AUC) to its executed result JSON pointer and field.",
                ],
            )
        return Result(True, "numbers_have_provenance", "explicit figure statistical annotations trace to bound result fields")

    only_md = str(ctx.spec.get("_only") or "").strip().casefold()
    if only_md and only_md not in rel.casefold() and Path(rel).stem.casefold() != only_md.removesuffix(".md"):
        return Result(True, "numbers_have_provenance", f"{rel}: skipped outside --only {ctx.spec.get('_only')}")
    verbose = bool(ctx.spec.get("_verbose"))
    from ..journalspec import admin_scrub
    from ..sourceclaims import mask
    masked, external_problems = mask(ctx.project, rel, ctx.read(rel))
    if external_problems:
        limit = len(external_problems) if verbose else 8
        return Result(False, "numbers_have_provenance", "; ".join(external_problems[:limit]))
    bad = _offenders(admin_scrub(masked, ctx.project, rel), floats, strings, allowed)
    if bad:
        limit = len(bad) if verbose else 10
        shown = "; ".join(f"line {ln}: {tok}" for ln, tok in bad[:limit])
        return Result(
            False,
            "numbers_have_provenance",
            f"{rel}: {len(bad)} number(s) with no provenance -> {shown}",
            [
                "Every statistic must already exist in 03_analysis/results/*.json, written by executed code.",
                "Own findings require executed facts; cited numbers require exact full-text source_claims. Only documented Methods constants use the typed allowlist.",
                "Do not fix this by rounding differently. Re-run the analysis and dump the value.",
            ],
        )
    from ..claims import validate_prose
    problems = validate_prose(ctx.project, rel, masked, already_masked=True)
    p_limit = len(problems) if verbose else 8
    return Result(not problems, "numbers_have_provenance", "; ".join(problems[:p_limit]) or
                  f"{rel}: numeric source checks passed; clinical interpretation still requires scientific review")


@check("numbers_cross_match")
def numbers_cross_match(ctx: Ctx) -> Result:
    """Numbers attributed to 'Table N' in Results must actually appear in Table N."""
    rel = "07_manuscript/results.md"
    if not ctx.p(rel).exists():
        return Result(False, "numbers_cross_match", f"{rel} missing")
    try:
        plan = ctx.read_json("01_protocol/artifact_plan.json")
    except Exception:  # noqa: BLE001
        return Result(False, "numbers_cross_match", "artifact_plan.json unreadable")

    table_files: dict[str, list] = {}
    for entry in plan.get("main_tables", []) + plan.get("supp_tables", []):
        label = str(entry.get("id", "")).strip()
        fp = entry.get("file")
        if not label or not fp:
            continue
        p = ctx.p(fp)
        if p.exists():
            try:
                table_files[label.lower()] = [v for _, _, v in xlsxlite.numeric_cell_values(p)]
            except Exception:  # noqa: BLE001
                table_files[label.lower()] = []

    if not table_files:
        return Result(False, "numbers_cross_match", "no rendered tables found to cross-match against")

    allowed = set()  # crossmatched Results cannot borrow a Methods constant exemption
    text = FENCE_RE.sub(" ", ctx.read(rel))
    sentences = re.split(r"(?<=[.;])\s+", text)
    problems: list[str] = []
    checked = 0
    for sent in sentences:
        refs = re.findall(r"\b((?:supplementary\s+)?table\s*S?\d+)\b", sent, re.I)
        if not refs:
            continue
        pool: set[str] = set()
        matched_label = None
        for r in refs:
            key = re.sub(r"\s+", " ", r.strip().lower())
            for label, vals in table_files.items():
                if key.endswith(label.split()[-1]) or label in key:
                    matched_label = label
                    for v in vals:
                        for m in NUM_RE.finditer(str(v)):
                            pool.add(m.group(1))
        if not pool:
            continue
        checked += 1
        body = ARTIFACT_RE.sub(" ", CITE_RE.sub(" ", sent))
        for m in NUM_RE.finditer(body):
            tok = m.group(1)
            if tok in allowed or tok in pool:
                continue
            if any(abs(float(tok) - float(v)) < 10 ** -max(0, len(tok.split(".")[1]) if "." in tok else 0)
                   for v in pool if _is_num(v)):
                continue
            problems.append(f"{tok} cited to {matched_label} but absent from it")
    if problems:
        uniq = sorted(set(problems))
        return Result(
            False,
            "numbers_cross_match",
            f"{len(uniq)} mismatch(es): " + "; ".join(uniq[:8]),
            ["Either the sentence cites the wrong table or the table was built from different values."],
        )
    return Result(
        True,
        "numbers_cross_match",
        f"{checked} table-citing sentence(s) agree with the rendered tables",
    )


def _is_num(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False
