"""种子数据脚本 — 为当前用户生成符合实际的测试数据。

使用: python -m shapeai.seed_data
"""

import logging
from datetime import datetime, timedelta, date
from .database import pg_cursor

logger = logging.getLogger(__name__)

USER_ID = "user_web_001"


def seed_user_profile():
    """创建用户资料。"""
    logger.info("创建用户资料...")
    with pg_cursor() as cur:
        cur.execute("""
            INSERT INTO user_profiles (
                user_id, height_cm, weight_kg, age, gender,
                target_weight_kg, exercise_frequency,
                preferred_exercises, exercise_goals,
                dietary_restrictions, preferred_cuisines,
                disliked_foods, meal_count_per_day,
                health_goal, target_date,
                sleep_hours, water_intake_ml, notes, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
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
                notes = EXCLUDED.notes,
                updated_at = now()
        """, (
            USER_ID, 175.0, 71.5, 28, "male",
            68.0, "moderate",
            '["跑步", "力量训练", "游泳"]',
            '["减脂", "增肌", "提升体能"]',
            '["少油少盐"]',
            '["中餐", "日料"]',
            '["肥肉", "动物内脏"]',
            3,
            "lose_weight", "2026-11-15",
            7.5, 2500, "坚持减脂42天，目标3个月减到68kg",
        ))
    logger.info("用户资料已创建/更新")


