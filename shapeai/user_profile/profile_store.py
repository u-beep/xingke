"""用户个人资料存储。

使用 PostgreSQL 持久化存储用户资料，Redis 缓存热数据。
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional

from ..database import pg_cursor, redis_client

logger = logging.getLogger(__name__)

# Redis key 前缀
_PROFILE_CACHE_PREFIX = "shapeai:profile:"
_PROFILE_CACHE_TTL = 3600  # 1小时


@dataclass
class UserProfile:
    """用户个人资料数据类。"""

    user_id: str
    # 基础身体数据
    height_cm: Optional[float] = None          # 身高(cm)
    weight_kg: Optional[float] = None          # 体重(kg)
    age: Optional[int] = None                  # 年龄
    gender: Optional[str] = None               # 性别: male/female
    target_weight_kg: Optional[float] = None   # 目标体重(kg)

    # 运动偏好
    exercise_frequency: Optional[str] = None   # 运动频率: sedentary/light/moderate/active/very_active
    preferred_exercises: list[str] = field(default_factory=list)  # 喜欢的运动类型
    exercise_goals: list[str] = field(default_factory=list)       # 运动目标

    # 饮食偏好
    dietary_restrictions: list[str] = field(default_factory=list) # 饮食限制: 素食/清真/过敏等
    preferred_cuisines: list[str] = field(default_factory=list)   # 喜欢的菜系
    disliked_foods: list[str] = field(default_factory=list)       # 不喜欢的食物
    meal_count_per_day: Optional[int] = None   # 每日餐数

    # 健康目标
    health_goal: Optional[str] = None          # 主要目标: lose_weight/maintain/gain_muscle
    target_date: Optional[str] = None          # 目标日期 ISO格式

    # 其他偏好
    sleep_hours: Optional[float] = None        # 平均睡眠时长
    water_intake_ml: Optional[int] = None      # 每日饮水目标(ml)
    daily_calorie_budget: Optional[int] = None  # 每日热量目标预算(kcal)，用户可自定义
    notes: Optional[str] = None                # 备注

    def to_dict(self) -> dict:
        """转换为字典。"""
        return asdict(self)

    def to_context_text(self) -> str:
        """格式化为可注入 prompt 的上下文文本。"""
        lines = ["【用户个人资料】"]

        if self.height_cm:
            lines.append(f"身高: {self.height_cm}cm")
        if self.weight_kg:
            lines.append(f"体重: {self.weight_kg}kg")
        if self.age:
            lines.append(f"年龄: {self.age}岁")
        if self.gender:
            lines.append(f"性别: {'男' if self.gender == 'male' else '女' if self.gender == 'female' else self.gender}")
        if self.target_weight_kg:
            lines.append(f"目标体重: {self.target_weight_kg}kg")

        if self.exercise_frequency:
            freq_map = {
                "sedentary": "久坐不动",
                "light": "轻度活动(每周1-3次)",
                "moderate": "中度活动(每周3-5次)",
                "active": "高度活动(每周6-7次)",
                "very_active": "极高活动(体力劳动者/运动员)",
            }
            lines.append(f"运动频率: {freq_map.get(self.exercise_frequency, self.exercise_frequency)}")
        if self.preferred_exercises:
            lines.append(f"喜欢的运动: {', '.join(self.preferred_exercises)}")
        if self.exercise_goals:
            lines.append(f"运动目标: {', '.join(self.exercise_goals)}")

        if self.dietary_restrictions:
            lines.append(f"饮食限制: {', '.join(self.dietary_restrictions)}")
        if self.preferred_cuisines:
            lines.append(f"喜欢的菜系: {', '.join(self.preferred_cuisines)}")
        if self.disliked_foods:
            lines.append(f"不喜欢的食物: {', '.join(self.disliked_foods)}")
        if self.meal_count_per_day:
            lines.append(f"每日餐数: {self.meal_count_per_day}餐")

        if self.health_goal:
            goal_map = {
                "lose_weight": "减脂",
                "maintain": "维持体重",
                "gain_muscle": "增肌",
            }
            lines.append(f"健康目标: {goal_map.get(self.health_goal, self.health_goal)}")
        if self.target_date:
            lines.append(f"目标日期: {self.target_date}")

        if self.sleep_hours:
            lines.append(f"平均睡眠: {self.sleep_hours}小时")
        if self.water_intake_ml:
            lines.append(f"每日饮水目标: {self.water_intake_ml}ml")
        if self.daily_calorie_budget:
            lines.append(f"每日热量预算: {self.daily_calorie_budget}kcal")
        if self.notes:
            lines.append(f"备注: {self.notes}")

        if len(lines) == 1:
            lines.append("(暂无个人资料，请在对话中告诉我你的基本信息)")

        return "\n".join(lines)

    def is_complete(self) -> bool:
        """检查基础资料是否完整。"""
        return all([
            self.height_cm is not None,
            self.weight_kg is not None,
            self.age is not None,
            self.gender is not None,
        ])


class ProfileStore:
    """用户资料存储器。

    PG 持久化 + Redis 缓存双写。
    """

    def __init__(self):
        self._ensure_table()

    @staticmethod
    def _cache_key(user_id: str) -> str:
        return f"{_PROFILE_CACHE_PREFIX}{user_id}"

    def _ensure_table(self):
        """确保用户资料表存在。"""
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS user_profiles (
                        user_id         VARCHAR(64) PRIMARY KEY,
                        height_cm       FLOAT,
                        weight_kg       FLOAT,
                        age             INTEGER,
                        gender          VARCHAR(16),
                        target_weight_kg FLOAT,
                        exercise_frequency VARCHAR(32),
                        preferred_exercises JSONB DEFAULT '[]'::jsonb,
                        exercise_goals  JSONB DEFAULT '[]'::jsonb,
                        dietary_restrictions JSONB DEFAULT '[]'::jsonb,
                        preferred_cuisines JSONB DEFAULT '[]'::jsonb,
                        disliked_foods  JSONB DEFAULT '[]'::jsonb,
                        meal_count_per_day INTEGER,
                        health_goal     VARCHAR(32),
                        target_date     VARCHAR(32),
                        sleep_hours     FLOAT,
                        water_intake_ml INTEGER,
                        daily_calorie_budget INTEGER,
                        notes           TEXT,
                        updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
        except Exception as exc:
            logger.warning("user_profiles 表创建检查失败(可能已存在): %s", exc)

    def get(self, user_id: str) -> UserProfile:
        """获取用户资料，优先从缓存读取。"""
        # 1. 尝试 Redis 缓存
        try:
            r = redis_client()
            cached = r.get(self._cache_key(user_id))
            if cached:
                data = json.loads(cached)
                return self._dict_to_profile(data)
        except Exception as exc:
            logger.debug("Redis 缓存读取失败: %s", exc)

        # 2. 从 PostgreSQL 读取
        try:
            with pg_cursor(commit=False) as cur:
                cur.execute("""
                    SELECT user_id, height_cm, weight_kg, age, gender,
                           target_weight_kg, exercise_frequency,
                           preferred_exercises, exercise_goals,
                           dietary_restrictions, preferred_cuisines,
                           disliked_foods, meal_count_per_day,
                           health_goal, target_date,
                           sleep_hours, water_intake_ml,
                           daily_calorie_budget, notes
                    FROM user_profiles WHERE user_id = %s
                """, (user_id,))
                row = cur.fetchone()
                if row:
                    profile = self._row_to_profile(row)
                    self._cache_set(user_id, profile)
                    return profile
        except Exception as exc:
            logger.warning("PG 读取用户资料失败: %s", exc)

        # 3. 返回空资料
        return UserProfile(user_id=user_id)

    def save(self, profile: UserProfile) -> bool:
        """保存用户资料到 PG 和 Redis。"""
        data = profile.to_dict()
        try:
            with pg_cursor() as cur:
                cur.execute("""
                    INSERT INTO user_profiles (
                        user_id, height_cm, weight_kg, age, gender,
                        target_weight_kg, exercise_frequency,
                        preferred_exercises, exercise_goals,
                        dietary_restrictions, preferred_cuisines,
                        disliked_foods, meal_count_per_day,
                        health_goal, target_date,
                        sleep_hours, water_intake_ml,
                        daily_calorie_budget, notes, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
                    ON CONFLICT (user_id) DO UPDATE SET
                        height_cm = EXCLUDED.height_cm,
                        weight_kg = EXCLUDED.weight_kg,
                        age = EXCLUDED.age,
                        gender = EXCLUDED.gender,
                        target_weight_kg = EXCLUDED.target_weight_kg,
                        exercise_frequency = EXCLUDED.exercise_frequency,
                        preferred_exercises = EXCLUDED.preferred_exercises,
                        exercise_goals = EXCLUDED.exercise_goals,
                        dietary_restrictions = EXCLUDED.dietary_restrictions,
                        preferred_cuisines = EXCLUDED.preferred_cuisines,
                        disliked_foods = EXCLUDED.disliked_foods,
                        meal_count_per_day = EXCLUDED.meal_count_per_day,
                        health_goal = EXCLUDED.health_goal,
                        target_date = EXCLUDED.target_date,
                        sleep_hours = EXCLUDED.sleep_hours,
                        water_intake_ml = EXCLUDED.water_intake_ml,
                        daily_calorie_budget = EXCLUDED.daily_calorie_budget,
                        notes = EXCLUDED.notes,
                        updated_at = now()
                """, (
                    profile.user_id, profile.height_cm, profile.weight_kg,
                    profile.age, profile.gender, profile.target_weight_kg,
                    profile.exercise_frequency,
                    json.dumps(profile.preferred_exercises),
                    json.dumps(profile.exercise_goals),
                    json.dumps(profile.dietary_restrictions),
                    json.dumps(profile.preferred_cuisines),
                    json.dumps(profile.disliked_foods),
                    profile.meal_count_per_day, profile.health_goal,
                    profile.target_date, profile.sleep_hours,
                    profile.water_intake_ml, profile.daily_calorie_budget,
                    profile.notes,
                ))
            self._cache_set(profile.user_id, profile)
            logger.info("用户资料已保存: %s", profile.user_id)
            return True
        except Exception as exc:
            logger.error("保存用户资料失败: %s", exc)
            return False

    def _cache_set(self, user_id: str, profile: UserProfile):
        """写入 Redis 缓存。"""
        try:
            r = redis_client()
            r.setex(
                self._cache_key(user_id),
                _PROFILE_CACHE_TTL,
                json.dumps(profile.to_dict(), ensure_ascii=False, default=str),
            )
        except Exception as exc:
            logger.debug("Redis 缓存写入失败: %s", exc)

    @staticmethod
    def _row_to_profile(row) -> UserProfile:
        """数据库行转 UserProfile。"""
        return UserProfile(
            user_id=row[0],
            height_cm=row[1],
            weight_kg=row[2],
            age=row[3],
            gender=row[4],
            target_weight_kg=row[5],
            exercise_frequency=row[6],
            preferred_exercises=row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]"),
            exercise_goals=row[8] if isinstance(row[8], list) else json.loads(row[8] or "[]"),
            dietary_restrictions=row[9] if isinstance(row[9], list) else json.loads(row[9] or "[]"),
            preferred_cuisines=row[10] if isinstance(row[10], list) else json.loads(row[10] or "[]"),
            disliked_foods=row[11] if isinstance(row[11], list) else json.loads(row[11] or "[]"),
            meal_count_per_day=row[12],
            health_goal=row[13],
            target_date=row[14],
            sleep_hours=row[15],
            water_intake_ml=row[16],
            daily_calorie_budget=row[17],
            notes=row[18],
        )

    @staticmethod
    def _dict_to_profile(data: dict) -> UserProfile:
        """字典转 UserProfile。"""
        return UserProfile(
            user_id=data.get("user_id", ""),
            height_cm=data.get("height_cm"),
            weight_kg=data.get("weight_kg"),
            age=data.get("age"),
            gender=data.get("gender"),
            target_weight_kg=data.get("target_weight_kg"),
            exercise_frequency=data.get("exercise_frequency"),
            preferred_exercises=data.get("preferred_exercises", []),
            exercise_goals=data.get("exercise_goals", []),
            dietary_restrictions=data.get("dietary_restrictions", []),
            disliked_foods=data.get("disliked_foods", []),
            preferred_cuisines=data.get("preferred_cuisines", []),
            meal_count_per_day=data.get("meal_count_per_day"),
            health_goal=data.get("health_goal"),
            target_date=data.get("target_date"),
            sleep_hours=data.get("sleep_hours"),
            water_intake_ml=data.get("water_intake_ml"),
            daily_calorie_budget=data.get("daily_calorie_budget"),
            notes=data.get("notes"),
        )
