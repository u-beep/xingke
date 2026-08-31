"""模型后端适配层 — 统一 complete() 接口。

不同 provider 在 HTTP 接口、响应结构上都有差异，
这些差异都在这里被抹平成统一的 complete() 接口。
上层网关只管路由和降级，不需要知道底层细节。
"""

import json
import time
import logging
import urllib.error
import urllib.request
from http.client import RemoteDisconnected
from typing import Optional

logger = logging.getLogger(__name__)


class ModelClient:
    """模型客户端基类，定义统一接口。"""

    def __init__(self, model: str, base_url: str = "", api_key: str = "", temperature: float = 0.3, timeout: int = 300):
        self.model = model
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.temperature = temperature
        self.timeout = timeout
        self.last_completion_metadata: dict = {}

    def complete(self, prompt: str, max_new_tokens: int = 2048, **kwargs) -> str:
        """向模型发起一次调用，返回生成文本。"""
        raise NotImplementedError

    def complete_with_image(
        self, prompt: str, image_base64: str,
        max_new_tokens: int = 2048, mime: str = "image/jpeg", **kwargs,
    ) -> str:
        """向模型发起一次多模态调用（图文），返回生成文本。

        基类默认不支持，子类按需覆写。上层通过该方法是否被覆写来做特性探测。
        """
        raise NotImplementedError("该模型客户端不支持多模态图像输入")

    def supports_image(self) -> bool:
        """是否支持图文多模态调用。"""
        return type(self).complete_with_image is not ModelClient.complete_with_image

    def health_check(self) -> bool:
        """检查模型后端是否可用。"""
        return True


class FakeModelClient(ModelClient):
    """伪模型客户端，用于测试。按预设队列依次返回固定输出。"""

    def __init__(self, outputs: list[str]):
        super().__init__(model="fake", base_url="", api_key="", temperature=0.0, timeout=0)
        self.outputs = list(outputs)
        self.prompts: list[str] = []

    def complete(self, prompt: str, max_new_tokens: int = 2048, **kwargs) -> str:
        self.prompts.append(prompt)
        self.last_completion_metadata = {"input_tokens": len(prompt) // 4, "output_tokens": 0}
        if not self.outputs:
            raise RuntimeError("fake model ran out of outputs")
        output = self.outputs.pop(0)
        self.last_completion_metadata["output_tokens"] = len(output) // 4
        return output

    def health_check(self) -> bool:
        return bool(self.outputs)


class OpenAICompatibleClient(ModelClient):
    """OpenAI 兼容模型客户端（Chat Completions API）。"""

    def complete(self, prompt: str, max_new_tokens: int = 2048, **kwargs) -> str:
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        return self._post_chat_and_parse(payload)

    def complete_with_image(
        self, prompt: str, image_base64: str,
        max_new_tokens: int = 2048, mime: str = "image/jpeg", **kwargs,
    ) -> str:
        """多模态调用：图文混排 content（OpenAI 兼容格式）。"""
        self.last_completion_metadata = {}
        # 防御性去掉 data:...;base64, 前缀
        if "," in image_base64 and image_base64.startswith("data:"):
            image_base64 = image_base64.split(",", 1)[1]
        data_url = f"data:{mime};base64,{image_base64}"
        payload = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            }],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        return self._post_chat_and_parse(payload)

    def _post_chat_and_parse(self, payload: dict) -> str:
        """统一的 POST /v1/chat/completions + 响应解析。

        text 与 image 两种调用仅 messages.content 形态不同，
        HTTP 发送、重试、解析、用量记录在此收敛复用。
        """
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        base = self.base_url
        # 仅当 URL 尚未包含 /v1 路径时才补全，
        # 兼容 https://host/v1/openai/native 这类已含 /v1 的网关地址。
        if not base.rstrip("/").endswith("/v1") and "/v1/" not in base:
            base = base.rstrip("/") + "/v1"
        else:
            base = base.rstrip("/")

        request = urllib.request.Request(
            base + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        attempts = 3
        body_text = ""
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body_text = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"模型请求失败 HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, RemoteDisconnected) as exc:
                if attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"无法连接模型服务: {self.base_url}") from exc

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("模型返回非JSON内容") from exc

        if data.get("error"):
            raise RuntimeError(f"模型错误: {data['error']}")

        choices = data.get("choices", [])
        if not choices:
            raise RuntimeError("模型返回空choices")

        content = choices[0].get("message", {}).get("content", "")
        usage = data.get("usage", {})
        self.last_completion_metadata = {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "model": self.model,
        }
        return content

    def health_check(self) -> bool:
        try:
            self.complete("ping", max_new_tokens=5)
            return True
        except Exception:
            return False


