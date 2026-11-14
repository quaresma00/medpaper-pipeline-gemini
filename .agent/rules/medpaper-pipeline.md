# medpaper pipeline — Antigravity workspace rule (v1.30.0)

This repository is a **gated 25-stage medical research paper pipeline**. Do not follow the
workflow from memory; `pipeline/pipeline.toml`, `AGENTS.md`, and the active stage card own all
sequencing, outputs, and checks.

## Start, resume, and context diet

Run via `pwsh` (never bare global `python` or `pip`):

```powershell
uv run python tools/wf.py status
uv run python tools/wf.py card
```

- If `.venv` is absent, run `uv run --python 3.13 python bootstrap.py`.
- After context compaction, run `uv run python tools/wf.py handoff` and read only the active card
  and topic references routed by `AGENTS.md` (`--details` only when first needed).
- Note the table/figure-first and pre-writing SCIE review order (all manuscript prose follows `S11b`): `S07_artifacts` -> `S10_tables` ->
  `S11_figures` -> `S11b_prewrite_review` -> `S08_methods` -> `S09_results` -> `S12_reconcile`.
- Complete active work, run `uv run python tools/wf.py check`, then
  `uv run python tools/wf.py advance --note "..."`. Gates are checkpoints, not turn boundaries.

## Non-negotiable integrity rules

1. **Full-census data acquisition**: Acquire the entire S03 protocol-defined universe (`tools/data_manifest.py`,
   or register large local originals in place via `tools/data_sources.py`). Never add convenience
   `LIMIT`, `TOP`, `head()`, `sample()`, `nrows=`, or page caps.
2. **Verified PubMed provenance**: Only `tools/pubmed/verify.py` (fresh EFetch + raw XML/library
   SHA-256) creates citable references. Register legal full texts with `tools/pubmed/fulltext.py register`.
   Never fabricate DOIs/PMIDs or hand-edit `verified.json`.
3. **Context-bound numeric provenance**: Own-study numbers must exist in executed
   `03_analysis/results/*.json` and bind to the exact population, endpoint, contrast, scale, join unit,
   and `n/N (%)` denominator (`claim_bindings.json`). Prior-study numbers require exact source passages.
4. **R-first medical figures & visual QA**: New statistical plots at S11 default to the managed R
   pipeline (`tools/figures/render_r.py`) using approved results without refitting. Always inspect
   actual rendered PNG/PDF/XLSX/DOCX files before recording visual QA.
5. **Version-bound subagent reviews & explicit approval**: Use one independent read-only subagent
   (`invoke_subagent` + `tools/review_round.py`) at S18/S19/S24/S25; no review ZIPs. Wait at S19/S24
   for the explicit version-bound statement **`我确认这一版`**.
6. **Scoped in-place rework & frozen scientific master**: Persist revisions via `tools/rework.py batch`
   at S19/S24, run affected owner checks in place, and rebuild true dependants (`wf rebuild`) without
   rewinding completed stages. Lock S19 with `scientific_master_freeze.json`; isolate all S20–S25
   journal adaptations under `08_submission/integration/` (`tools/journal.py`).
7. **Discussion isolation, single-source authors, display placement & supplemental naming (`v1.29.0`)**:
   Draft S16 from table-free/number-free `discussion_brief.md` after locking the 6-part `discussion_outline.md`;
   block Results sentence duplication and supplementary-callout overuse, and include `Discussion audit` in
   S18/S19/S24/S25 reviews. Render non-blinded authors on page 1 of `manuscript.docx` from `00_input/author_info.json`
   (separate `title_page.docx` only when double-blind or explicitly required by a verified guideline quote).
   Upload figures separately and put each main table on its own page after `References` unless an official
   guideline quote mandates inline placement. Name supplements `Supplemental_File_<N>_<Description>.<ext>`.
8. **Clean Word XML & user-owned disclosures**: Final DOCX outputs use native three-line tables and
   flat `SectionHeading` paragraphs stripped of `outlineLvl`, `keepNext`, `keepLines`,
   `pageBreakBefore`, borders, hyperlinks, and non-black text. Never draft an AI-use disclosure
   unless explicitly requested by the user.

See `AGENTS.md` and `reference/antigravity-integration.md` for capability and subagent routing.

8. **Clinical display internal text & dictionary gate (`v1.29.0`)**: All text inside figures (axes, tick labels, legend keys, panel titles, annotations, and flowchart boxes) and tables (headers, row stubs, cell values, and notes) must be peer-reviewed medical standard. S07 defines an explicit `display_dictionary` (mapping internal features/terms to clinical publication labels and units). Raw snake_case variables, formula syntax (`y ~ x`), bare `TRUE`/`FALSE`, raw package column names (`coef`, `se`, `fpr`), analysis report titles (`Analysis Report Figure 1`), and pipeline data manipulation language in flowcharts are strictly prohibited and enforced via the non-overridable gate `display_labels_clinical` across S07, S10, S11, S17, S18, S22, S23, S25.
9. **Per-section de-AI/claim-driven polish (with full retention of null/unfavorable results, limitations & uncertainty), S11b SCIE prewrite review, multi-route fulltext, browser guide capture & journal-named bundles (`v1.30.0`)**:
   - **Per-section polish**: Immediately run `tools/text/polish.py section --file <section.md> --snapshot` / `--verify` (`section_polished`) as each `.md` section is drafted (`S08`, `S09`, `S14`, `S16`, `S17` abstract) following `reference/clinical-deai-antidefensive-writing.md` (eliminate engineering jargon, AI clichés, and chronological work-report narration; adopt clear claim-driven structure while **strictly retaining unfavorable outcomes, null results, modest effect sizes, concrete study limitations, and calibrated statistical/causal uncertainty**).
   - **Early No-Go & S11b prewrite audit**: Halt immediately on `NO_GO` / `LOW_ROI_HALT` in `S02`/`S05`/`S06`/`S11b`. After `S11_figures` and before writing prose, run independent read-only SCIE review (`review_round.py --scope prewrite`) and obtain `我确认这一版`.
   - **Benchmark display & citation floors**: `S07` surveys 5–10 recent close SCIE comparators published within the past 5 years (`min_comparators = 5`) to drive figure counts/types (`benchmark_display_sufficiency`), and `S13`/`S14`/`S16`/`S17` enforce configured citation minimums (`literature_sufficiency`). `S22` performs cross-section consistency & journal limit alignment only, never full re-polishing.
   - **Multi-route fulltext + user fallback**: `fulltext.py fetch` tries OA + safe non-CAPTCHA Sci-Hub mirrors; CAPTCHA gates abort immediately without evasion and emit `.wf/pending_fulltext_requests.md` for user-supplied PDFs.
   - **Browser-first guidelines & journal+timestamp bundles**: Invoke the built-in `browser` subagent when HTTP guide extraction is incomplete; review `portal_discrepancies_and_warnings`; freeze releases and archives under `<Journal_Slug>_<YYYYMMDD_HHMMSS>`, and re-run full browser guide capture on journal switch.
