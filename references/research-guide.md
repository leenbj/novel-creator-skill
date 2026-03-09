# 联网调研指南

> 从 SKILL.md v8.0 第9节抽取，详细用法参考本文档。

## 概述

`/联网调研 [主题/关键词]` 是通用能力，在任何写作场景中均可调用（手动写作、半自动、全自动）。

## 执行流程

1. 运行 `python3 scripts/research_agent.py plan --genre <题材> --topic "<主题>" --project-root <目录>` 获取搜索关键词和知识缺口
2. 按关键词列表逐条联网搜索（使用当前 AI 工具的搜索能力：Claude Code WebSearch、OpenCode、Codex 等）
3. 将搜索结果通过 `python3 scripts/research_agent.py store --project-root <目录> --category "<类别>" --content "<内容>"` 存入知识库
4. 可与 `/继续写` 联动：每章写前检测知识缺口并自动补充

## 调研深度

| 深度 | 关键词数 | 适用场景 |
|------|----------|----------|
| `quick` | 5 | 日常补充、单一概念查询 |
| `standard` | 15 | 开书前调研（默认） |
| `deep` | 30 | 重大设定补充、复杂世界观 |

## 脚本命令

```bash
# 生成搜索关键词
python3 scripts/research_agent.py keywords --genre <题材> --topic "<主题>"

# 生成完整调研计划
python3 scripts/research_agent.py plan --genre <题材> --topic "<主题>" --project-root <目录> --depth standard

# 检测知识库缺口
python3 scripts/research_agent.py gaps --project-root <目录> --chapter-goal "<章节目标>"

# 存储调研结果
python3 scripts/research_agent.py store --project-root <目录> --category "<类别>" --content "<内容>" --source "<来源URL>"
```

## 知识库分类路由

| 类别关键词 | 存储文件 |
|-----------|---------|
| 世界观、体系、设定 | `02_knowledge_base/10_worldbuilding.md` |
| 历史、地理、制度、背景 | `02_knowledge_base/11_research_data.md` |
| 写作手法、风格 | `02_knowledge_base/12_style_skills.md` |
| 其他参考、分析 | `02_knowledge_base/13_reference_materials.md` |

## 与 `/继续写` 联动

使用 `--auto-research` 参数，系统在每章写作前自动检测知识缺口：

```bash
python3 scripts/novel_flow_executor.py continue-write \
  --project-root <目录> --query "<新剧情>" --auto-research
```

## 适配说明

- **Claude Code**：直接使用 WebSearch 工具执行搜索
- **OpenCode / Codex**：通过 AI 工具内置搜索能力执行
- **其他工具**：输出关键词列表供手动搜索
