#!/usr/bin/env python3
"""v1.28 regression suite:
1. Single-source author block on page 1 of non-blinded manuscript.docx, optional verified
   separate title_page.docx, and strict double-blind separation.
2. Default medical-journal display placement (figures as separate uploads with legends at end;
   main tables one per page after References) unless overridden by a verified verbatim official
   guideline quote.
3. Isolated Discussion brief (no tables, no display callout numbers), mandatory pre-draft 6-part
   outline lock, automated anti-restatement & supplementary-callout discipline, and dedicated
   Discussion audit across S18/S19/S24/S25 reviews.
4. Sequential descriptive supplemental filenames: Supplemental_File_<N>_<Description>.<ext>.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from docx import Document  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from tables.threeline import ci, fmt, p_value, write_table  # noqa: E402
from wfcore import authorblock, discussion, registry, submissionlayout, submissionqc, wordtables  # noqa: E402
from wfcore.buildproof import content_digest  # noqa: E402
from wfcore.checks import Ctx, get, load_all  # noqa: E402
from wfcore.readiness import atomic_json  # noqa: E402
from wfcore.state import State  # noqa: E402


def _progress(label: str) -> None:
    print(f"[1.28 regression] {label}", flush=True)


def _rmtree_onerror(func, path, _exc_info) -> None:
    Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
    func(path)


def _sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _setup_journal_profile(
    project: Path,
    guide_text: str,
    *,
    blinded: bool = False,
    with_journal_context: bool = False,
) -> None:
    """Create target_journal.json + guidelines_extract.md, and optionally journal_context.json."""
    from datetime import datetime, timezone
    from wfcore import journalcontext as jc

    target = {
        "journal": "Journal of Clinical Cohort Medicine",
        "issn": "1234-5678",
        "publisher": "Academic Medical Press",
        "article_type": "Original Research",
        "submission_stage": "initial",
        "guidelines_url": "https://journal.example.org/instructions-for-authors",
        "blinded_main_manuscript": blinded,
        "spelling": "american",
        "abstract_structure": ["Background", "Methods", "Results", "Conclusions"],
        "keywords_min": 3,
        "keywords_max": 6,
    }
    (project / "08_submission").mkdir(parents=True, exist_ok=True)
    atomic_json(project / "08_submission/target_journal.json", target)
    (project / "08_submission/guidelines_extract.md").write_text(guide_text, encoding="utf-8")

    ctx_path = project / "08_submission/journal_context.json"
    if not with_journal_context:
        ctx_path.unlink(missing_ok=True)
        return

    guide_rel = "08_submission/guidelines_snapshot.txt"
    guide_path = project / guide_rel
    raw = guide_text.encode("utf-8")
    guide_path.write_bytes(raw)
    digest = _sha256_bytes(raw)
    ident = jc.identity(target)
    context_id = jc.digest({"identity": ident, "attempt": "test128"})
    ctx = {
        "schema_version": 1,
        "attempt_id": "test128",
        "identity": ident,
        "context_id": context_id,
        "sources": {
            "author_guide": {
                "role": "instructions_for_authors",
                "url": target["guidelines_url"],
                "final_url": target["guidelines_url"],
                "context_id": context_id,
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "raw": guide_rel,
                "raw_sha256": digest,
                "text": guide_rel,
                "text_sha256": digest,
            }
        },
    }
    atomic_json(ctx_path, ctx)


def _default_style() -> dict:
    return {
        "font_family": "Times New Roman",
        "body_font_pt": 12,
        "title_font_pt": 14,
        "section_heading_font_pt": 12,
        "subsection_heading_font_pt": 12,
        "line_spacing": 2.0,
        "paragraph_spacing_after_pt": 0,
        "paper_size": "LETTER",
        "margins_in": 1.0,
        "page_numbers": True,
        "all_text_black": True,
        "external_hyperlinks": False,
        "reference_separator": "space",
        "figure_legend_scope": "main",
    }


def _default_author_info() -> dict:
    return {
        "authors": [
            {
                "name": "Lin Mei",
                "affiliations": ["1", "2"],
                "orcid": "0000-0002-1825-0097",
            },
            {
                "name": "Carlos Rivera",
                "affiliations": ["2"],
                "orcid": None,
                "orcid_absent_reason": "Co-author has not registered an ORCID identifier.",
            },
        ],
        "affiliations": [
            {"id": "1", "name": "Department of Cardiology, Starlight Medical Centre, 100083 Cityville"},
            {"id": "2", "name": "Institute of Clinical Epidemiology, Northern University, 200120 Townsville"},
        ],
        "corresponding": {
            "name": "Lin Mei",
            "email": "lead.author@example.org",
            "address": "Department of Cardiology, Starlight Medical Centre, 100083 Cityville",
            "orcid": "0000-0002-1825-0097",
        },
    }


def _write_minimal_manuscript_assets(project: Path) -> None:
    """Create minimal manuscript MD, bib, CSL, tables XLSX, figure PNG, and style JSON."""
    for sub in (
        "00_input",
        "01_protocol",
        "04_tables/main",
        "05_figures/out",
        "06_refs",
        "07_manuscript",
        "08_submission/integration",
        "08_submission/bundle",
    ):
        (project / sub).mkdir(parents=True, exist_ok=True)

    atomic_json(project / "00_input/author_info.json", _default_author_info())
    atomic_json(project / "08_submission/docx_style.json", _default_style())

    write_table(
        path=project / "04_tables/main/Table1.xlsx",
        sheet="Table 1",
        title="Table 1. Baseline characteristics by treatment strategy.",
        header=["Characteristic", "Early group (n=320)", "Delayed group (n=320)", "P value"],
        rows=[
            ["Age, years, mean (SD)", f"{fmt(63.4)} ({fmt(10.8)})", f"{fmt(64.1)} ({fmt(11.2)})", p_value(0.41)],
            ["Primary outcome, HR (95% CI)", ci(0.74, 0.58, 0.94), "Reference", p_value(0.014)],
        ],
        footnotes=["Abbreviations: CI, confidence interval; HR, hazard ratio; SD, standard deviation."],
    )
    write_table(
        path=project / "04_tables/main/Table2.xlsx",
        sheet="Table 2",
        title="Table 2. Prespecified subgroup and sensitivity analyses.",
        header=["Subgroup", "HR (95% CI)", "P value"],
        rows=[
            ["Age >= 65 years", ci(0.71, 0.52, 0.97), p_value(0.031)],
            ["Chronic kidney disease", ci(0.76, 0.55, 1.04), p_value(0.088)],
        ],
        footnotes=["Abbreviations: CI, confidence interval; HR, hazard ratio."],
    )
    (project / "05_figures/out/Figure1.png").write_bytes(b"\x89PNG\r\n\x1a\nfakefigure")

    plan = {
        "main_figures": [
            {
                "id": "Figure 1",
                "slug": "km_outcome",
                "title": "Cumulative incidence of the primary outcome",
                "file": "05_figures/out/Figure1.png",
            }
        ],
        "main_tables": [
            {
                "id": "Table 1",
                "slug": "baseline",
                "title": "Baseline characteristics",
                "file": "04_tables/main/Table1.xlsx",
                "sheet": "Table 1",
            },
            {
                "id": "Table 2",
                "slug": "subgroups",
                "title": "Subgroup analyses",
                "file": "04_tables/main/Table2.xlsx",
                "sheet": "Table 2",
            },
        ],
        "supp_figures": [],
        "supp_tables": [],
        "supp_files": [],
    }
    atomic_json(project / "01_protocol/artifact_plan.json", plan)
    atomic_json(
        project / "08_submission/integration/main_tables.json",
        {
            "tables": [
                {"id": "Table 1", "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1", "orientation": "portrait"},
                {"id": "Table 2", "file": "04_tables/main/Table2.xlsx", "sheet": "Table 2", "orientation": "portrait"},
            ]
        },
    )

    (project / "06_refs/refs.bib").write_text(
        "@article{smith2024cardio,\n"
        "  author = {Smith, John and Patel, Priya},\n"
        "  title = {Early Decongestion in Acute Heart Failure},\n"
        "  journal = {Circulation Research},\n"
        "  year = {2024},\n"
        "  volume = {134},\n"
        "  pages = {101--112}\n"
        "}\n",
        encoding="utf-8",
    )
    csl_candidates = list((ROOT / "reference").rglob("*.csl"))
    if csl_candidates:
        shutil.copy2(csl_candidates[0], project / "08_submission/journal.csl")
    else:
        (project / "08_submission/journal.csl").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<style xmlns="http://purl.org/net/xbiblio/csl" class="in-text" version="1.0">\n'
            '  <info><title>Minimal Test Style</title><id>http://www.zotero.org/styles/minimal-test</id></info>\n'
            '  <citation><layout prefix="[" suffix="]" delimiter=","><text variable="citation-number"/></layout></citation>\n'
            '  <bibliography><layout><text variable="citation-number" suffix=". "/><text variable="title"/></layout></bibliography>\n'
            '</style>\n',
            encoding="utf-8",
        )

    ms_md = (
        "# Early Guided Decongestion and Clinical Outcomes in Hospitalized Heart Failure\n\n"
        "# Abstract\n\n"
        "**Background:** Optimal timing of guided decongestion remains uncertain.\n\n"
        "**Methods:** We studied 640 hospitalized adults across two tertiary centers.\n\n"
        "**Results:** Early guided therapy lowered the primary composite endpoint.\n\n"
        "**Conclusions:** Early guided decongestion improved post-discharge event-free survival.\n\n"
        "Keywords: heart failure, decongestion, cohort study, prognosis\n\n"
        "# Introduction\n\n"
        "Residual congestion drives early readmission after acute heart failure [@smith2024cardio].\n\n"
        "# Methods\n\n"
        "Consecutive adults admitted between 2021 and 2024 were followed for 12 months.\n\n"
        "# Results\n\n"
        "Baseline characteristics were balanced across groups (Table 1), and subgroup estimates were consistent (Table 2) with cumulative incidence separation (Figure 1).\n\n"
        "# Discussion\n\n"
        "Early physiological guidance aligned diuretic intensity with intravascular refill and reduced post-discharge decompensation [@smith2024cardio].\n\n"
        "# Declarations and Statements\n\n"
        "Funding: Institutional academic support only.\n\n"
        "# References\n\n"
        "::: {#refs}\n:::\n\n"
        "# Figure legends\n\n"
        "## Figure 1.\n"
        "Cumulative incidence of the primary composite outcome over 12 months in the early versus delayed guided decongestion groups.\n"
    )
    (project / "08_submission/integration/full_manuscript.md").write_text(ms_md, encoding="utf-8")
    (project / "08_submission/cover_letter.md").write_text(
        "# Cover Letter\n\nDear Editors,\n\nPlease consider our original manuscript for publication.\n",
        encoding="utf-8",
    )


def _run_tool(project: Path, script_rel: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["MEDPAPER_PROJECT"] = str(project)
    env["MEDPAPER_ROOT"] = str(ROOT)
    return subprocess.run(
        [sys.executable, str(ROOT / script_rel), *args],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class AuthorPlacementAndSingleSourceTests(unittest.TestCase):
    """Requirement 1: Non-blinded page-1 single-source authors, verified separate title page, and double-blind."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="medpaper-author-128-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, onerror=_rmtree_onerror))
        self.project = self.tmp / "project"
        _write_minimal_manuscript_assets(self.project)
        self.state = State(self.project).create("medpaper", "1.28.0", "S23_package")
        self.pipe = registry.load()
        load_all()

    def test_author_schema_requires_affiliations_contact_and_orcid(self) -> None:
        _progress("author_info.json schema validation (contact + ORCID)")
        bad = {
            "authors": [{"name": "Lin Mei", "affiliations": ["1"]}],
            "affiliations": [{"id": "1", "name": "Department of Cardiology"}],
            "corresponding": {"name": "Lin Mei", "email": "lead.author@example.org"},
        }
        errs = authorblock.validate_author_info(bad, strict=True)
        self.assertTrue(any("orcid" in e.lower() for e in errs), errs)
        self.assertTrue(any("contact" in e.lower() for e in errs), errs)
        self.assertEqual(authorblock.validate_author_info(_default_author_info(), strict=True), [])

    def test_non_blinded_default_puts_authors_on_page1_and_blocks_extra_title_page(self) -> None:
        _progress("non-blinded default: page-1 manuscript authors + block unrequested title_page.docx")
        _setup_journal_profile(
            self.project,
            "Manuscripts should be double-spaced in Times New Roman 12 pt. Upload main manuscript and figures.",
            blinded=False,
        )
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {"required_upload_roles": ["manuscript", "cover_letter"]},
        )

        # Leftover title_page.md is automatically removed by author_block.py sync when not required.
        stale_tp = self.project / "08_submission/integration/title_page.md"
        stale_tp.write_text("# Old stale title page\n", encoding="utf-8")
        sync_res = _run_tool(self.project, "tools/manuscript/author_block.py", "sync", "--project", str(self.project))
        self.assertEqual(sync_res.returncode, 0, sync_res.stderr)
        self.assertFalse(stale_tp.exists())

        if not shutil.which("pandoc"):
            self.skipTest("pandoc not installed")

        ms_out = self.project / "08_submission/bundle/manuscript.docx"
        cl_out = self.project / "08_submission/bundle/cover_letter.docx"
        b1 = _run_tool(
            self.project,
            "tools/manuscript/build_docx.py",
            "build",
            "--kind",
            "manuscript",
            "--input",
            str(self.project / "08_submission/integration/full_manuscript.md"),
            "--output",
            str(ms_out),
            "--style-config",
            str(self.project / "08_submission/docx_style.json"),
            "--bibliography",
            str(self.project / "06_refs/refs.bib"),
            "--csl",
            str(self.project / "08_submission/journal.csl"),
            "--tables-json",
            str(self.project / "08_submission/integration/main_tables.json"),
        )
        self.assertEqual(b1.returncode, 0, b1.stderr + b1.stdout)
        b2 = _run_tool(
            self.project,
            "tools/manuscript/build_docx.py",
            "build",
            "--kind",
            "cover_letter",
            "--input",
            str(self.project / "08_submission/cover_letter.md"),
            "--output",
            str(cl_out),
            "--style-config",
            str(self.project / "08_submission/docx_style.json"),
        )
        self.assertEqual(b2.returncode, 0, b2.stderr + b2.stdout)

        # Verify page-1 author lines preserve exact institution spelling ("Centre") and postal code ("100083")
        # and survive build_docx.py finalize with identical content_digest.
        digest_before = content_digest(ms_out)
        fin = _run_tool(
            self.project,
            "tools/manuscript/build_docx.py",
            "finalize",
            "--kind",
            "manuscript",
            "--output",
            str(ms_out),
            "--style-config",
            str(self.project / "08_submission/docx_style.json"),
        )
        self.assertEqual(fin.returncode, 0, fin.stderr + fin.stdout)
        self.assertEqual(content_digest(ms_out), digest_before)

        title, front = authorblock._docx_front_paragraphs(ms_out)
        self.assertIn("Early Guided Decongestion", title)
        self.assertEqual(len(front), 4)
        self.assertTrue(front[0].startswith("Authors: Lin Mei [1,2]*, Carlos Rivera [2]"))
        self.assertIn("Starlight Medical Centre, 100083 Cityville", front[1])
        self.assertIn("lead.author@example.org", front[2])
        self.assertIn("0000-0002-1825-0097", front[3])

        shutil.copy2(self.project / "05_figures/out/Figure1.png", self.project / "08_submission/bundle/Figure_1.png")
        manifest = {
            "items": [
                {"role": "manuscript", "file": "08_submission/bundle/manuscript.docx", "upload": True},
                {"role": "cover_letter", "file": "08_submission/bundle/cover_letter.docx", "upload": True},
                {"role": "figure", "file": "08_submission/bundle/Figure_1.png", "upload": True},
            ]
        }
        atomic_json(self.project / "08_submission/bundle/manifest.json", manifest)

        stage = self.pipe.stage("S23_package")
        ctx = Ctx(self.pipe, self.state, self.project, stage, {})
        res = get("author_placement_consistent")(ctx)
        self.assertTrue(res.ok, res.detail)

        # Audit manifest without a separate title_page.docx passes cleanly.
        aud = _run_tool(
            self.project,
            "tools/manuscript/build_docx.py",
            "audit",
            "--manifest",
            str(self.project / "08_submission/bundle/manifest.json"),
            "--style-config",
            str(self.project / "08_submission/docx_style.json"),
        )
        self.assertEqual(aud.returncode, 0, aud.stdout + aud.stderr)

        # Adding an unrequested title_page upload for a non-blinded journal is blocked.
        manifest["items"].append({"role": "title_page", "file": "08_submission/bundle/cover_letter.docx", "upload": True})
        atomic_json(self.project / "08_submission/bundle/manifest.json", manifest)
        res_bad = get("author_placement_consistent")(ctx)
        self.assertFalse(res_bad.ok)
        self.assertIn("must NOT upload a separate title_page.docx", res_bad.detail)

    def test_non_blinded_explicit_separate_title_page_and_double_blind_modes(self) -> None:
        _progress("non-blinded verified separate title page + double-blind anonymity")
        if not shutil.which("pandoc"):
            self.skipTest("pandoc not installed")

        # 1. Fabricated quote not present in captured guide must be rejected (journal_context.json path).
        _setup_journal_profile(
            self.project,
            "Authors must upload a separate Title Page file containing full author names, affiliations, corresponding author contact details, and ORCID iDs.",
            blinded=False,
            with_journal_context=True,
        )
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {
                "required_upload_roles": ["manuscript", "title_page", "cover_letter"],
                "separate_title_page": {
                    "status": "required",
                    "source_id": "author_guide",
                    "locator": "Submission Files, paragraph 2",
                    "quote": "This sentence does not exist anywhere in the official journal guide.",
                },
            },
        )
        probs_fake = authorblock.verify_author_placement(self.project, "S20_journal")
        self.assertTrue(any("not found in captured official source" in p for p in probs_fake), probs_fake)

        # Verify journal_context.json passes when verbatim quote matches, then run full DOCX builds via guidelines_extract.md.
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {
                "required_upload_roles": ["manuscript", "title_page", "cover_letter"],
                "separate_title_page": {
                    "status": "required",
                    "source_id": "author_guide",
                    "locator": "Submission Files, paragraph 2",
                    "quote": "Authors must upload a separate Title Page file containing full author names, affiliations",
                },
            },
        )
        self.assertEqual(authorblock.verify_author_placement(self.project, "S20_journal"), [])

        # 2. Authentic verbatim quote passes; both manuscript.docx and title_page.docx share identical single-source lines.
        _setup_journal_profile(
            self.project,
            "Authors must upload a separate Title Page file containing full author names, affiliations, corresponding author contact details, and ORCID iDs.",
            blinded=False,
            with_journal_context=False,
        )
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {
                "required_upload_roles": ["manuscript", "title_page", "cover_letter"],
                "separate_title_page": {
                    "status": "required",
                    "source": "https://journal.example.org/instructions-for-authors",
                    "locator": "Submission Files, paragraph 2",
                    "quote": "Authors must upload a separate Title Page file containing full author names, affiliations",
                },
            },
        )
        sync_ok = _run_tool(self.project, "tools/manuscript/author_block.py", "sync", "--project", str(self.project))
        self.assertEqual(sync_ok.returncode, 0, sync_ok.stderr)
        tp_md = self.project / "08_submission/integration/title_page.md"
        self.assertTrue(tp_md.is_file())

        ms_out = self.project / "08_submission/bundle/manuscript.docx"
        tp_out = self.project / "08_submission/bundle/title_page.docx"
        cl_out = self.project / "08_submission/bundle/cover_letter.docx"
        for kind, inp, out in (
            ("manuscript", self.project / "08_submission/integration/full_manuscript.md", ms_out),
            ("title_page", tp_md, tp_out),
            ("cover_letter", self.project / "08_submission/cover_letter.md", cl_out),
        ):
            extra = (
                [
                    "--bibliography",
                    str(self.project / "06_refs/refs.bib"),
                    "--csl",
                    str(self.project / "08_submission/journal.csl"),
                    "--tables-json",
                    str(self.project / "08_submission/integration/main_tables.json"),
                ]
                if kind == "manuscript"
                else []
            )
            r = _run_tool(
                self.project,
                "tools/manuscript/build_docx.py",
                "build",
                "--kind",
                kind,
                "--input",
                str(inp),
                "--output",
                str(out),
                "--style-config",
                str(self.project / "08_submission/docx_style.json"),
                *extra,
            )
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)

        atomic_json(
            self.project / "08_submission/bundle/manifest.json",
            {
                "items": [
                    {"role": "manuscript", "file": "08_submission/bundle/manuscript.docx", "upload": True},
                    {"role": "title_page", "file": "08_submission/bundle/title_page.docx", "upload": True},
                    {"role": "cover_letter", "file": "08_submission/bundle/cover_letter.docx", "upload": True},
                ]
            },
        )
        self.assertEqual(authorblock.verify_author_placement(self.project, "S23_package"), [])
        self.assertEqual(authorblock._docx_front_paragraphs(ms_out), authorblock._docx_front_paragraphs(tp_out))

        # Tampering with title_page.md triggers single-source mismatch detection.
        tp_md.write_text(tp_md.read_text(encoding="utf-8").replace("Carlos Rivera", "Carlos X. Rivera"), encoding="utf-8")
        mismatch = authorblock.verify_author_placement(self.project, "S23_package")
        self.assertTrue(any("diverges from single-source" in p for p in mismatch), mismatch)

        # 3. Double-blind mode: manuscript.docx stays strictly anonymous; authors live only in title_page.docx.
        _setup_journal_profile(
            self.project,
            "Double-blind peer review: keep the main manuscript completely anonymous and submit a separate Title Page.",
            blinded=True,
        )
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {"required_upload_roles": ["manuscript", "title_page", "cover_letter"]},
        )
        _run_tool(self.project, "tools/manuscript/author_block.py", "sync", "--project", str(self.project))
        r_blind = _run_tool(
            self.project,
            "tools/manuscript/build_docx.py",
            "build",
            "--kind",
            "manuscript",
            "--input",
            str(self.project / "08_submission/integration/full_manuscript.md"),
            "--output",
            str(ms_out),
            "--style-config",
            str(self.project / "08_submission/docx_style.json"),
            "--bibliography",
            str(self.project / "06_refs/refs.bib"),
            "--csl",
            str(self.project / "08_submission/journal.csl"),
            "--tables-json",
            str(self.project / "08_submission/integration/main_tables.json"),
        )
        self.assertEqual(r_blind.returncode, 0, r_blind.stderr + r_blind.stdout)
        _, blind_front = authorblock._docx_front_paragraphs(ms_out)
        self.assertEqual(blind_front, [])
        self.assertEqual(authorblock.verify_author_placement(self.project, "S23_package"), [])


