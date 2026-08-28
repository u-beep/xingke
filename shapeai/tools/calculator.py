"""基础指标计算工具 — 纯计算，不依赖大模型。

包含：BMR（基础代谢）、TDEE（每日总能量消耗）、BMI（身体质量指数）、
热量缺口计算、宏量营养素配比计算。

所有公式采用国际通用的标准公式，确保计算结果准确可控。
"""


def calculate_bmr(gender: str, age: int, weight: float, height: float) -> dict:
    """计算基础代谢率（BMR）。

    使用 Mifflin-St Jeor 公式（目前最推荐的标准公式）。

    Args:
        gender: 性别（"male" / "female"）
        age: 年龄（岁）
        weight: 体重
        height: 身高
    Returns:
        {"bmr": float, "formula": "Mifflin-St Jeor", "unit": "kcal/day"}
    """
    gender = str(gender).lower().strip()
    weight = float(weight)
    height = float(height)
    age = int(age)

    # Mifflin-St Jeor 公式
    base = 10 * weight + 6.25 * height - 5 * age
    if gender in ("male", "m", "男"):
        bmr = base + 5
    elif gender in ("female", "f", "女"):
        bmr = base - 161
    else:
        # 未知性别取平均值
        bmr = base - 78

    return {
        "bmr": round(bmr, 1),
        "formula": "Mifflin-St Jeor",
        "unit": "kcal/day",
        "inputs": {"gender": gender, "age": age, "weight": weight, "height": height},
    }


def calculate_tdee(bmr: float, activity_level: str = "moderate") -> dict:
    """计算每日总能量消耗（TDEE）。

    Args:
        bmr: 基础代谢率
        activity_level: 活动水平
            - sedentary: 久坐不动（×1.2）
            - light: 轻度活动（×1.375）
            - moderate: 中度活动（×1.55）
            - active: 高度活动（×1.725）
            - very_active: 极高活动（×1.9）
    Returns:
        {"tdee": float, "activity_multiplier": float, "unit": "kcal/day"}
    """
    multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }
    level = str(activity_level).lower().strip()
    multiplier = multipliers.get(level, 1.55)
    tdee = float(bmr) * multiplier

    return {
        "tdee": round(tdee, 1),
        "activity_level": level,
        "activity_multiplier": multiplier,
        "bmr": float(bmr),
        "unit": "kcal/day",
    }


def calculate_bmi(weight: float, height: float) -> dict:
    """计算身体质量指数（BMI）。

    Args:
        weight: 体重
        height: 身高
    Returns:
        {"bmi": float, "category": str, "health_risk": str}
    """
    weight = float(weight)
    height = float(height)
    if height <= 0 or weight <= 0:
        return {"error": "身高和体重必须为正数"}

    bmi = weight / (height / 100) ** 2

    # 中国BMI分类标准
    if bmi < 18.5:
        category = "偏瘦"
        risk = "营养不良风险增加"
    elif bmi < 24:
        category = "正常"
        risk = "健康风险正常"
    elif bmi < 28:
        category = "超重"
        risk = "心血管疾病风险增加"
    else:
        category = "肥胖"
        risk = "多种慢性疾病风险显著增加"

    return {
        "bmi": round(bmi, 1),
        "category": category,
        "health_risk": risk,
        "weight": weight,
        "height": height,
    }


def calculate_calorie_deficit(tdee: float, target_deficit: float = 500) -> dict:
    """计算热量缺口与目标摄入量。

    Args:
        tdee: 每日总能量消耗
        target_deficit: 目标热量缺口，默认500kcal/day
    Returns:
        包含目标摄入量、缺口比例、预计减重速度等
    """
    tdee = float(tdee)
    deficit = float(target_deficit)

    # 安全检查：缺口不应超过TDEE的25%
    max_deficit = tdee * 0.25
    if deficit > max_deficit:
        deficit = max_deficit

    target_intake = tdee - deficit

    # 7700kcal ≈ 1kg脂肪
    weekly_loss = (deficit * 7) / 7700

    # 安全检查：摄入不应低于BMR估算值（TDEE/活动系数的下限）
    min_safe_intake = tdee * 0.5  # 粗略下限

    return {
        "tdee": round(tdee, 1),
        "target_deficit": round(deficit, 1),
        "target_intake": round(target_intake, 1),
        "deficit_ratio": round(deficit / tdee * 100, 1),
        "estimated_weekly_loss_kg": round(weekly_loss, 2),
        "estimated_monthly_loss_kg": round(weekly_loss * 4, 1),
        "is_safe": target_intake >= min_safe_intake,
        "warning": "" if target_intake >= min_safe_intake else f"目标摄入量低于安全下限({min_safe_intake:.0f}kcal)，建议适当减少缺口",
    }


def calculate_macros(target_calories: float, protein_ratio: float = 0.30,
                      carb_ratio: float = 0.40, fat_ratio: float = 0.30) -> dict:
    """计算宏量营养素配比。

    Args:
        target_calories: 目标每日摄入热量
        protein_ratio: 蛋白质占比（默认30%）
        carb_ratio: 碳水占比（默认40%）
        fat_ratio: 脂肪占比（默认30%）
    Returns:
        包含各营养素的克数和热量
    """
    total_ratio = protein_ratio + carb_ratio + fat_ratio
    if abs(total_ratio - 1.0) > 0.01:
        # 自动归一化
        protein_ratio /= total_ratio
        carb_ratio /= total_ratio
        fat_ratio /= total_ratio

    calories = float(target_calories)
    # 蛋白质 4kcal/g, 碳水 4kcal/g, 脂肪 9kcal/g
    protein_g = (calories * protein_ratio) / 4
    carb_g = (calories * carb_ratio) / 4
    fat_g = (calories * fat_ratio) / 9

    return {
        "target_calories": round(calories, 1),
        "protein": {"grams": round(protein_g, 1), "calories": round(calories * protein_ratio, 1), "ratio": round(protein_ratio * 100, 1)},
        "carbs": {"grams": round(carb_g, 1), "calories": round(calories * carb_ratio, 1), "ratio": round(carb_ratio * 100, 1)},
        "fat": {"grams": round(fat_g, 1), "calories": round(calories * fat_ratio, 1), "ratio": round(fat_ratio * 100, 1)},
    }
