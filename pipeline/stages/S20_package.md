# S20 - Assemble the submission bundle

## Purpose
Produce a folder the user can upload without editing anything. Every item present, in the
journal's required format, traceable to the rule that demanded it.

The manuscript arriving here has already been de-AI'd and language-polished at S19 with the
facts verified intact. Do not rewrite prose in this stage; assemble it.

## This stage needs the user
Now that the target journal is confirmed, collect the real administrative details:
- author names, intended order, ORCIDs, and institutional affiliations;
- corresponding author's email, address, and phone;
- exact funding agency and grant numbers (if any);
- confirmed conflicts of interest and specific ethics approval / IRB numbers.
Update `project/00_input/author_info.json` with these real details, replacing the S17 placeholders,
and refresh `project/07_manuscript/title_page.md` and `project/07_manuscript/statements.md` accordingly.

## Procedure
1. Collect and verify real author and administrative details from the user, updating `author_info.json`.
2. Re-read `08_submission/guidelines_extract.md` to extract the target journal's specific
   formatting requirements (e.g. font size 12pt vs 11pt, line spacing Double vs 1.5, margins).
3. **Render the entire bundle to publication-grade Word documents**:
   Execute the dedicated medical Word compilation pipeline:
   ```bash
   uv run python tools/docx/render_package.py --project project --csl <journal>.csl
   ```
   This engine automatically:
   - **Enforces journal typography**: Generates a dynamic reference docx template applying
     **Times New Roman**, **pure black (#000000)** headings (no blue/accent colors), zero list-bullet
     outlines, and the journal's exact requested font size and line spacing.
   - **Assembles full manuscript**: Sequentially links Title Page, Abstract (with clean Keywords at end),
     Introduction, Methods, Results, Discussion, Statements, and an explicit `# References` section.
   - **Appends Figure Legends to manuscript end**: Automatically reads `05_figures/legends.md`,
     ensures each legend conforms to the 4-element medical standard (80–150 words, concise bold title,
     panel guide, statistical markers, alphabetical abbreviations, without bloated methods text),
     and appends the `# Figure Legends` section directly after References inside `manuscript.docx`.
   - **Compiles full Word document suite**:
     - `project/08_submission/bundle/manuscript.docx`
     - `project/08_submission/bundle/title_page.docx` (standalone front matter for journals requiring detached title pages)
     - `project/08_submission/bundle/cover_letter.docx`
     - `project/08_submission/bundle/supplementary_materials.docx` (if supplementary methods or files exist)
   - **Deep WordprocessingML purification pipeline**:
     - **Zero black square marks**: Control attributes causing black margin squares (`keepNext`, `keepLines`, `pageBreakBefore`) are strictly eliminated across all XML streams (0 occurrences).
     - **Zero folding triangles**: Outline levels (`outlineLvl`) are strictly eliminated (0 occurrences) and all headings are mapped and flattened to body-level `SectionHeading` / `SubsectionHeading` (based on Normal), removing all folding triangles in Word so the text cannot be collapsed.
     - **Pure typography**: Times New Roman, pure black (#000000), un-nested hyperlinks, zero soft line breaks (down-arrows ↓).
4. Copy in the display items in the required formats: figures at the required resolution
   and colour mode (TIFF masters from `05_figures/out/`), tables as the journal wants them
   (editable tables in manuscript file or separate supplementary files).
5. Write `project/08_submission/bundle/cover_letter.md` (and render to `cover_letter.docx`): what the study asked, what it
   found, why it fits this journal specifically, the statements the journal wants in the
   letter (originality, no concurrent submission, all authors approved), suggested
   reviewers if requested, and the corresponding author block (with email, phone, physical address).
6. Write initial `project/08_submission/bundle/manifest.json` and `SUBMISSION_CHECKLIST.md`: every file in the bundle
   is cataloged with its role and guideline demand.

7. **User Human-in-the-Loop Review & Confirmation (Mandatory Pause)**:
   - Present the compiled submission bundle clearly to the user:
     "The complete submission bundle is compiled in `project/08_submission/bundle/`. Please open the Word files locally, inspect the layout, and make any human edits or formatting adjustments as you see fit."
   - **Mandatory Interactive Stop**: Do NOT proceed automatically. The agent must pause and explicitly ask the user:
     "**请确认您是否已完成人工审核与修改？确认 OK 吗？**"
   - Only after the user explicitly confirms OK may the agent proceed to Step 8.

8. **Package Freeze (Cryptographic SHA-256 Snapshot)**:
   - Immediately upon receiving user confirmation, freeze the reviewed bundle files:
     ```bash
     uv run python tools/package_review.py freeze --project project
     ```
   - This records SHA-256 hashes for all bundle files into `project/08_submission/package_review_freeze.json`, preventing any unintended tampering.

9. **Triple-Perspective Final Review by Independent Subagent (Single Pass, Zero Context Bloat)**:
   - To avoid redundant freezes, repeated reviews, and excessive token/context overhead, all pre-submission checks are unified into a single-pass **Triple-Perspective Final Review**:
     - **Role**: `Triple-Perspective Submission Reviewer` (Independent Reader + Journal Editor + Compliance Auditor).
     - **Execution**: The agent invokes this independent subagent using:
       ```bash
       uv run python tools/package_review.py prompt --project project
       ```
   - **Perspective 1: Independent Academic Reader (易读性与自明性审查)**:
     - Narrative flow & clarity: Can a biomedical researcher outside the narrow subfield follow the motivation, logic, and conclusions without confusion?
     - Are there conceptual leaps, unexplained jargon, or disjointed transitions?
     - **Self-explanatory Figures & Tables**: Can figures and tables be understood purely with their legends without referring back to Results prose? Are axes, markers, and groupings clear? Are abbreviations accessible in `statements.md`?
   - **Perspective 2: Journal Editor & Senior Peer Reviewer (学术质量与低级错误排查)**:
     - **Zero Tolerance for Low-level Defects (低级错误零容忍)**:
       * **Numerical cross-consistency**: Cross-check every number (sample sizes $N$, event rates, $p$-values, HR/OR/95% CIs) across Title Page, Abstract, Results, Tables, and Figure Legends. Strictly eliminate contradictions.
       * **Display item cross-referencing**: Verify that in-text citations like "Figure 1", "Table 2" strictly match the actual numbering, titles, and content of files in `bundle/` without mislabeling or off-by-one errors.
       * **Language hygiene**: Catch typos, double spaces, punctuation glitches, and non-standard biomedical units.
     - **Scientific Innovation & Scope Fit**: Do Title, Abstract, and Introduction sharply highlight the clinical/biological novelty and fit the target journal's Aims & Scope?
     - **Cover Letter Persuasion**: Does the letter effectively pitch the paper's importance to the Editor-in-Chief, with all mandatory declarations and complete corresponding author contact details?
   - **Perspective 3: Submission Compliance & Technical Integrity (投稿合规与格式硬审)**:
     - The subagent runs `uv run python tools/audit/audit_submission.py --project project`:
       * Physical DOCX integrity: Unpacks OpenXML, validates XML syntax, ensures non-empty paragraphs (> 0), confirms zero residual soft breaks (down-arrows ↓) and zero outline levels (`outlineLvl: 0`).
       * Target journal guidelines: Word count limits, reference caps, display item count limits, TIFF resolution (>= 300 DPI) and color spaces.
       * Mandatory declaration completeness: Ethics approval, informed consent, data availability, conflict of interest, author contributions.
   - **Output Report**:
     - The subagent writes the structured review to `project/08_submission/bundle/AUDIT_REPORT.md` (covering Executive Verdict, Perspective A Reader feedback, Perspective B Editor findings, Perspective C Compliance audit, and Prioritized Action Checklist).
   - **Verify Package Integrity**:
     - Subagent runs `uv run python tools/package_review.py verify --project project` to verify the bundle remained untouched throughout review.

10. Final tidy: `uv run python tools/wf.py clean --apply`, then resolve anything the orphan scan
    reports. The `no_orphans` gate runs here.

## Outputs
- `08_submission/bundle/manuscript.docx`
- `08_submission/bundle/title_page.docx`
- `08_submission/bundle/cover_letter.docx`
- `08_submission/bundle/manifest.json`
- `08_submission/bundle/SUBMISSION_CHECKLIST.md`
- `08_submission/bundle/AUDIT_REPORT.md`
- (plus rendered figures, tables and optional supplementary_materials.docx)

## Hard rules
- Every bundle file appears in `manifest.json`, and every manifest entry exists on disk.
- No file in the bundle that no guideline rule asks for.
- Citations must resolve. If `pandoc --citeproc` emits an unresolved-key warning, the
  bundle is not done.
- **Never bypass human review**: the agent must pause and obtain explicit user confirmation before freezing and auditing.
- **Package Freeze required**: `package_review_freeze.json` must be written before review and verified uncorrupted after review.
- **Triple-Perspective Review required**: `08_submission/bundle/AUDIT_REPORT.md` must encompass all three perspectives (Reader clarity, Editor low-level flaw check, and Compliance audit) with a `PASSED` or `READY_FOR_SUBMISSION` verdict before advancing.
- **Zero Literature Fabrication (文献绝对真实与穿透终审)**: Every cited reference must pass the deep cryptographic provenance check and physical NCBI XML cache verification in `audit_submission.py`. Any fabricated citekey, fake DOI, or unauthorized bypass script results in an immediate integrity failure and submission block.
- **Zero Data Truncation & Full Census (全量数据普查与零截断穿透审计)**: All data retrieval and cleaning code must pass the anti-truncation static audit in `audit_submission.py`. Physical raw file rows, `data_census.json`, and manuscript sample size descriptions must strictly reconcile without arbitrary truncation (`nrows=`, `.head(N)`, unapproved `.sample()`, or fake pagination breaks).
- **Strict Change Routing & Single Source of Truth**: If changes to content, data, figures or citations are requested, NEVER perform orphan edits on `manuscript_assembled.md` or `bundle/*.docx`. Always run `uv run python tools/wf.py route "<REQUEST>"`, execute `wf loop --to <STAGE>`, modify the single source of truth, and rebuild through the pipeline. Pure Word typography adjustments are the only allowed in-stage exception.
- **Base Manuscript Untouched**: The canonical base manuscript in `07_manuscript/` must remain strictly untouched throughout bundle compilation and audit. All journal-specific adaptations and outputs are strictly housed inside `08_submission/`.
- Do not fabricate a reviewer's affiliation or email when suggesting reviewers. Provide
  names and let the user supply contact details, or leave it for the portal.

## Close
```
python tools/wf.py check
python tools/wf.py advance --note "bundle complete for <journal>; human review confirmed; package frozen; audit report PASSED; <n> items"
```