def seed_weight_records():
    """插入42天体重记录（从75kg逐步下降到71.5kg）。"""
    logger.info("插入体重记录...")
    # 42天数据，从75.0kg逐步下降到71.5kg，带小幅波动
    base_weight = 75.0
    target_weight = 71.5
    days = 42
    daily_drop = (base_weight - target_weight) / days  # ~0.083kg/天

    weight_data = []
    for i in range(days):
        day_offset = days - 1 - i
        recorded_at = datetime.now() - timedelta(days=day_offset)
        # 基础趋势 + 随机波动(-0.3 ~ +0.3)
        import random
        random.seed(i * 7 + 13)  # 固定种子保证可复现
        trend = base_weight - (days - 1 - day_offset) * daily_drop
        noise = random.uniform(-0.3, 0.3)
        weight = round(trend + noise, 1)
        body_fat = round(24.5 - (days - 1 - day_offset) * 0.071 + random.uniform(-0.2, 0.2), 1)
        waist = round(84.0 - (days - 1 - day_offset) * 0.107 + random.uniform(-0.3, 0.3), 1)
        hip = round(97.0 - (days - 1 - day_offset) * 0.05 + random.uniform(-0.2, 0.2), 1)
        weight_data.append((USER_ID, weight, max(15, body_fat), waist, hip, recorded_at, None))

    with pg_cursor() as cur:
        # 先清空该用户旧数据
        cur.execute("DELETE FROM weight_records WHERE user_id = %s", (USER_ID,))
        cur.executemany("""
            INSERT INTO weight_records (user_id, weight_kg, body_fat_pct, waist_cm, hip_cm, recorded_at, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, weight_data)
    logger.info("已插入 %d 条体重记录", len(weight_data))


def seed_diet_records():
    """插入7天饮食记录（每日3餐）。"""
    logger.info("插入饮食记录...")

    meals_data = [
        # 第1天 (8/09)
        ("breakfast", "燕麦粥", 250, 152, 5.2, 28.0, 2.8, datetime(2026, 8, 9, 8, 0)),
        ("breakfast", "水煮蛋", 50, 78, 6.5, 0.6, 5.5, datetime(2026, 8, 9, 8, 10)),
        ("lunch", "鸡胸肉沙拉", 200, 280, 35.0, 12.0, 8.0, datetime(2026, 8, 9, 12, 30)),
        ("lunch", "糙米饭", 150, 170, 3.8, 35.0, 1.2, datetime(2026, 8, 9, 12, 35)),
        ("dinner", "清蒸鲈鱼", 180, 200, 28.0, 2.0, 8.0, datetime(2026, 8, 9, 19, 0)),
        ("dinner", "西兰花", 150, 50, 4.1, 4.3, 0.6, datetime(2026, 8, 9, 19, 5)),
        # 第2天 (8/10)
        ("breakfast", "全麦面包", 80, 210, 8.5, 38.0, 2.5, datetime(2026, 8, 10, 8, 0)),
        ("breakfast", "牛奶", 250, 135, 7.5, 8.5, 8.0, datetime(2026, 8, 10, 8, 5)),
        ("lunch", "牛肉时蔬炒面", 300, 520, 22.0, 65.0, 18.0, datetime(2026, 8, 10, 12, 30)),
        ("dinner", "豆腐蔬菜汤", 250, 120, 10.0, 8.0, 5.0, datetime(2026, 8, 10, 19, 0)),
        ("dinner", "玉米", 150, 130, 4.8, 28.0, 1.8, datetime(2026, 8, 10, 19, 5)),
        # 第3天 (8/11)
        ("breakfast", "杂粮粥", 300, 180, 6.0, 35.0, 2.0, datetime(2026, 8, 11, 8, 0)),
        ("breakfast", "茶叶蛋", 60, 95, 7.8, 0.8, 6.5, datetime(2026, 8, 11, 8, 5)),
        ("lunch", "虾仁炒饭", 250, 460, 18.0, 58.0, 15.0, datetime(2026, 8, 11, 12, 30)),
        ("dinner", "鸡丝凉面", 200, 340, 20.0, 42.0, 10.0, datetime(2026, 8, 11, 19, 0)),
        ("dinner", "冬瓜汤", 200, 45, 1.5, 6.0, 0.5, datetime(2026, 8, 11, 19, 5)),
        # 第4天 (8/12)
        ("breakfast", "燕麦粥", 250, 152, 5.2, 28.0, 2.8, datetime(2026, 8, 12, 8, 0)),
        ("breakfast", "水煮蛋", 50, 78, 6.5, 0.6, 5.5, datetime(2026, 8, 12, 8, 5)),
        ("lunch", "鸡胸肉沙拉", 200, 280, 35.0, 12.0, 8.0, datetime(2026, 8, 12, 12, 30)),
        ("dinner", "清蒸鲈鱼", 180, 200, 28.0, 2.0, 8.0, datetime(2026, 8, 12, 19, 0)),
        ("dinner", "生菜", 100, 13, 1.3, 2.0, 0.1, datetime(2026, 8, 12, 19, 5)),
        # 第5天 (8/13)
        ("breakfast", "红薯", 200, 172, 3.2, 40.0, 0.2, datetime(2026, 8, 13, 8, 0)),
        ("breakfast", "鸡蛋", 50, 72, 6.3, 0.6, 4.8, datetime(2026, 8, 13, 8, 5)),
        ("lunch", "牛肉炒西兰花", 250, 320, 28.0, 15.0, 16.0, datetime(2026, 8, 13, 12, 30)),
        ("lunch", "米饭", 150, 174, 3.9, 38.0, 0.4, datetime(2026, 8, 13, 12, 35)),
        ("dinner", "豆腐汤", 200, 95, 8.1, 3.8, 4.5, datetime(2026, 8, 13, 19, 0)),
        # 第6天 (8/14)
        ("breakfast", "全麦面包", 80, 210, 8.5, 38.0, 2.5, datetime(2026, 8, 14, 8, 0)),
        ("breakfast", "牛奶", 250, 135, 7.5, 8.5, 8.0, datetime(2026, 8, 14, 8, 5)),
        ("lunch", "鸡胸肉", 150, 200, 31.0, 0, 3.6, datetime(2026, 8, 14, 12, 30)),
        ("lunch", "红薯", 150, 129, 2.4, 30.0, 0.15, datetime(2026, 8, 14, 12, 35)),
        ("dinner", "鱼肉", 150, 155, 17.9, 0, 4.8, datetime(2026, 8, 14, 19, 0)),
        ("dinner", "胡萝卜", 100, 39, 1.0, 8.8, 0.2, datetime(2026, 8, 14, 19, 5)),
        # 第7天 (8/15) 今天
        ("breakfast", "燕麦粥", 250, 152, 5.2, 28.0, 2.8, datetime(2026, 8, 15, 8, 0)),
        ("breakfast", "水煮蛋", 50, 78, 6.5, 0.6, 5.5, datetime(2026, 8, 15, 8, 5)),
        ("lunch", "鸡胸肉沙拉", 200, 280, 35.0, 12.0, 8.0, datetime(2026, 8, 15, 12, 30)),
    ]

    records = [(USER_ID, m[0], m[1], m[2], m[3], m[4], m[5], m[6], m[7], None) for m in meals_data]

    with pg_cursor() as cur:
        cur.execute("DELETE FROM diet_records WHERE user_id = %s", (USER_ID,))
        cur.executemany("""
            INSERT INTO diet_records (user_id, meal_type, food_name, amount_g, calories, protein_g, carbs_g, fat_g, recorded_at, image_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, records)
    logger.info("已插入 %d 条饮食记录", len(records))


def seed_exercise_records():
    """插入本周运动记录。"""
    logger.info("插入运动记录...")

    # 本周运动计划（周一到周日）
    exercises = [
        ("HIIT燃脂训练", "有氧", 30, 320, True, date(2026, 8, 10)),  # 周一
        ("上肢力量训练", "力量", 45, 280, True, date(2026, 8, 11)),  # 周二
        ("休息日", "休息", None, 0, True, date(2026, 8, 12)),        # 周三
        ("核心训练", "核心", 30, 240, True, date(2026, 8, 13)),      # 周四
        ("下肢力量训练", "力量", 40, 300, False, date(2026, 8, 14)), # 周五（今天，未完成）
        ("有氧慢跑", "有氧", 40, 350, False, date(2026, 8, 15)),     # 周六（计划）
        ("瑜伽拉伸", "柔韧", 30, 150, False, date(2026, 8, 16)),     # 周日（计划）
    ]

    records = []
    for ex in exercises:
        recorded_at = datetime.combine(ex[5], datetime.min.time()) + timedelta(hours=18)
        records.append((USER_ID, ex[0], ex[1], ex[2], ex[3], ex[4], ex[5], recorded_at, None))

    with pg_cursor() as cur:
        cur.execute("DELETE FROM exercise_records WHERE user_id = %s", (USER_ID,))
        cur.executemany("""
            INSERT INTO exercise_records (user_id, exercise_name, exercise_type, duration_min, calories_burned, completed, scheduled_date, recorded_at, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, records)
    logger.info("已插入 %d 条运动记录", len(records))


def seed_user_goals():
    """插入用户目标。"""
    logger.info("插入用户目标...")

    goals = [
        ("weight_loss", 68.0, 71.5, "kg", 75.0, date(2026, 11, 15), "active"),
        ("body_fat", 18.0, 21.5, "%", 24.5, date(2026, 11, 15), "active"),
    ]

    records = [(USER_ID, g[0], g[1], g[2], g[3], g[4], g[5], g[6]) for g in goals]

    with pg_cursor() as cur:
        cur.execute("DELETE FROM user_goals WHERE user_id = %s", (USER_ID,))
        cur.executemany("""
            INSERT INTO user_goals (user_id, goal_type, target_value, current_value, unit, start_value, deadline, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now(), now())
        """, records)
    logger.info("已插入 %d 条目标记录", len(records))


def seed_all():
    """执行全部种子数据插入。"""
    print("=" * 60)
    print("  ShapeAI 种子数据生成")
    print("=" * 60)
    print(f"\n用户ID: {USER_ID}")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        seed_user_profile()
        print("  [OK] 用户资料")
    except Exception as e:
        print(f"  [FAIL] 用户资料: {e}")

    try:
        seed_weight_records()
        print("  [OK] 体重记录 (42天)")
    except Exception as e:
        print(f"  [FAIL] 体重记录: {e}")

    try:
        seed_diet_records()
        print("  [OK] 饮食记录 (7天)")
    except Exception as e:
        print(f"  [FAIL] 饮食记录: {e}")

    try:
        seed_exercise_records()
        print("  [OK] 运动记录 (本周)")
    except Exception as e:
        print(f"  [FAIL] 运动记录: {e}")

    try:
        seed_user_goals()
        print("  [OK] 用户目标")
    except Exception as e:
        print(f"  [FAIL] 用户目标: {e}")

    print("\n" + "=" * 60)
    print("  种子数据生成完成!")
    print("=" * 60)


if __name__ == "__main__":
    seed_all()
