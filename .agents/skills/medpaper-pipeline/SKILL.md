---
name: medpaper-pipeline
description: Drives a gated, resumable 26-stage medical/clinical research paper pipeline from research intake through full-census data acquisition, R-first figures and three-line tables, pre-writing SCIE audit (S11b), immediate per-section clinical de-AI/anti-defensive polish, context-bound IMRAD writing, version-bound independent subagent review, frozen scientific master, browser-verified journal adaptation, native Word packaging, and final reader/editor/compliance audit. Use whenever the task involves a medical research idea, clinical manuscript, research protocol, PubMed literature retrieval, medical figures/tables, journal selection, user revisions, or a submission package. Never follow the workflow from memory — run `uv run python tools/wf.py status` and obey the active stage card.
compatibility: Requires Windows pwsh, uv, and Python 3.12+ (3.13 recommended) for pinned science/PDF dependencies (matplotlib, numpy, openpyxl, pandas, scipy, python-docx, pypdf). R (Rscript) is the default renderer for new medical figures; Pandoc and Microsoft Word support final DOCX assembly and visual QA. Network access is required for PubMed, Crossref, Unpaywall, and official journal guidelines.
metadata:
  version: "1.30.0"
  entrypoint: "uv run python tools/wf.py status"
---

# medpaper pipeline (Antigravity / Gemini v1.30.0)

## Master Template & Dispatch Rule

The authoritative master template defaults on this machine to `F:\workspace\medpapaer\gemini` (external clones may override via `$env:MEDPAPER_MASTER_TEMPLATE` or `uv run python tools/medpaper_launcher.py --template-source <dir>`):

When this skill is invoked (always execute terminal commands via `pwsh` and `uv run python`, never bare global `python` or `pip`):

1. **Existing paper project** (`pipeline/pipeline.toml` and `tools/wf.py` already exist in the workspace):
   - Resume immediately with the compact, zero-network status and stage card:
     ```powershell
     uv run python tools/wf.py status
     uv run python tools/wf.py card
     ```
   - After context compaction, run `uv run python tools/wf.py handoff` to restore bounded resumption state without reloading history.
   - If the user explicitly asks to upgrade an older workspace engine from `F:\workspace\medpapaer\gemini`, sync **only** engine paths (`pipeline/`, `tools/`, `reference/`, `.agent/`, `.agents/`, `AGENTS.md`, `bootstrap.py`, `requirements.txt`, `requirements-guides.txt`) while strictly preserving `project/` and `.venv/`, install any new pinned packages into `.venv`, and keep `engine_pin` intact so completed historical stages are never silently rewound.
2. **New / empty project folder** (workspace lacks `pipeline/` and `tools/wf.py`):
   - Copy the purified engine skeleton (`pipeline/`, `tools/`, `project/`, `reference/`, `.agent/`, `.agents/`, `AGENTS.md`, `bootstrap.py`, `requirements.txt`, `requirements-guides.txt`, `.gitignore`) from `F:\workspace\medpapaer\gemini` into the current workspace (never from another study workspace).
   - Provision `.venv` and initialize `project/.wf/state.json`:
     ```powershell
     uv run --python 3.13 python bootstrap.py --skip-selftest
     uv run python tools/wf.py status
     uv run python tools/wf.py card
     ```
   - Proceed from `S01_intake`.

## Execution Loop & Context Diet

Read the workspace's `AGENTS.md` once and use its topic router to load `reference/*.md` guides only when needed (`uv run python tools/wf.py card <STAGE> --details` only on first pass of split stages).

```powershell
uv run python tools/wf.py status                 # compact local state (add --full to run gates)
uv run python tools/wf.py card                   # active stage instructions
# <complete active stage outputs; print progress during long tasks>
uv run python tools/wf.py check                  # run deterministic + provenance gates
uv run python tools/wf.py advance --note "..."   # advance when green; gates are not turn stops
```

