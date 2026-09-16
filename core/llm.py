"""统一的大模型接口（LLM 抽象层）。

为什么第一件事就要做抽象？
    Agent 的内核逻辑（循环、工具调用、记忆）**不应该**依赖任何一家厂商的 SDK。
    只要模型能"根据消息列表返回下一段文本"，Agent 就能跑。
    这样：
      1. 学习阶段可以用 Mock 模型离线跑，不烧钱、不联网、结果可复现；
      2. 换模型（GPT / Claude / DeepSeek / 本地模型）不用改 Agent 一行代码；
      3. 测试可以注入"故意犯错"的假模型，专门验证错误处理路径。

这就是软件工程里的依赖倒置原则（DIP）在 Agent 开发中的第一次应用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from .errors import LLMError as _CanonicalLLMError
from .message import Message


@dataclass
class LLMResponse:
    """模型一次回复的统一结构。

    注意 `usage`：从第一天就统计 token，是后面"成本优化"阶段的基础。
    """

    text: str
    model: str = "unknown"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMError(_CanonicalLLMError, RuntimeError):
    """模型调用失败（网络、限流、鉴权……）。Agent 需要有重试策略。

    ★ 为什么它同时继承 core.errors.LLMError 和 RuntimeError？

        这是一个真实的、很隐蔽的 Bug 修复记录：

        最早 `core/errors.py` 和 `core/llm.py` 各自定义了一个 `LLMError`，
        两者毫无关系。而 Agent 主循环里写的是：

            from .errors import LLMError
            try:
                resp = self.llm.complete(...)
            except LLMError:              # ← 只抓 core.errors.LLMError
                ...退避重试...

        但适配器实际抛出的是 `core.llm.LLMError`。结果：
          · 重试分支**永远不会执行**；
          · 异常一路冒到 Agent.run 的兜底 except，变成 stop_reason="error"；
          · 表象是"模型一抖动任务就失败"，而代码看起来明明写了重试。

        这类"两个同名异常类"的坑在多人协作的项目里非常常见，
        而且静态检查也发现不了（两边都能 import 成功）。

        修复方式：让 `core.llm.LLMError` 继承 `core.errors.LLMError`，
        "谁抛的"和"谁接的"终于对上了。同时保留 RuntimeError 基类，
        不破坏外部已有的 `except RuntimeError` 兼容性。
    """


class LLM:
    """所有模型适配器的基类。

    子类只需要实现 `_complete()`：把 messages 变成一段文本。
    """

    name: str = "base"
    model: str = "base"

    def __init__(self, model: str | None = None) -> None:
        if model:
            self.model = model
        # 每个实例独立的用量统计（类属性只是默认值）
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    # ---- 对外唯一入口 -------------------------------------------------
    def complete(self, messages: Sequence[Message], **kwargs: Any) -> LLMResponse:
        start = time.perf_counter()
        try:
            resp = self._complete(list(messages), **kwargs)
        except LLMError:
            raise
        except Exception as exc:  # 统一包装，便于上层按类型重试
            raise LLMError(f"{self.name} 调用失败: {exc}") from exc
        resp.latency_ms = (time.perf_counter() - start) * 1000
        resp.model = resp.model or self.model
        self._record(resp)
        return resp

    # ---- 子类实现 -----------------------------------------------------
    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        raise NotImplementedError

    # ---- 统计 ---------------------------------------------------------
    def _record(self, resp: LLMResponse) -> None:
        self.total_calls += 1
        self.total_prompt_tokens += resp.prompt_tokens
        self.total_completion_tokens += resp.completion_tokens

    def stats(self) -> dict[str, int]:
        return {
            "calls": self.total_calls,
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
        }


def estimate_tokens(text: str) -> int:
    """极简 token 估算：中文按 1 字 ≈ 1 token，英文按 4 字符 ≈ 1 token。

    真实分词器（tiktoken 等）我们后面阶段再引入；这里够用来观察趋势。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other = len(text) - cjk
    return cjk + max(1, other // 4)
