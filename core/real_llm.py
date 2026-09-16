"""真实大模型适配器（只用标准库 urllib，零依赖）。

支持所有 **OpenAI 兼容** 的 /chat/completions 接口：
    DeepSeek、Moonshot/Kimi、通义千问(DashScope 兼容模式)、智谱、硅基流动、
    vLLM / Ollama / LM Studio 本地服务、以及 OpenAI 本身。

用法：
    from core.real_llm import from_env
    llm = from_env()          # 自动读取环境变量
    if llm is None: ...       # 没配 Key 就退回 Mock

为什么不用官方 SDK？
    1. 学习目的：让你看见 HTTP 请求体到底长什么样（很多玄学问题都在这里）；
    2. 零依赖：不需要 pip install，任何装了 Python 的机器都能跑。
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Sequence

from .errors import LLMError
from .llm import LLM, LLMResponse
from .message import Message
from .parser import parse_tool_calls

# 常见服务商的默认配置：(环境变量前缀, base_url, 默认模型)
PROVIDERS: list[tuple[str, str, str]] = [
    ("DEEPSEEK", "https://api.deepseek.com/v1", "deepseek-chat"),
    ("OPENAI", "https://api.openai.com/v1", "gpt-4o-mini"),
    ("MOONSHOT", "https://api.moonshot.cn/v1", "moonshot-v1-8k"),
    ("DASHSCOPE", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
    ("ZHIPU", "https://open.bigmodel.cn/api/paas/v4", "glm-4-flash"),
    ("SILICONFLOW", "https://api.siliconflow.cn/v1", "Qwen/Qwen2.5-7B-Instruct"),
    ("GENERIC", "http://localhost:11434/v1", "qwen2.5"),   # Ollama 本地
]


class OpenAICompatLLM(LLM):
    """OpenAI 兼容协议的模型客户端。"""

    name = "openai-compat"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.deepseek.com/v1",
        model: str = "deepseek-chat",
        temperature: float = 0.0,
        max_tokens: int = 1024,
        timeout: float = 60.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(model)
        if not api_key:
            raise LLMError("缺少 API Key")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.extra_body = extra_body or {}

    # ------------------------------------------------------------------
    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _payload(self, messages: list[Message], **kwargs: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": kwargs.get("model", self.model),
            "messages": [m.to_openai() for m in messages],
            "temperature": kwargs.get("temperature", self.temperature),
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "stream": False,
        }
        tools = kwargs.get("tools")           # OpenAI 原生 function calling 的工具清单
        if tools:
            body["tools"] = tools
            body["tool_choice"] = kwargs.get("tool_choice", "auto")
        body.update(self.extra_body)
        return body

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        payload = self._payload(messages, **kwargs)
        data = self._post(payload)
        return self._parse_response(data)

    def _post(self, payload: dict[str, Any], retries: int = 3) -> dict[str, Any]:
        """发 HTTP 请求，带针对限流/服务端错误的退避重试。"""
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.endpoint,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
            },
            method="POST",
        )
        last_err = ""
        for attempt in range(1, retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = ""
                try:
                    detail = exc.read().decode("utf-8")[:400]
                except Exception:
                    pass
                last_err = f"HTTP {exc.code}: {detail}"
                retryable = exc.code in (408, 409, 429) or exc.code >= 500
                if not retryable or attempt == retries:
                    raise LLMError(f"{last_err}") from exc
            except urllib.error.URLError as exc:
                last_err = f"网络错误: {exc.reason}"
                if attempt == retries:
                    raise LLMError(last_err) from exc
            except TimeoutError as exc:
                last_err = f"请求超时（{self.timeout}s）"
                if attempt == retries:
                    raise LLMError(last_err) from exc
            time.sleep(min(2 ** (attempt - 1), 4))
        raise LLMError(last_err or "未知错误")

    def _parse_response(self, data: dict[str, Any]) -> LLMResponse:
        try:
            choice = data["choices"][0]
            msg = choice.get("message", {})
        except (KeyError, IndexError) as exc:
            raise LLMError(f"响应结构异常: {json.dumps(data, ensure_ascii=False)[:300]}") from exc

        text = msg.get("content") or ""
        # 原生 function calling：把结构化 tool_calls 还原成我们的文本协议，
        # 这样上层 Agent 的解析逻辑完全不用改（适配器模式的威力）。
        native_calls = msg.get("tool_calls") or []
        if native_calls:
            blocks = []
            for tc in native_calls:
                fn = tc.get("function", {})
                blocks.append(
                    f'<tool_call>{{"id": "{tc.get("id", "")}", "name": "{fn.get("name", "")}", '
                    f'"args": {fn.get("arguments") or "{}"}}}</tool_call>'
                )
            text = (text + "\n" + "\n".join(blocks)).strip()

        usage = data.get("usage", {}) or {}
        return LLMResponse(
            text=text,
            model=data.get("model", self.model),
            prompt_tokens=int(usage.get("prompt_tokens", 0) or 0),
            completion_tokens=int(usage.get("completion_tokens", 0) or 0),
            raw=data,
        )

    # ------------------------------------------------------------------
    def health_check(self) -> tuple[bool, str]:
        """连通性自检：发一条最短的消息，确认 Key / 地址 / 模型名都对。"""
        try:
            resp = self.complete([Message.user("ping")], max_tokens=8)
            return True, f"OK (model={resp.model}, {resp.latency_ms:.0f}ms, 回复={resp.text[:30]!r})"
        except LLMError as exc:
            return False, str(exc)


def find_provider() -> tuple[str, str, str, str] | None:
    """扫描环境变量，返回 (前缀, api_key, base_url, model)。

    约定：只需设置 <PREFIX>_API_KEY，其余两项可选覆盖：
        DEEPSEEK_API_KEY / DEEPSEEK_BASE_URL / DEEPSEEK_MODEL
    """
    for prefix, default_base, default_model in PROVIDERS:
        key = os.environ.get(f"{prefix}_API_KEY", "").strip()
        if key:
            base = os.environ.get(f"{prefix}_BASE_URL", default_base).strip()
            model = os.environ.get(f"{prefix}_MODEL", default_model).strip()
            return prefix, key, base, model
    return None


def from_env(model: str = "", base_url: str = "", api_key: str = "", **kwargs: Any) -> LLM | None:
    """按环境变量构造真实模型；没配 Key 返回 None（调用方应回退到 Mock）。"""
    found = find_provider()
    if not found and not api_key:
        return None
    if found:
        prefix, env_key, env_base, env_model = found
    else:
        prefix, env_key, env_base, env_model = "CUSTOM", "", "", ""
    try:
        return OpenAICompatLLM(
            api_key=api_key or env_key,
            base_url=base_url or env_base,
            model=model or env_model,
            **kwargs,
        )
    except LLMError:
        return None


def get_llm(prefer_real: bool = False, **kwargs: Any) -> tuple[LLM, str]:
    """教学主入口：优先真实模型，缺失则回退 Mock，并说明用的是哪个。"""
    from .mock_llm import default_mock

    if prefer_real:
        real = from_env(**kwargs)
        if real is not None:
            return real, f"真实模型 {real.model} @ {real.base_url}"
        return default_mock(), "未检测到 API Key，已回退到离线 Mock 模型（功能完全够学）"
    return default_mock(), "离线 Mock 模型"


def parse_native_tool_calls(text: str):
    """把适配器还原出来的文本协议再解析回 ToolCall（给高级用法）。"""
    return parse_tool_calls(text)
