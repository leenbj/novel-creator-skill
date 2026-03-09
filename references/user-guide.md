# Novel Claude AI v1.0.0 用户指南

## 目录

1. [快速上手（5分钟开始写书）](#1-快速上手)
2. [安装配置](#2-安装配置)
3. [多LLM配置](#3-多llm配置)
4. [新手三命令](#4-新手三命令)
5. [联网调研](#5-联网调研)
6. [一键写书](#6-一键写书)
7. [中途改纲续写](#7-中途改纲续写)
8. [进阶用法](#8-进阶用法)
9. [常见问题](#9-常见问题)

---

## 1. 快速上手

三步开始写你的第一本小说：

```bash
# 步骤1：安装技能（以 Claude Code 为例）
bash scripts/install-portable-skill.sh --tool claude-code --force

# 步骤2：一键开书
/一键开书 书名="穿越大唐之我是皇帝" 题材=历史 剧情种子="现代大学生穿越到唐朝成为太子，利用现代知识治国平天下"

# 步骤3：继续写
/继续写 "太子在朝堂上首次发言，引起百官震动"
```

就这么简单。系统会自动完成世界观建模、知识库初始化、章节写作、门禁校验等全流程。

---

## 2. 安装配置

### 支持的 AI 工具

| 工具 | 安装命令 |
|------|----------|
| Claude Code | `bash scripts/install-portable-skill.sh --tool claude-code --force` |
| OpenCode | `bash scripts/install-portable-skill.sh --tool opencode --force` |
| Codex | `bash scripts/install-portable-skill.sh --tool codex --force` |
| Gemini CLI | `bash scripts/install-portable-skill.sh --tool gemini-cli --force` |
| Antigravity | `bash scripts/install-portable-skill.sh --tool antigravity --force` |

### 安装验证

安装后在对话中输入 `/一键开书` 或 `/继续写`，如果系统识别命令并提示参数，说明安装成功。

### 目录结构说明

安装后你的小说项目目录结构如下：

```
你的小说项目/
├── 00_memory/            # 记忆系统
│   ├── novel_plan.md     # 主线计划（写前必读）
│   ├── novel_state.md    # 当前状态
│   └── retrieval/        # 检索索引
├── 02_knowledge_base/    # 知识库（设定+资料）
├── 03_manuscript/        # 章节正文
├── 04_editing/           # 编辑与门禁
└── .flow/                # 执行状态（内部）
```

---

## 3. 多LLM配置

v8.0 支持多种大模型，你可以根据需要选择。

### 配置文件

在小说项目根目录创建 `.novel_writer_config.yaml`（从模板复制）：

```bash
cp scripts/novel_writer_config.template.yaml 你的项目目录/.novel_writer_config.yaml
```

### 支持的 LLM 及配置

#### OpenAI（默认）

```yaml
ai_provider: openai
model: gpt-4
# 设置环境变量 OPENAI_API_KEY 或在此填写
openai_api_key: "sk-..."
```

#### Anthropic (Claude)

```yaml
ai_provider: anthropic
model: claude-3-sonnet-20240229
# 设置环境变量 ANTHROPIC_API_KEY
```

#### Kimi 2.5 (Moonshot)

```yaml
ai_provider: kimi
model: moonshot-v1-auto  # 也可选 moonshot-v1-128k
# 设置环境变量 MOONSHOT_API_KEY
```

#### GLM-5 (智谱)

```yaml
ai_provider: glm
model: glm-4-plus  # 也可选 glm-4, glm-4-flash
# 设置环境变量 GLM_API_KEY
```

#### MiniMax 2.5

```yaml
ai_provider: minimax
model: MiniMax-Text-01
# 设置环境变量 MINIMAX_API_KEY
```

#### 本地模型

```yaml
ai_provider: local
model: qwen2.5:72b
local_api_url: "http://localhost:11434/api/generate"
```

#### 任意 OpenAI 兼容 API

```yaml
ai_provider: custom
base_url: "https://your-api-endpoint.com/v1"
model: your-model-name
api_key: "your-api-key"
```

### 环境变量速查

| LLM | 环境变量 |
|-----|----------|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Kimi | `MOONSHOT_API_KEY` |
| GLM | `GLM_API_KEY` |
| MiniMax | `MINIMAX_API_KEY` |

---

## 4. 新手三命令

### `/一键开书`

初始化一个完整的小说项目。

```
/一键开书 书名="书名" 题材=历史 剧情种子="一句话概述核心剧情"
```

**执行内容**：
1. 创建项目目录结构
2. 生成主线计划（novel_plan.md）
3. 建立知识库骨架
4. 准备第一章占位文件
5. 构建初始检索索引

**等效脚本命令**：
```bash
python3 scripts/novel_flow_executor.py one-click \
  --project-root ./我的小说 --title "书名" --genre 历史 --idea "剧情种子"
```

### `/继续写`

执行完整的写作-校验流程。

```
/继续写 "本章要写的剧情方向"
```

**执行内容**（全自动串联）：
1. RAG 检索相关章节上下文
2. 生成/补全章节正文
3. 更新记忆 → 检查一致性 → 风格校准 → 校稿
4. 门禁检查（passed=true 才解锁下一章）
5. 更新检索索引

**高级参数**：
```bash
python3 scripts/novel_flow_executor.py continue-write \
  --project-root ./我的小说 \
  --query "太子在朝堂上首次发言" \
  --candidate-k 12 \          # RAG 粗筛候选数
  --max-auto-retry-rounds 2 \ # 门禁失败自动重试次数
  --rollback-on-failure \      # 失败时回滚
  --auto-research              # 写前自动检测知识缺口
```

### `/修复本章`

门禁失败后的修复命令。

```
/修复本章
```

系统根据 `repair_plan.md` 中的修复建议，自动修复章节问题并重新提交门禁。

---

## 5. 联网调研

联网调研是 v8.0 新增的**通用能力**，在任何写作场景中都可使用。

### 手动调研

```
/联网调研 唐朝安史之乱
```

系统会：
1. 根据题材自动生成搜索关键词列表
2. 逐条联网搜索
3. 将结果存入知识库对应分类文件

### 调研深度

| 深度 | 关键词数 | 适用场景 |
|------|----------|----------|
| `quick` | 5 | 日常补充、单一概念查询 |
| `standard` | 15 | 开书前调研（默认） |
| `deep` | 30 | 重大设定补充、复杂世界观 |

### 脚本直接使用

```bash
# 生成搜索关键词
python3 scripts/research_agent.py keywords \
  --genre 历史 --topic "唐朝安史之乱"

# 生成完整调研计划
python3 scripts/research_agent.py plan \
  --genre 历史 --topic "唐朝安史之乱" \
  --project-root ./我的小说 --depth standard

# 检测知识库缺口
python3 scripts/research_agent.py gaps \
  --project-root ./我的小说 \
  --chapter-goal "主角面临兵变危机"

# 存储调研结果
python3 scripts/research_agent.py store \
  --project-root ./我的小说 \
  --category "历史背景" \
  --content "安史之乱发生于755年..." \
  --source "https://example.com"
```

### 知识库分类规则

| 类别关键词 | 存储文件 |
|-----------|---------|
| 世界观、体系、设定 | `02_knowledge_base/10_worldbuilding.md` |
| 历史、地理、制度、背景 | `02_knowledge_base/11_research_data.md` |
| 写作手法、风格 | `02_knowledge_base/12_style_skills.md` |
| 其他参考、分析 | `02_knowledge_base/13_reference_materials.md` |

### 与 `/继续写` 联动

使用 `--auto-research` 参数，系统在每章写作前自动检测知识缺口：

```bash
python3 scripts/novel_flow_executor.py continue-write \
  --project-root ./我的小说 \
  --query "太子出征西域" \
  --auto-research
```

### 适配不同工具

- **Claude Code**：直接使用 WebSearch 工具联网搜索
- **OpenCode / Codex**：通过内置搜索能力执行
- **其他工具**：输出关键词列表，用户手动搜索后通过 `store` 命令存储

---

## 6. 一键写书

一键写书是 v8.0 的核心新功能，用户只需提供简介和目标字数，系统全自动完成整本书。

### 基本用法

```
/一键写书 简介="现代青年穿越到唐朝成为太子，利用现代知识改革朝政" 目标字数=200万
```

### 执行流程

1. **解析简介** → 提取题材、核心冲突、主角目标
2. **基础调研** → 根据题材自动联网搜索背景资料
3. **一键开书** → 建模、建库、首章准备
4. **循环写作**（直到目标字数）：
   - 检测知识缺口 → 联网补充
   - `/继续写` → 门禁校验
   - 失败 → 自动修复（最多3次）
   - 每10章冲刺复盘
   - 每卷结束输出进度报告
5. **完成报告** → 全书统计

### 断点续写

写作中断后再次执行 `/一键写书`，系统自动从断点恢复，不会重复已完成的章节。

### 进度查看

```bash
# 查看当前进度
python3 scripts/auto_novel_writer.py report --project-root ./我的小说

# 查看详细状态（JSON格式）
python3 scripts/auto_novel_writer.py progress --project-root ./我的小说
```

### 生成执行计划（不实际执行）

```bash
python3 scripts/auto_novel_writer.py plan \
  --synopsis "穿越唐朝太子" \
  --target-chars 2000000 \
  --genre 历史 \
  --research-depth standard
```

### 更新进度（供外部脚本调用）

```bash
python3 scripts/auto_novel_writer.py progress \
  --project-root ./我的小说 \
  --chapter 15 \
  --chars-added 3500 \
  --gate-passed
```

---

## 7. 中途改纲续写

v1.0.0 新增功能，当故事写到中途需要调整主线走向时使用。

### 什么时候需要改纲

- 发现当前大纲的某段剧情走向不对，需要修改 `novel_plan.md`
- 预计修改会影响已标注在知识图谱中的角色状态、事件记录或伏笔
- 修改完 `novel_plan.md` 后，需要在重新开始写作**之前**对齐系统的三层索引

> ⚠️ 直接修改 `novel_plan.md` 而不执行 `/改纲续写` 会导致大纲锚点与实际规划不一致，使后续门禁配额校验失准。

### 使用步骤

**步骤 1**：编辑主线计划文件

```bash
# 直接编辑改纲内容
vim 你的小说项目/00_memory/novel_plan.md
```

修改你希望变更的剧情章节、结局设定或情节节点。

**步骤 2**：执行改纲续写命令

```
/改纲续写 --from-chapter=<起始章节号> --change-description="<说明>"
```

等效脚本：

```bash
python3 scripts/novel_flow_executor.py revise-outline \
  --project-root ./你的小说 \
  --from-chapter 35 \
  --change-description "第35章起调整主线：反派提前登场，男主阵营裂变"
```

**步骤 3**：查阅影响报告

改纲完成后，系统在项目目录生成 `00_memory/revise_outline_report.md`，内容包含：
- 本次改纲涉及的卷数与总章节数
- 知识图谱中被标记为 `cascade_pending=True` 的节点与边数量
- RAG 索引重建状态

**步骤 4**：处理级联节点（可选但推荐）

对 `cascade_pending=True` 的节点，手动审查其记录的角色状态、事件信息是否与新大纲一致，必要时更新后将 `cascade_pending` 恢复为 `False`。

**步骤 5**：恢复正常写作

```
/继续写 "（本次改纲后的第一章新剧情）"
```

### 执行结果说明

| 字段 | 含义 |
|------|------|
| `ok: true` | 锚点重算成功且报告已写入，可以继续写作 |
| `ok: false` | 锚点重算失败（通常是 `novel_plan.md` 格式有误），需修正后重试 |
| `cascade.ok: false` 但 `ok: true` | 图谱标记软失败，不阻断流程，建议手动检查图谱文件 |
| `rag.ok: false` 但 `ok: true` | RAG 索引重建软失败，不阻断流程，可手动执行 `/更新剧情索引` |

### 备份与回滚

改纲前，系统自动备份原锚点文件至 `.flow/backup_anchors_<时间戳>.json`。如需回滚改纲：

```bash
# 查看备份列表
ls .flow/backup_anchors_*.json

# 手动恢复
cp .flow/backup_anchors_20260309_143022.json 00_memory/outline_anchors.json
```

---

## 8. 进阶用法

### 风格定制

在 `.novel_writer_config.yaml` 中调整生成参数：

```yaml
temperature: 0.8    # 0.6=保守稳定 0.8=平衡 1.0=创意发散
max_tokens: 4000    # 单次生成上限
min_chapter_chars: 3000   # 章节最低字数
target_chapter_chars: 3500  # 章节目标字数
style_consistency: true     # 风格一致性检测
```

### RAG 检索调优

```bash
# 增大候选池提升召回率
python3 scripts/novel_flow_executor.py continue-write \
  --project-root ./我的小说 \
  --candidate-k 20 --top-k 6

# 强制重建索引
python3 scripts/plot_rag_retriever.py build --project-root ./我的小说

# 查询特定剧情上下文
python3 scripts/plot_rag_retriever.py query \
  --project-root ./我的小说 \
  --query "主角与反派的第一次交锋" \
  --top-k 4
```

### 门禁检查

```bash
# 手动门禁检查
python3 scripts/chapter_gate_check.py \
  --project-root ./我的小说 \
  --chapter-file ./我的小说/03_manuscript/第15章_朝堂风云.md

# 查看门禁修复建议
python3 scripts/gate_repair_plan.py \
  --project-root ./我的小说 \
  --chapter-file ./我的小说/03_manuscript/第15章_朝堂风云.md
```

### 风格指纹

```bash
python3 scripts/style_fingerprint.py \
  --project-root ./我的小说
```

### 基线评测

```bash
python3 scripts/benchmark_novel_flow.py \
  --project-root ./我的小说 --rounds 5
```

---

## 9. 常见问题

### Q: 安装后命令不生效？
A: 确认安装脚本输出无错误。重启 AI 工具后重试。检查 SKILL.md 是否被正确链接到工具的 skill 目录。

### Q: 门禁一直不通过？
A: 使用 `/修复本章` 自动修复。如果多次失败，检查 `04_editing/gate_artifacts/<章节>/gate_result.json` 查看具体失败原因。常见问题：章节字数不足、缺少对话、一致性冲突。

### Q: 如何切换大模型？
A: 修改项目根目录的 `.novel_writer_config.yaml`，更改 `ai_provider` 和 `model` 字段。确保对应的 API Key 环境变量已设置。

### Q: 一键写书中断了怎么办？
A: 直接再次执行 `/一键写书`，系统会自动检测断点并从上次位置恢复。状态保存在 `.flow/auto_write_state.json`。

### Q: 联网调研搜索不到结果？
A: 检查当前 AI 工具是否支持联网搜索。Claude Code 支持 WebSearch，其他工具可能需要手动搜索后使用 `research_agent.py store` 存储。

### Q: 如何查看写作进度？
A:
```bash
# 一键写书进度
python3 scripts/auto_novel_writer.py report --project-root ./我的小说

# 基线评测
python3 scripts/benchmark_novel_flow.py --project-root ./我的小说
```

### Q: 知识库文件太大了怎么办？
A: 知识库文件按类别自动分类。如果单个文件过大，可以手动拆分。调研日志限制为最近 500 条记录。

### Q: 如何使用本地模型（如 Ollama）？
A:
```yaml
ai_provider: local
model: qwen2.5:72b
local_api_url: "http://localhost:11434/api/generate"
```
确保 Ollama 服务已启动：`ollama serve`

### Q: 支持哪些题材？
A: 内置调研维度的题材：历史、玄幻、科幻、都市、仙侠、游戏、悬疑、言情、军事。其他题材使用通用调研维度。

### Q: 目标字数设多少合适？
A:
- 短篇试水：5-10万字
- 中篇：30-50万字
- 长篇：100-200万字
- 超长篇：200万字以上

系统会自动计算卷/章结构，每章约3500字。
