# Content-Aware Amendments and Selected-Journal Production

Rules for post-freeze presentation revisions, deterministic Office/PDF builds, typed journal formatting (`S20-S24`), and explicit author-copy handoff.

## 1. Preserving Scientific Approval Across Presentation Deltas

- Genuine scientific changes (numbers, denominators, citations, direction/negation, model or design claims) must route back to their owning source stage and renew S19 approval.
- Pure journal-presentation revisions on an already approved/frozen manuscript use `rework.py batch --sealed` (`journal-format` for same-journal formatting/CSL/heading/layout updates; `journal-switch` when changing target journals, which replaces `08_submission/` only without rerunning S05-S19 science).
- When `rework.py check` flags non-trivial wording adaptations under `needs_review` with unchanged facts, inspect before/after text and supply `rework.py check --meaning-review <JSON>` (`files` SHA-256 map, `baseline` SHA-256 map, `verdict: "UNCHANGED_SCIENCE"`, and concrete observations for `population_comparison`, `endpoints_time_units`, `direction_negation_uncertainty`, `methods_claims`, `rendered_displays`).
- Validated presentation deltas append lineage in `.wf/presentation_deltas.json` and create a new immutable release without overwriting prior frozen releases or re-triggering S19 approval. Use `mark --deleted-file <path>` when an authorized file is removed.
- All journal-specific adaptations live in `08_submission/integration/`; never mutate `07_manuscript/` to satisfy one journal's house style.

## 2. Deterministic Builds & Typed Journal Formatting

- Managed DOCX, XLSX, and R PDF/TIFF writers normalize container/ZIP timestamps while preserving clinical content, embedded graphics, and bibliographic metadata.
- Configure sourced journal rules in `08_submission/target_journal.json`:
  - `main_text_headings` (canonical section -> journal heading), `keywords` (`min`, `max`, `separator`), `blinded_main_manuscript`, `spelling` (`US` default for new studies or `UK`), `line_numbers`, and `number_format` (`p_space`, `minus`, `thousands`, `interval`, `leading_zero`).
  - Typed `submission_requirements` enforce verified word/display caps (`<= 100%` of explicit caps passes; near-cap Word vs. portal counting differences emit an advisory check).
- Local bibliography tweaks use `08_submission/integration/csl_patch.json` (`build_docx.py --csl-patch`) verified against real official reference examples via `csl_check.py --docx ... --examples ...`—never edit verified `refs.bib` metadata to fake a style match.
- Build journal reporting checklists (`checklist_docx.py`) only when explicitly mandated by official author instructions, with no internal workspace paths. Use `preview.py --pdf <Word-exported.pdf>` for full-document page contact sheets alongside full-resolution critical-page inspection.

## 3. Stage Pinning & Author Final-Copy Handoff

- Completed stages retain their recorded presentation-gate pin across engine upgrades unless `wf migrate` is invoked; data, reference, numeric, and approval integrity checks always apply.
- If the author explicitly requests to finish minor upload tweaks manually at the end of S24, run `final_copy.py prepare`, place manual edits in `08_submission/final_copy/`, record authorization via `final_copy.py record --edit ... --words '<exact user instruction>'`, run `check`, visually inspect rendered pages, and `finish` (`PASS_AUTHOR_FINAL_COPY` / `AUTHOR_FINAL_COPY_HANDOFF_NOT_SUBMITTED`). Scientific facts, privacy gates, and prior independent review remain strictly enforced.
