"""Agent 主循环 —— 整个课程的心脏。

------------------------------------------------------------
一句话本质：
    Agent = 一个 while 循环 + 一个会调工具的模型 + 一个能记住历史的列表。
    循环的每一圈只做四件事：想（LLM）→ 做（Tool）→ 看（Observation）→ 记（History）。
------------------------------------------------------------

本模块把「循环」写成显式、可读、可插桩的代码，而不是藏进框架里。
你可以清楚地看到每一步：
    - 送给模型的上下文长什么样（SpyLLM 可以打印）
    - 模型输出了什么、被解析成了什么
    - 工具执行花了多久、成功还是失败
    - 什么条件下循环会停止（正常结束 / 步数上限 / 死循环 / 解析连续失败）
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import AgentError, LLMError, LoopDetected, MaxStepsExceeded
from .llm import LLM, LLMResponse, estimate_tokens
from .message import Conversation, Message, ToolCall
from .mock_llm import default_mock
from .parser import ParsedOutput, parse_output
from .prompts import PromptBuilder
from .tool import ToolRegistry, ToolResult, build_default_registry

# ===========================================================================
# 一、可观测性：每一步都留下痕迹
# ===========================================================================
# 为什么第一天就要做"轨迹（trace）"？
#   因为 Agent 出错时，你唯一能依赖的就是"它到底经历了什么"。
#   没有 trace 的 Agent 就是黑盒，调试等于猜谜。
#   这也是后面「阶段 10 评估与可观测性」的基础设施。


@dataclass
class StepRecord:
    """循环中一圈的完整记录。"""

    index: int
    thought: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    answer: str = ""
    parse_errors: list[str] = field(default_factory=list)
    llm_ms: float = 0.0
    tool_ms: float = 0.0
    tokens: int = 0
    note: str = ""      # 这一圈的特殊事件：重试、拦截、回灌……
    tool_note: str = ""  # 工具层的额外说明（审批拦截、慢调用告警）

    def summary(self) -> str:
        bits = [f"step {self.index}"]
        if self.thought:
            bits.append(f"thought={self.thought[:40]!r}")
        for c in self.tool_calls:
            bits.append(f"action={c.signature()[:60]}")
        for o in self.observations:
            bits.append(f"obs={o[:60]!r}")
        if self.answer:
            bits.append(f"answer={self.answer[:40]!r}")
        if self.parse_errors:
            bits.append(f"parse_errors={len(self.parse_errors)}")
        if self.note:
            bits.append(f"note={self.note}")
        return " | ".join(bits)


@dataclass
class AgentResult:
    """一次 run 的最终结果。"""

    answer: str
    steps: list[StepRecord]
    stop_reason: str            # final_answer / max_steps / loop_detected / parse_failed / error
    error: str = ""
    elapsed_ms: float = 0.0
    llm_calls: int = 0
    total_tokens: int = 0

    @property
    def ok(self) -> bool:
        return self.stop_reason == "final_answer"

    def trace(self) -> str:
        """渲染成人类可读的推理轨迹（写日志、做 UI 都用它）。"""
        lines = ["=" * 62, "Agent 推理轨迹", "=" * 62]
        for s in self.steps:
            lines.append(f"\n[第 {s.index} 步]  (llm {s.llm_ms:.0f}ms / tool {s.tool_ms:.0f}ms / {s.tokens} tok)")
            if s.thought:
                lines.append(f"  💭 Thought: {s.thought}")
            for c in s.tool_calls:
                lines.append(f"  🔧 Action : {c.signature()}")
            for o in s.observations:
                first = o.splitlines()
                lines.append(f"  👁  Obs    : {first[0][:100]}" + (f"  …(+{len(first)-1} 行)" if len(first) > 1 else ""))
            if s.parse_errors:
                lines.append(f"  ⚠️  Parse  : {s.parse_errors}")
            if s.note:
                lines.append(f"  ℹ️  Note   : {s.note}")
            if s.answer:
                lines.append(f"  ✅ Answer : {s.answer}")
        lines.append("\n" + "-" * 62)
        lines.append(f"停止原因: {self.stop_reason} | 步数: {len(self.steps)} | LLM 调用: {self.llm_calls} "
                     f"| tokens: {self.total_tokens} | 耗时: {self.elapsed_ms:.0f}ms")
        return "\n".join(lines)


# ===========================================================================
# 二、Agent 本体
# ===========================================================================
Observer = Callable[[str, dict[str, Any]], None]


class Agent:
    """最小但完整的 ReAct Agent。

    关键设计取舍（每一条都是血泪经验）：
      1. **工具执行永不抛异常**：错误变成 observation 回灌给模型，让模型自己救场。
      2. **max_steps 是必须的**：没有它，一个 bug 就能让你烧掉一整天的 API 额度。
      3. **重复动作检测**：模型陷入"复读"时主动打断，并给出提示。
      4. **解析失败有预算**：连续解析失败 N 次就停机，而不是无限回灌。
      5. **重试只针对 LLMError**：网络问题可重试；逻辑问题重试没用。
    """

    def __init__(
        self,
        llm: LLM | None = None,
        tools: ToolRegistry | None = None,
        prompt: PromptBuilder | None = None,
        max_steps: int = 8,
        max_parse_retries: int = 2,
        max_llm_retries: int = 2,
        repeat_limit: int = 2,
        verbose: bool = True,
        observer: Observer | None = None,
        approval_hook: Callable[[ToolCall], bool] | None = None,
        workspace: str = ".",
        context_char_limit: int = 24000,
    ) -> None:
        self.llm: LLM = llm or default_mock()
        self.tools: ToolRegistry = tools if tools is not None else build_default_registry(workspace)
        self.prompt: PromptBuilder = prompt or PromptBuilder(style="react")
        self.max_steps = max_steps
        self.max_parse_retries = max_parse_retries
        self.max_llm_retries = max_llm_retries
        self.repeat_limit = repeat_limit
        self.verbose = verbose
        self.observer = observer
        self.approval_hook = approval_hook
        self.context_char_limit = context_char_limit

        self.system_prompt = ""
        self.conversation = Conversation()
        self._call_history: list[str] = []      # 历史工具调用指纹（用于死循环检测）

    # ---- 对外主入口 ---------------------------------------------------
    def run(self, user_input: str, reset: bool = True) -> AgentResult:
        """跑一轮完整对话，返回 AgentResult。"""
        t0 = time.perf_counter()
        if reset:
            self.conversation = Conversation()
            self._call_history = []

        # ① 组装系统提示词：每次 run 都重新构建（工具/上下文可能变了）
        self.system_prompt = self.prompt.build_system(self.tools)
        if not self.conversation.messages:
            self.conversation.add(Message.system(self.system_prompt))
        self.conversation.add(Message.user(user_input))
        self._emit("user_input", {"text": user_input, "system_chars": len(self.system_prompt)})

        steps: list[StepRecord] = []
        stop_reason = "max_steps"
        error = ""
        parse_fail_streak = 0

        try:
            for i in range(1, self.max_steps + 1):
                step = StepRecord(index=i)
                steps.append(step)
                self._emit("step_start", {"index": i, "messages": len(self.conversation)})

                # ② 想：调用模型（带重试）
                resp, note = self._call_llm_with_retry(step)
                if resp is None:
                    stop_reason, error = "error", note
                    step.note = note
                    break
                if note:
                    step.note = note
                step.llm_ms = resp.latency_ms
                step.tokens = resp.total_tokens or estimate_tokens(resp.text)
                self._emit("llm_output", {"index": i, "text": resp.text, "tokens": step.tokens})

                # ③ 解析：文本 → 结构化动作
                parsed = parse_output(resp.text, known_tools=self.tools.names())
                step.thought = parsed.thought or _first_line(resp.text)
                step.parse_errors = list(parsed.errors)
                self._emit("parsed", {"index": i, "summary": str(parsed)})

                # ④ 这是最终答案吗？
                if parsed.is_final or (self.prompt.style == "plain" and not parsed.has_tool_call):
                    step.answer = parsed.answer.strip()
                    self.conversation.add(Message.assistant(resp.text))
                    stop_reason = "final_answer"
                    self._emit("final_answer", {"index": i, "text": step.answer})
                    break

                # ⑤ 解析失败（既没有答案也没有动作）→ 纠错回灌
                if not parsed.has_tool_call:
                    parse_fail_streak += 1
                    step.note = (step.note + "; " if step.note else "") + "输出无法解析，已回灌纠错提示"
                    self.conversation.add(Message.assistant(resp.text))
                    self.conversation.add(Message.user(
                        self.prompt.parse_error_feedback("; ".join(parsed.errors) or "没有找到 Action 或 Final Answer")
                    ))
                    self._emit("parse_error", {"index": i, "errors": parsed.errors})
                    if parse_fail_streak > self.max_parse_retries:
                        stop_reason = "parse_failed"
                        error = f"连续 {parse_fail_streak} 次无法解析模型输出"
                        break
                    continue
                parse_fail_streak = 0

                # ⑥ 做：执行工具（可能多个；每个都带安全检查）
                step.tool_calls = parsed.tool_calls
                self.conversation.add(Message.assistant(parsed.thought or "", parsed.tool_calls))
                tool_ms = 0.0
                for call in parsed.tool_calls:
                    result, blocked_note = self._run_one_tool(call)
                    tool_ms += result.elapsed_ms
                    obs = result.to_observation()
                    step.observations.append(obs)
                    step.tool_note = blocked_note
                    if blocked_note:
                        step.note = (step.note + "; " if step.note else "") + blocked_note
                    self.conversation.add(Message.tool_result(
                        call.name, obs, call.id, ok=result.ok,
                        elapsed_ms=round(result.elapsed_ms, 1),
                    ))
                    self._emit("tool_result", {
                        "index": i, "tool": call.name, "ok": result.ok,
                        "elapsed_ms": result.elapsed_ms, "content": result.content, "error": result.error,
                    })
                step.tool_ms = tool_ms

                # ⑦ 死循环检测：同样的动作重复太多次 → 打断
                sig = parsed.tool_calls[0].signature()
                self._call_history.append(sig)
                if self._call_history.count(sig) > self.repeat_limit:
                    msg = (f"检测到重复动作 {sig} 已出现 {self._call_history.count(sig)} 次。"
                           f"请停止重复调用，改用其他方法或直接给出 Final Answer。")
                    self.conversation.add(Message.user(msg))
                    step.note = (step.note + "; " if step.note else "") + "触发重复动作提醒"
                    self._emit("loop_warning", {"index": i, "signature": sig})
                    if self._call_history.count(sig) > self.repeat_limit + 1:
                        raise LoopDetected(f"动作 {sig} 重复 {self._call_history.count(sig)} 次，已停机")

                # ⑧ 上下文保护（阶段 05 会做真正的记忆压缩，这里先做硬保护）
                self._guard_context()

        except LoopDetected as exc:
            stop_reason, error = "loop_detected", str(exc)
        except MaxStepsExceeded as exc:
            stop_reason, error = "max_steps", str(exc)
        except AgentError as exc:
            stop_reason, error = "error", str(exc)
        except Exception as exc:  # 任何意外都不应该让宿主进程崩掉
            stop_reason, error = "error", f"{type(exc).__name__}: {exc}"

        elapsed = (time.perf_counter() - t0) * 1000
        answer = steps[-1].answer if steps and steps[-1].answer else ""
        result = AgentResult(
            answer=answer, steps=steps, stop_reason=stop_reason, error=error,
            elapsed_ms=elapsed, llm_calls=self.llm.total_calls,
            total_tokens=self.llm.total_prompt_tokens + self.llm.total_completion_tokens,
        )
        self._emit("run_end", {"stop_reason": stop_reason, "answer": answer, "steps": len(steps)})
        return result

    # ---- 内部：模型调用与重试 -----------------------------------------
    def _call_llm_with_retry(self, step: StepRecord) -> tuple[LLMResponse | None, str]:
        note = ""
        # ★ 原生 function calling 的工具规格必须走 API 的 `tools` 参数下发，
        #   而不是塞进提示词 —— 这是"原生"和"文本协议"的根本区别。
        #   只有 style="function_calling" 时才带：文本协议下带了会干扰服务商，
        #   也可能让不支持 tools 的兼容端点直接报错。
        extra: dict[str, Any] = {}
        if getattr(self.prompt, "style", "") == "function_calling":
            extra = {"tools": self.tools.openai_tools(), "tool_choice": "auto"}
        for attempt in range(1, self.max_llm_retries + 2):
            try:
                resp = self.llm.complete(self.conversation.messages, **extra)
                if attempt > 1:
                    note = f"第 {attempt} 次尝试成功（前面失败 {attempt - 1} 次）"
                return resp, note
            except LLMError as exc:
                if attempt > self.max_llm_retries:
                    return None, f"LLM 连续失败 {attempt} 次: {exc}"
                wait = min(2 ** (attempt - 1) * 0.05, 0.5)   # 教学里缩短等待；生产用指数退避+抖动
                note = f"LLM 调用失败，{wait*1000:.0f}ms 后重试: {exc}"
                self._emit("llm_retry", {"attempt": attempt, "error": str(exc)})
                time.sleep(wait)
        return None, note

    # ---- 内部：单个工具的安全执行 -------------------------------------
    def _run_one_tool(self, call: ToolCall) -> tuple[ToolResult, str]:
        """返回 (结果, 额外说明)。包含：审批、参数预演、执行、慢工具告警。"""
        note = ""
        spec = None
        try:
            spec = self.tools.get(call.name)
        except Exception:
            pass

        # 高危工具的人工审批（human-in-the-loop）
        if spec is not None and spec.requires_approval and self.approval_hook is not None:
            approved = False
            try:
                approved = bool(self.approval_hook(call))
            except Exception as exc:
                note = f"审批钩子异常，默认拒绝: {exc}"
            if not approved:
                return ToolResult(name=call.name, ok=False, content="",
                                  error="该操作需要人工审批，已被拒绝。请不要重试，改向用户说明情况。"), \
                       (note or f"工具 {call.name} 需要审批，被拒绝")

        result = self.tools.execute(call.name, call.args)
        if result.elapsed_ms > 1000:
            note = f"工具 {call.name} 耗时 {result.elapsed_ms:.0f}ms（偏慢，注意用户体验）"
        return result, note

    # ---- 内部：上下文硬保护 -------------------------------------------
    def _guard_context(self) -> None:
        """粗暴但有效的上下文保护：超限就折叠最老的工具结果。

        真正的做法（阶段 05）：摘要压缩、按重要性淘汰、外部记忆。
        """
        if self.conversation.total_chars() <= self.context_char_limit:
            return
        folded = 0
        for m in self.conversation.messages:
            if m.role == "tool" and len(m.content) > 200:
                m.metadata["original_chars"] = len(m.content)
                m.content = m.content[:120] + "\n…（历史观测已折叠以节省上下文）"
                folded += 1
            if self.conversation.total_chars() <= self.context_char_limit * 0.7:
                break
        if folded:
            self._emit("context_fold", {"folded": folded, "chars": self.conversation.total_chars()})

    # ---- 事件回调 -----------------------------------------------------
    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.observer:
            try:
                self.observer(event, payload)
            except Exception:
                pass
        if self.verbose:
            print(f"  · [{event}] {_brief(payload)}")


def _brief(payload: dict[str, Any], n: int = 90) -> str:
    parts = []
    for k, v in payload.items():
        s = str(v).replace("\n", " ")
        parts.append(f"{k}={s[:n]}")
    return " ".join(parts)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return ""


# ===========================================================================
# 三、便捷函数：三行代码跑一个 Agent
# ===========================================================================
def quick_agent(
    tools: ToolRegistry | None = None,
    llm: LLM | None = None,
    max_steps: int = 6,
    verbose: bool = True,
) -> Agent:
    return Agent(llm=llm, tools=tools, max_steps=max_steps, verbose=verbose)


def run_once(question: str, llm: LLM | None = None, tools: ToolRegistry | None = None,
             verbose: bool = True) -> AgentResult:
    agent = quick_agent(tools=tools, llm=llm, verbose=verbose)
    return agent.run(question)
