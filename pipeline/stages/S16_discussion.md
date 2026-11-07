# S16 - Discussion

Use the already-read close medical comparators to settle the narrative before Word build.
Default to connected paragraphs, not a subheading for every argument. Add subheadings only
when the actual design, target-journal examples or explicit author rules support them.

## Purpose
Interpret the finding against the literature you actually read. One file, this stage only.

## Inputs (strictly isolated from result tables and display numbers)
- `07_manuscript/discussion_brief.md` - prose-only summary of principal findings, deep-read comparison points, candidate mechanisms, and limitations/bias notes (**NO result tables from `04_tables/` and NO table/figure numbers**)
- `06_refs/deepread/*.md` - argument-bearing full texts, actually read
- `06_refs/library.json` - real abstracts or registered full texts for the wider context
- `03_analysis/notes.md` -> `Discussion points`, `Limitations`, `Surprises`
- `01_protocol/study_facts.json` & `01_protocol/protocol_diff.md` - clinical question, main finding, and internal limitation context
- Do **NOT** pass `04_tables/*.xlsx` or `artifact_plan.json` display numbers into the Discussion drafting prompt.

## Procedure
Use the Discussion route and illustration in `reference/medical-writing.md` before writing. Read
the finished argument against actual Results and cited source passages, especially its
certainty and clinical implications; no additional review round is introduced.

1. A useful narrative route, not mandatory subheadings or an inflexible order:
   1. **Principal finding** - concise, with uncertainty proportionate to the evidence; no new own-study result.
   2. **Comparison with prior work** - this is where the deep reads earn their place.
      Where you agree, say with whom and why. Where you disagree, name the study and give a
      mechanistic or methodological reason (population, exposure definition, follow-up,
      adjustment set, era). Every deep-read paper must appear here; the gate checks it.
   3. **Interpretation / mechanism** - clearly labelled as inference, not as demonstrated.
   4. **Clinical or research implications** - proportionate to the evidence. A single
      observational study does not change practice.
   5. **Strengths and limitations** - specific and quantified. Include scientifically
      material limitations, residual confounding, generalisability limits,
      precision, and measurement error as applicable. Explain a bias direction only when
      supportable; state when its direction or magnitude cannot be determined.
      Keep internal plan revisions in `01_protocol`; do not narrate every deviation or
      announce an unregistered protocol for ordinary retrospective mining. Preserve true
      post-hoc/exploratory status and any specifically applicable protocol reporting.
   6. **Conclusion** - two or three sentences, no stronger than the Results support.
2. **Context isolation & outline-first sequence (mandatory before drafting prose)**:
   - Run `uv run python tools/manuscript/discussion_brief.py scaffold` and refine `project/07_manuscript/discussion_brief.md` so it contains only prose-summarized principal findings, deep-read comparison points, candidate mechanisms, and limitations/bias notes (zero tables, zero `Table N` / `Figure N` / `Table S*` / `Figure S*` callouts).
   - Before writing `discussion.md`, write a concise 6-part outline in `project/07_manuscript/discussion_outline.md` (50–650 words, no tables or display numbers) with these exact `##` headings:
     1. `Principal findings`
     2. `Comparison with prior studies and reasons for differences`
     3. `Potential mechanisms`
     4. `Clinical implications`
     5. `Limitations and direction of bias`
     6. `Conclusion`
   - Lock the pre-draft receipt BEFORE creating `discussion.md`:
     `uv run python tools/manuscript/discussion_brief.py lock-outline`
3. Draft `project/07_manuscript/discussion.md` from `discussion_brief.md` + `discussion_outline.md` with pandoc citations `[@key]`.
4. Complete Discussion argument/passages in the sealed benchmark, including contrary evidence
   where relevant. Run `tools/wf.py check` for actual coverage and cited deep reads, not fixed
   chapter counts. Keep a coherent medical argument, not a separate heading per analysis.

## Outputs
- `07_manuscript/discussion_brief.md`
- `07_manuscript/discussion_outline.md`
- `07_manuscript/discussion.md`

## Hard rules
- Draft prose ONLY after locking `discussion_brief.md` and the 6-part `discussion_outline.md`.
- Do NOT over-cite supplementary tables/figures in Discussion (at most 1 supplementary reference if unavoidable; prefer zero) and do NOT copy or closely paraphrase sentences from `results.md` (`discussion_discipline` blocks both).
- No new own-study results. For 1.27+, any own-study number restated in `discussion.md` must
  be bound in `07_manuscript/claim_bindings.json` with `fact_ids` and `context_evidence`
  (same-section lead-in inheritance allowed), tracing to accepted Results/source JSON;
  numerical comparisons with prior studies (`[@key]`) require exact full-text `source_claims`
  in `reference/numeric-claims.md`, never recalled or freely invented values.
- Do not promote an observational association to causation. Any causal interpretation
  requires an actually justified design, assumptions and evidence; wording alone cannot supply them.
- Limitations are not a list of generic caveats. "Single-centre design" alone is not a
  limitation section; say what it does to the estimate.
- Do not claim a finding is "the first" unless S02's search supports it, and cite that.
- No stock closers: not "further studies are warranted" as the whole future-work paragraph,
  not "paves the way", not "holds promise".

## Close
```
uv run python tools/wf.py advance --note "discussion drafted; <n> words, <k> refs; disagreements addressed: <citekeys>"
```
