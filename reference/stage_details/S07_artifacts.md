# S07 - Artifact inventory (benchmarked) + legends written first

Read `reference/project-benchmarking.md` completely. Complete the genuine full-text benchmark
and seal its project adaptation before Methods or expensive production. Seed the same formal
PubMed library using selected comparator/method PMIDs and verify it; S13 later completes it.
Record comparison evidence and project citation-role/range choices in the existing benchmark
Markdown's `benchmark_version: 1` block. Counts are reference points, not fixed minima/caps.
Abstracts and a bare "benchmarked" flag do not satisfy this gate.

Read `reference/r-first.md`. Plan new figures with renderer="R" and co-located .R/PNG/PDF.
Use `01_protocol/artifact_benchmark.md` (surveying 5-10 recent close SCIE Original Article full texts published within the last 5 years, `min_comparators = 5`) to drive figure count and figure archetypes (`observations.main_figures`, `observations.figure_types`, `observations.references`, and `year` / `observations.year`). Synthesize `adaptation.displays.figure_count_rationale` so the paper presents an SCIE-competitive figure suite (e.g., study flow, primary outcome plot, subgroup/sensitivity forest plot, prognostic/calibration curve) instead of 2-3 sparse displays without explicit clinical justification (`benchmark_display_sufficiency`). Prototype in R with full data and the same semantic layout; retain approved legacy Python
figures or record a concrete Python exception instead of silently defaulting to it.

## Purpose
Decide exactly what the paper displays, benchmarked against what comparable papers
actually display, and write every legend before anything is drawn. Legends written
first keep panels from filling up with explanatory text later.

## Procedure
1. **Benchmark.** Retrieve comparable papers - same design, same field, the kind of
   journal you are targeting - and count what they display. A scholarly search helper may
   find candidates, but every comparator used in the benchmark must be retrieved through
   the bundled client:
```
uv run python tools/pubmed/client.py search --query "<design> <topic>" --retmax 100
uv run python tools/pubmed/client.py fetch --ids <...> --with-abstract
```
   Write `project/01_protocol/artifact_benchmark.md` with headings
   `Comparable papers surveyed`, `Figure/table counts observed`, `Chosen inventory and why`.
   Record the observed range (e.g. "4-6 main figures, 2-3 main tables, n=8 papers"), and
   justify your inventory against it. Optimize complete medical communication; fewer items
   are not inherently better and extra items must not be added merely to imitate counts.
   Counts alone are insufficient. Read the actual Methods/Results and at least one table
   and figure from close, legally accessible medical comparators. In the same benchmark
   note record their clinical ordering, labels, denominators, uncertainty and footnote/legend
   conventions, and explain what is suitable for this study. Do not imitate visual decoration
   or assume an abstract proves the full paper's display style. Record unavailable full text.
2. **Plan.** Write `project/01_protocol/artifact_plan.json`. Every entry needs a
   `source_results` list pointing at the result JSONs it is built from - an artifact with
   no numeric source cannot be built:
```json
{
  "main_figures": [
    {"id": "Figure 1", "slug": "flow", "title": "",
     "content": "what the reader learns from it, in one sentence",
     "archetype": "flow_diagram",
     "panels": ["A", "B"], "width": "single|1.5|double",
     "renderer": "R", "script": "05_figures/out/Figure1.R",
     "file": "05_figures/out/Figure1.png",
     "pdf": "05_figures/out/Figure1.pdf",
     "source_results": ["03_analysis/results/dataset_summary.json"]}
  ],
  "main_tables": [
    {"id": "Table 1", "slug": "baseline", "title": "",
     "content": "", "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1",
     "source_results": ["03_analysis/results/baseline.json"]}
  ],
  "supp_figures": [],
  "supp_tables": [
    {"id": "Table S1", "slug": "", "title": "", "content": "",
     "file": "04_tables/supplementary/supplementary_tables.xlsx", "sheet": "Table S1",
     "source_results": []}
  ],
  "supp_files": [{"id": "Supplementary File 1", "file": "", "what": ""}]
}
```
   Structural requirements the gate enforces: sequential numbering with no gaps; each
   main table in its own xlsx; **all supplementary tables in a single xlsx, one sheet
   each**; every figure has a `width`, a `script` and an `archetype`.
   Map the four reader tasks using `adaptation.displays.role_mapping` in the existing benchmark
   (schema in `reference/project-benchmarking.md`). A real participant/report/study selection
   process belongs in a main Figure 1 flow diagram, especially when versions, exclusions,
   suspect roles or nested subsets affect denominators. A supplementary counting table does
   not replace it. A genuinely absent selection process may be marked inapplicable with its
   scientific basis. Do not impose a fixed total figure count or an early reporting checklist.
   Specific journal reporting/display requirements are handled later in the integration copy.
   Add `display_dictionary` mapping every internal feature, covariate, and model term to clinical publication labels and units. Figure/table internal text (axes, tick marks, legends, flowchart boxes, table headers/cells) must completely avoid code variables, script syntax, bare boolean values, and analytics-report jargon. Add `reader_contract` to every display: `population`, `comparison`, `measure`,
   `denominator_and_units`, `interpretation_limit`, plus distinct `question`,
   `placement_reason`, `nonredundancy`, `misinterpretation_risk`. Use short factual sentences; explain
   inapplicability rather than inserting a fictional comparison. This internal contract
   guides captions and labels; never print JSON keys or workflow terminology in the figure.
   Declare table `script` paths too, and additional project-specific file consumers in
   top-level `dependencies: [{"file": "...", "source_files": ["..."]}]` when needed.

