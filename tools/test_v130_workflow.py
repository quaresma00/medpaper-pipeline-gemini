#!/usr/bin/env python3
"""v1.30.0 workflow regression tests with live progress reporting."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from wfcore import registry  # noqa: E402
from wfcore.checks import Ctx, get as get_check, load_all  # noqa: E402
from wfcore.state import State  # noqa: E402


def _progress(msg: str) -> None:
    print(f"[v1.30 test] {msg}", flush=True)


class TestV130Workflow(unittest.TestCase):
    def setUp(self) -> None:
        load_all()
        self.tmp = Path(tempfile.mkdtemp(prefix="medpaper_v130_"))
        self.project = self.tmp / "project"
        for sub in (
            ".wf", "00_input", "01_protocol", "02_data", "03_analysis/results",
            "04_displays", "04_tables/main", "05_figures/out", "06_refs/fulltext",
            "07_manuscript", "08_submission/bundle", "08_submission/integration",
        ):
            (self.project / sub).mkdir(parents=True, exist_ok=True)
        self.pipe = registry.load()
        self.state = State(self.project, ".wf")
        self.state.create(self.pipe.meta["name"], str(self.pipe.meta["version"]), self.pipe.stages[0].id)

    def tearDown(self) -> None:
        def _rw(fn, path, _exc):
            import stat
            Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
            fn(path)
        shutil.rmtree(self.tmp, onexc=_rw)

    def _ctx(self, stage_id: str, spec: dict | None = None) -> Ctx:
        return Ctx(pipeline=self.pipe, state=self.state, project=self.project,
                   stage=self.pipe.stage(stage_id), spec=spec or {})

    def test_1_pipeline_order_and_compact_cards(self) -> None:
        _progress("1/6 Checking 25-stage sequence (S10->S11->S11b->S08->S09, merged S24) and compact card limits...")
        ids = [s.id for s in self.pipe.stages]
        self.assertEqual(len(ids), 25)
        self.assertEqual(ids.index("S10_tables"), ids.index("S07_artifacts") + 1)
        self.assertEqual(ids.index("S11_figures"), ids.index("S10_tables") + 1)
        self.assertEqual(ids.index("S11b_prewrite_review"), ids.index("S11_figures") + 1)
        self.assertEqual(ids.index("S08_methods"), ids.index("S11b_prewrite_review") + 1)
        self.assertEqual(ids.index("S09_results"), ids.index("S08_methods") + 1)
        self.assertEqual(ids[-1], "S24_package_human_review")
        for name in ("S07_artifacts", "S20_journal", "S23_package", "S24_package_human_review", "S25_submission_audit"):
            card = ROOT / "pipeline/stages" / f"{name}.md"
            self.assertLess(len(card.read_text(encoding="utf-8")), 4000, f"{name} exceeded 4000 chars")

    def test_2_eutils_global_dotenv_fallback(self) -> None:
        _progress("2/6 Checking PubMed global ~/.env fallback without printing secret...")
        from pubmed import eutils
        fake_home = self.tmp / "fake_home"
        (fake_home / ".gemini").mkdir(parents=True)
        (fake_home / ".gemini" / ".env").write_text("NCBI_API_KEY=test_key_redacted_130\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(Path, "home", return_value=fake_home):
                self.assertEqual(eutils.api_key(), "test_key_redacted_130")

    def test_3_per_section_polish_and_engineering_block(self) -> None:
        _progress("3/6 Checking per-section de-AI, anti-defensive, and engineering-jargon polish gate...")
        import subprocess
        sec = self.project / "07_manuscript/methods.md"
        draft = (
            "# Methods\n\n"
            "Firstly, we ran our python script over a dataframe to inspect sepsis cohort outcomes (OR 1.42, 95% CI 1.10\u20131.83, P = 0.008) [@smith2023].\n"
            "Unfortunately, this modest approach merely achieves narrow precision.\n"
        )
        sec.write_text(draft, encoding="utf-8")
        gate = get_check("section_polished")
        r0 = gate(self._ctx("S08_methods", {"path": "07_manuscript/methods.md", "since": "1.30.0"}))
        self.assertFalse(r0.ok)

        tool = ROOT / "tools/text/polish.py"
        subprocess.run([sys.executable, str(tool), "section", "--file", str(sec), "--snapshot"],
                       cwd=self.tmp, check=True, capture_output=True)
        # Verify draft containing engineering jargon + defensive phrasing fails --verify
        v_bad = subprocess.run([sys.executable, str(tool), "section", "--file", str(sec), "--verify"],
                               cwd=self.tmp, capture_output=True, text=True)
        self.assertNotEqual(v_bad.returncode, 0)

        clean = (
            "# Methods\n\n"
            "We evaluated adult patients admitted with sepsis in a multivariable regression analysis (OR 1.42, 95% CI 1.10\u20131.83, P = 0.008) [@smith2023].\n"
            "Adjusted estimates quantified mortality risk across predefined clinical strata, while retaining modest effect sizes, null secondary findings, unfavorable adverse outcomes, study limitations, and wide confidence interval uncertainty.\n"
        )
        sec.write_text(clean, encoding="utf-8")
        subprocess.run([sys.executable, str(tool), "section", "--file", str(sec), "--verify"],
                       cwd=self.tmp, check=True, capture_output=True)
        r1 = gate(self._ctx("S08_methods", {"path": "07_manuscript/methods.md", "since": "1.30.0"}))
        self.assertTrue(r1.ok, r1.detail)

        # Fact drift after polish verification must fail the gate
        sec.write_text(clean.replace("1.42", "1.99"), encoding="utf-8")
        r2 = gate(self._ctx("S08_methods", {"path": "07_manuscript/methods.md", "since": "1.30.0"}))
        self.assertFalse(r2.ok)

        # Figure subtitle, excessive in-plot prose, and table/legend AI clichés & engineering jargon must be blocked
        from wfcore import displaylabels
        sub_issues = displaylabels.scan_text("Multivariable cohort comparison adjusted for age", context="Figure subtitle")
        self.assertTrue(any(i["kind"] == "figure_subtitle_forbidden" for i in sub_issues))
        prose_issues = displaylabels.scan_text(
            "Note: Solid line indicates multivariable Cox regression adjusted for age, sex, and baseline SOFA score across all strata.",
            context="Figure text",
        )
        self.assertTrue(any(i["kind"] in {"figure_explanatory_prose", "figure_excessive_text"} for i in prose_issues))
        ai_tbl_issues = displaylabels.scan_text(
            "This table delves into python script dataframe outputs and underscores the importance of sepsis biomarkers.",
            context="Table footnote",
        )
        kinds = {i["kind"] for i in ai_tbl_issues}
        self.assertIn("display_ai_cliche", kinds)
        self.assertIn("display_engineering_jargon", kinds)
        concise_stat = displaylabels.scan_text("Adjusted HR 1.42 (95% CI 1.10-1.83), P = 0.008", context="Figure text")
        self.assertEqual(concise_stat, [])

    def test_4_prewrite_independent_review_gate(self) -> None:
        _progress("4/6 Checking S11b_prewrite_review independent SCIE audit workflow...")
        from wfcore import reviewrounds as rounds
        (self.project / "01_protocol/analysis_contract.json").write_text('{"design":"cohort"}\n', encoding="utf-8")
        (self.project / "01_protocol/artifact_plan.json").write_text('{"main_figures":[],"main_tables":[]}\n', encoding="utf-8")
        self.state.data["current"] = "S11b_prewrite_review"
        self.state.save()
        gate = get_check("prewrite_review_verified")
        self.assertFalse(gate(self._ctx("S11b_prewrite_review", {"since": "1.30.0"})).ok)

        rec = rounds.start(self.project, "prewrite")
        rep = self.project / ".wf/review_inbox/W001.md"
        rep.parent.mkdir(parents=True, exist_ok=True)
        block = json.dumps({
            "reviewed_artifacts": rec["reviewed_artifacts"],
            "finding_inventory_complete": True,
            "section_verdicts": {
                "Statistical methods & results rigor": "no_actionable_findings",
                "SCIE Original Article sufficiency": "no_actionable_findings",
                "Display clarity & medical language": "no_actionable_findings",
            },
            "findings": [],
        }, indent=2)
        rep.write_text(
            "## Statistical methods & results rigor\n\n"
            + "Multivariable Cox models and competing-risk sensitivity analyses are properly specified with narrow confidence intervals across the cohort. " * 2 + "\n\n"
            "## SCIE Original Article sufficiency\n\n"
            + "Novelty, sample size, and incremental predictive metrics match peer-reviewed SCIE Original Article expectations across comparator studies. " * 2 + "\n\n"
            "## Display clarity & medical language\n\n"
            + "All figure axes, clinical labels, confidence intervals, and three-line table footnotes are unambiguous for physician readers. " * 2 + "\n\n"
            f"```json\n{block}\n```\n",
            encoding="utf-8",
        )
        rounds.attach(self.project, "prewrite", rep)
        rounds.close(self.project, "prewrite", [], [])
        rounds.decide(self.project, "prewrite", "no_further_review", "我确认这一版")
        r_ok = gate(self._ctx("S11b_prewrite_review", {"since": "1.30.0"}))
        self.assertTrue(r_ok.ok, r_ok.detail)

    def test_5_benchmark_display_and_reference_floors(self) -> None:
        _progress("5/6 Checking >=5 recent (<=5y) comparator display sufficiency and citation floors...")
        from datetime import datetime, timezone
        cur_year = datetime.now(timezone.utc).year
        bench_gate = get_check("benchmark_display_sufficiency")
        comp = lambda k, mf, yr: {"citekey": k, "year": yr, "observations": {"main_figures": mf, "figure_types": ["flow", "forest", "km", "roc"], "references": 42}}
        # Too few comparators (<5) must fail
        (self.project / "01_protocol/artifact_benchmark.json").write_text(json.dumps({
            "comparators": [comp("a", 5, cur_year), comp("b", 6, cur_year), comp("c", 5, cur_year)],
            "adaptation": {"displays": {"figure_count_rationale": "Matched to peer SCIE articles with four core clinical visuals."}},
        }), encoding="utf-8")
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_figures": [{"id": f"Figure {i}"} for i in range(1, 5)],
        }), encoding="utf-8")
        self.assertFalse(bench_gate(self._ctx("S07_artifacts", {"since": "1.30.0"})).ok)

        # Outdated comparators (>5 years old) without recency_exception must fail
        (self.project / "01_protocol/artifact_benchmark.json").write_text(json.dumps({
            "comparators": [comp(f"old{i}", 5, cur_year - 9) for i in range(5)],
            "adaptation": {"displays": {"figure_count_rationale": "Five older comparators surveyed across the design."}},
        }), encoding="utf-8")
        r_old = bench_gate(self._ctx("S07_artifacts", {"since": "1.30.0"}))
        self.assertFalse(r_old.ok)
        self.assertIn("last 5 years", r_old.detail)

        # 5 recent comparators + >=4 figures must pass
        (self.project / "01_protocol/artifact_benchmark.json").write_text(json.dumps({
            "comparators": [comp(f"c{i}", 5, cur_year - (i % 3)) for i in range(5)],
            "adaptation": {"displays": {"figure_count_rationale": "Five recent SCIE comparators (last 3 years) use 5 figures; our 4-figure plan covers flow, primary HR, forest, and ROC."}},
        }), encoding="utf-8")
        self.assertTrue(bench_gate(self._ctx("S07_artifacts", {"since": "1.30.0"})).ok)

        lit_gate = get_check("literature_sufficiency")
        (self.project / "06_refs/library.json").write_text(json.dumps({
            "entries": [{"citekey": f"ref{i}"} for i in range(10)]
        }), encoding="utf-8")
        self.assertFalse(lit_gate(self._ctx("S13_reflib", {"mode": "library", "since": "1.30.0"})).ok)
        (self.project / "06_refs/library.json").write_text(json.dumps({
            "entries": [{"citekey": f"ref{i}"} for i in range(42)]
        }), encoding="utf-8")
        self.assertTrue(lit_gate(self._ctx("S13_reflib", {"mode": "library", "since": "1.30.0"})).ok)

    def test_6_scihub_captcha_respect_and_journal_release_naming(self) -> None:
        _progress("6/6 Checking non-CAPTCHA Sci-Hub abort and <Journal>_<YYYYMMDD_HHMMSS> bundles...")
        from pubmed import fulltext
        from wfcore import packagefreeze as pf

        class _FakeResp:
            def __init__(self, body: bytes, ctype: str = "text/html"):
                self._body = body
                self.headers = {"Content-Type": ctype}
            def read(self, _n: int = -1) -> bytes:
                return self._body
            def __enter__(self):
                return self
            def __exit__(self, *_a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=_FakeResp(b"<html>Cloudflare Verify you are human CAPTCHA</html>")):
            blocked = fulltext.try_scihub({"citekey": "x2024", "doi": "10.1000/test"})
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["access"], "captcha_or_blocked")

        (self.project / "08_submission/target_journal.json").write_text('{"journal_name":"Critical Care Medicine"}\n', encoding="utf-8")
        (self.project / "08_submission/bundle/manuscript.docx").write_bytes(b"PK\x03\x04dummy-docx")
        (self.project / "08_submission/bundle/manifest.json").write_text(json.dumps({
            "items": [{"role": "manuscript", "file": "08_submission/bundle/manuscript.docx", "upload": True}]
        }), encoding="utf-8")
        for req in pf.REQUIRED_EVIDENCE:
            if not (self.project / req).is_file():
                (self.project / req).write_text('{"ok":true}\n' if req.endswith(".json") else "guide text\n", encoding="utf-8")
        freeze_path = pf.write_freeze(self.project)
        payload = json.loads(freeze_path.read_text(encoding="utf-8"))
        self.assertRegex(payload["release_dir"], r"^08_submission/releases/Critical_Care_Medicine_\d{8}_\d{6}(?:_[A-Fa-f0-9]{6})?$")
        ok, problems, count = pf.verify_freeze(self.project)
        self.assertTrue(ok, problems)
        self.assertEqual(count, 1)

    def test_7_non_result_exemptions_and_strict_table_cells(self) -> None:
        _progress("7/11 Checking table non-result exemptions, allowlist isolation, and strict body cell binding...")
        import contextlib
        import io
        from openpyxl import load_workbook
        from tables.threeline import write_table
        from wfcore import claims
        from wfcore.checks.numbers import numbers_have_provenance

        ctx_fact = {
            "outcome": "Mortality",
            "population": "Adult sepsis cohort",
            "comparison": "Treatment vs control",
            "model": "Cox model",
            "timepoint": "30-day",
            "unit": "Odds ratio",
            "denominator": "Eligible sepsis cohort",
            "percentage_basis": "Total sepsis admissions",
            "interval_level": "95%",
        }
        (self.project / "03_analysis/results/primary.json").write_text(json.dumps({
            "cohort": {"n_total": 66},
            "reported": {
                "context": ctx_fact,
                "values": {"estimate": 1.42, "low": 1.10, "high": 1.83, "n_total": 66},
            },
        }), encoding="utf-8")
        (self.project / "01_protocol/study_facts.json").write_text(json.dumps({
            "protocol_threshold_note": "120",
            "numeric_facts": {
                "or_primary": {
                    "source": "03_analysis/results/primary.json",
                    "pointer": "/reported",
                    "context": ctx_fact,
                }
            },
        }), encoding="utf-8")
        (self.project / "03_analysis/results/number_allowlist.tsv").write_text(
            "# value\tkind\tsource\trationale\n"
            "120\tconstant\t01_protocol/study_facts.json\tPreplanned study protocol threshold validated across clinical strata.\n",
            encoding="utf-8",
        )
        tbl_rel = "04_tables/main/Table1.xlsx"
        tbl_path = self.project / tbl_rel
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_tables": [{"id": "Table 1", "sheet": "Table 1", "file": tbl_rel}],
            "main_figures": [],
        }), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                tbl_path,
                sheet="Table 1",
                title="Table 1. Adult sepsis mortality outcomes (n = 66, ICD-10, 18-64 years).",
                header=["Characteristic", "Treatment vs control, 30-day (n=66)"],
                rows=[
                    ["Age 18-64 years", "—"],
                    ["ICD-10 coding / Cox model-1", "—"],
                    ["Mortality, Odds ratio (95% CI)", "1.42 (1.10 to 1.83)"],
                ],
                footnotes=[
                    "ICD-10 codes within 30-day window; protocol threshold 120 applied before subgroup fit.",
                ],
            )
        (self.project / "07_manuscript/claim_bindings.json").write_text(json.dumps({
            "schema_version": 1,
            "claims": [{
                "path": tbl_rel,
                "sheet": "Table 1",
                "cell": "B5",
                "text": "1.42 (1.10 to 1.83)",
                "fact_ids": ["or_primary"],
                "label_cells": ["A5"],
            }],
        }), encoding="utf-8")

        res_ok = numbers_have_provenance(self._ctx("S10_tables", {"source": "tables"}))
        self.assertTrue(res_ok.ok, res_ok.detail)
        self.assertEqual(claims.validate_tables(self.project, [tbl_path]), [])

        # Allowlist constant placed inside a result data cell must still fail strictly
        wb = load_workbook(tbl_path)
        wb["Table 1"]["B3"] = "120"
        wb.save(tbl_path)
        wb.close()
        res_allow_in_body = numbers_have_provenance(self._ctx("S10_tables", {"source": "tables"}))
        self.assertFalse(res_allow_in_body.ok)
        self.assertTrue(claims.validate_tables(self.project, [tbl_path]))

        # Unprovenanced arbitrary number in Row 1 title must fail
        wb = load_workbook(tbl_path)
        wb["Table 1"]["B3"] = "—"
        wb["Table 1"]["A1"] = "Table 1. Adult sepsis mortality outcomes (n = 999)."
        wb.save(tbl_path)
        wb.close()
        res_bad_title = numbers_have_provenance(self._ctx("S10_tables", {"source": "tables"}))
        self.assertFalse(res_bad_title.ok)

    def test_8_display_label_hardening_and_prefix_repetition(self) -> None:
        _progress("8/11 Checking clinical display label checks (internal codes, file leaks, spelled numbers, >=4 colon prefixes)...")
        import contextlib
        import io
        from tables.threeline import write_table
        from wfcore import displaylabels, displayquality

        cases = [
            ("Tier A cohort", "internal_code_label"),
            ("S1-S8", "internal_code_label"),
            ("loaded from primary.json under locked protocol with code paths and provenance", "display_engineering_jargon"),
            ("eighteen to sixty-four years", "spelled_clinical_number"),
            ("thirty-day", "spelled_clinical_number"),
        ]
        for text, expected_kind in cases:
            issues = displaylabels.scan_text(text, context="Table header")
            kinds = {i["kind"] for i in issues}
            self.assertIn(expected_kind, kinds, f"{text!r} -> {issues!r}")

        flat = displayquality.flat_labels([
            "Outcome category: Cardiac",
            "Outcome category: Renal",
            "Outcome category: Hepatic",
            "Outcome category: Pulmonary",
        ])
        self.assertTrue(flat, "4+ repeated colon prefixes must be flagged")

        tbl_rel = "04_tables/main/Table1.xlsx"
        tbl_path = self.project / tbl_rel
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_tables": [{"id": "Table 1", "sheet": "Table 1", "file": tbl_rel}],
            "main_figures": [],
        }), encoding="utf-8")
        from wfcore.packagefreeze import _sha256
        prev_rel = "04_tables/previews/Table_1.png"
        prev_path = self.project / prev_rel
        prev_path.parent.mkdir(parents=True, exist_ok=True)
        prev_path.write_bytes(b"\x89PNG\r\n\x1a\ndummy")

        def _sync_review() -> None:
            (self.project / "01_protocol/display_review.json").write_text(json.dumps({
                "final_reviews": {
                    "Table 1": {
                        "reviewed_file": tbl_rel,
                        "sha256": _sha256(tbl_path),
                        "rendered_preview": prev_rel,
                        "rendered_sha256": _sha256(prev_path),
                        "reader_explanation": "Organ-specific complication frequencies and percentages across the eligible clinical cohort.",
                        "layout_and_style": "Standard three-line table layout with clear hierarchy and alignment across all columns.",
                        "verdict": "PASS",
                    }
                }
            }), encoding="utf-8")

        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                tbl_path,
                sheet="Table 1",
                title="Table 1. Organ-specific complications.",
                header=["Characteristic", "Cohort (n=50)"],
                rows=[
                    ["Outcome category: Cardiac", "10 (20.0)"],
                    ["Outcome category: Renal", "8 (16.0)"],
                    ["Outcome category: Hepatic", "5 (10.0)"],
                    ["Outcome category: Pulmonary", "7 (14.0)"],
                ],
                footnotes=["Data are n (%)."],
            )
        _sync_review()
        probs_bad = displayquality.production_problems(self.project, "table")
        self.assertTrue(probs_bad, "repeated colon prefix rows should fail production_problems")

        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                tbl_path,
                sheet="Table 1",
                title="Table 1. Organ-specific complications.",
                header=["Characteristic", "Cohort (n=50)"],
                rows=[
                    ["Outcome category", ""],
                    ["Cardiac", "10 (20.0)"],
                    ["Renal", "8 (16.0)"],
                    ["Hepatic", "5 (10.0)"],
                    ["Pulmonary", "7 (14.0)"],
                ],
                group_rows=[0],
                indent_rows=[1, 2, 3, 4],
                footnotes=["Data are n (%)."],
            )
        _sync_review()
        self.assertEqual(displayquality.production_problems(self.project, "table"), [])

    def test_9_all_checks_only_debugging_and_s11b_targeted_rework(self) -> None:
        _progress("9/11 Checking --all-checks --only debugging and S11b scoped rework selective invalidation...")
        import contextlib
        import io
        import subprocess
        from tables.threeline import write_table
        from wfcore import dependencies, gates

        (self.project / "04_tables/code").mkdir(parents=True, exist_ok=True)
        (self.project / "04_tables/code/table1.py").write_text("# Table 1 builder\n", encoding="utf-8")
        (self.project / "04_tables/code/table2.py").write_text("# Table 2 builder\n", encoding="utf-8")
        t1_rel = "04_tables/main/Table1.xlsx"
        t2_rel = "04_tables/main/Table2.xlsx"
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_tables": [
                {"id": "Table 1", "sheet": "Table 1", "file": t1_rel},
                {"id": "Table 2", "sheet": "Table 2", "file": t2_rel},
            ],
            "main_figures": [{"id": "Figure 1", "file": "05_figures/out/Figure1.png", "pdf": "05_figures/out/Figure1.pdf", "script": "05_figures/out/Figure1.R", "width": "single", "archetype": "forest_plot"}],
        }), encoding="utf-8")
        (self.project / "04_tables/manifest.json").write_text(json.dumps({
            "built_at": "2026-01-01T00:00:00Z",
            "built_by": "04_tables/code/build_tables.py",
            "tables": [
                {"id": "Table 1", "file": t1_rel, "sheet": "Table 1", "script": "04_tables/code/table1.py", "source_results": ["03_analysis/results/primary.json"]},
                {"id": "Table 2", "file": t2_rel, "sheet": "Table 2", "script": "04_tables/code/table2.py", "source_results": ["03_analysis/results/primary.json"]},
            ],
        }), encoding="utf-8")
        (self.project / "03_analysis/results/primary.json").write_text('{"n": 40}\n', encoding="utf-8")
        (self.project / "01_protocol/study_facts.json").write_text('{"numeric_facts":{}}\n', encoding="utf-8")
        (self.project / "07_manuscript/claim_bindings.json").write_text('{"schema_version":1,"claims":[]}\n', encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            # Table 1 has engineering jargon AND unprovenanced number 9876
            write_table(
                self.project / t1_rel,
                sheet="Table 1",
                title="Table 1. Cohort summary from primary.json.",
                header=["Characteristic", "Count"],
                rows=[["Total cohort", "9876"]],
                footnotes=["Footnote with code paths."],
            )
            # Table 2 has unprovenanced number 54321
            write_table(
                self.project / t2_rel,
                sheet="Table 2",
                title="Table 2. Secondary summary.",
                header=["Characteristic", "Count"],
                rows=[["Secondary count", "54321"]],
                footnotes=["Clinical counts shown."],
            )

        stage_s10 = self.pipe.stage("S10_tables")
        early = gates.run_stage(self.pipe, self.state, self.project, stage_s10, break_on_blocker=True)
        full_t1 = gates.run_stage(self.pipe, self.state, self.project, stage_s10, break_on_blocker=False, only="Table 1", verbose=True)
        early_fails = [r for r in early if not r.ok]
        full_fails = [r for r in full_t1 if not r.ok]
        self.assertGreater(len(full_fails), len(early_fails), f"expected all-checks to surface more failures than early-stop: {full_fails}")
        joined = "\n".join(r.detail for r in full_fails)
        self.assertNotIn("54321", joined)
        self.assertNotIn("Table 2", joined)

        sentinel_cache = self.project / ".wf/last_check.json"
        sentinel_cache.write_text('{"sentinel":"keep"}\n', encoding="utf-8")
        env = {**os.environ, "MEDPAPER_PROJECT": str(self.project)}
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools/wf.py"), "check", "S10_tables", "--all-checks", "--only", "Table 1", "--verbose", "--json"],
            cwd=ROOT, env=env, capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(sentinel_cache.read_text(encoding="utf-8"), '{"sentinel":"keep"}\n')
        payload = json.loads(proc.stdout)
        failed_names = [c["check"] for c in payload["results"] if not c["ok"]]
        self.assertGreaterEqual(len(failed_names), 2)

        impacted = dependencies.closure(self.project, ["04_tables/code/table1.py"], change_type="layout")
        self.assertIn(t1_rel, impacted)
        self.assertIn("04_tables/previews/Table_1.png", impacted)
        self.assertIn("04_tables/qc/table_qc_report.json", impacted)
        self.assertNotIn(t2_rel, impacted)

        # S11b scoped rework: editing Table 1 layout must invalidate tables_visually_confirmed ONLY, not figures_visually_confirmed
        (self.project / "05_figures/out/Figure1.R").write_text("# fig\n", encoding="utf-8")
        (self.project / "05_figures/out/Figure1.png").write_bytes(b"PNG")
        (self.project / "05_figures/out/Figure1.pdf").write_bytes(b"%PDF")
        self.state.data["current"] = "S11b_prewrite_review"
        self.state.data["completed"] = ["S01_intake", "S07_artifacts", "S10_tables", "S11_figures"]
        self.state.data["decisions"] = {
            "tables_visually_confirmed": {"value": "YES", "why": "checked"},
            "figures_visually_confirmed": {"value": "YES", "why": "checked"},
            "prewrite_review_approved": {"value": "YES", "why": "checked"},
        }
        self.state.save()
        plan_file = self.tmp / "rework_plan.json"
        plan_file.write_text(json.dumps({
            "feedback_verbatim": "Adjust Table 1 column spacing and label wrapping before manuscript drafting.",
            "interpretation": "Update only the Table 1 builder script to improve header wrapping without changing any figure or downstream stage.",
            "ambiguous_or_requires_user_decision": [],
            "items": [{
                "kind": "table-layout",
                "request": "Improve wrapping and spacing in Table 1 layout only.",
                "affected_sources": ["04_tables/code/table1.py"],
                "acceptance_criteria": ["Table 1 preview passes wrapped_text_audit"],
            }],
        }), encoding="utf-8")
        subprocess.run(
            [sys.executable, str(ROOT / "tools/rework.py"), "batch", "--plan", str(plan_file), "--sealed",
             "--why", "Adjust Table 1 column spacing only.", "--project", str(self.project)],
            cwd=ROOT, check=True, capture_output=True, text=True,
        )
        reloaded = State(self.project, ".wf").load()
        self.assertIn("figures_visually_confirmed", reloaded.data["decisions"])
        self.assertNotIn("tables_visually_confirmed", reloaded.data["decisions"])
        round_files = sorted((self.project / ".wf/revisions").glob("*.json"))
        self.assertTrue(round_files)
        rev = json.loads(round_files[-1].read_text(encoding="utf-8"))
        self.assertNotIn("S17_assemble", rev["validation_stages"])
        self.assertIn("S10_tables", rev["validation_stages"])

    def test_10_threeline_defaults_and_render_preview_python_engine(self) -> None:
        _progress("10/11 Checking threeline print/wrap defaults and render_preview Python engine + layout QC...")
        import contextlib
        import io
        import subprocess
        from openpyxl import load_workbook
        from tables.threeline import write_table
        from tables.render_preview import render_all

        tbl_rel = "04_tables/main/Table1.xlsx"
        tbl_path = self.project / tbl_rel
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_tables": [{"id": "Table 1", "sheet": "Table 1", "file": tbl_rel}],
            "main_figures": [],
        }), encoding="utf-8")
        rows = [
            [f"Clinical subgroup stratum description number {i} with long label", "12 (30.0)", "18 (45.0)", "1.42 (1.10 to 1.83)", "0.008", "Adjusted Cox model cohort"]
            for i in range(1, 41)
        ]
        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                tbl_path,
                sheet="Table 1",
                title="Table 1. Multi-column subgroup analysis requiring landscape orientation and multi-page wrapping.",
                header=["Characteristic and Stratum", "Group A, n (%)", "Group B, n (%)", "Adjusted HR (95% CI)", "P value", "Statistical Model Specification"],
                rows=rows,
                footnotes=["HR, hazard ratio; CI, confidence interval. Rows demonstrate automatic wrapping and page title repetition."],
            )
        wb = load_workbook(tbl_path)
        ws = wb["Table 1"]
        self.assertTrue(ws["A2"].alignment.wrap_text)
        self.assertTrue(ws["A3"].alignment.wrap_text)
        self.assertIsNotNone(ws.row_dimensions[2].height)
        self.assertGreater(ws.row_dimensions[3].height, 0)
        self.assertEqual(ws.page_setup.orientation, "landscape")
        self.assertEqual(ws.page_setup.fitToWidth, 1)
        self.assertEqual(ws.page_setup.fitToHeight, 0)
        self.assertIn(ws.print_title_rows, ("1:2", "$1:$2"))
        wb.close()

        report = render_all(self.project, engine="python")
        self.assertEqual(len(report["tables"]), 1)
        tbl_rep = report["tables"][0]
        self.assertTrue(tbl_rep["ok"], tbl_rep)
        self.assertEqual(tbl_rep["engine"], "python")
        self.assertTrue((self.project / "04_tables/previews/Table_1.png").is_file())
        self.assertGreaterEqual(len(tbl_rep["pages"]), 2, f"Expected multi-page preview for 40 rows: {tbl_rep['pages']}")
        for p_rel in tbl_rep["pages"]:
            self.assertTrue((self.project / p_rel).is_file())
        checks_by_name = {c["check"]: c for c in tbl_rep["checks"]}
        for cname in ("wrapped_text_audit", "adjacent_column_touch_risk", "landscape_page_fit", "print_title_rows"):
            self.assertTrue(checks_by_name[cname]["ok"], f"{cname}: {checks_by_name[cname]}")
        self.assertFalse((self.project / "temp").exists())

        cli = subprocess.run(
            [sys.executable, str(ROOT / "tools/tables/render_preview.py"), "--all", "--engine", "python", "--project", str(self.project)],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(cli.returncode, 0, cli.stderr + cli.stdout)
        self.assertTrue((self.project / "04_tables/qc/table_qc_report.json").is_file())

    def test_11_r_forest_panels_qc_bounds_orphans_and_cross_display_parity(self) -> None:
        _progress("11/11 Checking medpaper_forest_panels, r_data_axis_bounds, no_orphan_legend_keys, and table-figure estimator parity...")
        import contextlib
        import io
        from tables.threeline import write_table
        from wfcore import claims

        # Part A: Cross-display estimator parity enforcement works without R too
        ctx_fact = {
            "outcome": "Mortality",
            "population": "Adult sepsis",
            "comparison": "Drug vs control",
            "model": "Cox model",
            "timepoint": "30-day",
            "unit": "Hazard ratio",
            "denominator": "Adult sepsis cohort",
            "percentage_basis": "Eligible ICU admissions",
            "interval_level": "95%",
        }
        (self.project / "03_analysis/results/primary.json").write_text(json.dumps({
            "groups": ["Stratum A", "Stratum B", "Stratum C"],
            "estimate": [1.42, 0.87, 1.95],
            "lower": [1.10, 0.66, 1.20],
            "upper": [1.83, 1.15, 4.20],
            "reported_a": {"context": ctx_fact, "values": {"hr": 1.42, "low": 1.10, "high": 1.83}},
            "reported_b": {"context": ctx_fact, "values": {"hr": 1.95, "low": 1.20, "high": 4.20}},
        }), encoding="utf-8")
        (self.project / "01_protocol/study_facts.json").write_text(json.dumps({
            "numeric_facts": {
                "hr_tbl": {"source": "03_analysis/results/primary.json", "pointer": "/reported_a", "context": ctx_fact},
                "hr_fig": {"source": "03_analysis/results/primary.json", "pointer": "/reported_b", "context": ctx_fact},
            },
        }), encoding="utf-8")
        fig_entry = {
            "id": "Figure 1",
            "title": "Subgroup hazard ratios",
            "content": "Adjusted hazard ratios",
            "source_results": ["03_analysis/results/primary.json"],
            "renderer": "R",
            "script": "05_figures/out/Figure1.R",
            "file": "05_figures/out/Figure1.png",
            "pdf": "05_figures/out/Figure1.pdf",
            "width": "double",
            "archetype": "forest_plot",
        }
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_tables": [{"id": "Table 1", "sheet": "Table 1", "file": "04_tables/main/Table1.xlsx"}],
            "main_figures": [fig_entry],
        }), encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                self.project / "04_tables/main/Table1.xlsx",
                sheet="Table 1",
                title="Table 1. Adult sepsis drug vs control hazard ratios.",
                header=["Characteristic", "Adjusted HR (95% CI)"],
                rows=[["Mortality, 30-day", "1.42 (1.10 to 1.83)"]],
                footnotes=["HR, hazard ratio; CI, confidence interval."],
            )
        qc_dir = self.project / "05_figures/qc"
        qc_dir.mkdir(parents=True, exist_ok=True)
        ann_text = "Adjusted HR 1.95 (95% CI 1.20 to 4.20)"
        (qc_dir / "Figure1.artist.json").write_text(json.dumps({
            "figure_text": [ann_text],
            "non_tick_text": [ann_text],
        }), encoding="utf-8")
        (self.project / "07_manuscript/claim_bindings.json").write_text(json.dumps({
            "schema_version": 1,
            "claims": [{
                "path": "04_tables/main/Table1.xlsx",
                "sheet": "Table 1",
                "cell": "B3",
                "text": "1.42 (1.10 to 1.83)",
                "fact_ids": ["hr_tbl"],
                "label_cells": ["A3"],
            }],
            "figure_annotations": [{
                "figure_id": "Figure 1",
                "label_id": "hr_callout",
                "text": ann_text,
                "fields": [{
                    "fact_id": "hr_fig",
                    "source": "03_analysis/results/primary.json",
                    "pointer": "/reported_b",
                    "field": "hr",
                    "shown": "1.95",
                }, {
                    "fact_id": "hr_fig",
                    "source": "03_analysis/results/primary.json",
                    "pointer": "/reported_b",
                    "field": "low",
                    "shown": "1.20",
                }, {
                    "fact_id": "hr_fig",
                    "source": "03_analysis/results/primary.json",
                    "pointer": "/reported_b",
                    "field": "high",
                    "shown": "4.20",
                }],
            }],
        }), encoding="utf-8")
        parity_errs = claims.validate_figures(self.project)
        self.assertTrue(any("conflicting estimates" in e or "cross-display inconsistency" in e for e in parity_errs), parity_errs)

        # Part B: Real R rendering + axis-bounds clipping + orphan legend checks
        if not shutil.which("Rscript"):
            self.skipTest("Rscript absent: real R forest-panel & QC tests NOT EXECUTED")
        from figures.render_r import render
        from figures.qc import load_archetypes, qc_figure

        (self.project / "01_protocol/study_facts.json").unlink(missing_ok=True)
        (self.project / "07_manuscript/claim_bindings.json").unlink(missing_ok=True)
        self.state.data["current"] = "S11_figures"
        self.state.save()
        (self.project / fig_entry["script"]).write_text(
            'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_style.R"))\n'
            'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_recipes.R"))\n'
            'r <- medpaper_result("03_analysis/results/primary.json")\n'
            'df <- data.frame(\n'
            '  label = unlist(r$groups),\n'
            '  estimate = unlist(r$estimate),\n'
            '  lower = unlist(r$lower),\n'
            '  upper = unlist(r$upper),\n'
            '  pval = c(0.008, 0.24, 0.002)\n'
            ')\n'
            'res <- medpaper_forest_panels(df, measure = "HR", null = 1, log_scale = TRUE, xlim = c(0.5, 2.5), p_col = "pval")\n'
            'medpaper_save(res$plot, "05_figures/out/Figure1", width = "double", height_mm = 75, panels = res$panels)\n',
            encoding="utf-8",
        )
        render(self.project, "Figure 1")
        art = json.loads((qc_dir / "Figure1.artist.json").read_text(encoding="utf-8"))
        self.assertEqual(art.get("data_clipped_at_axes", []), [])
        self.assertEqual(art.get("orphan_legend_keys", []), [])
        self.assertTrue(art["elements"]["axis_labels"]["found"], art["elements"])
        qc_ok = qc_figure(fig_entry, self.pipe.targets, load_archetypes(), self.project)
        self.assertTrue(qc_ok["ok"], json.dumps(qc_ok["checks"]))

        # Negative control 1: unclipped upper whisker exceeding coord_cartesian xlim -> r_data_axis_bounds fails
        (self.project / fig_entry["script"]).write_text(
            'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_style.R"))\n'
            'library(ggplot2)\n'
            'r <- medpaper_result("03_analysis/results/primary.json")\n'
            'd <- data.frame(group = unlist(r$groups), est = unlist(r$estimate), low = unlist(r$lower), high = unlist(r$upper))\n'
            'p <- ggplot(d, aes(x = est, y = group)) +\n'
            '  geom_vline(xintercept = 1, linetype = "dashed", linewidth = 0.25) +\n'
            '  geom_errorbar(aes(xmin = low, xmax = high), orientation = "y", width = 0.14, linewidth = 0.3) +\n'
            '  geom_point(size = 2) +\n'
            '  geom_text(aes(x = 2.1, label = sprintf("HR %.2f (%.2f to %.2f)", est, low, high)), size = 3) +\n'
            '  scale_x_log10() + coord_cartesian(xlim = c(0.5, 2.5)) +\n'
            '  labs(x = "Adjusted hazard ratio (95% CI)", y = "Patient group") + medpaper_theme()\n'
            'medpaper_save(p, "05_figures/out/Figure1", width = "double", height_mm = 75)\n',
            encoding="utf-8",
        )
        render(self.project, "Figure 1")
        qc_clip = qc_figure(fig_entry, self.pipe.targets, load_archetypes(), self.project)
        self.assertFalse(qc_clip["ok"])
        clip_checks = {c["name"]: c for c in qc_clip["checks"]}
        self.assertFalse(clip_checks["r_data_axis_bounds"]["ok"], qc_clip["checks"])

        # Negative control 2: unused legend key (drop = FALSE) -> no_orphan_legend_keys fails
        (self.project / fig_entry["script"]).write_text(
            'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_style.R"))\n'
            'library(ggplot2)\n'
            'r <- medpaper_result("03_analysis/results/primary.json")\n'
            'd <- data.frame(\n'
            '  group = unlist(r$groups),\n'
            '  est = c(1.42, 0.87, 1.35),\n'
            '  low = c(1.10, 0.66, 1.05),\n'
            '  high = c(1.83, 1.15, 1.75),\n'
            '  grp = factor(c("Subgroup A", "Subgroup B", "Subgroup A"), levels = c("Subgroup A", "Subgroup B", "Unused"))\n'
            ')\n'
            'p <- ggplot(d, aes(x = est, y = group, colour = grp)) +\n'
            '  geom_vline(xintercept = 1, linetype = "dashed", linewidth = 0.25) +\n'
            '  geom_errorbar(aes(xmin = low, xmax = high), orientation = "y", width = 0.14, linewidth = 0.3) +\n'
            '  geom_point(size = 2) +\n'
            '  geom_text(aes(x = 2.2, label = sprintf("HR %.2f (%.2f to %.2f)", est, low, high)), size = 3, colour = "black") +\n'
            '  scale_colour_manual(values = c("Subgroup A" = "#1f77b4", "Subgroup B" = "#d95f02", "Unused" = "#2ca02c"),\n'
            '                      breaks = c("Subgroup A", "Subgroup B", "Unused"), drop = FALSE) +\n'
            '  scale_x_log10(limits = c(0.5, 3.0)) +\n'
            '  labs(x = "Adjusted hazard ratio (95% CI)", y = "Patient group", colour = "Cohort") + medpaper_theme()\n'
            'medpaper_save(p, "05_figures/out/Figure1", width = "double", height_mm = 75)\n',
            encoding="utf-8",
        )
        render(self.project, "Figure 1")
        qc_orphan = qc_figure(fig_entry, self.pipe.targets, load_archetypes(), self.project)
        self.assertFalse(qc_orphan["ok"])
        orphan_checks = {c["name"]: c for c in qc_orphan["checks"]}
        self.assertFalse(orphan_checks["no_orphan_legend_keys"]["ok"], qc_orphan["checks"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
