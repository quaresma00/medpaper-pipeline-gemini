---
name: medpaper-pipeline
description: Drives a gated, resumable 25-stage medical/clinical research paper pipeline from research intake through full-census data acquisition, R-first figures and three-line tables, pre-writing SCIE audit (S11b), immediate per-section clinical de-AI/anti-defensive polish, context-bound IMRAD writing, version-bound independent subagent review, frozen scientific master, browser-verified journal adaptation, native Word packaging, and final reader/editor/compliance audit. Use whenever the task involves a medical research idea, clinical manuscript, research protocol, PubMed literature retrieval, medical figures/tables, journal selection, user revisions, or a submission package. Never follow the workflow from memory — run `uv run python tools/wf.py status` and obey the active stage card.
compatibility: Requires Windows pwsh, uv, and Python 3.12+ (3.13 recommended) for pinned science/PDF dependencies (matplotlib, numpy, openpyxl, pandas, scipy, python-docx, pypdf). R (Rscript) is the default renderer for new medical figures; Pandoc and Microsoft Word support final DOCX assembly and visual QA. Network access is required for PubMed, Crossref, Unpaywall, and official journal guidelines.
metadata:
  version: "1.32.0"
  entrypoint: "uv run python tools/wf.py status"
---

# medpaper pipeline (Gemini / Antigravity v1.32.0)

## Master Template & Dispatch Rule

The authoritative master template defaults on this machine to `F:\workspace\medpapaer\gemini` (override externally via `$env:MEDPAPER_MASTER_TEMPLATE` or `uv run python tools/medpaper_launcher.py --template-source <dir>`). Always execute via `pwsh` and `uv run python` (never bare global `python` or `pip`):

1. **Existing paper workspace** (`pipeline/pipeline.toml` and `tools/wf.py` present):
   - Resume immediately: `uv run python tools/wf.py status` then `uv run python tools/wf.py card` (use `wf handoff` after context compaction).
   - When explicitly upgrading engine files from `F:\workspace\medpapaer\gemini`, update only engine directories (`pipeline/`, `tools/`, `reference/`, `.agent/`, `.agents/`, `AGENTS.md`, `bootstrap.py`, `requirements*.txt`) while strictly preserving `project/`, `.venv/`, and `engine_pin`.
2. **New / empty workspace**:
   - Copy the clean skeleton (`pipeline/`, `tools/`, `project/`, `reference/`, `.agent/`, `.agents/`, `AGENTS.md`, `bootstrap.py`, `requirements.txt`, `requirements-guides.txt`, `.gitignore`) from `F:\workspace\medpapaer\gemini`, run `uv run --python 3.13 python bootstrap.py --skip-selftest`, and start at `S01_intake`.

## Execution Loop & Core Commands

Read `AGENTS.md` once and load routed `reference/*.md` guides on demand (`wf card <STAGE> --details` on first pass of split stages). Note the display-first sequence: **`S07_artifacts` -> `S10_tables` -> `S11_figures` -> `S11b_prewrite_review` -> `S08_methods` -> `S09_results` -> `S12_reconcile`**.

| Command | Purpose |
|---|---|
| `uv run python tools/wf.py status [--full]` | Compact local state (or full gate evaluation) |
| `uv run python tools/wf.py handoff` | Bounded context recovery after compaction |
| `uv run python tools/wf.py card [STAGE] [--details]` | Active/named stage card (or split procedure) |
| `uv run python tools/wf.py check [STAGE] [--only ID] [--timings]` | Run stage gates with optional single-item focus or ms timings |
| `uv run python tools/wf.py advance --note "..."` | Close current stage and advance on green gates |
| `uv run python tools/wf.py rebuild [--dry-run]` | Dependency-aware incremental DOCX rebuild |
| `uv run python tools/data_manifest.py init\|sync\|verify` | Full-census count, pagination, and hash proof |
| `uv run python tools/tables/render_preview.py --all [--changed]` | Three-line table PNG preview & layout QC |
| `uv run python tools/figures/render_r.py --all [--changed]` | Parallel R clinical figure renderer |
| `uv run python tools/text/polish.py section --file <md> --snapshot\|--verify\|--reanchor` | Immediate per-section clinical de-AI polish & safe re-anchor |
| `uv run python tools/manuscript/sync_claims.py [--reanchor]` | Sync fact/claim fingerprints and re-anchor wording-only edits |
| `uv run python tools/manuscript/reconcile.py` | Auto-generate S12 artifact-prose `reconciliation.md` |
| `uv run python tools/review_round.py start\|ingest\|close\|decide` | Version-bound read-only subagent review rounds (S11b/S18/S19/S24) |
| `uv run python tools/rework.py batch\|check\|mark --auto-changed\|close` | In-place scoped revisions without rewinding completed stages |

## Core Medical & Scientific Safeguards

1. **Full-data census & early stop-loss (`S02`–`S06`, `S11b`)**: Acquire 100% of the protocol universe (`acquisition_manifest.json` / `data_sources.py`); convenience caps (`LIMIT`, `head()`, `sample()`) are blocked. Recommend immediate `NO_GO` / `LOW_ROI_HALT` if power or confounding invalidates SCIE viability.
2. **Verified multi-track bibliography (`S07`/`S13`–`S24`)**: Only `tools/pubmed/verify.py` (PubMed XML, Crossref JSON for `--methodology`, or `Rscript citation()` / official authority snapshots) authorizes citation, backed by live checks at `S13`/`S19`/`S24`. Register legal full texts (`fulltext.py register`); archive uncited pool entries via `build_library.py --archive-uncited`.
3. **Exact numeric, scale & denominator provenance**: Own-study numbers in prose, tables, and figure annotations must trace to executed `03_analysis/results/*.json` (`claim_bindings.json`), matching endpoint, effect family (`HR`/`OR`/`RR`/`β`/`ΔRMST`/`GMR`/`AUC`/`I²`), CI level, and `n/N (%)` or survey/KM/CIF/MI denominators. Prior-study numbers require exact `source_claims`.
4. **SCIE comparator benchmarking & publication displays (`S07`–`S11b`)**: Benchmark `>=5` recent (`<=5y`) close SCIE full texts (`Original_Article` default; `Brief_Report`/`Research_Letter` with `genre_rationale`). R-first composite figures (`medpaper_clinical_forest`, `medpaper_consort_flow`, `medpaper_km_survival`) and three-line `.xlsx` tables forbid figure subtitles, in-plot captions, raw variable names, code jargon, and `>=4` repeated colon prefixes (`display_labels_clinical`).
5. **Clinical writing, section balance & isolated Discussion (`S08`–`S17`)**: Draft clear claim-driven clinical prose (`reference/medical-writing.md`, `reference/clinical-deai-antidefensive-writing.md`), preserving null/unfavorable findings, concrete limitations, and calibrated uncertainty. Isolate `discussion_brief.md` + 6-part `discussion_outline.md` before `discussion.md`, and guard Introduction depth (`section_balance_health`).
6. **Subagent blind review, frozen science & journal packaging (`S18`–`S24`)**: Use one read-only `research` subagent inspecting rendered PNGs via `read_file`, wait for explicit **`我确认这一版`**, freeze `scientific_master_freeze.json` at S19, capture official journal guidelines (`browser` subagent fallback) at S20, enforce `required_main_sections` and single-source `author_info.json`, build native three-line pure-black DOCX uploads (`build_docx.py`), and release under `<Journal_Slug>_<YYYYMMDD_HHMMSS>`.
