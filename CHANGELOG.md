# 更新记录 (Changelog)

执行以当前 `AGENTS.md`、`pipeline/pipeline.toml` 与激活阶段卡为准；以下为关键架构演进摘要。

## v1.32.0 — 纯 Gemini/Antigravity 原生架构、多源文献验证、高密度去冗余与防堵塞提速

- **100% 纯 Gemini / Antigravity 架构纯化**：移除全部历史异构适配层与外部私有工具依赖，统一收敛至 `pwsh` + `uv run python`、`invoke_subagent(TypeName="research" | "browser")`、多模态 `read_file` 直接审阅 PNG/PDF 及内置全仓零异构残留自测门禁。
- **去官僚化减负（保 100% 临床医学严谨性，省 50%+ 无效 Token 开销）**：移除主代理自审八股单 `executor_acceptance`（保留真正的 S11b/S18/S24 独立只读 subagent 盲审）、移除 S20 二次同刊全文对标 `journal_benchmark.md`（专注官方投稿指南与硬指标）、免除 `literature_coverage` 反向摘抄句子与 `usage.json`/`moved_to_legend.md`/`protocol_diff.md`/`polish_log.md` 空壳凑数，支持 `claims.py` 临床简写语境自动识别。
- **全链路提速与防堵塞工具链**：`os.scandir` 引擎哈希热缓存（`390ms -> 5ms`）、15 项重型纯确定性门禁 SHA-256 缓存复用、对标 PDF 文本双级缓存、`render_r.py --jobs` 并行作图、`render_preview.py --changed` 单次 Excel COM 批量导表、`selftest.py` 6 线程隔离并行，以及 [sync_claims.py](tools/manuscript/sync_claims.py)（`--reanchor`）、`polish.py section --reanchor`、[reconcile.py](tools/manuscript/reconcile.py) 自动对账与 `rework.py mark --auto-changed`。
- **多源文献验证、体裁自适应、Word 无损继承与分节均衡**：三轨文献溯源（PubMed XML + Crossref `--methodology` DOI + `Rscript citation()` / 官方权威快照）、`article_genre` 自适应配额、临床单位/分期切点豁免与统计百分比多模式、`threeline.py -> wordtables.py` 样式无损继承与内嵌宽表横向分节、复合临床 R 配方（`medpaper_clinical_forest`, `medpaper_consort_flow`, `medpaper_km_survival`）、`section_balance_health` 防引言坍缩与 `required_main_sections` 一级结构双端核验、S24 衍生层 `presentationdelta` 闭环。

## v1.30.0 – v1.31.0 — 写前 SCIE 独立审稿（S11b）、逐章即写即润色与表格预览打通

- **表图先行与写前独立 SCIE 盲审（`S07 -> S10 -> S11 -> S11b -> S08 -> S09`）**：正式正文动笔前完成三线表（`render_preview.py`）、R 统计图与独立只读 subagent SCIE 可发表性审查，支持早期 `NO_GO` 止损。
- **全章节即写即润色与反防御临床表达**：每章完成后立即执行 `polish.py section`（遵循 `reference/clinical-deai-antidefensive-writing.md`，消除 AI 套话、工程腔与实验流水账，完整保留阴性结果、研究局限与校准不确定性），并通过 `display_labels_clinical` 严禁图内副标题、裸变量名与代码术语。

## v1.20.0 – v1.29.0 — 核心科学防线基石

- **全量数据普查与原地只读挂载**：`data_manifest.py` 与 `data_sources.py` 核验源总数、分页穷尽与文件哈希，阻断 `LIMIT`/`head()`/`sample()` 采样截断。
- **语境绑定数值溯源与隔离讨论流**：`study_facts.json` + `claim_bindings.json` 逐句/逐格/逐图内统计标注绑定结局、效应尺度与分母；S16 隔离无表 `discussion_brief.md` 与 6 要素提纲并强制 `Discussion audit`。
- **版本绑定审阅、科学母版冻结与精准局部返工**：`review_round.py` + `scientific_master_freeze.json` 隔离 `07_manuscript/` 与 `08_submission/integration/`，单源 `author_info.json` 驱动题名与声明，`rework.py` 原地增量修订不回退已完成阶段。
