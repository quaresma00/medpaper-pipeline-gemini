# Data Registration, Producer Replay, and Review Isolation

Operational rules for external datasets (S04-S06), reproducible statistical replay, engine integrity, and isolated review rounds.

## 1. Zero-Copy External Data Registration (`data_sources.py`)

When the user supplies an existing local dataset file or folder, register that exact authorized path instead of copying gigabytes into `project/`:

```powershell
uv run python tools/data_sources.py add --name local --path "<authorized-absolute-path>" --why-file "<utf8-request-file>"
uv run python tools/data_sources.py show
```

- Stored in project-local `.wf/data_sources.json` (no global cross-study state; path traversal, escaping symlinks, and parent-workspace wildcards are rejected).
- Python scripts read via `from analysis.datasources import open_data, source_path` (`data:local/<relpath>`, read-only); R scripts source `tools/analysis/results.R` and call `medpaper_data_path("data:local/<relpath>")`. Declare the same `data:local/...` logical paths in result JSON `inputs`.
- `data_manifest.py sync` hashes registered inventories alongside `03_data/raw/`. Registration never waives full-census row counts, pagination receipts, exclusion tracking, or spotchecks; never mutate or hard-link original datasets.

## 2. Scoped Producer Replay (`analysis/reproduce.py`)

- `uv run python tools/analysis/reproduce.py replay` reruns only producers with missing or stale input/code hashes; downstream scripts consume verified upstream outputs.
- Scripts and small configs run inside `.wf/replay_sandboxes/run_*/` (`--copy-limit-mb 200` default) while reading registered `data:` datasets in place with zero dataset byte copying.
- One replay runs at a time per project with UTF-8 logs under `.wf/processes/` and bounded stderr heartbeats (`--timeout 3600` default). Batch code edits before replaying; use `reproduce.py cleanup` (`--apply`) only for dead crash remnants.

## 3. Engine Baseline & Medical Scope

- Packaged releases carry `.medpaper-engine.json` hashes; study executors must never edit `tools/`, `pipeline/`, `reference/`, or `.wf/` engine state to bypass a gate.
- Keep internal protocol v1 -> final workflow history under `01_protocol/`; report actual study methods, real pre-specified vs. post-hoc timing, and clinical limitations in the manuscript without turning workflow mechanics into Methods prose.
- Author each section cleanly with immediate clinical de-AI/anti-defensive polish (`polish.py section`); S22 harmonizes the journal-adapted copy rather than deferring all medical-language cleanup to the end.

## 4. Review Isolation & Optional Proposal Reuse

- The independent `research` subagent is read-only across study inputs and writes (or returns via `review_round.py ingest`) only the active round's report.
- Novel reviewer analyses are evaluated for scientific validity and clinical impact rather than executed blindly.
- When an author previously declined an optional methodological suggestion and a later review round repeats the exact same optional proposal on unchanged scientific files, both findings may declare `optional_method: true`, matching `proposal_id`, `proposal_text`, and SHA-256 `proposal_basis`, allowing `--author-decisions` to reference `reuse_from: {scope, round, finding}` without re-prompting the author.

## 5. Pre-Build Change Classification

Before running full Word/PDF rebuilds during late revisions, preview dependencies with `rework.py preview --plan ...` and classify actual edits via `rework.py classify` (exit `0` presentation, `3` meaning review needed, `2` scientific change) so presentation fixes never trigger unnecessary scientific rewinds.
