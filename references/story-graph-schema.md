# 知识图谱数据结构规范

> 状态：规划中（Phase 2 实现）

## 设计目标

用图结构（节点+边+版本）替代当前的平面文件，确保300万字规模下人物、事件、设定的一致性可机器校验。

## 核心数据结构

### 图谱文件

存储位置：`00_memory/story_graph.json`

```json
{
  "version": "1.0",
  "last_updated_chapter": 42,
  "nodes": [...],
  "edges": [...],
  "timeline": [...]
}
```

### 节点类型

| 类型 | 说明 | 必需字段 |
|------|------|---------|
| `character` | 角色 | name, role, traits, status, first_appear |
| `location` | 地点 | name, description, region |
| `faction` | 势力/组织 | name, purpose, leader, members |
| `item` | 重要物品 | name, description, owner, significance |
| `event` | 关键事件 | name, chapter, participants, outcome |
| `foreshadow` | 伏笔 | name, planted_chapter, status(planted/recalled/expired), target_chapter |
| `worldrule` | 世界观规则 | name, description, constraints |
| `power_system` | 力量体系 | name, levels, rules |

### 节点 Schema（示例：角色）

```json
{
  "id": "char_001",
  "type": "character",
  "name": "李承乾",
  "aliases": ["太子", "大郎"],
  "role": "protagonist",
  "traits": ["聪明", "谨慎", "有现代知识"],
  "status": "alive",
  "power_level": "无武力",
  "first_appear": 1,
  "last_updated": 42,
  "arc": "从迷茫穿越者到治国明君",
  "current_goal": "推动均田制改革",
  "secrets": ["穿越者身份"]
}
```

### 边类型

| 类型 | 说明 | 方向性 |
|------|------|--------|
| `ally` | 同盟 | 双向 |
| `enemy` | 敌对 | 双向 |
| `mentor` | 师徒 | 单向 |
| `subordinate` | 从属 | 单向 |
| `romantic` | 情感 | 双向 |
| `belongs_to` | 归属(角色→势力) | 单向 |
| `located_at` | 位于(角色/事件→地点) | 单向 |
| `triggers` | 引发(事件→事件) | 单向 |
| `foreshadows` | 铺垫(伏笔→事件) | 单向 |
| `owns` | 持有(角色→物品) | 单向 |

### 边 Schema

```json
{
  "id": "edge_001",
  "type": "ally",
  "source": "char_001",
  "target": "char_003",
  "strength": 0.8,
  "since_chapter": 5,
  "description": "太子提拔魏征，结为政治同盟",
  "evolution": [
    {"chapter": 5, "strength": 0.3, "note": "初次合作"},
    {"chapter": 15, "strength": 0.8, "note": "共渡危机后信任加深"}
  ]
}
```

### 时间线条目

```json
{
  "chapter": 12,
  "in_story_date": "贞观三年秋",
  "events": ["event_005", "event_006"],
  "location_changes": {"char_001": "长安→洛阳"},
  "status_changes": {"char_002": {"status": "injured"}}
}
```

## 操作协议

### 每章写后（自动）

1. 从新章节提取新增/变更的节点和边
2. 更新现有节点的 `last_updated` 和状态字段
3. 追加时间线条目
4. 校验边的一致性（不能出现已死亡角色参与新事件等）

### 改纲时（级联）

1. 标记受影响的节点和边
2. 计算影响范围（几度关联）
3. 生成级联更新报告
4. 用户确认后批量更新

### 一致性校验（门禁集成）

在 `/检查一致性` 步骤中，增加图谱校验：
- 角色状态与图谱是否一致
- 地点移动是否合理（无瞬移）
- 伏笔是否超期未回收
- 关系强度变化是否有叙事支撑

## 脚本入口（规划）

```bash
# 初始化图谱
python3 scripts/story_graph_builder.py init --project-root <目录>

# 章后更新图谱
python3 scripts/story_graph_updater.py update --project-root <目录> --chapter <章节文件>

# 图谱一致性校验
python3 scripts/story_graph_updater.py validate --project-root <目录>

# 改纲级联分析
python3 scripts/story_graph_updater.py cascade --project-root <目录> --changes <变更描述>

# 导出可视化（Mermaid格式）
python3 scripts/story_graph_builder.py export --project-root <目录> --format mermaid
```
