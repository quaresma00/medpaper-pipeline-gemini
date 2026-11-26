# S10 - Build the tables

Follow `reference/numeric-claims.md`: the table builder records source-bound cell mappings in
the existing `07_manuscript/claim_bindings.json`, preserving all existing prose bindings.

## Purpose
Render the planned tables as three-line xlsx files a reader and a reviewer can use.
Generated from result JSONs by code, never retyped.

## Procedure
1. Modularize table builders to avoid monolithic multi-thousand-line files: place shared
   formatting helpers in `project/04_tables/code/tables_common.py`, put each large table
   in its own module (`table1.py`, `table2.py`, ...), and expose `--only Table2` from a thin
   entrypoint `project/04_tables/code/build_tables.py`. Declare each table's `script` in
   `04_tables/manifest.json` so editing one table never invalidates unrelated tables:
   It reads `03_analysis/results/*.json` and `01_protocol/artifact_plan.json`, and writes
   every table with the shared helper (`threeline.py`, which enables `wrap_text=True`,
   auto-row heights, horizontal spacing, landscape fit, and `print_title_rows="1:2"`):

```python
import sys; sys.path.insert(0, "tools")
from tables.threeline import write_table, write_workbook

write_table(
    path="project/04_tables/main/Table1.xlsx",
    sheet="Table 1",
    title="Table 1. Baseline characteristics of the study population.",
    header=["Characteristic", "Group A (n=123)", "Group B (n=456)"],
    rows=[["Age, years, mean (SD)", "62.1 (11.4)", "61.7 (12.0)"]],
    footnotes=[
        "Data are n (%) unless stated otherwise.",
        "Abbreviations: SD, standard deviation; BMI, body mass index.",
    ],
)
```
   These numbers illustrate layout only. In a study the script reads executed results and
   records actual source-bound cells; do not copy example values. Select categorical,
   continuous, regression or outcome-table structure from design/analysis and the benchmark.
   Do not add baseline P values by default or infer summary type from a column's storage type.
   Report exported n (%), mean (SD) or median (IQR), actual missing/available counts and
   denominators as appropriate. Effect labels/interval levels, reference groups, adjustment
   sets and analysis populations must match their actual models; `tables.threeline.p_value`
   supports optional `decimals` or `borderline_three_decimals=True` when preserving borderline
   precision near 0.05 (such as distinguishing `0.049` from `0.050`). S10 formats; it does not
   fit models, run add-on tests or calculate a missing percentage. Follow the optional R
   table route in `reference/r-first.md` only when it improves this project.
2. Layout rules (enforced by the `tables_threeline` gate):
   - Row 1 is the title. Unruled.
   - Exactly three horizontal rules: above the header, below the header, below the last
     data row. No vertical rules. No interior horizontal rules.
   - At least one footnote row beneath the bottom rule.
   - Main tables: one xlsx per table.
   - Supplementary tables: **one** xlsx (`04_tables/supplementary/supplementary_tables.xlsx`)
     with one sheet per table, named exactly as the plan's `sheet` value. Use
     `write_workbook()` for this.
3. Write `project/04_tables/manifest.json`:
```json
{"built_at": "", "built_by": "04_tables/code/build_tables.py",
 "tables": [{"id": "Table 1", "file": "04_tables/main/Table1.xlsx", "sheet": "Table 1",
             "script": "04_tables/code/table1.py", "n_rows": 0, "source_results": ["03_analysis/results/baseline.json"]}]}
```
   - Clinical display labels & de-AI/de-engineering polish: Every table title (`04_tables/table_captions.md` and row 1), column header, row stub, cell value, and footnote must be publication-ready for medical clinicians. Raw column names (`sbp`, `bmi`, `age_yrs`), raw database codes, bare boolean `TRUE`/`FALSE`, bare package columns (`coef`, `p_val`), AI clichés (`delve into`, `underscores`), engineering/workflow jargon (`dataframe`, `script`, `JSON`, `CSV`, `locked protocol`), spelled-out clinical age/window words (`eighteen to sixty-four`, `thirty-day`), internal tier codes (`Tier A/B/C`), repeated `Prefix:` rows (`>=4` times instead of `group_rows`/`indent_rows`), and work-report narration are prohibited and blocked by `display_labels_clinical`. Retain honest null/unfavorable findings and uncertainty in all tables.
