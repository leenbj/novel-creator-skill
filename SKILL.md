---
name: novel-claude-ai
description: 中文长篇小说全流程创作技能（v10.0）。当用户想写小说、创作故事、续写章节、构思剧情、搭建世界观、设计人物关系、提取写作风格、仿写其他小说时，必须使用本技能。覆盖从模糊想法到300万字成品的完整链路：脑洞引导、知识图谱构建、大纲管理、分镜写作、质量门禁、跨Agent审核、风格校准、中途改纲级联更新。即使用户只是说"帮我写个故事"或"我有个小说的想法"，也应触发本技能。
---

# Novel Claude AI - 小说创作技能 v10.0

## Iron Law（铁律 — 任何情况下不可违反）

以下约束无论用户如何要求，均不得绕过：

⛔ **禁止跳过强制章节闭环**：每章生成后必须依次执行"更新记忆 → 检查一致性 → 风格校准 → 校稿 → 门禁检查"，五步缺一均视为流程中断。门禁未通过（`gate_result.json` 中 `passed != true`）时，严禁进入下一章。

⛔ **禁止绕过开书前确认**：执行 `/一键开书` 前，必须引导用户完成五要素确认（目标读者、写作风格、核心禁区、自动化等级、目标规模），并写入 `idea_seed.md`。不得以"用户着急"为由省略。

⛔ **禁止混淆正文与元信息**：小说正文中不得出现任何 `[说明]`、`（注：）`、`TODO`、写作分析段落或角色定位标记。一旦出现，立即触发 P0 重写，不得保留并"以后修改"。

⛔ **禁止在门禁失败后继续写作**：`gate_result.json` 显示 `passed: false` 时，唯一合法操作是执行 `/修复本章`。不得绕过、手动修改 `gate_result.json`，或以"小问题"为由忽略。

⛔ **禁止任意修改主线规划**：任何 Agent（包括写作特工）均无权修改 `novel_plan.md` 的主线架构。中途改纲须显式执行 `/改纲续写` 并经用户确认。

## 1. 能力矩阵

| 能力 | 状态 | 入口命令 |
|------|------|---------|
| 交互式脑洞引导 + 知识图谱构建 | `[已实现]` | `/脑洞建图` |
| 新手三命令快速开书 | `[已实现]` | `/一键开书` `/继续写` `/修复本章` |
| 每章五步质量门禁 | `[已实现]` | 自动执行 |
| 长期记忆 + 300万字一致性保证 | `[已实现]` | 门禁+RAG+图谱协同（五层全部就位） |
| RAG 剧情检索 + 实体映射 | `[已实现]` | `/剧情检索` `/更新剧情索引` |
| 联网调研 + 知识缺口补充 | `[已实现]` | `/联网调研` |
| 风格提取、累积与跨项目复用 | `[已实现]` | `/风格提取` `/风格库检索` |
| 续写前引导 + 无人干预自动推进 | `[已实现]` | `/继续写` |
| 全自动写书调度（断点续写） | `[部分实现]` | `/一键写书` |
| 小说仿写（联网拆解 + 魔改） | `[部分实现]` | `/仿写` `/拆书` |
| 中途改纲 + 级联更新 | `[已实现]` | `/改纲续写` |
| 大纲锚点 + 进度配额强约束 | `[已实现]` | 自动集成 |
| 多步流水线写作（Beat Sheet） | `[已实现]` | 自动集成 |
| 反向刹车（Anti-Resolution） | `[已实现]` | 自动集成 |
| 事件矩阵 + 冷却机制 | `[已实现]` | 自动集成 |
| 跨Agent双智能体审核 | `[已实现]` | `/双审` |
| 读者群体 + 写作风格强制确认 | `[已实现]` | `/一键开书 --target-audience --writing-style` |

### 300万字一致性保证机制

长期记忆不是单一功能，而是多层机制协同：

