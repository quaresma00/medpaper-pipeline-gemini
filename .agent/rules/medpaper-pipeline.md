# medpaper pipeline — Antigravity workspace rule (v1.32.0)

This repository runs a **gated 25-stage clinical research paper pipeline**. Never drive stages from memory; `pipeline/pipeline.toml`, `AGENTS.md`, and the active stage card (`uv run python tools/wf.py card`) govern all sequencing, outputs, and checks.

## Start, resume, and context discipline

Execute all commands via `pwsh` and `uv run python` (never bare global `python` or `pip`):

```powershell
uv run python tools/wf.py status
uv run python tools/wf.py card
```

- If `.venv` is absent, run `uv run --python 3.13 python bootstrap.py --skip-selftest`.
- After context compaction, run `uv run python tools/wf.py handoff` and load `reference/*.md` guides only when routed by `AGENTS.md` (`wf card <STAGE> --details` only on first pass of split stages).
- **Display-first & pre-write SCIE audit order**: `S07_artifacts` -> `S10_tables` -> `S11_figures` -> `S11b_prewrite_review` -> `S08_methods` -> `S09_results` -> `S12_reconcile`. Approved three-line tables, R figures, and an independent SCIE readiness audit precede all manuscript prose.
- Complete active outputs, run `uv run python tools/wf.py check` (add `--timings` or `--only "<ID>"` when diagnosing), then `uv run python tools/wf.py advance --note "..."`. Gates are checkpoints, not turn stops.

## Non-negotiable medical & scientific rules

1. **Full-census acquisition (`S04`)**: Acquire 100% of the S03 protocol-defined universe (`tools/data_manifest.py`, or read-only in-place registration via `tools/data_sources.py`). Convenience `LIMIT`, `TOP`, `head()`, `sample()`, `nrows=`, or page caps are blocked and non-overridable. Halt early (`NO_GO` / `LOW_ROI_HALT`) at `S02`/`S05`/`S06`/`S11b` if data or power cannot support a credible SCIE paper.
2. **Multi-track verified bibliography (`S07`/`S13`–`S24`)**: Only `tools/pubmed/verify.py` (fresh PubMed EFetch XML, Crossref JSON for `--methodology` DOIs, or verified `Rscript citation()` / official authority snapshots) authorizes citation, backed by live gates at `S13`/`S19`/`S24`. Register legal full texts with `tools/pubmed/fulltext.py register` (abort immediately on CAPTCHA gates).
3. **Context- & denominator-bound numbers**: Every own-study number in prose, tables, and explicit figure annotations must trace to `03_analysis/results/*.json` (`claim_bindings.json`; use `tools/manuscript/sync_claims.py --reanchor` after wording-only edits). Prior-study numbers require exact full-text `source_claims`.
4. **SCIE benchmarked displays & clinical labels (`S07`–`S11b`)**: Benchmark >=5 recent (`<=5y`) close SCIE full texts (`Original_Article` default; explicit `Brief_Report`/`Research_Letter` requires `genre_rationale`). Render table previews (`tables/render_preview.py --all --changed`) and R-first publication figures (`figures/render_r.py --all --changed`). **Zero figure subtitles/in-plot captions, zero raw variable names, zero code/pipeline jargon, and zero `>=4` repeated colon prefixes** (`display_labels_clinical`).
5. **Claim-driven medical prose & isolated Discussion (`S08`–`S17`)**: Run immediate per-section polish (`tools/text/polish.py section --file <sec.md> --snapshot|--verify|--reanchor`) to strip AI clichés, lab-log narration, and self-weakening filler while **strictly preserving null/unfavorable findings, concrete limitations, and calibrated uncertainty** (`reference/clinical-deai-antidefensive-writing.md`). Draft S16 from table-free `discussion_brief.md` + 6-part `discussion_outline.md`. Maintain section balance (`section_balance_health`).
6. **Independent subagent reviews & frozen scientific master (`S11b`/`S18`/`S19`/`S24`)**: Delegate reviews to one read-only subagent (`invoke_subagent(TypeName="research")` inspecting rendered PNGs via `read_file`), apply fixes in place via `tools/rework.py` (`mark --auto-changed`), and wait for explicit **`我确认这一版`**. Lock S19 with `scientific_master_freeze.json`.
7. **Browser-verified journal adaptation & clean Word bundle (`S20`–`S24`)**: Capture official Author Guidelines (delegate to `browser` subagent when HTTP is incomplete), isolate journal edits under `08_submission/integration/` (respecting `required_main_sections`, single-source `author_info.json`, default display placement, and `Supplemental_File_<N>_<Description>.<ext>` naming), build pure-black native three-line DOCX files (`build_docx.py`), and freeze `<Journal_Slug>_<YYYYMMDD_HHMMSS>` releases. Never insert AI-use disclosures unless explicitly requested by the user.
