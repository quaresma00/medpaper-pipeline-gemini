# Clinical De-AI, Anti-Defensive & Medical Prose Guide (v1.30.0)

Synthesized from:
- `Adkid-Zephyr/anti-defensive-writing-Skill`: *A paper is a press conference, not a lab log or self-audit.*
- Academic humanizer practices (`academic-humanizer`, `humanizer`, `humanize-writing-skill`): *Direct medical voice without AI clichés, padded tricolons, em-dash clutter, or programmer jargon.*

## 1. Per-Section Immediate Polish Rule (Do Not Wait for S22)

Every manuscript markdown section (`methods.md`, `results.md`, `introduction.md`, `discussion.md`, `abstract.md`) MUST undergo immediate de-AI, anti-defensive, and clinical language polishing **as soon as that section is drafted**:

1. **Snapshot the draft** before editing wording:
   `uv run python tools/text/polish.py section --file project/07_manuscript/<section>.md --snapshot`
2. **Rewrite** using the rules below while keeping every number, unit, confidence interval, P value, figure/table callout, and `[@citekey]` strictly unchanged.
3. **Verify & record the polish receipt** (required by the `section_polished` gate):
   `uv run python tools/text/polish.py section --file project/07_manuscript/<section>.md --verify`

## 2. Anti-Defensive Writing Principles

1. **Lead with strongest clinical evidence, not chronological lab logs**:
   - Ban execution-diary transitions: *"First, we ran..."*, *"In the next step, we implemented..."*, *"Then we filtered the dataframe..."*, *"Following pipeline stage S04..."*.
   - Organize paragraphs around clinical questions, cohorts, exposures, outcomes, and pathophysiological mechanisms.
2. **Eliminate self-weakening / apologetic framing**:
   - Ban premature apologies and belittling adverbs before presenting results or contributions: *unfortunately, merely, only achieves, severely insufficient, still lags far behind, limited improvement, trivial, modest at best, cannot rule out completely without specifying mechanism*.
   - State study scope, boundary conditions, and direction of residual bias factually in Limitations rather than undermining the primary findings in Abstract, Introduction, or Results.
3. **Never leak backend engineering or workflow terms into medical prose, tables, or figures**:
   - Ban terms physicians do not read in clinical journals: `pipeline`, `workflow`, `script`, `module`, `dataframe`, `JSON`, `manifest`, `freeze`, `gate`, `parser`, `artifact plan`, `CSV export`, `orchestration`, `stage S01–S25`.
   - Write in standard clinical-epidemiology language (*cohort selection, multivariable Cox regression, sensitivity analysis, receiver operating characteristic curve*).

## 3. High-Precision De-AI & Style Hygiene

- **Zero AI clichés**: Remove *delve into, underscore the importance, tapestry, paves the way, testament to, myriad, plethora, multifaceted, cutting-edge, game-changer, unlock the potential, at the forefront of, in today's rapidly evolving, intricate interplay, comprehensive understanding, it is worth noting*.
- **No mechanical em-dashes (`—`) or Rule-of-Three padding**: Replace decorative em-dash interruptions with crisp commas, parentheses, or split sentences; vary sentence length naturally (mix short declarative clinical sentences with analytical sentences).
- **Preserve scientific precision**: Keep appropriate epidemiological hedging (*associated with, consistent with, suggested, residual confounding*) while avoiding stacked hedges (*may possibly potentially*).
- **Fact invariance**: Polishing edits wording and narrative logic ONLY; numbers, CIs, P values, display numbers, and `[@citekey]` sets must remain 100% identical to the pre-polish snapshot.
