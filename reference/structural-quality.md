# Clinical Presentation, Complete Review Closure, and Denominator Binding

Core structural rules for S07 planning, S09-S11 display generation, S18/S24 independent review closure, and percentage reporting.

## 1. Shared Clinical Vocabulary (`display_dictionary`)

Define `artifact_plan.json.display_dictionary` at S07 whenever raw dataset variables or model labels are non-clinical or ambiguous:
- Each entry specifies unique `key`, `internal`, clinical `label`, one-sentence `definition`, and `scope` (cohort/source or `"all"`). Leave empty if all labels are already standard clinical terms.
- Python `clinicalpresentation.label(value, project, scope=...)`, `journalspec.label_text`, the three-line table builder, and R `medpaper_label()` consume the same dictionary.
- Never rename raw statistical variables or alter numeric facts to improve display labels; define composite endpoints at first clinical use. Keep technical model diagnostics in supplementary tables unless essential to main-table interpretation.

## 2. Early Physical Production Profile (`presentation_profile`)

Choose `presentation_profile` in `artifact_plan.json` at S07 before journal selection:
- `figure_font_pt_min` (default `>= 8` pt at final printed width), optional `figure_font_pt_max`, `figure_dpi_min`, `column_width_mm_single`, `column_width_mm_double`, `number_format`, and `basis`.
- S20 may override via `target_journal.figure_requirements` (`figure_rule_source`). Managed R rendering and SVG/raster QC validate effective typography at the planned physical column width.
- Flowcharts require complete boxes, counts, and exclusion arrows rather than x/y plot axes; statistical plots require zero-anchored bar baselines (including stacked bars) and explicit axes. Distinguish record/version counts from unique patient/case counts explicitly.
- Table body cells stay concise (`<= 300` chars); explanatory footnotes appear below every bottom rule and clearly distinguish zero, missing, not fitted, and nonestimable cells.

## 3. Complete Independent Review Disposition

Every S18/S24 independent review round uses schema 3 (`finding_inventory_complete: true`, `findings`, `section_verdicts`):
- Every review section (`Reader comprehension`, `Medical presentation`, scientific/editorial dimensions) records `findings_listed` or `no_actionable_findings`.
- Every actionable point carries `[finding:ID]` in prose and a JSON entry (`id`, `section`, `text`, `locator`, `category` in `numbers|grouping|conclusion_strength|objective|preference`, `affects_science`).
- Close rounds via `review_round.py close --resolutions <JSON>`: every finding requires either `{status: "fixed", reason, files}` (or `revision_round` for producer-only fixes) or `--kept ID <reason>` backed by real version-bound `--author-decisions` (`--words-file` / `--words-b64`). Numerical, grouping, or conclusion-strength defects require correction or explicit author adjudication—never self-dismissal as preference.

## 4. Percentage Denominator & Scale Binding

- Every reported proportion in `claim_bindings.json` binds `proportions`: `fact_id`, `numerator_key`, `denominator_key`, exact `reported` percentage, and optional `percentage_kind` (`part_whole` default, `relative_change`, or `probability`).
- Source `study_facts.json` states `percentage_basis` (eligibility, available-case rule, counting unit, time window). Mixing different denominator bases in one clause requires correction or an explicit `different_percentage_bases` explanation in prose.
- Rate scales in table headers/notes (e.g., `per 1,000 person-years`) use `kind: "unit_scale"` in `claim_bindings.json` with exact `path/sheet/cell/text`, `source_path`, and verbatim `source_quote`—never a global numeric whitelist.
- Display reference aliases (`Online Resource`, figure/table numbers) are excluded from effect-size comparisons via `display_reference_aliases` (`display_reference_rule_source`), while cross-reference and slot checks remain enforced.
