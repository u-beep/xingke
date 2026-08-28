"""食物图像识别服务。

MVP版本：使用规则匹配 + LLM描述辅助识别。
后续可替换为 YOLOv8 微调模型 + 营养数据库查询。

主要功能：
1. 食物图像识别 — 菜品名称、置信度
2. 分量估算 — 单份营养成分
3. 多菜品同框识别 — 自动拆分
4. 图片预处理 — 压缩、裁剪、画质归一化
5. 标注回流 — 低置信度结果归集
"""

import base64
import json
import logging
import re
from typing import Optional

from ..config import FOOD_ALIAS, FOOD_DATABASE

logger = logging.getLogger(__name__)


class FoodRecognitionService:
    """食物图像识别服务。

    MVP版本：基于用户描述/关键词 + 营养数据库查询。
    后续可接入 YOLOv8 模型做真正的图像识别。
    """

    def __init__(self, gateway=None):
        """初始化食物识别服务。

        Args:
            gateway: 模型网关，用于LLM辅助识别
        """
        self.gateway = gateway
        self._low_confidence_log: list[dict] = []
        self._food_db = FOOD_DATABASE

    def recognize(
        self,
        image_base64: str | None = None,
        description: str | None = None,
        user_id: str = "anonymous",
    ) -> dict:
        """识别食物。

        Args:
            image_base64: Base64编码的图片数据（MVP版本暂不使用）
            description: 用户对食物的文字描述
            user_id: 用户ID
        Returns:
            包含识别结果和营养信息的字典
        """
        # 图片预处理（MVP版本仅做基本校验）
        if image_base64:
            preprocessed = self._preprocess_image(image_base64)
            if not preprocessed["valid"]:
                return {"error": preprocessed["message"], "recognized": []}

        # 识别路径选择：
        # 1) 优先多模态视觉模型识别图片中的食材
        # 2) 退而求其次用文字描述 + 营养库规则匹配
        if image_base64 and self.gateway and self._gateway_supports_image():
            results = self._recognize_by_vision(image_base64, user_id)
        elif description:
            results = self._recognize_by_description(description, user_id)
        elif image_base64 and self.gateway:
            # 有图片但视觉模型不可用，降级到文本路径
            results = self._recognize_by_llm_description("用户上传了一张食物图片", user_id)
        else:
            return {"error": "请提供图片或食物描述", "recognized": []}

        # 低置信度结果归集
        for r in results:
            if r.get("confidence", 0) < 0.6:
                self._log_low_confidence(r, user_id)

        return {
            "recognized": results,
            "total_items": len(results),
            "total_calories": sum(r.get("calories", 0) for r in results),
        }

    def _gateway_supports_image(self) -> bool:
        """网关是否支持多模态图文调用。"""
        return getattr(self.gateway, "vision", None) is not None or \
            getattr(self.gateway, "supports_image", lambda: False)()

    def _recognize_by_vision(self, image_base64: str, user_id: str) -> list[dict]:
        """使用多模态视觉模型识别图片中的食材。

        返回结构化食材列表：name / category / quantity_g / unit / confidence，
        并附带营养参考（命中内置营养库时）与 food_name 兼容字段。
        """
        food_names_hint = "、".join(self._food_db.keys())
        prompt = f"""请识别这张冰箱/食材照片中出现的所有食材（仅原始食材，不要成品菜肴）。

已知食材名称参考（优先使用这些名称以便营养对齐）：{food_names_hint}

要求：
1. 仅返回严格 JSON 数组，不要 markdown 代码块、不要解释文字。
2. 每个元素：{{"name":"食材名","category":"分类","quantity_g":整数克数估值,"unit":"g或个或包或ml","confidence":0.0-1.0}}
3. category 从 [蔬菜, 肉蛋, 主食, 水果, 乳制品, 调味, 其他] 中选择。
4. 如果不是食材图片或无法识别，返回空数组 []。

输出："""

        try:
            response = self.gateway.complete_with_image(
                prompt, image_base64, max_new_tokens=1024,
                user_id=user_id, scene="fridge_recognition",
            )
            items = self._parse_ingredient_response(response)
            # 营养对齐 + 兼容字段
            for it in items:
                name = it.get("name", "")
                it["food_name"] = name
                # 别名 → 标准名,再精确/模糊匹配
                std_name = FOOD_ALIAS.get(name, name)
                nutrition = (
                    self._food_db.get(std_name)
                    or self._food_db.get(name)
                    or self._fuzzy_match_food(name)
                )
                if nutrition:
                    qty = it.get("quantity_g", 100) or 100
                    mult = qty / 100.0
                    it["calories"] = round(nutrition["calories"] * mult, 1)
                    it["protein"] = round(nutrition["protein"] * mult, 1)
                    it["carbs"] = round(nutrition["carbs"] * mult, 1)
                    it["fat"] = round(nutrition["fat"] * mult, 1)
                    it.setdefault("unit", nutrition.get("unit", "g"))
                else:
                    it.setdefault("calories", 0)
                    it.setdefault("protein", 0)
                    it.setdefault("carbs", 0)
                    it.setdefault("fat", 0)
                it.setdefault("quantity_g", it.get("quantity_g", 0) or 0)
                it.setdefault("unit", "g")
                it.setdefault("category", "")
                it.setdefault("confidence", 0.8)
            return items
        except Exception as exc:
            logger.warning("视觉模型识别失败: %s", exc)
            return [{
                "name": "未知",
                "food_name": "未知",
                "confidence": 0.1,
                "message": f"视觉识别服务暂时不可用: {exc}",
                "quantity_g": 0,
                "unit": "g",
                "category": "",
                "calories": 0,
                "protein": 0,
                "carbs": 0,
                "fat": 0,
            }]

    def _fuzzy_match_food(self, name: str) -> dict | None:
        """食材名精确匹配失败时的模糊匹配:双向子串包含。

        例:LLM 返回"小番茄"而库 key 是"番茄",含字串可命中。
        长度≥2 才参与,避免单字误匹配。
        """
        if not name or len(name) < 2:
            return None
        for key, val in self._food_db.items():
            if len(key) >= 2 and key in name:
                return val
        for key, val in self._food_db.items():
            if len(key) >= 2 and name in key:
                return val
        return None

    @staticmethod
    def _parse_ingredient_response(response: str) -> list[dict]:
        """解析视觉模型返回的食材 JSON 数组。"""
        if not response:
            return []
        # 去除可能的 markdown 代码块围栏
        text = response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict) and d.get("name")]
            if isinstance(data, dict) and "recognized" in data:
                return [d for d in data["recognized"] if isinstance(d, dict) and d.get("name")]
            if isinstance(data, dict) and "ingredients" in data:
                return [d for d in data["ingredients"] if isinstance(d, dict) and d.get("name")]
        except json.JSONDecodeError:
            pass
        # 正则兜底提取 JSON 数组
        match = re.search(r'\[[\s\S]*\]', response)
        if match:
            try:
                data = json.loads(match.group())
                return [d for d in data if isinstance(d, dict) and d.get("name")]
            except json.JSONDecodeError:
                pass
        return []

    def _recognize_by_description(self, description: str, user_id: str) -> list[dict]:
        """基于文字描述识别食物。

        从描述中提取食物名称，查询营养数据库。
        """
        results = []
        desc_lower = description.lower().strip()

        # 在食物数据库中查找匹配
        matched_foods = []
        for food_name, nutrition in self._food_db.items():
            if food_name in desc_lower or desc_lower in food_name:
                matched_foods.append((food_name, nutrition, 0.9))

        # 如果没有直接匹配，尝试用LLM辅助
        if not matched_foods and self.gateway:
            llm_results = self._recognize_by_llm_description(description, user_id)
            return llm_results

        # 如果仍然没有匹配，给出提示
        if not matched_foods:
            return [{
                "food_name": "未知食物",
                "confidence": 0.1,
                "message": f"无法识别'{description}'，请提供更详细的描述（如：一碗米饭、两个鸡蛋）",
                "calories": 0,
                "protein": 0,
                "carbs": 0,
                "fat": 0,
            }]

        # 解析分量
        portion_multiplier = self._estimate_portion(description)

        for food_name, nutrition, confidence in matched_foods:
            results.append({
                "food_name": food_name,
                "confidence": confidence,
                "portion": f"{portion_multiplier * 100:.0f}g" if portion_multiplier != 1 else nutrition["unit"],
                "calories": round(nutrition["calories"] * portion_multiplier, 1),
                "protein": round(nutrition["protein"] * portion_multiplier, 1),
                "carbs": round(nutrition["carbs"] * portion_multiplier, 1),
                "fat": round(nutrition["fat"] * portion_multiplier, 1),
            })

        return results

    def _recognize_by_llm_description(self, description: str, user_id: str) -> list[dict]:
        """使用LLM辅助识别食物。"""
        prompt = f"""请根据以下描述识别食物并估算营养成分。

用户描述：{description}

已知食物营养数据库（每100g）：
{json.dumps(self._food_db, ensure_ascii=False, indent=2)}

请以JSON格式输出识别结果：
[
  {{
    "food_name": "食物名称",
    "confidence": 0.0-1.0,
    "portion": "估算分量",
    "calories": 估算热量,
    "protein": 蛋白质g,
    "carbs": 碳水g,
    "fat": 脂肪g
  }}
]

如果是多个食物，返回多个对象。如果无法识别，返回空数组。"""

        try:
            response = self.gateway.complete(
                prompt, max_new_tokens=1024,
                user_id=user_id, scene="food_recognition",
            )
            return self._parse_recognition_response(response)
        except Exception as exc:
            logger.warning("LLM食物识别失败: %s", exc)
            return [{
                "food_name": "未知",
                "confidence": 0.1,
                "message": f"识别服务暂时不可用",
                "calories": 0,
                "protein": 0,
                "carbs": 0,
                "fat": 0,
            }]

    @staticmethod
    def _estimate_portion(description: str) -> float:
        """从描述中估算分量倍数。"""
        desc = description.lower()

        # 匹配数量词
        patterns = [
            (r"一碗|一盘|一份|一个|一杯", 1.0),
            (r"两碗|两盘|两份|两个|两杯", 2.0),
            (r"三碗|三盘|三份|三个|三杯", 3.0),
            (r"半碗|半盘|半份|半个|半杯", 0.5),
            (r"小份|少量|一点点", 0.5),
            (r"大份|很多|一大盘", 1.5),
            (r"(\d+)碗|(\d+)盘|(\d+)份|(\d+)个|(\d+)杯", None),  # 动态匹配
        ]

        for pattern, multiplier in patterns:
            match = re.search(pattern, desc)
            if match:
                if multiplier is None:
                    # 动态提取数字
                    num = next((int(g) for g in match.groups() if g), 1)
                    return float(num)
                return multiplier

        # 默认1份
        return 1.0

    @staticmethod
    def _preprocess_image(image_base64: str) -> dict:
        """图片预处理（MVP版本仅做基本校验）。"""
        if not image_base64:
            return {"valid": False, "message": "图片数据为空"}

        try:
            # 尝试解码Base64
            if "," in image_base64:
                # 去除 data:image/xxx;base64, 前缀
                image_base64 = image_base64.split(",", 1)[1]
            data = base64.b64decode(image_base64)
            if len(data) < 100:
                return {"valid": False, "message": "图片文件过小，可能无效"}
            if len(data) > 10 * 1024 * 1024:
                return {"valid": False, "message": "图片文件过大（>10MB），请压缩后上传"}
            return {"valid": True, "size": len(data)}
        except Exception as exc:
            return {"valid": False, "message": f"图片解码失败: {exc}"}

    @staticmethod
    def _parse_recognition_response(response: str) -> list[dict]:
        """解析LLM返回的识别结果JSON。"""
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return data
            if isinstance(data, dict) and "recognized" in data:
                return data["recognized"]
        except json.JSONDecodeError:
            # 尝试提取JSON数组
            match = re.search(r'\[[\s\S]*\]', response)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
        return [{"food_name": "未知", "confidence": 0.1, "message": "识别结果解析失败"}]

    def _log_low_confidence(self, result: dict, user_id: str):
        """记录低置信度识别结果，供后续人工标注回流。"""
        self._low_confidence_log.append({
            "user_id": user_id,
            "result": result,
            "needs_manual_review": True,
        })

    def get_low_confidence_log(self, limit: int = 50) -> list[dict]:
        """获取低置信度识别记录（供人工标注）。"""
        return self._low_confidence_log[-limit:]

    def clear_low_confidence_log(self):
        """清空低置信度记录。"""
        self._low_confidence_log.clear()

    def get_food_database(self) -> dict:
        """获取内置食物营养数据库。"""
        return dict(self._food_db)
