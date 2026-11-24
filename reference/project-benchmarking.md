# Project-specific SCIE full-text benchmarking and clinical display planning

Read at S07 and S13–S17; retain findings across turns instead of repeating searches. Keep this evidence backstage, outside manuscript headings and submission uploads.

## S07 full-text comparator survey (>=5 recent SCIE papers)

At S07, before drafting `Methods`, building workbooks, or rendering final figures, read `>=5` distinct close SCIE articles published within the past 5 years (`Original_Article` default; explicit `Brief_Report`/`Research_Letter` adapts floors with a substantive `genre_rationale`). Select by clinical topic, study design, and statistical relevance; inspect actual `Methods`, `Discussion`, and figures/tables from registered full texts—never abstracts alone.

Seed comparator/methodology references with the pipeline client:
`build_library.py --add-ids <PMIDs>`, `verify.py`, then `fulltext.py fetch --citekey <KEY> --no-stub` (or legal `register`). S13 completes this same library rather than creating a second one.

## Single benchmark document (`01_protocol/artifact_benchmark.md`)

Keep the declared headings (`Comparable papers surveyed`, `Figure/table counts observed`, `Chosen inventory and why`) in clear clinical prose and embed **one** fenced JSON object with `benchmark_version: 1`:

- `adequacy_rationale`: how the selected SCIE papers cover this study's clinical design and remaining differences.
- `comparators`: one entry per read full text with verified `citekey`, registered `fulltext` path, `sha256`, `year`, `relevance` (`topic`, `design`, `analysis`), `observations`, and short `evidence` quotes (`<=25` words per comparator, `kind: methods|discussion|display`).
  - `observations`: `methods_outline`, `discussion_structure`, `reference_roles`, `display_roles`, `figure_types`, integer `main_figures`, `main_tables`, `supp_figures`, `supp_tables`, `section_words` (`introduction`, `methods`, `results`, `discussion`), and `citations` (`introduction`, `methods`, `discussion`, `supplementary`).
- `adaptation.structure`: project-specific `methods`, `discussion`, `main_vs_supplement`, and `declarations` decisions. Keep validity-critical `Methods` in the main text; use connected `Discussion` paragraphs unless subheadings are clinically justified.
- `adaptation.references`: `basis`, advisory `ranges` (`introduction`, `methods`, `discussion`, `supplementary`, `library`, `main_total`), and project-specific argument `roles` (`id`, `section`, `claim`, `source_type`, `required`, `citekeys`). When each section is drafted, ensure those `citekeys` are genuinely cited in the target `.md` file (no need to copy-paste edited sentences back into `passage`).
- `adaptation.displays`: `inventory_rationale`, `essential_questions`, `omissions`, `figure_count_rationale` (`>=30` chars), and `role_mapping` covering four clinical reader tasks once each:
  1. `selection`: `applicable` (bool), `process: none|single_stage|multi_stage`, `steps`, `counting_unit_and_branches` (records vs unique patients; exclusions vs nested subsets), `display_ids`, `scientific_reason` (`>=40` chars), and `comparator_evidence: [{citekey, locator, adopt_or_depart}]`. Any real selection process maps to main **`Figure 1`** (`archetype: "flow_diagram"`).
  2. `population`: `summaries: {categorical, continuous}` specifying exact denominators (`n (%)`), distribution summaries (`mean [SD]` / `median [IQR]`), and missingness handling.
  3. `primary_results`: main-text clinical outcome display(s) distinct from the selection flowchart.
  4. `comparisons_or_robustness`: subgroup, sensitivity, or secondary displays (main or supplementary, never fabricated analyses).

Seal the pre-writing plan once at S07:
```powershell
uv run python tools/manuscript/benchmark.py seal --layer science
```

## Reader contracts, multi-panel R tags, and visual review (`S07`–`S11`)

- Every planned display in `01_protocol/artifact_plan.json` carries a `reader_contract` (`population`, `comparison`, `measure`, `denominator_and_units`, `interpretation_limit`, `question`, `placement_reason`, `nonredundancy`, `misinterpretation_risk`). Distinct displays cannot copy identical purpose/placement strings.
- Multi-panel R figures declare `panels: ["A", "B", ...]` and `panel_layout: {"columns": N}` (plus normalized `bounds` when irregular). Compose with `medpaper_compose(panels, ncol=N)` so uppercase panel tags sit at each panel's upper-left margin, separate from clinical panel titles.
- At `S10`/`S11`, record `final_reviews` in `01_protocol/display_review.json` keyed by display ID (`reviewed_file`, `sha256`, `rendered_preview` PNG/PDF, `rendered_sha256`, concise `reader_explanation` and `layout_and_style`, and `verdict: "PASS"` after inspecting actual rendered previews via `read_file`). Use `uv run python tools/manuscript/readiness.py sync-hashes` if hashes drift (`PENDING_REINSPECTION` requires genuine visual re-inspection).
- At `S20`/`S22`, explicit journal display caps live in `08_submission/submission_requirements.json.display_limits` (`null` when unstated) and are applied only to `08_submission/integration/artifact_plan.json`, keeping the S19 scientific master untouched.
