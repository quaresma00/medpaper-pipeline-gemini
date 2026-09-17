# medpaper - a gated medical research paper pipeline

[中文文档 (Chinese)](README_CN.md) | [English Documentation](README.md)

Turns a research idea into a submission-ready package across 25 stages, in any agentic IDE
(Kiro, Codex, Antigravity, Claude Code), without the workflow degrading as context is
compacted.

## The problem this solves

A workflow written as a long prompt fails in two predictable ways. It gets summarized away
during context compaction, so the agent drifts off the sequence. And it has no way to stop
the agent inventing a citation or a p-value, because a prompt cannot check anything.

The fix here is architectural, not rhetorical:

| Failure mode | Mechanism |
|---|---|
| Losing the place in the workflow | Run state on disk (`project/.wf/state.json`). `wf status` reprints everything needed to resume. |
| Instructions summarized away | The agent holds one stage card at a time, re-fetchable on demand instead of remembered. |
| Fabricated references | Every search caches its raw API payload; every citekey must appear in `verified.json` after an independent re-fetch. |
| Fabricated statistics | Every number in the manuscript must already exist in `03_analysis/results/*.json`. A gate extracts numeric tokens and rejects unmatched ones. |
| Racing ahead | `no_future_artifacts` and `single_section_written` block producing later stages' outputs. |
| "I verified the figure" without looking | QC is deterministic and separate; the visual review is a recorded decision with a rationale. |
| File sprawl | Every artifact is a declared stage output; `wf clean` reports anything undeclared. |

Prompt text carries intent. Code carries enforcement. The prompt layer here is deliberately
thin, and thin enough to survive compaction.

## Install

```powershell
uv venv .venv
uv pip install --python .venv\Scripts\python.exe matplotlib numpy openpyxl pandas scipy statsmodels

# Optional but recommended (raises PubMed from 3 to 10 req/s, enables Unpaywall full-text fetch)
$env:NCBI_API_KEY  = "your_ncbi_api_key_here"      # 10 req/s instead of 3
$env:NCBI_API_EMAIL = "your_email@example.com"     # required by Unpaywall, polite for NCBI
# On Linux/macOS:
# export NCBI_API_KEY="your_ncbi_api_key_here"
# export NCBI_API_EMAIL="your_email@example.com"

# adapters are now native skills under .agents/skills        # wire the skill into every IDE
uv run python tools/wf.py doctor               # verify
.venv\Scripts\python tools\selftest.py  # 26 offline checks; --online adds 3 live-API ones
```

The driver (`tools/wf.py`) is stdlib-only, so gates keep working even if the venv breaks.
Only figures and tables need the venv.

## Use

```powershell
uv run python tools/wf.py init                       # once
uv run python tools/wf.py status                     # every session, first
#   ... do what the stage card says ...
uv run python tools/wf.py check                      # run the gate
uv run python tools/wf.py advance --note "..."       # close the stage
```

`wf status` prints the invariants, the progress map, the gate state, the last handoff note,
the outputs this stage may create, and the full stage card. That one command is the whole
resume protocol.

| Command | Purpose |
|---|---|
| `wf tree -v` | Whole pipeline with outputs and gates |
| `wf card S11` | Read any stage card |
| `wf check S09` | Run any stage's gate without advancing |
| `wf decide NAME VALUE --why "..."` | Record a gated decision (rationale >= 40 chars) |
| `wf loop --to S05_analysis --why "..."` | Reopen an earlier stage; later stages return to pending |
| `wf note "..."` | Append to the handoff log |
| `wf clean [--apply]` | Report scratch and undeclared files; delete scratch |
| `wf config set intro_words_max 600` | Override a target per project |
| `wf doctor` | Environment and wiring check |

## The 19 stages

| | Stage | Gate highlights |
|---|---|---|
| S01 | Intake: normalize the idea | idea.json fully populated, notes.md started |
| S02 | Feasibility + go/no-go #1 | >= 3 cached searches, >= 20 records, verdict recorded with reasons |
| S03 | Protocol v1 + data plan | pre-specified analysis plan, reproducible retrieval steps |
| S04 | Acquire data, codebook, provenance | raw files present, dataset_summary.json, temp clean |
| S05 | Method scan + exploratory analysis | >= 5 searches, >= 2 result files, **no plotting code**, notes substantive |
| S06 | Final protocol + go/no-go #2 | deviations documented, convergence and verdict recorded |
| S07 | Artifact inventory + legends | benchmarked, 4-element concise figure legends (no methods bloat) |
| S08 | Methods | four-step causal skeleton, Statistical Analysis closes main text, technical detail to optional supplementary_methods.md |
| S09 | Results | numbers traceable, every planned artifact cited and nothing else |
| S10 | Tables | three-line format verified, every cell traceable |
| S11 | Figures | deterministic QC green, visual review recorded, panel text moved to legends |
| S12 | Reconcile text against artifacts | citations resolve to rendered files, table-cited numbers match the table |
| S13 | Reference library | ~50 entries, abstracts mandatory, all verified, bib/ris match |
| S14 | Introduction | word and reference targets, citations verified |
| S15 | Deep-read ~5 full texts | OA fetch recorded, notes substantive, every pick justified |
| S16 | Discussion | targets met, every deep-read paper engaged |
| S17 | Front matter & SCIE audit | automated title, deferred authors, complete manuscript assembled, independent subagent SCIE review |
| S18 | Journal choice + real guidelines | SCIE venues ranked by acceptance probability, guidelines fetched and snapshotted |
| S19 | Polish and de-AI | facts preserved, house style verified, AI boilerplate eliminated |
| S20 | Submission bundle | dynamic typography (pure black Times New Roman), legends at manuscript end, full Word package |

