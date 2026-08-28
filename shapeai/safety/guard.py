"""安全护栏 — 输入拦截 + 输出校验 + 医疗边界 + 合规声明。

所有AI输入输出的安全闸门，保障内容合规、医疗边界合规。
"""

import re
import logging
from typing import Optional

from ..config import (
    MEDICAL_FORBIDDEN_KEYWORDS,
    EXTREME_BEHAVIOR_KEYWORDS,
    SENSITIVE_WORDS,
)

logger = logging.getLogger(__name__)

# ─── 免责声明模板 ───
DISCLAIMER_HEALTH = "\n\n---\n⚠️ 免责声明：以上内容仅供健康管理参考，不构成医疗诊断或治疗建议。如有健康问题请咨询专业医生。"
DISCLAIMER_EXERCISE = "\n\n---\n⚠️ 运动提示：开始新的运动计划前建议咨询医生，特别是有慢性疾病或长期未运动的人群。"
DISCLAIMER_SPECIAL = "\n\n---\n⚠️ 特殊人群提醒：您可能属于特殊人群，建议在专业人员指导下进行身材管理。"

# ─── 医疗问题检测模式 ───
MEDICAL_QUESTION_PATTERNS = [
    r"诊断.*什么病|得了什么病|是什么疾病",
    r"处方.*什么药|开什么药|吃什么药",
    r"治疗方案|怎么治疗|如何治疗",
    r"我的病|这个症状是什么病",
    r"用药建议|药物.*副作用|药物.*相互作用",
    r"diagnose|prescription|treatment plan",
]