| 层级 | 机制 | 状态 |
|------|------|------|
| 第1层 | 每章5步门禁（记忆同步+一致性+风格+校稿+门禁脚本） | `[已实现]` |
| 第2层 | RAG 剧情检索（两级粗筛精排，写前自动回读相关片段） | `[已实现]` |
| 第3层 | 知识图谱（节点+边+版本，每章回写，改纲级联） | `[已实现]` |
| 第4层 | 大纲锚点（全局进度条，章节推进配额，越界即失败） | `[已实现]` |
| 第5层 | 跨Agent审核（独立审稿官交叉验证，批处理10章体检） | `[已实现]` |

5层全部就位，可支撑300万字规模的剧情一致性。知识图谱每章自动回写 + 大纲锚点强约束 + 跨Agent审核三重保障，从根本上消除全局性剧情漂移。

## 2. 新手三命令

| 命令 | 说明 |
|------|------|
| `/一键开书` | 输入题材与剧情种子，自动完成建模 + 建库 + 首章准备 |
| `/继续写` | 自动执行"检索 → 写作 → 门禁 → 索引更新"全链路 |
| `/修复本章` | 门禁失败后自动生成最短修复路径 |

新手模式：`/新手模式 开启`（默认）；高级用户：`/新手模式 关闭`

## 3. 开书前强制确认（写前必过）

执行 `/一键开书` 或 `/脑洞建图` 前，必须引导用户确认以下要素并写入 `00_memory/idea_seed.md`：

1. **目标读者**：年龄段、渠道（起点/番茄/出版）、口味偏好
2. **写作风格**：历史正文 / 网文爽文 / 文艺 / 悬疑推理 / 言情细腻（参照题材风格矩阵）
3. **核心禁区**：不能写什么（敏感题材、读者雷点）
4. **自动化等级**：手动（每章确认）/ 半自动（每10章确认）/ 全自动
5. **目标规模**：总字数、预期卷数、单章字数范围

用户回答"不确定"时：基于题材和读者群体，给出 2-3 个推荐选项供选择。

确认结果直接绑定后续生成参数（温度、对话占比、句长节奏、爽点密度等）。

## 4. 强制章节闭环

每次生成新章节后固定执行，按顺序逐项勾选，任何一项未通过都 ⛔ 禁止进入下一章：

- [ ] `/更新记忆` ⚠️ — 同步章节变化到状态追踪器。**跳过后果**：角色状态、伏笔、时间线等关键信息失去追踪，后续章节将产生设定冲突。
- [ ] `/检查一致性` ⚠️ — 检查剧情/设定/角色/时间线冲突。**跳过后果**：矛盾在后续章节累积，到百章后几乎无法修复。
- [ ] `/风格校准` ⚠️ — 检测并修正文风偏移（题材基调、句长节奏、对话比例）。**跳过后果**：风格逐章漂移，读者流失率上升。
- [ ] `/校稿` ⛔ — 两遍式去AI味润色：清除24类AI模式 → 自审剩余AI感 → 二次修改。解决翻译腔、过度总结、对话同质化。**跳过后果**：正文保留明显AI痕迹，读者识别后丧失沉浸感，直接影响完结率。详见 `references/humanizer-guide.md`。
- [ ] `/门禁检查` ⛔ — 脚本化校验发布标准（`gate_result.json` `passed: true` 方可解锁下一章）。**跳过后果**：违反 Iron Law，流程强制中断。

**为什么不能跳过**：长篇小说的设定矛盾和风格漂移会随章节指数级放大。门禁每章多花10分钟，可以避免后期30章的全面返工。

## 5. 低上下文策略

- 写前默认只读：`00_memory/novel_plan.md`、`00_memory/novel_state.md`
- 新剧情优先执行 `/剧情检索`，只读取 `next_plot_context.md` 推荐的 Top 片段
- 单章前置读取上限：**最多 4 个文件**
- 每 10 章做一次深度压缩与深度风格校准

