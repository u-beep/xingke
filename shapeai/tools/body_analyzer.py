"""身材数据解读引擎。

体重/体脂/围度趋势分析，区分水分/肌肉/脂肪波动原因，
平台期识别、进度评估、风险预警。
"""

import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class BodyAnalyzer:
    """身材数据分析引擎。"""

    def __init__(self, gateway=None):
        self.gateway = gateway

    def analyze(
        self,
        weight_records: list[dict] | None = None,
        body_fat_records: list[dict] | None = None,
        goal: str = "减脂",
        target_weight: float | None = None,
        user_profile: dict | None = None,
        user_id: str = "anonymous",
    ) -> dict:
        """分析身材数据趋势。

        Args:
            weight_records: 体重记录列表 [{"date": "2024-01-01", "weight": 70.0}, ...]
            body_fat_records: 体脂记录列表
            goal: 用户目标
            target_weight: 目标体重
            user_profile: 用户画像
            user_id: 用户ID
        Returns:
            包含趋势分析、平台期识别、进度评估的字典
        """
        weight_records = weight_records or []
        body_fat_records = body_fat_records or []

        # 硬规则分析
        stats = self._compute_stats(weight_records, body_fat_records, target_weight)
        plateau = self._detect_plateau(weight_records)
        risk = self._risk_assessment(stats, plateau, weight_records)

        # LLM 深度解读
        interpretation = ""
        if self.gateway:
            interpretation = self._interpret_with_llm(stats, plateau, risk, goal, user_profile, user_id)

        return {
            "statistics": stats,
            "plateau_analysis": plateau,
            "risk_assessment": risk,
            "interpretation": interpretation,
            "recommendations": self._generate_recommendations(stats, plateau, risk, goal),
        }

    def _compute_stats(self, weights: list[dict], body_fats: list[dict],
                       target_weight: float | None) -> dict:
        """计算统计指标。"""
        if not weights:
            return {"error": "无体重数据"}

        weights_sorted = sorted(weights, key=lambda x: x.get("date", ""))
        weight_values = [float(r["weight"]) for r in weights_sorted if "weight" in r]

        if len(weight_values) < 2:
            return {
                "current_weight": weight_values[-1] if weight_values else 0,
                "data_points": len(weight_values),
                "message": "数据点不足，至少需要2条记录才能分析趋势",
            }

        current = weight_values[-1]
        initial = weight_values[0]
        total_change = current - initial
        latest_period = weight_values[-min(7, len(weight_values)):]
        recent_change = latest_period[-1] - latest_period[0] if len(latest_period) >= 2 else 0

        # 计算变化率（kg/周）
        if len(weights_sorted) >= 2:
            try:
                d1 = datetime.fromisoformat(str(weights_sorted[0]["date"]).split("T")[0])
                d2 = datetime.fromisoformat(str(weights_sorted[-1]["date"]).split("T")[0])
                weeks = max((d2 - d1).days / 7, 0.1)
                weekly_rate = total_change / weeks
            except Exception:
                weekly_rate = 0
        else:
            weekly_rate = 0

        # 体脂数据
        bf_stats = {}
        if body_fats:
            bf_values = [float(r["body_fat"]) for r in body_fats if "body_fat" in r]
            if len(bf_values) >= 2:
                bf_stats = {
                    "current_body_fat": bf_values[-1],
                    "initial_body_fat": bf_values[0],
                    "body_fat_change": bf_values[-1] - bf_values[0],
                }

        # 目标进度
        progress = {}
        if target_weight and initial != current:
            total_needed = abs(initial - target_weight)
            achieved = abs(total_change)
            progress = {
                "target_weight": target_weight,
                "total_needed_kg": round(total_needed, 1),
                "achieved_kg": round(achieved, 1),
                "progress_percent": round(min(achieved / max(total_needed, 0.1) * 100, 100), 1),
            }

        return {
            "current_weight": round(current, 1),
            "initial_weight": round(initial, 1),
            "total_change_kg": round(total_change, 2),
            "recent_change_kg": round(recent_change, 2),
            "weekly_rate_kg": round(weekly_rate, 2),
            "data_points": len(weight_values),
            "trend": "下降" if total_change < 0 else "上升" if total_change > 0 else "持平",
            **bf_stats,
            **progress,
        }

    def _detect_plateau(self, weights: list[dict]) -> dict:
        """检测平台期。"""
        if len(weights) < 4:
            return {"is_plateau": False, "message": "数据点不足，无法判断平台期"}

        weights_sorted = sorted(weights, key=lambda x: x.get("date", ""))
        recent = [float(r["weight"]) for r in weights_sorted[-4:] if "weight" in r]
        if len(recent) < 4:
            return {"is_plateau": False, "message": "近期数据点不足"}

        # 计算近期波动范围
        weight_range = max(recent) - min(recent)
        avg = sum(recent) / len(recent)
        variation_pct = (weight_range / max(avg, 1)) * 100

        # 波动小于1%且持续4次以上判定为平台期
        is_plateau = variation_pct < 1.0

        return {
            "is_plateau": is_plateau,
            "recent_weight_range": round(weight_range, 2),
            "variation_percent": round(variation_pct, 2),
            "plateau_duration": "至少2周" if is_plateau else "无",
            "message": "检测到体重持续停滞，可能进入平台期" if is_plateau else "体重仍在正常变化中",
        }

    def _risk_assessment(self, stats: dict, plateau: dict, weights: list[dict]) -> dict:
        """风险评估。"""
        risks = []

        # 体重下降过快
        weekly_rate = stats.get("weekly_rate_kg", 0)
        if weekly_rate < -1.0:
            risks.append({
                "level": "warning",
                "type": "rapid_weight_loss",
                "message": f"体重下降速度过快({weekly_rate:.2f}kg/周)，建议控制在0.5-1kg/周",
            })

        # 体重异常波动
        if len(weights) >= 4:
            recent_weights = [float(r["weight"]) for r in sorted(weights, key=lambda x: x.get("date", ""))[-4:]]
            if len(recent_weights) >= 4:
                changes = [abs(recent_weights[i] - recent_weights[i-1]) for i in range(1, len(recent_weights))]
                if changes and max(changes) > 2.0:
                    risks.append({
                        "level": "warning",
                        "type": "abnormal_fluctuation",
                        "message": f"近期体重波动较大(单次变化{max(changes):.1f}kg)，可能是水分波动",
                    })

        # 平台期风险
        if plateau.get("is_plateau"):
            risks.append({
                "level": "info",
                "type": "plateau",
                "message": "进入平台期，建议调整训练强度或饮食结构",
            })

        # 体重过低
        current = stats.get("current_weight", 0)
        if current > 0 and current < 40:
            risks.append({
                "level": "danger",
                "type": "underweight",
                "message": f"当前体重{current}kg过低，建议咨询专业人士",
            })

        return {
            "has_risk": len(risks) > 0,
            "risk_count": len(risks),
            "risks": risks,
            "highest_level": max((r["level"] for r in risks), default="none"),
        }

    def _generate_recommendations(self, stats: dict, plateau: dict, risk: dict, goal: str) -> list[str]:
        """生成建议。"""
        recommendations = []

        if plateau.get("is_plateau"):
            recommendations.append("平台期建议：尝试调整训练计划，增加强度或变换训练方式")
            recommendations.append("饮食建议：适当调整碳水摄入比例或尝试碳水循环")

        if goal == "减脂":
            weekly_rate = stats.get("weekly_rate_kg", 0)
            if weekly_rate > 0:
                recommendations.append("当前体重呈上升趋势，建议检查饮食摄入是否超标")
            elif weekly_rate < -1.0:
                recommendations.append("减重速度偏快，建议适当增加摄入，保证营养均衡")

        if risk.get("has_risk"):
            for r in risk.get("risks", []):
                if r["level"] == "danger":
                    recommendations.append(f"⚠️ {r['message']}，建议咨询专业医生")

        if not recommendations:
            recommendations.append("当前进展良好，继续保持现有的饮食和运动习惯")

        return recommendations

    def _interpret_with_llm(self, stats: dict, plateau: dict, risk: dict,
                            goal: str, user_profile: dict | None, user_id: str) -> str:
        """使用LLM进行深度解读。"""
        profile_str = json.dumps(user_profile or {}, ensure_ascii=False)
        stats_str = json.dumps(stats, ensure_ascii=False)
        plateau_str = json.dumps(plateau, ensure_ascii=False)
        risk_str = json.dumps(risk, ensure_ascii=False)

        prompt = f"""请基于以下数据为用户生成身材管理趋势解读报告。

用户画像：{profile_str}
目标：{goal}
统计数据：{stats_str}
平台期分析：{plateau_str}
风险评估：{risk_str}

请生成一段200-300字的解读报告，包括：
1. 整体趋势评价
2. 数据背后的可能原因分析（水分/肌肉/脂肪波动）
3. 下一步建议

注意：不要做任何医疗诊断，只做健康建议。"""

        try:
            return self.gateway.complete(
                prompt, max_new_tokens=1024,
                user_id=user_id, scene="body_analysis",
            )
        except Exception as exc:
            logger.warning("LLM趋势解读失败: %s", exc)
            return ""