class AnthropicCompatibleClient(ModelClient):
    """Anthropic 兼容模型客户端（Messages API）。"""

    def complete(self, prompt: str, max_new_tokens: int = 2048, **kwargs) -> str:
        self.last_completion_metadata = {}
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_new_tokens,
            "stream": False,
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }

        base = self.base_url
        if not base.endswith("/v1"):
            base = base.rstrip("/") + "/v1"

        request = urllib.request.Request(
            base + "/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        attempts = 3
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body_text = response.read().decode("utf-8")
                break
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                if exc.code >= 500 and attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"模型请求失败 HTTP {exc.code}: {body}") from exc
            except (urllib.error.URLError, RemoteDisconnected) as exc:
                if attempt < attempts - 1:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"无法连接模型服务: {self.base_url}") from exc

        try:
            data = json.loads(body_text)
        except json.JSONDecodeError as exc:
            raise RuntimeError("模型返回非JSON内容") from exc

        if data.get("error"):
            raise RuntimeError(f"模型错误: {data['error']}")

        # 尝试 Anthropic Messages API 格式: content[].type == "text"
        content_list = data.get("content", [])
        if content_list:
            # 优先提取 type=text 的块（标准 Anthropic 格式）
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    usage = data.get("usage", {})
                    self.last_completion_metadata = {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "model": self.model,
                    }
                    return text

            # DeepSeek 兼容：只有 thinking 块时，提取 thinking 内容作为回复
            # thinking 块格式: {"type": "thinking", "thinking": "..."}
            thinking_text = ""
            for item in content_list:
                if isinstance(item, dict) and item.get("type") == "thinking":
                    thinking_text = item.get("thinking", "") or item.get("text", "")
                    break
            if thinking_text:
                usage = data.get("usage", {})
                self.last_completion_metadata = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "model": self.model,
                }
                logger.debug("从 thinking 块提取文本，长度=%d", len(thinking_text))
                return thinking_text

            # content 存在但没有 type=text/thinking 的块，尝试取第一个有 text 字段的块
            for item in content_list:
                if isinstance(item, dict) and item.get("text"):
                    text = item.get("text", "")
                    usage = data.get("usage", {})
                    self.last_completion_metadata = {
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "model": self.model,
                    }
                    return text
            # content 是字符串而非列表
            if isinstance(content_list, str):
                usage = data.get("usage", {})
                self.last_completion_metadata = {
                    "input_tokens": usage.get("input_tokens", 0),
                    "output_tokens": usage.get("output_tokens", 0),
                    "model": self.model,
                }
                return content_list

        # 降级：尝试 OpenAI 兼容格式 choices[0].message.content
        choices = data.get("choices", [])
        if choices:
            content = choices[0].get("message", {}).get("content", "")
            if content:
                usage = data.get("usage", {})
                self.last_completion_metadata = {
                    "input_tokens": usage.get("prompt_tokens", usage.get("input_tokens", 0)),
                    "output_tokens": usage.get("completion_tokens", usage.get("output_tokens", 0)),
                    "model": self.model,
                }
                return content

        # 所有解析方式都失败，记录原始响应用于调试
        logger.error("无法从模型响应中提取文本，原始响应: %s", body_text[:1000])
        raise RuntimeError("无法从模型响应中提取文本")