## 6. 五大工作模式

| 模式 | 流程 | 适用场景 | 状态 |
|------|------|---------|------|
| 从模糊想法 | `/脑洞建图` → `/一键开书` → `/继续写` → 章节闭环 | 只有一个灵感 | `/脑洞建图` 规划中，其余已实现 |
| 从样章仿写 | `/仿写` → `/风格提取` → `/题材选风格` → `/继续写` → 章节闭环 | 模仿已有作品 | 部分实现 |
| 已有项目续写 | `/续写` → `/继续写` 或 `/批量写作` → 章节闭环 | 中断后恢复 | 已实现 |
| 中途改纲 | `/改纲续写` → 级联更新 → `/继续写` → 章节闭环 | 剧情走向需要调整 | 已实现 |
| 全自动 | `/一键写书` → 系统自动循环至目标字数 | 完全托管 | 部分实现（调度框架就绪） |

详细步骤教程见 `references/user-guide.md`。

## 7. 长篇强约束机制

以下机制为300万字级别长篇的核心保障，详细规范见各参考文档。

### 7.1 知识图谱（替代平面文件）

用图结构（节点+边+版本）管理角色、事件、伏笔、世界观规则。每章写后自动提取信息回写图谱，改纲时级联更新。
→ 详见 `references/story-graph-schema.md`

### 7.2 大纲锚点与进度配额

每章写前读取全局进度条，动态注入约束（"当前第X章，距离目标还有200章，本章严禁超过当前节点剧情"）。越界直接触发门禁失败。
→ 详见 `references/outline-anchor-quota-spec.md`

### 7.3 多步流水线写作

将"写一章"拆解为：生成 Beat Sheet（分镜头）→ 按 Beat 扩写血肉 → 串联合成。强制限制单次生成的剧情跨度，让每个场景充分展开。
→ 详见 `references/beat-pipeline-spec.md`

### 7.4 反向刹车 + 事件冷却

- 非终局章节禁止解决主线核心冲突，强制保留悬念
- 事件分类池（冲突爽点/人物羁绊/势力经营/风土人情/危机升级），冷却窗口防模式化
- 非冲突场景中强制埋设微型伏笔
→ 详见 `references/anti-resolution-cooldown-spec.md`

### 7.5 跨Agent双智能体审核

- 逐章审核：写作工具完成 → 不同工具审核（Claude写Codex审，反之亦然）
- 批处理审核：每10章由"极严苛老书虫"人设审核官做三维度体检（逻辑硬伤/阅读体验/去AI化）
- 防死循环：单章最多3轮审核，连续3章"有条件通过"则强制暂停请求人工介入
→ 详见 `references/cross-agent-review-protocol.md`

## 8. 命令表

### 新手命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/一键开书` | 自动完成开书全流程 | 第一次开项目 |
| `/继续写` | 引导剧情走向 → 自动串行完整章节流程 | 日常推进章节 |
| `/修复本章` | 门禁失败后自动修复 | 门禁返回失败后 |
| `/新手模式` | 切换简化/高级交互层 | 按需 |

### `/继续写` 的续写前引导机制

每次执行 `/继续写` 时，系统在写作前自动执行：

1. **引导提问**：向用户询问本章的剧情走向偏好（"你希望本章发生什么？有什么新的脑洞吗？"）
2. **脑洞拓展**：基于当前大纲和知识库，提供 2-3 个可能的剧情走向供选择
3. **用户确认**：用户选择一个方向，或提供自己的想法
4. **兜底机制**：如果用户回复"不确定"/"随便"/"自动"，则按 `novel_plan.md` 当前节点自动推进，无需人工干预
5. **全自动模式**：如果在开书确认卡中选择了"全自动"等级，跳过引导直接按大纲写作

