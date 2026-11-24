# S12 - Reconcile rendered artifacts against Methods and Results

## Purpose
Verify 100% alignment between drafted `Methods`/`Results` prose and the audited tables/figures (`S10`–`S11b`): every planned item is cited in order, every number cited alongside `Table N` exists in that table, and legends accurately decode rendered panels.

## Procedure
1. Generate the automated artifact-prose cross-check report:
```powershell
uv run python tools/manuscript/reconcile.py
```
   This runs `artifact_refs_consistent`, `display_numbering_consistent`, and `numbers_cross_match` and writes `project/07_manuscript/reconciliation.md` with exact citation line numbers.
2. Visually spot-check any flagged item against the actual `.xlsx` / rendered `.png` and `05_figures/legends.md` (panel letters, group order, axis units, error bars, symbols).
3. Fix the true upstream source of any discrepancy (edit `results.md` + `sync_claims.py --reanchor` if prose misquoted a valid table, or route through `S05`/`S10` if analysis changed—never patch numbers ad hoc), then re-run `reconcile.py`.

## Outputs
- `07_manuscript/reconciliation.md`

## Close
```powershell
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "reconciled <n> display items; all prose citations and table values verified"
```
