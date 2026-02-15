# Novel Creator Skill v7.1

中文小说全流程创作技能，支持 Codex、Claude Code、OpenCode、Gemini CLI、Antigravity 直接安装使用。

核心目标：
- 用更低上下文消耗持续写长篇小说（百万字路线可持续推进）。
- 每章强制通过门禁流程，降低跑偏与 AI 味。
- 支持样章风格提取、跨项目风格复用、题材风格引导。

## v7.1 更新

- 修复 `/继续写` 占位章误判：正文中出现“待写”不再误判为草稿。
- 优化自动成稿上下文清洗：自动去除占位标记，减少脏上下文污染。
- 补齐执行器回归测试：`scripts/test_novel_flow_executor.py` 全部通过。

## 项目结构

```text
00_memory/                 # 长期记忆与检索索引
02_knowledge_base/         # 设定与风格知识库
03_manuscript/             # 章节正文（.md）
04_editing/gate_artifacts/ # 章节门禁产物
scripts/                   # 可执行脚本
references/                # 详细说明文档
```

## 新手最简流程（推荐）

1. `/新手模式 开启`
2. `/一键开书`
3. `/继续写`
4. 门禁失败时执行 `/修复本章`

`/继续写` 默认自动串联：
`剧情检索 → 写作 → 更新记忆 → 检查一致性 → 风格校准 → 校稿 → 门禁检查 → 更新剧情索引`

## 强制门禁流程（每章不可跳过）

1. `/更新记忆`
2. `/检查一致性`
3. `/风格校准`
4. `/校稿`
5. `/门禁检查`

仅当 `gate_result.json` 中 `passed=true`，才允许进入下一章。

## 跨工具安装

统一安装脚本：`scripts/install-portable-skill.sh`

Codex:
```bash
bash scripts/install-portable-skill.sh --tool codex --force
```

Claude Code:
```bash
bash scripts/install-portable-skill.sh --tool claude-code --force
```

OpenCode:
```bash
bash scripts/install-portable-skill.sh --tool opencode --force
```

Gemini CLI:
```bash
bash scripts/install-portable-skill.sh --tool gemini-cli --force
```

Antigravity:
```bash
bash scripts/install-portable-skill.sh --tool antigravity --force
```

安装详情见：`references/multi-tool-install.md`

## 可执行脚本（真实流程）

一键开书：
```bash
python3 scripts/novel_flow_executor.py one-click \
  --project-root <项目目录> \
  --title <书名> \
  --genre <题材> \
  --idea <剧情种子>
```

继续写作：
```bash
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <项目目录> \
  --query "<新剧情>"
```

门禁检查：
```bash
python3 scripts/chapter_gate_check.py \
  --project-root <项目目录> \
  --chapter-file <章节文件>
```

剧情索引与检索：
```bash
python3 scripts/plot_rag_retriever.py build --project-root <项目目录>
python3 scripts/plot_rag_retriever.py query --project-root <项目目录> --query "<新剧情>" --top-k 4 --auto-build
```

失败修复计划：
```bash
python3 scripts/gate_repair_plan.py \
  --project-root <项目目录> \
  --chapter-file <章节文件>
```

## 命令手册（完整）

保留命令：
- `/拆书`、`/仿写`、`/建库`、`/写作`、`/续写`、`/批量写作`、`/修改章节`
- `/更新记忆`、`/检查一致性`、`/风格校准`、`/校稿`

新增命令：
- `/写全篇`、`/一键开书`、`/继续写`、`/修复本章`、`/新手模式`
- `/门禁检查`、`/更新剧情索引`、`/剧情检索`
- `/题材选风格`、`/风格提取`、`/风格迁移`、`/风格库检索`
- `/检索记忆`、`/伏笔状态`、`/角色状态`、`/时间线`、`/完整流程`

每个命令的“功能 + 输入 + 输出 + 适用场景”完整说明见：
- `SKILL.md`
- `references/command-playbook.md`

## 回归测试

执行：
```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_novel_flow_executor.py
```

当前测试覆盖：
- `one-click` 初始化
- `continue-write` 自动成稿 + 门禁通过
- 门禁失败自动重试修复（误放章节迁移）

## 详细文档

- Skill 主文档：`SKILL.md`
- 命令手册：`references/command-playbook.md`
- 门禁产物规范：`references/gate-artifacts-spec.md`
- RAG 一致性设计：`references/rag-consistency-design.md`
- 百万字路线图：`references/million-word-roadmap.md`
- 题材风格矩阵：`references/genre-style-matrix.md`
- 跨工具安装：`references/multi-tool-install.md`

