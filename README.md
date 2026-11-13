# MedPaper Gemini / Antigravity Workflow

[中文说明](README.md) | [English Documentation](README_EN.md)

一套面向医学与临床研究的 Gemini / Google Antigravity 门禁式工作流（`v1.30.0` 架构）。它把“研究想法”推进为经过全量数据核验、真实文献溯源、语境与效应尺度绑定统计结果、R 优先临床图表、写前独立 SCIE 审稿（S11b）、全章节即写即去 AI/反防御润色、版本绑定独立子代理复核和目标期刊官方规则共同校验的投稿包，而不是让 AI 一次性凭记忆拼凑一篇看似完整的论文。

当前版本：`1.30.0`　｜　流程：26 个阶段（表图先行 + 写前 SCIE 审稿）　｜　运行环境：Windows `pwsh` + Google Antigravity / Gemini (`uv run python`)

## 当前版本的使用要点

写出来的是供医学读者阅读的论文，正文按研究问题、人群、比较、结局和不确定性组织；真实近似论文全文决定结构和图表用途，不再设置机械的一刀切文献数量、字数或主图数门槛。写作入口是简明指南（`reference/medical-writing.md`）和原创示例，数据、文献与构建记录留在后台，通过 `wf status`、`wf handoff` 与话题路由按需读取，彻底消除上下文膨胀。

执行顺序采用**表图先行与写前独立审稿**：尽管保留稳定的阶段编号，在完成 `S08_methods` 后先执行 **`S10_tables` → `S11_figures` → `S11b_prewrite_review` → `S09_results` → `S12_reconcile`**，确保三线表、统计图与分析方法先行经独立子代理和用户审计是否足以发表 SCIE 原著（发现不足可原地返修，发现 `NO_GO`/低收益立即止损），再撰写 `Results` 及后续正文章节；同时 `S08`/`S09`/`S14`/`S16`/`S17(摘要)` 每写完一章 `.md` 立即执行去 AI 化、反防御写作与去工程腔润色，不再等到组装后才统一润色。

数据处理可用 Python，新医学图形默认使用 R（`reference/r-first.md`）。内置配方涵盖筛选流程图（主文默认 Figure 1）、带对齐数值列的森林图、KM 生存曲线（支持基于真实结果的零删失证明）、ROC、校准曲线、剂量反应曲线、决策曲线（DCA）和协变量平衡图；配方只读取已完成分析的结果，不会为了画图另做统计。大型外部原始数据支持通过 `tools/data_sources.py` 原地只读登记，免除数 GB 文件重复拷贝。

在表图呈现上（`v1.29.0`），全面杜绝计算机、工程和代码样描述：三线表与所有统计图内部文字（含坐标轴、图例、分面标题、图内注释、受试者入排流程图文本框及表头/单元格）必须符合医学同行评审阅读标准。S07 明确建立特征变量到临床专业标签的显示词典（`display_dictionary`），底层全面拦截 `snake_case`、模型公式语法、裸布尔值、统计包裸列名（`coef`、`fpr`）、分析报告式标题以及数据管道脚本流水账，通过不可旁路的 `display_labels_clinical` 门禁实施全流程质量防御。

Discussion 阶段采用无表格、无图表编号的纯文字写作简报（`discussion_brief.md`），动笔前先锁定 6 要素简短提纲（`discussion_outline.md`），自动拦截过分引用补充图表与复述 Results 近似句，并在 S18/S19/S24/S25 专项审计讨论质量。确定期刊后，通过 `tools/journal.py` 锁定当前官方指南：非双盲期刊直接将单源作者信息（`00_input/author_info.json`）排入 `manuscript.docx` 第一页（仅期刊明确要求或双盲时生成同源 `title_page.docx`）；指南未规定时图片单独上传、正文末尾只留图注，主表每张单独一页置于参考文献之后（严禁 AI 自行决定嵌进正文）；补充文件统一按 `Supplemental_File_<序号>_<具体描述>.<ext>` 连续命名。换刊会自动归档隔离旧规则与投稿副本，S19 冻结的科学母稿始终只读保留。返工在 S19/S24 原地修改轮次中定位真实源文件及依赖闭包（`wf rebuild`），只重建和复核受影响的材料；普通回顾性/数据库研究不再默认要求公开注册，命名报告清单推迟至 S20 选刊后仅在目标期刊明确要求时生成。

在 Antigravity 中可直接调用全局技能 `medpaper-pipeline` 启动或恢复项目，后续直接用自然语言提出修改意见。作者确认当前版的明确口令统一为 **`我确认这一版`**。工作流不会代替作者执行外部投稿系统上传。

