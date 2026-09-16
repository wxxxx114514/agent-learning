"""离线 Mock 模型：让 Agent 学习**不依赖网络、不花钱、结果可复现**。

这是本课程最重要的工程决策之一：
    把"不确定的大模型"替换成"确定性的假模型"，我们就能单独调试 Agent 的逻辑。
    真实项目里也一样 —— 单元测试绝对不应该调用真模型（慢、贵、不稳定）。

本文件提供 6 个假模型，每个都模拟一类真实世界的问题：

    ScriptedLLM      按剧本背台词            → 学习循环结构
    RuleBasedLLM     规则驱动的"看起来像真的" → 学习 ReAct / 多步工具
    FlakyLLM         随机抽风                → 学习重试
    MalformedLLM     输出格式错误            → 学习鲁棒解析
    HallucinatingLLM 调用不存在的工具        → 学习错误回灌
    LoopingLLM       永远重复同一个动作      → 学习死循环检测
    SpyLLM           记录收到的提示词        → 学习提示词工程（看上下文怎么变化）
"""

from __future__ import annotations

import random
import re
from typing import Any, Callable, Sequence

from .errors import LLMError
from .llm import LLM, LLMResponse, estimate_tokens
from .message import Message
from .parser import parse_output


def as_mock_response(text: str, model: str = "mock") -> LLMResponse:
    """把纯文本包装成 LLMResponse，并估算 token。"""
    return LLMResponse(
        text=text,
        model=model,
        prompt_tokens=0,
        completion_tokens=estimate_tokens(text),
    )


# ---------------------------------------------------------------------------
# 1. 剧本模型：最纯粹的"确定性"
# ---------------------------------------------------------------------------
class ScriptedLLM(LLM):
    """按给定剧本逐条返回。

    用途：测试 Agent 循环的每一个分支（正常结束 / 工具调用 / 解析失败）。
    剧本用完后：默认重复最后一条（方便观察循环保护），也可以抛错。
    """

    name = "scripted"

    def __init__(self, script: Sequence[str], repeat_last: bool = True, model: str = "mock-scripted"):
        super().__init__(model)
        self.script = list(script)
        self.repeat_last = repeat_last
        self.calls: list[list[Message]] = []   # 记录每次收到的上下文，便于断言

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        self.calls.append(list(messages))
        idx = self.total_calls  # 本次调用是第几次（0-based）
        if idx < len(self.script):
            text = self.script[idx]
        elif self.repeat_last and self.script:
            text = self.script[-1]
        else:
            raise LLMError("剧本已用完")
        prompt = sum(estimate_tokens(m.to_text()) for m in messages)
        resp = as_mock_response(text, self.model)
        resp.prompt_tokens = prompt
        return resp


# ---------------------------------------------------------------------------
# 2. 规则模型：模拟"一个听话的模型"，能完成多步工具调用
# ---------------------------------------------------------------------------
# 意图规则：(正则, 要调用的工具, 从正则分组构造参数)
TOOL_RULES: list[tuple[str, str, Callable[[re.Match], dict[str, Any]]]] = [
    # 算术：3+4*2 / 计算 12*(3+4)
    (r"(?:计算|算一下|算算|calculate|calc)\s*[:：]?\s*([0-9\.\+\-\*/\(\)\s%]+)", "calc",
     lambda m: {"expr": m.group(1).strip()}),
    (r"^\s*([0-9\.]+(?:\s*[\+\-\*/]\s*[0-9\.]+)+)\s*[=？?]?\s*$", "calc",
     lambda m: {"expr": m.group(1).strip()}),
    # 订单查询：订单 A1001 到哪了 / 查一下 A1001
    (r"(?:订单|order)\s*[:：#]?\s*([A-Za-z]{0,2}\d{3,})", "lookup_order",
     lambda m: {"order_id": m.group(1).upper()}),
    (r"(?:进度|状态|到哪|查询|查一下|status)\D{0,6}?([A-Za-z]{1,2}\d{3,})", "lookup_order",
     lambda m: {"order_id": m.group(1).upper()}),
    # 字数统计：统计 xxx 的字数 / 数一数"xxx"有几个字
    (r"(?:统计|数一数|数数|count)\s*[\"“']?([^\"”'\n]+?)[\"”']?\s*(?:的)?\s*(?:字数|多少字|words?)", "count_words",
     lambda m: {"text": m.group(1).strip()}),
    # 读文件：读一下 notes.md / 打开 notes.md
    (r"(?:读|看|打开|read|cat|open)\s*(?:一下|取)?\s*[\"“']?([\w\-./\\]+\.\w+)[\"”']?", "read_file",
     lambda m: {"path": m.group(1).replace("\\", "/")}),
]

