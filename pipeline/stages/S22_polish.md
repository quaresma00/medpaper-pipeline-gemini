# S22 - Journal-specific, fact-preserving polish

After wording changes update only affected `08_submission/integration/claim_bindings.json`
entries under `reference/numeric-claims.md`; never alter frozen scientific facts to match prose.

## Purpose
Per-section de-AI, claim-driven (anti-lab-log), and balanced clinical language polishing has ALREADY been completed
when each `.md` was drafted (`S08`, `S09`, `S14`, `S16`, `S17`). **Do NOT re-polish or rewrite
the entire manuscript here** (avoid redundant token spend and numeric drift), and never weaken or delete honest reports of null/unfavorable findings, limitations, or uncertainty. Limit this stage
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
   structure, exact H1 `required_main_sections` (do not demote mandated H1 headings such as `Aim`
   or `Ethics approval` to `##`), and word/reference limits. When trimming main text to meet a
   journal word cap, prioritize moving redundant Methods/secondary Results detail to
   `Supplementary Methods` / Online Resources — never disproportionately strip `Introduction`
   (`section_balance_health` flags Introductions < 350 words, < 10% share, or > 30% shrinkage vs S19). Leave already-clean section prose intact.
3. Keep Keywords immediately after the Abstract. Use the actual selected journal's keyword
   count and final-output separator, already recorded in the target profile. The scientific
   source's 3-6 comma-delimited convention does not override that journal. Preserve the
   explicit References heading and concise Figure legends at the end.
4. Run `tools/text/polish.py diff` and `tools/text/polish.py lint` again. Restore and redo
   any wording edit that loses or adds a number, citation or artifact reference (if wording-only
   edits shifted bound sentences, run `uv run python tools/manuscript/sync_claims.py --layer journal --reanchor`).
5. Reread the complete manuscript and optional supplementary Methods, then record
   `polish_reviewed YES` with a concrete reason. (`polish_log.md` is optional.)

## Outputs
- `08_submission/integration/polish_report.json`

## Hard rules
- Wording only. Never change a number, citekey, artifact reference or conclusion strength.
- Never edit `07_manuscript/full_manuscript.md` or any other frozen scientific-master file to
  meet one journal's requirements. All such presentation changes stay inside
  `08_submission/integration/` and the resulting bundle.
- Do not re-take the snapshot to hide a failed fact-preservation diff.
- Do not add content or an AI-use disclosure during polishing.

## Close
```powershell
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "journal polish complete; facts preserved; abstract/main/reference limits pass; read by eye"
```
