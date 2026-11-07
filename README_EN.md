# medpaper-pipeline-gemini — Gated Medical Research Paper Workflow (v1.27.0)

[中文说明](README.md) | [English Documentation](README_EN.md)

A 25-stage, fail-closed medical and clinical research paper workflow optimized for **Google Antigravity / Gemini** (`uv run python` + `pwsh`), running the `v1.27.0` verification architecture. It drives a clinical research idea from feasibility and full-census data acquisition through R-first statistical graphics, context- and scale-bound IMRAD writing, version-bound read-only subagent review, frozen scientific master isolation, and journal-compliant native Word submission bundles.

## Architectural Highlights (`v1.27.0`)

| Risk / Failure Mode | Architectural Enforcement |
|---|---|
| Context rot & prompt bloat | Disk-backed state (`project/.wf/state.json`), zero-network compact `wf status`, bounded `wf handoff`, split `--details` cards, and on-demand `reference/*.md` topic routing. |
| Convenience data truncation | `tools/data_manifest.py` + `dataproof.py` verify source totals, terminal pagination, join-unit counts, file/script SHA-256, and reject `LIMIT`, `TOP`, `head()`, `sample()`, and `nrows=`. Large local datasets register read-only in place via `tools/data_sources.py`. |
| Hallucinated or spoofed references | `tools/pubmed/verify.py` binds fresh EFetch XML SHA-256 and parsed fingerprints to `library.json`, re-verified live at S13 and S25 (with 24h hash-bound cache in between). Legal full texts require `fulltext.py register` identity checks. |
| Disembodied or misattributed numbers | `claim_bindings.json` + `proportions.py` bind every own-study number across `Results`, `Abstract`, `Discussion`, table cells, and explicit figure annotations (`figure_annotations`) to executed `03_analysis/results/*.json` (population, endpoint, contrast, controlled `HR`/`RR`/`OR` scale, interval level, table header/row context, join unit, and `n/N (%)` denominator) and prior-study numbers to registered source passages. |
| Results drafted before displays settle | **Table/figure-first execution order**: `S08_methods` -> `S10_tables` -> `S11_figures` -> `S09_results` -> `S12_reconcile`, gated by `display_review.json`. |
| Amateur plots & universal quotas | Comparator full-text PDF benchmarking at S07 (`pypdf`) replaces rigid word/reference/figure quotas. S11 defaults to managed R clinical recipes (`render_r.py`: flowcharts, aligned-column forest plots, KM, ROC, calibration, dose-response, DCA, balance) with `renv` and per-figure job locks. |
| Destructive rewrites & journal drift | Version-bound read-only subagent reviews (`invoke_subagent` + `review_round.py`, no review ZIPs), explicit `我确认这一版` sign-off, in-place scoped `rework.py` batches + `wf rebuild`, S19 `scientific_master_freeze.json`, and isolated `08_submission/integration/` (`tools/journal.py`). |
| Corrupted Word formatting | `build_docx.py` + `wordtables.py` produce native portrait/landscape three-line Word tables and strip `outlineLvl`, `keepNext`, `keepLines`, `pageBreakBefore`, borders, hyperlinks, and non-black runs across all Word XML parts. |

## Quick Start (Windows `pwsh`)

```powershell
# 1. Provision .venv (Python 3.13), initialize project/, run doctor and offline self-test
uv run --python 3.13 python bootstrap.py

# Optional environment variables (never commit credentials to repository files)
$env:NCBI_API_KEY = "<your NCBI API key>"
$env:NCBI_API_EMAIL = "you@example.org"

# 2. Standard stage execution loop
uv run python tools/wf.py status
uv run python tools/wf.py card
# ... complete active stage work ...
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "concise summary of outputs, decisions, and open items"
```

## Key CLI Entrypoints

| Command | Purpose |
|---|---|
| `uv run python tools/wf.py status [--full]` | Fast local summary (add `--full` to run active gates) |
| `uv run python tools/wf.py handoff` | Bounded local context recovery after compaction |
| `uv run python tools/wf.py card [STAGE] [--details]` | Show active/named stage card (or detailed procedure) |
| `uv run python tools/wf.py check [STAGE]` | Evaluate stage gates without advancing |
| `uv run python tools/wf.py rebuild [--dry-run]` | Dependency-aware incremental rebuild of affected outputs |
| `uv run python tools/wf.py migrate [--dry-run]` | Inspect or adopt current engine gates on pinned workspaces |
| `uv run python tools/wf.py doctor` | Check wiring, `.venv` modules, `Rscript`, `pandoc`, and `git` |
| `uv run python tools/review_round.py ...` | Manage hash-bound independent subagent review rounds |
| `uv run python tools/rework.py ...` | Manage persisted in-place scoped revision batches |
| `uv run python tools/journal.py ...` | Bind target journal/ISSN/article-type context and guides |
| `uv run python tools/selftest.py` | Run the full offline regression suite (23+ sub-suites) |

## The 25 Stages (Execution Order)

1. `S01_intake` — Normalize research idea & clinical question
2. `S02_feasibility` — Literature saturation check & Go/No-Go #1
3. `S03_protocol` — Protocol v1, design-specific contract & full-census acquisition plan
4. `S04_data` — Full-census data acquisition (or in-place source registration) & hash manifest
5. `S05_analysis` — Method scan, full-precision statistical execution & source spot-check
6. `S06_protocol_final` — Freeze `analysis_contract.json`, `study_facts.json`, `writing_readiness.json` & Go/No-Go #2
7. `S07_artifacts` — Comparator full-text PDF benchmark, display prototypes & reader contracts
8. `S08_methods` — Reproducible main Methods & optional prose-only `supplementary_methods.md`
9. `S10_tables` — Three-line main & supplementary XLSX workbooks + visual QA (`display_review.json`)
10. `S11_figures` — R-first publication figures (PDF + PNG), deterministic QC & visual QA
11. `S09_results` — Context- and denominator-bound Results narrative aligned to verified displays
12. `S12_reconcile` — Cross-check Methods, Results, tables, figures, and numeric claim bindings
13. `S13_reflib` — Fresh EFetch verified reference library (`library.json`, `verified.json`, `.bib`, `.ris`)
14. `S14_introduction` — Focused clinical Introduction with verified citations & source claims
15. `S15_deepread` — Legal OA/authorized full-text registration & structured deep-read notes
16. `S16_discussion` — Evidence-bounded Discussion engaging deep-read literature
17. `S17_assemble` — Automated accurate title, abstract, keywords, centralized abbreviations & `full_manuscript.md`
18. `S18_independent_review` — Independent read-only subagent publication-readiness review (`M001`)
19. `S19_human_review` — Scoped executor fixes, single consolidated report, explicit `我确认这一版` & `scientific_master_freeze.json`
20. `S20_journal` — Realistic SCIE journal selection, official guide capture & isolated `08_submission/integration/`
21. `S21_authors` — Deferred author/affiliation/declaration intake & synced reference counts
22. `S22_polish` — Fact-preserving journal style adaptation & contextual language review
23. `S23_package` — Native Word three-line tables, pure-black flat-heading DOCX bundle, optional required checklist & portal fields
24. `S24_package_human_review` — Package subagent review round, visible-text baseline check, explicit `我确认这一版` & upload freeze
25. `S25_submission_audit` — Independent read-only reader, screening-editor & official-guideline final audit

See [INSTALL-ANTIGRAVITY.md](INSTALL-ANTIGRAVITY.md), [reference/antigravity-integration.md](reference/antigravity-integration.md), and [README_CN.md](README_CN.md) for full details.
