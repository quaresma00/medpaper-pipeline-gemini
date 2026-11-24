# S11 - Render figures, then actually look at them

## Production boundary
Read `reference/r-first.md`, `reference/efficient-quality.md` and `reference/figure-standards.md`.
New medical statistical figures default to R. Reuse the approved S07 data, semantics and
prototype expression. Keep a literal .R script beside vector PDF/PNG in 05_figures/out.
Use mature clinical R packages and ggplot/grid/patchwork outputs as appropriate, with one
statistical source per result. Do not refit or rerun imputation to adjust a graph.
Retain an approved legacy Python graph or a concrete documented Python exception.
Missing R packages require repair, not an unannounced Python fallback.

## Procedure
Choose the design-appropriate recipe using `reference/r-first.md`'s medical figure routes.
The endpoint, measure and required uncertainty determine the graph; a theme cannot supply
missing clinical content. Use `medpaper_clinical_forest` (`medpaper_forest_panels` in
`tools/figures/r_recipes.R`) for multi-column subgroup forest plots (supports duplicate
`Yes`/`No` levels, `Reference`/`NE` rows, left count columns, and `P for interaction`),
`medpaper_consort_flow` (`orthogonal=TRUE`) for single/multi-source selection diagrams,
and `medpaper_km_survival` for KM/CIF curves + aligned risk tables. Always use
the exact same statistical estimator and sparse/zero-cell rule shown in S10 tables, and use
neutral grey + `NE (0/N)` for zero-event heatmap/matrix cells without smoothed positive shading.

1. Confirm Rscript and the actual required packages/environment. Put renderer="R" in each
   new figure entry, plus its .R script, PNG/PDF paths, width, source_results and archetype.
   A Python exception declares renderer="Python" and a substantive renderer_reason.
   No additional routine user approval stop is introduced.
2. Write one source per figure (promoting and refining any fast R prototype script created in
   `01_protocol/prototypes/` during S07). Source `tools/figures/r_style.R` and read declared
   executed results with `medpaper_result()`. Centralize theme, font, physical size, palette and
   panel layout. Multi-panel letters are independent `A`/`B`/`C` at each component's outer
   upper-left corner (`medpaper_compose(panels, ncol=N)`), separate from clinical titles/facet
   strips, with `panel_layout.columns` declared in `artifact_plan.json`. Pass actual component
   ggplots in `panels=list(p1,p2,...)` to `medpaper_save()`. Use patchwork/grid instead of
   repeated pixel nudges.
3. Render and run deterministic QC (batch/incremental or single-figure):
```powershell
uv run python tools/figures/render_r.py --all --changed
uv run python tools/figures/qc.py --all
# Single-figure rebuild & focused check:
uv run python tools/figures/render_r.py --figure "Figure 1"
uv run python tools/figures/qc.py --figure "Figure 1"
uv run python tools/wf.py check --all-checks --only "Figure 1"
```
   Python in the runner does not draw the plot. R uses explicit objects/physical sizes and
   generates PNG+vector PDF; TIFF is opt-in. Render warnings fail instead of silently
   dropping observations. Staging preserves existing outputs on failed R builds.
4. Read actual QC findings. R QC inspects SVG font/stroke/text positions and built ggplot
   layers, PNG resolution/content and bound script/results/render identities. For 1.27+, any
   explicit statistical text rendered inside a figure (`HR`/`OR`/`RR`/`CI`/`P`, sample counts,
   or effect estimates) must also be bound item-by-item under `figure_annotations` in
   `07_manuscript/claim_bindings.json` to its exact `fact_id`, result `source`/`pointer` and
   value fields (`qc.py` + `numbers_have_provenance source=figures`).
   Text-height/collision estimates are conservative; glyph coverage, PDF font fallback,
   clipping paths and complex layouts remain visual-review items, not fabricated PASS.
   Some specialized base/grid graphics need a measured adapter. Keep the appropriate R
   tool; do not relabel a chart or fabricate elements to evade checks.
