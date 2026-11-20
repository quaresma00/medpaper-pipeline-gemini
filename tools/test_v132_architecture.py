#!/usr/bin/env python3
"""Regression suite for v1.32.0 universal clinical workflow & display architecture."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))


class V132ArchitectureTests(unittest.TestCase):
    def test_01_multi_source_reference_provenance_and_tamper_rejection(self) -> None:
        print("[1/6] Testing multi-track PubMed + Crossref DOI + R citation provenance...", flush=True)
        from pubmed import build_library as bl
        from pubmed import eutils as eu
        from pubmed import verify as vf
        from wfcore import refproof, registry
        from wfcore.checks import Ctx, get, load_all
        from wfcore.state import State

        load_all()
        pipe = registry.load()

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "project"
            (proj / "06_refs/cache").mkdir(parents=True)
            st = State(proj, ".wf").create("medpaper", pipe.meta["version"], "S13_reflib")

            # 1) PubMed XML fixture
            pm_xml = (
                b'<?xml version="1.0"?><PubmedArticleSet><PubmedArticle><MedlineCitation>'
                b'<PMID>33445566</PMID><Article><Journal><JournalIssue><PubDate><Year>2024</Year>'
                b'</PubDate></JournalIssue><Title>Journal of Clinical Oncology</Title></Journal>'
                b'<ArticleTitle>Prospective multicenter survival cohort.</ArticleTitle>'
                b'<Abstract><AbstractText>Patients were followed prospectively for 36 months.</AbstractText></Abstract>'
                b'<AuthorList><Author><LastName>Adams</LastName><ForeName> Clara</ForeName><Initials>C</Initials></Author></AuthorList>'
                b'</Article></MedlineCitation><PubmedData><ArticleIdList>'
                b'<ArticleId IdType="doi">10.1200/jco.2024.01</ArticleId>'
                b'</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>'
            )
            pm_rel = "06_refs/cache/verify_efetch_pubmed_test_20260101T000000Z.xml"
            pm_path = proj / pm_rel
            pm_path.write_bytes(pm_xml)
            pm_parsed = refproof.parse_pubmed_payload(pm_xml)["33445566"]
            pm_parsed["cache_file"] = pm_rel
            pm_parsed["cache_sha256"] = refproof.file_sha256(pm_path)
            pm_parsed["fresh_fetch"] = True

            # 2) Crossref foundational methodology DOI fixture (Benjamini & Hochberg 1995)
            cr_json = json.dumps({
                "status": "ok",
                "message": {
                    "DOI": "10.1111/j.2517-6161.1995.tb02031.x",
                    "title": ["Controlling the False Discovery Rate: A Practical and Powerful Approach to Multiple Testing"],
                    "container-title": ["Journal of the Royal Statistical Society Series B"],
                    "issued": {"date-parts": [[1995]]},
                    "author": [
                        {"family": "Benjamini", "given": "Yoav"},
                        {"family": "Hochberg", "given": " Yosef"},
                    ],
                    "type": "journal-article",
                },
            }).encode("utf-8")
            cr_rel = "06_refs/cache/verify_crossref_bh1995_20260101T000000Z.json"
            cr_path = proj / cr_rel
            cr_path.write_bytes(cr_json)
            cr_parsed = refproof.parse_crossref_payload(cr_json)
            cr_parsed["cache_file"] = cr_rel
            cr_parsed["cache_sha256"] = refproof.file_sha256(cr_path)
            cr_parsed["fresh_fetch"] = True

            # 3) Real R citation record if Rscript is available
            with mock.patch.dict(os.environ, {"MEDPAPER_PROJECT": str(proj)}):
                r_rec = eu.r_citation_record("survival", fresh=True, purpose="verify")

            taken: set[str] = set()
            e_pm = bl._entry_from_record({**pm_parsed, "source": "pubmed"}, taken)
            e_cr = bl._entry_from_record({**cr_parsed, "source": "crossref", "authority_kind": "methodology_doi"}, taken)
            e_au = bl._entry_from_record(r_rec, taken)

            entries = [e_pm, e_cr, e_au]
            lib_path = proj / "06_refs/library.json"
            lib_path.write_text(json.dumps({"entries": entries}, indent=2, ensure_ascii=False), encoding="utf-8")

            entries_sorted = sorted(entries, key=lambda x: x["citekey"])
            (proj / "06_refs/refs.bib").write_text(bl.to_bibtex(entries_sorted), encoding="utf-8")
            (proj / "06_refs/refs.ris").write_text(bl.to_ris(entries_sorted), encoding="utf-8")

            r_pm = vf.verify_entry(e_pm, pm_parsed, False, project=proj)
            r_cr = vf.verify_entry(e_cr, cr_parsed, False, project=proj)
            r_au = vf.verify_entry(e_au, r_rec, False, project=proj)
            self.assertTrue(r_pm["verified"] and r_cr["verified"] and r_au["verified"])

            verified_doc = {
                "schema": refproof.SCHEMA,
                "generator": {
                    "tool": refproof.GENERATOR,
                    "mode": "fresh_multi_authority_verify",
                    "source": "NCBI PubMed EFetch + Crossref/Authority",
                },
                "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "strict": False,
                "library_sha256": refproof.file_sha256(lib_path),
                "n_entries": 3,
                "n_verified": 3,
                "records": {
                    e_pm["citekey"]: r_pm,
                    e_cr["citekey"]: r_cr,
                    e_au["citekey"]: r_au,
                },
            }
            (proj / "06_refs/verified.json").write_text(json.dumps(verified_doc, indent=2), encoding="utf-8")

            ok, problems, cnt = refproof.validate_local_proof(proj)
            self.assertTrue(ok, msg=f"validate_local_proof failed: {problems}")
            self.assertEqual(cnt, 3)

            ctx_bib = Ctx(pipe, st, proj, pipe.stage("S13_reflib"), {"check": "bib_ris_match_library"})
            res_bib = get("bib_ris_match_library")(ctx_bib)
            self.assertTrue(res_bib.ok, msg=res_bib.detail)

            ctx_lib = Ctx(pipe, st, proj, pipe.stage("S13_reflib"), {"check": "refs_library", "min_entries": 3})
            res_lib = get("refs_library")(ctx_lib)
            self.assertTrue(res_lib.ok, msg=res_lib.detail)

            with mock.patch("pubmed.eutils.efetch", return_value=[pm_parsed]), \
                 mock.patch("pubmed.eutils.crossref_fetch", return_value=cr_parsed), \
                 mock.patch("pubmed.eutils.r_citation_record", return_value=r_rec):
                ctx_live = Ctx(pipe, st, proj, pipe.stage("S13_reflib"), {"check": "reference_provenance", "live": True})
                res_live = get("reference_provenance")(ctx_live)
                self.assertTrue(res_live.ok, msg=res_live.detail)

            # Negative check: tampering Crossref year in library.json even after updating library_sha256 must fail
            entries[1]["year"] = "1999"
            lib_path.write_text(json.dumps({"entries": entries}, indent=2, ensure_ascii=False), encoding="utf-8")
            verified_doc["library_sha256"] = refproof.file_sha256(lib_path)
            (proj / "06_refs/verified.json").write_text(json.dumps(verified_doc, indent=2), encoding="utf-8")
            ok_tampered, probs_tampered, _ = refproof.validate_local_proof(proj)
            self.assertFalse(ok_tampered)
            self.assertTrue(any("year differs from Crossref payload" in p for p in probs_tampered))

    def test_02_genre_aware_quotas_and_candidate_pool_archival(self) -> None:
        print("[2/6] Testing article_genre Brief_Report quotas & candidate-pool archival...", flush=True)
        from wfcore import registry
        from wfcore.checks import Ctx, get, load_all
        from wfcore.state import State

        load_all()
        pipe = registry.load()

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "project"
            (proj / "01_protocol").mkdir(parents=True)
            (proj / "06_refs").mkdir(parents=True)
            (proj / "07_manuscript").mkdir(parents=True)
            st = State(proj, ".wf").create("medpaper", pipe.meta["version"], "S07_artifacts")

            cur_year = datetime.now(timezone.utc).year
            bench = {
                "comparators": [
                    {"citekey": f"comp{i}", "year": cur_year - 1, "observations": {"main_figures": 2, "figure_types": "forest + survival"}}
                    for i in range(1, 4)
                ],
                "adaptation": {"displays": {"figure_count_rationale": "Concise brief report matching 3 recent pharmacovigilance brief communications."}},
            }
            plan = {
                "main_figures": [{"id": "Figure 1"}],
                "main_tables": [{"id": "Table 1"}],
            }
            (proj / "01_protocol/artifact_benchmark.json").write_text(json.dumps(bench), encoding="utf-8")
            (proj / "01_protocol/artifact_plan.json").write_text(json.dumps(plan), encoding="utf-8")

            # Default Original_Article must reject 3 comparators & 1 figure
            ctx_orig = Ctx(pipe, st, proj, pipe.stage("S07_artifacts"), {"check": "benchmark_display_sufficiency"})
            self.assertFalse(get("benchmark_display_sufficiency")(ctx_orig).ok)

            # Brief_Report without rationale must also be rejected
            (proj / "01_protocol/analysis_contract.json").write_text(
                json.dumps({"article_genre": "Brief_Report"}), encoding="utf-8"
            )
            self.assertFalse(get("benchmark_display_sufficiency")(ctx_orig).ok)

            # Brief_Report with substantive rationale passes with 3 comparators and 1 figure + 1 table
            (proj / "01_protocol/analysis_contract.json").write_text(
                json.dumps({
                    "article_genre": "Brief_Report",
                    "genre_rationale": "Focused rare safety-signal evaluation with compact cohort size suited to a Brief Report format.",
                }),
                encoding="utf-8",
            )
            res_brief = get("benchmark_display_sufficiency")(ctx_orig)
            self.assertTrue(res_brief.ok, msg=res_brief.detail)

            # Literature sufficiency & candidate archival
            entries = [{"citekey": f"ref{i}", "year": str(cur_year - 1)} for i in range(15)]
            entries[14]["pool_role"] = "candidate"
            (proj / "06_refs/library.json").write_text(json.dumps({"entries": entries}), encoding="utf-8")
            ctx_lib = Ctx(pipe, st, proj, pipe.stage("S13_reflib"), {"check": "literature_sufficiency", "mode": "library"})
            self.assertTrue(get("literature_sufficiency")(ctx_lib).ok)

            # Cite ref0..ref9 in introduction/discussion; ref10..ref13 uncited without reason -> fail first
            (proj / "07_manuscript/introduction.md").write_text(" ".join(f"[@ref{i}]" for i in range(4)), encoding="utf-8")
            (proj / "07_manuscript/discussion.md").write_text(" ".join(f"[@ref{i}]" for i in range(4, 10)), encoding="utf-8")
            ctx_usage = Ctx(pipe, st, proj, pipe.stage("S17_assemble"), {"check": "reference_usage"})
            self.assertFalse(get("reference_usage")(ctx_usage).ok)

            # Run build_library.py --archive-uncited and recheck
            env = {**os.environ, "MEDPAPER_PROJECT": str(proj), "MEDPAPER_ROOT": str(ROOT)}
            proc = subprocess.run(
                [sys.executable, str(ROOT / "tools/pubmed/build_library.py"), "--archive-uncited"],
                capture_output=True, text=True, env=env, check=False,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertTrue(get("reference_usage")(ctx_usage).ok)

    def test_03_clinical_units_proportions_and_measure_families(self) -> None:
        print("[3/6] Testing clinical unit scrub, statistical percentage modes & MEASURE_FAMILIES...", flush=True)
        from wfcore import claims, proportions
        from wfcore.checks.numbers import _offenders

        # Standard clinical units/stagings do not trigger false unprovenanced-number errors
        prose = (
            "Baseline eGFR < 60 mL/min/1.73 m² (or 1.73 m2), tumor stage cT2N0M0, ECOG status 0-1, "
            "NYHA class II-III, CHA2DS2-VASc score, and 1-, 3-, and 5-year survival were assessed."
        )
        offenders = _offenders(prose, {60.0}, {"60"}, set())
        self.assertEqual(offenders, [], msg=f"Unexpected offenders: {offenders}")
        # Genuine unbacked clinical value still flagged
        self.assertTrue(_offenders("Median biomarker level was 87.4 ng/mL.", {60.0}, {"60"}, set()))

        # Statistical proportion modes: weighted_survey, survival_km, cif, pooled_mi
        catalog = {
            "f_svy": {
                "values": {"pct_w": 14.23, "n_unw": 142, "N_unw": 1150},
                "context": {"percentage_kind": "weighted_survey", "percentage_basis": "NHANES MEC survey-weighted adults"},
            },
            "f_km": {
                "values": {"km_3y": 78.41, "n_at_risk_0": 420},
                "context": {"percentage_kind": "survival_km", "percentage_basis": "Kaplan-Meier 3-year OS estimate"},
            },
            "f_mi": {
                "values": {"mi_pct": 23.6, "N_total": 500, "m_imputations": 20},
                "context": {"percentage_kind": "pooled_mi", "percentage_basis": "Rubin pooled across 20 MICE imputations"},
            },
        }
        claim_ok = {
            "fact_ids": ["f_svy", "f_km", "f_mi"],
            "different_percentage_bases": "survey-weighted prevalence, KM survival, and MI pooled proportion",
            "proportions": [
                {"fact_id": "f_svy", "reported": "14.2%", "percentage_key": "pct_w", "unweighted_n_key": "n_unw", "denominator_key": "N_unw"},
                {"fact_id": "f_km", "reported": "78.4%", "percentage_key": "km_3y", "at_risk_key": "n_at_risk_0"},
                {"fact_id": "f_mi", "reported": "23.6%", "percentage_key": "mi_pct", "denominator_key": "N_total"},
            ],
        }
        clause = "Estimates were 14.2%, 78.4%, and 23.6% (survey-weighted prevalence, KM survival, and MI pooled proportion)."
        self.assertEqual(proportions.validate(claim_ok, catalog, clause), [])

        # Wrong percentage must fail
        claim_bad = json.loads(json.dumps(claim_ok))
        claim_bad["proportions"][0]["reported"] = "19.2%"
        self.assertTrue(proportions.validate(claim_bad, catalog, clause.replace("14.2%", "19.2%")))

        # Expanded MEASURE_FAMILIES
        for fam in ("regression_slope", "rmst_difference", "geometric_mean_ratio",
                    "predictive_value", "reclassification", "heterogeneity_i2", "mendelian_randomization_ivw"):
            self.assertIn(fam, claims.MEASURE_FAMILIES)

    def test_04_threeline_to_wordtables_lossless_inheritance(self) -> None:
        print("[4/6] Testing threeline.py (.xlsx) -> wordtables.py (.docx) style inheritance...", flush=True)
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from tables.threeline import write_table
        from wfcore import wordtables

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            xlsx_rel = "04_tables/main/table1_baseline.xlsx"
            write_table(
                proj / xlsx_rel,
                sheet="Table 1",
                title="Table 1. Baseline characteristics by treatment exposure.",
                header=["Characteristic", "Exposed (n = 120)", "Unexposed (n = 240)", "P value"],
                rows=[
                    ["Age group, n (%)", "", "", ""],
                    ["< 65 years", "70 (58.3)", "160 (66.7)", "0.042"],
                    [">= 65 years", "50 (41.7)", "80 (33.3)", ""],
                ],
                footnotes=["Abbreviations: n, number of patients."],
                group_rows=[0],
                indent_rows=[1, 2],
                align=["left", "center", "center", "right"],
                col_widths=[36.0, 14.0, 14.0, 10.0],
            )
            doc = Document()
            style = {
                "paper_size": "LETTER",
                "margins_in": 1.0,
                "body_font_pt": 10.0,
                "font_name": "Times New Roman",
                "line_spacing": 1.15,
            }
            wordtables.append_tables(
                doc,
                proj,
                [{"id": "Table 1", "file": xlsx_rel, "sheet": "Table 1", "caption": "Table 1. Baseline characteristics."}],
                style,
            )
            self.assertEqual(wordtables.table_problems(doc), [])
            tbl = doc.tables[0]
            # Column 0 width weight (36.0) > Column 3 width weight (10.0)
            self.assertGreater(tbl.columns[0].width, tbl.columns[3].width)
            # Group row (row index 1 in table: row 0 is header) preserves bold
            self.assertTrue(all(r.bold for r in tbl.cell(1, 0).paragraphs[0].runs))
            # Indented sub-row (row index 2) preserves paragraph left_indent without leading spaces in text
            self.assertEqual(tbl.cell(2, 0).text, "<\u00a065 years")
            self.assertFalse(tbl.cell(2, 0).text.startswith(" "))
            self.assertIsNotNone(tbl.cell(2, 0).paragraphs[0].paragraph_format.left_indent)
            self.assertGreater(tbl.cell(2, 0).paragraphs[0].paragraph_format.left_indent, 0)
            # Right-aligned P value column preserved on data row
            self.assertEqual(tbl.cell(2, 3).paragraphs[0].alignment, WD_ALIGN_PARAGRAPH.RIGHT)

    def test_05_reproduce_float_rtol_and_loop_preserve_unaffected(self) -> None:
        print("[5/6] Testing reproduce.py bounded float_rtol & wf loop --preserve-unaffected...", flush=True)
        from analysis import reproduce as rp
        from wfcore import cli, registry
        from wfcore.state import State

        base = {"n_events": 42, "hr": 1.8500000000001, "environment": {"writer": "medpaper-results-v1", "float_rtol": 1e-12}}
        near = {"n_events": 42, "hr": 1.8500000000002, "environment": {"writer": "medpaper-results-v1", "float_rtol": 1e-12}}
        count_diff = {"n_events": 43, "hr": 1.8500000000001, "environment": {"writer": "medpaper-results-v1", "float_rtol": 1e-12}}
        excessive_tol = {"n_events": 42, "hr": 1.85, "environment": {"writer": "medpaper-results-v1", "float_rtol": 1e-5}}

        self.assertTrue(rp.canonical_equal(near, base))
        self.assertFalse(rp.canonical_equal(count_diff, base))
        with self.assertRaises(ValueError):
            rp.canonical_equal(near, excessive_tol)

        pipe = registry.load()
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "project"
            proj.mkdir(parents=True)
            st = State(proj, ".wf").create("medpaper", pipe.meta["version"], "S10_tables")
            st.record_decision("tables_visually_confirmed", "YES", "All rendered table PNG previews inspected with zero clipping.")
            st.complete("S10_tables", "S11_figures")
            st.clear_decisions_for(["S10_tables", "S11_figures"], preserve_names={"tables_visually_confirmed"})
            self.assertIsNotNone(st.decision("tables_visually_confirmed"))
            st.clear_decisions_for(["S10_tables", "S11_figures"])
            self.assertIsNone(st.decision("tables_visually_confirmed"))
            _ = cli

    def test_06_r_recipes_clinical_forest_consort_km_and_subtitle_gate(self) -> None:
        print("[6/6] Testing real R rendering of medpaper_clinical_forest, consort_flow, km_survival & QC gates...", flush=True)
        if not shutil.which("Rscript"):
            self.skipTest("Rscript not installed")
        from figures import qc, render_r
        from wfcore import displaylabels

        # Verify displaylabels catches Model 1a and bare Group 2, while allowing Stage 2 / Type 2
        self.assertIsNotNone(displaylabels.NUMBERED_MODEL_RE.search("Model 1a"))
        issues_bad = displaylabels.diagnose_label_token(
            "Group 2", path="04_tables/main/t.xlsx", locator="A4", surface="stub"
        )
        self.assertEqual([i["kind"] for i in issues_bad], ["raw_coding_label"])
        issues_ok = displaylabels.diagnose_label_token(
            "Stage 2 tumor with Type 2 diabetes (Grade 3)", path="04_tables/main/t.xlsx", locator="A5", surface="stub"
        )
        self.assertEqual(issues_ok, [])

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "project"
            (proj / "01_protocol").mkdir(parents=True)
            (proj / "03_analysis/results").mkdir(parents=True)
            (proj / "05_figures/out").mkdir(parents=True)
            (proj / "05_figures/qc").mkdir(parents=True)
            (proj / "07_manuscript").mkdir(parents=True)
            (proj / ".wf").mkdir(parents=True)
            (proj / ".wf/state.json").write_text(
                json.dumps({"pipeline_version": "1.32.0", "engine_pin": "1.32.0", "current": "S11_figures"}),
                encoding="utf-8",
            )

            res_payload = {
                "flow": {"db_a": 600, "db_b": 400, "merged": 1000, "excluded": 180, "analytic": 820},
                "forest": {"hr_yes": 1.65, "lo_yes": 1.18, "hi_yes": 2.31, "p_int": 0.038},
                "km": {"n0_a": 410, "n0_b": 410},
            }
            (proj / "03_analysis/results/v132.json").write_text(json.dumps(res_payload), encoding="utf-8")

            # Figure 1: multi-source orthogonal CONSORT flow with detail exclusions
            (proj / "05_figures/out/fig1_flow.R").write_text(
                'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_style.R"))\n'
                'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_recipes.R"))\n'
                'r <- medpaper_result("03_analysis/results/v132.json")\n'
                'nodes <- data.frame(\n'
                '  id = c("a", "b", "m", "ex", "fin"),\n'
                '  label = c("Registry cohort A", "Registry cohort B", "Combined screened records", "Excluded records", "Primary analytic cohort"),\n'
                '  n = c(600, 400, 1000, 180, 820),\n'
                '  x = c(0.26, 0.74, 0.50, 0.92, 0.50),\n'
                '  y = c(0.90, 0.90, 0.62, 0.36, 0.14),\n'
                '  detail = c("", "", "", "Age < 18 years (n = 100)\\nMissing follow-up (n = 80)", ""),\n'
                '  stringsAsFactors = FALSE\n'
                ')\n'
                'edges <- data.frame(from = c("a", "b", "m", "m"), to = c("m", "m", "ex", "fin"), stringsAsFactors = FALSE)\n'
                'p <- medpaper_consort_flow(nodes, edges, box_width = 0.34, box_height = 0.14, orthogonal = TRUE)\n'
                'medpaper_save(p, "05_figures/out/fig1_flow", width = "double", height_mm = 105)\n',
                encoding="utf-8",
            )

            # Figure 2: multi-column subgroup forest with duplicate Yes/No, Reference, NE, left count col & P for interaction
            (proj / "05_figures/out/fig2_forest.R").write_text(
                'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_style.R"))\n'
                'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_recipes.R"))\n'
                'df <- data.frame(\n'
                '  label = c("Exposure group", "Unexposed", "Exposed", "Prior hypertension", "Yes", "No", "Rare stratum"),\n'
                '  events_n = c("", "24/240", "38/180", "", "30/190", "32/230", "0/12"),\n'
                '  estimate = c(NA, NA, 1.65, NA, 1.82, 1.44, NA),\n'
                '  lower = c(NA, NA, 1.18, NA, 1.21, 0.96, NA),\n'
                '  upper = c(NA, NA, 2.31, NA, 2.74, 2.16, NA),\n'
                '  status = c("", "Reference", "", "", "", "", "NE"),\n'
                '  p_int = c("", "", "", "0.38", "", "", ""),\n'
                '  is_group = c(TRUE, FALSE, FALSE, TRUE, FALSE, FALSE, FALSE),\n'
                '  indent = c(FALSE, TRUE, TRUE, FALSE, TRUE, TRUE, TRUE),\n'
                '  stringsAsFactors = FALSE\n'
                ')\n'
                'res <- medpaper_clinical_forest(\n'
                '  df, measure = "Adjusted hazard ratio", null = 1, log_scale = TRUE,\n'
                '  left_cols = "events_n", left_headers = "Events/N",\n'
                '  p_interaction_col = "p_int", p_interaction_header = "P interaction"\n'
                ')\n'
                'medpaper_save(res$plot, "05_figures/out/fig2_forest", width = "double", height_mm = 88, panels = res$panels)\n',
                encoding="utf-8",
            )

            # Figure 3: KM survival + aligned risk table
            (proj / "05_figures/out/fig3_km.R").write_text(
                'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_style.R"))\n'
                'source(file.path(Sys.getenv("MEDPAPER_ROOT"), "tools/figures/r_recipes.R"))\n'
                'curve_df <- data.frame(\n'
                '  time = c(0, 12, 24, 36, 0, 12, 24, 36),\n'
                '  surv = c(1.00, 0.92, 0.85, 0.79, 1.00, 0.86, 0.74, 0.66),\n'
                '  group = rep(c("Standard therapy", "Intensive therapy"), each = 4),\n'
                '  stringsAsFactors = FALSE\n'
                ')\n'
                'censor_df <- data.frame(\n'
                '  time = c(18, 30), surv = c(0.88, 0.70),\n'
                '  group = c("Standard therapy", "Intensive therapy"), stringsAsFactors = FALSE\n'
                ')\n'
                'risk_df <- data.frame(\n'
                '  time = rep(c(0, 12, 24, 36), 2),\n'
                '  n_risk = c(410, 380, 342, 298, 410, 355, 304, 251),\n'
                '  group = rep(c("Standard therapy", "Intensive therapy"), each = 4),\n'
                '  stringsAsFactors = FALSE\n'
                ')\n'
                'km <- medpaper_km_survival(curve_df, risk_df, censor_data = censor_df, x_label = "Months since index date", p_label = "Log-rank P = 0.012")\n'
                'medpaper_save(km$plot, "05_figures/out/fig3_km", width = "double", height_mm = 115, panels = km$panels)\n',
                encoding="utf-8",
            )

            plan = {
                "main_figures": [
                    {
                        "id": "Figure 1",
                        "renderer": "R",
                        "archetype": "flow_diagram",
                        "width": "double",
                        "script": "05_figures/out/fig1_flow.R",
                        "file": "05_figures/out/fig1_flow.png",
                        "pdf": "05_figures/out/fig1_flow.pdf",
                        "source_results": ["03_analysis/results/v132.json"],
                    },
                    {
                        "id": "Figure 2",
                        "renderer": "R",
                        "archetype": "forest_plot",
                        "width": "double",
                        "script": "05_figures/out/fig2_forest.R",
                        "file": "05_figures/out/fig2_forest.png",
                        "pdf": "05_figures/out/fig2_forest.pdf",
                        "source_results": ["03_analysis/results/v132.json"],
                    },
                    {
                        "id": "Figure 3",
                        "renderer": "R",
                        "archetype": "km_survival",
                        "width": "double",
                        "script": "05_figures/out/fig3_km.R",
                        "file": "05_figures/out/fig3_km.png",
                        "pdf": "05_figures/out/fig3_km.pdf",
                        "source_results": ["03_analysis/results/v132.json"],
                    },
                ],
                "supp_figures": [],
            }
            (proj / "01_protocol/artifact_plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
            (proj / "07_manuscript/claim_bindings.json").write_text(
                json.dumps({"schema_version": 2, "facts": [], "prose_claims": [], "table_claims": [], "figure_annotations": []}),
                encoding="utf-8",
            )

            for fid in ("Figure 1", "Figure 2", "Figure 3"):
                render_r.render(proj, fid)

            arch = qc.load_archetypes()
            # Avoid numeric figure_annotation binding check on pure visual structural check by testing structural/QC checks
            for idx, fid in enumerate(("Figure 1", "Figure 2", "Figure 3")):
                rep = qc._qc_figure(plan["main_figures"][idx], {}, arch, proj)
                structural_failures = [
                    c for c in rep["checks"]
                    if not c["ok"] and c["severity"] == "fail" and c["name"] != "figure_annotation_provenance"
                ]
                self.assertEqual(structural_failures, [], msg=f"{fid} failed QC: {structural_failures}")

            # Verify no_figure_subtitle blocks any injected subtitle metadata
            sidecar_p = proj / "05_figures/qc/fig2_forest.artist.json"
            art_doc = json.loads(sidecar_p.read_text(encoding="utf-8"))
            art_doc["subtitles_found"] = ["Multivariable Cox model adjusted for age"]
            sidecar_p.write_text(json.dumps(art_doc), encoding="utf-8")
            rep_sub = qc._qc_figure(plan["main_figures"][1], {}, arch, proj)
            sub_chk = next(c for c in rep_sub["checks"] if c["name"] == "no_figure_subtitle")
            self.assertFalse(sub_chk["ok"])

    def test_07_s20_journal_display_fit_and_pristine_workspace_no_deadlock(self) -> None:
        print("[7/8] Testing S20/S22 journal_display_fit & journal_workspace_ready deadlock resolution...", flush=True)
        from wfcore import journalworkspace, registry
        from wfcore.checks import Ctx, get, load_all
        from wfcore.packagefreeze import _sha256
        from wfcore.state import State

        load_all()
        pipe = registry.load()

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "project"
            for d in ("01_protocol", "04_tables", "05_figures", "07_manuscript", "08_submission/integration"):
                (proj / d).mkdir(parents=True)
            st = State(proj, ".wf").create("medpaper", pipe.meta["version"], "S20_journal")

            sci_plan = {
                "main_figures": [{"id": f"Figure {i}"} for i in range(1, 6)],
                "main_tables": [{"id": f"Table {i}"} for i in range(1, 4)],
                "supp_figures": [{"id": "Figure S1"}],
                "supp_tables": [{"id": "Table S1"}],
            }
            (proj / "01_protocol/artifact_plan.json").write_text(json.dumps(sci_plan, indent=2), encoding="utf-8")
            (proj / "08_submission/integration/artifact_plan.json").write_text(json.dumps(sci_plan, indent=2), encoding="utf-8")
            (proj / "07_manuscript/full_manuscript.md").write_text("# Abstract\n\nFrozen science.\n", encoding="utf-8")
            (proj / "08_submission/integration/full_manuscript.md").write_text("# Abstract\n\nFrozen science.\n", encoding="utf-8")

            freeze_files = [
                {"path": "01_protocol/artifact_plan.json", "sha256": journalworkspace._sha256(proj / "01_protocol/artifact_plan.json")},
                {"path": "07_manuscript/full_manuscript.md", "sha256": journalworkspace._sha256(proj / "07_manuscript/full_manuscript.md")},
            ]
            ws_manifest = {
                "schema_version": 1,
                "scientific_freeze_id": "freeze-1",
                "journal": "Clinical Research Journal",
                "issn": "1234-5678",
                "files": [
                    {
                        "source": "01_protocol/artifact_plan.json",
                        "source_sha256": freeze_files[0]["sha256"],
                        "destination": "08_submission/integration/artifact_plan.json",
                        "initial_destination_sha256": freeze_files[0]["sha256"],
                    },
                    {
                        "source": "07_manuscript/full_manuscript.md",
                        "source_sha256": freeze_files[1]["sha256"],
                        "destination": "08_submission/integration/full_manuscript.md",
                        "initial_destination_sha256": freeze_files[1]["sha256"],
                    },
                ],
            }
            (proj / "08_submission/target_journal.json").write_text(
                json.dumps({"journal": "Clinical Research Journal", "issn": "1234-5678"}), encoding="utf-8"
            )
            (proj / "08_submission/integration/journal_workspace.json").write_text(
                json.dumps(ws_manifest, indent=2), encoding="utf-8"
            )
            (proj / "08_submission/submission_requirements.json").write_text(
                json.dumps({
                    "article_type": "Research",
                    "display_limits": {
                        "main_display_items": {
                            "status": "required",
                            "value": 6,
                            "source": "https://journal.example/guidelines",
                            "article_type": "Research",
                        }
                    },
                }),
                encoding="utf-8",
            )

            ctx_s20 = Ctx(pipe, st, proj, pipe.stage("S20_journal"), {"check": "journal_display_fit"})
            ctx_s22 = Ctx(pipe, st, proj, pipe.stage("S22_polish"), {"check": "journal_display_fit"})

            with mock.patch("wfcore.journalworkspace.verify_scientific_freeze", return_value=(True, [], {"freeze_id": "freeze-1", "files": freeze_files})), \
                 mock.patch("wfcore.journalcontext.enabled", return_value=False):
                # Route A: integration/artifact_plan.json kept pristine at S20 -> both S20 gates pass; S22 blocks until adapted
                self.assertTrue(journalworkspace.verify(proj, require_pristine=True)[0])
                self.assertTrue(get("journal_display_fit")(ctx_s20).ok)
                self.assertFalse(get("journal_display_fit")(ctx_s22).ok)

                # Route B: integration/artifact_plan.json adapted at S20 (<= 6 main displays + reason) -> both S20 and S22 pass!
                adapted_plan = {
                    "main_figures": [{"id": f"Figure {i}"} for i in range(1, 4)],
                    "main_tables": [{"id": f"Table {i}"} for i in range(1, 4)],
                    "supp_figures": [{"id": "Figure S1"}, {"id": "Figure S2"}, {"id": "Figure S3"}],
                    "supp_tables": [{"id": "Table S1"}],
                    "journal_adaptation_reason": "Retained 3 core figures and 3 tables (6 total) in main text and moved 2 sensitivity figures to supplement per journal 6-item cap.",
                }
                (proj / "08_submission/integration/artifact_plan.json").write_text(
                    json.dumps(adapted_plan, indent=2), encoding="utf-8"
                )
                self.assertTrue(journalworkspace.verify(proj, require_pristine=True)[0])
                self.assertTrue(get("journal_display_fit")(ctx_s20).ok)
                self.assertTrue(get("journal_display_fit")(ctx_s22).ok)

                # Mutating prose full_manuscript.md before S20 closes is still strictly rejected by require_pristine=True
                (proj / "08_submission/integration/full_manuscript.md").write_text("# Abstract\n\nPremature edit.\n", encoding="utf-8")
                self.assertFalse(journalworkspace.verify(proj, require_pristine=True)[0])

    def test_08_s22_subpanel_renumbering_abbreviation_glossary_and_inline_image_facts(self) -> None:
        print("[8/8] Testing S22 subpanel renumbering, abbreviation glossary stripping & lint_abbreviations...", flush=True)
        from text import polish
        from wfcore import presentation

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "project"
            snap = proj / "08_submission/integration/prepolish"
            snap.mkdir(parents=True)

            before_main = (
                "# Abstract\n\n"
                "Systemic tyrosine kinase inhibitors (TKIs) and immune checkpoint inhibitors (ICIs) were evaluated "
                "across 120 patients (P = 0.004) [@smith2024trial].\n\n"
                "# Introduction\n\n"
                "Prior TKI studies evaluated PD-1, PD-L1, CTLA-4, and LAG-3 pathways under BH-FDR control (Figure 1A, Figure 40).\n\n"
                "# Results\n\n"
                "Sensitivity analyses held across strata (Figure 4A, Figure 4B; HR 1.85, 95% CI 1.22 to 2.81). "
                "Latency was consistent (Figure 5B; median 77.0 days).\n\n"
                "# Declarations and Statements\n\n"
                "## Abbreviations\n\n"
                "BH-FDR, Benjamini-Hochberg false discovery rate; CI, confidence interval; "
                "CTLA-4, cytotoxic T-lymphocyte-associated protein 4; ICI, immune checkpoint inhibitor; "
                "LAG-3, lymphocyte-activation gene 3; PD-1, programmed cell death protein 1; "
                "PD-L1, programmed death-ligand 1; TKI, tyrosine kinase inhibitor; 95% CI, 95% confidence interval.\n"
            )
            before_supp = "# Supplementary Methods\n\nAdditional protocol details.\n"
            before_stmt = (
                "# Declarations and Statements\n\n"
                "## Funding\n\nNone.\n\n"
                "## Abbreviations\n\n"
                "CTLA-4, cytotoxic T-lymphocyte-associated protein 4; LAG-3, lymphocyte-activation gene 3; "
                "PD-1, programmed cell death protein 1; PD-L1, programmed death-ligand 1; 95% CI, 95% confidence interval.\n"
            )

            rel_main = "08_submission/integration/full_manuscript.md"
            rel_supp = "08_submission/integration/supplementary_methods.md"
            rel_stmt = "08_submission/integration/statements.md"

            (snap / "full_manuscript.md").write_text(before_main, encoding="utf-8")
            (snap / "supplementary_methods.md").write_text(before_supp, encoding="utf-8")
            (snap / "statements.md").write_text(before_stmt, encoding="utf-8")

            moved_orig = "Sensitivity analyses held across strata (Figure 4A, Figure 4B; HR 1.85, 95% CI 1.22 to 2.81)."
            moved_after = "Sensitivity analyses held across strata (Figure S3a, Figure S3b; HR 1.85, 95% CI 1.22 to 2.81)."

            after_main = (
                "# Abstract\n\n"
                "Systemic tyrosine kinase inhibitors (TKIs) and immune checkpoint inhibitors (ICIs) were evaluated "
                "across 120 patients (P = 0.004) [@smith2024trial].\n\n"
                "# Introduction\n\n"
                "Prior TKI studies evaluated PD-1, PD-L1, CTLA-4, and LAG-3 pathways under Benjamini-Hochberg false discovery rate (BH-FDR) control (Figure 1a, Figure 40).\n\n"
                "![Figure 1](05_figures/out/Figure1.png){width=6.0in}\n\n"
                "# Results\n\n"
                "Latency was consistent (Figure S4b; median 77.0 days) under BH-FDR thresholds.\n\n"
                "# Declarations and Statements\n\n"
                "## Funding\n\nNone.\n"
            )
            after_supp = before_supp + "\n" + moved_after + "\n"
            after_stmt = "# Declarations and Statements\n\n## Funding\n\nNone.\n"

            (proj / rel_main).write_text(after_main, encoding="utf-8")
            (proj / rel_supp).write_text(after_supp, encoding="utf-8")
            (proj / rel_stmt).write_text(after_stmt, encoding="utf-8")

            index = {
                "snapshot_id": "snap-v132",
                "files": {
                    rel_main: polish.facts(before_main),
                    rel_supp: polish.facts(before_supp),
                    rel_stmt: polish.facts(before_stmt),
                },
            }
            (proj / presentation.MAP).write_text(
                json.dumps({
                    "snapshot_id": "snap-v132",
                    "renumbering": {"Figure 4": "Figure S3", "Figure 5": "Figure S4"},
                    "moves": [{"from": rel_main, "to": rel_supp, "text": moved_orig, "after": moved_after}],
                }),
                encoding="utf-8",
            )

            problems = presentation.check(proj, snap, index, polish.facts)
            self.assertEqual(problems, [], msg=f"Unexpected presentation problems: {problems}")

            docs = [(rel_main, after_main), (rel_supp, after_supp), (rel_stmt, after_stmt)]
            abbr_issues = [x for x in polish.lint_abbreviations(docs) if x["severity"] == "blocking"]
            self.assertEqual(abbr_issues, [], msg=f"Unexpected blocking abbreviation issues: {abbr_issues}")

    def test_09_s23_embedded_figures_preserved_and_wide_inline_tables_landscape_wrapped(self) -> None:
        print("[9/9] Testing S23 apply_docx <w:drawing> preservation, orphan media audit & wide inline table landscape wrapping...", flush=True)
        import re
        import zipfile
        from xml.etree import ElementTree as ET
        from docx import Document
        from docx.enum.section import WD_ORIENT
        from docx.shared import Inches
        from manuscript.build_docx import normalize_docx
        from tables.threeline import write_table
        from wfcore import journalspec, submissionlayout, wordtables

        # Minimal valid 1x1 PNG bytes
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
            b"\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb0\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "project"
            (proj / "04_tables/main").mkdir(parents=True)
            img_path = proj / "fig1.png"
            img_path.write_bytes(png_bytes)

            # Build 2 wide 8-column tables (landscape) and 1 narrow 3-column table (portrait)
            write_table(
                proj / "04_tables/main/t1.xlsx",
                sheet="Table 1",
                title="Table 1. Wide baseline characteristics.",
                header=["Characteristic", "Arm A", "Arm B", "Arm C", "Arm D", "Arm E", "Arm F", "P value"],
                rows=[["Age, mean (SD)", "61.2 (10.1)", "62.4 (9.8)", "60.8 (11.0)", "63.0 (9.5)", "59.9 (10.4)", "61.7 (10.0)", "0.41"]],
                footnotes=["See Table 2 for multivariable regression results."],
            )
            write_table(
                proj / "04_tables/main/t2.xlsx",
                sheet="Table 2",
                title="Table 2. Wide regression models.",
                header=["Model", "Events", "N", "Crude OR", "Adjusted OR", "95% CI Low", "95% CI High", "P value"],
                rows=[["Primary", "42", "500", "2.10", "1.85", "1.22", "2.81", "0.004"]],
                footnotes=["Abbreviations: CI, confidence interval; OR, odds ratio."],
            )
            write_table(
                proj / "04_tables/main/t3.xlsx",
                sheet="Table 3",
                title="Table 3. Compact summary.",
                header=["Subgroup", "Events", "P value"],
                rows=[["Overall", "42", "0.004"]],
                footnotes=["Abbreviations: P, probability value."],
            )

            doc = Document()
            doc.add_heading("Clinical Study Title", level=0)
            doc.add_heading("Results", level=1)
            p_fig = doc.add_paragraph("Tumor colour was analysed across centres (Table 1 and Table 2). ")
            p_fig.add_run().add_picture(str(img_path), width=Inches(1.5))
            doc.add_paragraph("Compact subgroup findings are summarized in Table 3.")
            doc.add_heading("References", level=1)
            doc.add_paragraph("1. Smith A. Clinical study. 2025.")

            style = {
                "font_family": "Times New Roman",
                "body_font_pt": 12,
                "title_font_pt": 14,
                "section_heading_font_pt": 12,
                "subsection_heading_font_pt": 12,
                "line_spacing": 2.0,
                "paragraph_spacing_after_pt": 0,
                "paper_size": "A4",
                "margins_in": 1.0,
                "all_text_black": True,
                "external_hyperlinks": False,
                "journal_profile": {"spelling": "american", "number_format": {}},
                "journal_project": str(proj),
            }
            entries = [
                {"id": "Table 1", "file": "04_tables/main/t1.xlsx", "sheet": "Table 1", "caption": "Table 1. Wide baseline characteristics."},
                {"id": "Table 2", "file": "04_tables/main/t2.xlsx", "sheet": "Table 2", "caption": "Table 2. Wide regression models."},
                {"id": "Table 3", "file": "04_tables/main/t3.xlsx", "sheet": "Table 3", "caption": "Table 3. Compact summary."},
            ]
            wordtables.embed_tables_in_text(doc, proj, entries, style)
            out_docx = proj / "manuscript.docx"
            doc.save(out_docx)

            # Run full normalize_docx (which invokes journalspec.apply_docx + section geometry normalization)
            normalize_docx(out_docx, style, "manuscript")

            # 1) Verify <w:drawing> and <a:blip> survived apply_docx + normalize_docx, while spelling updated
            with zipfile.ZipFile(out_docx) as zf:
                media = [n for n in zf.namelist() if n.startswith("word/media/")]
                xml_root = ET.fromstring(zf.read("word/document.xml"))
            drawings = [n for n in xml_root.iter() if n.tag.rsplit("}", 1)[-1] == "drawing"]
            blips = [n for n in xml_root.iter() if n.tag.rsplit("}", 1)[-1] == "blip"]
            self.assertEqual(len(media), 1)
            self.assertGreaterEqual(len(drawings), 1, msg="Embedded <w:drawing> was destroyed by apply_docx!")
            self.assertGreaterEqual(len(blips), 1, msg="Embedded <a:blip> was destroyed by apply_docx!")
            self.assertEqual(submissionlayout.docx_embedded_media_problems(out_docx, allow_embedded_figures=True), [])

            checked = Document(out_docx)
            full_txt = "\n".join(p.text for p in checked.paragraphs)
            self.assertIn("color", full_txt)
            self.assertIn("analyzed", full_txt)
            self.assertIn("centers", full_txt)

            # 2) Verify section orientations: Portrait (intro+fig) -> Landscape (Table 1) -> Landscape (Table 2) -> Portrait (Table 3 + Refs)
            orientations = [sec.orientation for sec in checked.sections]
            self.assertEqual(
                orientations,
                [WD_ORIENT.PORTRAIT, WD_ORIENT.LANDSCAPE, WD_ORIENT.LANDSCAPE, WD_ORIENT.PORTRAIT],
                msg=f"Unexpected section orientation sequence: {orientations}",
            )
            self.assertEqual(wordtables.table_problems(checked), [])

            # 3) Negative guard: stripped <w:drawing> with orphan word/media/ must be caught by docx_embedded_media_problems
            orphan_docx = proj / "orphan_media.docx"
            with zipfile.ZipFile(out_docx, "r") as zin, zipfile.ZipFile(orphan_docx, "w") as zout:
                for info in zin.infolist():
                    blob = zin.read(info.filename)
                    if info.filename == "word/document.xml":
                        blob = re.sub(rb"<w:drawing\b.*?</w:drawing>", b"", blob, flags=re.S)
                    zout.writestr(info, blob)
            orphan_probs = submissionlayout.docx_embedded_media_problems(orphan_docx, allow_embedded_figures=True)
            self.assertTrue(any("embedded figures were stripped" in p for p in orphan_probs), msg=orphan_probs)

    def test_10_embedded_table_footnotes_and_docx_section_word_counts(self):
        """Non-final table footnotes must survive section breaks; docx_sections & polish must exclude embedded display text and Impact statements."""
        from docx import Document
        from docx.enum.style import WD_STYLE_TYPE
        from docx.oxml.ns import qn
        from manuscript.build_docx import normalize_docx
        from tables.threeline import write_table
        from wfcore import submission, wordtables
        from wfcore.checks.polish import _canonical_section_counts

        with tempfile.TemporaryDirectory() as td:
            proj = Path(td)
            (proj / "04_tables/main").mkdir(parents=True)

            write_table(
                proj / "04_tables/main/t1.xlsx",
                sheet="Table 1",
                title="Table 1. Cohort characteristics.",
                header=["Group", "N", "Age", "Female", "BMI", "Stage", "Score", "P value"],
                rows=[["Exposed", "250", "61.0", "120", "24.1", "III", "1.40", "0.002"]],
                footnotes=[
                    "Table1NoteFirst: values are median and count.",
                    "Table1NoteLast: final footnote on non-final table must survive sectPr.",
                ],
            )
            write_table(
                proj / "04_tables/main/t2.xlsx",
                sheet="Table 2",
                title="Table 2. Multivariable regression.",
                header=["Model", "Events", "N", "Crude OR", "Adjusted OR", "CI Low", "CI High", "P value"],
                rows=[["Primary", "42", "500", "2.10", "1.85", "1.22", "2.81", "0.004"]],
                footnotes=["Table2NoteOnly: final footnote on last table."],
            )

            doc = Document()
            doc.styles.add_style("ImageCaption", WD_STYLE_TYPE.PARAGRAPH)
            doc.add_heading("Clinical Cohort Manuscript Title", level=0)
            doc.add_heading("Abstract", level=1)
            doc.add_heading("Background", level=2)
            doc.add_paragraph("Background abstract narrative sentence.")
            doc.add_heading("Methods", level=2)
            doc.add_paragraph("Structured abstract methods sentence.")
            doc.add_heading("Impact statements", level=2)
            doc.add_paragraph("ImpactStatementMarker clinical takeaway not counted in abstract.")
            doc.add_paragraph("Keywords: cohort; outcomes; safety")
            doc.add_heading("Introduction", level=1)
            doc.add_paragraph("Intro narrative sentence.")
            doc.add_heading("Methods", level=1)
            doc.add_paragraph("Full methods body sentence.")
            doc.add_heading("Results", level=1)
            doc.add_paragraph("Results narrative references Table 1 and Table 2 clearly.")
            doc.add_paragraph("Fig. 1 InlineFigureCaptionMarker showing survival curve.", style="ImageCaption")
            doc.add_heading("Discussion", level=1)
            doc.add_paragraph("Discussion body sentence.")
            doc.add_heading("References", level=1)
            doc.add_paragraph("1. Smith A. Clinical cohort study. 2025.")

            style = {
                "font_family": "Times New Roman",
                "body_font_pt": 12,
                "title_font_pt": 14,
                "section_heading_font_pt": 12,
                "subsection_heading_font_pt": 12,
                "line_spacing": 2.0,
                "paragraph_spacing_after_pt": 0,
                "paper_size": "A4",
                "margins_in": 1.0,
                "all_text_black": True,
                "external_hyperlinks": False,
                "journal_profile": {"spelling": "american", "number_format": {}},
                "journal_project": str(proj),
            }
            entries = [
                {"id": "Table 1", "file": "04_tables/main/t1.xlsx", "sheet": "Table 1", "caption": "Table 1. Cohort characteristics."},
                {"id": "Table 2", "file": "04_tables/main/t2.xlsx", "sheet": "Table 2", "caption": "Table 2. Multivariable regression."},
            ]
            wordtables.embed_tables_in_text(doc, proj, entries, style)
            out_docx = proj / "manuscript.docx"
            doc.save(out_docx)
            normalize_docx(out_docx, style, "manuscript")

            checked = Document(out_docx)
            all_para_text = "\n".join(p.text for p in checked.paragraphs)
            # 1) Non-final table's final footnote must survive sectPr stripping
            self.assertIn("Table1NoteFirst", all_para_text)
            self.assertIn("Table1NoteLast", all_para_text)
            self.assertIn("Table2NoteOnly", all_para_text)

            # 2) Bookmark names <= 40 chars and globally unique; bookmark IDs globally unique
            bm_nodes = list(checked.element.iter(qn("w:bookmarkStart")))
            bm_names = [n.get(qn("w:name")) for n in bm_nodes]
            bm_ids = [n.get(qn("w:id")) for n in bm_nodes]
            self.assertTrue(all(len(name) <= 40 for name in bm_names), msg=bm_names)
            self.assertEqual(len(bm_names), len(set(bm_names)), msg=bm_names)
            self.assertEqual(len(bm_ids), len(set(bm_ids)), msg=bm_ids)
            self.assertTrue(any(name.startswith("medpaper_tblnote_") for name in bm_names))

            # 3) docx_sections must exclude tables, table captions/footnotes, ImageCaption, and Impact statements
            title, sections, full_text = submission.docx_sections(out_docx)
            self.assertEqual(title, "Clinical Cohort Manuscript Title")
            self.assertIn("Structured abstract methods sentence.", sections["Abstract"])
            self.assertNotIn("ImpactStatementMarker", sections["Abstract"])
            self.assertIn("ImpactStatementMarker", sections.get("Impact statements", ""))
            self.assertIn("Full methods body sentence.", sections["Methods"])
            self.assertIn("Results narrative references Table 1 and Table 2 clearly.", sections["Results"])
            self.assertNotIn("Exposed", sections["Results"])
            self.assertNotIn("Table 1. Cohort characteristics.", sections["Results"])
            self.assertNotIn("Table1NoteLast", sections["Results"])
            self.assertNotIn("InlineFigureCaptionMarker", sections["Results"])
            # all_visible (full_text) still contains complete visible document text
            self.assertIn("Exposed", full_text)
            self.assertIn("Table1NoteLast", full_text)
            self.assertIn("InlineFigureCaptionMarker", full_text)
            self.assertIn("ImpactStatementMarker", full_text)

            # 4) Markdown _canonical_section_counts aligns with DOCX exclusion of Impact statements and inline figure lines
            md = (
                "# Abstract\n\n"
                "## Background\n\nAlpha beta gamma.\n\n"
                "## Impact statements\n\nExcluded impact words here.\n\n"
                "Keywords: alpha; beta\n\n"
                "# Results\n\n"
                "Delta epsilon.\n\n"
                "![Fig. 1 Inline caption words excluded.](05_figures/out/Figure1.png){width=6.0in}\n\n"
                "# Conclusion\n\nZeta eta.\n"
            )
            md_counts = _canonical_section_counts(md)
            self.assertEqual(md_counts["abstract"], 4)  # Background + Alpha beta gamma
            self.assertEqual(md_counts["results"], 2)   # Delta epsilon
            self.assertEqual(md_counts["conclusion"], 2)  # Zeta eta


if __name__ == "__main__":
    unittest.main(verbosity=2)