class DisplayPlacementTests(unittest.TestCase):
    """Requirement 2: Default separate figures + one-table-per-page after References, and verified quote overrides."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="medpaper-layout-128-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, onerror=_rmtree_onerror))
        self.project = self.tmp / "project"
        _write_minimal_manuscript_assets(self.project)
        _setup_journal_profile(
            self.project,
            "Submit text in Word format. Do not embed figures unless requested.",
            blinded=False,
        )
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {"required_upload_roles": ["manuscript", "cover_letter"]},
        )

    def test_markdown_and_docx_block_embedded_figures_and_inline_tables_by_default(self) -> None:
        _progress("default display placement: block inline figures/tables & require 1 table/page after References")
        md_with_img = "# Title\n\n# Results\n\n![Figure 1](05_figures/out/Figure1.png)\n\n# References\n"
        probs_img = submissionlayout.markdown_display_problems(md_with_img)
        self.assertTrue(any("figures must not be embedded" in p for p in probs_img), probs_img)

        md_with_tbl = "# Title\n\n# Results\n\n| Group | HR |\n| --- | --- |\n| Early | 0.74 |\n\n# References\n"
        probs_tbl = submissionlayout.markdown_display_problems(md_with_tbl)
        self.assertTrue(any("tables must not be embedded" in p for p in probs_tbl), probs_tbl)

        # Build a DOCX with an unauthorized w:drawing / media entry and verify rejection.
        bad_docx = self.project / "08_submission/bundle/bad_media.docx"
        doc = Document()
        doc.add_paragraph("Title")
        doc.add_paragraph("Abstract")
        p = doc.add_paragraph()
        p._p.append(OxmlElement("w:drawing"))
        doc.save(bad_docx)
        media_probs = submissionlayout.docx_embedded_media_problems(bad_docx, allow_embedded_figures=False)
        self.assertTrue(any("embedded image/figure found" in x for x in media_probs), media_probs)

        # Build a DOCX where a table sits BEFORE References and verify rejection.
        before_ref_docx = self.project / "08_submission/bundle/before_ref.docx"
        doc2 = Document()
        doc2.add_paragraph("Results")
        t = doc2.add_table(rows=2, cols=2)
        t.cell(0, 0).text = "Col1"
        doc2.add_paragraph("References")
        doc2.save(before_ref_docx)
        tbl_probs = submissionlayout.docx_table_placement_problems(before_ref_docx, self.project)
        self.assertTrue(any("appear before References" in x for x in tbl_probs), tbl_probs)

        # Build a DOCX where two tables sit after References on the SAME page without a break and verify rejection.
        same_page_docx = self.project / "08_submission/bundle/same_page_tables.docx"
        doc3 = Document()
        doc3.add_paragraph("References")
        doc3.add_paragraph("1. Smith J. Circ Res 2024.")
        brk_p = doc3.add_paragraph()
        r = brk_p.add_run()
        br = OxmlElement("w:br")
        br.set(qn("w:type"), "page")
        r._r.append(br)
        doc3.add_table(rows=2, cols=2)
        doc3.add_paragraph("Table 2 caption without page break")
        doc3.add_table(rows=2, cols=2)
        doc3.save(same_page_docx)
        same_probs = submissionlayout.docx_table_placement_problems(same_page_docx, self.project)
        self.assertTrue(any("multiple tables share a page" in x for x in same_probs), same_probs)

        # Build a compliant DOCX using wordtables.append_tables (one section/page per table after References).
        good_docx = self.project / "08_submission/bundle/manuscript.docx"
        doc_ok = Document()
        doc_ok.add_paragraph("Early Guided Decongestion and Clinical Outcomes in Hospitalized Heart Failure")
        doc_ok.add_paragraph("Abstract")
        doc_ok.add_paragraph("References")
        doc_ok.add_paragraph("1. Smith J, Patel P. Circ Res. 2024;134:101-112.")
        doc_ok.add_paragraph("Figure legends")
        doc_ok.add_paragraph("Figure 1. Cumulative incidence curve.")
        entries, _ = wordtables.load_spec(self.project, self.project / "08_submission/integration/main_tables.json")
        wordtables.append_tables(doc_ok, self.project, entries, _default_style())
        doc_ok.save(good_docx)

        self.assertEqual(
            submissionlayout.docx_table_placement_problems(
                good_docx,
                self.project,
                tables_mode="after_references",
                check_planned_main_tables=True,
            ),
            [],
        )

        # Verify S23 gate requires separate figure upload when figures_mode == "separate_files".
        shutil.copy2(self.project / "05_figures/out/Figure1.png", self.project / "08_submission/bundle/Figure_1.png")
        atomic_json(
            self.project / "08_submission/bundle/manifest.json",
            {"items": [{"role": "manuscript", "file": "08_submission/bundle/manuscript.docx", "upload": True}]},
        )
        missing_fig = submissionlayout.verify_display_placement(self.project, "S23_package")
        self.assertTrue(any("separate upload files in manifest.json" in x for x in missing_fig), missing_fig)

        atomic_json(
            self.project / "08_submission/bundle/manifest.json",
            {
                "items": [
                    {"role": "manuscript", "file": "08_submission/bundle/manuscript.docx", "upload": True},
                    {"role": "figure", "file": "08_submission/bundle/Figure_1.png", "upload": True},
                ]
            },
        )
        self.assertEqual(submissionlayout.verify_display_placement(self.project, "S23_package"), [])

    def test_inline_display_override_requires_verified_guideline_quote(self) -> None:
        _progress("display_placement override: block AI judgement, allow verified verbatim guideline quote")
        # Bare string override without official quote must fail.
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {
                "required_upload_roles": ["manuscript", "cover_letter"],
                "display_placement": {"figures": "embedded_in_text", "tables": "embedded_in_text"},
            },
        )
        _, _, pol_err = submissionlayout.display_placement_policy(self.project)
        self.assertEqual(len(pol_err), 2)

        # Captured guide explicitly mandates inline placement -> verified quote unlocks embedded_in_text.
        _setup_journal_profile(
            self.project,
            "For initial review, figures and tables must be embedded directly in the main manuscript text near their first citation.",
            blinded=False,
            with_journal_context=True,
        )
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {
                "required_upload_roles": ["manuscript", "cover_letter"],
                "display_placement": {
                    "figures": {
                        "mode": "embedded_in_text",
                        "source_id": "author_guide",
                        "locator": "Formatting, Initial Submission",
                        "quote": "figures and tables must be embedded directly in the main manuscript text",
                    },
                    "tables": {
                        "mode": "embedded_in_text",
                        "source_id": "author_guide",
                        "locator": "Formatting, Initial Submission",
                        "quote": "figures and tables must be embedded directly in the main manuscript text",
                    },
                },
            },
        )
        fig_mode, tbl_mode, pol_ok = submissionlayout.display_placement_policy(self.project)
        self.assertEqual(pol_ok, [])
        self.assertEqual((fig_mode, tbl_mode), ("embedded_in_text", "embedded_in_text"))

        # Test native three-line inline embedding via embed_tables_in_text.
        inline_docx = self.project / "08_submission/bundle/inline_ms.docx"
        doc = Document()
        doc.add_paragraph("Title")
        doc.add_paragraph("Results")
        doc.add_paragraph("Baseline characteristics are summarized in Table 1 and subgroups in Table 2.")
        doc.add_paragraph("References")
        entries, _ = wordtables.load_spec(self.project, self.project / "08_submission/integration/main_tables.json")
        wordtables.embed_tables_in_text(doc, self.project, entries, _default_style())
        doc.save(inline_docx)
        self.assertEqual(wordtables.table_problems(Document(inline_docx)), [])
        self.assertEqual(
            submissionlayout.docx_table_placement_problems(
                inline_docx,
                self.project,
                tables_mode="embedded_in_text",
                check_planned_main_tables=True,
            ),
            [],
        )


class DiscussionWorkflowAndAuditTests(unittest.TestCase):
    """Requirement 3: Isolated brief, locked 6-part outline before prose, discipline checks, and review audit."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="medpaper-disc-128-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, onerror=_rmtree_onerror))
        self.project = self.tmp / "project"
        for sub in ("01_protocol", "03_analysis", "06_refs/deepread", "07_manuscript", "08_submission"):
            (self.project / sub).mkdir(parents=True, exist_ok=True)
        self.state = State(self.project).create("medpaper", "1.28.0", "S16_discussion")
        self.pipe = registry.load()
        load_all()

        atomic_json(
            self.project / "01_protocol/study_facts.json",
            {
                "clinical_question": "Whether early physiology-guided decongestion lowers 12-month heart failure readmission or death.",
                "main_finding": "Early guided therapy was associated with a meaningful reduction in composite events (see Table 2 and Figure 1).",
                "cannot_claim": "Observational cohort design precludes definitive causal inference despite propensity overlap weighting.",
            },
        )
        (self.project / "07_manuscript/results.md").write_text(
            "# Results\n\n"
            "Among 640 hospitalized patients, early physiology-guided decongestion was associated with a lower 12-month incidence of death or heart failure readmission compared with delayed standard titration (18.4% vs 27.2%; hazard ratio 0.74, 95% CI 0.58 to 0.94; P = 0.014; Table 1, Figure 1).\n\n"
            "Prespecified subgroup analyses across age strata, baseline kidney function, and ejection fraction phenotypes demonstrated consistent directional benefit without significant interaction (Table 2, Supplementary Table S1).\n",
            encoding="utf-8",
        )

    def _valid_outline_text(self) -> str:
        return (
            "# Discussion outline\n\n"
            "## Principal findings\n"
            "Early physiology-guided decongestion was associated with a clinically meaningful reduction in 12-month post-discharge mortality or heart failure rehospitalization across two tertiary centers.\n\n"
            "## Comparison with prior studies and reasons for differences\n"
            "Prior neutral trials enrolled lower-risk euvolaemic patients and initiated titration late; our stronger association reflects earlier natriuresis-guided adjustment in congested inpatients.\n\n"
            "## Potential mechanisms\n"
            "Timely sodium excretion coupled to plasma refill monitoring may relieve venous renal congestion while avoiding intravascular underfilling and neurohormonal rebound.\n\n"
            "## Clinical implications\n"
            "Routine early spot urinary sodium and congestion profiling can guide bedside loop-diuretic escalation before discharge readiness assessment.\n\n"
            "## Limitations and direction of bias\n"
            "Unmeasured frailty or clinician preference could introduce residual confounding, though preferential use in sicker patients would bias estimates conservatively toward the null.\n\n"
            "## Conclusion\n"
            "Early physiology-guided decongestion was associated with improved 12-month event-free survival and warrants pragmatic randomized evaluation.\n"
        )

    def test_brief_isolation_and_outline_before_draft_gate(self) -> None:
        _progress("S16 Discussion: table-free/callout-free brief + mandatory 6-part outline lock before prose")
        scaf = _run_tool(self.project, "tools/manuscript/discussion_brief.py", "scaffold", "--project", str(self.project))
        self.assertEqual(scaf.returncode, 0, scaf.stderr)
        self.assertEqual(discussion.validate_brief(self.project), [])

        # Injecting a table or Table/Figure number into discussion_brief.md is immediately blocked.
        brief_path = self.project / "07_manuscript/discussion_brief.md"
        clean_brief = brief_path.read_text(encoding="utf-8")
        brief_path.write_text(clean_brief + "\nSee Table 1 and 04_tables/main/Table1.xlsx.\n| A | B |\n| --- | --- |\n| 1 | 2 |\n", encoding="utf-8")
        bad_brief = discussion.validate_brief(self.project)
        self.assertTrue(any("must not contain any result tables" in p for p in bad_brief), bad_brief)
        self.assertTrue(any("must not contain table/figure numbers" in p for p in bad_brief), bad_brief)
        brief_path.write_text(clean_brief, encoding="utf-8")

        # Outline missing one of the 6 sections or missing direction of bias is rejected.
        outline_path = self.project / "07_manuscript/discussion_outline.md"
        outline_path.write_text(
            self._valid_outline_text()
            .replace("## Potential mechanisms\n", "## Something else\n")
            .replace("bias estimates conservatively toward the null", "affect interpretation in routine practice"),
            encoding="utf-8",
        )
        bad_outline = discussion.validate_outline(self.project)
        self.assertTrue(any("Potential mechanisms" in p for p in bad_outline), bad_outline)
        self.assertTrue(any("direction of bias" in p for p in bad_outline), bad_outline)

        outline_path.write_text(self._valid_outline_text(), encoding="utf-8")
        self.assertEqual(discussion.validate_outline(self.project), [])

        # Writing discussion.md BEFORE locking the outline must fail!
        disc_path = self.project / "07_manuscript/discussion.md"
        disc_path.write_text("# Discussion\n\nPremature prose written before locking outline.\n", encoding="utf-8")
        premature = _run_tool(self.project, "tools/manuscript/discussion_brief.py", "lock-outline", "--project", str(self.project))
        self.assertNotEqual(premature.returncode, 0)
        self.assertIn("already exists without a prior outline lock", premature.stderr)

        # Lock with --reset-draft removes premature draft, locks receipt, and then allows drafting discussion.md.
        locked = _run_tool(
            self.project,
            "tools/manuscript/discussion_brief.py",
            "lock-outline",
            "--reset-draft",
            "--project",
            str(self.project),
        )
        self.assertEqual(locked.returncode, 0, locked.stderr)
        self.assertFalse(disc_path.exists())
        self.assertEqual(discussion.validate_discussion_workflow(self.project), [])

    def test_discussion_discipline_blocks_supp_overuse_and_results_duplication(self) -> None:
        _progress("S16/S22 Discussion discipline: block supplementary overuse & near-duplicate Results sentences")
        _run_tool(self.project, "tools/manuscript/discussion_brief.py", "scaffold", "--project", str(self.project))
        (self.project / "07_manuscript/discussion_outline.md").write_text(self._valid_outline_text(), encoding="utf-8")
        _run_tool(self.project, "tools/manuscript/discussion_brief.py", "lock-outline", "--project", str(self.project))

        disc_path = self.project / "07_manuscript/discussion.md"
        # Bad Discussion: cites Table S1 + Figure S2 + paraphrases Results sentence with a transition prefix.
        disc_path.write_text(
            "# Discussion\n\n"
            "Notably, in our study, among 640 hospitalized patients, early physiology-guided decongestion was associated with a lower 12-month incidence of death or heart failure readmission compared with delayed standard titration.\n\n"
            "Additional sensitivity patterns are shown in Table S1 and Supplementary Figure S2.\n",
            encoding="utf-8",
        )
        probs = discussion.validate_discussion_discipline(self.project, "07_manuscript/discussion.md")
        self.assertTrue(any("supplementary tables/figures 2 time(s)" in p for p in probs), probs)
        self.assertTrue(any("repeats Results wording" in p for p in probs), probs)

        # Good Discussion: synthesizes findings, compares prior literature + reasons, mechanisms, clinical meaning, bias direction.
        disc_path.write_text(
            "# Discussion\n\n"
            "Early alignment of loop-diuretic dosing with bedside natriuresis and congestion trajectories was associated with a substantially lower hazard of post-discharge mortality or heart failure rehospitalization over one year.\n\n"
            "Whereas earlier inpatient diuretic trials reported neutral post-discharge outcomes in milder cohorts randomized after initial stabilization [@smith2024cardio], our cohort targeted acutely congested patients within hours of admission, explaining the larger clinical separation.\n\n"
            "From a pathophysiological perspective, rapid relief of renal venous hypertension may preserve glomerular filtration and blunt neurohormonal activation without provoking intravascular depletion.\n\n"
            "Clinically, integrating early spot urinary sodium checks into ward protocols offers an accessible strategy to identify diuretic resistance before premature discharge. Because clinicians may have intensified monitoring in higher-acuity patients, residual confounding by indication would likely attenuate the observed protective association toward the null.\n\n"
            "In conclusion, early physiology-guided decongestion improved 12-month event-free survival and merits confirmation in multicenter pragmatic trials.\n",
            encoding="utf-8",
        )
        self.assertEqual(discussion.validate_discussion_discipline(self.project, "07_manuscript/discussion.md"), [])
        stage = self.pipe.stage("S16_discussion")
        ctx = Ctx(self.pipe, self.state, self.project, stage, {"path": "07_manuscript/discussion.md"})
        self.assertTrue(get("discussion_workflow_valid")(ctx).ok)
        self.assertTrue(get("discussion_discipline")(ctx).ok)

    def test_independent_review_requires_dedicated_discussion_audit(self) -> None:
        _progress("S18/S19/S24/S25 review gate: enforce dedicated Discussion audit section")
        rev_path = self.project / "07_manuscript/independent_publishability_review.md"
        # Missing Discussion audit section -> fails.
        rev_path.write_text(
            "# Independent Publishability Review\n\n## Verdict\nMinor revision.\n\n## Medical presentation\nClear prose.\n",
            encoding="utf-8",
        )
        probs_missing = discussion.validate_discussion_review(self.project, "S18_independent_review")
        self.assertTrue(any("Discussion audit" in p for p in probs_missing), probs_missing)

        # Partial Discussion audit omitting mechanisms and clinical implications -> fails.
        rev_path.write_text(
            "# Independent Publishability Review\n\n"
            "## Discussion audit\n"
            "The Discussion does not restate Results numbers verbatim and compares findings with prior cohort studies while explaining differences in baseline congestion.\n",
            encoding="utf-8",
        )
        probs_partial = discussion.validate_discussion_review(self.project, "S18_independent_review")
        self.assertTrue(any("candidate mechanisms" in p for p in probs_partial), probs_partial)
        self.assertTrue(any("clinical implications" in p for p in probs_partial), probs_partial)

        # Complete Discussion audit covering all 4 aspects -> passes.
        rev_path.write_text(
            "# Independent Publishability Review\n\n"
            "## Discussion audit\n"
            "The Discussion synthesizes main findings without restating Results sentences, compares effect direction against prior trials and explains reasons for differences in congestion acuity, frames renal venous decompression mechanisms proportionately as hypotheses, and articulates bedside clinical implications alongside conservative bias direction.\n",
            encoding="utf-8",
        )
        self.assertEqual(discussion.validate_discussion_review(self.project, "S18_independent_review"), [])


