#!/usr/bin/env python3
"""Dynamic Draft Generator - 动态草稿生成器

根据章节号、写作阶段和上下文动态生成草稿，避免硬编码模板的重复问题。

作者: Claude Code
版本: 1.0.0
日期: 2025-03-02
"""

import re
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass


@dataclass
class DraftContext:
    """草稿生成上下文"""
    chapter_no: int
    query: str
    previous_summary: str
    character_states: Dict[str, Dict]
    stage: str
    milestone: Optional[str] = None


class DynamicDraftGenerator:
    """动态草稿生成器主类"""
    
    # 写作阶段定义
    STAGES = {
        "opening": (1, 10, "开篇阶段", "建立世界观和主角形象"),
        "rising": (11, 30, "上升阶段", "推进剧情，升级冲突"),
        "climax_building": (31, 50, "高潮铺垫", "回收伏笔，准备高潮"),
        "sustaining": (51, float('inf'), "长程维持", "保持节奏，深化世界")
    }
    
    # 里程碑定义
    MILESTONES = {
        50: ("半百庆典", "中期总结，检查进度"),
        100: ("百章大节点", "重大转折，开启新篇章"),
        150: ("后半程开启", "加速推进，收紧线索"),
        200: ("终局铺垫", "准备最终高潮")
    }
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict:
        """加载模板配置"""
        return {
            "opening": {
                "structure": [
                    "场景建立：描绘时间、地点、氛围",
                    "主角登场：外貌、状态、心理描写",
                    "冲突引入：事件触发、初步矛盾",
                    "章末钩子：悬念设置，引发期待"
                ],
                "min_paragraphs": 8,
                "focus": "世界观建立 + 主角塑造 + 冲突引入"
            },
            "rising": {
                "structure": [
                    "承接上文：回应前一章的悬念",
                    "冲突升级：新挑战、新角色加入",
                    "关系发展：盟友、敌人、暧昧对象",
                    "能力提升：技能、资源、影响力增长",
                    "章末钩子：更大的危机降临"
                ],
                "min_paragraphs": 10,
                "focus": "冲突升级 + 关系网络扩展"
            },
            "climax_building": {
                "structure": [
                    "多线并行：主线与支线交织",
                    "旧账清算：前期伏笔回收",
                    "势力对决：大规模冲突爆发",
                    "角色蜕变：关键成长时刻",
                    "章末钩子：终极对决预告"
                ],
                "min_paragraphs": 12,
                "focus": "伏笔回收 + 大规模冲突"
            },
            "sustaining": {
                "structure": [
                    "定期回顾：每10章总结进展",
                    "新血注入：新角色、新势力",
                    "规则演变：世界规则深化",
                    "多卷联动：跨卷伏笔",
                    "节奏控制：张弛有度"
                ],
                "min_paragraphs": 10,
                "focus": "长期架构 + 节奏控制",
                "special": {
                    "context_refresh_interval": 10,
                    "memory_recall_frequency": 5
                }
            }
        }
    
    def generate_draft(self, chapter_no: int, query: str, 
                       previous_summary: str = "",
                       character_states: Optional[Dict] = None) -> str:
        """生成章节草稿"""
        stage = self._get_stage(chapter_no)
        template = self.templates[stage]
        milestone = self._check_milestone(chapter_no)
        
        context = DraftContext(
            chapter_no=chapter_no,
            query=query,
            previous_summary=previous_summary,
            character_states=character_states or {},
            stage=stage,
            milestone=milestone
        )
        
        draft = self._build_draft(context, template)
        return draft
    
    def _get_stage(self, chapter_no: int) -> str:
        """根据章节号确定写作阶段"""
        for stage, (start, end, _, _) in self.STAGES.items():
            if start <= chapter_no <= end:
                return stage
        return "sustaining"
    
    def _check_milestone(self, chapter_no: int) -> Optional[str]:
        """检查是否是里程碑章节"""
        if chapter_no in self.MILESTONES:
            name, desc = self.MILESTONES[chapter_no]
            return f"{name} - {desc}"
        return None
    
    def _build_draft(self, context: DraftContext, template: Dict) -> str:
        """构建草稿内容"""
        lines = []
        
        # 标题
        lines.append(f"# 第{context.chapter_no}章 - 草稿规划")
        lines.append("")
        
        # 阶段信息
        stage_info = self.STAGES.get(context.stage, (0, 0, "未知", ""))
        lines.append(f"## 本章节阶段定位")
        lines.append(f"- 阶段类型：{context.stage}")
        lines.append(f"- 阶段描述：{stage_info[2] if len(stage_info) > 2 else 'N/A'}")
        lines.append(f"- 阶段重点：{stage_info[3] if len(stage_info) > 3 else 'N/A'}")
        lines.append("")
        
        # 里程碑提示
        if context.milestone:
            lines.append(f"## 🎯 本章里程碑")
            lines.append(f"**{context.milestone}**")
            lines.append("")
            lines.append("### 里程碑任务")
            milestone_num = int(context.chapter_no) if context.chapter_no else 0
            if milestone_num == 50:
                lines.append("- [ ] 总结前49章的核心进展")
                lines.append("- [ ] 整理主要角色的成长轨迹")
                lines.append("- [ ] 检查并回收重要伏笔")
                lines.append("- [ ] 设置下一阶段的关键转折")
            elif milestone_num == 100:
                lines.append("- [ ] 完成第一阶段的宏大叙事")
                lines.append("- [ ] 开启全新的故事篇章")
                lines.append("- [ ] 引入新的势力或角色")
                lines.append("- [ ] 升级世界观或力量体系")
            elif milestone_num == 150:
                lines.append("- [ ] 总结前半程的经验教训")
                lines.append("- [ ] 加速剧情推进节奏")
                lines.append("- [ ] 为最终高潮做铺垫")
                lines.append("- [ ] 收紧所有松散的情节线")
            elif milestone_num == 200:
                lines.append("- [ ] 启动最终篇章的倒计时")
                lines.append("- [ ] 所有伏笔必须回收完毕")
                lines.append("- [ ] 主要角色的最终定位")
                lines.append("- [ ] 为最终决战做好准备")
            lines.append("")
        
        # 章节结构
        lines.append(f"## 章节结构要求（至少{template['min_paragraphs']}个段落）")
        for i, item in enumerate(template['structure'], 1):
            lines.append(f"{i}. {item}")
        lines.append("")
        
        # 本章核心目标
        lines.append(f"## 本章核心目标")
        lines.append(f"{context.query}")
        lines.append("")
        
        # 前情衔接
        if context.previous_summary:
            lines.append(f"## 前情衔接")
            lines.append(f"{context.previous_summary[:300]}...")
            lines.append("")
        
        # 里程碑特殊提示
        if context.milestone:
            lines.append(f"## 🎉 本章是第{context.chapter_no}章（{context.milestone.split(' - ')[0]}）")
            lines.append(f"这是一个重要的里程碑章节，请特别注意：")
            lines.append(f"- 做好阶段性的总结与回顾")
            lines.append(f"- 为下一阶段做好铺垫")
            lines.append(f"- 确保情节的连贯性和一致性")
            lines.append("")
        
        # 正文提示
        lines.append(f"## 正文（请严格按结构要求撰写，确保字数不低于2500字）")
        lines.append(f"[在此处开始撰写章节正文...]")
        lines.append("")
        
        # 自检清单
        lines.append(f"## 自检清单（写作完成后核对）")
        lines.append(f"- [ ] 字数达到2500字以上（建议3000-3500字）")
        lines.append(f"- [ ] 严格遵循章节结构（共{len(template['structure'])}个部分）")
        lines.append(f"- [ ] 段落数不少于{template['min_paragraphs']}个")
        lines.append(f"- [ ] 承接上一章剧情，无断层")
        lines.append(f"- [ ] 章末有合理钩子或悬念")
        if context.milestone:
            lines.append(f"- [ ] 满足第{context.chapter_no}章里程碑特殊要求")
        
        return "\n".join(lines)


