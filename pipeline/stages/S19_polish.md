# S19 - Target journal adaptation and academic-English polish in submission sandbox

## Purpose
Adapt the finalized, frozen canonical manuscript to the chosen target journal's specific guidelines
(word limits, abstract subheadings, display item rules, spelling variants) and apply de-AI / academic-English
polishing strictly inside the **submission sandbox (`08_submission/adapted_manuscript/`)**.

**Absolute Isolation Rule**: The canonical base manuscript in `07_manuscript/` is cryptographically frozen
and must remain 100% untouched. All journal-specific alterations, text trims, and custom formatting
must be isolated inside `08_submission/`.

## Procedure

1. **Initialize the Journal Adaptation Sandbox**:
   Read the frozen canonical files from `project/07_manuscript/` as read-only templates.
   Derive the working adaptation files into `project/08_submission/adapted_manuscript/`:
   - `adapted_title_page.md`
   - `adapted_abstract.md`
   - `adapted_introduction.md`
   - `adapted_methods.md`
   - `adapted_results.md`
   - `adapted_discussion.md`
   - `adapted_statements.md`

2. **Remove AI Tells and Polish English in Sandbox**:
   Review the sandbox files to strip machine-generated tells:
   - Inflated verbs (`utilize`/`leverage` -> `use`)
   - Empty intensifiers ("plays a crucial role", "paves the way", "game-changer")
   - Framing filler ("it is worth noting that", "in the realm of")
   - Marketing register ("cutting-edge", "seamlessly")
   - Varied syntax, eliminate robotic triple-lists and unnecessary hedges.

3. **Conform to Journal Constraints**:
   Re-read `08_submission/guidelines_extract.md`:
   - **Word Limits**: If main text exceeds the journal's cap, trim discursive text in sandbox files; if vital details must be cut, move them into `supplementary_methods.md` (which routes to `supplementary_materials.docx`).
   - **Abstract Structure**: Adapt abstract headings to match journal expectations (e.g. Background/Methods/Results/Conclusions vs Objective/Methods/Findings/Interpretation).
   - **Spelling Variant**: Consistently apply American or British English per journal guidelines.

4. **Assemble the Journal-Adapted Manuscript**:
   Run `render_package.py` or assemble the sandbox files into `project/08_submission/adapted_manuscript/manuscript_assembled.md`.

5. **Log and Verify**:
   - Write `project/08_submission/polish_report.json` and `project/08_submission/polish_log.md`.
   - Ensure numbers and citations in the adapted text remain 100% truthful to the underlying results JSON and reference library.
   - Record user review decision:
   ```bash
   uv run python tools/wf.py decide polish_reviewed YES --why "adapted to <journal> limits; base manuscript untouched; facts preserved"
   ```

## Outputs
- `08_submission/polish_report.json`
- `08_submission/polish_log.md`
- `08_submission/adapted_manuscript/manuscript_assembled.md`

## Hard rules
- **Zero base manuscript mutation**: Never modify any file under `07_manuscript/` or foundational folders (`01`-`06`). The `base_manuscript_untouched` gate enforces this strictly.
- **Wording and conciseness only**: Never alter a numeric finding or invent facts to meet word limits.
- **Full resubmission agility**: If the target journal rejects, the frozen base manuscript remains intact; simply return to S18 and adapt for the next journal without rework.

## Close
```bash
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "journal adaptation completed in sandbox; 07_manuscript strictly untouched; limits met"
```
