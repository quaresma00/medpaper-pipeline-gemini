# S07 - Artifact inventory and reader-ready display plan

Before writing or expensive production, survey 5-10 recent close SCIE Original Article
full-text comparators published within the past 5 years (`min_comparators = 5`). Synthesize
their figure counts, figure archetypes (e.g., study flow, primary outcome plot, subgroup/forest
plot, ROC/calibration/KM curve), and per-section word counts (`observations.section_words`:
`introduction`, `methods`, `results`, `discussion`) so this study matches current SCIE Original
Article depth and section balance rather than using outdated articles or thin displays. Abstract-only comparisons are insufficient.

For EACH table/figure state its clinical question, population/comparison, measure/unit and
denominator, placement, overlap with other displays and likely reader misunderstanding.
Required scientific reader tasks determine displays. Do not treat "focused", "compact" or
"nonredundant" as grounds to omit an applicable main selection flow or primary-result view.
Map actual comparator figure/table pages to adopted/modified/omitted roles in the existing
benchmark. Use **lightweight prototypes** under `01_protocol/prototypes/` to verify reader comprehension without writing duplicate production code: table prototypes use `.md`/`.csv` structural skeletons (headers, group/indent stubs, units, footnote templates); figure prototypes MUST be real low-DPI visual drafts (`.png`/`.svg`/`.pdf` from fast prototype scripts in `01_protocol/prototypes/` promoted to `05_figures/out/` in S11 — never write to `05_figures/out/` at S07). Use `readiness.py sync-hashes` to sync objective hashes.
New statistical graphics default to managed R (`ggplot2`/`patchwork`, modeled on S07 comparators; use `comparator_composite` + `comparator_basis` for heterogeneous layouts); record concrete Python exceptions.

Write substantive legends/captions that decode the actual display without repeating Results.
No magic word such as "footnote" certifies notes: S10 inspects every real workbook's notes.
Keep crowded abbreviations centralized, with necessary clinical definitions at point of use.
Do not infer units, endpoint components or confidence level from an internal variable name.
Establish an explicit display dictionary (internal terms -> clinical peer-reviewed display labels). Figure/table internal text, titles, captions, and legends must be fully readable to medical clinicians and polished for de-AI, anti-engineering, and anti-lab-log standards: zero snake_case variables, zero formula syntax, zero bare TRUE/FALSE, zero raw statistic column names (coef, fpr), zero AI clichés, zero engineering/pipeline jargon, **zero figure subtitles (`subtitle` / in-plot `caption`), and zero lengthy explanatory sentences inside figures** (all explanations belong in `05_figures/legends.md` or table footnotes).

## Full procedure
`reference/stage_details/S07_artifacts.md` (`tools/wf.py card S07_artifacts --details`). Read on first pass; after compaction use `tools/wf.py handoff`.

## Outputs
- `01_protocol/artifact_benchmark.md`
- `01_protocol/artifact_plan.json`
- `05_figures/legends.md`
- `04_tables/table_captions.md`
- `01_protocol/display_review.json`
- low-cost previews under `01_protocol/prototypes/`

## Close
Run `tools/wf.py check` (or the active scoped revision check). Fix actual failures before
`tools/wf.py advance --note "<actual completed work>"`. Stages are not turn boundaries.
Review stages still require the real author statement; generic continuation is not approval.
