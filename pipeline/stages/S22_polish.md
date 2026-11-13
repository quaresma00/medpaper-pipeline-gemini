# S22 - Journal-specific, fact-preserving polish

After wording changes update only affected `08_submission/integration/claim_bindings.json`
entries under `reference/numeric-claims.md`; never alter frozen scientific facts to match prose.

## Purpose
Per-section de-AI, anti-defensive, and clinical language polishing has ALREADY been completed
when each `.md` was drafted (`S08`, `S09`, `S14`, `S16`, `S17`). **Do NOT re-polish or rewrite
the entire manuscript here** (avoid redundant token spend and numeric drift). Limit this stage
strictly to cross-section consistency (spelling, abbreviation first-definitions, section seam
transitions), target-journal word/heading/abstract limits, and immutable fact preservation.

## Procedure
1. Snapshot before editing:
```
uv run python tools/text/polish.py snapshot
```
   The tool snapshots `08_submission/integration/full_manuscript.md` plus its supplementary
   Methods and administrative files. It never snapshots or edits the frozen S19 sources.
2. Run `tools/text/polish.py lint` to catch ONLY cross-section house-style issues (`lint_spelling`,
   `lint_abbreviations`, `P`/`p` case consistency, numeric range dashes), check seam transitions
   between assembled sections, and apply only the target journal's required spelling, abstract
   structure, and word/reference limits. Leave already-clean section prose intact.
3. Keep Keywords immediately after the Abstract. Use the actual selected journal's keyword
   count and final-output separator, already recorded in the target profile. The scientific
   source's 3-6 comma-delimited convention does not override that journal. Preserve the
   explicit References heading and concise Figure legends at the end.
4. Run `tools/text/polish.py diff` and `tools/text/polish.py lint` again. Restore and redo
   any wording edit that loses or adds a number, citation or artifact reference.
5. Keep the existing `polish_log.md` concise: actual changes, retained context-dependent
   terminology and substantive reading findings. Do not write a justification per harmless word.
   New lint reports bind current sources, linter and exceptions; rerun only this cheap check
   when those inputs change, never analysis or an unrelated Word build.
6. Reread the complete manuscript and optional supplementary Methods, then record
   `polish_reviewed YES` with a concrete reason.

## Outputs
- `08_submission/integration/polish_report.json`
- `08_submission/integration/polish_log.md`

## Hard rules
- Wording only. Never change a number, citekey, artifact reference or conclusion strength.
- Never edit `07_manuscript/full_manuscript.md` or any other frozen scientific-master file to
  meet one journal's requirements. All such presentation changes stay inside
  `08_submission/integration/` and the resulting bundle.
- Do not re-take the snapshot to hide a failed fact-preservation diff.
- Do not add content or an AI-use disclosure during polishing.

## Close
Complete journal preproduction executor acceptance from the same-journal benchmark and actual
integration sources: `benchmark.py accept --layer journal --review <findings.json>`.
Resolve Methods/Discussion organization, declaration order, main/supp legends and sourced
limits before expensive Word. Use explicit prototype/source_file paths for unbuilt journal
displays, never pretend a future output was inspected. Final-upload acceptance remains S23.
Note: Per-section de-AI, anti-defensive, and clinical polish already runs at drafting (`S08`, `S09`, `S14`, `S16`, `S17`); `S22` performs whole-manuscript harmonization, house style, and immutable fact preservation.

```
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "journal polish complete; facts preserved; abstract/main/reference limits pass; read by eye"
```
