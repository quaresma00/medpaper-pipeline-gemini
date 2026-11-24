# Source-Aligned Incremental Validation and Managed Rebuild

Rules for separating scientific master files from journal integration sources, tracking build receipts, relocating prose/displays safely, and running `wf rebuild`.

## 1. Scientific Master vs. Journal Integration

- Scientific truth lives in frozen `01_protocol/`, `03_data/`, `05_figures/`, `04_tables/`, and `07_manuscript/`.
- Journal layout lives in `08_submission/integration/` (derived manuscript, optional derived `artifact_plan.json`, and `bundle/manifest.json`). Display renumbering, main-to-supplement moves, and journal heading/legend splits happen only in `08_submission/integration/`.
- Managed builders record exact input/output hashes, entrypoints, and parameters in `.wf/build_receipts.json`. Every manifest upload declares `source_files` and `build_entrypoint` (plus `legend_scope` in `main|supp|all` when legends are split).
- When a revision uncovers a downstream derived file inside `08_submission/`, register it via `rework.py depend --input ... --output ... --why ...`, and record inspected/modified sources with `rework.py mark --changed-file` / `--checked-file` (or `--auto-changed`).

## 2. Explicit Presentation Migration (`presentation_map.json`)

- Before starting a new polish/adaptation round, run `polish.py snapshot --new-round` to store a baseline under `.wf/polish_snapshots/`.
- When moving prose passages or renumbering displays across integration files, declare `08_submission/integration/presentation_map.json` (`snapshot_id`, optional `renumbering` map, `moves` with `from`/`to`/`text`, and optional hash-bound `additions` drawn strictly from already-frozen scientific Methods sources). Package-level numerical claims, P values, and citation identities must be preserved intact.

## 3. Final Word Chain & `wf rebuild`

- Standard S23/S24 DOCX pipeline: freeze sources -> `build_docx.py build` -> layout repair if needed -> `build_docx.py finalize` -> render final pages -> `package_content.py capture` -> `submission_fields.py` & `submission_qc.py measure`.
- Postprocessing stages edits safely, disables Word picture compression, verifies content equivalence across body, headers, footnotes, tables, and media, and ignores `~$` Office lock files.
- After sealing an S24 source fix (or during S23 updates), preview stale targets with `uv run python tools/wf.py rebuild --dry-run` and execute `uv run python tools/wf.py rebuild`. It rebuilds only stale managed DOCX outputs in dependency order and refreshes portal counts/measured QC—never bypassing visual QA, independent review, or user freeze approval.
- Query resolved numeric facts concisely via `readiness.py facts` (`--fact-id`, `--fields`, `--limit`; full dump in `.wf/resolved_facts.json`).

## 4. Same-Round Independent Revalidation (`review_round.py`)

- When a scientific defect found during S18 or S24 requires independent re-checking within the same open review round, run `uv run python tools/review_round.py prepare-revalidation --scope manuscript|package`, pass the updated neutral context and hashes to the read-only `research` subagent, and attach its reply via `--revalidation` (using `review_round.py ingest --from-file <reply.md>` if the subagent returns `<<<REPORT>>>...<<<END>>>` inline).
- Typed word caps in `target_journal.json` may declare `basis: "explicit" | "page_derived" | "estimated"` (with a `>= 20`-char `derivation` when non-explicit); explicit journal caps remain hard limits.
