"""大模型网关 — 多模型路由、故障降级、统一调用入口。

上层业务只需要调用 gateway.complete()，
网关自动选择最优模型、处理故障降级、记录成本。
"""

import time
import logging
from typing import Optional

from .clients import ModelClient, OpenAICompatibleClient, AnthropicCompatibleClient, FakeModelClient
from .cost_tracker import CostTracker
from ..config import (
    PRIMARY_MODEL, PRIMARY_BASE_URL, PRIMARY_API_KEY,
    FALLBACK_MODEL, FALLBACK_BASE_URL, FALLBACK_API_KEY,
    VISION_MODEL, VISION_BASE_URL, VISION_API_KEY,
    MODEL_TIMEOUT, MODEL_TEMPERATURE, MODEL_MAX_TOKENS,
)

logger = logging.getLogger(__name__)

# ─── 路由策略 ───
ROUTE_SIMPLE = "simple"       # 简单问答用低成本模型
ROUTE_COMPLEX = "complex"     # 复杂生成/分析用高性能模型
ROUTE_VISION = "vision"        # 图像识别
ROUTE_DEFAULT = "default"     # 默认路由


class ModelGateway:
    """大模型网关。

    职责：
    1. 多模型统一适配 — 主备模型标准化接入
    2. 智能路由 — 根据场景选择最优模型
    3. 高可用降级 — 主模型故障时自动切换备用
    4. 成本管控 — 统一记录Token消耗
    """

    def __init__(
        self,
        primary: Optional[ModelClient] = None,
        fallback: Optional[ModelClient] = None,
        cost_tracker: Optional[CostTracker] = None,
    ):
        """初始化模型网关。

        Args:
            primary: 主模型客户端，None 时从配置自动构建
            fallback: 备用模型客户端，None 时从配置自动构建
            cost_tracker: 成本追踪器
        """
        self.primary = primary or self._build_primary()
        self.fallback = fallback or self._build_fallback()
        self.vision = self._build_vision()
        self.cost_tracker = cost_tracker or CostTracker()
        self._failover_count = 0
        self._last_used = "primary"

    @staticmethod
    def _build_primary() -> ModelClient:
        """从配置构建主模型客户端。"""
        if not PRIMARY_API_KEY:
            logger.warning("主模型API Key未配置，使用FakeModelClient")
            return FakeModelClient(outputs=["（模型未配置）"])
        # DeepSeek 使用 Anthropic 兼容协议
        if "anthropic" in PRIMARY_BASE_URL or "deepseek" in PRIMARY_BASE_URL:
            return AnthropicCompatibleClient(
                model=PRIMARY_MODEL, base_url=PRIMARY_BASE_URL,
                api_key=PRIMARY_API_KEY, temperature=MODEL_TEMPERATURE,
                timeout=MODEL_TIMEOUT,
            )
        return OpenAICompatibleClient(
            model=PRIMARY_MODEL, base_url=PRIMARY_BASE_URL,
            api_key=PRIMARY_API_KEY, temperature=MODEL_TEMPERATURE,
            timeout=MODEL_TIMEOUT,
        )

    @staticmethod
    def _build_fallback() -> ModelClient:
        """从配置构建备用模型客户端。"""
        if not FALLBACK_API_KEY:
            logger.warning("备用模型API Key未配置")
            return FakeModelClient(outputs=["（备用模型未配置）"])
        return OpenAICompatibleClient(
            model=FALLBACK_MODEL, base_url=FALLBACK_BASE_URL,
            api_key=FALLBACK_API_KEY, temperature=MODEL_TEMPERATURE,
            timeout=MODEL_TIMEOUT,
        )

    @staticmethod
    def _build_vision() -> Optional[ModelClient]:
        """从配置构建视觉模型客户端（多模态，OpenAI 兼容 chat completions）。

        未配置 VISION_API_KEY 时返回 None，上层应据此降级或报错。
        """
        if not VISION_API_KEY:
            logger.warning("视觉模型API Key未配置，多模态识别不可用")
            return None
        client = OpenAICompatibleClient(
            model=VISION_MODEL, base_url=VISION_BASE_URL,
            api_key=VISION_API_KEY, temperature=0.2,
            timeout=MODEL_TIMEOUT,
        )
        logger.info("视觉模型客户端已构建: %s @ %s", VISION_MODEL, VISION_BASE_URL)
        return client

    def complete(
        self,
        prompt: str,
        max_new_tokens: int = MODEL_MAX_TOKENS,
        user_id: str = "anonymous",
        scene: str = "chat",
        route: str = ROUTE_DEFAULT,
    ) -> str:
        """统一模型调用入口。

        自动处理：
        - 模型路由选择
        - 主模型故障降级到备用
        - Token消耗记录

        Args:
            prompt: 完整 prompt 文本
            max_new_tokens: 最大输出 token
            user_id: 用户标识，用于额度管控
            scene: 调用场景（chat/diet/exercise/analysis等）
            route: 路由策略
        Returns:
            模型生成文本
        """
        # 额度检查
        allowed, reason = self.cost_tracker.check_quota(user_id)
        if not allowed:
            raise RuntimeError(f"调用额度不足: {reason}")

        # 路由选择：简单场景可使用更便宜的模型
        client = self._select_client(route)

        started_at = time.monotonic()
        try:
            text = client.complete(prompt, max_new_tokens=max_new_tokens)
            self._last_used = "primary" if client is self.primary else "fallback"
            self._record_usage(client, user_id, scene, "gateway/complete")
            logger.debug(
                "模型调用成功 client=%s scene=%s duration=%.2fs tokens=%s",
                self._last_used, scene, time.monotonic() - started_at,
                client.last_completion_metadata,
            )
            return text
        except Exception as exc:
            logger.warning("主模型调用失败: %s，尝试降级到备用模型", exc)
            self._failover_count += 1
            # 降级到备用模型
            if client is not self.primary:
                raise  # 已经是备用模型了，不再降级
            try:
                text = self.fallback.complete(prompt, max_new_tokens=max_new_tokens)
                self._last_used = "fallback"
                self._record_usage(self.fallback, user_id, scene, "gateway/complete")
                logger.info("降级到备用模型成功")
                return text
            except Exception as fallback_exc:
                logger.error("备用模型也失败: %s", fallback_exc)
                raise RuntimeError(
                    f"主备模型均不可用。主模型: {exc}; 备用模型: {fallback_exc}"
                ) from fallback_exc

    def complete_with_image(
        self,
        prompt: str,
        image_base64: str,
        max_new_tokens: int = 1024,
        user_id: str = "anonymous",
        scene: str = "vision",
        mime: str = "image/jpeg",
    ) -> str:
        """多模态统一调用入口（图文）。

        优先使用视觉模型客户端；视觉模型失败时若主模型支持多模态则降级到主模型。

        Args:
            prompt: 提示词文本
            image_base64: Base64 编码的图片（可含或不含 data: 前缀）
            max_new_tokens: 最大输出 token
            user_id: 用户标识
            scene: 调用场景
            mime: 图片 MIME 类型
        Returns:
            模型生成文本
        """
        allowed, reason = self.cost_tracker.check_quota(user_id)
        if not allowed:
            raise RuntimeError(f"调用额度不足: {reason}")

        client = self.vision
        if client is None:
            # 视觉模型未配置：尝试用主模型（若主模型支持多模态）
            if self.primary.supports_image():
                client = self.primary
            else:
                raise RuntimeError("视觉模型未配置且主模型不支持多模态图像输入")

        try:
            text = client.complete_with_image(
                prompt, image_base64, max_new_tokens=max_new_tokens, mime=mime,
            )
            self._last_used = "vision" if client is self.vision else "primary"
            self._record_usage(client, user_id, scene, "gateway/complete_with_image")
            logger.debug("视觉模型调用成功 scene=%s", scene)
            return text
        except Exception as exc:
            logger.warning("视觉模型调用失败: %s", exc)
            # 视觉模型失败时尝试降级到主模型（若主模型支持多模态且当前不是主模型）
            if client is self.vision and self.primary.supports_image():
                try:
                    text = self.primary.complete_with_image(
                        prompt, image_base64, max_new_tokens=max_new_tokens, mime=mime,
                    )
                    self._last_used = "primary"
                    self._record_usage(self.primary, user_id, scene, "gateway/complete_with_image")
                    logger.info("视觉模型降级到主模型成功")
                    return text
                except Exception as fallback_exc:
                    raise RuntimeError(
                        f"视觉模型与主模型多模态调用均失败。视觉: {exc}; 主模型: {fallback_exc}"
                    ) from fallback_exc
            raise

    def _select_client(self, route: str) -> ModelClient:
        """根据路由策略选择模型客户端。

        MVP 版本：简单路由，后续可扩展为基于成本/延迟的动态路由。
        """
        # 简单问答场景优先用备用模型（成本更低）
        if route == ROUTE_SIMPLE and self.fallback.health_check():
            return self.fallback
        # 复杂场景用主模型（性能更好）
        return self.primary

    def _record_usage(self, client: ModelClient, user_id: str, scene: str, endpoint: str):
        """记录模型调用量。"""
        meta = client.last_completion_metadata or {}
        self.cost_tracker.record(
            user_id=user_id,
            endpoint=endpoint,
            scene=scene,
            model=meta.get("model", client.model),
            input_tokens=meta.get("input_tokens", 0),
            output_tokens=meta.get("output_tokens", 0),
        )

    def get_stats(self) -> dict:
        """获取网关运行状态。"""
        return {
            "primary_model": self.primary.model,
            "fallback_model": self.fallback.model,
            "vision_model": self.vision.model if self.vision else None,
            "last_used": self._last_used,
            "failover_count": self._failover_count,
            "cost_stats": self.cost_tracker.get_global_stats(),
        }

    def health_check(self) -> dict:
        """检查模型可用性。"""
        return {
            "primary": self.primary.model,
            "primary_available": self.primary.health_check(),
            "fallback": self.fallback.model,
            "fallback_available": self.fallback.health_check(),
            "vision": self.vision.model if self.vision else None,
            "vision_available": self.vision.health_check() if self.vision else False,
        }
