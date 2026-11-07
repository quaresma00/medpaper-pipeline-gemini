# Install and operate medpaper on Google Antigravity / Gemini (v1.27.0)

## Requirements

- Windows PowerShell 7 (`pwsh`)
- `uv`
- Python 3.13 (installed or provisionable by `uv`; pinned science/PDF dependencies require Python 3.12+)
- Network access for live PubMed EFetch, Crossref, Unpaywall, indexing, and official journal guides
- R (`Rscript`) as the default renderer for new medical figures (with `renv` support), plus Pandoc and Microsoft Word for deterministic DOCX builds and visual QA

## Bootstrap

From the repository root (`F:\workspace\medpapaer\gemini` or any derived workspace):

```powershell
uv run --python 3.13 python bootstrap.py
```

`bootstrap.py` creates `.venv`, installs the pinned packages (`requirements.txt`, including `pypdf`), initializes `project/`, runs `wf doctor`, and executes the offline regression suite.

Set credentials in the user or process environment, never inside repository files:

```powershell
$env:NCBI_API_KEY = "<your NCBI API key>"
$env:NCBI_API_EMAIL = "you@example.org"
```

## What Antigravity and `agy` read

| File | Read by | Role |
|---|---|---|
| `.agent/rules/medpaper-pipeline.md` | Antigravity IDE | Workspace passive rule |
| `.agents/skills/medpaper-pipeline/SKILL.md` | Antigravity IDE + `agy` CLI | Workspace skill (`v1.27.0`) |
| `AGENTS.md` | Antigravity + cross-IDE | Primary execution policy and topic router |
| `reference/antigravity-integration.md` | On-demand router | Subagent (`invoke_subagent`), Science plugin, and tool arbitration |
| `~/.gemini/config/skills/medpaper-pipeline/SKILL.md` | Global IDE + CLI | Global dispatcher (`F:\workspace\medpapaer\gemini` default, override via `MEDPAPER_MASTER_TEMPLATE` or `tools/medpaper_launcher.py --template-source`) |

## Start, resume, and context recovery

Place your research idea in `project/00_input/idea.md` and ask Antigravity to start or resume the `medpaper-pipeline` skill, or run directly via `pwsh`:

```powershell
uv run python tools/wf.py status
uv run python tools/wf.py card
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "specific handoff note"
```

- `wf status` is fast, local, and network-free; pass `--full` to run gates inline.
- After context compaction, run `uv run python tools/wf.py handoff` to restore bounded resumption state without reloading conversation history.
- Use `uv run python tools/wf.py card <STAGE> --details` only when reading a split stage procedure (`S07`, `S20`, `S23`, `S25`) for the first time.
- Despite stable stage IDs (`S01`–`S25`), execution advances **`S08_methods` -> `S10_tables` -> `S11_figures` -> `S09_results` -> `S12_reconcile`** so verified tables and R figures precede `Results` drafting.

## Core integrity and revision workflows

1. **Full-census acquisition (`S04`)**:
   ```powershell
   uv run python tools/data_manifest.py init
   uv run python tools/data_manifest.py sync
   uv run python tools/data_manifest.py verify
   ```
   Large local datasets can be registered read-only in place via `uv run python tools/data_sources.py register ...`. Convenience `LIMIT`, `TOP`, `head()`, `sample()`, `nrows=`, and page caps are blocked and cannot be waived with `--force`.
2. **Fail-closed PubMed provenance (`S13`–`S25`)**:
   Only `uv run python tools/pubmed/verify.py` (fresh EFetch + raw XML/library hashes) makes a reference citable, backed by live EFetch gates at S13 and S25. Register legal full texts via `uv run python tools/pubmed/fulltext.py register ...`.
3. **R-first figures & benchmark-driven scope (`S06`–`S11`)**:
   S06 freezes `analysis_contract.json` and `study_facts.json`; S07 benchmarks registered close comparator PDFs (`tools/manuscript/benchmark.py`) instead of imposing universal reference/word/figure quotas. S11 renders figures via `uv run python tools/figures/render_r.py` from approved results without refitting models.
4. **Version-bound subagent reviews & explicit `我确认这一版` (`S18`, `S19`, `S24`, `S25`)**:
   No review ZIPs are created. Independent reviews run in one read-only subagent (`invoke_subagent(TypeName="research", ...)`), attached via `uv run python tools/review_round.py ingest --from-file ...`. Safe fixes are applied in place via `tools/rework.py batch`, reported once with clickable paths, and gated on the user's explicit **`我确认这一版`** for the current version.
5. **Frozen scientific master, journal switching, and native Word tables (`S20`–`S25`)**:
   `scientific_master_freeze.json` locks S19 scientific sources. All journal adaptations live in `08_submission/integration/` (`tools/journal.py`), archiving prior journal attempts cleanly when switching targets. `uv run python tools/wf.py rebuild` and `build_docx.py` produce native portrait/landscape three-line Word tables and flat, pure-black `SectionHeading` XML free of `outlineLvl`, `keepNext`, `keepLines`, `pageBreakBefore`, borders, and hyperlinks.

## Verify or package

```powershell
uv run python tools/wf.py doctor
uv run python tools/selftest.py
uv run python tools/package.py --output ..\medpaper-gemini-ready.zip
```