Note the **table/figure-first and pre-writing SCIE audit sequence**: execution advances **`S08_methods` -> `S10_tables` -> `S11_figures` -> `S11b_prewrite_review` -> `S09_results` -> `S12_reconcile`** so approved three-line tables, R figures, and an independent SCIE methods/display audit precede `Results` and full manuscript prose.

## Key Commands

| Command | Purpose |
|---|---|
| `uv run python tools/wf.py status [--full]` | Compact local state (or full gate evaluation) |
| `uv run python tools/wf.py handoff` | Bounded local context recovery after compaction |
| `uv run python tools/wf.py card [STAGE] [--details]` | Read active/named stage card (or full split procedure) |
| `uv run python tools/wf.py check [STAGE]` | Run stage gates without advancing |
| `uv run python tools/wf.py advance --note "..."` | Close current stage and advance on green gates |
| `uv run python tools/wf.py decide NAME VALUE --why "..."` | Record a gated scientific/editorial decision |
| `uv run python tools/wf.py rebuild [--dry-run]` | Dependency-aware incremental rebuild of affected outputs |
| `uv run python tools/wf.py migrate [--dry-run]` | Inspect or adopt current engine gates on pinned legacy projects |
| `uv run python tools/wf.py doctor` | Verify environment, `.venv` packages, Rscript, Pandoc, and wiring |
| `uv run python tools/wf.py clean [--apply]` | Report undeclared files and clean `project/temp/` |
| `uv run python tools/data_manifest.py init\|sync\|verify` | Full-census count, pagination, join-unit, and hash proof |
| `uv run python tools/data_sources.py register ...` | Register external large raw datasets read-only in place |
| `uv run python tools/figures/render_r.py --figure "..."` | Managed R-first clinical figure renderer with job lock |
| `uv run python tools/review_round.py start\|ingest\|close\|decide` | Version-bound subagent review rounds (S18/S19/S24) |
| `uv run python tools/rework.py batch\|status\|check\|close` | Persisted in-place scoped revisions without stage rewind |
| `uv run python tools/journal.py begin\|guide\|seal` | Bind journal/ISSN/article-type context and archive prior attempts |

## Non-Negotiable Scientific & Production Rules

