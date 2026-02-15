# 命令手册（详细版）

## 0. 每章标准门禁（强制）
每章固定顺序：
1. `/更新记忆`
2. `/检查一致性`
3. `/风格校准`
4. `/校稿`
5. `/门禁检查`

门禁失败规则：`/门禁检查` 未通过，章节状态必须保持草稿。

## 0.1 新手最简命令（推荐）
1. `/一键开书`
2. `/继续写`
3. `/修复本章`

`/继续写` 自动执行完整章节流程，无需手动拆分命令。

## 1. 核心创作命令
`/一键开书`
- 输入：题材、剧情种子、主角目标、核心冲突、预期篇幅。
- 输出：自动完成开书建模 + 建库 + 首章写作准备。

`/继续写`
- 输入：本章目标、冲突、角色（均可选）。
- 输出：自动完成“检索→写作→门禁→索引更新”。
- 自动流程：`/剧情检索`（条件触发）→ `/写作` → `/更新记忆` → `/检查一致性` → `/风格校准` → `/校稿` → `/门禁检查` → `/更新剧情索引`。

`/修复本章`
- 输入：项目目录 + 章节文件。
- 执行：`python3 scripts/gate_repair_plan.py --project-root <项目目录> --chapter-file <章节文件>`
- 输出：`repair_plan.md`（最短修复路径）。

`/新手模式`
- 输入：`开启` 或 `关闭`。
- 输出：切换简化交互层。

`/写全篇`
- 输入：题材、剧情种子、主角目标、核心冲突、预期篇幅。
- 输出：`idea_seed.md`、`million_word_blueprint.md`、`novel_plan.md`、`novel_state.md`。

`/剧情检索`
- 输入：当前准备写的新剧情描述（冲突、人物、事件目标）。
- 执行：`python3 scripts/plot_rag_retriever.py query --project-root <项目目录> --query "<新剧情>" --top-k 4 --auto-build`
- 默认行为：条件触发（轻场景自动跳过）、片段级召回、查询缓存。
- 常用参数：`--force`（强制检索）、`--no-cache`（禁用缓存）、`--no-conditional`（每次都检索）。
- 输出：`00_memory/retrieval/next_plot_context.md`（建议回读章节 + 关键片段 + 角色关系片段）。

`/写作`
- 输入：章节目标、冲突、人物、上章结尾。
- 输出：单章草稿（必须保存为 `03_manuscript/*.md`，然后进入门禁流程）。

`/续写`
- 输入：项目目录。
- 输出：状态恢复 + 新章节草稿（进入门禁流程）。

`/批量写作`
- 输入：目标章数、每章任务点。
- 输出：多章草稿（每章都要跑门禁流程）。

`/修改章节`
- 输入：目标章节、修改要求。
- 输出：修订稿 + 影响报告 + 记忆级联更新。

## 2. 剧情索引与检索命令
`/更新剧情索引`
- 输入：项目目录。
- 执行：`python3 scripts/plot_rag_retriever.py build --project-root <项目目录>`（默认增量构建，仅重算变更章节）
- 全量重建：`python3 scripts/plot_rag_retriever.py build --project-root <项目目录> --full-rebuild`
- 输出：`00_memory/retrieval/story_index.json`、`00_memory/retrieval/entity_chapter_map.json`。

`/剧情检索`
- 输入：新剧情描述。
- 输出：`next_plot_context.md`，用于写前最小上下文读取。

## 3. 分析与建库命令
`/拆书`
- 输入：目标作品文本或信息。
- 输出：结构拆解、爽点机制、人设与开篇策略。

`/仿写`
- 输入：样章文本（建议 >=2）。
- 输出：写法模板 + 风格特征摘要。

`/建库`
- 输入：项目名、题材、核心设定。
- 输出：记忆系统与知识库初始化（章节目录为 `03_manuscript/`，知识库目录为 `02_knowledge_base/`）。

## 4. 质量命令（每章必经）
`/更新记忆`
- 输入：本章正文。
- 输出：`novel_state.md`、追踪器、摘要更新。
- 产物：`04_editing/gate_artifacts/<chapter_id>/memory_update.md`

`/检查一致性`
- 输入：本章正文 + 当前记忆文件。
- 输出：一致性风险清单 + 修正建议。
- 产物：`04_editing/gate_artifacts/<chapter_id>/consistency_report.md`

`/风格校准`
- 输入：本章正文 + `style_anchor.md`。
- 输出：风格偏移报告 + 修正建议。
- 产物：`04_editing/gate_artifacts/<chapter_id>/style_calibration.md`

`/校稿`
- 输入：校准后的章节稿。
- 输出：去AI味发布稿。
- 产物：
- `04_editing/gate_artifacts/<chapter_id>/copyedit_report.md`
- `04_editing/gate_artifacts/<chapter_id>/publish_ready.md`

`/门禁检查`
- 输入：项目目录 + 章节文件。
- 执行：`python3 scripts/chapter_gate_check.py --project-root <项目目录> --chapter-file <章节文件>`
- 输出：通过/失败结果（同时校验章节必须在 `03_manuscript/` 且为 `.md`，并检查知识库目录没有混入章节文件）。
- 产物：`04_editing/gate_artifacts/<chapter_id>/gate_result.json`

## 5. 风格系统命令
`/风格提取`
- 输入：风格名、项目目录、样章文件。
- 输出：项目风格档案 + 全局风格库索引。

`/题材选风格`
- 输入：题材、目标读者、节奏偏好。
- 输出：题材基线风格 + 项目修正项。

`/风格迁移`
- 输入：章节草稿 + 目标风格档案。
- 输出：迁移稿 + 偏移说明。

`/风格库检索`
- 输入：题材与目标效果。
- 输出：可复用风格候选与优先级。

## 6. 安装与模式命令
`/安装到多工具`
- 输入：目标工具（codex/claude-code/opencode/gemini-cli/antigravity）。
- 执行：`bash scripts/install-portable-skill.sh --tool <tool> --force`
- 输出：安装目录与入口文件。

`/新手模式`
- 输入：`开启` 或 `关闭`。
- 输出：切换结果与下一步推荐命令。
