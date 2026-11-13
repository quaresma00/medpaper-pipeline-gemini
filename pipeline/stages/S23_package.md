# S23 - Build and verify only actual journal uploads

Follow `reference/journal-adaptation.md`: verify the sealed guide context before builds. Use selected CSL/official template assets, inspect manual guide clauses in the same rendered QA pass, and run submission measurements once. Required clauses without current evidence remain pending; a built Word is not compliance.

Freeze content, author/blinding facts, official rules, and exact uploads before expensive builds. Keep one source/dependency path and compose from the real build entrypoint. Resolve routine medical prose, display meaning, and reference coverage before building. Build DOCX/supplements/figures once, then correct only affected dependants.

Use the managed R renderer and per-figure QC sequentially. Pending jobs or Excel locks are incomplete work. Logs belong in `.wf/processes` or `.wf/logs`, never inside `temp/`.

Apply layout repair -> final XML cleanup -> final rendering -> visible-content baseline and measured portal fields (`submission_fields.py`). Inspect overview + critical pages, black text, journal fonts, no soft breaks/hyperlinks, three-line tables, concise legends, separate supplementary tables, and sourced `line_numbers`.

Non-blinded `manuscript.docx` places single-source authors on page 1 (separate `title_page.docx` only if double-blind or quoted in guidelines); upload figures separately (legends at end), put tables one/page after `References`, and name supplements `Supplemental_File_<N>_<Description>.<ext>`. Review `portal_discrepancies_and_warnings` against the live portal UI. Only manifest-listed uploads enter the `<Journal_Slug>_<YYYYMMDD_HHMMSS>` release (never raw ZIPs, previews, locks, or unrequested AI-use disclosures). Follow scoped revision rules for changes.

## Full procedure, read once when needed
`reference/stage_details/S23_package.md` (`tools/wf.py card S23_package --details`).
On first execution read the detailed procedure; later corrections go directly to affected owner rules. After compaction run `tools/wf.py handoff`.

## Outputs
- Journal-requested reporting checklist only when explicitly required in official instructions.
- `08_submission/cover_letter.md`, `evidence/SUBMISSION_CHECKLIST.md`, `portal_fields.json` (with `portal_discrepancies_and_warnings`)
- `08_submission/bundle/manifest.json`, `package_content_baseline.json`, `submission_qc.md`
- Journal-required Word, figure, table, and `Supplemental_File_<N>_<Description>` uploads

## Close
Run `tools/wf.py check` before `tools/wf.py advance`. Stages are not turn boundaries; review stages require explicit author approval.
