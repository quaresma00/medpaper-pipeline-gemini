# S24 - Package independent audit, scoped repair, user confirmation and immutable release

For a changed target/article type/initial-or-revision stage, follow `reference/journal-adaptation.md` inside a sealed journal-switch batch. Start a fresh guide context, preserve the old attempt, reuse accepted science/author facts, and update only true submission consumers.

## Purpose
Run ONE comprehensive independent reader, editor, and journal-guideline audit on the actual journal uploads, fix safe defects in the workflow, report once to the user, and upon explicit confirmation lock the read-only `<Journal_Slug>_<YYYYMMDD_HHMMSS>` release together with its bound `08_submission/independent_submission_audit.md` (`Freeze ID: <freeze_id>`). No review ZIP. Never overwrite user edits by blindly rebuilding.

## Procedure
If the package was already approved and the request is presentation-only, use the content-aware scoped amendment path. Real science or an explicitly requested additional reading follows below.

1. Start with `tools/review_round.py start --scope package` (later rounds use `--delta`). Give `exactly one independent read-only subagent` actual uploads in `bundle/manifest.json`, source documents, rendered page images/figures, official guideline snapshot, and article-specific requirements. Text copies do not replace visual inspection. Do not transfer patient data/credentials.
2. The reviewer reads as an `ordinary scientific reader` and screening editor. Require precise locations, severity, rule/evidence, the printed `reviewed_artifacts` JSON, and substantive `Reader comprehension`, `Medical presentation`, `Discussion audit` (checking Results non-restatement, literature comparison + difference reasons, mechanisms, and clinical implications), `Editorial screening and low-level errors`, and `Guideline compliance` sections. Attach before editing:
```
uv run python tools/review_round.py attach --scope package --report <actual-report.md>
```
3. Fix safe findings through one scoped `tools/rework.py batch --sealed` at S24. Journal-only changes stay in `08_submission/integration/`. Visible Word text edits must be reconciled to source and `legitimately rebuilt`; format-only changes may remain when `package_content.py verify` proves unchanged visible content. Scientific corrections need owner rules, renewed S19 approval/freeze, and delta merge. Never guess author/ethics/funding facts or insert AI-use disclosures. Every `objective low-level error` must be fixed.
4. Rebuild affected outputs only, render and visually inspect changed files, update baselines/portal fields, refresh `tools/submission_qc.py measure`, and close the source revision.
5. Run `tools/review_round.py close --scope package` with `--change`, `--kept`, and actual `--unresolved` count.
6. Report once with exact upload/checklist/preview/report paths, corrections, and unadopted reasons. Ask ONLY:

   > 本轮审阅与修改已完成。是否再进行一轮子代理审阅？若无需继续审阅，请回复“我确认这一版”。

   Preserve the answer via `tools/review_round.py decide --scope package --answer another_round|no_further_review --words "<actual words>"` (`submission_package_user_confirmed=OK`).
7. After explicit user approval, freeze the exact upload-only release (binding `08_submission/independent_submission_audit.md` to `Freeze ID: <freeze_id>` and `submission_package_independent_audit=PASS`), verify live PubMed provenance and all final gates, and close:
```
uv run python tools/package_review.py freeze
uv run python tools/package_review.py verify
uv run python tools/wf.py check
uv run python tools/wf.py advance --note "package round approved; exact uploads frozen and independent audit bound"
```

## Hard boundaries
The reviewer reports only and `never edits frozen uploads`; the main agent corrects outside immutable releases via `tools/rework.py batch`. Preserve old rounds, releases, and legacy archives. Read `reference/structural-quality.md` for bounded rework rules. The portal remains user-controlled.


