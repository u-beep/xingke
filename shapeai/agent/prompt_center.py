"""Prompt 工程中心。

统一管理系统人设 Prompt、场景化 Prompt、安全约束 Prompt。
支持 Prompt 热更新与版本管理。
"""

import hashlib
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PromptVersion:
    """Prompt 版本信息。"""
    text: str
    version: str = "1.0"
    created_at: str = field(default_factory=_now)
    description: str = ""


# ─── 系统人设 Prompt ───
SYSTEM_PERSONA = textwrap.dedent("""\
    你是 ShapeAI，一位专业的身材管理AI助手。你的职责是帮助用户科学地管理身材，
    包括饮食建议、运动计划、数据分析和生活习惯指导。

    核心原则：
    1. 基于科学依据回答，优先使用工具计算而非猜测
    2. 不提供医疗诊断、处方或治疗方案
    3. 对极端减肥方式（节食、催吐等）予以劝阻并引导健康方式
    4. 回答简洁实用，给出可操作的建议
    5. 主动询问缺失的关键信息（如身高、体重、目标等）
    6. 所有健康/运动类回答需附带免责声明

    你可以使用以下工具来帮助用户。每次只调用一个工具，或直接给出最终答案。

    工具调用格式（JSON）：
    <tool>{"name":"工具名","args":{"参数名":"值"}}</tool>

    最终答案格式：
    <final>你的回答</final>
""")


# ─── 场景化 Prompt 模板 ───
SCENE_PROMPTS = {
    "diet_plan": textwrap.dedent("""\
        你正在为用户生成个性化饮食方案。请基于用户画像和计算结果，
        生成一份包含早中晚三餐的具体食谱，注明食材和分量。
        确保总热量在目标范围内，营养素配比合理。
    """),
    "exercise_plan": textwrap.dedent("""\
        你正在为用户生成运动计划。请基于用户的运动基础、可用时间和目标，
        生成一周的训练计划，包括动作、组数、次数和休息时间。
    """),
    "body_analysis": textwrap.dedent("""\
        你正在为用户分析身材数据。请基于体重趋势、体脂数据等，
        区分水分/肌肉/脂肪波动原因，识别平台期，给出进度评估。
    """),
    "food_recognition": textwrap.dedent("""\
        你正在帮助用户识别食物。请基于图片描述或用户输入，
        识别菜品名称，估算分量和营养成分。
    """),
}


# ─── 安全约束 Prompt ───
SAFETY_PROMPT = textwrap.dedent("""\
    安全约束（必须严格遵守）：
    - 不得提供任何医疗诊断、处方或治疗方案
    - 不得推荐低于基础代谢(BMR)的极低热量饮食方案
    - 不得推荐催吐、断食、滥用药物等有害行为
    - 涉及疾病相关问题，建议用户咨询专业医生
    - 对孕妇、慢病患者、青少年等特殊人群需额外谨慎
""")


class PromptCenter:
    """Prompt 工程中心。

    管理 Prompt 的版本、热更新和场景化调用。
    """

    def __init__(self):
        self._versions: dict[str, list[PromptVersion]] = {
            "system": [PromptVersion(text=SYSTEM_PERSONA, description="系统人设")],
            "safety": [PromptVersion(text=SAFETY_PROMPT, description="安全约束")],
        }
        self._scene_prompts = dict(SCENE_PROMPTS)
        self._active: dict[str, str] = {
            "system": "1.0",
            "safety": "1.0",
        }

    def get(self, name: str) -> str:
        """获取当前活跃版本的 Prompt 文本。"""
        versions = self._versions.get(name, [])
        if not versions:
            return self._scene_prompts.get(name, "")
        active_version = self._active.get(name, "1.0")
        for v in versions:
            if v.version == active_version:
                return v.text
        return versions[-1].text

    def get_scene_prompt(self, scene: str) -> str:
        """获取场景化 Prompt。"""
        return self._scene_prompts.get(scene, "")

    def update(self, name: str, text: str, description: str = "") -> str:
        """更新 Prompt（创建新版本）。

        Returns:
            新版本号
        """
        versions = self._versions.setdefault(name, [])
        new_version_num = len(versions) + 1
        new_version = f"{new_version_num}.0"
        versions.append(PromptVersion(text=text, version=new_version, description=description))
        self._active[name] = new_version
        return new_version

    def set_active(self, name: str, version: str) -> bool:
        """设置活跃版本。"""
        versions = self._versions.get(name, [])
        for v in versions:
            if v.version == version:
                self._active[name] = version
                return True
        return False

    def list_versions(self, name: str) -> list[dict]:
        """列出 Prompt 的所有版本。"""
        versions = self._versions.get(name, [])
        return [
            {
                "version": v.version,
                "created_at": v.created_at,
                "description": v.description,
                "is_active": v.version == self._active.get(name),
            }
            for v in versions
        ]

    def build_prefix(self, tools: dict) -> str:
        """构建完整的 prompt 前缀。

        Args:
            tools: 工具注册表
        Returns:
            前缀文本
        """
        # 系统人设
        persona = self.get("system")
        # 安全约束
        safety = self.get("safety")
        # 工具列表
        tool_lines = []
        for name, spec in tools.items():
            fields = ", ".join(f"{k}: {v}" for k, v in spec.get("schema", {}).items())
            risk = "approval required" if spec.get("risky", False) else "safe"
            tool_lines.append(f"- {name}({fields}) [{risk}] {spec.get('description', '')}")
        tool_text = "\n".join(tool_lines)

        # 示例
        examples = "\n".join([
            '<tool>{"name":"calculate_bmr","args":{"gender":"male","age":25,"weight":70,"height":175}}</tool>',
            '<tool>{"name":"generate_diet_plan","args":{"target_calories":1800,"meals_per_day":3}}</tool>',
            "<final>根据您的身体数据，您的BMR为1650kcal，TDEE为2310kcal。建议每日摄入1800kcal...</final>",
        ])

        prefix = f"""{persona}

Tools:
{tool_text}

Valid response examples:
{examples}

{safety}
"""
        return prefix.strip()

    @staticmethod
    def hash_prompt(text: str) -> str:
        """计算 Prompt 哈希（用于缓存键）。"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
