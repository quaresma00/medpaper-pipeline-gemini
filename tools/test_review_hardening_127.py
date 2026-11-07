#!/usr/bin/env python3
"""v1.27 regression suite: S16 Discussion bindings, prose measure/unit & interval level,
S10 table row/column context & borderline P-values, S11 figure statistical annotations,
S25 non-overridable decision guard, cross-drive launcher, and pandoc-optional selftest.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from tables.threeline import p_value, write_table  # noqa: E402
from wfcore import claims, cli, registry, sourceclaims  # noqa: E402
from wfcore.checks import Ctx, Result, get, load_all  # noqa: E402
from wfcore.checks.artifacts import figures_qc_pass, submission_audit_matches_freeze  # noqa: E402
from wfcore.checks.numbers import numbers_have_provenance  # noqa: E402
from wfcore.checks.statecheck import decision_recorded  # noqa: E402
from wfcore.readiness import atomic_json  # noqa: E402
from wfcore.state import State  # noqa: E402


def _progress(label: str) -> None:
    print(f"[1.27 regression] {label}", flush=True)


class DiscussionProvenanceTests(unittest.TestCase):
    """P1-1: S16 Discussion own-study bindings + external source_claims coexistence."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="medpaper-disc-127-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.state = State(self.project).create("medpaper", "1.27.0", "S16_discussion")
        self.pipe = registry.load()
        load_all()
        self.rel = "07_manuscript/discussion.md"
        self.context = {
            "outcome": "all-cause mortality",
            "population": "hospitalized adults",
            "comparison": "early versus delayed therapy",
            "model": "multivariable Cox model",
            "timepoint": "5-year follow-up",
            "unit": "hazard ratio",
            "denominator": "eligible hospitalized adults",
        }
        self.values = {
            "estimate": 1.42,
            "ci_low": 1.10,
            "ci_high": 1.83,
            "p_value": 0.007,
            "followup_years": 5,
        }
        self.export = {"primary": {"context": self.context, "values": self.values}}
        self.catalog = {
            "primary": {
                "source": "03_analysis/results/primary.json",
                "pointer": "/primary",
                "context": dict(self.context),
            }
        }
        self.alternatives = {
            "population": "pediatric outpatients",
            "comparison": "early therapy versus placebo",
            "model": "unadjusted Cox model",
            "timepoint": "1-year follow-up",
        }
        for key, alt in self.alternatives.items():
            alt_ctx = {**self.context, key: alt}
            alt_vals = dict(self.values)
            if key == "timepoint":
                alt_vals["followup_years"] = 1
            self.export[key] = {"context": alt_ctx, "values": alt_vals}
            self.catalog[key] = {
                "source": "03_analysis/results/primary.json",
                "pointer": f"/{key}",
                "context": alt_ctx,
            }
        atomic_json(self.project / "03_analysis/results/primary.json", self.export)
        atomic_json(self.project / "01_protocol/study_facts.json", {"numeric_facts": self.catalog})
        self.sentence = (
            "Among hospitalized adults, the multivariable Cox model comparing early versus delayed therapy "
            "showed higher all-cause mortality over 5-year follow-up (hazard ratio 1.42; 95% CI, 1.10 to 1.83)."
        )

    def _make_claim(self, text: str, path: str | None = None, observations: dict | None = None) -> dict:
        fact = claims.facts(self.project)["primary"]
        obs = observations or {k: self.context[k] for k in claims.PROSE_CONTEXT_KEYS}
        return {
            "path": path or self.rel,
            "text": text,
            "fact_ids": ["primary"],
            "context_evidence": {
                "primary": {
                    "fact_fingerprint": fact["fingerprint"],
                    "claim_fingerprint": claims.fingerprint(text),
                    "observations": obs,
                }
            },
        }

    def test_discussion_unbound_and_mismatched_context_and_external_coexistence(self) -> None:
        _progress("P1-1 S16 Discussion own-study bindings + external source_claims")
        disc_path = self.project / self.rel
        disc_path.parent.mkdir(parents=True, exist_ok=True)
        disc_path.write_text("# Discussion\n\n" + self.sentence + "\n", encoding="utf-8")

        # Missing claim_bindings fails in 1.27.0, while 1.26.0 legacy pin preserves old behavior
        ctx = Ctx(self.pipe, self.state, self.project, self.pipe.stage("S16_discussion"), {"path": self.rel})
        res_missing = numbers_have_provenance(ctx)
        self.assertFalse(res_missing.ok, res_missing.detail)

        self.state.data["engine_pin"] = "1.26.0"
        self.state.save()
        res_legacy = numbers_have_provenance(ctx)
        self.assertTrue(res_legacy.ok, res_legacy.detail)
        self.state.data["engine_pin"] = "1.27.0"
        self.state.save()

        # Valid own-study Discussion binding passes
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {"schema_version": 1, "claims": [self._make_claim(self.sentence)]},
        )
        self.assertTrue(numbers_have_provenance(ctx).ok)

        # Wrong population / comparison / model / timepoint each fail even with identical digits
        for field, wrong in self.alternatives.items():
            with self.subTest(field=field):
                bad_sentence = self.sentence.replace(self.context[field], wrong)
                disc_path.write_text("# Discussion\n\n" + bad_sentence + "\n", encoding="utf-8")
                bad_claim = self._make_claim(bad_sentence)
                bad_claim["context_evidence"]["primary"]["observations"][field] = wrong
                atomic_json(
                    self.project / "07_manuscript/claim_bindings.json",
                    {"schema_version": 1, "claims": [bad_claim]},
                )
                errs = claims.validate_prose(self.project, self.rel, disc_path.read_text(encoding="utf-8"))
                self.assertTrue(errs, f"expected Discussion mismatch failure on {field}")

        # Wrong measure scale (HR -> risk ratio) fails in Discussion
        wrong_scale = self.sentence.replace("hazard ratio 1.42", "risk ratio 1.42")
        disc_path.write_text("# Discussion\n\n" + wrong_scale + "\n", encoding="utf-8")
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {"schema_version": 1, "claims": [self._make_claim(wrong_scale)]},
        )
        self.assertTrue(claims.validate_prose(self.project, self.rel, disc_path.read_text(encoding="utf-8")))

        # Same-section lead-in inheritance in Discussion + cited external prior-study number via source_claims
        lead_in = (
            "In our cohort of hospitalized adults evaluated with the multivariable Cox model "
            "for early versus delayed therapy, we observed elevated risk."
        )
        short_own = "All-cause mortality over 5-year follow-up remained elevated with a hazard ratio of 1.42 (95% CI, 1.10 to 1.83)."
        ext_sentence = "Prior multicenter registries reported a 28.4% 5-year event rate in untreated cohorts [@smith2024]."
        fulltext_rel = "06_refs/fulltext/smith2024.html"
        fulltext_file = self.project / fulltext_rel
        fulltext_file.parent.mkdir(parents=True, exist_ok=True)
        excerpt = "Across untreated multicenter cohorts, the 5-year event rate was 28.4% during follow-up."
        fulltext_file.write_text("<html><p>" + excerpt + "</p></html>", encoding="utf-8")
        from wfcore.packagefreeze import _sha256 as freeze_sha256
        ft_sha = freeze_sha256(fulltext_file)
        atomic_json(
            self.project / "06_refs/library.json",
            {"entries": [{"citekey": "smith2024"}]},
        )
        atomic_json(
            self.project / "06_refs/fulltext/retrieval_manifest.json",
            {"retrievals": [{"citekey": "smith2024", "fulltext": fulltext_rel, "sha256": ft_sha, "access": "oa"}]},
        )
        inherited_obs = {
            k: {"mode": "literal", "scope": "section", "quote": lead_in}
            for k in ("population", "comparison", "model")
        }
        inherited_obs["timepoint"] = "5-year follow-up"
        disc_body = f"# Discussion\n\n{lead_in} {short_own} {ext_sentence}\n"
        disc_path.write_text(disc_body, encoding="utf-8")
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {
                "schema_version": 1,
                "claims": [self._make_claim(short_own, observations=inherited_obs)],
                "source_claims": [
                    {
                        "path": self.rel,
                        "text": ext_sentence,
                        "citekey": "smith2024",
                        "fulltext": fulltext_rel,
                        "sha256": ft_sha,
                        "locator": "Results paragraph 2",
                        "excerpt": excerpt,
                        "support": "Direct external registry comparison in synthetic test.",
                    }
                ],
            },
        )
        with (
            mock.patch("wfcore.refproof.validate_local_proof", return_value=(True, [], {})),
            mock.patch("pubmed.identity.errors", return_value=[]),
        ):
            res_combined = numbers_have_provenance(ctx)
        self.assertTrue(res_combined.ok, res_combined.detail)

        # Assembled full_manuscript.md derives Discussion section bindings cleanly
        results_claim = self._make_claim(self.sentence, path="07_manuscript/results.md")
        disc_claim = self._make_claim(short_own, path="07_manuscript/discussion.md", observations=inherited_obs)
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {"schema_version": 1, "claims": [results_claim, disc_claim]},
        )
        assembled_md = (
            f"# Results\n\n{self.sentence}\n\n"
            f"# Discussion\n\n{lead_in} {short_own}\n"
        )
        derived_payload = claims.assembled_bindings(self.project, assembled_md)
        atomic_json(self.project / "07_manuscript/claim_bindings.json", derived_payload)
        full_sections = {
            tuple(row.get("section", ()))
            for row in derived_payload["claims"]
            if row.get("path") == "07_manuscript/full_manuscript.md"
        }
        self.assertIn(("Discussion",), full_sections)
        self.assertEqual(
            claims.validate_prose(self.project, "07_manuscript/full_manuscript.md", assembled_md),
            [],
        )


