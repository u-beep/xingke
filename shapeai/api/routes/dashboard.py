"""仪表盘聚合 API 路由。

聚合体重、饮食、运动、目标等多维度数据，返回前端 Dashboard 所需的核心指标。
"""

from fastapi import APIRouter, Request

from ...records import WeightStore, DietStore, ExerciseStore, GoalStore
from ...user_profile import ProfileStore
from ..security import get_auth_user_id

router = APIRouter(prefix="/dashboard", tags=["仪表盘"])


@router.get("/metrics", summary="核心指标聚合")
async def get_dashboard_metrics(req: Request):
    """获取仪表盘核心指标（体重、饮食、运动、目标进度）。"""
    user_id = get_auth_user_id(req)

    weight_store = WeightStore()
    diet_store = DietStore()
    exercise_store = ExerciseStore()
    goal_store = GoalStore()
    profile_store = ProfileStore()

    # 最新体重
    latest_weight = weight_store.get_latest(user_id)
    weight_stats = weight_store.get_stats(user_id, days=7)

    # 今日饮食
    diet_summary = diet_store.get_today_summary(user_id)

    # 本周运动
    exercise_summary = exercise_store.get_week_summary(user_id)

    # 目标进度
    goal_progress = goal_store.get_progress_summary(user_id)

    # 用户资料
    profile = profile_store.get(user_id)

    return {
        "weight": {
            "current": latest_weight.weight_kg if latest_weight else None,
            "body_fat_pct": latest_weight.body_fat_pct if latest_weight else None,
            "change_7d": weight_stats.get("change", 0),
            "avg_7d": weight_stats.get("avg_weight"),
        },
        "diet": {
            "today_calories": diet_summary.get("total_calories", 0),
            "today_protein": diet_summary.get("total_protein_g", 0),
            "today_carbs": diet_summary.get("total_carbs_g", 0),
            "today_fat": diet_summary.get("total_fat_g", 0),
            "record_count": diet_summary.get("record_count", 0),
        },
        "exercise": {
            "week_total": exercise_summary.get("total_count", 0),
            "week_completed": exercise_summary.get("completed_count", 0),
            "week_duration_min": exercise_summary.get("total_duration_min", 0),
            "week_calories": exercise_summary.get("total_calories_burned", 0),
        },
        "goals": goal_progress,
        "profile": {
            "height_cm": profile.height_cm,
            "target_weight_kg": profile.target_weight_kg,
            "health_goal": profile.health_goal,
        },
    }


@router.get("/weekly-summary", summary="周报数据")
async def get_weekly_summary(req: Request):
    """获取本周数据摘要（平均热量缺口、运动次数、体重变化、打卡率）。"""
    user_id = get_auth_user_id(req)

    weight_store = WeightStore()
    diet_store = DietStore()
    exercise_store = ExerciseStore()

    # 体重变化
    weight_stats = weight_store.get_stats(user_id, days=7)

    # 饮食统计（7天）
    diet_records = diet_store.get_history(user_id, days=7)
    total_calories = sum(r.calories or 0 for r in diet_records)
    avg_calories = total_calories / 7 if diet_records else 0

    # 运动统计
    exercise_summary = exercise_store.get_week_summary(user_id)

    # 计算打卡率（有饮食记录的天数 / 7）
    from datetime import datetime
    record_days = set()
    for r in diet_records:
        if r.recorded_at:
            record_days.add(r.recorded_at.strftime("%Y-%m-%d"))
    check_in_rate = round(len(record_days) / 7 * 100, 1)

    return {
        "avg_calorie_intake": round(avg_calories, 1),
        "exercise_count": exercise_summary.get("completed_count", 0),
        "weight_change": weight_stats.get("change", 0),
        "diet_check_in_rate": check_in_rate,
        "period": "本周",
    }
