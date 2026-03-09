# Novel Claude AI - 小说创作大师

> **版本**: v10.0
> **状态**: 生产可用
> **支持工具**: Claude Code / Codex / OpenCode / Gemini CLI / Antigravity

中文长篇小说全流程创作技能，覆盖从模糊想法到300万字成品的完整链路。

---

## 目录

- [核心亮点](#核心亮点)
- [框架设计特点](#框架设计特点)
- [长期记忆解决方案](#长期记忆解决方案)
- [去AI味道解决方案](#去ai味道解决方案)
- [快速开始](#快速开始)
- [安装指南](#安装指南)
- [新手三命令](#新手三命令)
- [完整命令参考](#完整命令参考)
- [项目目录结构](#项目目录结构)
- [多LLM配置](#多llm配置)
- [常见问题](#常见问题)

---

## 核心亮点

### 300万字一致性保证

通过**五层协同机制**确保长篇写作不跑偏：

| 层级 | 机制 | 作用 |
|------|------|------|
| 第1层 | 五步质量门禁 | 每章强制闭环：记忆同步→一致性检查→风格校准→校稿→门禁脚本 |
| 第2层 | RAG剧情检索 | 两级检索（粗筛+精排），写前自动回读相关片段 |
| 第3层 | 知识图谱 | 节点+边+版本管理，每章自动回写，改纲级联更新 |
| 第4层 | 大纲锚点 | 全局进度条，章节推进配额约束，越界即失败 |
| 第5层 | 跨Agent审核 | 独立审稿官交叉验证，批处理10章体检 |

### 去AI味润色

基于 [humanizer skill](https://github.com/blader/humanizer) 方法论定制：
- **两遍式润色**：第一遍清除AI模式 → 第二遍AI自审残留问题
- **7大类问题检测**：AI高频词、弱化副词、意义膨胀、通用套话、论文结构、正式语体、排比三连
- **最小化改动原则**：只改有问题的地方，不破坏原有叙事

### 编辑团队协作

仿真实报社流程的多人设协作：
```
策划主编 → 写作特工 → 反AI编辑 + 连载核实官（并行）→ 总编辑判定
```

职责严格分离，从根本上消除AI幻觉、角色错乱、Agent思路污染正文三大顽疾。

---

## 框架设计特点

### 1. 铁律约束（Iron Law）

以下规则任何情况下不可违反：

| 铁律 | 说明 |
|------|------|
| 禁止跳过强制章节闭环 | 每章必须完成五步门禁 |
| 禁止绕过开书前确认 | 必须引导用户确认五要素 |
| 禁止混淆正文与元信息 | 正文不得出现 `[说明]`、`TODO` 等标记 |
| 禁止门禁失败后继续写作 | 唯一合法操作是执行 `/修复本章` |
| 禁止任意修改主线规划 | 改纲须显式执行 `/改纲续写` |

### 2. 反向刹车机制

解决AI过度"帮助解决问题"的倾向：

- **非终局章节禁止解决主线核心冲突**
- **每章必须新增至少一个未解决的次要问题**
- **章末必须留下悬念钩子**（疑问型/危机型/转折型）

### 3. 事件矩阵与冷却

防止剧情模式化（主角走到哪都踩人）：

| 事件类型 | 说明 | 冷却期 |
|----------|------|--------|
| `conflict_thrill` | 冲突爽点 | 2章 |
| `bond_deepening` | 人物羁绊 | 1章 |
| `faction_building` | 势力经营 | 2章 |
| `world_painting` | 风土人情 | 3章 |
| `tension_escalation` | 危机升级 | 2章 |

规则：刚用过的类型在冷却期内不得作为主Beat，每5章必须至少出现一次羁绊或风土人情。

### 4. 多步流水线写作

将"写一章"拆解为多步协作：

```
Beat Sheet生成 → Beat扩写（填血肉）→ 章节合成 → 门禁流程
```

强制限制单次生成的剧情跨度，让每个场景充分展开。

### 5. 低上下文策略

- 写前默认只读：`novel_plan.md` + `novel_state.md`
- 单章前置读取上限：**最多4个文件**
- RAG检索只返回Top-K片段，不回读整章
- 每10章做一次深度压缩与风格校准

---

## 长期记忆解决方案

### 问题背景

长篇小说（100万字以上）面临的核心挑战：
1. **设定遗忘**：写到后面忘记前面的设定
2. **角色漂移**：角色性格、位置、能力前后矛盾
3. **剧情断裂**：伏笔忘记回收，支线悬而未决
4. **时间线错乱**：故事时间推进不合理

### 解决架构

#### 第一层：五步质量门禁（每章强制）

```
/更新记忆 → /检查一致性 → /风格校准 → /校稿 → /门禁检查
```

每一步都产出对应的门禁产物文件，`gate_result.json` 显示 `passed: true` 才能解锁下一章。

#### 第二层：RAG剧情检索

**两级检索算法**：

1. **粗筛（BM25风格TF-IDF）**：从所有章节中筛选候选池（默认8个）
2. **精排（语义重排）**：对候选池进行语义分析，返回Top-K（默认4个）

**条件触发**：
- 轻场景（日常/过渡）自动跳过检索
- 复杂剧情才执行检索

**文件位置**：
```
00_memory/retrieval/
├── story_index.json      # 章节检索索引
├── entity_chapter_map.json  # 实体-章节映射
├── next_plot_context.md  # 当前写前上下文建议
└── chapter_meta/*.meta.json  # 章节元数据侧车文件
```

#### 第三层：知识图谱

用图结构管理角色、事件、伏笔、世界观：

```json
{
  "nodes": [
    {"id": "char_001", "type": "character", "name": "李承乾", "status": "alive", ...}
  ],
  "edges": [
    {"type": "ally", "source": "char_001", "target": "char_003", "strength": 0.8}
  ],
  "timeline": [...]
}
```

**节点类型**：角色、地点、势力、物品、事件、伏笔、世界观规则、力量体系

**边类型**：同盟、敌对、师徒、从属、情感、归属、位于、引发、铺垫、持有

**自动更新**：每章写后自动提取信息回写图谱

**改纲级联**：修改大纲时自动计算影响范围并更新关联节点

#### 第四层：大纲锚点

**进度配额约束**：

```json
{
  "total_chapters": 300,
  "current_chapter": 42,
  "current_arc": "第二卷：朝堂博弈",
  "chapters_in_arc": 40,
  "quota": {
    "min_progress": 0.14,
    "max_progress": 0.15
  }
}
```

每章写前读取全局进度条，动态注入约束。越界直接触发门禁失败。

#### 第五层：跨Agent审核

**双智能体交叉验证**：

| 写作工具 | 审核工具 |
|---------|---------|
| Claude Code | Codex |
| OpenCode | Claude Code |
| Codex | Claude Code |

**三维度审核**：
1. 逻辑与连续性硬伤
2. 阅读体验与节奏把控
3. 文笔去AI化

**防死循环机制**：
- 单章最多3轮审核
- 连续3章"有条件通过"强制暂停请求人工介入

---

## 去AI味道解决方案

### 核心原理

AI文本之所以"有AI味"，是因为大语言模型的统计算法倾向于选择"在最多情况下都说得过去"的表达——导致文字安全、中性、可预测，缺乏人类写作的具体性和个人性。

**去AI味不是删词，而是用具体细节替代抽象套话，用行动替代状态描述。**

### 两遍式润色流程

执行 `/校稿` 时必须完成两遍：

#### 第一遍：清除AI模式

逐段扫描，针对7类模式逐一处理。

#### 第二遍：AI自审

完成第一遍后，对修改稿提问：
> "这段文字哪些地方还是明显AI生成的感觉？"

列出3-5条具体问题，再次修改后输出最终版。

### 7大AI写作模式

#### 1. AI高频词汇（直接替换）

| 词/短语 | 问题 | 改法 |
|---------|------|------|
| 不禁 | 剥夺角色主动性 | 直接写角色的行动 |
| 仿佛/宛如/宛若 | 过度比喻 | 用具体感知描写替代 |
| 映入眼帘 | 陈词滥调 | 直接写看到了什么 |
| 心中暗道/暗自思忖 | 内心独白套话 | 删除或改为行动 |
| 沉声道/淡淡地说 | 对话标签膨胀 | 统一用"说"或删标签 |
| 脸色一变/身形一顿 | 反应套话 | 写具体的生理反应 |
| 嘴角微扬/勾起一抹弧度 | 微笑套话（AI特征极强） | "他笑了"或删掉 |
| 不由自主/情不自禁 | 主体性剥夺 | 改为角色主动行动 |
| 只见/此时此刻 | 场景过渡套话 | 直接切换场景 |
| 目光如炬/目光深邃 | 眼睛描写套话 | 写眼睛看向哪里 |

**示例**：
```
❌ 他不禁感到一阵心悸
✅ 他的手抖了一下

❌ 只见她嘴角微扬，勾起一抹弧度
✅ 她笑了

❌ 此时此刻，他心中暗道
✅ （删除，直接写下一个行动）
```

#### 2. 弱化副词泛滥

"微微"、"淡淡"、"缓缓"、"轻轻"、"悄然"、"默默"、"隐隐"……

**原则**：删除大部分，每千字不超过3个。

```
❌ 他微微点了点头
✅ 他点了点头

❌ 她轻轻叹了口气
✅ 她叹气
```

#### 3. 意义膨胀

AI喜欢给普通事件加上"意义深远"、"前所未有"、"可谓"等宏大标签。

**原则**：删除标签，用具体的后续影响替代。

```
❌ 这次会面意义深远
✅ 从那以后，他改变了用兵的方式
```

#### 4. 通用结论套话

"未来可期"、"前途无量"、"充满希望"等空洞结语。

**原则**：用具体的悬念、未解决的冲突、角色的下一步行动结尾。

```
❌ 展望未来，他充满希望
✅ 他把那封信折好，放进了锁匣。还有一件事没做完。
```

#### 5. 论文式段落结构

段落以"不难看出"、"由此可见"、"事实上"、"值得注意的是"开头。

```
❌ 不难看出，他已下定决心。接下来，他走向了马厩……
✅ 他走向了马厩，没有回头。
```

#### 6. 正式语体入侵小说

"于是乎"、"与此同时"、"从而"、"因而"、"诚然"、"一方面……另一方面……"

**原则**：全部删除或改为口语化/行动化表达。

#### 7. 排比三连过多

AI喜欢把事物凑成三个一组制造"全面感"。

```
❌ 他展现出了勇气、智慧和决断力
✅ 他很果断

❌ 这场战斗充满了激烈、残酷和牺牲
✅ 这场战斗死了很多人
```

### 有灵魂的写作

避免了AI模式但仍然无聊，同样是失败。好的写作特征：

- **有观点**：叙述者对事件有态度，不只是中性记录
- **节奏变化**：短句与长句交替使用
- **具体感受**：不是"他感到担忧"，而是"他的后背出了一层冷汗"
- **细节代替判断**：不是"她很聪明"，而是写她做了什么具体的聪明事

### 脚本用法

```bash
# 检测章节的AI痕迹
python3 scripts/text_humanizer.py detect --chapter-file 03_manuscript/第15章.md

# 获取可读报告
python3 scripts/text_humanizer.py report --chapter-file 03_manuscript/第15章.md

# 生成两遍式润色prompt
python3 scripts/text_humanizer.py prompt --chapter-file 03_manuscript/第15章.md
```

---

## 快速开始

### 3分钟上手

```bash
# 步骤1：安装技能
bash scripts/install-portable-skill.sh --tool claude-code --force

# 步骤2：一键开书
/一键开书 书名="穿越大唐之我是皇帝" 题材=历史 剧情种子="现代大学生穿越到唐朝成为太子，利用现代知识治国平天下"

# 步骤3：继续写
/继续写 "太子在朝堂上首次发言，引起百官震动"
```

系统会自动完成：世界观建模 → 知识库初始化 → 章节写作 → 门禁校验 → 索引更新。

---

## 安装指南

### 支持的AI工具

| 工具 | 安装命令 |
|------|----------|
| Claude Code | `bash scripts/install-portable-skill.sh --tool claude-code --force` |
| OpenCode | `bash scripts/install-portable-skill.sh --tool opencode --force` |
| Codex | `bash scripts/install-portable-skill.sh --tool codex --force` |
| Gemini CLI | `bash scripts/install-portable-skill.sh --tool gemini-cli --force` |
| Antigravity | `bash scripts/install-portable-skill.sh --tool antigravity --force` |

### 安装验证

安装后在对话中输入 `/一键开书`，如果系统识别命令并提示参数，说明安装成功。

### 手动安装

1. 复制以下目录到目标工具的skill目录：
   - `SKILL.md`
   - `novel-creator.md`
   - `novel-creator.json`
   - `templates/`
   - `references/`
   - `scripts/`

2. Claude Code 额外需要复制 `.claude/agents/` 中的Agent定义文件。

3. 安装目录命名建议：`novel-claude-ai`

---

## 新手三命令

### `/一键开书`

初始化一个完整的小说项目。

```
/一键开书 书名="书名" 题材=历史 剧情种子="一句话概述核心剧情"
```

**执行内容**：
1. 引导确认五要素（目标读者、写作风格、核心禁区、自动化等级、目标规模）
2. 创建项目目录结构
3. 生成主线计划（novel_plan.md）
4. 建立知识库骨架
5. 构建初始检索索引

### `/继续写`

执行完整的写作-校验流程。

```
/继续写 "本章要写的剧情方向"
```

**执行内容**（全自动串联）：
1. 续写前引导（询问剧情走向偏好）
2. RAG检索相关章节上下文
3. 大纲锚点配额检查
4. Beat Sheet生成与扩写
5. 章节合成与门禁校验
6. 知识图谱回写与索引更新

### `/修复本章`

门禁失败后的修复命令。

```
/修复本章
```

系统根据 `repair_plan.md` 中的修复建议，自动修复章节问题并重新提交门禁。

---

## 完整命令参考

### 新手命令

| 命令 | 功能 | 何时使用 |
|------|------|---------|
| `/一键开书` | 自动完成开书全流程 | 第一次开项目 |
| `/继续写` | 引导剧情走向并完成章节流程 | 日常推进章节 |
| `/修复本章` | 门禁失败后自动修复 | 门禁返回失败后 |
| `/新手模式` | 切换简化/高级交互层 | 按需 |

### 创作命令

| 命令 | 功能 |
|------|------|
| `/写全篇` | 模糊想法→百万字路线图 |
| `/写作` | 生成单章草稿并触发闭环 |
| `/续写` | 恢复会话状态并继续 |
| `/批量写作` | 连续生成多章 |
| `/修改章节` | 修订已写章节并级联更新 |
| `/一键写书` | 全自动写作调度 |
| `/改纲续写` | 中途改纲+级联更新 |

### 质量命令（每章必经）

| 命令 | 功能 |
|------|------|
| `/更新记忆` | 同步状态追踪器 |
| `/检查一致性` | 检查剧情/设定/时间线冲突 |
| `/风格校准` | 检测文风偏移 |
| `/校稿` | 去AI味润色 |
| `/门禁检查` | 脚本化校验发布标准 |

### 检索与记忆命令

| 命令 | 功能 |
|------|------|
| `/更新剧情索引` | 扫描章节建立索引 |
| `/剧情检索` | RAG检索相关片段 |
| `/检索记忆` | 按关键词搜索记忆 |
| `/伏笔状态` | 查看伏笔埋设/回收/超期 |
| `/角色状态` | 汇总角色当前状态 |
| `/时间线` | 查看事件时间顺序 |
| `/联网调研` | 联网搜索补充知识库 |

### 风格命令

| 命令 | 功能 |
|------|------|
| `/题材选风格` | 按题材矩阵选择基线风格 |
| `/风格提取` | 从样章提取风格到库 |
| `/风格迁移` | 将风格档案应用到章节 |
| `/风格库检索` | 检索可复用风格 |

### 分析命令

| 命令 | 功能 |
|------|------|
| `/拆书` | 拆解作品结构，提炼爽点钩子 |
| `/仿写` | 提取写法模板与风格特征 |
| `/双审` | 跨Agent双智能体审核 |

---

## 项目目录结构

```
<project-root>/
├── 00_memory/                    # 记忆系统
│   ├── novel_plan.md             # 主线计划（写前必读）
│   ├── novel_state.md            # 当前状态（写前必读）
│   ├── idea_seed.md              # 开书确认卡
│   ├── story_graph.json          # 知识图谱
│   ├── outline_anchors.json      # 大纲锚点
│   ├── event_matrix_state.json   # 事件冷却状态
│   └── retrieval/                # 检索索引
│       ├── story_index.json      # 章节检索索引
│       ├── entity_chapter_map.json
│       └── next_plot_context.md
├── 02_knowledge_base/            # 知识库（设定+资料）
│   ├── 10_worldbuilding.md       # 世界观设定
│   ├── 11_research_data.md       # 调研资料
│   ├── 12_style_skills.md        # 写作手法
│   ├── 13_reference_materials.md # 参考资料
│   ├── character_tracker.md      # 角色追踪器
│   ├── timeline.md               # 时间线
│   └── foreshadowing_tracker.md  # 伏笔追踪器
├── 03_manuscript/                # 章节正文
│   └── 第NNN章_标题.md
├── 04_editing/                   # 编辑与门禁
│   └── gate_artifacts/<chapter_id>/
│       ├── memory_update.md
│       ├── consistency_report.md
│       ├── style_calibration.md
│       ├── copyedit_report.md
│       ├── publish_ready.md
│       ├── gate_result.json
│       └── repair_plan.md
└── .flow/                        # 执行状态（内部）
    ├── auto_write_state.json     # 一键写书状态
    ├── continue_write_cache.json # 幂等缓存
    └── snapshots/                # 快照备份
```

---

## 多LLM配置

在项目根目录创建 `.novel_writer_config.yaml`：

### OpenAI（默认）

```yaml
ai_provider: openai
model: gpt-4
openai_api_key: "sk-..."
```

### Anthropic (Claude)

```yaml
ai_provider: anthropic
model: claude-3-sonnet-20240229
```

### Kimi 2.5

```yaml
ai_provider: kimi
model: moonshot-v1-auto
```

### GLM-5

```yaml
ai_provider: glm
model: glm-4-plus
```

### 本地模型

```yaml
ai_provider: local
model: qwen2.5:72b
local_api_url: "http://localhost:11434/api/generate"
```

### 环境变量

| LLM | 环境变量 |
|-----|----------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Kimi | `MOONSHOT_API_KEY` |
| GLM | `GLM_API_KEY` |
| MiniMax | `MINIMAX_API_KEY` |

---

## 常见问题

### Q: 安装后命令不生效？
A: 确认安装脚本输出无错误。重启AI工具后重试。检查SKILL.md是否被正确链接。

### Q: 门禁一直不通过？
A: 使用 `/修复本章` 自动修复。查看 `04_editing/gate_artifacts/<章节>/gate_result.json` 了解具体失败原因。

### Q: 如何切换大模型？
A: 修改项目根目录的 `.novel_writer_config.yaml`，更改 `ai_provider` 和 `model` 字段。

### Q: 一键写书中断了怎么办？
A: 直接再次执行 `/一键写书`，系统会自动检测断点并恢复。状态保存在 `.flow/auto_write_state.json`。

### Q: 目标字数设多少合适？
A:
- 短篇试水：5-10万字
- 中篇：30-50万字
- 长篇：100-200万字
- 超长篇：200万字以上

系统自动计算卷/章结构，每章约3500字。

### Q: 支持哪些题材？
A: 内置调研维度的题材：历史、玄幻、科幻、都市、仙侠、游戏、悬疑、言情、军事。其他题材使用通用调研维度。

---

## 参考文档索引

| 文档 | 内容 |
|------|------|
| `references/user-guide.md` | 从零开书用户指南 |
| `references/command-playbook.md` | 完整命令手册 |
| `references/gate-artifacts-spec.md` | 门禁产物规范 |
| `references/million-word-roadmap.md` | 百万字路线图 |
| `references/genre-style-matrix.md` | 题材风格矩阵 |
| `references/rag-consistency-design.md` | RAG一致性设计 |
| `references/story-graph-schema.md` | 知识图谱数据结构 |
| `references/outline-anchor-quota-spec.md` | 大纲锚点规范 |
| `references/beat-pipeline-spec.md` | 多步流水线写作 |
| `references/anti-resolution-cooldown-spec.md` | 反向刹车与事件冷却 |
| `references/cross-agent-review-protocol.md` | 跨Agent审核协议 |
| `references/editorial-team-protocol.md` | 编辑团队架构与协议 |
| `references/humanizer-guide.md` | 去AI味润色指南 |
| `references/research-guide.md` | 联网调研指南 |
| `references/auto-write-guide.md` | 一键写书指南 |

---

## 开发与测试

### 运行回归测试

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py
```

### 脚本入口速查

```bash
# 一键开书
python3 scripts/novel_flow_executor.py one-click \
  --project-root ./我的小说 --title "书名" --genre 历史 --idea "剧情种子"

# 继续写作
python3 scripts/novel_flow_executor.py continue-write \
  --project-root ./我的小说 --query "新剧情"

# 门禁检查
python3 scripts/chapter_gate_check.py \
  --project-root ./我的小说 --chapter-file ./我的小说/03_manuscript/第15章.md

# RAG检索
python3 scripts/plot_rag_retriever.py build --project-root ./我的小说
python3 scripts/plot_rag_retriever.py query --project-root ./我的小说 --query "剧情关键词"

# 联网调研
python3 scripts/research_agent.py plan --genre 历史 --topic "唐朝安史之乱"

# 一键写书
python3 scripts/auto_novel_writer.py plan --synopsis "简介" --target-chars 2000000
python3 scripts/auto_novel_writer.py run --project-root ./我的小说

# 基线评测
python3 scripts/benchmark_novel_flow.py --project-root ./我的小说 --rounds 5
```

---

## License

MIT License