## Layout

```
pipeline/pipeline.toml       single source of truth: stages, outputs, gates, targets, policy
pipeline/stages/S01..S19.md  one instruction card per stage
tools/wf.py                  driver (stdlib only)
tools/wfcore/                state machine, gate runner, 31 checks, xlsx reader
tools/pubmed/                E-utilities + Crossref + Unpaywall, library builder, verifier
tools/tables/threeline.py    three-line xlsx writer
tools/figures/style.py       journal rcParams + panel-first figure builder
tools/figures/qc.py          deterministic figure QC
tools/install_adapters.py    sync the skill into each IDE
tools/selftest.py            regression test for the whole toolchain
reference/                   figure and table standards, loaded on demand
project/                     the paper; one folder per phase, state in project/.wf/
```

## Multi-IDE support

One skill, `.agents/skills/medpaper-pipeline/SKILL.md`, following the
[Agent Skills open standard](https://agentskills.io/specification). `tools/install_adapters.py`
copies it to each tool's discovery path and writes a short pointer file:

| Tool | Skill path | Pointer |
|---|---|---|
| **Codex** | `.agents/skills/medpaper-pipeline` (source) | `AGENTS.md` |
| **Claude Code** | `.claude/skills/medpaper-pipeline` | `CLAUDE.md` |
| **Antigravity** | `.agents/skills/medpaper-pipeline` (shared) | `.agents/AGENTS.md`, `.agent/rules/`, `.agent/workflows/` |
| **Kiro** | `.kiro/skills/medpaper-pipeline` | `.kiro/steering/medpaper-pipeline.md`, `.kiro/hooks/` |

Every adapter says the same short thing: run `uv run python tools/wf.py status` and obey the card. Because none of
them contains the workflow, editing a stage card never means touching an adapter.
`# adapters are now native skills under .agents/skills --check` reports drift.

### How to reuse with Claude Code
1. Generate Claude adapters (or sync all):
   ```bash
   # adapters are now native skills under .agents/skills --only claude
   # Or sync all supported IDEs:
   # adapters are now native skills under .agents/skills --all
   ```
   This generates `CLAUDE.md` at the project root and `.claude/skills/medpaper-pipeline/SKILL.md`.
2. Open this directory with Claude Code (`claude`).
3. Claude automatically picks up `CLAUDE.md` as context and loads the skill. Start the workflow by entering:
   ```
   Run uv run python tools/wf.py status and start the pipeline.
   ```
   Or invoke the skill directly.

### How to reuse with OpenAI Codex
1. Generate Codex adapters:
   ```bash
   # adapters are now native skills under .agents/skills --only codex
   # Or sync all supported IDEs:
   # adapters are now native skills under .agents/skills --all
   ```
   This generates `AGENTS.md` at the repository root and `.agents/skills/medpaper-pipeline/SKILL.md`.
2. Open this repository in Codex. Codex natively discovers `AGENTS.md` and reads project rules.
3. In the chat, prompt Codex:
   ```
   Run uv run python tools/wf.py status and follow the stage card.
   ```

### How to reuse with Google Antigravity
1. The repository is pre-configured with Antigravity rules (`.agent/rules/`) and slash command (`.agent/workflows/medpaper-resume.md`).
2. Type `/medpaper-resume` in the chat, or run `uv run uv run python tools/wf.py status`.

## Extending it

- **Change a rule**: edit `pipeline/pipeline.toml`. Stage order is array order; gates are
  declarative.
- **Add a check**: write a function in `tools/wfcore/checks/`, decorate it with
  `@check("name")`, reference it from a gate. No engine change. `wf checks` lists all of
  them; `wf doctor` fails if a gate names one that does not exist.
- **Add a stage**: append a `[[stage]]` block and write its card. `wf doctor` verifies the
  card exists.
- **Retarget for a different journal**: `wf config set` writes `project/.wf/config.toml`,
  which overrides `[targets]`.

## Known limits

- The numeric-provenance check works on token matching. It cannot tell a correct number
  from a correct-looking one that came from the wrong analysis; it only proves the number
  exists in a result file. `numbers_cross_match` at S12 narrows this for table-cited values.
- `no_ai_boilerplate` flags stock phrasing as a warning, not a failure. Judgement stays
  with the writer.
- The grey-text detector is only meaningful for vector-style statistical plots. Photographic,
  blot and heat-map panels put legitimate data in the mid-grey band, so it never blocks.
- Font size and line width are measured from the live figure object, so a figure not written
  through `figures.style.save()` cannot be audited for them. QC says so rather than passing
  silently.
- Journal acceptance probability at S18 is a reasoned estimate from retrieved evidence, not
  a computed number.