class ProseMeasureAndIntervalTests(unittest.TestCase):
    """P1-2: Controlled measure/unit matching, lowercase 'or' immunity, and non-95% CI checks."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="medpaper-measure-127-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.state = State(self.project).create("medpaper", "1.27.0", "S09_results")
        self.rel = "07_manuscript/results.md"
        self.base_ctx = {
            "outcome": "death or hospitalization",
            "population": "adults",
            "comparison": "exposed versus unexposed",
            "model": "adjusted model",
            "timepoint": "long-term follow-up",
            "unit": "hazard ratio",
            "denominator": "eligible adults",
        }
        self.values = {"estimate": 1.42, "ci_low": 1.10, "ci_high": 1.83}

    def _save_and_validate(self, text: str, context: dict | None = None, extra_obs: dict | None = None, body: str | None = None) -> list[str]:
        ctx = context or self.base_ctx
        atomic_json(self.project / "03_analysis/results/primary.json", {"primary": {"context": ctx, "values": self.values}})
        atomic_json(
            self.project / "01_protocol/study_facts.json",
            {"numeric_facts": {"primary": {"source": "03_analysis/results/primary.json", "pointer": "/primary", "context": ctx}}},
        )
        fact = claims.facts(self.project)["primary"]
        obs = {k: ctx[k] for k in claims.PROSE_CONTEXT_KEYS}
        if extra_obs:
            obs.update(extra_obs)
        row = {
            "path": self.rel,
            "text": text,
            "fact_ids": ["primary"],
            "context_evidence": {
                "primary": {
                    "fact_fingerprint": fact["fingerprint"],
                    "claim_fingerprint": claims.fingerprint(text),
                    "observations": obs,
                }
            },
        }
        atomic_json(self.project / "07_manuscript/claim_bindings.json", {"schema_version": 1, "claims": [row]})
        return claims.validate_prose(self.project, self.rel, body or text)

    def test_measure_scale_synonyms_lowercase_or_and_interval_levels(self) -> None:
        _progress("P1-2 S09 prose measure/unit synonyms, lowercase 'or', and interval_level")
        # Lowercase English 'or' in 'death or hospitalization' + valid HR/aHR passes without false OR conflict
        valid_hr = (
            "Among adults, the adjusted model for exposed versus unexposed showed higher death or hospitalization "
            "over long-term follow-up (HR 1.42; 95% CI, 1.10 to 1.83)."
        )
        self.assertEqual(self._save_and_validate(valid_hr), [])

        valid_ahr = valid_hr.replace("HR 1.42", "aHR 1.42")
        self.assertEqual(self._save_and_validate(valid_ahr), [])

        # Swapping HR -> risk ratio or uppercase OR is blocked
        bad_rr = valid_hr.replace("HR 1.42", "risk ratio 1.42")
        errs_rr = self._save_and_validate(bad_rr)
        self.assertTrue(any("effect scale" in e or "unit" in e for e in errs_rr), errs_rr)

        bad_or = valid_hr.replace("HR 1.42", "OR 1.42")
        errs_or = self._save_and_validate(bad_or)
        self.assertTrue(any("effect scale" in e or "unit" in e for e in errs_or), errs_or)

        # Same-section inherited unit passes when lead-in states 'hazard ratios'
        lead = "Adjusted model estimates for exposed versus unexposed among adults over long-term follow-up are reported as hazard ratios."
        clause = "Death or hospitalization was 1.42 (95% CI, 1.10 to 1.83)."
        inherited = {k: {"mode": "literal", "scope": "section", "quote": lead} for k in claims.PROSE_CONTEXT_KEYS}
        inherited["unit"] = {"mode": "literal", "scope": "section", "quote": lead}
        self.assertEqual(self._save_and_validate(clause, extra_obs=inherited, body=f"# Results\n\n{lead} {clause}\n"), [])

        # Count / N/A unit exemptions do not demand effect-scale terms
        count_ctx = {**self.base_ctx, "unit": "participants"}
        self.values = {"n": 412}
        count_clause = "Among adults, the adjusted model for exposed versus unexposed over long-term follow-up included 412 individuals with death or hospitalization."
        self.assertEqual(self._save_and_validate(count_clause, context=count_ctx), [])

        # Non-95% CI mismatch vs declared 90% interval_level
        self.values = {"estimate": 1.42, "ci_low": 1.10, "ci_high": 1.83}
        mismatch_90 = valid_hr.replace("95% CI", "90% CI")
        errs_ci = self._save_and_validate(mismatch_90)
        self.assertTrue(any("90%" in e for e in errs_ci), errs_ci)

        ctx_90 = {**self.base_ctx, "interval_level": 90}
        self.assertEqual(self._save_and_validate(mismatch_90, context=ctx_90), [])
        errs_ci_rev = self._save_and_validate(valid_hr, context=ctx_90)
        self.assertTrue(any("90%" in e for e in errs_ci_rev), errs_ci_rev)


class TableCellContextAndPValueTests(unittest.TestCase):
    """P1-3: S10 table header/row/group context verification and borderline P-value formatting."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="medpaper-table-127-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.state = State(self.project).create("medpaper", "1.27.0", "S10_tables")
        self.pipe = registry.load()
        load_all()
        self.rel = "04_tables/main/Table1.xlsx"

    def test_cross_group_scale_and_model_swaps_rejected_while_valid_table_passes(self) -> None:
        _progress("P1-3 S10 table row/column context verification + threeline.p_value precision")
        path = self.project / self.rel
        path.parent.mkdir(parents=True, exist_ok=True)

        # 1. Group B fact pasted into Group A column fails even when ONLY Group B fact is in study_facts.json
        ctx_b = {
            "outcome": "Hypertension",
            "population": "Group B",
            "comparison": "Descriptive baseline",
            "model": "Observed count",
            "timepoint": "Baseline",
            "unit": "Participants (%)",
            "denominator": "Group B participants",
            "percentage_basis": "Group B baseline cohort",
        }
        vals_b = {"n_event": 20, "n_total": 100, "pct": 20.0}
        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                path,
                sheet="Table 1",
                title="Table 1. Baseline characteristics.",
                header=["Characteristic", "Group A", "Group B"],
                rows=[["Cardiometabolic history", "", ""], ["Hypertension, n (%)", "20 (20.0)", "20 (20.0)"]],
                footnotes=["Data are n (%)."],
                group_rows=[0],
                indent_rows=[1],
            )
        atomic_json(self.project / "03_analysis/results/base.json", {"htn_b": {"context": ctx_b, "values": vals_b}})
        atomic_json(
            self.project / "01_protocol/study_facts.json",
            {"numeric_facts": {"htn_b": {"source": "03_analysis/results/base.json", "pointer": "/htn_b", "context": ctx_b}}},
        )
        prop_b = [{"fact_id": "htn_b", "numerator_key": "n_event", "denominator_key": "n_total", "reported": "20.0"}]
        bad_bindings = {
            "schema_version": 1,
            "claims": [
                {"path": self.rel, "sheet": "Table 1", "cell": "B4", "text": "20 (20.0)", "fact_ids": ["htn_b"], "label_cells": ["A4"], "proportions": prop_b},
                {"path": self.rel, "sheet": "Table 1", "cell": "C4", "text": "20 (20.0)", "fact_ids": ["htn_b"], "label_cells": ["A4"], "proportions": prop_b},
            ],
        }
        atomic_json(self.project / "07_manuscript/claim_bindings.json", bad_bindings)
        errs_group = claims.validate_tables(self.project, [path])
        self.assertTrue(any("B4" in e for e in errs_group), errs_group)

        # 2. Regression table: HR fact in Risk ratio column or Adjusted fact in Unadjusted column fails;
        #    accurate Unadjusted HR + Adjusted HR + standalone P value column passes!
        reg_path = self.project / "04_tables/main/Table2.xlsx"
        reg_rel = "04_tables/main/Table2.xlsx"
        ctx_unadj = {
            "outcome": "All-cause mortality",
            "population": "Eligible adults",
            "comparison": "Early vs delayed",
            "model": "Unadjusted Cox model",
            "timepoint": "5-year follow-up",
            "unit": "hazard ratio",
            "denominator": "Eligible adults",
        }
        ctx_adj = {**ctx_unadj, "model": "Adjusted Cox model"}
        vals_unadj = {"estimate": 1.55, "ci_low": 1.20, "ci_high": 2.00, "p_value": 0.001}
        vals_adj = {"estimate": 1.42, "ci_low": 1.10, "ci_high": 1.83, "p_value": 0.007}
        atomic_json(
            self.project / "03_analysis/results/reg.json",
            {"unadj": {"context": ctx_unadj, "values": vals_unadj}, "adj": {"context": ctx_adj, "values": vals_adj}},
        )
        atomic_json(
            self.project / "01_protocol/study_facts.json",
            {
                "numeric_facts": {
                    "unadj": {"source": "03_analysis/results/reg.json", "pointer": "/unadj", "context": ctx_unadj},
                    "adj": {"source": "03_analysis/results/reg.json", "pointer": "/adj", "context": ctx_adj},
                }
            },
        )
        # Wrong measure column header ("Risk ratio (95% CI)" for HR fact)
        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                reg_path,
                sheet="Table 2",
                title="Table 2. Primary outcome regression.",
                header=["Outcome", "Unadjusted RR (95% CI)", "Adjusted HR (95% CI)", "P value"],
                rows=[["All-cause mortality", "1.55 (1.20-2.00)", "1.42 (1.10-1.83)", "0.007"]],
                footnotes=["Abbreviations: HR, hazard ratio; CI, confidence interval."],
            )
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {
                "schema_version": 1,
                "claims": [
                    {"path": reg_rel, "sheet": "Table 2", "cell": "B3", "text": "1.55 (1.20-2.00)", "fact_ids": ["unadj"], "label_cells": ["A3"]},
                    {"path": reg_rel, "sheet": "Table 2", "cell": "C3", "text": "1.42 (1.10-1.83)", "fact_ids": ["adj"], "label_cells": ["A3"]},
                    {"path": reg_rel, "sheet": "Table 2", "cell": "D3", "text": "0.007", "fact_ids": ["adj"], "label_cells": ["A3"]},
                ],
            },
        )
        errs_scale = claims.validate_tables(self.project, [reg_path])
        self.assertTrue(any("B3" in e and "measure" in e for e in errs_scale), errs_scale)

        # Fix header to Unadjusted HR, then swap adjusted fact into Unadjusted column -> fails
        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                reg_path,
                sheet="Table 2",
                title="Table 2. Primary outcome regression.",
                header=["Outcome", "Unadjusted HR (95% CI)", "Adjusted HR (95% CI)", "P value"],
                rows=[["All-cause mortality", "1.42 (1.10-1.83)", "1.42 (1.10-1.83)", "0.007"]],
                footnotes=["Abbreviations: HR, hazard ratio; CI, confidence interval."],
            )
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {
                "schema_version": 1,
                "claims": [
                    {"path": reg_rel, "sheet": "Table 2", "cell": "B3", "text": "1.42 (1.10-1.83)", "fact_ids": ["adj"], "label_cells": ["A3"]},
                    {"path": reg_rel, "sheet": "Table 2", "cell": "C3", "text": "1.42 (1.10-1.83)", "fact_ids": ["adj"], "label_cells": ["A3"]},
                    {"path": reg_rel, "sheet": "Table 2", "cell": "D3", "text": "0.007", "fact_ids": ["adj"], "label_cells": ["A3"]},
                ],
            },
        )
        errs_adj = claims.validate_tables(self.project, [reg_path])
        self.assertTrue(any("B3" in e for e in errs_adj), errs_adj)

        # Correct Unadjusted + Adjusted + standalone P value column passes cleanly
        with contextlib.redirect_stdout(io.StringIO()):
            write_table(
                reg_path,
                sheet="Table 2",
                title="Table 2. Primary outcome regression.",
                header=["Outcome", "Unadjusted HR (95% CI)", "Adjusted HR (95% CI)", "P value"],
                rows=[["All-cause mortality", "1.55 (1.20-2.00)", "1.42 (1.10-1.83)", "0.007"]],
                footnotes=["Abbreviations: HR, hazard ratio; CI, confidence interval."],
            )
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {
                "schema_version": 1,
                "claims": [
                    {"path": reg_rel, "sheet": "Table 2", "cell": "B3", "text": "1.55 (1.20-2.00)", "fact_ids": ["unadj"], "label_cells": ["A3"]},
                    {"path": reg_rel, "sheet": "Table 2", "cell": "C3", "text": "1.42 (1.10-1.83)", "fact_ids": ["adj"], "label_cells": ["A3"]},
                    {"path": reg_rel, "sheet": "Table 2", "cell": "D3", "text": "0.007", "fact_ids": ["adj"], "label_cells": ["A3"]},
                ],
            },
        )
        self.assertEqual(claims.validate_tables(self.project, [reg_path]), [])

        # 3. threeline.p_value backward compatibility + borderline_three_decimals + fixed decimals
        self.assertEqual(p_value(0.049), "0.05")
        self.assertEqual(p_value(0.0004), "<0.001")
        self.assertEqual(p_value(0.049, borderline_three_decimals=True), "0.049")
        self.assertEqual(p_value(0.050, borderline_three_decimals=True), "0.050")
        self.assertEqual(p_value(0.24, borderline_three_decimals=True), "0.24")
        self.assertEqual(p_value(0.24, decimals=3), "0.240")