### 创作命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/写全篇` | 模糊想法 → 百万字路线图 | 开新书或大纲重建 |
| `/写作` | 生成单章草稿并触发闭环 | 手动推进单章 |
| `/续写` | 恢复会话状态并继续 | 中断后恢复 |
| `/批量写作` | 连续生成多章 | 快速推进 |
| `/修改章节` | 修订已写章节并级联更新 | 章节返工 |
| `/改纲续写` | 中途改纲 + 锚点重算 + 图谱级联 + RAG 重建 | 调整主线走向后继续写作 |
| `/一键写书` | 全自动写作调度 | 完全托管 |

### `/改纲续写` 使用说明

**适用场景**：发现主线走向需要调整，修改了 `novel_plan.md` 之后，必须通过此命令重新对齐系统的三层索引（大纲锚点 + 知识图谱 + RAG 索引），然后才能继续写作。

**执行前置条件**（顺序不可颠倒）：
1. 手动编辑 `00_memory/novel_plan.md`，完成改纲内容
2. 确认改纲影响的起始章节（`--from-chapter`），即从第几章开始剧情走向已发生变化

**三步级联流程**：
1. **锚点重算**（必须成功，否则中止）：备份当前 `outline_anchors.json` → 从修改后的 `novel_plan.md` 重新计算所有大纲锚点
2. **图谱级联标记**（依赖锚点重算成功）：将 `last_updated >= from_chapter` 的知识图谱节点标记为 `cascade_pending=True`，生成级联影响报告
3. **RAG 索引重建**（依赖锚点重算成功）：调用 `plot_rag_retriever.py build` 全量重建检索索引

**脚本执行**：
```bash
python3 scripts/novel_flow_executor.py revise-outline \
  --project-root <项目目录> \
  --from-chapter <起始章节号> \
  --change-description "<本次改纲的简要说明>" \
  [--emit-json]
```

**参数说明**：

| 参数 | 类型 | 必选 | 说明 |
|------|------|------|------|
| `--project-root` | 路径 | 是 | 小说项目根目录 |
| `--from-chapter` | 整数（≥1） | 是 | 改纲影响的起始章节号 |
| `--change-description` | 字符串 | 否 | 本次改纲的简要说明（写入报告） |
| `--emit-json` | 开关 | 否 | 追加输出 JSON 结果到 stdout |

**成功判定**：`ok = anchors_recalculated AND report_written`（图谱标记失败和 RAG 构建失败为软失败，不影响 `ok`）

**产物**：
- `.flow/backup_anchors_<时间戳>.json`：改纲前的锚点备份
- `00_memory/outline_anchors.json`：重算后的新锚点
- `00_memory/revise_outline_report.md`：本次改纲影响范围报告（卷章总数、级联节点数、RAG 状态）

**改纲后续操作**：检查报告确认级联节点无误 → 对 `cascade_pending=True` 的节点做人工审核或自动修正 → 执行 `/继续写` 恢复正常写作流程

### 质量命令（每章必经）

| 命令 | 功能 |
|------|------|
| `/更新记忆` | 同步状态追踪器 |
| `/检查一致性` | 检查剧情/设定/时间线冲突 |
| `/风格校准` | 检测文风偏移 |
| `/校稿` | 去AI味润色 |
| `/门禁检查` | 脚本化校验发布标准 |

### 检索与记忆命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/更新剧情索引` | 扫描章节建立索引 | 门禁通过后 |
| `/剧情检索` | RAG 检索相关片段 | 每章写前 |
| `/检索记忆` | 按关键词搜索记忆 | 定位历史设定 |
| `/伏笔状态` | 查看伏笔埋设/回收/超期 | 写前确认 |
| `/角色状态` | 汇总角色当前状态 | 群像章节前 |
| `/时间线` | 查看事件时间顺序 | 跨章跳时叙事 |
| `/联网调研` | 联网搜索补充知识库 | 知识缺口补充 |