# 便捷函数
def generate_chapter_draft(
    chapter_no: int,
    query: str,
    project_root: Path,
    previous_summary: str = "",
    character_states: Optional[Dict] = None
) -> str:
    """
    便捷函数：生成章节草稿
    
    Args:
        chapter_no: 章节号
        query: 本章目标/查询
        project_root: 项目根目录
        previous_summary: 上一章摘要
        character_states: 角色状态
    
    Returns:
        生成的草稿文本
    """
    generator = DynamicDraftGenerator(project_root)
    return generator.generate_draft(
        chapter_no=chapter_no,
        query=query,
        previous_summary=previous_summary,
        character_states=character_states or {}
    )


# 测试代码
if __name__ == "__main__":
    # 简单测试
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)
        
        # 测试不同阶段的草稿生成
        test_cases = [
            (5, "开篇测试", "这是第5章，开篇阶段"),
            (20, "上升测试", "这是第20章，上升阶段"),
            (40, "高潮铺垫测试", "这是第40章，高潮铺垫阶段"),
            (60, "长程维持测试", "这是第60章，长程维持阶段"),
            (50, "里程碑测试", "这是第50章，半百里程碑"),
            (100, "百章里程碑测试", "这是第100章，百章里程碑"),
        ]
        
        for chapter_no, query, prev_summary in test_cases:
            print(f"\n{'='*60}")
            print(f"测试第{chapter_no}章 - {query}")
            print(f"{'='*60}")
            
            draft = generate_chapter_draft(
                chapter_no=chapter_no,
                query=query,
                project_root=project_root,
                previous_summary=prev_summary,
                character_states={"protagonist": {"name": "主角"}}
            )
            
            # 打印草稿前500字符作为预览
            preview = draft[:500] + "..." if len(draft) > 500 else draft
            print(preview)
            print(f"\n总字数: {len(draft)}")