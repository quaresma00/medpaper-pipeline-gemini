# medpaper pipeline — Antigravity workspace rule (v1.29.0)

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
- Note the table/figure-first execution order: `S08_methods` -> `S10_tables` -> `S11_figures` ->
  `S09_results` -> `S12_reconcile`.
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
