# S14 - Introduction

## Purpose
Write the Introduction from the verified library, read full-text comparators and `notes.md`. One file,
this stage only.

## Inputs
- `06_refs/library.json` and `06_refs/deepread/` (built and deep-read in S13 + S15 so Introduction draws on verified full texts, not abstracts alone)
- `03_analysis/notes.md` -> `Introduction points`
- `01_protocol/feasibility.md` -> the gap argument, already reasoned once
- `01_protocol/protocol_final.md` -> the objective, stated exactly

## Procedure
Use the Introduction route in `reference/medical-writing.md`; settle the actual
gap-to-objective argument before writing, then read it without the literature notes.

1. Use this common clinical route, adapting it to the actual problem rather than imposing a template:
   1. The clinical problem and why it matters (burden, consequence).
   2. What is established. Cite the strongest evidence, not the most convenient.
   3. What is not established - the specific gap, narrow enough to be closable by this
      study. This is the sentence the reviewer tests the whole paper against.
   4. The objective. One sentence, matching `protocol_final.md` word for word in substance.
2. Write `project/07_manuscript/introduction.md`. Cite with pandoc markers `[@key]`, keys
   from `refs.bib` only.
3. Bind the benchmark's Introduction argument roles to exact cited passages, assess evidence
   coverage and inspect the range diagnostically. Never pad or reduce a gate target:
```
uv run python tools/manuscript/benchmark.py metrics
uv run python tools/wf.py check
```
   Later journal-specific limits apply only to the integration copy, not this scientific master.

## Outputs
- `07_manuscript/introduction.md`

## Hard rules
- ONE section file this stage. No Discussion, no Abstract.
- Every citation verified. Read the source to the depth needed to support the actual claim;
  an abstract alone is not enough for nuanced method/result comparisons.
- No results in the Introduction. No hypothesis stated as if already confirmed.
- Prefer a concrete clinical problem to stock openers. Wording flags prompt judgement,
  not automatic replacement of legitimate medical terminology.
- Do not restate the whole field, yet keep Introduction depth and proportion aligned with your S07
  comparators (`section_balance_health` warns when an Original Article Introduction is thin,
  < 50% of comparator median, or top-light; ensure clinical burden, mechanistic chain, and
  literature-gap argument are substantively developed).
- Respect configured citation floors (`literature_sufficiency`, including comparator parity warnings)
  and immediately run per-section de-AI + claim-driven clinical polish (`polish.py section --file project/07_manuscript/introduction.md --snapshot` / `--verify`, removing work-report narration while keeping balanced clinical framing and genuine evidence uncertainty) once drafted.

## Close
```
uv run python tools/wf.py advance --note "introduction drafted; <n> words, <k> refs; gap sentence: <quote it>"
```
