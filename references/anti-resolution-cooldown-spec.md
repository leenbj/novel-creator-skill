# 反向刹车与事件冷却机制规范

> 状态：规划中（Phase 2/3 实现）

## 一、反向刹车（Anti-Resolution）

### 问题背景

AI 有强烈的"帮助解决问题"倾向，导致它太喜欢在章节末尾给出大团圆或快速化解矛盾。对于长篇小说，这会导致剧情推进过快、悬念消耗殆尽。

### 核心规则

1. **非终局章节禁止解决主线核心冲突**
   - "核心冲突"定义来自 `novel_plan.md` 和 `outline_anchors.json`
   - 终局章节由大纲锚点明确标记

2. **每章必须新增至少一个未解决的次要问题**
   - 可以是新角色登场带来的疑问
   - 可以是旧角色的异常行为
   - 可以是环境/局势的微妙变化

3. **章末钩子强制检查**
   - 章节最后200字必须包含"悬念元素"
   - 悬念类型：疑问型（"那个人是谁？"）、危机型（"门外传来脚步声"）、转折型（"信封里只有一张白纸"）

4. **允许解决的范围**
   - 当前章可以解决**次要冲突**（支线任务、小危机）
   - 可以推进主线但不得闭合
   - 可以给予阶段性胜利，但必须伴随新的代价或风险

### 门禁集成

在 `/检查一致性` 中增加反向刹车校验：
- 本章是否解决了不该解决的核心冲突 → 失败
- 章末是否缺少悬念元素 → 警告
- 本章是否引入了新的未解决问题 → 未引入则警告

### 写作 Prompt 注入

每章写作指令中自动追加：
```
重要约束：不要在本章解决核心矛盾「{core_conflict}」。
必须保留悬念，制造新的次要障碍，让角色的短期目标落空或延后。
章末必须留下一个让读者想翻下一页的钩子。
```

---

## 二、事件矩阵与冷却机制

### 问题背景

如果支线全靠"打脸/奇遇"驱动，AI 极易陷入模式化（主角走到哪都在踩人），引发审美疲劳。需要多元化的事件类型和节奏控制。

### 事件分类池

| 类型 | 说明 | 情绪效果 | 示例 |
|------|------|---------|------|
| `conflict_thrill` | 冲突爽点 | 紧张→爽快 | 打脸、捡漏、突破、逆转 |
| `bond_deepening` | 人物羁绊 | 温暖→感动 | 与配角吃饭聊天、共患难、误会化解 |
| `faction_building` | 势力经营 | 成就→掌控 | 打理产业、人情世故、招揽人才 |
| `world_painting` | 风土人情 | 沉浸→好奇 | 侧面展现时代背景、民俗、技术 |
| `tension_escalation` | 危机升级 | 不安→期待 | 暗中的阴谋推进、反派的布局 |

### 冷却机制

每种事件类型有冷却窗口（以章为单位）：

```json
{
  "conflict_thrill": {"cooldown": 2, "last_used_chapter": 40},
  "bond_deepening": {"cooldown": 1, "last_used_chapter": 41},
  "faction_building": {"cooldown": 2, "last_used_chapter": 39},
  "world_painting": {"cooldown": 3, "last_used_chapter": 38},
  "tension_escalation": {"cooldown": 2, "last_used_chapter": 41}
}
```

规则：
- 刚用过的类型在冷却期内不得作为主 Beat
- 冲突爽点不得连续出现超过2章
- 每5章内必须至少出现一次 `bond_deepening` 或 `world_painting`
- 冷却参数可按题材调整（爽文缩短 `conflict_thrill` 冷却，文艺向加长）

### 微型伏笔要求

在非冲突型事件中，要求 AI 埋下至少一个看似不起眼的细节，作为后续主线的辅助：
- 日常场景中出现的路人后续可能成为关键角色
- 经营场景中提到的某个商品后续可能成为剧情道具
- 风土人情中的某个习俗后续可能影响战局

这些微伏笔记录到知识图谱的 `foreshadow` 节点中。

### Beat Sheet 集成

在生成 Beat Sheet 时，系统自动：
1. 查询事件冷却状态
2. 根据冷却规则筛选可用事件类型
3. 按比例分配 Beat 类型
4. 在 Beat 中标注微伏笔要求

### 存储位置

`00_memory/event_matrix_state.json`

## 脚本入口（规划）

```bash
# 查询当前事件冷却状态
python3 scripts/event_matrix_scheduler.py status --project-root <目录>

# 为下一章推荐事件类型分配
python3 scripts/event_matrix_scheduler.py recommend --project-root <目录> --chapter <章号>

# 记录本章使用的事件类型
python3 scripts/event_matrix_scheduler.py record --project-root <目录> --chapter <章号> --types "conflict_thrill,bond_deepening"
```
