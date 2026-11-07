"""Display-item placement and supplemental filename verification (v1.28+).

Rules enforced:
1. Default medical-journal convention when guidelines are silent:
   - Figures are NOT embedded in ``manuscript.docx``; they are uploaded as separate files and
     ``manuscript.docx`` keeps only ``# Figure legends`` at the end.
   - Main tables are placed AFTER ``# References``, each on its own separate page.
2. Override rule: switching figures or tables to ``embedded_in_text`` (or tables to
   ``separate_files_only``) is permitted ONLY when backed by a verified verbatim quote from the
   captured official journal guidelines — never by AI judgement.
3. Supplemental filenames must follow ``Supplemental_File_<N>_<Descriptive_Name>.<ext>``
   (e.g., ``Supplemental_File_1_Supplementary_Methods.docx``), numbered 1..K without gaps,
   rejecting terse labels like ``ESM1`` unless an official guideline quote mandates a literal
   machine filename pattern.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from .authorblock import verify_sourced_clause
from .packagefreeze import _safe_path

REQ_REL = "08_submission/submission_requirements.json"
MANIFEST_REL = "08_submission/bundle/manifest.json"
INTEGRATION_MS_REL = "08_submission/integration/full_manuscript.md"

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

FENCE_RE = re.compile(r"```.*?```", re.S)
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)|<img\b", re.I)
PIPE_DIVIDER_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
GRID_TABLE_RE = re.compile(r"^\s*\+[=-]{3,}(?:\+[=-]{3,})+\+\s*$", re.M)

SUPP_ROLES = {
    "supplementary",
    "supplementary_methods",
    "supplementary_tables",
    "supplementary_figures",
    "supp_table",
    "supp_tables",
    "supp_figure",
    "supp_figures",
    "supplement",
    "supplemental",
}
TERSE_SUPP_STEM_RE = re.compile(
    r"^(?:esm\d*|supp(?:lement(?:al|ary)?)?[_-]?\d*|appendix[_-]?\d*|s\d+|mmc\d+)$",
    re.I,
)
SUPP_FILENAME_RE = re.compile(
    r"^Supplemental_File_([1-9]\d*)_([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)\.([A-Za-z0-9]+)$"
)
GENERIC_SUPP_DESC_RE = re.compile(
    r"^(?:esm\d*|supp(?:lement(?:al|ary)?)?\d*|file\d*|doc(?:ument)?\d*|item\d*|appendix\d*|material\d*|data\d*|\d+)$",
    re.I,
)


def _load_plan(project: Path) -> dict:
    for rel in ("08_submission/integration/artifact_plan.json", "01_protocol/artifact_plan.json"):
        path = project / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
    return {}


def display_placement_policy(project: Path) -> tuple[str, str, list[str]]:
    """Return (figures_mode, tables_mode, problems)."""
    figures_mode = "separate_files"
    tables_mode = "after_references"
    problems: list[str] = []

    req_path = project / REQ_REL
    if not req_path.is_file():
        return figures_mode, tables_mode, problems
    try:
        req = json.loads(req_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return figures_mode, tables_mode, [f"{REQ_REL}: invalid JSON ({exc})"]

    dp = req.get("display_placement")
    if dp is None:
        return figures_mode, tables_mode, problems
    if not isinstance(dp, dict):
        return figures_mode, tables_mode, ["display_placement must be an object when present"]

    fig_cfg = dp.get("figures")
    if fig_cfg is not None:
        if fig_cfg == "separate_files" or (isinstance(fig_cfg, dict) and fig_cfg.get("mode", "separate_files") == "separate_files"):
            figures_mode = "separate_files"
        elif isinstance(fig_cfg, dict) and fig_cfg.get("mode") == "embedded_in_text":
            figures_mode = "embedded_in_text"
            problems.extend(verify_sourced_clause(project, fig_cfg, "display_placement.figures"))
        else:
            problems.append(
                "display_placement.figures defaults to 'separate_files'; switching to 'embedded_in_text' "
                "requires an object with mode='embedded_in_text' and a verified verbatim official guideline quote"
            )

    tbl_cfg = dp.get("tables")
    if tbl_cfg is not None:
        if tbl_cfg == "after_references" or (isinstance(tbl_cfg, dict) and tbl_cfg.get("mode", "after_references") == "after_references"):
            tables_mode = "after_references"
        elif isinstance(tbl_cfg, dict) and tbl_cfg.get("mode") in {"embedded_in_text", "separate_files_only"}:
            tables_mode = str(tbl_cfg["mode"])
            problems.extend(verify_sourced_clause(project, tbl_cfg, "display_placement.tables"))
        else:
            problems.append(
                "display_placement.tables defaults to 'after_references'; switching to 'embedded_in_text' or "
                "'separate_files_only' requires an object with a verified verbatim official guideline quote"
            )

    return figures_mode, tables_mode, problems


def markdown_display_problems(
    text: str,
    *,
    figures_mode: str = "separate_files",
    tables_mode: str = "after_references",
) -> list[str]:
    """Check Markdown manuscript source for unauthorized inline figures or body tables."""
    cleaned = FENCE_RE.sub(" ", text)
    problems: list[str] = []
    if figures_mode != "embedded_in_text" and MD_IMAGE_RE.search(cleaned):
        problems.append(
            "figures must not be embedded in manuscript Markdown unless official guidelines explicitly "
            "require inline figures; upload figures as separate files and retain only '# Figure legends'"
        )
    if tables_mode != "embedded_in_text":
        before_refs = re.split(r"(?mi)^#\s+References\s*$", cleaned)[0]
        if (
            any(PIPE_DIVIDER_RE.match(line) for line in before_refs.splitlines())
            or re.search(r"<table\b", before_refs, re.I)
            or GRID_TABLE_RE.search(before_refs)
        ):
            problems.append(
                "tables must not be embedded in the manuscript body before References unless official "
                "guidelines explicitly require inline tables; append native three-line tables after References"
            )
    return problems


def docx_embedded_media_problems(docx_path: Path, *, allow_embedded_figures: bool = False) -> list[str]:
    """Reject any embedded image/media in a manuscript DOCX unless explicitly authorized by guidelines."""
    if allow_embedded_figures:
        return []
    try:
        with zipfile.ZipFile(docx_path) as zf:
            media = [n for n in zf.namelist() if n.startswith("word/media/")]
            doc_xml = zf.read("word/document.xml")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        return [f"{docx_path.name}: unreadable DOCX ({exc})"]

    try:
        root = ET.fromstring(doc_xml)
    except ET.ParseError as exc:
        return [f"{docx_path.name}: invalid document.xml ({exc})"]

    has_drawing = any(
        node.tag.rsplit("}", 1)[-1] in {"drawing", "pict", "imagedata"}
        for node in root.iter()
    )
    if media or has_drawing:
        return [
            f"{docx_path.name}: embedded image/figure found in main manuscript; figures must be uploaded "
            "as separate files with only '# Figure legends' in the manuscript unless official guidelines "
            "explicitly mandate inline figures"
        ]
    return []


def _paragraph_has_page_or_section_break(p_elem: ET.Element) -> bool:
    ppr = p_elem.find("w:pPr", NS)
    if ppr is not None and ppr.find("w:sectPr", NS) is not None:
        return True
    for br in p_elem.findall(".//w:br", NS):
        if br.get(f"{{{W_NS}}}type") == "page":
            return True
    return False


def docx_table_placement_problems(
    docx_path: Path,
    project: Path | None = None,
    *,
    tables_mode: str = "after_references",
    check_planned_main_tables: bool = False,
) -> list[str]:
    """Verify table placement inside manuscript DOCX according to journal policy."""
    try:
        with zipfile.ZipFile(docx_path) as zf:
            root = ET.fromstring(zf.read("word/document.xml"))
    except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError) as exc:
        return [f"{docx_path.name}: cannot inspect table placement ({exc})"]

    body = root.find("w:body", NS)
    if body is None:
        return [f"{docx_path.name}: missing w:body"]

    ref_aliases = {"references"}
    if project is not None:
        from .journalspec import aliases, load as load_target
        try:
            mapped = aliases(load_target(project))
            if "References" in mapped:
                ref_aliases.add(mapped["References"].strip().casefold())
        except Exception:  # noqa: BLE001
            pass

    children = list(body)
    ref_index: int | None = None
    table_indices: list[int] = []
    table_ids: list[str] = []

    for idx, elem in enumerate(children):
        local = elem.tag.rsplit("}", 1)[-1]
        if local == "p":
            txt = "".join(t.text or "" for t in elem.findall(".//w:t", NS)).strip()
            if txt.casefold() in ref_aliases and ref_index is None:
                ref_index = idx
        elif local == "tbl":
            table_indices.append(idx)
            cap = elem.find("w:tblPr/w:tblCaption", NS)
            val = cap.get(f"{{{W_NS}}}val", "") if cap is not None else ""
            if val.startswith("medpaper-threeline:"):
                table_ids.append(val.split(":", 1)[1].strip())

    problems: list[str] = []
    if tables_mode == "separate_files_only":
        if table_indices:
            problems.append(
                f"{docx_path.name}: journal rule requires tables as separate files only, "
                f"but {len(table_indices)} table(s) appear inside manuscript.docx"
            )
        return problems

    if tables_mode == "embedded_in_text":
        if check_planned_main_tables and project is not None:
            planned_main = [
                str(item.get("id", "")).strip()
                for item in _load_plan(project).get("main_tables", [])
                if str(item.get("id", "")).strip()
            ]
            if planned_main and not table_indices:
                problems.append(
                    f"{docx_path.name}: display_placement.tables is 'embedded_in_text' "
                    "but no tables are embedded in manuscript.docx"
                )
        return problems

    # Default medical-journal rule: tables_mode == "after_references", one table per page.
    if table_indices:
        if ref_index is None:
            problems.append(f"{docx_path.name}: contains table(s) without a preceding References section")
        else:
            before_ref = [i for i in table_indices if i < ref_index]
            if before_ref:
                problems.append(
                    f"{docx_path.name}: {len(before_ref)} table(s) appear before References; "
                    "main tables must be placed after References unless official guidelines explicitly require inline tables"
                )
            # First table after References must be separated from preceding text by a page/section break.
            after_ref = [i for i in table_indices if i > ref_index]
            if after_ref:
                first_tbl = after_ref[0]
                has_initial_break = any(
                    children[k].tag.rsplit("}", 1)[-1] == "p" and _paragraph_has_page_or_section_break(children[k])
                    for k in range(ref_index, first_tbl)
                )
                if not has_initial_break:
                    problems.append(
                        f"{docx_path.name}: first table after References does not start on a new page"
                    )
                for prev_tbl, next_tbl in zip(after_ref, after_ref[1:]):
                    has_between_break = any(
                        children[k].tag.rsplit("}", 1)[-1] == "p" and _paragraph_has_page_or_section_break(children[k])
                        for k in range(prev_tbl + 1, next_tbl)
                    )
                    if not has_between_break:
                        problems.append(
                            f"{docx_path.name}: multiple tables share a page; each table after References must occupy its own page"
                        )

    if check_planned_main_tables and project is not None:
        planned_main = [
            str(item.get("id", "")).strip()
            for item in _load_plan(project).get("main_tables", [])
            if str(item.get("id", "")).strip()
        ]
        if planned_main:
            found_cf = {tid.casefold() for tid in table_ids}
            missing = [tid for tid in planned_main if tid.casefold() not in found_cf]
            if missing:
                problems.append(
                    f"{docx_path.name}: planned main table(s) missing after References ({', '.join(missing)}); "
                    "pass --tables-json to build_docx.py so each main table appears on its own page after References"
                )
    return problems


def verify_display_placement(project: Path, stage_id: str) -> list[str]:
    """Stage gate helper enforcing figure and table placement across S20-S25."""
    figures_mode, tables_mode, problems = display_placement_policy(project)
    if stage_id == "S20_journal":
        return problems

    ms_md = project / INTEGRATION_MS_REL
    if ms_md.is_file():
        problems.extend(
            markdown_display_problems(
                ms_md.read_text(encoding="utf-8", errors="replace"),
                figures_mode=figures_mode,
                tables_mode=tables_mode,
            )
        )

    if stage_id not in {"S23_package", "S24_package_human_review", "S25_submission_audit"}:
        return problems

    manifest_path = project / MANIFEST_REL
    if not manifest_path.is_file():
        return problems + [f"{MANIFEST_REL} missing"]
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return problems + [f"{MANIFEST_REL}: invalid JSON ({exc})"]

    ms_docx: Path | None = None
    separate_figure_uploads = 0
    for item in manifest.get("items", []):
        if item.get("upload", True) is False:
            continue
        role = str(item.get("role", "")).strip().casefold()
        raw = str(item.get("file", "")).strip()
        if not raw:
            continue
        try:
            _, resolved = _safe_path(project, raw)
        except ValueError as exc:
            problems.append(str(exc))
            continue
        if role == "manuscript" and resolved.suffix.lower() == ".docx" and resolved.is_file():
            ms_docx = resolved
        if role in {"figure", "figures", "main_figure", "main_figures"} or (
            resolved.suffix.lower() in {".pdf", ".tif", ".tiff", ".eps", ".png", ".jpg", ".jpeg"}
            and role not in SUPP_ROLES
        ):
            separate_figure_uploads += 1

    if ms_docx is None:
        problems.append("manifest lacks a built manuscript DOCX")
        return problems

    problems.extend(
        docx_embedded_media_problems(ms_docx, allow_embedded_figures=(figures_mode == "embedded_in_text"))
    )
    problems.extend(
        docx_table_placement_problems(
            ms_docx,
            project,
            tables_mode=tables_mode,
            check_planned_main_tables=(tables_mode == "after_references"),
        )
    )

    plan = _load_plan(project)
    planned_main_figs = [f for f in plan.get("main_figures", []) if str(f.get("id", "")).strip()]
    if figures_mode == "separate_files" and planned_main_figs and separate_figure_uploads < len(planned_main_figs):
        problems.append(
            f"planned {len(planned_main_figs)} main figure(s) must be listed as separate upload files in manifest.json "
            f"(found {separate_figure_uploads})"
        )
    return problems


def _is_supplemental_item(role: str, filename: str) -> bool:
    role_cf = role.strip().casefold()
    if role_cf in SUPP_ROLES:
        return True
    stem = Path(filename).stem
    if TERSE_SUPP_STEM_RE.match(stem) or stem.lower().startswith(("supplemental_", "supplementary_")):
        return True
    return False


def supplemental_filename_problems(project: Path, manifest: dict | None = None) -> list[str]:
    """Validate Supplemental_File_<N>_<Description>.<ext> naming on all supplemental uploads."""
    if manifest is None:
        manifest_path = project / MANIFEST_REL
        if not manifest_path.is_file():
            return [f"{MANIFEST_REL} missing"]
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"{MANIFEST_REL}: invalid JSON ({exc})"]

    problems: list[str] = []
    custom_regex: re.Pattern[str] | None = None
    req_path = project / REQ_REL
    if req_path.is_file():
        try:
            req = json.loads(req_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            req = {}
        rule = req.get("supplemental_filename_rule")
        if rule is not None:
            rule_problems = verify_sourced_clause(project, rule, "supplemental_filename_rule")
            if rule_problems:
                problems.extend(rule_problems)
            else:
                pat = str(rule.get("pattern", "")).strip()
                if not pat:
                    problems.append("supplemental_filename_rule.pattern must be a non-empty regex")
                else:
                    try:
                        custom_regex = re.compile(pat)
                    except re.error as exc:
                        problems.append(f"supplemental_filename_rule.pattern invalid regex ({exc})")

    numbers: list[int] = []
    seen_names: set[str] = set()
    for item in manifest.get("items", []):
        if item.get("upload", True) is False:
            continue
        role = str(item.get("role", "")).strip()
        raw = str(item.get("file", "")).strip()
        if not raw:
            continue
        name = Path(raw).name
        if not _is_supplemental_item(role, name):
            continue
        if name.casefold() in seen_names:
            problems.append(f"duplicate supplemental upload filename: {name}")
        seen_names.add(name.casefold())

        if custom_regex is not None:
            if not custom_regex.match(name):
                problems.append(f"{name}: does not match journal-mandated supplemental_filename_rule pattern")
            continue

        match = SUPP_FILENAME_RE.match(name)
        if not match:
            problems.append(
                f"{name}: supplemental upload must be named 'Supplemental_File_<N>_<Specific_Description>.<ext>' "
                "(e.g. 'Supplemental_File_1_Supplementary_Methods.docx'), never terse names like 'ESM1' or unnumbered files"
            )
            continue
        num = int(match.group(1))
        desc = match.group(2)
        numbers.append(num)
        if len(desc) < 5 or GENERIC_SUPP_DESC_RE.match(desc):
            problems.append(
                f"{name}: supplemental description {desc!r} is too terse or generic; state what the file contains "
                "(e.g. 'Supplementary_Methods', 'Supplementary_Tables', 'Supplementary_Figures')"
            )

    if custom_regex is None and numbers:
        if len(set(numbers)) != len(numbers):
            problems.append(f"supplemental file numbers contain duplicates: {sorted(numbers)}")
        elif sorted(numbers) != list(range(1, len(numbers) + 1)):
            problems.append(
                f"supplemental file numbers must be sequential 1..{len(numbers)} without gaps (got {sorted(numbers)})"
            )
    return problems
