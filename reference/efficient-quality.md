# Quality-preserving execution and incremental builds

Use at S06/S07, during feedback rounds (`S11b`/`S19`/`S24`), and during journal packaging (`S20`–`S24`).

## S06 pre-writing scientific freeze

- `01_protocol/analysis_contract.json` locks nine fields: `population_and_period` (`design`, `population`, `period`, `time_origin`, `follow_up`), `eligibility`, `unit_and_denominators` (`analysis_unit`, `key_fields`, `denominator_basis`), `outcomes`, `missing_duplicates_outliers` (`missing_data`, `duplicates`, `outliers`), `validation_and_adjudication`, `models_and_sensitivity` (`primary_analysis`, `target_question_or_quantity`, `confounding`, `sensitivity`), `exploratory_vs_confirmatory`, and `evidence_boundaries` (`contract_detail_version: 2`, using `{"applicable": true, "definition": "..."}` or `{"applicable": false, "reason": "..."}` rather than bare `N/A`), plus `variable_definitions` and `statistical_reporting`.
- `01_protocol/study_facts.json` holds the four-sentence clinical story (`clinical_question`, `main_finding`, `clinical_relevance`, `cannot_claim`), `result_sources`, and `numeric_facts` pointers (`reference/numeric-claims.md`).
- **Analysis stopping rule ([ICMJE guidance](https://www.icmje.org/recommendations/browse/manuscript-preparation/preparing-for-submission.html))**: Complete prespecified primary/secondary models and validity checks; report null, unfavorable, and non-estimable findings honestly without post-hoc power excuses or p-hunting. Retire superseded task-created JSONs to `.wf/retired_analysis/` with logged reasons rather than deleting valid null results.
- After `analysis_converged=YES` and `go_nogo_2=GO`, run `uv run python tools/manuscript/readiness.py freeze`. Any later change to analysis code, data, or contract invalidates `writing_ready` and requires owner reassessment.

## S07 low-cost prototypes & R-first production (`S10`–`S11`)

- Build lightweight structural prototypes under `01_protocol/prototypes/` (Markdown/CSV table skeletons and fast low-DPI R figure drafts that promote directly to `05_figures/out/` in S11) and record `items` in `01_protocol/display_review.json` (`readiness.py displays`).
- New statistical figures default to R (`reference/r-first.md`) consuming approved `03_analysis/results/*.json` (`render_r.py --all --changed`). Approved Python exceptions retain `tools/figures/style.py + recipes.py`. Inspect every rendered table preview (`tables/render_preview.py --all --changed`) and figure PNG via `read_file`. Keep technical paths, hashes, and JSON keys strictly backstage.

## Scoped revisions, dependency closure & gate caching

- Collect feedback via `tools/rework.py batch` (`--sealed` when ready to apply; see `reference/rework-routing.md`). `rebuild_files` tracks actual file dependencies (`source_files` in `bundle/manifest.json` and result JSONs). After editing `artifact_plan.json`, `rework.py refresh` narrows single-entry changes to affected displays.
- Record build passes with `rework.py build --scope full|targeted`; after two full builds, diagnose unstable inputs and switch to targeted fixes (`wf rebuild`). Mark resolved items with `rework.py mark --item <ID> --auto-changed --validated-by "..." --summary "..."`.
- Pure deterministic checks reuse SHA-256 input-bound receipts (`gatecache.py`, `wf check --timings`); any byte change in watched inputs or engine code invalidates the cached receipt immediately. Live reference gates (`S13`, `S19`, `S24`), data census gates, approvals, and freezes always execute fresh.

## Journal adaptation & immutable releases (`S20`–`S24`)

- S20 freezes `08_submission/submission_requirements.json` from official guidelines (`article_type`, `required_upload_roles`, `blinding`, `word_count`, optional `required_main_sections`, `display_limits`, `display_placement`; use `null` where guidelines are silent).
- S21 records `00_input/author_info.json` as the single administrative source (`author_block.py`).
- S23 builds clean DOCX uploads (`build_docx.py`), computes `portal_fields.json` (`submission_fields.py`), and captures `package_content_baseline.json`.
- S24 runs one independent read-only `research` subagent audit (`review_round.py --scope package`), obtains explicit **`我确认这一版`**, and freezes the read-only `<Journal_Slug>_<YYYYMMDD_HHMMSS>` release (`package_review.py freeze` / `verify`) bound to `Freeze ID` and `Audit context ID`.
