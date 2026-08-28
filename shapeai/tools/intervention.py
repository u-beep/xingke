"""异常干预策略引擎。

针对连续超标、连续未打卡、体重异常波动等场景，
生成干预话术与方案。
"""

import json
import logging

logger = logging.getLogger(__name__)


class InterventionEngine:
    """异常干预策略引擎。

    根据不同异常场景生成干预策略和话术。
    """

    def __init__(self, gateway=None):
        self.gateway = gateway

    def generate_intervention(
        self,
        scenario: str,
        context: dict | None = None,
        user_profile: dict | None = None,
        user_id: str = "anonymous",
    ) -> dict:
        """生成异常干预策略。

        Args:
            scenario: 干预场景类型
                - consecutive_overrun: 连续热量超标
                - consecutive_missed: 连续未打卡
                - weight_spike: 体重异常波动
                - plateau_long: 长期平台期
                - extreme_behavior: 极端行为
            context: 场景上下文数据
            user_profile: 用户画像
            user_id: 用户ID
        Returns:
            包含干预话术和方案的字典
        """
        context = context or {}
        user_profile = user_profile or {}

        # 规则引擎生成基础策略
        base_strategy = self._rule_based_intervention(scenario, context, user_profile)

        # LLM 增强话术
        if self.gateway:
            enhanced = self._llm_enhance(scenario, context, user_profile, base_strategy, user_id)
            if enhanced:
                base_strategy["enhanced_message"] = enhanced

        return base_strategy

    def _rule_based_intervention(self, scenario: str, context: dict, profile: dict) -> dict:
        """基于规则的干预策略。"""
        strategies = {
            "consecutive_overrun": {
                "level": "warning",
                "title": "热量连续超标提醒",
                "message": self._overrun_message(context),
                "actions": [
                    "回顾最近几天的饮食记录，找出超标原因",
                    "尝试用低热量食物替代高热量食物",
                    "增加日常活动量，如多走路、爬楼梯",
                ],
            },
            "consecutive_missed": {
                "level": "info",
                "title": "打卡中断提醒",
                "message": self._missed_message(context),
                "actions": [
                    "从简单的一餐开始恢复记录",
                    "设置每日提醒闹钟",
                    "不必追求完美，坚持记录比完美记录更重要",
                ],
            },
            "weight_spike": {
                "level": "warning",
                "title": "体重异常波动提醒",
                "message": self._spike_message(context),
                "actions": [
                    "不要慌张，短期波动多为水分变化",
                    "检查近期盐分摄入是否过高",
                    "女性注意生理周期对体重的影响",
                    "保持正常饮食和运动节奏",
                ],
            },
            "plateau_long": {
                "level": "info",
                "title": "平台期突破建议",
                "message": self._plateau_message(context),
                "actions": [
                    "调整训练计划，增加强度或改变训练方式",
                    "尝试碳水循环或调整热量摄入",
                    "确保充足睡眠，减少压力",
                    "平台期是身体适应的过程，保持耐心",
                ],
            },
            "extreme_behavior": {
                "level": "danger",
                "title": "健康行为警告",
                "message": "检测到可能的极端减重行为。过度节食、催吐等行为会严重损害健康，"
                          "包括肌肉流失、代谢下降、电解质紊乱、内分泌失调等。",
                "actions": [
                    "立即停止极端限制饮食的行为",
                    "恢复正常饮食，保证每日摄入不低于基础代谢",
                    "如有进食障碍倾向，请及时寻求专业帮助",
                    "健康比体重数字更重要",
                ],
            },
        }

        result = strategies.get(scenario, {
            "level": "info",
            "title": "提醒",
            "message": "请保持健康的饮食和运动习惯。",
            "actions": [],
        })

        result["scenario"] = scenario
        result["user_profile"] = profile
        return result

    def _overrun_message(self, context: dict) -> str:
        days = context.get("consecutive_days", 3)
        avg_overrun = context.get("avg_overrun", 0)
        return (
            f"您已连续{days}天热量摄入超过目标值，平均超标{avg_overrun:.0f}kcal。"
            "偶尔超标很正常，但连续超标可能影响进度。"
            "建议回顾饮食记录，找出可以优化的部分。"
        )

    def _missed_message(self, context: dict) -> str:
        days = context.get("missed_days", 3)
        return (
            f"您已连续{days}天未记录饮食。"
            "坚持记录是身材管理的关键习惯，"
            "即使只是简单记录也比完全不记录好。"
        )

    def _spike_message(self, context: dict) -> str:
        change = context.get("weight_change", 0)
        return (
            f"检测到体重在短时间内变化{change:.1f}kg。"
            "短期内大幅变化通常是水分波动而非脂肪变化，不必过于担心。"
            "建议继续正常记录和坚持计划。"
        )

    def _plateau_message(self, context: dict) -> str:
        duration = context.get("plateau_weeks", 2)
        return (
            f"您已处于平台期约{duration}周。"
            "平台期是身体适应当前状态的正常现象，"
            "通过调整训练和饮食策略可以有效突破。"
        )

    def _llm_enhance(self, scenario: str, context: dict, profile: dict,
                     base_strategy: dict, user_id: str) -> str:
        """使用LLM生成更个性化的干预话术。"""
        prompt = f"""请为用户生成一段温暖、有同理心的干预提醒话术。

场景：{base_strategy['title']}
基础信息：{base_strategy['message']}
用户画像：{json.dumps(profile, ensure_ascii=False)}
上下文数据：{json.dumps(context, ensure_ascii=False)}

要求：
1. 语气温暖、理解、不指责
2. 给出具体的、可操作的建议
3. 控制在100-150字
4. 不涉及任何医疗诊断
"""
        try:
            return self.gateway.complete(
                prompt, max_new_tokens=512,
                user_id=user_id, scene="intervention",
            )
        except Exception as exc:
            logger.warning("LLM干预话术生成失败: %s", exc)
            return ""
