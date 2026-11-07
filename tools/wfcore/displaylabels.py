"""Clinical-reader label and internal display-text checks for tables and figures (v1.29+).

Ensures that text rendered inside medical tables (titles, column headers, row stubs,
cells, and footnotes) and inside medical figures (axis titles, tick labels, legends,
forest/balance variable labels, panel headers, and selection-flowchart boxes) uses
self-explanatory clinical terminology rather than raw code identifiers, statistical
package dump column names, unlabelled numeric/boolean codes, or analytics-report jargon.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from . import xlsxlite
from .packagefreeze import _safe_path
from .readiness import load

URL_OR_DOI_RE = re.compile(r"(?:https?://\S+|\b10\.\d{4,9}/\S+)", re.I)

# Underscore-joined code/database identifiers (e.g. age_yr, hosp_los, icu_flag, p_val, m1_crude).
SNAKE_CASE_RE = re.compile(
    r"(?<![A-Za-z0-9/.\-])"
    r"(?!Supplemental_File_\d+\b)"
    r"([A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+)"
    r"(?![A-Za-z0-9/.\-])"
)

# Multi-word programming camelCase (e.g. followUpDays, baselineSbp, predProb, hospLos).
# Single-letter prefixes (eGFR, cTnI, mRNA, sST2, uACR) and all-caps suffixes
# (miRNA, siRNA, scRNA, cfDNA, ctDNA, ddPCR, rtPCR) do NOT match [a-z]{2,}[A-Z][a-z]{2,}.
CAMEL_CASE_RE = re.compile(r"(?<![A-Za-z0-9\-])([a-z]{2,}[A-Z][a-z]{2,}[A-Za-z0-9]*)\b")
CAMEL_BIOMED_ALLOW = {
    "pka",
    "pkb",
    "mcnemar",
    "macos",
    "dejavu",
    "pubmed",
    "biorxiv",
    "medrxiv",
    "openfda",
    "ukbiobank",
    "clinicaltrials",
}

# R / Python / formula / dataframe syntax leaked into display labels.
FORMULA_SYNTAX_RE = re.compile(
    r"(?:"
    r"\b(?:as\.factor|as\.numeric|as\.character|as\.integer|factor|strata|rcs|ns|bs|poly|offset|relevel|ifelse|case_when)\s*\("
    r"|\b(?:np|pd|plt|sns|stats|sm|smf)\.[A-Za-z_]\w*"
    r"|\b[A-Za-z_]\w*\$[A-Za-z_]\w*\b"
    r"|\bI\s*\([^)\n]*[+\-*/^=<>][^)\n]*\)"
    r"|\bC\s*\([^,\n)]+,\s*Treatment\b"
    r")"
)

# Raw boolean literals or 0/1 coding or numbered placeholder groups in categorical labels/legends.
RAW_BOOL_EXACT_RE = re.compile(r"^\s*(?:TRUE|FALSE|True|False)\s*$")
RAW_BOOL_KV_RE = re.compile(r"(?:=|:)\s*(?:TRUE|FALSE|True|False)\b|\b(?:TRUE|FALSE)\s*\(")
RAW_BINARY_KV_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9\s\-]{1,28}?)\s*(?:=|:)\s*([01])\b")
BINARY_KV_ALLOWED_KEYS = {
    "n", "p", "hr", "or", "rr", "irr", "smd", "auc", "ci", "sd", "iqr", "se",
    "df", "k", "r", "r2", "i2", "q", "score", "grade", "stage", "class", "type",
    "phase", "step", "visit", "day", "week", "month", "year", "cycle", "dose",
    "level", "tier", "tertile", "quartile", "quintile", "decile", "parity", "gravidity",
    "ecog", "asa", "nyha", "mrs", "killip", "timi", "glasgow", "sofa", "apache",
    "cha2ds2-vasc", "has-bled", "child-pugh", "meld", "aki", "ckd", "gold", "bi-rads",
}
NUMBERED_GROUP_CODE_RE = re.compile(
    r"\b(?:Group|Arm|Cluster|Cohort|Treat(?:ment)?|Exposure|Stratum)\s+[01]\b",
    re.I,
)

# Raw statistical package dump column names (broom, summary.glm, coxph, statsmodels, lifelines, sklearn).
RAW_STAT_HEADER_RE = re.compile(
    r"^\s*(?:"
    r"coef|coeff|std\.?\s*err(?:or)?|stderr|statistic|"
    r"[zt][\s._\-]?(?:val(?:ue)?|stat(?:istic)?)|chisq|"
    r"p\.value|pval|p[\s._\-]?val|pr\s*\(\s*>\s*(?:\|[zt]\||chisq|f)\s*\)|"
    r"conf\.low|conf\.high|ci\.low|ci\.high|lower\.95|upper\.95|"
    r"hr\.ci|or\.ci|rr\.ci|fpr|tpr|surv(?:\.prob)?|cumhaz|"
    r"n\.risk|n\.event|n\.censor"
    r")\s*$",
    re.I,
)

# Machine-oriented first-column headers in clinical tables.
MACHINE_STUB_HEADERS = {
    "variable",
    "variables",
    "feature",
    "features",
    "covariate",
    "covariates",
    "predictor",
    "predictors",
    "field",
    "fields",
    "column",
    "columns",
    "parameter",
    "parameters",
    "term",
    "terms",
}

# Analytics-report / notebook titles instead of clinical subject titles.
ANALYTICS_TITLE_RE = re.compile(
    r"\b(?:"
    r"(?:primary\s+|secondary\s+|main\s+|multivariable\s+)?model\s+output|"
    r"regression\s+(?:output|summary|results\s+dump)|"
    r"statistical\s+output|analysis\s+output|summary\s+output|"
    r"dataset\s+summary|data\s+summary|exploratory\s+data\s+analysis|"
    r"feature\s+importance|variable\s+importance|shap\s+summary|"
    r"hyperparameter\s+tuning|ablation\s+study|"
    r"data\s+cleaning\s+flow|pipeline\s+workflow"
    r")\b",
    re.I,
)

# Shorthand model object names and numbered models.
SHORTHAND_MODEL_RE = re.compile(r"^\s*(?:m[1-9]|mod[1-9]|fit[1-9]|mdl[1-9])(?:\b|\s*\()", re.I)
NUMBERED_MODEL_RE = re.compile(r"\bModel\s+([1-9]\d*|I{1,3}|IV|V)\b")
MODEL_ADJUSTMENT_EXPLANATION_RE = re.compile(
    r"\b(?:"
    r"unadjusted|crude|adjusted\s+for|adjusting\s+for|controlling\s+for|"
    r"covariates?|stratified\s+by|includes?\b|including\b|plus\b|"
    r"model\s+(?:[1-9]\d*|i{1,3}|iv|v)\s*[:=,;(]"
    r")\b",
    re.I,
)

# Data-wrangling / script jargon inside participant or record selection flowcharts.
FLOW_JARGON_RE = re.compile(
    r"\b(?:"
    r"raw\s+(?:csv|tsv|json|parquet|xlsx|data|rows|table|file)|"
    r"csv\s+rows|dataframe|data\s+frame|sql\s+query|"
    r"dedup(?:licat\w*)?\s+script|deduped|merged\s+table|inner\s+join|left\s+join|"
    r"complete[- ]case\s+filter|dropna|dropped\s+na|missingness\s+drop|"
    r"regex\s+filter|parsed\s+rows|parser"
    r")\b",
    re.I,
)


def _strip_urls(text: str) -> str:
    return URL_OR_DOI_RE.sub(" ", text)


def _make_issue(path: str, locator: str, kind: str, excerpt: str, message: str, context: str | None = None) -> dict:
    basis = (context if context is not None else excerpt).strip()
    identity = hashlib.sha256(f"{path}\0{kind}\0{basis}".encode("utf-8")).hexdigest()[:16]
    short = excerpt.strip()
    if len(short) > 180:
        short = short[:177].rstrip() + "…"
    return {
        "id": identity,
        "path": path,
        "locator": locator,
        "kind": kind,
        "excerpt": short,
        "message": message,
    }


def diagnose_label_token(
    text: str,
    *,
    path: str,
    locator: str,
    surface: str = "cell",
    is_first_header: bool = False,
    archetype: str = "",
) -> list[dict]:
    """Inspect one visible display string according to its structural role.

    `surface` is one of: ``title``, ``header``, ``stub``, ``cell``, ``footnote``,
    ``figure_text``, ``figure_axis``, ``legend``, ``dictionary``.
    """
    raw = str(text or "").strip()
    if not raw:
        return []
    cleaned = _strip_urls(raw)
    out: list[dict] = []

    for match in SNAKE_CASE_RE.finditer(cleaned):
        tok = match.group(1)
        out.append(_make_issue(
            path,
            locator,
            "code_identifier",
            raw,
            f"Replace raw code/field identifier '{tok}' with a self-explanatory clinical term and unit (via display_dictionary).",
            context=raw,
        ))
        break

    for match in CAMEL_CASE_RE.finditer(cleaned):
        tok = match.group(1)
        if tok.casefold() not in CAMEL_BIOMED_ALLOW:
            out.append(_make_issue(
                path,
                locator,
                "code_identifier",
                raw,
                f"Replace camelCase variable identifier '{tok}' with standard medical wording.",
                context=raw,
            ))
            break

    if FORMULA_SYNTAX_RE.search(cleaned):
        out.append(_make_issue(
            path,
            locator,
            "formula_syntax",
            raw,
            "Remove R/Python formula or dataframe syntax (e.g. factor(...), rcs(...), I(...), df$col) from reader-facing display text.",
            context=raw,
        ))

    if surface in {"header", "stub", "figure_text", "figure_axis", "dictionary"}:
        if RAW_BOOL_EXACT_RE.match(cleaned) or RAW_BOOL_KV_RE.search(cleaned):
            out.append(_make_issue(
                path,
                locator,
                "raw_coding_label",
                raw,
                "Replace raw boolean literal (TRUE/FALSE) with explicit clinical category wording (e.g. Yes/No or present clinical state).",
                context=raw,
            ))
        else:
            for match in RAW_BINARY_KV_RE.finditer(cleaned):
                key_norm = re.sub(r"\s+", " ", match.group(1)).strip().casefold()
                last_word = key_norm.rsplit(" ", 1)[-1]
                if key_norm not in BINARY_KV_ALLOWED_KEYS and last_word not in BINARY_KV_ALLOWED_KEYS:
                    out.append(_make_issue(
                        path,
                        locator,
                        "raw_coding_label",
                        raw,
                        f"Decode binary code '{match.group(0).strip()}' into real clinical categories (e.g. Male/Female, Exposure vs Reference).",
                        context=raw,
                    ))
                    break
        if NUMBERED_GROUP_CODE_RE.search(cleaned):
            out.append(_make_issue(
                path,
                locator,
                "raw_coding_label",
                raw,
                "Replace machine-numbered group label (e.g. Group 0 / Group 1) with the actual clinical exposure, intervention, or stratum name.",
                context=raw,
            ))

    if surface in {"header", "figure_axis", "figure_text", "dictionary"}:
        if RAW_STAT_HEADER_RE.match(cleaned):
            out.append(_make_issue(
                path,
                locator,
                "raw_stat_header",
                raw,
                f"Replace statistical-software dump label '{cleaned}' with standard medical journal wording (e.g. 'Adjusted HR (95% CI)', 'P value', '1 - specificity').",
                context=raw,
            ))

    if is_first_header and cleaned.casefold() in MACHINE_STUB_HEADERS:
        out.append(_make_issue(
            path,
            locator,
            "generic_machine_header",
            raw,
            f"First-column header '{cleaned}' reads like a data dictionary/model dump; use clinical column headings such as 'Characteristic', 'Subgroup', or 'Outcome'.",
            context=raw,
        ))

    if surface in {"header", "stub", "cell", "figure_text"} and SHORTHAND_MODEL_RE.match(cleaned):
        out.append(_make_issue(
            path,
            locator,
            "unexplained_model_label",
            raw,
            f"Replace shorthand model object '{cleaned}' with descriptive clinical adjustment labels (e.g. 'Unadjusted', 'Multivariable-adjusted').",
            context=raw,
        ))

    if surface in {"title", "figure_text"} and ANALYTICS_TITLE_RE.search(cleaned):
        out.append(_make_issue(
            path,
            locator,
            "analytics_report_title",
            raw,
            "Title/header uses analytics-report phrasing; state the clinical population, exposure/comparison, and outcome instead.",
            context=raw,
        ))

    if (archetype == "flow_diagram" or surface == "flow_node") and FLOW_JARGON_RE.search(cleaned):
        out.append(_make_issue(
            path,
            locator,
            "pipeline_flowchart_jargon",
            raw,
            "Selection flowchart box uses data-processing/script jargon instead of clinical eligibility and exclusion criteria.",
            context=raw,
        ))

    return out


def _check_numbered_models(
    path: str,
    locator_prefix: str,
    visible_items: list[str],
    explanatory_notes: str,
) -> list[dict]:
    models_seen: list[str] = []
    for item in visible_items:
        for match in NUMBERED_MODEL_RE.finditer(str(item or "")):
            label = f"Model {match.group(1)}"
            if label not in models_seen:
                models_seen.append(label)
    if not models_seen:
        return []
    if MODEL_ADJUSTMENT_EXPLANATION_RE.search(explanatory_notes or ""):
        return []
    joined = ", ".join(models_seen)
    return [_make_issue(
        path,
        f"{locator_prefix} footnotes/legend",
        "unexplained_model_label",
        joined,
        f"{joined} appears in the display without stating what clinical covariates each model adjusts for in the table footnote or figure legend.",
        context=f"{locator_prefix}:{joined}",
    )]


def inspect_xlsx_table(path: Path, rel: str | None = None, sheet_name: str | None = None) -> list[dict]:
    """Audit all structural zones (title, headers, stubs, cells, footnotes) of a three-line XLSX."""
    rel_str = rel or path.name
    try:
        wb = xlsxlite.Workbook(path)
    except Exception:  # noqa: BLE001
        return []

    issues: list[dict] = []
    sheets = [wb.sheet(sheet_name)] if sheet_name else list(wb.sheets)
    for sh in sheets:
        if sh is None or sh.max_row == 0:
            continue
        loc_base = f"{sh.name}"
        row_cells = {r: sh.row_cells(r) for r in range(1, sh.max_row + 1)}
        ruled = [
            r for r, cells in row_cells.items()
            if any(wb.border_of(c).top or wb.border_of(c).bottom for c in cells)
        ]
        title_cells = row_cells.get(1, [])
        title_text = " ".join(c.value or "" for c in title_cells if c.value).strip()
        if title_text:
            issues.extend(diagnose_label_token(
                title_text, path=rel_str, locator=f"{loc_base}!row1 (title)", surface="title"
            ))

        if not ruled:
            for r in range(2, sh.max_row + 1):
                for c in row_cells.get(r, []):
                    if c.value:
                        issues.extend(diagnose_label_token(
                            c.value, path=rel_str, locator=f"{loc_base}!{c.ref}", surface="cell"
                        ))
            continue

        header_start = min(ruled)
        last_body = max(ruled)
        header_end = max(
            [r for r in ruled if r < last_body] or [header_start]
        )

        body_and_header_texts: list[str] = []
        for r in range(header_start, header_end + 1):
            for idx, c in enumerate(row_cells.get(r, [])):
                if not c.value:
                    continue
                body_and_header_texts.append(c.value)
                issues.extend(diagnose_label_token(
                    c.value,
                    path=rel_str,
                    locator=f"{loc_base}!{c.ref} (header)",
                    surface="header",
                    is_first_header=(r == header_start and idx == 0 and c.ref.startswith("A")),
                ))

        for r in range(header_end + 1, last_body + 1):
            for c in row_cells.get(r, []):
                if not c.value:
                    continue
                is_stub = c.ref.startswith("A")
                body_and_header_texts.append(c.value)
                issues.extend(diagnose_label_token(
                    c.value,
                    path=rel_str,
                    locator=f"{loc_base}!{c.ref} ({'stub' if is_stub else 'cell'})",
                    surface="stub" if is_stub else "cell",
                ))

        footnote_texts: list[str] = []
        for r in range(last_body + 1, sh.max_row + 1):
            for c in row_cells.get(r, []):
                if not c.value:
                    continue
                footnote_texts.append(c.value)
                issues.extend(diagnose_label_token(
                    c.value,
                    path=rel_str,
                    locator=f"{loc_base}!{c.ref} (footnote)",
                    surface="footnote",
                ))

        issues.extend(_check_numbered_models(
            rel_str, loc_base, body_and_header_texts, "\n".join(footnote_texts)
        ))
    return _dedup(issues)


def inspect_docx_tables(path: Path, rel: str | None = None) -> list[dict]:
    """Audit native Word tables (headers, stubs, cells, surrounding captions/notes) in a .docx."""
    rel_str = rel or path.name
    try:
        from docx import Document
        doc = Document(path)
    except Exception:  # noqa: BLE001
        return []

    body_nodes = list(doc.element.body)
    paragraphs_by_el = {p._p: p.text.strip() for p in doc.paragraphs}
    tables_by_el = {t._tbl: t for t in doc.tables}

    issues: list[dict] = []
    for idx, node in enumerate(body_nodes):
        tbl = tables_by_el.get(node)
        if tbl is None or not tbl.rows:
            continue
        t_num = sum(1 for n in body_nodes[: idx + 1] if n in tables_by_el)
        loc_base = f"Word table {t_num}"

        caption = ""
        if idx > 0 and body_nodes[idx - 1] in paragraphs_by_el:
            caption = paragraphs_by_el[body_nodes[idx - 1]]
            if caption:
                issues.extend(diagnose_label_token(
                    caption, path=rel_str, locator=f"{loc_base} caption", surface="title"
                ))

        notes: list[str] = []
        scan_i = idx + 1
        while scan_i < len(body_nodes) and body_nodes[scan_i] in paragraphs_by_el:
            txt = paragraphs_by_el[body_nodes[scan_i]]
            if not txt or re.match(r"^(?:Table|Figure)\s+S?\d+[.:]", txt, re.I):
                break
            notes.append(txt)
            issues.extend(diagnose_label_token(
                txt, path=rel_str, locator=f"{loc_base} note", surface="footnote"
            ))
            scan_i += 1
            if len(notes) >= 8:
                break

        visible_cells: list[str] = []
        for r_idx, row in enumerate(tbl.rows):
            seen_tc: set[int] = set()
            for c_idx, cell in enumerate(row.cells):
                if id(cell._tc) in seen_tc:
                    continue
                seen_tc.add(id(cell._tc))
                val = cell.text.strip()
                if not val:
                    continue
                visible_cells.append(val)
                if r_idx == 0:
                    issues.extend(diagnose_label_token(
                        val,
                        path=rel_str,
                        locator=f"{loc_base} header col {c_idx + 1}",
                        surface="header",
                        is_first_header=(c_idx == 0),
                    ))
                else:
                    issues.extend(diagnose_label_token(
                        val,
                        path=rel_str,
                        locator=f"{loc_base} row {r_idx + 1} col {c_idx + 1}",
                        surface="stub" if c_idx == 0 else "cell",
                    ))

        issues.extend(_check_numbered_models(
            rel_str, loc_base, visible_cells, "\n".join(notes)
        ))
    return _dedup(issues)


def _svg_texts(svg_path: Path) -> list[str]:
    try:
        root = ET.fromstring(svg_path.read_bytes())
    except Exception:  # noqa: BLE001
        return []
    out: list[str] = []
    for node in root.iter():
        if node.tag.endswith("}text") or node.tag == "text":
            txt = "".join(node.itertext()).strip()
            if txt:
                out.append(txt)
    return out


def _pdf_texts(pdf_path: Path) -> list[str]:
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        lines: list[str] = []
        for page in reader.pages:
            for ln in (page.extract_text() or "").splitlines():
                if ln.strip():
                    lines.append(ln.strip())
        return lines
    except Exception:  # noqa: BLE001
        return []


def _legend_for_figure(project: Path, figure_id: str, *, layer: str = "science") -> str:
    from .checks.artifacts import _same_id, _split_blocks
    candidates = (
        ["08_submission/integration/figure_legends.md", "05_figures/legends.md"]
        if layer == "journal"
        else ["05_figures/legends.md"]
    )
    for rel in candidates:
        p = project / rel
        if p.is_file():
            blocks = _split_blocks(p.read_text(encoding="utf-8", errors="replace"))
            for key, body in blocks.items():
                if _same_id(key, figure_id):
                    return body
    return ""


def collect_figure_text_items(
    project: Path,
    entry: dict,
    *,
    art_override: dict | None = None,
) -> tuple[str, list[tuple[str, str, str]]]:
    """Return ``(report_rel, [(locator, surface, text), ...])`` for a planned figure.

    Penetrates raster ``.png``/``.tiff`` targets by reading the co-produced
    ``qc/<stem>.artist.json`` (R and Python ``figure_text`` + panel ``x_label``/``y_label``),
    ``qc/<stem>.render.svg``, and vector ``.pdf`` master when present.
    """
    file_rel = str(entry.get("file", "")).strip()
    if not file_rel:
        return "", []
    _, fpath = _safe_path(project, file_rel)
    stem = fpath.stem

    qc_candidates = [
        fpath.parent.parent / "qc" / f"{stem}.artist.json",
        project / "05_figures" / "qc" / f"{stem}.artist.json",
    ]
    svg_candidates = [
        fpath.parent.parent / "qc" / f"{stem}.render.svg",
        project / "05_figures" / "qc" / f"{stem}.render.svg",
    ]
    if fpath.suffix.lower() == ".svg":
        svg_candidates.insert(0, fpath)

    items: list[tuple[str, str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()

    def _add(loc: str, surf: str, txt: str) -> None:
        val = str(txt or "").strip()
        if not val:
            return
        sig = (surf, val)
        if sig not in seen_pairs:
            seen_pairs.add(sig)
            items.append((loc, surf, val))

    art = art_override
    if art is None:
        for cand in qc_candidates:
            if cand.is_file():
                try:
                    art = json.loads(cand.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    art = None
                break

    if isinstance(art, dict):
        runtime = art.get("runtime") if isinstance(art.get("runtime"), dict) else {}
        panels = runtime.get("panels") if isinstance(runtime.get("panels"), list) else []
        for idx, panel in enumerate(panels, 1):
            if isinstance(panel, dict):
                if panel.get("x_label"):
                    _add(f"panel {idx} x-axis", "figure_axis", str(panel["x_label"]))
                if panel.get("y_label"):
                    _add(f"panel {idx} y-axis", "figure_axis", str(panel["y_label"]))
        for txt in art.get("non_tick_text") or []:
            _add("artist non-tick text", "figure_text", str(txt))
        for txt in art.get("figure_text") or []:
            _add("artist figure_text", "figure_text", str(txt))

    for svg_cand in svg_candidates:
        if svg_cand.is_file():
            for txt in _svg_texts(svg_cand):
                _add("rendered SVG text", "figure_text", txt)
            break

    if not items:
        pdf_rel = entry.get("pdf")
        pdf_candidates = []
        if pdf_rel:
            try:
                pdf_candidates.append(_safe_path(project, str(pdf_rel))[1])
            except ValueError:
                pass
        pdf_candidates.append(fpath.with_suffix(".pdf"))
        for pdf_cand in pdf_candidates:
            if pdf_cand.is_file():
                for txt in _pdf_texts(pdf_cand):
                    _add("vector PDF text", "figure_text", txt)
                break

    return file_rel, items


def inspect_figure_entry(
    project: Path,
    entry: dict,
    *,
    layer: str = "science",
    art_override: dict | None = None,
) -> list[dict]:
    """Audit all rendered internal text of a figure entry for clinical readability."""
    fid = str(entry.get("id", "?")).strip()
    archetype = str(entry.get("archetype", "")).strip()
    rel_str, items = collect_figure_text_items(project, entry, art_override=art_override)
    if not rel_str or not items:
        return []

    issues: list[dict] = []
    all_texts: list[str] = []
    for loc, surf, txt in items:
        all_texts.append(txt)
        issues.extend(diagnose_label_token(
            txt,
            path=rel_str,
            locator=f"{fid} ({loc})",
            surface="flow_node" if archetype == "flow_diagram" else surf,
            archetype=archetype,
        ))

    legend_body = _legend_for_figure(project, fid, layer=layer)
    issues.extend(_check_numbered_models(
        rel_str, fid, all_texts, "\n".join([*all_texts, legend_body])
    ))
    return _dedup(issues)


def figure_visible_companion_text(project: Path, entry: dict) -> tuple[str, str]:
    """Return ``(logical_rel, newline_joined_text)`` from verified vector/artist sidecars for medicalstyle.scan."""
    rel_str, items = collect_figure_text_items(project, entry)
    if not rel_str or not items:
        return rel_str, ""
    return rel_str, "\n".join(txt for _, _, txt in items)


def verify_plan_labels(project: Path, *, journal: bool = False) -> list[dict]:
    """Audit S07/journal artifact_plan.json display_dictionary, planned titles, captions and legends."""
    plan_rel = "08_submission/integration/artifact_plan.json" if journal else "01_protocol/artifact_plan.json"
    plan_path = project / plan_rel
    if not plan_path.is_file():
        return [_make_issue(plan_rel, "file", "missing_plan", plan_rel, f"{plan_rel} missing")]
    plan = load(project, plan_rel)

    issues: list[dict] = []
    dictionary = plan.get("display_dictionary") or []
    mapped_internals: dict[str, str] = {}
    for idx, row in enumerate(dictionary, 1):
        if not isinstance(row, dict):
            continue
        internal = str(row.get("internal", "")).strip()
        key = str(row.get("key", "")).strip()
        lbl = str(row.get("label", "")).strip()
        if internal:
            mapped_internals[internal] = lbl
        if key:
            mapped_internals[key] = lbl
        if lbl:
            issues.extend(diagnose_label_token(
                lbl,
                path=plan_rel,
                locator=f"display_dictionary[{idx}] label",
                surface="dictionary",
            ))

    has_displays = any(plan.get(g) for g in ("main_figures", "main_tables", "supp_figures", "supp_tables"))
    contract_rel = "01_protocol/analysis_contract.json"
    if not journal and has_displays and (project / contract_rel).is_file():
        try:
            contract = load(project, contract_rel)
        except Exception:  # noqa: BLE001
            contract = {}
        var_defs = contract.get("variable_definitions") or []
        unmapped_codes: list[str] = []
        for row in var_defs:
            if not isinstance(row, dict):
                continue
            src_field = str(row.get("source_field", "")).strip()
            if not src_field:
                continue
            code_hits = diagnose_label_token(
                src_field, path=contract_rel, locator="variable_definitions", surface="dictionary"
            )
            if code_hits and src_field not in mapped_internals:
                unmapped_codes.append(src_field)
        if unmapped_codes:
            sample = ", ".join(sorted(dict.fromkeys(unmapped_codes))[:6])
            issues.append(_make_issue(
                plan_rel,
                "display_dictionary",
                "missing_dictionary_mapping",
                sample,
                f"Map code-style analysis_contract source_field(s) ({sample}) in artifact_plan.json display_dictionary to clinical reader labels before building tables/figures.",
                context=sample,
            ))

    for group in ("main_figures", "main_tables", "supp_figures", "supp_tables"):
        for entry in plan.get(group, []):
            eid = str(entry.get("id", "?"))
            title = str(entry.get("title", "")).strip()
            if title:
                issues.extend(diagnose_label_token(
                    title,
                    path=plan_rel,
                    locator=f"{eid}.title",
                    surface="title",
                ))

    captions_rel = "08_submission/integration/table_captions.md" if journal else "04_tables/table_captions.md"
    legends_rel = "08_submission/integration/figure_legends.md" if journal else "05_figures/legends.md"
    for doc_rel, surf in ((captions_rel, "title"), (legends_rel, "legend")):
        p = project / doc_rel
        if not p.is_file():
            continue
        for line_no, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            issues.extend(diagnose_label_token(
                stripped, path=doc_rel, locator=f"line {line_no}", surface=surf
            ))

    return _dedup(issues)


def collect_project_issues(
    project: Path,
    kind: str = "all",
    *,
    layer: str = "science",
    final: bool = False,
) -> list[dict]:
    """Collect structured clinical-label issues for `plan`, `table`, `figure`, or `all`."""
    journal = layer == "journal"
    plan_rel = "08_submission/integration/artifact_plan.json" if journal else "01_protocol/artifact_plan.json"
    plan = load(project, plan_rel) if (project / plan_rel).is_file() else {}
    issues: list[dict] = []

    if kind in {"plan", "all"}:
        issues.extend(verify_plan_labels(project, journal=journal))

    if kind in {"table", "all"}:
        seen_xlsx: set[tuple[str, str | None]] = set()
        for group in ("main_tables", "supp_tables"):
            for entry in plan.get(group, []):
                f_rel = str(entry.get("file", "")).strip()
                if not f_rel:
                    continue
                _, f_path = _safe_path(project, f_rel)
                sheet = entry.get("sheet")
                key = (f_rel, sheet)
                if f_path.is_file() and f_path.suffix.lower() == ".xlsx" and key not in seen_xlsx:
                    seen_xlsx.add(key)
                    issues.extend(inspect_xlsx_table(f_path, rel=f_rel, sheet_name=sheet))

    if kind in {"figure", "all"}:
        for group in ("main_figures", "supp_figures"):
            for entry in plan.get(group, []):
                issues.extend(inspect_figure_entry(project, entry, layer=layer))

    if final and (project / "08_submission/bundle/manifest.json").is_file():
        manifest = load(project, "08_submission/bundle/manifest.json")
        for row in manifest.get("items", []):
            if not row.get("upload", True):
                continue
            b_rel = str(row.get("file", "")).strip()
            if not b_rel:
                continue
            _, b_path = _safe_path(project, b_rel)
            if not b_path.is_file():
                continue
            suf = b_path.suffix.lower()
            if suf == ".xlsx":
                issues.extend(inspect_xlsx_table(b_path, rel=b_rel))
            elif suf == ".docx" and row.get("role") in {"manuscript", "tables", "supplementary"}:
                issues.extend(inspect_docx_tables(b_path, rel=b_rel))

    return _dedup(issues)


def _dedup(issues: list[dict]) -> list[dict]:
    unique: dict[str, dict] = {}
    for item in issues:
        iid = item["id"]
        if iid in unique:
            unique[iid].setdefault("also_at", []).append(item["locator"])
        else:
            unique[iid] = dict(item)
    return list(unique.values())

def scan_text(text: str, context: str = "") -> list[dict]:
    """Convenience helper to scan a single text string for clinical label defects."""
    ctx_lower = context.lower() if context else ""
    surface = "figure_axis" if "axis" in ctx_lower else ("flow_node" if "flow" in ctx_lower else "figure_text")
    archetype = "flow_diagram" if "flow" in ctx_lower else ""
    return diagnose_label_token(text, path="inline", locator=context or "text", surface=surface, archetype=archetype)


def extract_table_text(path: Path) -> list[dict]:
    """Convenience helper to audit an xlsx table path."""
    return inspect_xlsx_table(path)


def extract_figure_text(path_or_dict: Path | dict, project: Path | None = None) -> list[dict]:
    """Convenience helper to audit a figure entry or sidecar."""
    if isinstance(path_or_dict, Path):
        if path_or_dict.suffix.lower() == ".json":
            try:
                data = json.loads(path_or_dict.read_text(encoding="utf-8"))
            except Exception:
                return []
            entry = {"id": path_or_dict.stem.split(".")[0], "file": str(path_or_dict.with_suffix(".png"))}
            proj = project if project is not None else path_or_dict.parent.parent
            return inspect_figure_entry(proj, entry, art_override=data)
        elif path_or_dict.suffix.lower() == ".svg":
            texts = _svg_texts(path_or_dict)
            issues = []
            for t in texts:
                issues.extend(diagnose_label_token(t, path=str(path_or_dict), locator="svg_text", surface="figure_text"))
            return _dedup(issues)
    elif isinstance(path_or_dict, dict) and project is not None:
        return inspect_figure_entry(project, path_or_dict)
    return []

