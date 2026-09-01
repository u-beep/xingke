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
import time
from typing import Optional

from ..config import FOOD_ALIAS, FOOD_DATABASE

logger = logging.getLogger(__name__)

# 营养库未命中的食材按分类给保守估值（每100g），避免出现 0kcal 的明显不合理记录
_CATEGORY_FALLBACK_NUTRITION = {
"蔬菜": {"calories": 25, "protein": 1.2, "carbs": 4.5, "fat": 0.2},
"肉蛋": {"calories": 170, "protein": 18.0, "carbs": 1.0, "fat": 10.0},
"主食": {"calories": 180, "protein": 5.0, "carbs": 35.0, "fat": 2.0},
"水果": {"calories": 55, "protein": 0.6, "carbs": 13.0, "fat": 0.3},
"乳制品": {"calories": 130, "protein": 8.0, "carbs": 6.0, "fat": 8.0},
"调味": {"calories": 320, "protein": 2.0, "carbs": 15.0, "fat": 28.0},
"其他": {"calories": 150, "protein": 4.0, "carbs": 18.0, "fat": 6.0},
}


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
        # 营养库外食材的营养缓存：模型查询结果留存，避免重复请求
        self._nutrition_cache: dict[str, dict] = {}

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
        # 1) 优先多模态视觉模型识别图片中的食物（先完整菜品，再拆解食材）
        # 2) 退而求其次用文字描述 + 营养库规则匹配
        dish = ""
        if image_base64 and self.gateway and self._gateway_supports_image():
            try:
                results, dish = self._recognize_by_vision(image_base64, user_id)
            except Exception as exc:
                # 多次重试后仍失败，才返回失败结果
                logger.warning("视觉识别重试后仍失败: %s", exc)
                return {
                    "error": f"视觉识别失败：{exc}",
                    "recognized": [],
                    "dish": "",
                }
        elif description:
            results = self._recognize_by_description(description, user_id)
        elif image_base64 and self.gateway:
            # 有图片但视觉模型不可用，降级到文本路径
            results = self._recognize_by_llm_description("用户上传了一张食物图片", user_id)
        else:
            return {"error": "请提供图片或食物描述", "recognized": [], "dish": ""}

        # 低置信度结果归集
        for r in results:
            if r.get("confidence", 0) < 0.6:
                self._log_low_confidence(r, user_id)

        return {
            "recognized": results,
            "dish": dish or (results[0].get("name", "") if results else ""),
            "total_items": len(results),
            "total_calories": sum(r.get("calories", 0) for r in results),
        }

    def _gateway_supports_image(self) -> bool:
        """网关是否支持多模态图文调用。"""
        return getattr(self.gateway, "vision", None) is not None or \
            getattr(self.gateway, "supports_image", lambda: False)()

    def _recognize_by_vision(self, image_base64: str, user_id: str) -> tuple[list[dict], str]:
        """使用多模态视觉模型识别图片中的食物。

        先让模型判断完整食物/菜品，再拆解食材明细。
        返回 (食材列表, 完整食物名称)；多次重试后仍失败则抛出 RuntimeError。
        """
        food_names_hint = "、".join(self._food_db.keys())
        prompt = f"""请识别这张照片中的食物。先判断图中完整的食物或菜品是什么（如"火腿三明治"、"蔬菜沙拉"），再拆解出其中包含的食材。

已知食材名称参考（优先使用这些名称以便营养对齐）：{food_names_hint}

要求：
1. 仅返回严格 JSON 对象，不要 markdown 代码块、不要解释文字，格式：
{{"dish":"完整食物或菜品的名称","ingredients":[{{"name":"食材名","category":"分类","quantity_g":整数克数估值,"unit":"g或个或包或ml","confidence":0.0-1.0}}]}}
2. category 从 [蔬菜, 肉蛋, 主食, 水果, 乳制品, 调味, 其他] 中选择。
3. 如果照片中没有食物或无法识别，返回 {{"dish":"","ingredients":[]}}。

输出："""

        last_error = ""
        for attempt in range(3):
            try:
                response = self.gateway.complete_with_image(
                    prompt, image_base64, max_new_tokens=1024,
                    user_id=user_id, scene="fridge_recognition",
                )
                dish, items = self._parse_vision_response(response)
                if items:
                    return self._enrich_items(items, user_id), dish
                last_error = "模型未识别到食物"
            except Exception as exc:
                last_error = str(exc)
                logger.warning("视觉模型识别第 %d 次尝试失败: %s", attempt + 1, exc)
            if attempt < 2:
                time.sleep(1.0 * (attempt + 1))
        raise RuntimeError(last_error or "视觉识别失败")

    def _apply_nutrition(self, item: dict, nutrition: dict) -> None:
        """把每100g营养数据按食材克重换算后写入条目。"""
        qty = item.get("quantity_g", 100) or 100
        mult = qty / 100.0
        item["calories"] = round(float(nutrition.get("calories", 0)) * mult, 1)
        item["protein"] = round(float(nutrition.get("protein", 0)) * mult, 1)
        item["carbs"] = round(float(nutrition.get("carbs", 0)) * mult, 1)
        item["fat"] = round(float(nutrition.get("fat", 0)) * mult, 1)
        item.setdefault("unit", nutrition.get("unit", "g"))

    def _apply_category_estimate(self, item: dict) -> None:
        """在线查询也不可得时，按分类给保守估值（绝不允许 0 值营养）。"""
        qty = item.get("quantity_g", 100) or 100
        mult = qty / 100.0
        est = _CATEGORY_FALLBACK_NUTRITION.get(item.get("category", ""), _CATEGORY_FALLBACK_NUTRITION["其他"])
        item["calories"] = round(est["calories"] * mult, 1)
        item["protein"] = round(est["protein"] * mult, 1)
        item["carbs"] = round(est["carbs"] * mult, 1)
        item["fat"] = round(est["fat"] * mult, 1)
        logger.info("食材 %s 在线营养查询不可得，按分类 %s 估算: %skcal/%.0fg",
                    item.get("name", ""), item.get("category", "其他"), item["calories"], qty)

    def _enrich_items(self, items: list[dict], user_id: str = "anonymous") -> list[dict]:
        """营养对齐：本地营养库 → 模型知识在线查询 → 分类估算兜底。"""
        pending: list[tuple[dict, str]] = []  # 未命中 (条目, 标准名)
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
                self._apply_nutrition(it, nutrition)
                it.setdefault("category", "")
                it.setdefault("confidence", 0.8)
            else:
                pending.append((it, std_name))

        if pending:
            fetched: dict[str, dict] = {}
            if self.gateway:
                try:
                    fetched = self._lookup_nutrition_online([std for _, std in pending], user_id)
                except Exception as exc:
                    logger.warning("在线查询营养失败，改用分类估算: %s", exc)
            for it, std_name in pending:
                nutrition = fetched.get(std_name) or fetched.get(it.get("name", ""))
                if nutrition and float(nutrition.get("calories", 0) or 0) > 0:
                    self._apply_nutrition(it, nutrition)
                else:
                    self._apply_category_estimate(it)

        for it in items:
            it.setdefault("quantity_g", it.get("quantity_g", 0) or 0)
            it.setdefault("unit", "g")
            it.setdefault("category", "")
            it.setdefault("confidence", 0.8)
        return items

    def _lookup_nutrition_online(self, names: list[str], user_id: str) -> dict[str, dict]:
        """本地营养库未命中时，用模型知识查询食物营养（每100g）。

        结果缓存在实例内，同一食材只查询一次。
        Returns:
            {食物名: {calories, protein, carbs, fat}}（仅包含查询成功的条目）
        """
        result: dict[str, dict] = {}
        missing: list[str] = []
        for name in names:
            cached = self._nutrition_cache.get(name)
            if cached:
                result[name] = cached
            else:
                missing.append(name)
        if not missing:
            return result

        prompt = f"""请查询以下食物每100g的营养成分（参考《中国食物成分表》等权威营养数据）：

{json.dumps(missing, ensure_ascii=False)}

仅返回严格 JSON 对象，不要 markdown 代码块、不要解释文字，格式：
{{"nutrition": {{"食物名": {{"calories": 热量kcal, "protein": 蛋白质g, "carbs": 碳水g, "fat": 脂肪g}}}}}}

要求：
1. 数值必须是每100g可食部分的合理值（常见烹调状态）。
2. 不确定时给出保守估计，禁止返回 0 或负数。

输出："""

        response = self.gateway.complete(
            prompt, max_new_tokens=1024,
            user_id=user_id, scene="nutrition_lookup",
        )
        data = self._parse_json_object(response)
        lookup = data.get("nutrition") if isinstance(data, dict) else None
        if isinstance(lookup, dict):
            for name, val in lookup.items():
                if not isinstance(val, dict):
                    continue
                try:
                    entry = {
                        "calories": float(val.get("calories", 0) or 0),
                        "protein": float(val.get("protein", 0) or 0),
                        "carbs": float(val.get("carbs", 0) or 0),
                        "fat": float(val.get("fat", 0) or 0),
                    }
                except (TypeError, ValueError):
                    continue
                if entry["calories"] <= 0:
                    continue
                result[name] = entry
                self._nutrition_cache[name] = entry
                logger.info("食材 %s 通过模型知识获取营养: %skcal/100g", name, entry["calories"])
        return result

    @staticmethod
    def _parse_json_object(response: str) -> dict:
        """解析模型返回的 JSON 对象，兼容 markdown 围栏与裸片段。"""
        if not response:
            return {}
        text = response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        try:
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            match = re.search(r'\{[\s\S]*\}', response)
            if match:
                try:
                    data = json.loads(match.group())
                    return data if isinstance(data, dict) else {}
                except json.JSONDecodeError:
                    return {}
            return {}

    @staticmethod
    def _parse_vision_response(response: str) -> tuple[str, list[dict]]:
        """解析视觉模型返回结果，兼容多种格式。

        支持：{"dish":..., "ingredients":[...]}、{"recognized":[...]}、裸数组 [...]。
        返回 (dish, 食材列表)。
        """
        if not response:
            return "", []
        # 去除可能的 markdown 代码块围栏
        text = response.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 正则兜底提取 JSON 片段
            match = re.search(r'\{[\s\S]*\}', response) or re.search(r'\[[\s\S]*\]', response)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return "", []
        if isinstance(data, dict):
            items = data.get("ingredients") or data.get("recognized") or []
            dish = str(data.get("dish") or "").strip()
            return dish, [d for d in items if isinstance(d, dict) and d.get("name")]
        if isinstance(data, list):
            return "", [d for d in data if isinstance(d, dict) and d.get("name")]
        return "", []

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