1. **Full-data census coverage (`S04`)**: Acquire 100% of the S03 protocol-defined universe (`acquisition_manifest.json`) or register read-only originals via `data_sources.py`. Convenience `LIMIT`, `TOP`, `head()`, `sample()`, `nrows=`, or fixed page caps are blocked and non-overridable.
2. **Fail-closed literature provenance (`S02`/`S05`/`S07`/`S13`–`S25`)**: Candidate search tools may discover papers, but only `tools/pubmed/verify.py` (fresh EFetch + raw XML/library hashes) makes a reference citable, backed by live EFetch gates at S13 and S25 (and 24h hash-bound cache in between). Register legal full texts via `tools/pubmed/fulltext.py register`. Never invent metadata or hand-write `verified.json`.
3. **Context-, scale-, denominator-, and figure-bound numbers**: Every own-study number in Results, Abstract, Discussion, tables, and explicit figure statistical annotations must originate from executed `03_analysis/results/*.json` (with R/Python replay provenance) and bind to population, endpoint, contrast, controlled effect scale (`HR`/`RR`/`OR`), interval level, join unit, table header/row context, `n/N (%)` denominator, and `figure_annotations` (`claim_bindings.json`). Prior-study numbers require exact source passages (`source_claims`).
4. **Benchmark-driven design & R-first figures**: No universal reference/word/figure quotas — S06 freezes `analysis_contract.json` + `study_facts.json`, and S07 seals comparator full-text benchmarks (`tools/manuscript/benchmark.py`). Ordinary retrospective/database studies require no default public registration; reporting checklists are generated only after S20 if required by the target journal (`checklist_docx.py`). New statistical figures default to R (`reference/r-first.md`).
5. **Version-bound subagent review & explicit `我确认这一版` (`S18`/`S19`/`S24`/`S25`)**: Delegate independent reviews to one read-only subagent (`invoke_subagent` with `research` + `review_round.py ingest --from-file`), fix safe defects in place via `rework.py`, report once with clickable file links, and wait for the user's explicit **`我确认这一版`** for the current version (no review ZIPs).
6. **Isolated Discussion, single-source authors, display placement & `Supplemental_File` naming (`v1.28.0`)**: S16 builds a table-free/callout-free `discussion_brief.md` and locks a concise 6-part `discussion_outline.md` (`discussion_brief.py`) before drafting `discussion.md`, blocks Results restatement and supplementary-callout overuse, and verifies `Discussion audit` at S18/S19/S24/S25. Non-blinded `manuscript.docx` places complete single-source author info (`00_input/author_info.json`) on page 1 (separate `title_page.docx` only when double-blind or backed by a verified official guideline quote). Figures upload separately (keeping `# Figure legends` at the end) and main tables sit one per page after `# References` unless an official guideline quote mandates inline embedding. Supplemental uploads use sequential `Supplemental_File_<N>_<Specific_Description>.<ext>` filenames.
7. **Frozen scientific master & isolated journal layer (`S19`–`S25`)**: After S19 approval, lock `07_manuscript/scientific_master_freeze.json`. Perform all journal styling, native portrait/landscape Word three-line tables (`wordtables.py`), flat pure-black `SectionHeading` XML cleanup (`build_docx.py`), and portal field extraction inside `08_submission/` and `08_submission/integration/`. See `reference/antigravity-integration.md`.
8. **Clinical display internal text & dictionary gate (`v1.29.0`)**: All text inside figures (axes, tick labels, legend keys, panel titles, annotations, and flowchart boxes) and tables (headers, row stubs, cell values, and notes) must be peer-reviewed medical standard. S07 defines an explicit `display_dictionary` (mapping internal features/terms to clinical publication labels and units). Raw snake_case variables, formula syntax (`y ~ x`), bare `TRUE`/`FALSE`, raw package column names (`coef`, `se`, `fpr`), analysis report titles (`Analysis Report Figure 1`), and pipeline data manipulation language in flowcharts are strictly prohibited and enforced via the non-overridable gate `display_labels_clinical` across S07, S10, S11, S17, S18, S22, S23, S25.
9. **Per-section de-AI/anti-defensive polish, S11b SCIE prewrite review, multi-route fulltext, browser guide capture & journal-named bundles (`v1.30.0`)**:
   - **Immediate per-section polish**: Immediately run `tools/text/polish.py section --file <section.md> --snapshot` / `--verify` (`section_polished`) as each `.md` section is drafted (`S08`, `S09`, `S14`, `S16`, `S17` abstract) following `reference/clinical-deai-antidefensive-writing.md`.
   - **Early No-Go & S11b prewrite audit**: Halt immediately on `NO_GO` / `LOW_ROI_HALT` in `S02`/`S05`/`S06`/`S11b`. After `S11_figures` and before writing prose, run independent read-only SCIE review (`review_round.py --scope prewrite`) and obtain `我确认这一版`.
   - **Benchmark display & citation floors**: `S07` surveys 5–10 recent close SCIE comparators published within the past 5 years (`min_comparators = 5`) to drive figure counts/types (`benchmark_display_sufficiency`), and `S13`/`S14`/`S16`/`S17` enforce configured citation minimums (`literature_sufficiency`). `S22` performs cross-section consistency & journal limit alignment only, never full re-polishing.
   - **Multi-route fulltext + user fallback**: `fulltext.py fetch` tries OA + safe non-CAPTCHA Sci-Hub mirrors; CAPTCHA gates abort immediately without evasion and emit `.wf/pending_fulltext_requests.md` for user-supplied PDFs.
   - **Browser-first guidelines & journal+timestamp bundles**: Invoke the built-in `browser` subagent when HTTP guide extraction is incomplete; inspect `portal_discrepancies_and_warnings`; freeze releases and archives under `<Journal_Slug>_<YYYYMMDD_HHMMSS>`, and re-run full browser guide capture on journal switch.