### 风格命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/题材选风格` | 按题材矩阵选择基线风格 | 开书定风格 |
| `/风格提取` | 从样章提取风格到库 | 用户提供样章 |
| `/风格迁移` | 将风格档案应用到章节 | 切换文风 |
| `/风格库检索` | 检索可复用风格 | 选风格困难时 |

### 分析命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/拆书` | 拆解作品结构，提炼爽点钩子 | 学习目标作品 |
| `/仿写` | 提取写法模板与风格特征 | 模仿样章文风 |

### 规划中命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/脑洞建图` | 交互式脑洞拓展 + 知识图谱构建 | 只有模糊想法时 |
| `/双审` | 跨Agent双智能体审核 | 每10章或手动触发 |
| `/完整流程` | 串联全链路 | 一次性跑通 |

## 9. 脚本入口

| 脚本 | 用途 |
|------|------|
| `python3 scripts/novel_flow_executor.py one-click` | `/一键开书` |
| `python3 scripts/novel_flow_executor.py continue-write --project-root <目录> --query "<新剧情>"` | `/继续写`（全功能默认开启，无需额外参数） |
| `python3 scripts/novel_flow_executor.py revise-outline --project-root <目录> --from-chapter <N> --change-description "<说明>"` | `/改纲续写`（锚点重算 + 图谱级联 + RAG 重建） |
| `python3 scripts/plot_rag_retriever.py build/query` | `/更新剧情索引` `/剧情检索` |
| `python3 scripts/chapter_gate_check.py` | `/门禁检查` |
| `python3 scripts/gate_repair_plan.py` | `/修复本章` |
| `python3 scripts/auto_novel_writer.py` | `/一键写书` |
| `python3 scripts/style_fingerprint.py` | `/风格提取` |
| `python3 scripts/research_agent.py` | `/联网调研` |
| `python3 scripts/benchmark_novel_flow.py` | `/评测基线` |
| `python3 scripts/story_graph_builder.py` | 知识图谱 CRUD / 校验 / Mermaid 导出 |
| `python3 scripts/outline_anchor_manager.py` | 大纲锚点初始化 / 配额检查 / 推进 |
| `python3 scripts/event_matrix_scheduler.py` | 事件矩阵冷却 / 推荐 / 记录 |
| `python3 scripts/anti_resolution_guard.py` | 反向刹车校验 / 约束 prompt 生成 |
| `python3 scripts/beat_sheet_generator.py` | Beat Sheet 生成 / 扩写提示 / 校验 |
| `python3 scripts/chapter_synthesizer.py` | 章节合成 / 合成稿质量校验 |
| `python3 scripts/cross_agent_reviewer.py` | 跨Agent审核任务生成 / 结果记录 |
| `python3 scripts/story_graph_updater.py` | 章节完成后自动提取信息更新图谱 |
| `python3 scripts/interactive_ideation_engine.py` | 交互式脑洞引导 5 轮收敛 / 产出物生成 |
| `python3 scripts/text_humanizer.py` | AI痕迹检测 / 两遍式润色 prompt 生成（自动集成到章节写作流程） |
| `python3 scripts/editorial_team_manager.py` | 编辑团队状态管理：快照/审核记录/状态查询/人工介入检测 |

**`continue-write` 标准用法（v10.0，全功能默认开启）：**

```bash
# 标准用法：知识图谱/大纲锚点/Beat Sheet/AI痕迹纠正/风格更新均自动激活
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <项目目录> --query "<新剧情>"

# 高级用户：按需关闭部分功能
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <项目目录> --query "<新剧情>" \
  --no-beat-sheet --no-constraints --no-graph-update
```

完整参数说明见 `references/command-playbook.md`。

## 10. 参考文档导航

根据你的场景选择对应文档：

