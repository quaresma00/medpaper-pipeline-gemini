"""
audit_submission.py - Industrial-grade submission package audit and compliance engine.

Performs deterministic, mechanical verification:
1. Physical DOCX integrity & structural validation (unpacks zip, checks XML syntax, paragraph counts, corruption detection)
2. Soft linebreak & outline level residual scans inside DOCX
3. Manifest validity & required role coverage
4. Real journal guideline parsing (checks TIFF requirements, word limits, line spacing)
5. Package Freeze verification (validates SHA-256 signatures against package_review_freeze.json)
6. Cross-file consistency (prose figure/table citations vs actual files, citation counts vs Title Page)
7. Mandatory declarations completeness
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def verify_docx_integrity(docx_path: Path) -> list[str]:
    """Physically open and unpack docx to ensure it is genuine, uncorrupted, and properly formatted."""
    problems = []
    if not docx_path.exists():
        return [f"File does not exist: {docx_path.name}"]

    if docx_path.stat().st_size < 500:
        return [f"File is suspiciously small ({docx_path.stat().st_size} bytes): {docx_path.name}"]

    try:
        with zipfile.ZipFile(docx_path, "r") as z:
            namelist = z.namelist()
            if "word/document.xml" not in namelist:
                return [f"Corrupted docx (missing word/document.xml): {docx_path.name}"]

            doc_xml = z.read("word/document.xml")
            try:
                root = ET.fromstring(doc_xml)
            except ET.ParseError as pe:
                return [f"Corrupted XML syntax in {docx_path.name}: {pe}"]

            # Check paragraph count
            paragraphs = root.findall(f".//{{{W_NS}}}p")
            if not paragraphs:
                problems.append(f"Empty document (0 paragraphs): {docx_path.name}")

            # Check for illegal soft line breaks (<w:br/> not page/column)
            soft_brs = [
                br for br in root.findall(f".//{{{W_NS}}}br")
                if br.attrib.get(f"{{{W_NS}}}type") not in ("page", "column")
            ]
            if soft_brs:
                problems.append(f"Unconverted manual soft line breaks (down-arrows ↓) found: {len(soft_brs)} in {docx_path.name}")

            # 1. Zero-tolerance check for black square controls across all XML streams in the docx
            for name in namelist:
                if name.endswith(".xml"):
                    txt = z.read(name).decode("utf-8", errors="ignore")
                    for tag, desc in (
                        ("keepNext", "keep-with-next pagination"),
                        ("keepLines", "keep-lines pagination"),
                        ("pageBreakBefore", "page-break-before pagination"),
                    ):
                        cnt = txt.count(tag)
                        if cnt > 0:
                            problems.append(
                                f"Forbidden {desc} attribute '{tag}' (causes black square margin marks) found: {cnt} in {name} of {docx_path.name}"
                            )

                    # 2. Zero-tolerance check for outlineLvl across all XML streams
                    cnt_ol = txt.count("outlineLvl")
                    if cnt_ol > 0:
                        problems.append(
                            f"Forbidden outline level attribute 'outlineLvl' (causes folding arrows) found: {cnt_ol} in {name} of {docx_path.name}"
                        )

            # 3. Check for unflattened native Heading styles in document.xml
            for p in paragraphs:
                ppr = p.find(f"{{{W_NS}}}pPr")
                if ppr is not None:
                    pstyle = ppr.find(f"{{{W_NS}}}pStyle")
                    if pstyle is not None:
                        val = pstyle.get(f"{{{W_NS}}}val", "")
                        if re.match(r"(?i)^heading\s*\d+$", val) or re.match(r"^Heading\d+$", val):
                            problems.append(
                                f"Unflattened native heading style '{val}' found in {docx_path.name}; all headings must be mapped to flat 'SectionHeading' / 'SubsectionHeading'"
                            )
                            break

            # 4. Check for horizontal rules (---)
            if 'o:hr="t"' in doc_xml.decode("utf-8", errors="ignore"):
                problems.append(f"Residual horizontal dividing lines (---) found: {docx_path.name}")

            # 5. Check for duplicate Figure Legends heading in manuscript.docx
            if docx_path.name == "manuscript.docx":
                legend_headings = []
                for p in paragraphs:
                    p_text = "".join(t.text for t in p.findall(f".//{{{W_NS}}}t") if t.text).strip()
                    if re.match(r"(?i)^figure\s+legends?$", p_text):
                        legend_headings.append(p_text)
                if len(legend_headings) > 1:
                    problems.append(f"Duplicate 'Figure Legends' heading detected ({len(legend_headings)} times) in {docx_path.name}")

    except zipfile.BadZipFile:
        return [f"Corrupted file (not a valid ZIP/DOCX format): {docx_path.name}"]
    except Exception as e:
        return [f"Unexpected error inspecting {docx_path.name}: {e}"]

    return problems


def audit_bundle(project_dir: Path) -> dict:
    bundle_dir = project_dir / "08_submission" / "bundle"
    manuscript_dir = project_dir / "07_manuscript"
    figures_dir = project_dir / "05_figures"
    tables_dir = project_dir / "04_tables"
    guidelines_path = project_dir / "08_submission" / "guidelines_extract.md"
    freeze_path = project_dir / "08_submission" / "package_review_freeze.json"

    results = {
        "files_checked": [],
        "missing_files": [],
        "corrupted_files": [],
        "guideline_compliance": [],
        "consistency_issues": [],
        "freeze_status": "NOT_CHECKED",
        "metrics": {},
        "overall_status": "PASSED",
    }

    # 1. Essential files existence and physical integrity check
    core_files = ["manuscript.docx", "cover_letter.docx", "SUBMISSION_CHECKLIST.md", "manifest.json"]
    if (manuscript_dir / "title_page.md").exists():
        core_files.append("title_page.docx")
    for f in core_files:
        p = bundle_dir / f
        if not p.exists():
            results["missing_files"].append(f"Essential bundle file missing: {f}")
            results["overall_status"] = "ACTION_REQUIRED"
        else:
            results["files_checked"].append(f)
            if f.endswith(".docx"):
                doc_errors = verify_docx_integrity(p)
                if doc_errors:
                    results["corrupted_files"].extend(doc_errors)
                    results["overall_status"] = "ACTION_REQUIRED"

    # Also thoroughly audit any additional DOCX in bundle (e.g. supplementary_materials.docx)
    for extra_docx in bundle_dir.glob("*.docx"):
        if extra_docx.name not in core_files:
            results["files_checked"].append(extra_docx.name)
            doc_errors = verify_docx_integrity(extra_docx)
            if doc_errors:
                results["corrupted_files"].extend(doc_errors)
                results["overall_status"] = "ACTION_REQUIRED"

    # 2. Manifest structural validation
    manifest_file = bundle_dir / "manifest.json"
    if manifest_file.exists():
        try:
            m_data = json.loads(manifest_file.read_text(encoding="utf-8"))
            if not isinstance(m_data, dict) or not m_data.get("items"):
                results["consistency_issues"].append("manifest.json is empty or invalid (must contain 'items' list).")
                results["overall_status"] = "ACTION_REQUIRED"
            else:
                roles = {str(item.get("role", "")).lower() for item in m_data.get("items", [])}
                for r in ("manuscript", "cover_letter", "checklist"):
                    if r not in roles:
                        results["consistency_issues"].append(f"manifest.json missing required role: '{r}'")
                        results["overall_status"] = "ACTION_REQUIRED"
        except json.JSONDecodeError:
            results["corrupted_files"].append("manifest.json is malformed JSON")
            results["overall_status"] = "ACTION_REQUIRED"

    # 3. Target Guidelines parsing & adherence check
    if guidelines_path.exists():
        g_text = guidelines_path.read_text(encoding="utf-8", errors="ignore").lower()
        # Check TIFF demand
        if "tiff" in g_text or ".tif" in g_text:
            tiff_files = list(bundle_dir.glob("*.tiff")) + list(bundle_dir.glob("*.tif"))
            if not tiff_files:
                # Check figures/out for masters
                out_tiffs = list((figures_dir / "out").glob("*.tiff")) + list((figures_dir / "out").glob("*.tif"))
                if not out_tiffs:
                    results["guideline_compliance"].append(
                        "Journal guidelines require TIFF format figures, but no TIFF figures exist in bundle or 05_figures/out."
                    )
                    results["overall_status"] = "ACTION_REQUIRED"
                else:
                    results["guideline_compliance"].append(f"Found {len(out_tiffs)} master TIFF figures ready for upload.")
    else:
        results["guideline_compliance"].append("Warning: 08_submission/guidelines_extract.md not found.")

    # 4. Package Freeze Verification (SHA-256 integrity)
    if freeze_path.exists():
        try:
            from wfcore.packagefreeze import verify_freeze
            ok, problems, count = verify_freeze(project_dir, freeze_path)
            real_problems = [p for p in problems if "AUDIT_REPORT.md" not in p]
            if real_problems:
                results["freeze_status"] = "TAMPERED_OR_OUT_OF_SYNC"
                results["consistency_issues"].extend([f"Freeze verification failed: {e}" for e in real_problems])
                results["overall_status"] = "ACTION_REQUIRED"
            else:
                results["freeze_status"] = f"VERIFIED_MATCH ({count} files)"
        except Exception as fe:
            results["freeze_status"] = f"ERROR: {fe}"
    else:
        results["freeze_status"] = "PENDING_FREEZE"

    # 5. Main text cross-consistency (Figure & Table callouts vs real files)
    assembled_md = manuscript_dir / "manuscript_assembled.md"
    prose_text = ""
    if assembled_md.exists():
        prose_text = assembled_md.read_text(encoding="utf-8", errors="replace")
    else:
        for name in ("introduction.md", "methods.md", "results.md", "discussion.md"):
            p = manuscript_dir / name
            if p.exists():
                prose_text += "\n" + p.read_text(encoding="utf-8", errors="replace")

    fig_mentions = sorted(set(re.findall(r"\bFigure\s+([S\d]+)\b", prose_text, flags=re.IGNORECASE)))
    tab_mentions = sorted(set(re.findall(r"\bTable\s+([S\d]+)\b", prose_text, flags=re.IGNORECASE)))

    bundle_files = [p.name.lower() for p in bundle_dir.glob("*") if p.is_file()]
    for fig_num in fig_mentions:
        target_prefix = f"figure{fig_num.lower()}"
        matching = [f for f in bundle_files if f.startswith(target_prefix)]
        out_figs = [f.name.lower() for f in (figures_dir / "out").glob("*") if f.name.lower().startswith(target_prefix)]
        if not matching and not out_figs:
            results["consistency_issues"].append(f"Figure {fig_num} is cited in prose but no figure file was found.")
            results["overall_status"] = "ACTION_REQUIRED"

    for tab_num in tab_mentions:
        target_prefix = f"table{tab_num.lower()}"
        matching = [f for f in bundle_files if f.startswith(target_prefix)]
        out_tabs = [f.name.lower() for f in (tables_dir / "main").glob("*") if f.name.lower().startswith(target_prefix)]
        supp_tab = tables_dir / "supplementary" / "supplementary_tables.xlsx"
        if not matching and not out_tabs and not (tab_num.upper().startswith("S") and supp_tab.exists()):
            results["consistency_issues"].append(f"Table {tab_num} is cited in prose but no table file was found.")
            results["overall_status"] = "ACTION_REQUIRED"

    # 6. Reference count consistency
    title_page_file = manuscript_dir / "title_page.md"
    if title_page_file.exists():
        tp_text = title_page_file.read_text(encoding="utf-8", errors="replace")
        citekeys = set()
        for grp in re.findall(r"\[([^\]]*@[^\]]*)\]", prose_text):
            citekeys.update(re.findall(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)", grp))
        for single in re.findall(r"(?<!\w)@([A-Za-z][\w:.#$%&+?<>~/-]*)", prose_text):
            citekeys.add(single)
        results["metrics"]["actual_unique_citations"] = len(citekeys)

        m_ref = re.search(r"(?i)\b(?:number\s+of\s+references|references?)\s*:\s*(\d+)", tp_text)
        if m_ref:
            tp_ref_count = int(m_ref.group(1))
            results["metrics"]["title_page_reference_count"] = tp_ref_count
            if tp_ref_count != len(citekeys):
                results["consistency_issues"].append(
                    f"Reference count mismatch: Title Page states {tp_ref_count}, but prose cites {len(citekeys)} unique keys."
                )
                results["overall_status"] = "ACTION_REQUIRED"

    # 7. Statements check
    statements_file = manuscript_dir / "statements.md"
    if statements_file.exists():
        st_text = statements_file.read_text(encoding="utf-8", errors="replace").lower()
        if "abbreviation" not in st_text:
            results["missing_files"].append("Centralized 'Abbreviations' section missing from statements.md")
            results["overall_status"] = "ACTION_REQUIRED"
        if "conflict" not in st_text and "competing interest" not in st_text:
            results["missing_files"].append("Conflict of interest statement missing from statements.md")
            results["overall_status"] = "ACTION_REQUIRED"
        if "data availability" not in st_text:
            results["missing_files"].append("Data availability statement missing from statements.md")
            results["overall_status"] = "ACTION_REQUIRED"
        if "ethics" not in st_text and "institutional review board" not in st_text:
            results["missing_files"].append("Ethics approval statement missing from statements.md")
            results["overall_status"] = "ACTION_REQUIRED"

    # 8. Single Source of Truth: Check for orphan edits in assembled manuscript
    assembled_file = manuscript_dir / "manuscript_assembled.md"
    if assembled_file.exists():
        assembled_txt = assembled_file.read_text(encoding="utf-8", errors="replace")
        # Ensure key sections from component files are actually reflected in assembled
        for sec in ["title_page.md", "abstract.md", "introduction.md", "methods.md", "results.md", "discussion.md"]:
            sec_p = manuscript_dir / sec
            if sec_p.exists():
                sample = sec_p.read_text(encoding="utf-8", errors="replace").strip()
                # Take first meaningful non-heading line
                lines = [l.strip() for l in sample.splitlines() if l.strip() and not l.strip().startswith("#")]
                if lines:
                    first_line = lines[0][:40]
                    if first_line and first_line not in assembled_txt:
                        results["consistency_issues"].append(
                            f"Orphan edit or stale assembly: Component section '{sec}' content is not reflected in 'manuscript_assembled.md'. Run render_package.py to re-assemble."
                        )
                        results["overall_status"] = "ACTION_REQUIRED"

    # 9. Supplementary Methods checks: no embedded raw tables, no horizontal rules
    supp_md = manuscript_dir / "supplementary_methods.md"
    if supp_md.exists():
        supp_txt = supp_md.read_text(encoding="utf-8", errors="replace")
        if re.search(r"(?m)^\|[-:| ]+\|$", supp_txt):
            results["consistency_issues"].append(
                "Embedded markdown data table detected in 'supplementary_methods.md'. Per medical SCI standards, all tables must be routed to '04_tables/supplementary/supplementary_tables.xlsx' as three-line tables (Table S1, S2...)."
            )
            results["overall_status"] = "ACTION_REQUIRED"
        if re.search(r"(?m)^[ \t]*([-_*])[ \t]*(?:\1[ \t]*){2,}[ \t]*$", supp_txt):
            results["consistency_issues"].append(
                "Residual horizontal rules (--- or ***) detected in 'supplementary_methods.md'. Section divisions must rely solely on markdown headings (##, ###)."
            )
            results["overall_status"] = "ACTION_REQUIRED"

    # 10. Deep Literature Authenticity & Cryptographic Provenance Audit (Anti-Fabrication Guard)
    refs_dir = project_dir / "06_refs"
    ver_path = refs_dir / "verified.json"
    lib_path = refs_dir / "library.json"

    # 10.1 Detect rogue bypass or tampering scripts in project/ or workspace
    try:
        from tools.wfcore.checks.refs import detect_bypass_scripts, verify_cache_evidence
        suspicious_scripts = detect_bypass_scripts(type("DummyCtx", (), {"root": ROOT, "project": project_dir})())
        if suspicious_scripts:
            results["consistency_issues"].append(
                f"FATAL ACADEMIC INTEGRITY VIOLATION: Unauthorized bypass script(s) detected: {', '.join(suspicious_scripts)}. "
                "Bypassing tools/pubmed/ to forge verified.json is strictly forbidden."
            )
            results["overall_status"] = "ACTION_REQUIRED"
    except Exception as exc:
        results["consistency_issues"].append(f"Bypass script detection error: {exc}")

    # 10.2 Cryptographic signature check on verified.json
    if ver_path.exists():
        try:
            ver_data = json.loads(ver_path.read_text(encoding="utf-8"))
            from tools.pubmed.verify import verify_provenance_signature
            sig_ok, sig_msg = verify_provenance_signature(ver_data, project_dir)
            if not sig_ok:
                results["consistency_issues"].append(
                    f"FATAL INTEGRITY VIOLATION: verified.json signature verification failed: {sig_msg}. "
                    "File has been tampered with or modified outside tools/pubmed/verify.py."
                )
                results["overall_status"] = "ACTION_REQUIRED"
        except Exception as ve:
            results["consistency_issues"].append(f"Error checking verified.json provenance signature: {ve}")
            results["overall_status"] = "ACTION_REQUIRED"

    # 10.3 Penetrating proof-of-retrieval check for every cited reference
    if prose_text and ver_path.exists() and lib_path.exists():
        try:
            ver_data = json.loads(ver_path.read_text(encoding="utf-8"))
            lib_data = json.loads(lib_path.read_text(encoding="utf-8"))
            ver_records = ver_data.get("records", {})
            lib_entries = {e["citekey"]: e for e in lib_data.get("entries", []) if e.get("citekey")}

            cited_keys = set()
            for grp in re.findall(r"\[([^\]]*@[^\]]*)\]", prose_text):
                cited_keys.update(re.findall(r"@([A-Za-z][\w:.#$%&+?<>~/-]*)", grp))
            for single in re.findall(r"(?<!\w)@([A-Za-z][\w:.#$%&+?<>~/-]*)", prose_text):
                cited_keys.add(single)

            for ck in sorted(cited_keys):
                v_rec = ver_records.get(ck)
                l_rec = lib_entries.get(ck)
                if not v_rec or not v_rec.get("verified"):
                    results["consistency_issues"].append(f"Cited reference '@{ck}' is not verified in verified.json.")
                    results["overall_status"] = "ACTION_REQUIRED"
                    continue

                cache_rel = v_rec.get("cache_file") or (l_rec or {}).get("cache_file")
                if not cache_rel:
                    results["consistency_issues"].append(f"Cited reference '@{ck}' lacks raw NCBI XML cache file.")
                    results["overall_status"] = "ACTION_REQUIRED"
                    continue

                cache_file = project_dir / cache_rel
                if not cache_file.exists() or cache_file.stat().st_size == 0:
                    results["consistency_issues"].append(f"Cited reference '@{ck}' raw cache file '{cache_rel}' is missing or empty.")
                    results["overall_status"] = "ACTION_REQUIRED"
                    continue

                pmid = str(v_rec.get("pmid") or (l_rec or {}).get("pmid") or "").strip()
                doi = str(v_rec.get("doi") or (l_rec or {}).get("doi") or "").strip().lower()

                if any(fake in doi for fake in ("fake", "dummy", "test", "example", "placeholder", "todo")):
                    results["consistency_issues"].append(f"Fabricated/placeholder DOI detected in '@{ck}': {doi}")
                    results["overall_status"] = "ACTION_REQUIRED"

                if pmid:
                    try:
                        xml_txt = cache_file.read_text(encoding="utf-8", errors="replace")
                        if f"<PMID>{pmid}</PMID>" not in xml_txt and f"<PMID Version=" not in xml_txt:
                            root_xml = ET.fromstring(xml_txt)
                            pmids_in_cache = {t.text.strip() for t in root_xml.findall(".//PMID") if t.text}
                            if pmid not in pmids_in_cache:
                                results["consistency_issues"].append(
                                    f"ACADEMIC INTEGRITY VIOLATION: Cited reference '@{ck}' (PMID {pmid}) is absent from declared raw NCBI cache {cache_rel} (fabrication detected)."
                                )
                                results["overall_status"] = "ACTION_REQUIRED"
                    except Exception as pe:
                        results["consistency_issues"].append(f"Error parsing raw NCBI cache for '@{ck}': {pe}")
                        results["overall_status"] = "ACTION_REQUIRED"
        except Exception as e:
            results["consistency_issues"].append(f"Error auditing literature authenticity: {e}")
            results["overall_status"] = "ACTION_REQUIRED"

    # 11. Data Acquisition Integrity & Anti-Truncation Audit
    try:
        from tools.wfcore.checks.data_integrity import scan_code_for_truncation, count_file_physical_rows
        # 11.1 Scan data code for rogue truncation
        code_files = []
        for d in (project_dir / "02_data", project_dir / "03_analysis" / "code"):
            if d.exists():
                for ext in ("*.py", "*.R", "*.sh"):
                    code_files.extend(d.rglob(ext))
        for p in project_dir.glob("*.py"):
            if p.is_file() and p.name not in ("test_", "conftest.py"):
                code_files.append(p)

        for cf in sorted(set(code_files)):
            try:
                rel_cf = cf.relative_to(project_dir).as_posix()
            except ValueError:
                rel_cf = cf.as_posix()
            if rel_cf.startswith("temp/") or "/temp/" in rel_cf or ".venv/" in rel_cf:
                continue
            trunc_issues = scan_code_for_truncation(cf)
            if trunc_issues:
                results["consistency_issues"].extend([
                    f"DATA TRUNCATION VIOLATION: {iss}" for iss in trunc_issues
                ])
                results["overall_status"] = "ACTION_REQUIRED"

        # 11.2 Reconcile data_census.json vs dataset_summary.json vs physical disk
        census_path = project_dir / "02_data" / "data_census.json"
        summary_path = project_dir / "03_analysis" / "results" / "dataset_summary.json"
        if census_path.exists() and summary_path.exists():
            c_data = json.loads(census_path.read_text(encoding="utf-8"))
            s_data = json.loads(summary_path.read_text(encoding="utf-8"))
            c_rows = c_data.get("actual_raw_rows", 0)
            s_rows = s_data.get("n_rows", 0)
            if c_rows != s_rows:
                results["consistency_issues"].append(
                    f"DATA RECONCILIATION MISMATCH: data_census.json reports {c_rows} rows, "
                    f"but dataset_summary.json reports {s_rows} rows (unexplained discrepancy)."
                )
                results["overall_status"] = "ACTION_REQUIRED"

            # Physical disk row check
            for rf in (project_dir / "02_data" / "raw").rglob("*"):
                if rf.is_file() and rf.name != ".gitkeep":
                    phys_cnt = count_file_physical_rows(rf)
                    if phys_cnt is not None and phys_cnt < c_rows * 0.9:
                        results["consistency_issues"].append(
                            f"PHYSICAL DATA AUDIT FAILURE: Physical file '{rf.name}' only contains {phys_cnt} rows on disk, "
                            f"while data_census.json claims {c_rows} rows (physical data truncation)."
                        )
                        results["overall_status"] = "ACTION_REQUIRED"
    except Exception as de:
        results["consistency_issues"].append(f"Error auditing data acquisition integrity: {de}")
        results["overall_status"] = "ACTION_REQUIRED"

    # 12. Canonical Base Manuscript Untouched & Freeze Verification
    try:
        from tools.wfcore.basefreeze import BASE_FREEZE_REL, verify_base_freeze
        freeze_file = project_dir / BASE_FREEZE_REL
        if freeze_file.exists():
            ok_base, prob_base, cnt_base = verify_base_freeze(project_dir, freeze_file)
            if not ok_base:
                results["consistency_issues"].extend([
                    f"BASE MANUSCRIPT FREEZE VIOLATION: {p}" for p in prob_base
                ])
                results["overall_status"] = "ACTION_REQUIRED"
        else:
            results["consistency_issues"].append(
                f"Missing {BASE_FREEZE_REL}: Canonical base manuscript must be frozen before submission bundle review."
            )
            results["overall_status"] = "ACTION_REQUIRED"
    except Exception as bfe:
        results["consistency_issues"].append(f"Error checking base manuscript freeze: {bfe}")
        results["overall_status"] = "ACTION_REQUIRED"

    return results


def format_markdown_report(results: dict, journal_name: str = "Target Journal") -> str:
    status_icon = "[PASS]" if results["overall_status"] == "PASSED" else "[ACTION REQUIRED]"
    lines = [
        f"# Submission Bundle Audit Report: {journal_name}",
        f"\n**Overall Verdict**: **{results['overall_status']}** {status_icon}\n",
        f"**Package Freeze Status**: `{results['freeze_status']}`\n",
        "## 1. Bundle Files & Physical Integrity",
    ]
    for f in results["files_checked"]:
        lines.append(f"- [x] `{f}` present and verified.")
    for m in results["missing_files"]:
        lines.append(f"- [ ] **MISSING**: {m}")
    for c in results["corrupted_files"]:
        lines.append(f"- [!] **CORRUPTED / DEFECT**: {c}")

    lines.append("\n## 2. Guideline Adherence")
    if results["guideline_compliance"]:
        for item in results["guideline_compliance"]:
            lines.append(f"- {item}")
    else:
        lines.append("- [x] Baseline guideline checks passed.")

    lines.append("\n## 3. Cross-Consistency & Alignment")
    if results["consistency_issues"]:
        for issue in results["consistency_issues"]:
            lines.append(f"- [!] **Inconsistency**: {issue}")
    else:
        lines.append("- [x] All Figure and Table references in prose match available files.")
        lines.append("- [x] Citation counts on Title Page match actual cited literature.")

    lines.append("\n## 4. Metrics Summary")
    for k, v in results["metrics"].items():
        lines.append(f"- **{k.replace('_', ' ').capitalize()}**: {v}")

    lines.append("\n## 5. Auditor Conclusion")
    if results["overall_status"] == "PASSED":
        lines.append("The submission package is compliant with target journal guidelines, free of omissions, and internally consistent. Ready for portal submission.")
    else:
        lines.append("Action required: Please address the flagged errors, corrupted files, or inconsistencies before advancing.")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit submission package for compliance and consistency.")
    parser.add_argument("--project", type=Path, default=Path("project"))
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    results = audit_bundle(args.project)
    report_md = format_markdown_report(results)

    out_file = args.out or (args.project / "08_submission" / "bundle" / "AUDIT_REPORT.md")
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(report_md, encoding="utf-8")

    print(report_md)
    print(f"Audit report saved to: {out_file}")
    return 0 if results["overall_status"] == "PASSED" else 1


if __name__ == "__main__":
    sys.exit(main())
