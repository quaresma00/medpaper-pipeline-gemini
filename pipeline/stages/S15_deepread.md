# S15 - Deep-read the papers that carry the Discussion

Registration also checks the acquired article's own identity. Do not accept a DOI found
in a bibliography as proof. For PDF/title-only cases, inspect the actual first page and
get explicit reader confirmation; `fulltext.py confirm --citekey KEY --confirmed-by NAME
--identity-note "concrete title/authors/identifier evidence"` records that confirmation,
not an automatic AI verdict. Wrong identities block; never invent user confirmation.

## Purpose
Read the sources needed for real method/result comparisons and competing explanations.
Reuse the S07 full texts already read; obtain further sources only for unresolved arguments.
There is no fixed deep-read quantity; substantive coverage, source identity and notes matter.

## Procedure
1. Select the papers that the Discussion genuinely depends on. Typically:
   - the closest prior study on the same question (whatever the direction of its result),
   - the study that most disagrees with your finding,
   - the methodological reference your approach stands on,
   - the largest or most authoritative study in the area,
   - the paper a reviewer will ask "why does your result differ from this one".
   Selection is by argumentative need, not by impact factor.
2. Fetch full text across automated routes (Europe PMC / PMC, Unpaywall, OpenAlex, plus automatic DOI-verified Sci-Hub mirror fallback). Any mirror presenting a CAPTCHA or anti-bot gate is skipped automatically without evasion:
```
uv run python tools/pubmed/fulltext.py fetch --citekey smith2023 --citekey lee2021
```
   Retrieved files are saved to `06_refs/fulltext/` and recorded in `06_refs/fulltext/retrieval_manifest.json`.
3. If `fulltext.py fetch` leaves missing items (exit code 2), STOP and show `project/.wf/pending_fulltext_requests.md` (citekey, Title, PMID, DOI link) directly to the user so they can provide the local PDF(s) to register:
```
uv run python tools/pubmed/fulltext.py register --citekey smith2023 --file "C:\path\paper.pdf" --access authorized --source-url "https://doi.org/..." --route user-provided --authorization-note "User-supplied full-text PDF"
```
   Never substitute a paywalled abstract or landing link for a required deep read. Once registered, complete structured notes in `06_refs/deepread/<citekey>.md`.
4. Read each registered local full text and write structured notes to
   `06_refs/deepread/<citekey>.md`:
```markdown
# <citekey> - <short title>
## Design and population
## What they did differently from us
## Their key numbers
## How this supports or contradicts our finding
## What a reviewer would take from this
```
   Notes must be substantive; the gate rejects notes under 400 characters as evidence that
   no real read happened.
5. Index them in `project/06_refs/deepread/deepread_index.json`:
```json
{"selected": [{"citekey": "", "pmid": "", "reason": "why this paper carries part of the Discussion",
  "access": "oa|authorized", "fulltext": "06_refs/fulltext/<file>.pdf",
  "notes": "06_refs/deepread/<citekey>.md"}]}
```
6. Update `03_analysis/notes.md` -> `Discussion points` with what the deep reads changed.
   If a deep read overturned an assumption, that is the most valuable output of this stage.

## Outputs
- `06_refs/deepread/deepread_index.json`
- (plus per-paper notes and fetched full texts)

## Hard rules
- Every selected citekey must already be in `library.json`.
- Every selected file must have a matching retrieval-manifest record and unchanged hash.
- Every selection needs a recorded reason. "Highly cited" is not a reason.
- If a paper turns out not to matter, remove it from the index and record why - the gate at
  S16 requires every indexed paper to be cited in the Discussion.

## Close
```
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "<n> deep reads: <citekeys>; changed my view on: <...>"
```
