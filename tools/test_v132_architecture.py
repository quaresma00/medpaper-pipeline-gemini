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


if __name__ == "__main__":
    unittest.main(verbosity=2)