5. Open the actual rendered PNG and inspect font/glyphs, overlap/clipping, clinical labels,
   reference groups, units, denominator/time window, uncertainty, axes, risk tables,
   panel alignment, colour/greyscale readability, margins and resolution. For complex
   layouts also open the vector PDF. Use one <=1280px, <=500KB preview per tool round.
   Warnings must be resolved or substantively addressed in the existing review.
6. Correct only the affected producing script/config, rerender that figure and rerun its
   QC. Do not redo cleaning/models or unchanged figures for a visual-only correction.
   A substantive statistical correction follows the existing scientific revision route.
7. Keep explanatory prose backstage or in its proper Methods destination. Figure legends
   only decode the display, panels, symbols and necessary test/error-bar definitions.
   They do not repeat Results directions/effect estimates. Preserve journal-mandated risk
   tables, flow counts, units and essential source-bound statistics. Use the existing
   legend length as advisory unless the journal explicitly limits it; record actual moved
   material in 05_figures/moved_to_legend.md.
   - **No subtitles, no in-plot captions, and no excessive explanatory text inside figures**: Never add a `subtitle` (`labs(subtitle=...)`, `ggtitle(..., subtitle=...)`, `plot_annotation(subtitle=...)`) or in-plot `caption` to any figure. Keep all explanatory notes, model covariate lists, symbol/line definitions (`Solid line indicates...`, `Adjusted for...`, `Note:...`), and abbreviations out of the figure canvas—place them in `05_figures/legends.md` or Methods. Inside a non-flowchart panel, keep text strictly to concise axis labels with units, group/stratum names, panel letters (`A`, `B`, `C`), and brief statistical annotations (`<=12` words, e.g. `HR 1.42 (95% CI 1.10-1.83), P = 0.008`).
   - **Clinical internal labels & de-AI/de-engineering polish**: All text rendered inside figures and `05_figures/legends.md` must be clinical-reader ready and free of AI clichés, work-report narration, analytics pipeline phrasing (`filtered where age >= 18`, `dropna()`, `Analysis Report Figure 1`), raw variables, and model code. Apply `apply_labels()` or `medpaper_label()` in R scripts. Figures and legends are strictly gated by `display_labels_clinical` and `figures_qc_pass`.
8. Write 05_figures/manifest.json with actual renderer, script, source_results, png/pdf,
   width/size_mm/dpi, R/package versions or the Python exception, and review_rounds.
   SVG/rmeta/artist sidecars are backstage QC, not submission uploads.
9. Bind each production render in `01_protocol/display_review.json.final_reviews` (`reference/project-benchmarking.md`, `reference/medical-reader-presentation.md`; use `uv run python tools/manuscript/readiness.py sync-hashes` to sync objective hashes — drifted files reset to `PENDING_REINSPECTION`), mark `visual_reviewed: true` in `05_figures/qc/qc_report.json`, and record `figures_visually_confirmed` ONLY after genuine image inspection. Automated QC never supplies this approval.
10. Clear task scratch. Journal-specific adaptations after S19 use integration copies and
    preserve the accepted scientific script/output.

## Python exceptions
For an existing approved Matplotlib figure or concrete exception, retain its source and
`tools/figures/style.py + recipes.py`. No R-to-Matplotlib conversion is needed.
`image-generator` may critique readability as an optional visual critic, but never redraw or edit statistical content; fix source
code and inspect the deterministic new render via `read_file`.

## Outputs
- 05_figures/manifest.json
- 05_figures/qc/qc_report.json
- 05_figures/moved_to_legend.md
- Co-located producing scripts and PDF/PNG; legacy separated scripts remain supported.

## Hard rules
No invented results, fabricated inspection or skipped source checks. Keep all data.
Do not fix a layout defect by shrinking below the font floor. Correct the layout structure.
No gratuitous 3-D/gridlines or unplanned figures. Missing inspection is pending, not PASS.

## Close
```powershell
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "Declared R/Python outputs rendered; measured QC and actual visual review completed; unresolved items stated."
```

