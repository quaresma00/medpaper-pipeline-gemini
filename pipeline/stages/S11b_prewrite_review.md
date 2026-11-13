# S11b - Pre-writing independent SCIE rigor & display review

**CRITICAL CHECKPOINT BEFORE DRAFTING PROSE.** Run this independent audit AFTER `S10_tables` and `S11_figures` and BEFORE writing `results.md`, `introduction.md`, `discussion.md`, or `abstract.md`. Catching fatal statistical gaps, thin figures, or non-publishable designs here saves massive rework and token quota.

## Purpose
Dispatch one independent, read-only subagent to evaluate whether the statistical methodology, executed results, tables, and rendered figures are scientifically rigorous and sufficiently comprehensive to support an **SCIE Original Article**—and gather user feedback BEFORE drafting prose.

## Early No-Go / Low-ROI Halt Rule
- If the independent reviewer or you find that the dataset, primary comparison, sample size, or residual confounding cannot support a publishable SCIE Original Article—or that further reanalysis offers minimal marginal benefit—**STOP IMMEDIATELY**.
- Present a clear, objective stop-loss assessment directly to the user rather than forcing weak prose into later stages.

## Procedure
1. Start the pre-writing independent review round:
```
uv run python tools/review_round.py start --scope prewrite
```
2. Launch ONE independent read-only subagent with NO orchestration/backstage history. Provide ONLY:
   - `01_protocol/analysis_contract.json`, `01_protocol/protocol_final.md`, `01_protocol/artifact_benchmark.md`
   - `03_analysis/results/*.json`, `03_analysis/method_scan.md`
   - `04_tables/` rendered `.xlsx`/captions and `05_figures/` rendered images + `legends.md`
   - Required JSON evidence hash map `reviewed_artifacts` from step 1.
3. The independent reviewer MUST deliver substantive findings (>=80 chars each) under these exact `##` headings plus the JSON `reviewed_artifacts` + `findings` fence:
   - `## Statistical methods & results rigor` (design alignment, confounding, sensitivity checks, effect precision, null/borderline honesty)
   - `## SCIE Original Article sufficiency` (novelty/incremental value vs the ≥5 recent SCIE benchmark comparators; verdict on whether results warrant an Original Article vs NO-GO / stop-loss)
   - `## Display clarity & medical language` (clinician readability of figure axes/panels and table headers/notes; zero code/variable jargon; adequate figure count and types)
4. Ingest the saved reply and present key gaps/revisions to the user:
```
uv run python tools/review_round.py ingest --scope prewrite --from-file <reply.md>
```
5. Execute any user-approved method/result/figure/table revisions via scoped `tools/rework.py` owners (run `prepare-revalidation` + `ingest --revalidation` if scientific inputs changed), close the round, and obtain explicit user approval (`我确认这一版`) BEFORE starting `S09_results`:
```
uv run python tools/review_round.py close --scope prewrite --change <path> "<why>" ...
uv run python tools/review_round.py decide --scope prewrite --answer no_further_review --words "我确认这一版"
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "prewrite SCIE audit W001 approved; methods, results, and displays verified"
```
