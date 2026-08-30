"""工具路由 — 单工具手动调用接口。"""

from fastapi import APIRouter, Request, HTTPException

from ..models import ToolCallRequest, ToolCallResponse

router = APIRouter(prefix="/tools", tags=["工具"])


@router.get("/list", summary="列出所有可用工具")
async def list_tools(req: Request):
    """列出所有可用工具及其规格。"""
    from ...tools.executor import TOOL_SPECS
    return {"tools": TOOL_SPECS}


@router.post("/call", response_model=ToolCallResponse, summary="直接调用工具")
async def call_tool(request: ToolCallRequest, req: Request):
    """直接调用指定工具，不需要经过Agent循环。"""
    executor = req.app.state.tool_executor
    result = executor.execute(request.tool_name, request.args)
    return ToolCallResponse(
        tool_name=request.tool_name,
        content=result["content"],
        metadata=result.get("metadata", {}),
    )


@router.post("/calculate/bmr", summary="计算基础代谢率(BMR)")
async def calculate_bmr(
    gender: str = "male",
    age: int = 25,
    weight: float = 70,
    height: float = 175,
    req: Request = None,
):
    """计算基础代谢率。"""
    executor = req.app.state.tool_executor
    result = executor.execute("calculate_bmr", {
        "gender": gender, "age": age, "weight": weight, "height": height,
    })
    return {"result": result["content"]}


@router.post("/calculate/tdee", summary="计算每日总能量消耗(TDEE)")
async def calculate_tdee(
    bmr: float,
    activity_level: str = "moderate",
    req: Request = None,
):
    """计算每日总能量消耗。"""
    executor = req.app.state.tool_executor
    result = executor.execute("calculate_tdee", {
        "bmr": bmr, "activity_level": activity_level,
    })
    return {"result": result["content"]}


@router.post("/calculate/bmi", summary="计算身体质量指数(BMI)")
async def calculate_bmi(
    weight: float,
    height: float,
    req: Request = None,
):
    """计算BMI。"""
    executor = req.app.state.tool_executor
    result = executor.execute("calculate_bmi", {
        "weight": weight, "height": height,
    })
    return {"result": result["content"]}


@router.post("/diet-plan", summary="生成个性化饮食方案")
async def generate_diet_plan(
    gender: str = "male",
    age: int = 25,
    weight: float = 70,
    height: float = 175,
    activity_level: str = "moderate",
    target_deficit: float = 500,
    meals_per_day: int = 3,
    preferences: str = "",
    allergies: str = "",
    days: int = 1,
    user_id: str = "anonymous",
    req: Request = None,
):
    """生成个性化饮食方案。"""
    executor = req.app.state.tool_executor
    result = executor.execute("generate_diet_plan", {
        "gender": gender, "age": age, "weight": weight, "height": height,
        "activity_level": activity_level, "target_deficit": target_deficit,
        "meals_per_day": meals_per_day, "preferences": preferences,
        "allergies": allergies, "days": days,
    })
    return {"result": result["content"]}


@router.post("/exercise-plan", summary="生成运动训练计划")
async def generate_exercise_plan(
    fitness_level: str = "beginner",
    available_days: int = 4,
    time_per_session: int = 45,
    equipment: str = "none",
    target_areas: str = "全身",
    goal: str = "减脂",
    user_id: str = "anonymous",
    req: Request = None,
):
    """生成一周运动训练计划。"""
    executor = req.app.state.tool_executor
    result = executor.execute("generate_exercise_plan", {
        "fitness_level": fitness_level, "available_days": available_days,
        "time_per_session": time_per_session, "equipment": equipment,
        "target_areas": target_areas, "goal": goal,
    })
    return {"result": result["content"]}


@router.post("/analyze-body", summary="分析身材数据")
async def analyze_body(
    weight_records: list[dict] = None,
    body_fat_records: list[dict] = None,
    goal: str = "减脂",
    target_weight: float = 0,
    req: Request = None,
):
    """分析体重/体脂趋势。"""
    executor = req.app.state.tool_executor
    result = executor.execute("analyze_body_data", {
        "weight_records": weight_records or [],
        "body_fat_records": body_fat_records or [],
        "goal": goal,
        "target_weight": target_weight,
    })
    return {"result": result["content"]}
