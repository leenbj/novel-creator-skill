# 📖 Novel Creator Skill v5.1 - 小说创作大师

> 基于文件级长期记忆的AI小说创作系统，支持百万字级长篇小说的持续创作。

## 核心理念

**上下文窗口 = 内存（易失）；文件系统 = 磁盘（持久）**

借鉴 [planning-with-files](https://github.com/OthmanAdi/planning-with-files) 的持久记忆模式，将所有重要小说信息写入文件系统，而非依赖对话记忆。即使写到第200万字，系统仍能准确回忆第1章的内容。

## v5.1 核心改进

### Smart State 模式
- `novel_state.md` 升级为唯一必读状态文件，内含各追踪器关键摘要
- Pre-Write Protocol 从6个必读文件降至2个（novel_plan + novel_state），按需加载其余
- **效率提升：减少70%的写前文件读取量**

### 新增功能
| 功能 | 说明 |
|------|------|
| **风格锚点** (`style_anchor.md`) | 风格DNA + 角色对话画像 + 情感节奏图 + 去AI禁忌清单 |
| **批量写作** (`/批量写作`) | 连续多章生成，自动循环 Pre-Write → 生成 → Post-Write |
| **章节修订** (`/修改章节`) | 修改已写章节 + 级联更新所有受影响的记忆文件 |
| **风格校准** (`/风格校准`) | 对比当前写作与风格锚点，检测偏离并给出修正建议 |
| **章末钩子追踪** | 每章结尾必须设计读者留存钩子，下章开头回应 |
| **情感节奏追踪** | 追踪全书情感曲线，确保节奏张弛有度 |

## 记忆系统架构

```
00_memory/
├── novel_plan.md              # 主线计划（写前必读）
├── novel_state.md             # Smart State（写前必读·核心）
├── novel_findings.md          # 发现与修正记录
├── character_tracker.md       # 角色完整档案（按需读取）
├── timeline.md                # 时间线（按需读取）
├── foreshadowing_tracker.md   # 伏笔追踪器（按需读取）
├── world_state.md             # 世界状态（按需读取）
├── style_anchor.md            # 风格锚点（按需读取）
└── chapter_summaries/
    ├── recent.md              # L1：最近10章详细摘要
    ├── mid_term.md            # L2：11-50章中等摘要
    └── archive/               # L3：50章前卷级压缩
```

### 滚动压缩策略

| 层级 | 范围 | 单章字数 | 触发条件 |
|------|------|---------|---------|
| L1 详细 | 最近10章 | 300-500字 | 每章生成 |
| L2 中等 | 11-50章 | 100-200字 | 每10章压缩 |
| L3 压缩 | 50章前 | 每卷1000字 | 每50章压缩 |

## 钩子行为（强制协议）

### Pre-Write Protocol (Smart State)
```
必读：novel_plan.md + novel_state.md（2个文件）
按需：character_tracker / timeline / foreshadowing / world_state / style_anchor / recent.md
```

### Post-Write Protocol
```
1. 提取章节摘要
2. 全量更新 novel_state.md
3. 按需更新受影响的追踪器（并行）
4. 追加 L1 摘要
5. 一致性检查
6. 更新进度 checkbox
```

### 2-Chapter Rule
每写完2章，执行角色/设定/伏笔/主线/风格的全面审计。

### Session Recovery
新会话仅需读取 novel_plan + novel_state + novel_findings 即可恢复全部状态。

## 命令列表

| 命令 | 功能 |
|------|------|
| `/拆书` | 四维分析目标小说 |
| `/仿写` | 提取写作模板 + 风格DNA |
| `/建库` | 12个知识库 + 全部记忆文件初始化 |
| `/写作` | 生成章节（完整记忆协议） |
| `/续写` | 会话恢复 + 写下一章 |
| `/批量写作` | 连续多章生成 |
| `/修改章节` | 修改已写章节 + 级联更新 |
| `/更新记忆` | 全面记忆更新 |
| `/检查一致性` | 全面一致性审计 |
| `/检索记忆` | 关键词搜索记忆文件 |
| `/伏笔状态` | 伏笔状态报告 |
| `/角色状态` | 角色状态报告 |
| `/时间线` | 时间线报告 |
| `/风格校准` | 风格偏离检测 |
| `/校稿` | 校稿编辑（全面/快速/去AI/精修） |
| `/完整流程` | 拆书→仿写→建库→写作 |

## 安装

将以下文件放入 `~/.claude/skills/` 目录：

```
~/.claude/skills/
├── novel-creator.md           # 主指令文件
├── novel-creator.json         # 配置文件
├── novel-analyzer.md          # 拆书分析器
├── novel-analyzer.json        # 分析器配置
└── templates/novel-memory/    # 记忆文件模板
    ├── novel_plan.template.md
    ├── novel_state.template.md
    ├── novel_findings.template.md
    ├── character_tracker.template.md
    ├── timeline.template.md
    ├── foreshadowing_tracker.template.md
    ├── world_state.template.md
    ├── chapter_summaries_recent.template.md
    └── style_anchor.template.md
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `novel-creator.md` | 核心指令文件，包含完整的记忆系统、钩子协议、功能模块说明 |
| `novel-creator.json` | 机器可读配置，定义所有模块、钩子、记忆架构 |
| `novel-analyzer.md` | 四维拆书分析器指令 |
| `novel-analyzer.json` | 分析器配置 |
| `templates/` | 记忆文件初始化模板，`/建库` 时使用 |

## 一致性检测引擎

检测维度覆盖：

- **角色**：性格、能力、关系、位置、对话风格
- **设定**：世界观、力量体系、势力分布、地理
- **剧情**：时间线、因果逻辑、伏笔回收、主线方向、章末钩子
- **风格**：语气、节奏、去AI化合规性

## MCP 集成

| MCP | 用途 |
|-----|------|
| Sequential | 复杂剧情逻辑分析、一致性推理 |
| Context7 | 写作技巧、文学理论 |
| Tavily | 参考资料、对标作品信息 |

## 版本历史

- **v5.1.0** - Smart State模式、风格锚点、批量写作、章节修订、风格校准、章末钩子追踪
- **v5.0.0** - 文件级长期记忆系统、三核心文件、四追踪器、滚动压缩
- **v4.0.0** - 长期记忆概念设计
- **v3.0.0** - 校稿编辑器、去AI化
- **v2.0.0** - 完整工作流、12知识库模块
- **v1.0.0** - 四维拆书分析

## License

MIT
