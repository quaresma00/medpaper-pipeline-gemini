---
name: medpaper-pipeline
description: Drives a gated, resumable medical/clinical research paper pipeline from a research idea through feasibility, data acquisition, exploratory analysis, figure and table production, IMRAD writing, independent review, frozen scientific master, journal selection, integration workspace, submission package and triple-perspective audit. Use whenever the task involves a medical research idea, a clinical manuscript, a research protocol, literature retrieval via PubMed, publication-grade figures or three-line tables, journal selection, or a submission package. Do not follow the workflow from memory - run `uv run python tools/wf.py status` and obey the stage card it prints.
compatibility: Requires Python 3.11+ for the driver. Figure and table production additionally need matplotlib, numpy, openpyxl, and python-docx. Network access is required for PubMed, Crossref and Unpaywall. Set NCBI_API_KEY to raise the E-utilities rate limit.
metadata:
  version: "1.4.0"
  entrypoint: "uv run python tools/wf.py status"
---

# medpaper pipeline

## Master Template & Dispatch Rule

The official and authoritative master template of this pipeline is strictly anchored at:
`F:\workspace\medpapaer\gemini`

When this skill is invoked:
1. **Existing paper project**: If the current workspace already contains `pipeline/` and `tools/wf.py`, resume the pipeline immediately by running:
   ```bash
   uv run python tools/wf.py status
   ```
2. **New / Empty project**: If the current workspace lacks the pipeline files, do NOT fail or invent files. Automatically copy the complete purified engine structure (`pipeline/`, `tools/`, `project/`, `reference/`, `.agent/`, `.agents/`, `requirements.txt`, `.gitignore`) directly from the master template at `F:\workspace\medpapaer\gemini` into the current workspace, run:
   ```bash
   uv run python tools/wf.py init
   ```
   and proceed to Stage S01.

This repository holds a 25-stage research pipeline. The workflow is **not** in this file
and must not be reconstructed from memory. It lives in `pipeline/pipeline.toml` and
`pipeline/stages/*.md`, and a CLI hands you exactly one stage at a time.

That indirection is the point. A long prompt degrades as context is compacted; a state
file on disk does not. Anything you need to know is one command away, always current.

## The only loop you need

```bash
uv run python tools/wf.py status                 # where am I, what is blocking, full stage card
<do the work described on the card>
uv run python tools/wf.py check                  # run the stage's gate
<fix what it reports>
uv run python tools/wf.py advance --note "..."   # closes the stage; refuses on a red gate
```

**Run `status` first, every session, before anything else.** It prints the invariants, the
progress map, the gate state, the last handoff note, the declared outputs, and the whole
stage card. After a context reset that single command restores everything that matters.

Never infer the current stage from the conversation, from which files exist, or from what
you remember doing. Ask the CLI.

## Key commands

| Command | Use |
|---|---|
| `uv run python tools/wf.py status` | Where am I, what is blocking, full stage card |
| `uv run python tools/wf.py init` | First time only: scaffold `project/` and create the run state |
| `uv run python tools/wf.py doctor` | Environment and wiring check; run when something behaves oddly |
| `uv run python tools/wf.py check` | Run the active stage's gates without advancing |
| `uv run python tools/wf.py advance --note "..."` | Advance to the next stage upon green gates |
| `uv run python tools/wf.py decide NAME VALUE --why "..."` | Record a gated decision plus its rationale |
| `uv run python tools/wf.py loop --to STAGE --why "..."` | Deliberately reopen an earlier stage |
| `uv run python tools/rework.py status` | Inspect active persisted revision round |
| `uv run python tools/rework.py batch --source-stage STAGE --items-json '...'` | Route user revisions to earliest owning stages |
| `uv run python tools/rework.py close` | Finalize revision round with verified hashes |
| `uv run python tools/wf.py clean [--apply]` | Report scratch and undeclared files; delete scratch |
| `uv run python tools/wf.py config set KEY VALUE` | Override a target (word counts, reference counts, caps) |

## Non-negotiable rules

These are also printed by `wf status`, and several are mechanically enforced.

1. **Literature comes from the API, never from memory.** Use `tools/pubmed/`. Every search
   caches its raw payload. A reference that is not verified against raw XML caches and live PubMed EFetch does not exist. Never state a PMID, DOI, title, journal, year or finding you did not retrieve.
2. **Full-data census coverage.** Acquire the entire S03 protocol-defined data universe before analysis. Hash all raw/acquisition files with `tools/data_manifest.py`, verify pagination exhaustion, and reconcile received records. Never use LIMIT, head(), sample(), or fixed page counts.
3. **No number without provenance.** Every figure in the manuscript, tables and abstract
   must already exist in `03_analysis/results/*.json`, written there by code that ran.
4. **Canonical Assembly & Independent Scientific Review (S17-S19).** S17 assembles canonical full manuscript. S18 executes independent publication-readiness review. S19 requires user review, generates third-party review ZIP package (`tools/manuscript/review_package.py`), and freezes the journal-independent scientific master (`tools/manuscript/scientific_freeze.py`).
5. **Journal-Specific Integration Isolation (S20-S25).** S20 establishes a derived integration sandbox (`08_submission/integration/`). The S19 scientific master is NEVER edited for journal styling. All journal tailoring lives in the integration layer.
6. **Layout vs Content Disambiguation (S24).** DOCX files are monitored via visible text extraction (`tools/package_content.py`). Pure Word layout/typography edits are permitted when visible text hashes match baseline. Text changes require workflow rewind.
7. **Triple-Perspective Submission Audit (S25).** Independent single-pass review from Reader, Editor, and Journal Compliance perspectives before submission readiness.

## Handoff discipline

Before advancing, record what a stranger would need to pick this up: what was produced,
what was decided and why, and what is still open. `wf advance` refuses without it.
