# S18 - Journal selection by acceptance probability, then the real guidelines

## Purpose
Select the target SCIE journal based on the peer review report from S17. The primary
objective is **maximizing acceptance probability** (lower-impact SCIE venues like Q3/Q4
with IF 1–3 are fully acceptable). **The AI recommends candidates; the user makes the final choice.**
Then fetch the live author instructions instead of recalling them.

## This stage needs the user
**The AI is strictly prohibited from choosing the target journal autonomously.**
The AI must present a structured shortlist of 3–5 high-acceptance SCIE candidate journals to
the user in the chat interface, and pause until the user explicitly selects one (or provides
an alternative target).

## Procedure
1. Read the finished manuscript and `project/07_manuscript/review_report.md` first. The
   shortlist must be informed by the peer review report's recommended journal profile,
   design strength, sample size, novelty, and geographic generalisability.
   **Target requirement**: Must be **SCIE-indexed**. Lower-impact journals (Q3/Q4, IF 1–3)
   are fully acceptable; the governing criterion is **high acceptance probability** and
   rapid, reliable editorial turnaround.
2. Search for candidate venues. Look for journals that recently published work of the same
   design and scale on adjacent questions - that is the strongest signal a paper of this
   type is in scope:
```bash
uv run python tools/pubmed/client.py search --query "<topic> <design>" --retmax 100 --journals
```
   This reports the journal distribution across retrieved hits. Use it, plus the journals
   already in `library.json`, as the candidate pool.
3. Write `project/08_submission/journal_shortlist.md` with headings
   `Ranking basis`, `Shortlist`, `Reject-fallback cascade`.
   Provide 3 to 5 candidate SCIE journals. For each candidate give:
   - Journal title, publisher, verified SCIE indexing status;
   - Impact factor, JCR quartile;
   - Scope fit in one sentence, evidence of publishing similar designs (cite retrieved papers);
   - Realistic acceptance odds with specific rationale (prioritising high-acceptance venues);
   - APC (open access cost) and average time to first decision;
   - Main potential rejection risk.
   Rank strictly by **acceptance probability x scope fit**.
   `Reject-fallback cascade`: if #1 rejects, where next, and what would have to change.
4. **Present the candidate shortlist to the user in the chat conversation and wait.**
   Do NOT choose a journal autonomously. Do NOT advance this stage without user selection.
   Wait for the user to confirm their selection.
5. Once the user makes the choice, fetch the actual author instructions from the journal's
   official website, snapshot the raw page under `project/08_submission/cache/`, and write
   `project/08_submission/target_journal.json`:
```json
{"journal": "<Chosen Journal>", "issn": "", "publisher": "", "scie_indexed": true,
 "guidelines_url": "", "guidelines_fetched_at": "", "chosen_by_user": true}
```
6. Write `project/08_submission/guidelines_extract.md`. It must quote the exact
   constraints, include the source URL, and cover at minimum:
   `Word limits`, `Reference style`, `Figure` requirements (format, resolution, colour
   mode, dimensions), `Table` requirements, `Required statements`, `Submission items`.
   Add abstract structure, reference count caps, supplementary file rules, cover letter
   expectations, and any reporting-checklist the journal mandates.
7. Reconcile the manuscript against the guidelines and record the deltas: word counts over
   limit, too many references, figure count, abstract headings that differ, missing
   statements. Fix what is mechanical; raise what needs a decision.

## Outputs
- `08_submission/journal_shortlist.md`
- `08_submission/target_journal.json`
- `08_submission/guidelines_extract.md`
- (plus the raw snapshot under `08_submission/cache/`)

## Hard rules
- Never state a journal's word limit, reference style, APC or turnaround time from memory.
  Fetch it, snapshot it, quote it.
- Do not rank by impact factor or quartile. A high-acceptance Q3/Q4 journal is prioritized
  over an over-ambitious Q1 journal with high rejection rates.
- Verify SCIE indexing rather than assuming; flag predatory or questionable venues.
- **The user MUST choose the journal.** The agent must never select the journal itself.
- **Base Manuscript Read-Only**: The frozen canonical base files under `01_protocol/` through `07_manuscript/` must remain strictly untouched. The `base_manuscript_untouched` gate enforces zero modifications.

## Close
Mechanical deltas (word counts, spelling variant, abstract headings, reference caps) are
fixed in the next stage, S19, which is a single polish pass already aimed at this journal.
Record what needs fixing rather than fixing it here.

```bash
uv run python tools/wf.py decide journal_chosen "<journal name>" --why "<the user's choice and the acceptance-odds reasoning behind the ranking>"
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "target: <journal>; guidelines fetched <date>; chosen by user; deltas for S19 to fix: <...>"
```