# 需要"两步都调工具"的意图：值 = 第一次工具的参数（由调用方填充）
MULTI_STEP_HINTS = ("然后", "再", "并且", "并", "之后", "接着")


class RuleBasedLLM(LLM):
    """规则驱动的假模型：看懂用户想干什么，然后**像真模型一样**发起工具调用。

    工作方式（模仿 ReAct 的两拍）：
      第 1 拍：还没看到工具结果 → 输出 Thought + Action（工具调用）
      第 2 拍：看到了工具结果   → 输出 Thought + Final Answer（把结果讲成人话）

    这足够撑起前 3 个阶段的所有教学实验。
    """

    name = "rule-based"

    def __init__(self, profile: str = "generic", model: str = "mock-rule"):
        super().__init__(model)
        self.profile = profile
        self.seen_actions: set[str] = set()

    # -- 主逻辑 ---------------------------------------------------------
    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        idx = self.total_calls
        user_msg = self._last_user(messages)
        tool_msgs = self._tool_results_after_last_user(messages)

        if tool_msgs:
            text = self._after_tools(user_msg, tool_msgs, idx)
        else:
            text = self._before_tools(user_msg, idx)

        resp = as_mock_response(text, self.model)
        resp.prompt_tokens = sum(estimate_tokens(m.to_text()) for m in messages)
        return resp

    # -- 第一拍：决定调用哪个工具 ---------------------------------------
    def _before_tools(self, user_msg: str, idx: int) -> str:
        if not user_msg:
            return "Thought: 用户没有提供有效输入。\n\nFinal Answer: 请告诉我你想做什么？"

        plan = self.plan(user_msg)
        if not plan:
            return f"Thought: 这是一个不需要工具的普通问题。\n\nFinal Answer: 关于「{user_msg[:30]}」，我的直接回答是：{user_msg[:30]}。"

        # 每拍只做一个动作（真实 ReAct 也是这样，一次一步）
        name, args = plan[0]
        return (
            f"Thought: 我需要用 {name} 工具来获取信息，参数已经准备好。\n"
            f"Action: {name}({_fmt_args(args)})\n"
            f'<tool_call>{{"name": "{name}", "args": {_json_args(args)}}}</tool_call>'
        )

    def plan(self, user_msg: str) -> list[tuple[str, dict[str, Any]]]:
        """把用户输入映射成工具调用计划（可被外部覆写/断言，便于教学）。"""
        text = user_msg.strip()
        plans: list[tuple[str, dict[str, Any]]] = []
        for pattern, tool, build in TOOL_RULES:
            m = re.search(pattern, text, re.I | re.S)
            if m:
                try:
                    args = build(m)
                except (IndexError, AttributeError):
                    continue
                if args:
                    plans.append((tool, args))
                    break
        return plans

    # -- 第二拍：把工具结果讲成人话 -------------------------------------
    def _after_tools(self, user_msg: str, tool_msgs: list[Message], idx: int) -> str:
        last = tool_msgs[-1]
        ok = bool(last.metadata.get("ok", True))
        if self.profile == "rule-fail-once" and not ok and idx <= 3:
            # 模拟"模型看到错误但第一次没改对"，用于演示反思
            return "Thought: 上一步失败了。\n\nFinal Answer: 抱歉，我没能取到数据。"

        if not ok:
            return (
                f"Thought: 工具 {last.name} 执行失败，我应该如实告诉用户原因。\n\n"
                f"Final Answer: 调用 {last.name} 时出错：{last.content[:200]}"
            )

        # 已经完成的动作不再重复
        self.seen_actions.add(last.name)
        body = _strip_wrappers(last.content)

        # 多步意图：若用户说"并/然后 统计字数"，继续调用下一个工具
        if any(h in user_msg for h in MULTI_STEP_HINTS):
            rest = self.plan(user_msg.replace("然后", " ").replace("再", " "))
            for name, args in rest:
                if name not in self.seen_actions and name != last.name:
                    return (
                        f"Thought: 第 1 步完成了，继续执行第 2 步：{name}。\n"
                        f'Action: {name}({_fmt_args(args)})\n'
                        f'<tool_call>{{"name": "{name}", "args": {_json_args(args)}}}</tool_call>'
                    )

        return (
            f"Thought: {last.name} 返回了结果，我可以据此回答了。\n\n"
            f"Final Answer: 根据 {last.name} 的结果：{body}"
        )

    # -- 工具函数 -------------------------------------------------------
    @staticmethod
    def _last_user(messages: list[Message]) -> str:
        for m in reversed(messages):
            if m.role == "user":
                return m.content
        return ""

    @staticmethod
    def _tool_results_after_last_user(messages: list[Message]) -> list[Message]:
        out: list[Message] = []
        for m in reversed(messages):
            if m.role == "user":
                break
            if m.role == "tool":
                out.append(m)
        return list(reversed(out))


