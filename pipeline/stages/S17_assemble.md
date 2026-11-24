# S17 - Select the title and assemble the complete manuscript

Bind numeric Abstract findings under `reference/numeric-claims.md`. The assembler carries
matching Abstract/Results bindings to full-manuscript mappings without printing them in prose.

Read the Abstract/title section of `reference/medical-writing.md` before distilling the
accepted paper. Reuse the existing close-paper observations.

## Purpose
Create the first complete paper before asking for author or affiliation details. The paper
must be readable as one medical-journal manuscript and becomes the canonical scientific
source for review, user editing, polishing and packaging.

## Procedure
1. Read the protocol, final results, finished sections, artifact plan, table captions and
   figure legends. Generate several title candidates internally and select the single best
   one without asking the user. Score for design accuracy, population/exposure/outcome
   specificity, searchability, brevity and freedom from causal or novelty overclaim. Write
   only the selected title to `project/07_manuscript/title.md` as one level-1 heading.
2. Write `project/07_manuscript/abstract.md` after all scientific sections are final. Use
   the structure most appropriate to the design. Every number must already occur in a
   results JSON and every conclusion must agree with the Discussion.
3. Write `project/07_manuscript/keywords.md` as one line:
   `Keywords: term 1, term 2, term 3`. Use 3-6 specific, MeSH-aligned terms where suitable.
   Commas are the only separators: no slash, semicolon, ampersand or conjunction padding.
4. Assemble the exact order with the deterministic tool:
   First, verify S07's abbreviation policy was followed. When lists exceed eight unique terms,
   any local list exceeds 50 words, or the lists visibly dominate captions, define the terms
   once in optional `07_manuscript/statements.md` under `# Declarations and Statements`
   and `## Abbreviations`. These thresholds are workflow defaults, not journal standards.
   Use one `term, full expansion` entry per line or semicolon-separated entries, preserving
   mixed-case names such as eGFR. Remove the corresponding `Abbreviations:` blocks from
   legends/captions and the table-building source. Add a short pointer to the central list
   where needed; keep units, symbol meanings and error-bar definitions local. This should
   already be reflected in the first table build; regenerate and visually recheck only an
   actually defective table, not every table as a scheduled second pass. No author/admin details or blank declaration
   sections are needed here. Then run:
```
uv run python tools/manuscript/assemble.py
```
   It writes `project/07_manuscript/full_manuscript.md` in this order: selected title,
   Abstract, Keywords, Introduction, Methods, Results, Discussion, References, Figure
   legends, with the optional Declarations and Statements section between Discussion and
   References. Supplementary Methods remains a separate file. The References heading must be
   present even though Pandoc later expands the bibliography beneath it. The assembler and
   gate require exactly one `Figure legends` section title and one identifier per figure;
   never repeat `Figure N.` at the start of the corresponding legend body.
5. Read the assembled file from beginning to end. Fix the source section, abstract,
   keywords or legend file and re-run the assembler; do not hand-splice the first build.
   The S17 gate runs `assemble.py --check`, so omissions or manual divergence fail even
   when the visible heading structure still looks valid.

## Outputs
- `07_manuscript/title.md`
- `07_manuscript/abstract.md`
- `07_manuscript/keywords.md`
- `07_manuscript/full_manuscript.md`
- `07_manuscript/statements.md` (optional abbreviation list only; administrative facts wait)

## Hard rules
- Do not ask for or invent authors, affiliations, ORCIDs, grants or correspondence details.
- Do not present title choices. Select the strongest accurate title automatically.
- Keywords appear immediately after the Abstract and nowhere before it.
- `References` and `Figure legends` are explicit level-1 sections; figure legends are the
  final manuscript section.
- `full_manuscript.md` is the canonical assembled view after this stage. Later scientific or
  human edits return through `tools/rework.py` to the owning component source, then rebuild
  this file; never patch it as a detached manuscript.
- Immediately polish `07_manuscript/abstract.md` via `polish.py section --file project/07_manuscript/abstract.md --snapshot` / `--verify` BEFORE assembling (clear finding-first prose without work-report narration, while accurately retaining null/unfavorable outcomes, limitations, and appropriate uncertainty), and ensure total citations satisfy `literature_sufficiency`.

## Close
Read the complete assembled manuscript alongside rendered table previews and figure PNGs to resolve any remaining cross-reference, abbreviation, or clinical-label defects before independent review at S18. If candidate-pool references remain uncited in `06_refs/library.json`, archive them cleanly with `uv run python tools/pubmed/build_library.py --archive-uncited`.

```powershell
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "full manuscript assembled; selected title: <title>; keywords=<n>; figure legends=<n>"
```


