# 大纲锚点与章节进度配额规范

> 状态：规划中（Phase 2 实现）

## 问题背景

AI 缺乏全局观，容易把长线任务当短线跑——在早期章节就推进大量剧情，导致后期无事可写，或者提前揭露悬念。

## 设计原则

每章写作前，系统必须读取全局大纲的"进度条"，在底层 Prompt 中注入推进约束。

## 锚点结构

存储位置：`00_memory/outline_anchors.json`

```json
{
  "total_chapters_target": 600,
  "total_volumes": 10,
  "current_chapter": 42,
  "current_volume": 2,
  "progress_percent": 7.0,
  "volumes": [
    {
      "volume": 1,
      "title": "初入朝堂",
      "chapter_range": [1, 60],
      "core_conflict": "站稳脚跟，获取初始权力",
      "must_not_reveal": ["反派真实身份", "主角穿越者身份暴露"],
      "must_achieve": ["获得第一个盟友", "第一次小规模政治胜利"],
      "foreshadows_to_plant": ["foreshadow_001", "foreshadow_002"]
    }
  ],
  "current_node": {
    "volume": 2,
    "chapter": 42,
    "allowed_plot_range": "推进均田制改革受阻，不得解决土地兼并问题",
    "forbidden_reveals": ["终极BOSS身份"],
    "mandatory_tension": "至少保留一个未解决冲突进入下一章"
  }
}
```

## 配额检查逻辑

每章写作前注入的约束（动态生成）：

```
当前是第 {current_chapter} 章（共 {total_chapters_target} 章），进度 {progress_percent}%。
当前卷：{current_volume_title}（第{volume_start}-{volume_end}章）。
本章推进范围：{allowed_plot_range}。
本章禁止揭露：{forbidden_reveals}。
本章必须保留：{mandatory_tension}。
```

## 越界判定

门禁中新增"进度合规检查"：
1. 本章是否推进了超出当前卷允许范围的剧情
2. 是否提前揭露了禁止揭露的悬念
3. 章末是否保留了足够的未解决冲突
4. 伏笔回收是否在计划时间窗口内

越界 → 门禁失败 → 必须改写。

## 锚点更新时机

- `/一键开书` 时初始化
- 每卷结束时自动推进到下一卷
- `/改纲续写` 时重新计算所有锚点
- 每10章冲刺复盘时微调

## 脚本入口（规划）

```bash
# 初始化锚点
python3 scripts/outline_anchor_manager.py init --project-root <目录>

# 写前配额检查
python3 scripts/outline_anchor_manager.py check --project-root <目录> --chapter <章号>

# 推进锚点
python3 scripts/outline_anchor_manager.py advance --project-root <目录> --to-chapter <章号>

# 改纲后重算
python3 scripts/outline_anchor_manager.py recalculate --project-root <目录>
```