class SupplementalFilenameTests(unittest.TestCase):
    """Requirement 4: Enforce Supplemental_File_<N>_<Description>.<ext> and reject ESM1/terse/gapped names."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="medpaper-suppname-128-"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, onerror=_rmtree_onerror))
        self.project = self.tmp / "project"
        (self.project / "08_submission/bundle").mkdir(parents=True, exist_ok=True)
        self.state = State(self.project).create("medpaper", "1.28.0", "S23_package")
        self.pipe = registry.load()
        load_all()
        _setup_journal_profile(self.project, "Standard medical submission guidelines.", blinded=False)
        atomic_json(self.project / "08_submission/docx_style.json", _default_style())
        atomic_json(
            self.project / "08_submission/submission_requirements.json",
            {"required_upload_roles": ["manuscript", "cover_letter"]},
        )

    def test_rejects_esm1_generic_and_gapped_names_and_accepts_descriptive_sequence(self) -> None:
        _progress("Supplemental filenames: reject ESM1/generic/gapped, accept Supplemental_File_<N>_<Description>")
        for bad_items, expected_hint in (
            (
                [{"role": "supplementary", "file": "08_submission/bundle/ESM1.docx", "upload": True}],
                "never terse names like 'ESM1'",
            ),
            (
                [{"role": "supplementary", "file": "08_submission/bundle/supplementary_methods.docx", "upload": True}],
                "Supplemental_File_<N>_<Specific_Description>",
            ),
            (
                [{"role": "supplementary", "file": "08_submission/bundle/Supplemental_File_1_ESM1.docx", "upload": True}],
                "too terse or generic",
            ),
            (
                [
                    {"role": "supplementary", "file": "08_submission/bundle/Supplemental_File_1_Supplementary_Methods.docx", "upload": True},
                    {"role": "supplementary_tables", "file": "08_submission/bundle/Supplemental_File_3_Supplementary_Tables.xlsx", "upload": True},
                ],
                "sequential 1..2 without gaps",
            ),
        ):
            probs = submissionlayout.supplemental_filename_problems(self.project, {"items": bad_items})
            self.assertTrue(any(expected_hint in p for p in probs), (expected_hint, probs))

        # Verify submissionqc.measure flags ESM1.docx with a dedicated Supplemental_File naming defect.
        esm1 = self.project / "08_submission/bundle/ESM1.docx"
        doc_esm = Document()
        doc_esm.add_paragraph("Supplementary Methods")
        doc_esm.save(esm1)
        from manuscript.build_docx import normalize_docx
        normalize_docx(esm1, _default_style(), "supplementary")
        atomic_json(
            self.project / "08_submission/bundle/manifest.json",
            {"items": [{"role": "supplementary", "file": "08_submission/bundle/ESM1.docx", "upload": True}]},
        )
        qc_bad = submissionqc.measure(self.project)
        bad_defects = [d for row in qc_bad["rows"] for d in row.get("defects", [])]
        self.assertTrue(any("never terse names like 'ESM1'" in err for err in bad_defects), bad_defects)

        # Valid sequential descriptive names pass supplemental_filenames_compliant and produce zero naming defects in submissionqc.
        f1 = self.project / "08_submission/bundle/Supplemental_File_1_Supplementary_Methods.docx"
        f2 = self.project / "08_submission/bundle/Supplemental_File_2_Supplementary_Tables.xlsx"
        shutil.copy2(esm1, f1)
        esm1.unlink()
        write_table(
            path=f2,
            sheet="Table S1",
            title="Table S1. Sensitivity analysis.",
            header=["Model", "HR (95% CI)"],
            rows=[["Propensity-weighted", ci(0.75, 0.58, 0.96)]],
            footnotes=["Abbreviations: CI, confidence interval; HR, hazard ratio."],
        )
        good_manifest = {
            "items": [
                {"role": "supplementary", "file": "08_submission/bundle/Supplemental_File_1_Supplementary_Methods.docx", "upload": True},
                {"role": "supplementary_tables", "file": "08_submission/bundle/Supplemental_File_2_Supplementary_Tables.xlsx", "upload": True},
            ]
        }
        atomic_json(self.project / "08_submission/bundle/manifest.json", good_manifest)
        self.assertEqual(submissionlayout.supplemental_filename_problems(self.project), [])
        stage = self.pipe.stage("S23_package")
        ctx = Ctx(self.pipe, self.state, self.project, stage, {})
        self.assertTrue(get("supplemental_filenames_compliant")(ctx).ok)
        qc_good = submissionqc.measure(self.project)
        good_defects = [d for row in qc_good["rows"] for d in row.get("defects", [])]
        self.assertFalse(any("Supplemental_File_" in err or "ESM1" in err for err in good_defects), good_defects)


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