详细演进见 [CHANGELOG.md](CHANGELOG.md)；专题执行规范见 [Antigravity 集成](reference/antigravity-integration.md)、[医学写作](reference/medical-writing.md)、[R 统计制图](reference/r-first.md)、[期刊适配](reference/journal-adaptation.md) 和 [精准返工](reference/rework-routing.md)。

## 这套工作流解决什么问题

医学论文真正困难的部分不是生成文字，而是让研究问题、数据、统计分析、文献、图表、正文和投稿文件彼此一致，并且符合目标期刊的要求。本工作流通过分阶段门禁和确定性校验阻断以下常见风险：

- 研究选题已经高度饱和，做完后缺乏发表价值；
- 数据源明明可全量获取，AI 却为省时间、上下文或算力只取前 N 条、抽样或漏翻页；
- 引用、DOI、PMID、期刊名或年份由 AI 凭记忆生成，或用旁路脚本伪造 `verified: true`；
- 正文或表格数字没有分析结果来源、张冠李戴（人群/终点/对比/比例分母错位），或表图与正文对不上；
- Methods 过长，把敏感性分析、实现细节等全部堆进主文；
- 图注重复 Results，缩写到处重复，表格和图片不像医学期刊文章；
- 作者信息过早介入，打断科学内容的形成；
- Word 文件存在标题左侧小黑点（`keepNext`/`keepLines`/`pageBreakBefore`）、折叠三角（`outlineLvl`）、非黑色字体、残留超链接或不可编辑表格；
- 投稿包缺文件，标题、作者、图表编号、补充材料和声明跨文件不一致；
- AI 擅自编造未经用户确认的伦理、基金、利益冲突、AI 使用声明或作者信息。

工作流的目标是：在保证研究有效性和材料一致性的前提下，优先寻找真实、当前、合规且接受概率较高的 SCIE 期刊（含匹配度高的 Q3、Q4 期刊），不盲目追求高影响因子而牺牲现实接受率。

## 核心处理逻辑

整个流程遵循严格的证据依赖链：

```text
研究问题(S01) → 发表可行性(S02) → 初版方案(S03) → 全量数据获取/原地登记(S04) → 探索与全精度分析(S05)
        → 冻结研究事实契约与二次评估(S06) → ≥3篇同类SCIE全文对标与图表规划(S07)
        → Methods写完即润色(S08) → 三线表(S10) → R统计图(S11) → 写前独立SCIE与图表审计(S11b) → Results写完即润色(S09) → 跨文件对账(S12)
        → 足量实时核验文献库(S13) → Introduction写完即润色(S14) → 多路由全文与用户补齐(S15) → Discussion写完即润色(S16) → 组装与摘要润色(S17)
        → 独立只读子代理可发表性审查(S18) → 审阅轮次修正与“我确认这一版”科学母稿冻结(S19)
        → 浏览器全量抓指南与选刊(S20) → 作者与声明采集(S21) → 全篇事实不变谐调润色(S22) → 原生Word构建与Portal差异预警(S23)
        → 投稿包审阅与<期刊名_时间戳>发布冻结(S24) → 独立读者/编辑/指南合规终审(S25)
```

贯穿全流程的硬约束包括：

1. **全量数据普查（Full Census）**：默认覆盖 S03 定义的完整数据范围，逐源核对源端总数、实际接收数、末页/空游标证据、复杂连接（join）唯一分析单位及原始文件/脚本 SHA-256；严禁 `LIMIT`、`TOP`、`head()`、`sample()`、`nrows=` 或固定页数截断，不可通过 `--force` 豁免。
2. **双保险文献真实性**：外部检索工具仅提供候选，正式引用必须由 `tools/pubmed/verify.py` 执行新鲜 EFetch 并绑定原始 XML 与文献库哈希，在 S13 和 S25 强制独立实时复核（中间关口支持 24 小时未变更哈希缓存）；无 PubMed 摘要的经典方法原始论文须凭已登记并核验身份的合法全文入库。
3. **全场景语境、效应尺度与分母级数值溯源**：本研究数字在 `Results`、`Abstract`、`Discussion`、三线表单元格及图内显式统计标注中均必须来自已执行的 `03_analysis/results/*.json`，并绑定对应人群、终点、对比、受控效应尺度（区分 `HR`/`RR`/`OR`）、置信水平、时间窗、表格行列头语境、比例分子/分母及图上统计字段（`claim_bindings.json`）；引用既往文献数字必须绑定已登记原文段落（`source_claims`）。
4. **去 ZIP 化独立审阅与原地局部返工**：S18/S19/S24/S25 通过 Antigravity 原生只读子代理（`invoke_subagent` + `tools/review_round.py`）开展版本绑定审阅，不再生成冗余审核 ZIP；修改意见持久化为 `tools/rework.py` 批次，在 S19/S24 原地调用上游规则并按真实依赖增量重建（`wf rebuild`），不清空后续阶段历史。
5. **科学母稿冻结与换刊隔离**：S19 收到针对当前版本的 **`我确认这一版`** 后冻结 `scientific_master_freeze.json`；S20–S25 的期刊定制全部隔离在 `08_submission/integration/`，换刊时自动归档旧尝试，绝不污染已确认的科学母稿。
6. **隐私与披露控制权**：未经明确授权，患者级数据、私密文件与密钥严禁外发；绝不擅自起草或插入 AI 使用声明。

