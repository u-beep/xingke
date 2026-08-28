"""用户个人资料 API 路由。

提供查询和更新用户个人资料的接口。
"""

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, List

from ...user_profile import ProfileStore, UserProfile

router = APIRouter(prefix="/profile", tags=["用户资料"])


class ProfileUpdateRequest(BaseModel):
    """更新用户资料请求。"""
    height_cm: Optional[float] = Field(None, description="身高(cm)")
    weight_kg: Optional[float] = Field(None, description="体重(kg)")
    age: Optional[int] = Field(None, description="年龄")
    gender: Optional[str] = Field(None, description="性别: male/female")
    target_weight_kg: Optional[float] = Field(None, description="目标体重(kg)")
    exercise_frequency: Optional[str] = Field(None, description="运动频率")
    preferred_exercises: Optional[List[str]] = Field(None, description="喜欢的运动")
    exercise_goals: Optional[List[str]] = Field(None, description="运动目标")
    dietary_restrictions: Optional[List[str]] = Field(None, description="饮食限制")
    preferred_cuisines: Optional[List[str]] = Field(None, description="喜欢的菜系")
    disliked_foods: Optional[List[str]] = Field(None, description="不喜欢的食物")
    meal_count_per_day: Optional[int] = Field(None, description="每日餐数")
    health_goal: Optional[str] = Field(None, description="健康目标")
    target_date: Optional[str] = Field(None, description="目标日期")
    sleep_hours: Optional[float] = Field(None, description="平均睡眠时长")
    water_intake_ml: Optional[int] = Field(None, description="每日饮水目标(ml)")
    notes: Optional[str] = Field(None, description="备注")


@router.get("/me", summary="获取当前用户资料")
async def get_my_profile(req: Request):
    """获取当前登录用户的个人资料。"""
    # 从请求头或 session 获取 user_id
    user_id = req.headers.get("X-User-Id", "anonymous")

    store = ProfileStore()
    profile = store.get(user_id)

    return {
        "user_id": profile.user_id,
        "profile": profile.to_dict(),
        "context_text": profile.to_context_text(),
        "is_complete": profile.is_complete(),
    }


@router.post("/me", summary="更新当前用户资料")
async def update_my_profile(req: Request, body: ProfileUpdateRequest):
    """更新当前登录用户的个人资料。"""
    user_id = req.headers.get("X-User-Id", "anonymous")

    store = ProfileStore()
    profile = store.get(user_id)

    # 应用更新
    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and hasattr(profile, field):
            setattr(profile, field, value)

    success = store.save(profile)
    if not success:
        raise HTTPException(status_code=500, detail="保存用户资料失败")

    return {
        "success": True,
        "user_id": profile.user_id,
        "profile": profile.to_dict(),
        "message": "用户资料已更新",
    }


@router.get("/by-id/{user_id}", summary="获取指定用户资料(管理员)")
async def get_user_profile(user_id: str, req: Request):
    """获取指定用户的个人资料（需要管理员权限）。"""
    store = ProfileStore()
    profile = store.get(user_id)
    return profile.to_dict()


@router.delete("/me", summary="清空当前用户资料")
async def clear_my_profile(req: Request):
    """清空当前用户的所有个人资料。"""
    user_id = req.headers.get("X-User-Id", "anonymous")

    store = ProfileStore()
    profile = UserProfile(user_id=user_id)  # 创建空资料
    success = store.save(profile)

    return {
        "success": success,
        "message": "用户资料已清空",
    }


# ─────────────────────────────────────────────────────────────
#  每日热量目标预算（用户自定义）
# ─────────────────────────────────────────────────────────────

class CalorieBudgetRequest(BaseModel):
    """设置每日热量预算请求。"""
    user_id: Optional[str] = Field(None, description="用户ID（未传则取 X-User-Id 头）")
    daily_calorie_budget: int = Field(..., ge=800, le=5000, description="每日热量目标预算(kcal)")


def _compute_suggested_tdee(profile: UserProfile) -> Optional[int]:
    """根据用户身体数据计算 TDEE 作为建议预算（缺数据返回 None）。"""
    if not all([profile.gender, profile.age, profile.weight_kg, profile.height_cm]):
        return None
    try:
        from ..tools.calculator import calculate_bmr, calculate_tdee
        bmr = calculate_bmr(
            gender=profile.gender,
            age=profile.age,
            weight=profile.weight_kg,
            height=profile.height_cm,
        )
        activity = profile.exercise_frequency or "moderate"
        # activity_frequency 字段值映射到 calculate_tdee 接受的 activity_level
        freq_map = {"sedentary": "sedentary", "light": "light", "moderate": "moderate",
                    "active": "active", "very_active": "very_active"}
        tdee = calculate_tdee(bmr=bmr, activity_level=freq_map.get(activity, "moderate"))
        return int(tdee.get("tdee", tdee) if isinstance(tdee, dict) else tdee)
    except Exception:
        return None


@router.get("/calorie-budget", summary="获取每日热量目标预算")
async def get_calorie_budget(req: Request, user_id: str = None):
    """获取用户每日热量目标预算。

    返回：
    - daily_calorie_budget：用户自定义的预算（未设置则 null）
    - suggested_budget：根据身体数据计算的 TDEE 建议值（缺身体数据则 null）
    - has_custom：是否已自定义
    """
    uid = user_id or req.headers.get("X-User-Id", "anonymous")
    store = ProfileStore()
    profile = store.get(uid)
    suggested = _compute_suggested_tdee(profile)
    return {
        "user_id": uid,
        "daily_calorie_budget": profile.daily_calorie_budget,
        "suggested_budget": suggested,
        "has_custom": profile.daily_calorie_budget is not None,
    }


@router.put("/calorie-budget", summary="设置每日热量目标预算")
async def set_calorie_budget(body: CalorieBudgetRequest, req: Request):
    """设置用户每日热量目标预算（kcal），覆盖 TDEE 建议值。"""
    uid = body.user_id or req.headers.get("X-User-Id", "anonymous")
    store = ProfileStore()
    profile = store.get(uid)
    profile.daily_calorie_budget = body.daily_calorie_budget
    success = store.save(profile)
    if not success:
        raise HTTPException(status_code=500, detail="保存热量预算失败")
    return {
        "success": True,
        "user_id": uid,
        "daily_calorie_budget": profile.daily_calorie_budget,
        "message": f"每日热量预算已设为 {body.daily_calorie_budget} kcal",
    }
