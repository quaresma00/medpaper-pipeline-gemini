#!/usr/bin/env python3
"""v1.29.0 regression suite:
Clinical peer-reviewed display text inside figures and tables.
Eliminates code variables, formula syntax, bare booleans, raw statistical package columns,
analysis report titles, and pipeline data manipulation language in flowcharts.
"""
from __future__ import annotations

import json
import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from tables.threeline import write_table  # noqa: E402
from wfcore import clinicalpresentation, displaylabels, registry  # noqa: E402
from wfcore.checks import Ctx, get, load_all  # noqa: E402
from wfcore.state import State  # noqa: E402


def _progress(msg: str) -> None:
    print(f"[v1.29 clinical labels test] {msg}", flush=True)


def _rmtree_onerror(func, path, _exc_info) -> None:
    Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
    func(path)


class TestClinicalDisplayLabels129(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="medpaper_129_test_"))
        self.pipe = registry.load()
        load_all()

    def tearDown(self):
        shutil.rmtree(self.tmp, onerror=_rmtree_onerror)

    def test_01_scanner_catches_code_and_pipeline_jargon(self):
        _progress("Step 1: Testing scanner detection of code variables, formulas, and report jargon")
        
        # 1. snake_case
        issues = displaylabels.scan_text("patient_age_yrs", context="Table header")
        self.assertTrue(any(i.get("kind") == "code_identifier" for i in issues))

        # 2. formula syntax
        issues = displaylabels.scan_text("Hazard ratio for as.factor(trt) + age", context="Figure title")
        self.assertTrue(any(i.get("kind") == "formula_syntax" for i in issues))

        # 3. bare booleans
        issues = displaylabels.scan_text("TRUE", context="Table cell")
        self.assertTrue(any(i.get("kind") == "raw_coding_label" for i in issues))
        issues_false = displaylabels.scan_text("FALSE", context="Table cell")
        self.assertTrue(any(i.get("kind") == "raw_coding_label" for i in issues_false))

        # 4. raw statistical columns
        issues = displaylabels.scan_text("coef", context="Column header")
        self.assertTrue(any(i.get("kind") == "raw_stat_header" for i in issues))
        issues_fpr = displaylabels.scan_text("fpr", context="Axis label")
        self.assertTrue(any(i.get("kind") == "raw_stat_header" for i in issues_fpr))

        # 5. analysis report titles
        issues = displaylabels.scan_text("Primary model output across strata", context="Title")
        self.assertTrue(any(i.get("kind") == "analytics_report_title" for i in issues))

        # 6. pipeline language in flowcharts
        issues = displaylabels.scan_text("raw csv rows imported (n=50000)", context="Flowchart box")
        self.assertTrue(any(i.get("kind") == "pipeline_flowchart_jargon" for i in issues))
        issues_drop = displaylabels.scan_text("dropna filter executed", context="Flowchart box")
        self.assertTrue(any(i.get("kind") == "pipeline_flowchart_jargon" for i in issues_drop))

        _progress("Step 1 passed: All technical / engineering jargon detected.")

    def test_02_medical_whitelist_zero_false_positives(self):
        _progress("Step 2: Testing medical whitelist for zero false positives")

        valid_terms = [
            "HbA1c",
            "eGFR",
            "NT-proBNP",
            "IL-6",
            "TNF-alpha",
            "SARS-CoV-2",
            "mRNA-1273",
            "COVID-19",
            "p53",
            "miR-21",
            "Group A (n=123)",
            "Group B (n=456)",
            "Age, years, mean (SD)",
            "Systolic blood pressure (mmHg)",
            "Body mass index (kg/m²)",
            "Hazard ratio (95% CI)",
            "1 - specificity",
            "Sensitivity (%)",
            "Patients assessed for eligibility (n = 10,000)",
            "Excluded with missing baseline covariates (n = 120)",
            "Adult cohort meeting inclusion criteria (n = 9,880)",
        ]

        for term in valid_terms:
            issues = displaylabels.scan_text(term, context="Validation check")
            self.assertEqual(len(issues), 0, f"False positive triggered for legitimate medical term: {term}")

        _progress("Step 2 passed: All medical terms passed with zero false positives.")

    def test_03_table_text_extraction_and_reporting(self):
        _progress("Step 3: Testing extraction from three-line xlsx workbook")

        tbl_path = self.tmp / "Table1.xlsx"
        write_table(
            path=str(tbl_path),
            sheet="Table 1",
            title="Table 1. Patient baseline characteristics.",
            header=["Characteristic", "trt_group_1", "trt_group_0"],
            rows=[
                ["patient_age_yrs", "62.1 (11.4)", "61.7 (12.0)"],
                ["history_of_cad", "TRUE", "FALSE"],
            ],
            footnotes=["Data are n (%) unless stated otherwise."],
        )

        entries = displaylabels.extract_table_text(tbl_path)
        self.assertTrue(len(entries) > 0)
        excerpts = [e["excerpt"] for e in entries]
        self.assertTrue(any("trt_group_1" in ex for ex in excerpts))
        self.assertTrue(any("patient_age_yrs" in ex for ex in excerpts))

        _progress("Step 3 passed: Table text successfully extracted and diagnosed.")

    def test_04_figure_text_extraction_from_artist_and_svg(self):
        _progress("Step 4: Testing extraction from figure artist.json and svg")

        fig_dir = self.tmp / "05_figures" / "out"
        fig_dir.mkdir(parents=True)

        # 1. artist.json with flowchart archetype
        artist_path = self.tmp / "05_figures" / "qc" / "Figure1.artist.json"
        artist_path.parent.mkdir(parents=True, exist_ok=True)
        artist_data = {
            "title": "Primary model output across cohorts",
            "figure_text": [
                "Primary model output across cohorts",
                "patient_subgroup_a",
            ],
            "runtime": {
                "panels": [
                    {"x_label": "fpr", "y_label": "tpr"}
                ]
            }
        }
        artist_path.write_text(json.dumps(artist_data), encoding="utf-8")

        entries = displaylabels.extract_figure_text(artist_path, project=self.tmp)
        self.assertTrue(len(entries) >= 2)
        excerpts = [e["excerpt"] for e in entries]
        self.assertTrue(any("Primary model output" in ex for ex in excerpts))
        self.assertTrue(any("patient_subgroup_a" in ex for ex in excerpts))

        # 2. SVG extraction
        svg_path = fig_dir / "Figure2.render.svg"
        svg_content = """<svg xmlns="http://www.w3.org/2000/svg">
            <text x="10" y="20">exposure_cohort_id</text>
            <text x="10" y="40">as.factor(cohort)</text>
        </svg>"""
        svg_path.write_text(svg_content, encoding="utf-8")

        svg_entries = displaylabels.extract_figure_text(svg_path)
        self.assertEqual(len(svg_entries), 2)

        _progress("Step 4 passed: Figure artist.json and SVG text diagnosed.")

    def test_05_display_dictionary_verification(self):
        _progress("Step 5: Testing display dictionary verification in clinicalpresentation")

        valid_plan = {
            "display_dictionary": {
                "age_yrs": "Age (years)",
                "sbp_mean": "Systolic blood pressure (mmHg)",
                "trt_arm": "Treatment group",
            }
        }
        res = clinicalpresentation.verify_plan_labels(valid_plan)
        self.assertTrue(res.passed)
        self.assertEqual(len(res.issues), 0)

        invalid_plan = {
            "display_dictionary": {
                "age_yrs": "as.factor(age)",
                "sbp_mean": "sbp_value_mean",
            }
        }
        res_inv = clinicalpresentation.verify_plan_labels(invalid_plan)
        self.assertFalse(res_inv.passed)
        self.assertTrue(len(res_inv.issues) >= 2)

        _progress("Step 5 passed: Display dictionary verified.")

    def test_06_gate_display_labels_clinical_and_pin_compatibility(self):
        _progress("Step 6: Testing gate execution and backward compatibility")

        gate_func = get("display_labels_clinical")
        self.assertIsNotNone(gate_func, "display_labels_clinical gate must be registered")

        project_dir = self.tmp / "project"
        project_dir.mkdir(parents=True)
        
        # 1. State with engine_pin = 1.28.0 (legacy) -> should pass even with code labels
        state = State(project_dir).create("medpaper", "1.28.0", "S10_tables")
        state.data["engine_pin"] = "1.28.0"
        state.save()

        proto_dir = project_dir / "01_protocol"
        proto_dir.mkdir(parents=True)
        plan_data = {
            "main_tables": [
                {"id": "Table 1", "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1"}
            ],
            "main_figures": []
        }
        (proto_dir / "artifact_plan.json").write_text(json.dumps(plan_data), encoding="utf-8")

        # Add a table with snake_case
        tbl_dir = project_dir / "04_tables" / "main"
        tbl_dir.mkdir(parents=True)
        write_table(
            path=str(tbl_dir / "Table1.xlsx"),
            sheet="Table 1",
            title="Table 1. Characteristics.",
            header=["Characteristic", "patient_cohort_a"],
            rows=[["sbp_val", "120 (10)"]],
            footnotes=["Notes."],
        )

        stage_s10 = self.pipe.stage("S10_tables")
        ctx_legacy = Ctx(self.pipe, state, project_dir, stage_s10, {"kind": "all", "since": "1.29.0"})
        gate_res_legacy = gate_func(ctx_legacy)
        self.assertTrue(gate_res_legacy.ok, "engine_pin 1.28.0 must bypass 1.29.0 check")
        self.assertIn("1.29.0", gate_res_legacy.detail)

        # 2. Upgrade engine_pin to 1.29.0 -> must FAIL
        state.data["engine_pin"] = "1.29.0"
        state.data["pipeline_version"] = "1.29.0"
        state.save()

        ctx_129 = Ctx(self.pipe, state, project_dir, stage_s10, {"kind": "all", "since": "1.29.0"})
        gate_res_129 = gate_func(ctx_129)
        self.assertFalse(gate_res_129.ok, "engine_pin 1.29.0 must fail on snake_case in tables")

        # 3. Clean up table to clinical standard -> must PASS
        write_table(
            path=str(tbl_dir / "Table1.xlsx"),
            sheet="Table 1",
            title="Table 1. Patient baseline characteristics.",
            header=["Characteristic", "Study cohort (n=100)"],
            rows=[["Systolic blood pressure, mmHg, mean (SD)", "120 (10)"]],
            footnotes=["Data are presented as mean (SD)."],
        )

        ctx_clean = Ctx(self.pipe, state, project_dir, stage_s10, {"kind": "all", "since": "1.29.0"})
        gate_res_clean = gate_func(ctx_clean)
        self.assertTrue(gate_res_clean.ok, "Clean clinical table must pass gate")

        _progress("Step 6 passed: Gate enforcement and backward compatibility verified.")


if __name__ == "__main__":
    unittest.main()
