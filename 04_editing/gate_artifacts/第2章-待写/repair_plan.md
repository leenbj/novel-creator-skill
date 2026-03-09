# 章节修复计划

- 生成时间：2026-03-08 18:41:45
- 章节：/Users/ethan/Desktop/小说/novel-creator-skill/03_manuscript/第2章-待写.md
- 门禁结果：未通过

## 失败项
1. memory_update: 文件时间早于章节文件，疑似未执行最新流程
2. consistency_report: 文件时间早于章节文件，疑似未执行最新流程
3. style_calibration: 文件时间早于章节文件，疑似未执行最新流程
4. copyedit_report: 文件时间早于章节文件，疑似未执行最新流程
5. publish_ready: 文件时间早于章节文件，疑似未执行最新流程
6. quality_baseline: quality_report 显示未通过

## 修复步骤（最短路径）
1. 重新执行 /更新记忆，生成并补全 memory_update.md。
2. 继续执行 /检查一致性 -> /风格校准 -> /校稿 -> /门禁检查。
3. 重新执行 /检查一致性，修复冲突后更新 consistency_report.md。
4. 继续执行 /风格校准 -> /校稿 -> /门禁检查。
5. 重新执行 /风格校准，更新 style_calibration.md。
6. 继续执行 /校稿 -> /门禁检查。
7. 重新执行 /校稿，生成 copyedit_report.md。
8. 继续执行 /门禁检查。
9. 重新执行 /校稿，生成 publish_ready.md 且确保为最终发布稿。
10. 检查 publish_ready.md 包含可发布关键词（可发布/通过/PASS）。
11. 检查失败项：quality_baseline: quality_report 显示未通过
12. 按失败项补齐对应产物后，重新执行 /门禁检查。
13. 修复完成后再执行 /更新剧情索引。

## 建议命令
```bash
python3 scripts/gate_repair_plan.py --project-root /Users/ethan/Desktop/小说/novel-creator-skill --chapter-file '/Users/ethan/Desktop/小说/novel-creator-skill/03_manuscript/第2章-待写.md'
python3 scripts/chapter_gate_check.py --project-root /Users/ethan/Desktop/小说/novel-creator-skill --chapter-file '/Users/ethan/Desktop/小说/novel-creator-skill/03_manuscript/第2章-待写.md'
```