3. **Declare each figure's archetype.** Pick it from `reference/archetypes.toml` and read
   that entry before planning the figure - it lists the elements that chart type must have,
   and S11 checks the rendered figure for them. Choosing `km_survival` commits you to a
   number-at-risk table and censoring marks; choosing `histopathology` commits you to a
   physical scale bar. Pick the archetype that matches what the data needs, then accept its
   requirements. `other` is available but demands an `archetype_rationale`, and it turns off
   the domain checks, so prefer a real archetype.
4. **Legends.** Write `project/05_figures/legends.md`, one compact block per figure, each
   headed `Figure N.` / `Figure S1.` Use medical-journal form: a brief descriptive title;
   one clause or sentence per panel; only essential visual encodings; sample size/error-bar
   definition/statistical test only when the figure cannot be interpreted without it; then
   a short abbreviations clause when needed. Target 40-140 words and never exceed the
   configured 180-word ceiling. Describe what is drawn and how to decode it; do not state
   which group was higher or lower, repeat effect estimates, or retell the Results.
   Do not repeat cohort acquisition, complete model specification, software versions,
   interpretation, numerical Results or generic caveats already stated elsewhere. The file
   contains exactly one `# Figure legends` section heading and exactly one heading for each
   planned figure. After a `Figure N.` heading, do not begin the body with `Figure N.` again.
5. **Table captions.** Write `project/04_tables/table_captions.md`, one block per table,
   headed `Table N.` Each needs a title line plus the footnote content: abbreviation
   expansions, units, the test used, what a dagger/asterisk marks. Short abbreviation lists
   may remain local. Decide the shared glossary here, before production, using
   `artifact_plan.json` field `abbreviation_policy` (placement and definitions). If more than
   eight different terms accumulate across displays, or one local list exceeds 50 words,
   plan a central Declarations and Statements glossary. Preserve local units/symbol meanings
   needed to read each display. S17 assembles and verifies the choice, not a planned table rebuild.

6. Read `reference/efficient-quality.md` and create **lightweight prototypes** for each planned
   display strictly under `01_protocol/prototypes/`:
   - Table previews use `.md` or `.csv` structural skeletons (column hierarchy, bold group headings,
     indented row stubs, units, and footnote templates — without building formatted XLSX workbooks).
   - Figure previews MUST be real visual files (`.png`, `.svg`, or `.pdf`) generated by fast low-DPI
     prototype R scripts placed inside `01_protocol/prototypes/` (e.g. `dpi = 120` to test real data
     density, multi-panel proportions, and axis bounds in <1 s). Never write to `05_figures/out/` at
     S07; promote and refine those prototype R scripts into `05_figures/out/` at S11.
   Open each preview, conduct the one-minute reader-comprehension screen, record substantive explanations
   and reviewer identity in `01_protocol/display_review.json` (do not claim a human reviewed an agent
   simulation), sync objective hashes via `uv run python tools/manuscript/readiness.py sync-hashes`, and
   verify via `uv run python tools/manuscript/readiness.py displays`.

## Outputs
- `01_protocol/artifact_benchmark.md`
- `01_protocol/artifact_plan.json`
- `05_figures/legends.md`
- `04_tables/table_captions.md`
- `01_protocol/display_review.json`
- low-cost previews under `01_protocol/prototypes/`

## Hard rules
- Only low-cost prototypes under `01_protocol/prototypes/` are allowed here. No formatted XLSX, Word, `05_figures/out/` builds, or journal-specific TIFF.
- Do not plan a display item you have no result JSON for; percentage claims must preserve numerator, denominator, and source basis (`reference/structural-quality.md`).
- Check clinical labels, counting units, denominators, statistical marks, and distinct missing/zero-event states (`reference/medical-reader-presentation.md`); never imply prespecification or alter counts by renaming units.
- Detailed methods, cohort provenance and general caveats belong in Methods or
  supplementary Methods, not in panels and not automatically in every legend.
- Do not use the literal down-arrow character. Express direction in words outside legends;
  legends themselves describe the display without claiming the direction of a result.
- Do not duplicate the Figure legends section title, a figure identifier, or the descriptive
  legend title between the heading and the first body sentence.

## Close
Run `tools/manuscript/benchmark.py seal` before closing. Do not reduce its protected ranges
or required argument roles after drafting to get a green check; use a justified scoped replan.

```
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "inventory: <F main / T main / F supp / T supp> vs benchmark <range>; legends written"
```