class FigureAnnotationProvenanceTests(unittest.TestCase):
    """P1-4: S11 explicit statistical text annotations on rendered figures."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="medpaper-fig-127-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.state = State(self.project).create("medpaper", "1.27.0", "S11_figures")
        self.pipe = registry.load()
        load_all()
        self.context = {
            "outcome": "all-cause mortality",
            "population": "adults",
            "comparison": "early vs delayed",
            "model": "adjusted Cox model",
            "timepoint": "5-year follow-up",
            "unit": "hazard ratio",
            "denominator": "eligible adults",
        }
        self.values = {"estimate": 1.42, "ci_low": 1.10, "ci_high": 1.83, "p_value": 0.007}
        atomic_json(
            self.project / "03_analysis/results/primary.json",
            {"primary": {"context": self.context, "values": self.values}},
        )
        atomic_json(
            self.project / "01_protocol/study_facts.json",
            {
                "numeric_facts": {
                    "primary": {
                        "source": "03_analysis/results/primary.json",
                        "pointer": "/primary",
                        "context": self.context,
                    }
                }
            },
        )
        atomic_json(
            self.project / "01_protocol/artifact_plan.json",
            {
                "main_tables": [],
                "supp_tables": [],
                "main_figures": [
                    {
                        "id": "Figure 1",
                        "archetype": "other",
                        "width": "single",
                        "renderer": "Python",
                        "renderer_reason": "Synthetic offline regression test fixture for figure annotation provenance.",
                        "file": "05_figures/out/Figure1.png",
                        "pdf": "05_figures/out/Figure1.pdf",
                        "source_results": ["03_analysis/results/primary.json"],
                    }
                ],
                "supp_figures": [],
            },
        )

    def _render_test_figure(self, annotation_text: str) -> Path:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from figures import style

        style.apply_style()
        fig, [(_sf, ax)] = style.figure(width="single")
        ax.plot([0, 1, 2, 3, 4, 5], [1.0, 0.92, 0.85, 0.79, 0.74, 0.70], label="Early therapy")
        ax.plot([0, 1, 2, 3, 4, 5], [1.0, 0.88, 0.76, 0.68, 0.61, 0.55], label="Delayed therapy")
        ax.set_xlabel("Follow-up (years)")
        ax.set_ylabel("Survival probability")
        ax.text(0.3, 0.60, annotation_text, fontsize=7.5)
        ax.legend(loc="upper right")
        out_base = self.project / "05_figures/out/Figure1"
        with contextlib.redirect_stdout(io.StringIO()):
            style.save(fig, out_base, width="single", archetype="other")
        plt.close(fig)
        return out_base.with_suffix(".png")

    def _run_qc(self) -> subprocess.CompletedProcess:
        env = dict(os.environ, MEDPAPER_PROJECT=str(self.project))
        return subprocess.run(
            [sys.executable, str(ROOT / "tools/figures/qc.py"), "--figure", "Figure 1"],
            capture_output=True,
            text=True,
            env=env,
            encoding="utf-8",
            errors="replace",
        )

    def test_figure_annotation_missing_tampered_valid_and_hash_drift(self) -> None:
        _progress("P1-4 S11 figure statistical annotation provenance + QC hash lock")
        annot = "HR 1.42 (95% CI, 1.10 to 1.83); P = 0.007"
        self._render_test_figure(annot)

        # 1. Unregistered explicit statistical annotation fails QC and S11 numbers_have_provenance
        proc_missing = self._run_qc()
        self.assertNotEqual(proc_missing.returncode, 0, proc_missing.stdout + proc_missing.stderr)
        gate_ctx = Ctx(self.pipe, self.state, self.project, self.pipe.stage("S11_figures"), {"source": "figures"})
        self.assertFalse(numbers_have_provenance(gate_ctx).ok)

        # 2. Scale mismatch on figure ("OR 1.42..." against hazard ratio source) fails
        self._render_test_figure("OR 1.42 (95% CI, 1.10 to 1.83); P = 0.007")
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {
                "schema_version": 1,
                "claims": [],
                "figure_annotations": [
                    {
                        "figure_id": "Figure 1",
                        "text": "OR 1.42 (95% CI, 1.10 to 1.83); P = 0.007",
                        "fact_id": "primary",
                        "source": "03_analysis/results/primary.json",
                        "pointer": "/primary",
                        "values": [
                            {"field": "estimate", "reported": "1.42", "digits": 2},
                            {"field": "ci_low", "reported": "1.10", "digits": 2},
                            {"field": "ci_high", "reported": "1.83", "digits": 2},
                            {"field": "p_value", "reported": "0.007", "digits": 3, "op": "="},
                        ],
                    }
                ],
            },
        )
        self.assertFalse(numbers_have_provenance(gate_ctx).ok)

        # 3. Unbound extra number smuggled into annotation fails
        smuggled = "HR 1.42 (95% CI, 1.10 to 1.83); P = 0.007; n = 999"
        self._render_test_figure(smuggled)
        atomic_json(
            self.project / "07_manuscript/claim_bindings.json",
            {
                "schema_version": 1,
                "claims": [],
                "figure_annotations": [
                    {
                        "figure_id": "Figure 1",
                        "text": smuggled,
                        "fact_id": "primary",
                        "source": "03_analysis/results/primary.json",
                        "pointer": "/primary",
                        "values": [
                            {"field": "estimate", "reported": "1.42", "digits": 2},
                            {"field": "ci_low", "reported": "1.10", "digits": 2},
                            {"field": "ci_high", "reported": "1.83", "digits": 2},
                            {"field": "p_value", "reported": "0.007", "digits": 3, "op": "="},
                        ],
                    }
                ],
            },
        )
        self.assertFalse(numbers_have_provenance(gate_ctx).ok)

        # 4. Exact item-by-item binding passes qc.py, numbers_have_provenance(source="figures"), and figures_qc_pass
        self._render_test_figure(annot)
        valid_bindings = {
            "schema_version": 1,
            "claims": [],
            "figure_annotations": [
                {
                    "figure_id": "Figure 1",
                    "text": annot,
                    "fact_id": "primary",
                    "source": "03_analysis/results/primary.json",
                    "pointer": "/primary",
                    "values": [
                        {"field": "estimate", "reported": "1.42", "digits": 2},
                        {"field": "ci_low", "reported": "1.10", "digits": 2},
                        {"field": "ci_high", "reported": "1.83", "digits": 2},
                        {"field": "p_value", "reported": "0.007", "digits": 3, "op": "="},
                    ],
                }
            ],
        }
        atomic_json(self.project / "07_manuscript/claim_bindings.json", valid_bindings)
        proc_ok = self._run_qc()
        self.assertEqual(proc_ok.returncode, 0, proc_ok.stdout + proc_ok.stderr)
        self.assertTrue(numbers_have_provenance(gate_ctx).ok)

        qc_path = self.project / "05_figures/qc/qc_report.json"
        qc_data = json.loads(qc_path.read_text(encoding="utf-8"))
        qc_data["figures"][0]["visual_reviewed"] = True
        qc_path.write_text(json.dumps(qc_data, indent=2), encoding="utf-8")

        fig_qc_ctx = Ctx(self.pipe, self.state, self.project, self.pipe.stage("S11_figures"), {})
        self.assertTrue(figures_qc_pass(fig_qc_ctx).ok)

        # 5. Post-QC mutation of underlying result is blocked both on value mismatch and on stale QC fingerprint
        tampered_values = {**self.values, "estimate": 1.88}
        atomic_json(
            self.project / "03_analysis/results/primary.json",
            {"primary": {"context": self.context, "values": tampered_values}},
        )
        drift_res = figures_qc_pass(fig_qc_ctx)
        self.assertFalse(drift_res.ok)
        self.assertIn("does not match source 1.88", drift_res.detail)

        # Even if rounded 2-decimal display still equals 1.42, changing the underlying precision without rerunning qc.py invalidates figure_annotations_sha256
        subtle_values = {**self.values, "estimate": 1.421}
        atomic_json(
            self.project / "03_analysis/results/primary.json",
            {"primary": {"context": self.context, "values": subtle_values}},
        )
        hash_drift_res = figures_qc_pass(fig_qc_ctx)
        self.assertFalse(hash_drift_res.ok)
        self.assertIn("figure annotation binding changed after QC", hash_drift_res.detail)


class S25ForceGuardTests(unittest.TestCase):
    """P2-1: S25_submission_audit cannot bypass decision_recorded or audit gates via --force."""

    def setUp(self) -> None:
        self.project = Path(tempfile.mkdtemp(prefix="medpaper-s25-127-"))
        def _cleanup() -> None:
            import stat as _stat
            shutil.rmtree(
                self.project,
                onexc=lambda fn, p, _: (Path(p).chmod(_stat.S_IWRITE | _stat.S_IREAD), fn(p)),
            )
        self.addCleanup(_cleanup)
        self.state = State(self.project).create("medpaper", "1.27.0", "S25_submission_audit")
        self.pipe = registry.load()
        load_all()
        self.stage = self.pipe.stage("S25_submission_audit")

        # Prepare authentic package freeze + evidence manifest
        bundle_dir = self.project / "08_submission/bundle"
        bundle_dir.mkdir(parents=True, exist_ok=True)
        upload_file = bundle_dir / "manuscript.docx"
        upload_file.write_bytes(b"synthetic-docx-payload")
        atomic_json(
            bundle_dir / "manifest.json",
            {"items": [{"role": "manuscript", "file": "08_submission/bundle/manuscript.docx", "upload": True}]},
        )
        from wfcore.packagefreeze import sync_evidence, write_freeze

        freeze_path = write_freeze(self.project)
        self.freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
        self.evidence = sync_evidence(self.project)
        self.audit_path = self.project / "08_submission/independent_submission_audit.md"

    def _write_audit(self, verdict_body: str, freeze_id: str | None = None) -> None:
        fid = freeze_id if freeze_id is not None else self.freeze["freeze_id"]
        obs_text = (
            "Synthetic S25 verification fixture: clinical cohort population, primary endpoint scale, "
            "three-line table denominators, and figure uncertainty intervals were checked against frozen uploads."
        )
        self.audit_path.write_text(
            f"# Verdict\n\n{verdict_body}\n\nFreeze ID: {fid}\n"
            f"Audit context ID: {self.evidence['audit_context_id']}\n\n"
            f"# Reader comprehension\n\n{obs_text}\n\n"
            f"# Medical presentation\n\n{obs_text}\n\n"
            f"# Editorial screening and low-level errors\n\n{obs_text}\n\n"
            "# Guideline compliance\n\nPass.\n\n"
            "# Required files and omissions\n\nNone.\n\n"
            "# Cross-file consistency\n\nPass.\n\n"
            "# Formatting and technical checks\n\nPass.\n\n"
            "# Issues requiring correction\n\nNone.\n\n"
            "# Final recommendation\n\nReady.\n",
            encoding="utf-8",
        )

    def _run_s25_advance(self, *, force: bool) -> int:
        # Evaluate the real S25 audit, freeze, final_copy and decision gates while stubbing unrelated live/DOCX gates
        audit_res = submission_audit_matches_freeze(
            Ctx(self.pipe, self.state, self.project, self.stage, {"path": "08_submission/independent_submission_audit.md"})
        )
        dec_res = decision_recorded(
            Ctx(
                self.pipe,
                self.state,
                self.project,
                self.stage,
                {"name": "submission_package_independent_audit", "allowed": ["PASS", "PASS_AUTHOR_FINAL_COPY"]},
            )
        )
        final_copy_fn = get("final_copy_verified")
        final_res = final_copy_fn(Ctx(self.pipe, self.state, self.project, self.stage, {}))
        results = [Result(True, "outputs_exist", "ok"), audit_res, dec_res, final_res]

        args = argparse.Namespace(
            force=force,
            reason="Synthetic test attempting CLI --force override at S25.",
            note="S25 advance test",
        )
        with (
            mock.patch("wfcore.cli._load", return_value=(self.pipe, self.state, self.project)),
            mock.patch("wfcore.gates.run_stage", return_value=results),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            return cli.cmd_advance(args)

    def test_s25_blocks_force_on_bad_verdict_wrong_freeze_or_missing_decision(self) -> None:
        _progress("P2-1 S25 --force cannot bypass Verdict, freeze_id, or decision_recorded")
        rationale = "Independent read-only audit verified frozen package against official journal guidelines."

        # 1. REVISE / BLOCKED / missing Verdict / wrong freeze_id all reject --force even if state decision says PASS
        self.state.record_decision("submission_package_independent_audit", "PASS", rationale)
        for bad_verdict, bad_fid in (
            ("REVISE", None),
            ("BLOCKED", None),
            ("Pending further checks", None),
            ("PASS", "0" * 64),
        ):
            with self.subTest(verdict=bad_verdict, fid=bad_fid):
                self._write_audit(bad_verdict, freeze_id=bad_fid)
                rc = self._run_s25_advance(force=True)
                self.assertEqual(rc, 2)
                self.assertFalse(self.state.is_done("S25_submission_audit"))

        # 2. Valid PASS audit + valid freeze_id, BUT missing or invalid state decision -> --force MUST still fail!
        self._write_audit("PASS")
        self.state.data["decisions"].pop("submission_package_independent_audit", None)
        self.state.save()
        self.assertEqual(self._run_s25_advance(force=True), 2)
        self.assertFalse(self.state.is_done("S25_submission_audit"))

        self.state.record_decision("submission_package_independent_audit", "REVISE", rationale)
        self.assertEqual(self._run_s25_advance(force=True), 2)
        self.assertFalse(self.state.is_done("S25_submission_audit"))

        # 3. Valid PASS audit + valid recorded PASS decision -> normal advance succeeds without --force
        self.state.record_decision("submission_package_independent_audit", "PASS", rationale)
        self.assertEqual(self._run_s25_advance(force=False), 0)
        self.assertTrue(self.state.is_done("S25_submission_audit"))


class CrossDriveLauncherAndNoPandocTests(unittest.TestCase):
    """P2-2: External clone template resolution / safe upgrade and pandoc-free selftest skip."""

    def test_cross_drive_launcher_init_upgrade_and_incomplete_template_guard(self) -> None:
        _progress("P2-2 Cross-drive medpaper_launcher init/upgrade + incomplete source guard")
        import medpaper_launcher as launcher

        with tempfile.TemporaryDirectory(prefix="medpaper-ext-clone-") as raw_tmp:
            base = Path(raw_tmp)
            clone_src = base / "cloned_template"
            clone_src.mkdir()
            # Build a clean template clone on the system temp drive (outside F:\workspace\medpapaer\gemini)
            launcher._stage_template_to_dir("dir", ROOT, clone_src, include_project_skeleton=True)

            # 1. Incomplete template source is rejected without half-populating target
            broken_src = base / "broken_template"
            (broken_src / "tools").mkdir(parents=True)
            empty_target = base / "aborted_workspace"
            empty_target.mkdir()
            proc_bad = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/medpaper_launcher.py"),
                    "--workspace",
                    str(empty_target),
                    "--template-source",
                    str(broken_src),
                    "--no-bootstrap",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertNotEqual(proc_bad.returncode, 0)
            self.assertFalse((empty_target / "tools").exists())

            # 2. New workspace creation via MEDPAPER_MASTER_TEMPLATE on temp drive
            new_ws = base / "new_study"
            new_ws.mkdir()
            clean_env = {
                k: v for k, v in os.environ.items()
                if k not in {"MEDPAPER_PROJECT", "MEDPAPER_ROOT", "MEDPAPER_SELFTEST_ROOT"}
            }
            clean_env["MEDPAPER_MASTER_TEMPLATE"] = str(clone_src)
            proc_new = subprocess.run(
                [
                    sys.executable,
                    str(clone_src / "tools/medpaper_launcher.py"),
                    "--workspace",
                    str(new_ws),
                    "--no-bootstrap",
                ],
                capture_output=True,
                text=True,
                env=clean_env,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(proc_new.returncode, 0, proc_new.stdout + proc_new.stderr)
            self.assertTrue((new_ws / "pipeline/pipeline.toml").is_file())
            self.assertTrue((new_ws / "tools/wf.py").is_file())
            # Initialize state and check wf status on the newly provisioned workspace
            State(new_ws / "project").create("medpaper", "1.27.0", "S01_intake")
            proc_status = subprocess.run(
                [sys.executable, str(new_ws / "tools/wf.py"), "status"],
                cwd=str(new_ws),
                capture_output=True,
                text=True,
                env=clean_env,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(proc_status.returncode, 0, proc_status.stdout + proc_status.stderr)
            self.assertIn("S01_intake", proc_status.stdout)

            # 3. Safe --upgrade from an older 1.25.0 workspace updates engine while preserving project/, .venv/, and engine_pin
            current_ver = str(registry.load().meta["version"])
            old_toml = new_ws / "pipeline/pipeline.toml"
            old_toml.write_text(
                old_toml.read_text(encoding="utf-8").replace(f'version = "{current_ver}"', 'version = "1.25.0"', 1),
                encoding="utf-8",
            )
            (new_ws / ".medpaper-engine.json").unlink(missing_ok=True)
            idea_file = new_ws / "project/00_input/idea.md"
            idea_file.parent.mkdir(parents=True, exist_ok=True)
            idea_file.write_text("# My clinical study idea\nPreserve me across upgrades.\n", encoding="utf-8")
            venv_marker = new_ws / ".venv/keep_marker.txt"
            venv_marker.parent.mkdir(parents=True, exist_ok=True)
            venv_marker.write_text("existing-venv", encoding="utf-8")
            st = State(new_ws / "project").load()
            st.data["engine_pin"] = "1.25.0"
            st.save()

            proc_upg = subprocess.run(
                [
                    sys.executable,
                    str(clone_src / "tools/medpaper_launcher.py"),
                    "--workspace",
                    str(new_ws),
                    "--template-source",
                    str(clone_src),
                    "--upgrade",
                    "--no-bootstrap",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            self.assertEqual(proc_upg.returncode, 0, proc_upg.stdout + proc_upg.stderr)
            self.assertIn(f'version = "{current_ver}"', old_toml.read_text(encoding="utf-8"))
            self.assertIn("Preserve me across upgrades.", idea_file.read_text(encoding="utf-8"))
            self.assertEqual(venv_marker.read_text(encoding="utf-8"), "existing-venv")
            self.assertEqual(State(new_ws / "project").load().data["engine_pin"], "1.25.0")

    def test_selftest_manuscript_docx_skips_cleanly_without_pandoc(self) -> None:
        _progress("P2-2 selftest run_manuscript_docx clean SKIP when pandoc is unavailable")
        snippet = (
            "import os, shutil, stat, tempfile; from pathlib import Path; import selftest; "
            "tmp = Path(tempfile.mkdtemp(prefix='medpaper-nopandoc-')); "
            "proj = tmp / 'project'; "
            "os.environ['MEDPAPER_PROJECT'] = str(proj); "
            "os.environ['MEDPAPER_ROOT'] = str(selftest.ROOT); "
            "os.environ['MEDPAPER_SELFTEST_ROOT'] = str(tmp); "
            "selftest.build_fixture(proj); "
            "from wfcore.state import State; "
            "st = State(proj, '.wf'); st.create('medpaper', '1.27.0', 'S17_assemble'); st.data['engine_pin'] = '1.25.0'; st.save(); "
            "selftest.results.clear(); "
            "selftest.run_manuscript_docx(proj); "
            "shutil.rmtree(tmp, onexc=lambda fn, p, _: (Path(p).chmod(stat.S_IWRITE | stat.S_IREAD), fn(p))); "
            "failed = [r for r in selftest.results if r[1] == selftest.FAIL]; "
            "skipped = [r for r in selftest.results if r[1] == selftest.SKIP]; "
            "assert not failed, failed; "
            "assert skipped, 'expected SKIP record when pandoc is absent'; "
            "print('SKIP_VERIFIED:', skipped[0][0])"
        )
        env = dict(os.environ, MEDPAPER_TEST_NO_PANDOC="1")
        proc = subprocess.run(
            [sys.executable, "-c", snippet],
            cwd=str(ROOT / "tools"),
            capture_output=True,
            text=True,
            env=env,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("SKIP_VERIFIED:", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