## 在 Google Antigravity 中如何启动与恢复

### 1. 通过全局技能 `medpaper-pipeline` 在任意文件夹启动（推荐）

本机全局技能（`~/.gemini/config/skills/medpaper-pipeline/SKILL.md`）默认锚定唯一官方纯化母版 `F:\workspace\medpapaer\gemini`（外部克隆环境亦可通过环境变量 `$env:MEDPAPER_MASTER_TEMPLATE` 或 `uv run python tools/medpaper_launcher.py --template-source <目录>` 指定母版源）：

- **新论文项目（空文件夹）**：在 Antigravity 打开目标工作区，告知研究想法并唤起 `medpaper-pipeline`，Agent 会自动从官方母版复制纯化引擎骨架、配置 `.venv`、初始化 `project/.wf/state.json` 并从 `S01_intake` 启动。
- **已有论文项目**：自动执行 `uv run python tools/wf.py status`（上下文压缩后执行 `wf handoff`）恢复当前阶段。

### 2. 常用终端命令（均通过 `pwsh` 执行）

```powershell
uv run --python 3.13 python bootstrap.py       # 首次创建/校验 .venv、初始化并运行自检
uv run python tools/wf.py status               # 极简本地状态（加 --full 运行门禁诊断）
uv run python tools/wf.py handoff              # 上下文压缩后的有界恢复摘要
uv run python tools/wf.py card                 # 查看当前阶段卡片（加 --details 查看拆分详规）
uv run python tools/wf.py check                # 执行当前阶段门禁检查
uv run python tools/wf.py rebuild --dry-run    # 预览受影响产物的增量重建闭包
uv run python tools/wf.py advance --note "本阶段产出、关键决策与待决事项"
uv run python tools/wf.py doctor               # 检查环境、依赖包、Rscript、Pandoc 与接线完整性
uv run python tools/selftest.py                # 运行全套离线回归测试套件
```

## 可选环境变量配置

```powershell
$env:NCBI_API_KEY = "<你的 NCBI API key>"
$env:NCBI_API_EMAIL = "you@example.org"
```

请勿将真实密钥或私人邮箱写入仓库文件。

## 代码与工作区目录结构

```text
AGENTS.md                                  核心执行策略与按需话题路由表
.agent/rules/medpaper-pipeline.md          Antigravity IDE 工作区规则
.agents/skills/medpaper-pipeline/          Antigravity / CLI 工作流技能入口
pipeline/pipeline.toml                     25 阶段、输出与门禁的唯一机器配置
pipeline/stages/                           25 张阶段执行卡片（表图先行顺序）
reference/                                 18+ 份按需加载专题指南与 stage_details/ 拆分规程
tools/wf.py, tools/wfcore/                 状态机、增量构建、语境数值/文献/数据证明与门禁
tools/analysis/                            R/Python 全精度结果导出、原地数据源与隔离复现
tools/tables/, tools/figures/              三线表、R 默认临床统计图配方与像素级质量检查
tools/pubmed/                              PubMed/Crossref/Unpaywall 核验与全文身份登记
tools/text/, tools/manuscript/             事实不变润色、全文 PDF 对标、原生横竖版 Word 三线表构建
project/                                   单个研究课题的输入、数据、分析、稿件与投稿包目录
```

详细安装与 Antigravity 协同说明请参见 [INSTALL-ANTIGRAVITY.md](INSTALL-ANTIGRAVITY.md) 与 [reference/antigravity-integration.md](reference/antigravity-integration.md)。
