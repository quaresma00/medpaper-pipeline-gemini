# Source-bound numeric claims, proportions, and figure annotations

Use at S05/S06 when exporting results and at S09/S10/S11/S16/S17/S22 when binding prose, tables, and figure annotations. Never fabricate numbers or edit result JSON manually; fix and re-run the producing script.

## 1. Executed `numeric_facts` catalog (`01_protocol/study_facts.json`)

Each reportable finding in `03_analysis/results/*.json` exports a structured object with `context` (`outcome`, `population`, `comparison`, `model`, `timepoint`, `unit`, `denominator`, optional `percentage_basis` / `percentage_kind` / non-95 `interval_level`) and named `values` (`estimate`, `ci_low`, `ci_high`, `p_value`, `n`, etc.). Register pointers in `01_protocol/study_facts.json`:

```json
{
  "numeric_facts": {
    "mortality_primary": {
      "source": "03_analysis/results/primary.json",
      "pointer": "/reported/mortality_primary",
      "context": {
        "outcome": "all-cause mortality",
        "population": "eligible adult cohort",
        "comparison": "exposed versus unexposed",
        "model": "multivariable Cox proportional hazards model",
        "timepoint": "24-month follow-up",
        "unit": "hazard ratio",
        "denominator": "200 patients",
        "percentage_basis": "200 eligible adults followed for 24 months"
      }
    }
  }
}
```

Use `uv run python tools/manuscript/readiness.py facts` to inspect resolved facts and fingerprints without loading large result files.

## 2. Prose claim bindings (`07_manuscript/claim_bindings.json`)

Every own-study numeric finding in `results.md`, `abstract.md`, and `discussion.md` requires a `claims` entry (`path`, exact sentence `text` containing the outcome label, `fact_ids`, optional `section` / 1-based `occurrence` for repeated text, `proportions` when percentages appear, and `context_evidence` keyed by `fact_ids`). Cited external-literature numbers in `introduction.md`/`discussion.md` belong in `source_claims` (`citekey`, `fulltext`, `sha256`, `locator`, `excerpt`, `support`).

- **Controlled effect scales & CI levels**: `claims.py` enforces exact measure-family agreement (`HR`/`aHR`, `OR`/`aOR`, `RR`/`aRR`, `IRR`, `RD`, `MD`, `SMD`, `AUC`, `β`, `ΔRMST`, `GMR`, `PPV`/`NPV`, `NRI`/`IDI`, `I²`, `IVW`; lowercase `"or"` is never misread as `OR`) and non-95% CI agreement. Standard clinical units/stagings (`1.73 m²`, `TNM`, `ECOG`, `NYHA`, `CHA2DS2-VASc`, `(SMQ) 20000107`) are automatically scrubbed.
- **Concise context observations**: In `context_evidence[fact_id].observations` (`population`, `comparison`, `model`, `timepoint`, optional `unit`):
  - Pass a concise clinical phrase present in `text` (e.g. `"multivariable Cox model"` automatically matches `"multivariable Cox proportional hazards model..."` as long as no conflicting exported pole/adjustment exists);
  - Or inherit lead-in context from earlier in the same section via `{"mode": "literal", "scope": "section", "quote": "<short lead-in phrase>"}`;
  - Reserve `{"mode": "read_back", "reviewer": "executor", "scope": "claim"|"section", "quote": "...", "interpretation": "<>=30 chars>", "reason": "<>=60 chars>"}` only for genuinely non-literal paraphrases.
- **Fast fingerprint sync & wording-only re-anchor**: After de-AI polishing or British/American spelling adjustments that preserve the exact numeric multiset, run:
  ```powershell
  uv run python tools/manuscript/sync_claims.py --reanchor
  ```
  (`--layer journal` for `08_submission/integration/claim_bindings.json`). `assemble.py` automatically propagates component bindings to `07_manuscript/full_manuscript.md`.

## 3. S10 table-cell & denominator bindings

Append worksheet cell bindings (`path`, `sheet`, `cell`, exact `text`, `fact_ids`, `label_cells`, and `proportions`) in `build_tables.py`:
- Header stacks, row-group banners, and `label_cells` are cross-checked against `fact.context` to block column swaps, `HR`/`OR`/`RR` mismatches, and `adjusted` vs `unadjusted` mix-ups.
- Count percentages (`64.2%` or `102 (64.2)` under an `n (%)` header) require `proportions: [{"fact_id": "...", "numerator_key": "...", "denominator_key": "...", "reported": "64.2%"}]` (also supporting `percentage_kind` = `weighted_survey`, `survival_km`, `cif`, `pooled_mi`, `measurement`, or `percentage_point_difference`).
- Documented protocol constants in non-result headers/stubs/footnotes may use `03_analysis/results/number_allowlist.tsv` (`token \t constant \t source_path \t reason`) or `kind: "unit_scale"` for `per N` rate headers—never for result-body cells.

## 4. S11 figure statistical annotation bindings

Bind every explicit statistical label rendered inside a figure (`HR`/`OR`/`RR`, `CI`, `P = ...`, `n = ...`, `AUC`) under top-level `figure_annotations` (`figure_id`, `label_id`, exact rendered `text`, `fact_id`, `source`, `pointer`, and `fields: [{"field": "estimate", "shown": "1.42", "digits": 2}, ...]`), maintaining estimator parity between tables and figures.