| 你想做什么 | 读哪个文档 |
|-----------|-----------|
| 第一次使用，从零开书 | `references/user-guide.md` |
| 查看某个命令的完整参数 | `references/command-playbook.md` |
| 理解门禁产物和通过标准 | `references/gate-artifacts-spec.md` |
| 规划百万字级别的卷章结构 | `references/million-word-roadmap.md` |
| 选择合适的写作风格 | `references/genre-style-matrix.md` |
| 理解 RAG 检索的设计原理 | `references/rag-consistency-design.md` |
| 使用联网调研功能 | `references/research-guide.md` |
| 使用全自动写书功能 | `references/auto-write-guide.md` |
| 执行 /校稿 去AI味润色 | `references/humanizer-guide.md` |
| 了解知识图谱数据结构 | `references/story-graph-schema.md` |
| 了解大纲锚点与进度配额 | `references/outline-anchor-quota-spec.md` |
| 了解多步流水线写作 | `references/beat-pipeline-spec.md` |
| 了解反向刹车与事件冷却 | `references/anti-resolution-cooldown-spec.md` |
| 了解跨Agent审核协议 | `references/cross-agent-review-protocol.md` |
| 了解脑洞引导流程 | `references/interactive-brainstorming-playbook.md` |
| 仿写或魔改已有小说 | `references/adaptation-workflow.md` |
| 了解编辑团队架构与工作协议 | `references/editorial-team-protocol.md` |

## 11. Agent 编辑团队（`/启动编辑团队`）

### 11.1 为什么需要编辑团队

单 Agent 写作存在三个根性问题：
1. **AI 幻觉**：写作 Agent 可能捏造从未出现过的地名、人名、设定规则
2. **角色错乱**：角色被放错位置、被赋予其不具备的能力、或语气风格全部雷同
3. **Agent 思路污染正文**：写作过程中的分析思路、角色定位说明、meta注记渗入小说正文

编辑团队通过职责严格分离，在生产流程中内建三道防火墙。

### 11.2 团队架构（真实报社模型）

```
用户
  │
  ▼
总编辑（Claude Code 主 Agent）
  │  协调所有子 Agent，汇总报告，作最终裁判
  ├──► 策划主编（planning-editor）
  │     读规划文件 → 生成 Chapter Brief → 传给写作特工
  │
  ├──► 写作特工（novelist）
  │     只接收 Brief，只输出纯正文，严格隔离 meta 信息
  │
  ├──► 反AI编辑（anti-ai-editor）      ┐ 并行
  └──► 连载核实官（consistency-reviewer）┘ 审核
```

### 11.3 触发命令

```
/启动编辑团队 [--项目路径 <路径>] [--章节 <N>] [--模式 单章|批量]
```

**单章模式**（默认）：完整走一章的生产+审核流程。
**批量模式**：连续生产并审核多章（每章之间等待门禁通过）。

### 11.4 执行步骤（Claude Code 按此流程操作）

当收到 `/启动编辑团队` 时，Claude Code 执行：

```
步骤 0：准备上下文快照
  python3 scripts/editorial_team_manager.py snapshot --project-root <路径>
  → 读取输出中的 context_file 路径和 current_chapter_no

步骤 1：创建团队
  TeamCreate(team_name="editorial-team-ch{N}", description="第N章编辑生产")

步骤 2：召唤策划主编
  Agent(subagent_type="planning-editor", team_name=..., name="planning-editor",
        prompt="请读取以下文件并生成第N章 Chapter Brief：
                novel_plan.md={路径}
                novel_state.md={路径}
                character_tracker.md={路径}")
  → 等待 CHAPTER_BRIEF_START...CHAPTER_BRIEF_END

步骤 3：召唤写作特工
  Agent(subagent_type="novelist", team_name=..., name="novelist",
        prompt="[将完整 CHAPTER_BRIEF 原文粘贴于此]")
  → 等待 NOVEL_TEXT_START...NOVEL_TEXT_END

步骤 4：并行召唤审核者（同时发起）
  Agent(subagent_type="anti-ai-editor", team_name=..., name="anti-ai-editor",
        prompt="请对以下章节正文执行去AI化审核：\n[NOVEL_TEXT]")
  Agent(subagent_type="consistency-reviewer", team_name=..., name="consistency-reviewer",
        prompt="请核查以下章节正文，项目路径：<路径>\n[NOVEL_TEXT]")
  → 等待两份报告

步骤 5：总编辑汇总判定
  - 如有 P0 → 返工（最多2次）
  - 无 P0 → 使用反AI编辑润色后的版本
  - 记录结果：
    python3 scripts/editorial_team_manager.py record-review \
      --project-root <路径> --chapter N --stage final --verdict pass/conditional/rewrite \
      --p0 X --p1 Y --p2 Z

步骤 6：输出最终章节包
  将 FINAL_CHAPTER_PACKAGE 写入 03_manuscript/第N章-[标题].md

步骤 7：检查是否需要人工介入
  python3 scripts/editorial_team_manager.py need-human --project-root <路径>
  → 如 need_human=true，暂停并向用户汇报

步骤 8：关闭团队
  SendMessage(type="shutdown_request") × 各子 Agent
  TeamDelete()
```

