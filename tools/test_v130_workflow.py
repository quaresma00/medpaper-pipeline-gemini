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
        _progress("1/6 Checking 26-stage sequence (S11b before S09) and compact card limits...")
        ids = [s.id for s in self.pipe.stages]
        self.assertEqual(len(ids), 26)
        self.assertEqual(ids.index("S11b_prewrite_review"), ids.index("S11_figures") + 1)
        self.assertEqual(ids.index("S09_results"), ids.index("S11b_prewrite_review") + 1)
        for name in ("S07_artifacts", "S20_journal", "S23_package", "S25_submission_audit"):
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
            "Adjusted estimates quantified independent mortality risk across predefined clinical strata.\n"
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
        _progress("5/6 Checking >=3 comparator display sufficiency and citation floors...")
        bench_gate = get_check("benchmark_display_sufficiency")
        comp = lambda k, mf: {"citekey": k, "observations": {"main_figures": mf, "figure_types": ["flow", "forest", "km", "roc"], "references": 42}}
        (self.project / "01_protocol/artifact_benchmark.json").write_text(json.dumps({
            "comparators": [comp("a", 5), comp("b", 6)],
            "adaptation": {"displays": {"figure_count_rationale": "Matched to peer SCIE articles with four core clinical visuals."}},
        }), encoding="utf-8")
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_figures": [{"id": f"Figure {i}"} for i in range(1, 3)],
        }), encoding="utf-8")
        self.assertFalse(bench_gate(self._ctx("S07_artifacts", {"since": "1.30.0"})).ok)

        (self.project / "01_protocol/artifact_benchmark.json").write_text(json.dumps({
            "comparators": [comp("a", 5), comp("b", 6), comp("c", 5)],
            "adaptation": {"displays": {"figure_count_rationale": "Three SCIE comparators use 5-6 figures; our 4-figure plan covers flow, primary HR, forest, and ROC."}},
        }), encoding="utf-8")
        (self.project / "01_protocol/artifact_plan.json").write_text(json.dumps({
            "main_figures": [{"id": f"Figure {i}"} for i in range(1, 5)],
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