def _fmt_args(args: dict[str, Any]) -> str:
    return ", ".join(f'{k}="{v}"' if isinstance(v, str) else f"{k}={v}" for k, v in args.items())


def _json_args(args: dict[str, Any]) -> str:
    import json

    return json.dumps(args, ensure_ascii=False)


def _strip_wrappers(content: str) -> str:
    """去掉工具返回里的 <result ...> 包裹和多余空白，让句子更自然。

    注意正则要吃掉**带属性**的开标签（`<result tool="calc">`）：
    只匹配 `</?result>` 会残留 ` tool="calc">` 这种碎片，
    最终答案里就会出现脏字符 —— 这是很容易被忽视的一类解析 bug。
    """
    text = re.sub(r"</?result\b[^>]*>", "", content, flags=re.I).strip()
    text = re.sub(r"\s*\n\s*", "；", text)
    return text[:400]


# ---------------------------------------------------------------------------
# 3~6. "捣乱"模型：专门用来测试 Agent 的健壮性
# ---------------------------------------------------------------------------
class FlakyLLM(LLM):
    """模拟不稳定 API：前 `fail_times` 次调用抛错，之后正常。

    ★ 这里有一个容易写错的细节：
        `self.total_calls` 是在 LLM.complete() **成功返回后**才自增的
        （见 core/llm.py 的 _record），所以它统计的是"成功调用次数"。
        如果直接用 total_calls 当失败计数器，那么每次失败后计数都不变，
        模型会**永远**停在"第 1 次调用失败"——永远恢复不了，
        重试逻辑的演示就成了假的。

        正确做法：用独立的 `_attempts` 统计"尝试次数"，它每次都自增。
        （`total_calls` 保持"成功次数"的语义，便于成本统计 —— 失败的调用不计费。）
    """

    name = "flaky"

    def __init__(self, fail_times: int = 2, then: str = "Final Answer: 重试成功了", model: str = "mock-flaky"):
        super().__init__(model)
        self.fail_times = fail_times
        self.then = then
        self._attempts = 0

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        attempt = self._attempts
        self._attempts += 1
        if attempt < self.fail_times:
            raise LLMError(f"模拟网络抖动 (第 {attempt + 1} 次调用)")
        return as_mock_response(self.then, self.model)


class MalformedLLM(LLM):
    """模拟格式崩坏的输出（没闭合的 JSON、错别字、半截话）。

    用来验证：解析器是否鲁棒？Agent 会不会把错误回灌给模型要求重写？
    """

    name = "malformed"

    def __init__(self, bad_outputs: Sequence[str] | None = None, good_output: str | None = None,
                 model: str = "mock-malformed"):
        super().__init__(model)
        self.bad_outputs = list(bad_outputs or [
            'Thought: 我要算一下\nAction: calc(expr="1+1"',
            '{"name": "calc", "args": {"expr": 1+1}}   <-- 非法 JSON',
            'Thought: 嗯……\nAction: calc{expr: 1+1}',
        ])
        self.good_output = good_output or 'Final Answer: 1+1=2'

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        i = self.total_calls
        text = self.bad_outputs[i] if i < len(self.bad_outputs) else self.good_output
        return as_mock_response(text, self.model)


