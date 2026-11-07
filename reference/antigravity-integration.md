# Antigravity / Gemini capability integration

`medpaper-pipeline` is the sole workflow orchestrator in Google Antigravity and the `agy` CLI.
Installed Antigravity skills, Science plugins, MCP servers, browser tools, and local applications
act solely as capability providers inside the currently active stage; they never replace the
pipeline's state (`project/.wf/state.json`), declared output paths, or deterministic gates.

## Environment, shell, and master template discipline

- **Shell & Python invocation**: On Windows, execute all terminal commands via `pwsh`
  (PowerShell 7). Always invoke workflow and analysis entrypoints with `uv run python <script.py>`
  (never bare global `python` or `pip`). If `.venv` does not exist yet, initialize and verify it
  with `uv run --python 3.13 python bootstrap.py`.
- **Progress visibility**: Long-running acquisition, statistical replay, R rendering, and build
  scripts must emit clear step/progress output so background tasks never appear stalled.
- **Master template dispatch (`F:\workspace\medpapaer\gemini`, or `$env:MEDPAPER_MASTER_TEMPLATE` / `tools/medpaper_launcher.py --template-source <dir>` on external clones)**:
  1. **Existing workspace** (`pipeline/` and `tools/wf.py` present): run
     `uv run python tools/wf.py status` (or `wf handoff` after context compaction). If refreshing
     engine files from the master template onto an existing study, update only engine directories
     (`pipeline/`, `tools/`, `reference/`, `.agent/`, `.agents/`, `AGENTS.md`, `bootstrap.py`,
     `requirements*.txt`) while strictly preserving `project/` and `.venv/`. Completed historical
     stages remain protected by `engine_pin`; use `uv run python tools/wf.py migrate --dry-run`
     only when intentionally auditing legacy gates.
  2. **New / empty workspace**: copy the purified engine skeleton (`pipeline/`, `tools/`,
     `project/`, `reference/`, `.agent/`, `.agents/`, `AGENTS.md`, `bootstrap.py`,
     `requirements.txt`, `requirements-guides.txt`, `.gitignore`) from
     `F:\workspace\medpapaer\gemini`, ensure `.venv` (`uv run --python 3.13 python bootstrap.py`),
     and begin at `S01_intake`.

## Subagent delegation for independent reviews (S18, S19, S24, S25)

Antigravity provides native read-only subagent isolation via `invoke_subagent`:

1. **Start the hash-bound round before delegating**:
   - At S18 / S19: `uv run python tools/review_round.py start --scope manuscript` (use `--delta`
     on subsequent user-requested rounds).
   - At S24: `uv run python tools/review_round.py start --scope package` (or `--delta`).
   - At S25: freeze and verify exact uploads first (`uv run python tools/package_review.py freeze`
     and `verify`), then extract `freeze_id` and `audit_context_id`.
2. **Launch exactly one independent read-only subagent**:
   - Prefer `invoke_subagent(TypeName="research", Role="...", Prompt="...")` because the `research`
     subagent runs in a read-only sandbox and has `read_file` support for Markdown, PNG rendered
     figures/pages, and workspace artifacts without risk of mutating frozen sources.
   - Pass the exact file paths and `reviewed_artifacts` JSON block printed by `review_round.py start`
     (or the frozen bundle + cached official journal guide at S25). Instruct the reviewer to inspect
     actual tables and rendered figure/page PNGs directly, write all required headings, include the
     exact `reviewed_artifacts` JSON fenced block, and return the complete verbatim Markdown report.
3. **Persist and attach the verbatim report**:
   - Because `research` is read-only, save its returned verbatim Markdown to a UTF-8 file in
     `project/temp/` and ingest it cleanly via:
     ```powershell
     uv run python tools/review_round.py ingest --scope manuscript --from-file project/temp/raw_review.md
     ```
     (or `--scope package` at S24; at S25 write the verbatim returned report directly to
     `project/08_submission/independent_submission_audit.md` without modifying frozen uploads).
   - Never fabricate a subagent report, reuse a stale hash block, or substitute the main agent's
     own self-check as an independent review. If subagent delegation is genuinely unavailable,
     keep the independent review pending and report the blocker honestly.
4. **Scoped fixes and explicit version-bound approval**:
   - Apply safe, evidence-supported fixes through a sealed `tools/rework.py batch` in place at S19
     or S24 without rewinding stage history, recheck true dependants, close the review round with
     exact `--change` and `--kept` dispositions, report once, and wait for the user's explicit
     statement **`我确认这一版`** (pass non-ASCII user wording safely via `--words-file` UTF-8 file).

## Arbitrating Science plugin skills, viewers, and UI tools

- **Literature & biomedical databases** (`pubmed-database`, `literature-search-europepmc`,
  `literature-search-openalex`, `literature-search-biorxiv`, `clinical-trials-database`,
  `chembl-database`, `opentargets-database`, `gtex-database`, `gnomad-database`, `uniprot-database`):
  - Discovery and exploratory cross-checks are welcome, but **formal manuscript citations must
    pass through `tools/pubmed/client.py`, `build_library.py`, and `verify.py`**.
  - Legal open-access or user-authorized full-text PDFs fetched via external skills must be
    registered with `uv run python tools/pubmed/fulltext.py register ...` so article identity and
    SHA-256 provenance are verified. Never use illicit PDF sources or hand-edit `verified.json`.
- **Data acquisition & full-census enforcement**:
  - External database/API helpers may fetch data at S04, or large local user datasets may be
    registered in place via `uv run python tools/data_sources.py register ...` without copying.
  - Every source must record machine-verifiable total counts, pagination exhaustion, and file
    hashes via `tools/data_manifest.py`. Convenience `LIMIT`, `head()`, `sample()`, or row caps
    are blocked by non-overridable gates.
- **R-first medical figures, structural viewers, and `image-generator` / `generative_ui`**:
  - Publication statistical figures at S11 default to the managed R pipeline
    (`uv run python tools/figures/render_r.py`), consuming approved `03_analysis/results/*.json`
    without refitting models.
  - Interactive sidecars (`biomolecular-structure-viewer`), `pymol`, or `generative_ui` may help
    explore molecular structures or explain results in chat, and `image-generator` may act solely
    as an optional visual critic, **never** to redraw or edit statistical plots.
- **Word builds, native tables, and journal switching (S20–S25)**:
  - Scientific freeze (`07_manuscript/scientific_master_freeze.json`) locks S19 sources.
  - All journal tailoring lives under `08_submission/integration/` managed by `tools/journal.py`
    and `tools/manuscript/journal_workspace.py`. Switching target journals archives prior
    integration artifacts cleanly without touching the frozen scientific master.
  - Use `uv run python tools/wf.py rebuild` (and `tools/manuscript/build_docx.py`) to produce
    native portrait/landscape three-line Word tables and clean XML stripped of `outlineLvl`,
    `keepNext`, `keepLines`, `pageBreakBefore`, paragraph borders, hyperlinks, and non-black runs.
  - Inspect actual rendered PNG/PDF/DOCX outputs with `read_file` before recording visual QA.