class SafetyGuard:
    """安全护栏。

    在输入和输出两个环节进行安全检查：
    - 输入侧：敏感词过滤、医疗高危问题拦截、极端行为识别
    - 输出侧：医疗边界校验、极端方案拦截、合规声明注入

    拦截日志持久化到 PostgreSQL interception_logs 表。
    """

    def __init__(self):
        self._medical_keywords = set(MEDICAL_FORBIDDEN_KEYWORDS)
        self._extreme_keywords = set(EXTREME_BEHAVIOR_KEYWORDS)
        self._sensitive_words = set(SENSITIVE_WORDS)
        self._interception_log: list[dict] = []

        self._db_mode = False
        try:
            from ..database import pg_cursor
            with pg_cursor(commit=False) as cur:
                cur.execute("SELECT 1")
            self._db_mode = True
            logger.info("SafetyGuard 使用 PostgreSQL 模式")
        except Exception as exc:
            logger.warning("SafetyGuard 回退到内存模式: %s", exc)

    # ─── 输入侧安全检查 ───

    def guard_input(self, text: str) -> tuple[bool, str, Optional[str]]:
        """输入安全检查。

        Args:
            text: 用户输入文本
        Returns:
            (是否安全通过, 拦截原因, 修改后的文本)
            - 如果不安全，返回 (False, 原因, None)
            - 如果安全，返回 (True, "", 原文或修改后的文本)
        """
        text = str(text)

        # 1. 敏感词过滤
        is_safe, reason = self._check_sensitive_words(text)
        if not is_safe:
            self._log_interception("input", "sensitive_word", reason, text)
            return False, reason, None

        # 2. 医疗高危问题检测
        is_safe, reason = self._check_medical_questions(text)
        if not is_safe:
            self._log_interception("input", "medical_question", reason, text)
            # 不直接拦截，而是修改为引导话术
            modified = "我注意到您的问题涉及医疗诊断/治疗。作为AI助手，我无法提供医疗诊断或处方建议。" \
                       "如果您有健康方面的担忧，建议咨询专业医生。" \
                       "我可以帮您提供一般性的健康管理建议。请问有什么我可以帮助的吗？"
            return True, "", modified

        # 3. 极端行为检测
        is_safe, reason, modified = self._check_extreme_behavior(text)
        if not is_safe:
            self._log_interception("input", "extreme_behavior", reason, text)
            return False, reason, None
        if modified:
            return True, "", modified

        return True, "", text

    def _check_sensitive_words(self, text: str) -> tuple[bool, str]:
        """敏感词过滤。"""
        text_lower = text.lower()
        for word in self._sensitive_words:
            if word in text_lower:
                return False, f"输入包含敏感内容: {word}"
        return True, ""

    def _check_medical_questions(self, text: str) -> tuple[bool, str]:
        """医疗高危问题检测。"""
        for pattern in MEDICAL_QUESTION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return False, f"检测到医疗类问题，已转换为引导话术"
        return True, ""

    def _check_extreme_behavior(self, text: str) -> tuple[bool, str, Optional[str]]:
        """极端行为检测。

        Returns:
            (是否安全, 原因, 修改后的文本或None)
        """
        text_lower = text.lower()
        detected = []

        for keyword in self._extreme_keywords:
            if keyword in text_lower:
                detected.append(keyword)

        if not detected:
            return True, "", None

        # 检测到极端行为关键词，不直接拦截，而是注入劝导话术
        modified = f"我注意到您提到了{'、'.join(detected)}。" \
                   f"这些方式可能对健康造成严重伤害，包括肌肉流失、代谢下降、电解质紊乱等。" \
                   f"健康比体重数字更重要。建议采用科学的饮食和运动方式来管理身材。" \
                   f"\n\n请告诉我您的身高、体重和目标，我可以为您制定一个健康安全的计划。"
        return True, "", modified

    # ─── 输出侧安全检查 ───

    def guard_output(self, text: str, scene: str = "chat") -> str:
        """输出安全检查。

        Args:
            text: AI生成文本
            scene: 调用场景
        Returns:
            检查后的文本（可能被修改或添加声明）
        """
        text = str(text)

        # 1. 医疗边界校验：替换禁止表述
        text = self._enforce_medical_boundary(text)

        # 2. 极端方案拦截
        text = self._intercept_extreme_plans(text)

        # 3. 合规声明注入
        text = self._inject_disclaimer(text, scene)

        return text

    def _enforce_medical_boundary(self, text: str) -> str:
        """医疗边界校验：替换禁止表述。"""
        replacements = {
            "诊断": "评估",
            "确诊": "判断",
            "处方": "建议",
            "开药": "建议咨询医生",
            "治疗方案": "管理方案",
            "疾病": "健康问题",
        }
        for forbidden, replacement in replacements.items():
            # 只替换作为建议性表述的场景，不替换用户引用
            if f"为您{forbidden}" in text or f"建议{forbidden}" in text:
                text = text.replace(f"为您{forbidden}", f"为您{replacement}")
                text = text.replace(f"建议{forbidden}", f"建议{replacement}")

        # 检查是否包含明确的医疗建议
        if any(kw in text for kw in ["确诊为", "诊断为", "处方药", "服用"]):
            text += "\n\n注意：以上内容不构成医疗诊断，如有疾病相关疑问请咨询专业医生。"

        return text

    def _intercept_extreme_plans(self, text: str) -> str:
        """极端方案拦截：检测并修正低于BMR的节食方案等。"""
        # 检测极端低热量建议
        calorie_pattern = r"每日[^0-9]*摄入[^0-9]*(\d+)\s*kcal|建议[^0-9]*(\d+)\s*kcal|热量[^0-9]*目标[^0-9]*(\d+)\s*kcal"
        matches = re.findall(calorie_pattern, text, re.IGNORECASE)

        for match in matches:
            for value_str in match:
                if value_str:
                    value = int(value_str)
                    # 低于1000kcal的方案被认为是极端的
                    if value < 1000:
                        text = text.replace(
                            f"{value}kcal",
                            f"{value}kcal（注意：此热量低于安全下限，建议不低于1200kcal）"
                        )
                        text = text.replace(
                            f"{value} kcal",
                            f"{value} kcal（注意：此热量低于安全下限，建议不低于1200kcal）"
                        )

        # 检测极端运动建议
        if re.search(r"每天.*运动.*[3-9]小时|每天.*训练.*[3-9]小时", text):
            text += "\n\n注意：建议每日运动时间不超过2小时，过度运动可能损伤身体。"

        return text

    def _inject_disclaimer(self, text: str, scene: str) -> str:
        """合规声明注入。"""
        # 避免重复添加
        if "免责声明" in text or "⚠️" in text:
            return text

        # 根据场景添加不同声明
        if scene in ("diet_plan", "body_analysis"):
            if any(kw in text for kw in ["饮食", "食谱", "热量", "营养", "减脂", "减重",
                                         "BMR", "TDEE", "BMI", "kcal", "摄入", "卡路里",
                                         "代谢", "蛋白质", "碳水", "脂肪", "体重"]):
                text += DISCLAIMER_HEALTH
        elif scene == "exercise_plan":
            if any(kw in text for kw in ["运动", "训练", "锻炼", "动作"]):
                text += DISCLAIMER_EXERCISE
        else:
            # 通用健康类回答
            if any(kw in text for kw in ["体重", "减脂", "增肌", "饮食", "运动", "健康", "身材",
                                         "BMR", "TDEE", "BMI", "kcal", "热量", "摄入",
                                         "卡路里", "代谢", "营养", "蛋白质", "碳水", "脂肪"]):
                text += DISCLAIMER_HEALTH

        return text

    # ─── 日志与统计 ───

    def _log_interception(self, side: str, event_type: str, reason: str, original_text: str):
        """记录安全拦截事件。"""
        log_entry = {
            "side": side,
            "type": event_type,
            "reason": reason,
            "text_preview": original_text[:200],
        }
        # 内存始终保留一份（回退用 + 立即可查）
        self._interception_log.append(log_entry)
        logger.info("安全拦截: side=%s type=%s reason=%s", side, event_type, reason)

        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor() as cur:
                    cur.execute("""
                        INSERT INTO interception_logs (side, type, reason, text_preview)
                        VALUES (%s, %s, %s, %s)
                    """, (side, event_type, reason, original_text[:200]))
            except Exception as exc:
                logger.error("PostgreSQL 拦截日志写入失败: %s", exc)

    def get_interception_log(self, limit: int = 50) -> list[dict]:
        """获取安全拦截日志。"""
        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor(commit=False) as cur:
                    cur.execute("""
                        SELECT side, type, reason, text_preview, created_at
                        FROM interception_logs
                        ORDER BY created_at DESC LIMIT %s
                    """, (limit,))
                    rows = cur.fetchall()
                return [{
                    "side": r[0], "type": r[1], "reason": r[2],
                    "text_preview": r[3],
                    "created_at": r[4].isoformat() if r[4] else "",
                } for r in rows]
            except Exception as exc:
                logger.error("PostgreSQL 拦截日志查询失败: %s", exc)

        return self._interception_log[-limit:]

    def get_stats(self) -> dict:
        """获取安全统计。"""
        if self._db_mode:
            try:
                from ..database import pg_cursor
                with pg_cursor(commit=False) as cur:
                    cur.execute("SELECT COUNT(*) FROM interception_logs")
                    total = cur.fetchone()[0]

                    cur.execute("""
                        SELECT type, COUNT(*) FROM interception_logs
                        GROUP BY type
                    """)
                    type_rows = cur.fetchall()

                return {
                    "total_interceptions": total,
                    "by_type": {r[0]: r[1] for r in type_rows},
                }
            except Exception as exc:
                logger.error("PostgreSQL 安全统计查询失败: %s", exc)

        from collections import Counter
        type_counts = Counter(log["type"] for log in self._interception_log)
        return {
            "total_interceptions": len(self._interception_log),
            "by_type": dict(type_counts),
        }