class HallucinatingLLM(LLM):
    """模拟"幻觉工具"：调一个根本不存在的工具，看 Agent 怎么纠正它。

    正确的做法：返回一条 observation「工具不存在，可用工具有 A/B/C」，
    模型（或将来的真实模型）据此改调正确工具。
    """

    name = "hallucinating"

    def __init__(self, phantom: str = "search_google",
                 then: str = 'Thought: 原来没有这个工具，我改用 calc。\n'
                             'Action: calc(expr="6*7")\n'
                             '<tool_call>{"name": "calc", "args": {"expr": "6*7"}}</tool_call>',
                 model: str = "mock-hallucinating"):
        super().__init__(model)
        self.phantom = phantom
        self.then = then

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        if self.total_calls == 0:
            text = f'Thought: 我需要搜索。\n<tool_call>{{"name": "{self.phantom}", "args": {{"q": "anything"}}}}</tool_call>'
        elif self.total_calls == 1:
            text = self.then
        else:
            tool_msgs = [m for m in messages if m.role == "tool"]
            last = _strip_wrappers(tool_msgs[-1].content) if tool_msgs else "(无结果)"
            text = f"Thought: 我拿到了结果。\n\nFinal Answer: 答案是 {last}"
        return as_mock_response(text, self.model)


class LoopingLLM(LLM):
    """永远请求同一个工具调用，用来验证 max_steps 与死循环检测。"""

    name = "looping"

    def __init__(self, action: str = "count_words", args: dict[str, Any] | None = None,
                 model: str = "mock-looping"):
        super().__init__(model)
        self.action = action
        self.args = args or {"text": "循环测试"}

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        import json

        text = (
            "Thought: 我再确认一次。\n"
            f'<tool_call>{{"name": "{self.action}", "args": {json.dumps(self.args, ensure_ascii=False)}}}</tool_call>'
        )
        return as_mock_response(text, self.model)


class SpyLLM(LLM):
    """包装任意模型，记录它每次看到的完整提示词。

    学习提示词工程时，最有效的方法就是"把上下文打印出来看"。
    """

    name = "spy"

    def __init__(self, inner: LLM, model: str | None = None):
        super().__init__(model or f"spy({inner.model})")
        self.inner = inner
        self.seen: list[list[Message]] = []

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        self.seen.append(list(messages))
        resp = self.inner.complete(messages, **kwargs)
        self.total_calls = self.inner.total_calls
        self.total_prompt_tokens = self.inner.total_prompt_tokens
        self.total_completion_tokens = self.inner.total_completion_tokens
        return resp

    def last_prompt(self) -> str:
        if not self.seen:
            return "(还没调用过)"
        return "\n\n".join(m.to_text() for m in self.seen[-1])

    def diff_summary(self) -> str:
        """对比相邻两次提示词的长度变化，直观感受"上下文在膨胀"。"""
        if len(self.seen) < 2:
            return "至少调用两次才能对比"
        lines = []
        for i, msgs in enumerate(self.seen, 1):
            chars = sum(m.char_len() for m in msgs)
            lines.append(f"  第 {i} 次调用：{len(msgs)} 条消息 / {chars} 字符")
        return "\n".join(lines)


class HumanInLoopLLM(LLM):
    """模拟"人类兜底"：当模型无法决定时，暂停等待人类输入。

    真实系统里这对应 human-in-the-loop（审批、补充信息）。
    """

    name = "human-in-loop"

    def __init__(self, answers: dict[int, str] | None = None, model: str = "mock-hitl"):
        super().__init__(model)
        self.answers = answers or {}

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        answer = self.answers.get(self.total_calls, "Final Answer: 需要人工确认后继续。")
        return as_mock_response(answer, self.model)


def random_flaky(inner: LLM, fail_rate: float = 0.3, seed: int = 0) -> LLM:
    """给任意模型套一层"随机故障"，用于压测重试逻辑。"""
    rng = random.Random(seed)

    class _RandomFlaky(LLM):
        name = "random-flaky"

        def __init__(self) -> None:
            super().__init__(f"flaky({inner.model})")

        def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
            if rng.random() < fail_rate:
                raise LLMError("随机故障注入")
            resp = inner.complete(messages, **kwargs)
            self.total_calls = inner.total_calls
            return resp

    return _RandomFlaky()


def default_mock(profile: str = "generic") -> LLM:
    """教学的默认模型：规则驱动，能跑多步工具。"""
    return RuleBasedLLM(profile=profile)


__all__ = [
    "ScriptedLLM", "RuleBasedLLM", "FlakyLLM", "MalformedLLM",
    "HallucinatingLLM", "LoopingLLM", "SpyLLM", "HumanInLoopLLM",
    "default_mock", "random_flaky", "as_mock_response", "parse_output",
]