4. Run the table builder, scaffold source-bound cell mappings (`sync_claims.py --scaffold-claims`), render official visual previews (`tools/tables/render_preview.py`), and inspect all checks in one pass:
```powershell
uv run python project/04_tables/code/build_tables.py --only Table1
uv run python tools/manuscript/sync_claims.py --scaffold-claims
uv run python tools/tables/render_preview.py --all --changed
uv run python tools/wf.py check --all-checks --only "Table 1"
```
   The builder must support selecting an affected workbook (`--only Table2`).
   A shared supplementary workbook is one rebuild unit; preserve the other sheets' values
   and meaning. A change to one main table must not overwrite other main workbooks.
5. Inspect the rendered previews in `project/04_tables/previews/` (`render_preview.py` uses
   Excel/pdftoppm or deterministic Python booktabs rendering + layout QC in
   `04_tables/qc/table_qc_report.json` with zero `temp/` residue — do NOT write ad-hoc COM
   scripts in `project/temp/`). Check clipping, wrapping, column widths, row heights, title
   and header hierarchy (`group_rows`/`indent_rows` with empty statistic cells on group rows),
   adjacent right/left column gaps, multi-page header repeats, footnotes, units, decimal
   precision, missing/zero-event symbols (`NE (0/N)` vs `-`), and page usability. Bind the
   saved workbook AND rendered preview PNG in `01_protocol/display_review.json.final_reviews`
   (`reference/project-benchmarking.md`, `reference/medical-reader-presentation.md`), using
   `uv run python tools/manuscript/readiness.py sync-hashes` to sync objective hashes (drifted
   files reset to `PENDING_REINSPECTION` until genuinely re-inspected). Fix the generating
   script, regenerate only that affected table, and visually inspect again; never hand-edit a
   generated value.
   - Table-figure estimator parity: Ensure every comparison shown in both a table and a figure uses the exact same statistical estimator and sparse-cell handling (never Wald in one display and Haldane/penalized in the other).
6. After all workbooks pass visual review and `final_reviews` verdicts are `PASS`, record the gate:
```
uv run python tools/wf.py decide tables_visually_confirmed YES --why "<workbooks/sheets inspected and defects corrected>"
```
7. Delete scratch files from `project/temp/`.

## Outputs
- `04_tables/code/build_tables.py`
- `04_tables/manifest.json`
- (plus the xlsx files declared in the artifact plan)

## Hard rules
- A table is a reader-facing object, not an analysis dump. No console output or
  paragraph-length cells. Clinically relevant discrimination, calibration, diagnostic
  accuracy or sensitivity results remain when required by the study design; hide engineering
  logs and redundant model-debugging output, not necessary scientific evidence.
  The writer rejects body cells over 300 characters. A 1500-character footnote block is an
  advisory prompt to remove unnecessary detail, not permission to truncate essential notes.
- Every numeric cell must trace to `03_analysis/results/*.json` (gate:
  `numbers_have_provenance source=tables`), and for 1.27+ the merged column-header stack,
  interior bold group header, and row label must agree with the bound fact's `context`
  (group/comparison, adjusted vs unadjusted model, population, timepoint, and effect scale).
  Do not retype from the Results prose.
- Titles are self-contained and short. Footnotes carry abbreviations, units and tests.
- Follow S07's abbreviation policy on the first build. Use the central glossary when planned,
  retaining only the local decoding information needed to understand the table. S17 checks
  consistency; regenerate only a table with an actual newly discovered defect.
- Add a necessary table through a scoped S07-owned plan correction and its true consumers;
  stay at the revision checkpoint rather than looping or rebuilding unrelated tables.
- Structural checks alone are insufficient; both `display_review.json.final_reviews` (bound to
  current workbook + preview hashes) and the `tables_visually_confirmed` decision are mandatory
  before `S11b` / `S08` / `S09`. Percentage claims must bind numerator, denominator, and source
  percentage basis (`reference/structural-quality.md`); keep source/counting-unit identities
  accurate without renaming records as patients.

## Close
```
uv run python tools/wf.py advance --note "K main + M supp tables built; all values traced to results JSON"
```

