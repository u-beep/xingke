"""运动热量消耗规则表 + 运动方案模板表。

exercise_calories: 存储常见运动的热量消耗规则（按体重和时间计算）
workout_templates: 用户自定义运动方案模板，可一键应用到当天计划
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from ..database import pg_cursor

logger = logging.getLogger(__name__)


# ─── 运动热量消耗规则数据类 ───

@dataclass
class ExerciseCalorie:
    """运动热量消耗规则。"""
    id: Optional[int] = None
    exercise_name: str = ""
    exercise_type: str = ""        # cardio / strength / anaerobic
    met_value: float = 5.0         # 代谢当量
    calories_per_min: float = 0    # 每分钟每公斤体重消耗热量（预计算: MET × 体重 / 60）
    category: str = ""             # 子分类：跑步/游泳/力量等
    intensity: str = "moderate"    # light / moderate / vigorous
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "exercise_name": self.exercise_name,
            "exercise_type": self.exercise_type,
            "met_value": self.met_value,
            "calories_per_min": self.calories_per_min,
            "category": self.category,
            "intensity": self.intensity,
            "description": self.description,
        }


# ─── 运动方案模板数据类 ───

@dataclass
class WorkoutTemplate:
    """运动方案模板。"""
    id: Optional[int] = None
    user_id: str = ""
    template_name: str = ""         # 模板名称：如"减脂有氧日""力量塑形日"
    description: str = ""
    items: list = None              # [{exercise_name, exercise_type, duration_min}, ...]
    total_duration: int = 0
    estimated_calories: float = 0   # 预估消耗热量（按70kg计算）
    created_at: Optional[datetime] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "template_name": self.template_name,
            "description": self.description,
            "items": self.items or [],
            "total_duration": self.total_duration,
            "estimated_calories": self.estimated_calories,
            "created_at": self.created_at.isoformat() if self.created_at else "",
        }


# ─── 内置运动热量消耗规则（初始数据） ───

BUILTIN_EXERCISES = [
    # 有氧运动 (cardio)
    ("跑步", "cardio", 9.8, "跑步", "vigorous", "中高强度跑步，约8km/h"),
    ("快走", "cardio", 4.3, "步行", "light", "快步走，约6km/h"),
    ("游泳", "cardio", 8.0, "游泳", "vigorous", "自由泳中等强度"),
    ("骑车", "cardio", 7.5, "骑行", "moderate", "户外骑行15-20km/h"),
    ("跳绳", "cardio", 12.0, "跳跃", "vigorous", "快速跳绳120次/分钟"),
    ("椭圆机", "cardio", 5.0, "器械", "moderate", "健身房椭圆机中等阻力"),
    ("划船机", "cardio", 7.0, "器械", "moderate", "划船机中等强度"),
    ("爬楼梯", "cardio", 8.8, "攀爬", "vigorous", "连续爬楼梯"),
    ("健身操", "cardio", 6.0, "操课", "moderate", "有氧健身操"),
    ("跳舞", "cardio", 5.5, "舞蹈", "moderate", "中等强度舞蹈"),
    ("羽毛球", "cardio", 5.5, "球类", "moderate", "休闲单打或双打"),
    ("篮球", "cardio", 6.5, "球类", "vigorous", "半场或全场篮球"),
    ("足球", "cardio", 7.0, "球类", "vigorous", "业余足球比赛"),
    ("乒乓球", "cardio", 4.0, "球类", "light", "休闲乒乓球"),
    ("网球", "cardio", 7.3, "球类", "vigorous", "单打网球"),
    ("登山", "cardio", 6.9, "户外", "moderate", "中等坡度登山"),
    # 力量训练 (strength)
    ("杠铃深蹲", "strength", 6.0, "下肢力量", "vigorous", "大重量杠铃深蹲"),
    ("硬拉", "strength", 6.0, "全身力量", "vigorous", "杠铃硬拉"),
    ("卧推", "strength", 5.0, "上肢力量", "moderate", "杠铃平板卧推"),
    ("哑铃训练", "strength", 4.5, "综合力量", "moderate", "哑铃各部位训练"),
    ("器械训练", "strength", 4.5, "综合力量", "moderate", "健身房器械训练"),
    ("俯卧撑", "strength", 3.8, "上肢力量", "moderate", "标准俯卧撑"),
    ("引体向上", "strength", 4.0, "上肢力量", "vigorous", "宽握引体向上"),
    ("臀桥", "strength", 4.0, "下肢力量", "moderate", "杠铃或自重臀桥"),
    ("箭步蹲", "strength", 5.0, "下肢力量", "moderate", "哑铃或杠铃箭步蹲"),
    # 无氧/核心 (anaerobic)
    ("HIIT", "anaerobic", 10.0, "高强度间歇", "vigorous", "高强度间歇训练"),
    ("波比跳", "anaerobic", 9.0, "爆发力", "vigorous", "连续波比跳"),
    ("平板支撑", "anaerobic", 3.5, "核心", "moderate", "标准平板支撑"),
    ("卷腹", "anaerobic", 3.5, "核心", "light", "标准卷腹"),
    ("俄罗斯转体", "anaerobic", 4.0, "核心", "moderate", "负重俄罗斯转体"),
    ("山羊挺身", "anaerobic", 4.5, "核心", "moderate", "罗马椅山羊挺身"),
]


class WorkoutStore:
    """运动热量规则 + 运动方案模板 存储管理。"""

    def __init__(self):
        self._ensure_tables()
        self._seed_builtin_exercises()

    def _ensure_tables(self):
        """确保表存在。"""
        try:
            with pg_cursor(commit=True) as cur:
                # 运动热量消耗规则表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS exercise_calories (
                        id SERIAL PRIMARY KEY,
                        exercise_name VARCHAR(128) NOT NULL UNIQUE,
                        exercise_type VARCHAR(32) NOT NULL DEFAULT 'cardio',
                        met_value FLOAT NOT NULL DEFAULT 5.0,
                        category VARCHAR(64) DEFAULT '',
                        intensity VARCHAR(16) DEFAULT 'moderate',
                        description TEXT DEFAULT '',
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)

                # 运动方案模板表
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS workout_templates (
                        id SERIAL PRIMARY KEY,
                        user_id VARCHAR(64) NOT NULL,
                        template_name VARCHAR(128) NOT NULL,
                        description TEXT DEFAULT '',
                        items JSONB NOT NULL DEFAULT '[]',
                        total_duration INTEGER DEFAULT 0,
                        estimated_calories FLOAT DEFAULT 0,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_workout_templates_user
                    ON workout_templates(user_id)
                """)
        except Exception as exc:
            logger.error("创建运动热量/模板表失败: %s", exc)

    def _seed_builtin_exercises(self):
        """填充内置运动数据（仅首次）。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("SELECT COUNT(*) FROM exercise_calories")
                count = cur.fetchone()[0]
                if count > 0:
                    return

                for name, etype, met, category, intensity, desc in BUILTIN_EXERCISES:
                    cur.execute("""
                        INSERT INTO exercise_calories
                            (exercise_name, exercise_type, met_value, category, intensity, description)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (exercise_name) DO NOTHING
                    """, (name, etype, met, category, intensity, desc))
                logger.info("已填充 %d 条内置运动热量规则", len(BUILTIN_EXERCISES))
        except Exception as exc:
            logger.error("填充运动热量规则失败: %s", exc)

    # ─── 运动热量规则 CRUD ───

    def list_exercises(self, exercise_type: str = None) -> List[ExerciseCalorie]:
        """获取运动列表，可按类型过滤。"""
        try:
            with pg_cursor(commit=False) as cur:
                if exercise_type:
                    cur.execute("""
                        SELECT id, exercise_name, exercise_type, met_value,
                               category, intensity, description
                        FROM exercise_calories
                        WHERE exercise_type = %s
                        ORDER BY exercise_type, category, exercise_name
                    """, (exercise_type,))
                else:
                    cur.execute("""
                        SELECT id, exercise_name, exercise_type, met_value,
                               category, intensity, description
                        FROM exercise_calories
                        ORDER BY exercise_type, category, exercise_name
                    """)
                rows = cur.fetchall()
                return [ExerciseCalorie(
                    id=r[0], exercise_name=r[1], exercise_type=r[2],
                    met_value=r[3], category=r[4], intensity=r[5], description=r[6],
                ) for r in rows]
        except Exception as exc:
            logger.error("查询运动热量规则失败: %s", exc)
            return []

    def get_exercise_by_name(self, name: str) -> Optional[ExerciseCalorie]:
        """按名称获取运动。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, exercise_name, exercise_type, met_value,
                           category, intensity, description
                    FROM exercise_calories WHERE exercise_name = %s
                """, (name,))
                r = cur.fetchone()
                if r:
                    return ExerciseCalorie(
                        id=r[0], exercise_name=r[1], exercise_type=r[2],
                        met_value=r[3], category=r[4], intensity=r[5], description=r[6],
                    )
        except Exception as exc:
            logger.error("查询运动失败: %s", exc)
        return None

    @staticmethod
    def calc_calories(met_value: float, duration_min: int, weight_kg: float = 71.5) -> float:
        """根据 MET 值计算热量消耗。"""
        hours = duration_min / 60.0
        return round(met_value * weight_kg * hours, 1)

    # ─── 运动方案模板 CRUD ───

    def create_template(
        self, user_id: str, template_name: str, description: str,
        items: list, weight_kg: float = 71.5,
    ) -> Optional[int]:
        """创建运动方案模板。

        Args:
            items: [{exercise_name, exercise_type, duration_min}, ...]
        Returns:
            模板 ID
        """
        total_duration = sum(i.get("duration_min", 0) for i in items)
        total_calories = 0
        for i in items:
            exercise = self.get_exercise_by_name(i["exercise_name"])
            met = exercise.met_value if exercise else 5.0
            total_calories += self.calc_calories(met, i["duration_min"], weight_kg)

        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("""
                    INSERT INTO workout_templates
                        (user_id, template_name, description, items, total_duration, estimated_calories)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (user_id, template_name, description, json.dumps(items, ensure_ascii=False),
                      total_duration, round(total_calories, 1)))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as exc:
            logger.error("创建运动方案模板失败: %s", exc)
            return None

    def list_templates(self, user_id: str) -> List[WorkoutTemplate]:
        """获取用户的运动方案模板列表。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, user_id, template_name, description, items,
                           total_duration, estimated_calories, created_at
                    FROM workout_templates
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                """, (user_id,))
                rows = cur.fetchall()
                return [WorkoutTemplate(
                    id=r[0], user_id=r[1], template_name=r[2], description=r[3],
                    items=r[4] if isinstance(r[4], list) else json.loads(r[4] or "[]"),
                    total_duration=r[5], estimated_calories=r[6], created_at=r[7],
                ) for r in rows]
        except Exception as exc:
            logger.error("查询运动方案模板失败: %s", exc)
            return []

    def get_template(self, template_id: int) -> Optional[WorkoutTemplate]:
        """获取单个模板详情。"""
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT id, user_id, template_name, description, items,
                           total_duration, estimated_calories, created_at
                    FROM workout_templates WHERE id = %s
                """, (template_id,))
                r = cur.fetchone()
                if r:
                    return WorkoutTemplate(
                        id=r[0], user_id=r[1], template_name=r[2], description=r[3],
                        items=r[4] if isinstance(r[4], list) else json.loads(r[4] or "[]"),
                        total_duration=r[5], estimated_calories=r[6], created_at=r[7],
                    )
        except Exception as exc:
            logger.error("查询运动方案模板失败: %s", exc)
        return None

    def delete_template(self, template_id: int) -> bool:
        """删除模板。"""
        try:
            with pg_cursor(commit=True) as cur:
                cur.execute("DELETE FROM workout_templates WHERE id = %s", (template_id,))
                return cur.rowcount > 0
        except Exception as exc:
            logger.error("删除运动方案模板失败: %s", exc)
            return False