### 11.5 正文隔离协议（防止 Agent 思路污染正文）

这是最关键的安全机制：

| Agent | 允许的输出内容 | 严禁的输出内容 |
|-------|--------------|--------------|
| 写作特工 | `NOVEL_TEXT_START` 到 `NOVEL_TEXT_END` 之间的纯小说正文 | 分析说明、角色定位、写作思路、meta注记、括号说明 |
| 反AI编辑 | 报告 + `HUMANIZED_TEXT` 标记内的净化正文 | 在润色后正文中插入任何注释 |
| 连载核实官 | 结构化核查报告 | 直接修改正文 |
| 总编辑 | 最终章节包（正文与报告分区） | 将审核意见混入正文区 |

**P0 检测触发器**：正文中出现以下任意内容，立即触发 P0 强制重写：
- `[` `]` 括号包裹的说明文字（如 `[此处填写]`、`[角色A]`）
- `（注：）`、`【写作说明】`、`TODO`、`作者按`等元信息标记
- 写作 Agent 的推理过程或分析性段落出现在正文区域内

### 11.6 角色一致性强制校验清单

连载核实官每章必须核查的项目（不得省略）：

- [ ] 所有出场角色的当前地理位置与 character_tracker 一致
- [ ] 所有出场角色的能力边界未被违反
- [ ] 已确认死亡/离开的角色未在正文中复活（非明确的回忆/幻觉场景）
- [ ] 本章时间点与上一章时间点的推进逻辑合理
- [ ] 正文中未出现规划文件和角色档案中从未注册的新地名/人名/组织

### 11.7 自由创作与规划遵守的平衡机制

编辑团队在以下两类规则之间保持严格分工：

**策划主编负责遵守（硬约束）**：
- 当前章节的情节任务必须推进
- 本章禁区（不得提前触碰的剧情）必须遵守
- 角色位置和状态的真实性

**写作特工负责创新（软自由）**：
- 章节入口角度（8种模式轮换，不重复）
- 场景的具体呈现方式
- 对话的具体内容和节奏
- 细节描写的选择

**没有任何 Agent 有权限做的事**：
- 改变小说主线规划
- 让角色提前到达不该到的地方
- 发明规划文件外的重要设定

### 11.8 状态管理脚本

```bash
# 生成上下文快照（团队启动前必须运行）
python3 scripts/editorial_team_manager.py snapshot --project-root <路径>

# 记录单次审核结果
python3 scripts/editorial_team_manager.py record-review \
  --project-root <路径> --chapter N --stage final \
  --verdict pass --p0 0 --p1 2 --p2 3

# 查看最近10章审核历史
python3 scripts/editorial_team_manager.py status --project-root <路径>

# 检测是否需要人工介入
python3 scripts/editorial_team_manager.py need-human --project-root <路径>
```
