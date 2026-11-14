# Clinical De-AI, Claim-Driven & Balanced Medical Prose Guide (v1.30.0)

Synthesized from:
- Selective adaptation of `Adkid-Zephyr/anti-defensive-writing-Skill`: **Adopt its anti-lab-log narrative and clear, claim-driven argument structure, while strictly rejecting "only-highlight-strengths / press-conference" spin.** Medical manuscripts must transparently report unfavorable results, null findings, study limitations, and statistical/causal uncertainty.
- Academic humanizer practices (`academic-humanizer`, `humanizer`, `humanize-writing-skill`): *Direct medical voice without AI clichés, padded tricolons, em-dash clutter, or programmer jargon.*

## 1. Per-Section Immediate Polish Rule (Do Not Wait for S22)

Every manuscript markdown section (`methods.md`, `results.md`, `introduction.md`, `discussion.md`, `abstract.md`) MUST undergo immediate de-AI, anti-lab-log, and clinical language polishing **as soon as that section is drafted**:

1. **Snapshot the draft** before editing wording:
   `uv run python tools/text/polish.py section --file project/07_manuscript/<section>.md --snapshot`
2. **Rewrite** using the rules below while keeping every number, unit, confidence interval, P value, figure/table callout, and `[@citekey]` strictly unchanged.
3. **Verify & record the polish receipt** (required by the `section_polished` gate):
   `uv run python tools/text/polish.py section --file project/07_manuscript/<section>.md --verify`

## 2. Claim-Driven Narrative Without Spin (Adopt Structure, Preserve Honesty)

1. **Lead with clear clinical claims and findings, not chronological work-report logs**:
   - Ban execution-diary transitions: *"First, we ran..."*, *"In the next step, we implemented..."*, *"Then we filtered the dataframe..."*, *"Following pipeline stage S04..."*.
   - Organize paragraphs around explicit clinical questions, cohorts, exposures, outcomes, and pathophysiological mechanisms. State the core point of each paragraph clearly in its opening sentence.
2. **Eliminate empty work-report self-belittling, NOT genuine medical limitations**:
   - Ban non-quantitative, apologetic work-report filler: *merely achieves, only achieves, severely insufficient, still lags far behind*.
   - **Never suppress or spin unfavorable, null, or modest findings**: In clinical research, a negative/null primary or secondary outcome, an attenuated sensitivity analysis, an unfavorable subgroup signal, or an adverse safety event is a core scientific result. Report null and unfavorable findings with the exact same clarity, quantitative precision (point estimate, 95% CI, exact $P$ value), and prominence as positive findings. Describing a genuinely small effect as a *modest association*, *small absolute risk difference*, or *null finding* is accurate clinical reporting—never rewrite it to sound stronger than the data warrant.
   - **Preserve calibrated uncertainty and explicit limitations**: Observational studies must retain appropriate non-causal hedging (*was associated with, is consistent with, may reflect residual confounding*). Wide confidence intervals, limited event counts, unmeasured confounding, selection bias, measurement error, and generalizability constraints must be stated explicitly and quantitatively in Results and Discussion.
3. **Never leak backend engineering or workflow terms into medical prose, tables, or figures**:
   - Ban terms physicians do not read in clinical journals: `pipeline`, `workflow`, `script`, `module`, `dataframe`, `JSON`, `manifest`, `freeze`, `gate`, `parser`, `artifact plan`, `CSV export`, `orchestration`, `stage S01–S25`.
   - Write in standard clinical-epidemiology language (*cohort selection, multivariable Cox regression, sensitivity analysis, receiver operating characteristic curve*).

## 3. High-Precision De-AI & Style Hygiene

- **Zero AI clichés**: Remove *delve into, underscore the importance, tapestry, paves the way, testament to, myriad, plethora, multifaceted, cutting-edge, game-changer, unlock the potential, at the forefront of, in today's rapidly evolving, intricate interplay, comprehensive understanding, it is worth noting*.
- **No mechanical em-dashes (`—`) or Rule-of-Three padding**: Replace decorative em-dash interruptions with crisp commas, parentheses, or split sentences; vary sentence length naturally (mix short declarative clinical sentences with analytical sentences).
- **Preserve scientific precision**: Keep appropriate epidemiological hedging (*associated with, consistent with, suggested, residual confounding, wide confidence interval*) while avoiding stacked hedges (*may possibly potentially*).
- **Fact invariance**: Polishing edits wording and narrative logic ONLY; numbers, CIs, P values, display numbers, and `[@citekey]` sets must remain 100% identical to the pre-polish snapshot.
