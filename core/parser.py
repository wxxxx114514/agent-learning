"""从模型自由文本中解析「思考 + 工具调用」。

真实的大模型有两种输出工具调用的方式：
  A. 原生 Function Calling：API 返回结构化的 tool_calls 字段（可靠性高，厂商相关）
  B. 纯文本协议：让模型按 ReAct 格式输出 Thought/Action，我们自己解析
     （可靠性低，但通用、可解释、可调试——早期 Agent 全是这么做的）

本模块负责 B 路线，同时兼容 A 路线的思路。
关键工程思想：**解析失败不要崩，要把失败原因变成可读的反馈**。
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .errors import ParseError
from .message import ToolCall

# ---------------------------------------------------------------------------
# 一、正则：从文本中挖出"像工具调用"的片段
# ---------------------------------------------------------------------------

# 1) <tool_call>{"name": ..., "args": {...}}</tool_call>
RE_TAG = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S | re.I)
# 2) ```json {"name": ...} ```
RE_FENCE = re.compile(r"```(?:json|tool_call|python)?\s*(\{.*?\})\s*```", re.S | re.I)
# 3) Action: calc(expr="1+1")   /  Action: calc{"expr": "1+1"}
RE_ACTION = re.compile(r"Action\s*[:：]\s*([A-Za-z_][\w.]*)\s*[\(\{](.*?)[\)\}]\s*(?:\n|$)", re.S | re.I)
# 4) JSON 对象（兜底，从第一个 { 到最后一个 }）
RE_JSONISH = re.compile(r"\{.*\}", re.S)

# ReAct 风格的分段标记
RE_THOUGHT = re.compile(r"Thought\s*[:：]\s*(.*?)(?=\n\s*(?:Action|Final Answer|思考|行动|最终答案)\s*[:：]|\Z)", re.S | re.I)
RE_FINAL = re.compile(r"(?:Final Answer|最终答案|最终回答)\s*[:：]\s*(.*)\Z", re.S | re.I)
RE_ANSWER_TAG = re.compile(r"<answer>(.*?)</answer>", re.S | re.I)

# 参数名 -> 值 的松散解析（用于 Action: calc(expr="1+1") 这种）
RE_KV = re.compile(r"([A-Za-z_][\w]*)\s*[=:]\s*(?:\"([^\"]*)\"|'([^']*)'|([^,，\)）\s]+))")


@dataclass
class ParsedOutput:
    """一次模型输出的解析结果。

    thought / answer / tool_calls 三者可以并存：
    模型可能"边想边调工具"，也可能直接给最终答案。
    """

    thought: str = ""
    answer: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def has_tool_call(self) -> bool:
        return bool(self.tool_calls)

    @property
    def is_final(self) -> bool:
        """是否可以直接结束：有答案且没有待执行的工具调用。"""
        return bool(self.answer.strip()) and not self.tool_calls

    def __str__(self) -> str:
        parts = []
        if self.thought:
            parts.append(f"Thought: {self.thought}")
        for c in self.tool_calls:
            parts.append(f"Action: {c.signature()}")
        if self.answer:
            parts.append(f"Answer: {self.answer}")
        if self.errors:
            parts.append(f"ParseErrors: {self.errors}")
        return "\n".join(parts) or "(空)"


# ---------------------------------------------------------------------------
# 二、宽松 JSON 解析：模型很爱输出"不完全合法"的 JSON
# ---------------------------------------------------------------------------

def _loose_json(text: str) -> Any:
    """尽最大努力把一段文本解析成 Python 对象。

    依次尝试：标准 JSON → Python 字面量(ast) → 单引号修正 → 去尾逗号。
    失败抛 ParseError。
    """
    text = text.strip()
    if not text:
        raise ParseError("空内容")

    try:
        return json.loads(text)
    except Exception:
        pass

    # 处理 {"a": 1,} 这类尾逗号，以及单引号
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    fixed = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', fixed)  # key
    fixed = re.sub(r":\s*'([^']*)'", r': "\1"', fixed)     # value
    try:
        return json.loads(fixed)
    except Exception:
        pass

    try:
        return ast.literal_eval(text)
    except Exception as exc:
        raise ParseError(f"不是合法 JSON/Python 字面量: {text[:120]!r} ({exc})") from exc


def _kv_fallback(body: str) -> dict[str, Any]:
    """Action: calc(expr="1+1", note='x') —— 从参数串里抠出键值对。"""
    args: dict[str, Any] = {}
    for m in RE_KV.finditer(body):
        key = m.group(1)
        value = m.group(2) or m.group(3) or m.group(4) or ""
        args[key] = _coerce(value)
    # 只有一个裸位置参数：Action: read_file(notes.md)
    if not args:
        bare = body.strip().strip("'\"")
        if bare:
            args["input"] = bare
    return args


def _coerce(value: str) -> Any:
    """把字符串形式的标量转成合适的 Python 类型（"3" -> 3, "true" -> True）。"""
    v = value.strip()
    low = v.lower()
    if low in {"true", "false"}:
        return low == "true"
    if low in {"null", "none"}:
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _normalize_call(obj: Any) -> ToolCall:
    """把各种"长得像工具调用"的 dict 归一化成 ToolCall。

    兼容这些常见形态：
      {"name": "calc", "args": {...}}
      {"tool": "calc", "arguments": {...}}
      {"action": "calc", "action_input": {...}}
      {"function": {"name": "calc", "arguments": "{\"expr\":\"1+1\"}"}}   # OpenAI 原生格式
      {"calc": {"expr": "1+1"}}                                          # 简写
    """
    if not isinstance(obj, dict):
        raise ParseError(f"工具调用必须是 JSON 对象，收到 {type(obj).__name__}")

    # OpenAI 原生形态
    if isinstance(obj.get("function"), dict):
        fn = obj["function"]
        args = fn.get("arguments", {})
        if isinstance(args, str):
            args = _loose_json(args) if args.strip() else {}
        return ToolCall(name=str(fn.get("name", "")), args=dict(args or {}), id=str(obj.get("id", "")))

    for name_key in ("name", "tool", "tool_name", "action", "function_name"):
        if name_key in obj:
            name = obj[name_key]
            for args_key in ("args", "arguments", "parameters", "params", "action_input", "input"):
                if args_key in obj:
                    args = obj[args_key]
                    if isinstance(args, str):
                        try:
                            args = _loose_json(args)
                        except ParseError:
                            args = {"input": args}
                    if not isinstance(args, dict):
                        args = {"input": args}
                    return ToolCall(name=str(name), args=dict(args))
            # 没有参数键：其余字段都当参数
            rest = {k: v for k, v in obj.items() if k != name_key and k != "id"}
            return ToolCall(name=str(name), args=rest, id=str(obj.get("id", "")))

    # 简写 {"calc": {...}}
    if len(obj) == 1:
        (k, v), = obj.items()
        if isinstance(v, dict):
            return ToolCall(name=str(k), args=dict(v))

    raise ParseError(f"无法识别的工具调用结构: {list(obj)[:6]}")


# ---------------------------------------------------------------------------
# 三、主解析函数
# ---------------------------------------------------------------------------

def parse_output(text: str, known_tools: list[str] | None = None) -> ParsedOutput:
    """把模型输出解析成 ParsedOutput。

    参数 known_tools：可选的"已知工具清单"。
        如果模型调用了不存在的工具（幻觉），我们**不在解析层拦**，
        而是留给 Agent 循环生成一条"工具不存在"的 observation。
        原因：让模型自己看到错误并纠正，比直接崩掉更符合 Agent 的哲学；
              同时解析层保持纯粹（只做语法，不做业务规则）。
    """
    out = ParsedOutput(raw=text or "")
    if not text or not text.strip():
        out.errors.append("模型返回空内容")
        return out

    # 1) 思考
    m = RE_THOUGHT.search(text)
    if m:
        out.thought = _clean(m.group(1))

    # 2) 最终答案：<answer> 优先，其次 Final Answer:
    m = RE_ANSWER_TAG.search(text)
    if m:
        out.answer = _clean(m.group(1))
    else:
        m = RE_FINAL.search(text)
        if m:
            out.answer = _clean(m.group(1))

    # 3) 工具调用：按可靠性从高到低尝试
    #
    #    这里的"分级"很关键。一个真实回复里往往**同时**出现多种形态：
    #        Thought: ...
    #        Action: calc(expr="1+1")
    #        <tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>
    #    如果无脑把所有形态都塞进 candidates，低优先级的那几种会重复解析出
    #    同一个调用（被 seen 去重掉，无害），但更糟的是：行内 JSON 片段
    #    `{"name": "calc", "args": {"expr": "1+1"}}` 这种**尾花括号**的截断
    #    形式会被当成候选，解析失败后往 errors 里塞一条**假错误**，
    #    误导读者以为模型输出有问题。
    #
    #    正确做法：每一级单独解析，**只要这一级有能解析成功的候选就整体采纳**，
    #    后面的级别不再参与（自然也就不会产生垃圾错误）。
    levels: list[list[str]] = [
        [m.group(1) for m in RE_TAG.finditer(text)],                 # 1. <tool_call> 标签
        [m.group(1) for m in RE_FENCE.finditer(text)],               # 2. ```json 代码块
        [f'{{"name": "{m.group(1)}", "args": {{{m.group(2)}}}}}'     # 3. Action: name(...)
         for m in RE_ACTION.finditer(text)],
    ]
    # 4. 整段兜底：第一个像 JSON 的片段
    m_jsonish = RE_JSONISH.search(text)
    if m_jsonish:
        levels.append([m_jsonish.group(0)])

    seen: set[str] = set()
    for level in levels:
        parsed_any = False
        for cand in level:
            try:
                obj = _loose_json(cand)
                calls = [_normalize_call(o) for o in (obj if isinstance(obj, list) else [obj])]
            except Exception:
                continue   # 本级这一条不行，但同级其他候选可能行 —— 不急着报错
            parsed_any = True
            for c in calls:
                if c.name and c.signature() not in seen:
                    seen.add(c.signature())
                    out.tool_calls.append(c)
        if parsed_any:
            break   # 这一级已经拿到工具调用，无需降级到更粗糙的解析方式

    # 3.5) 兜底：Action: name(...) 走 KV 解析（完全不依赖 JSON）
    #      走到这里说明上面四级都没拿到调用 —— 通常意味着模型的 JSON 彻底崩了，
    #      但 `Action: calc(expr="1+1")` 这种写法本身还是可读的，能救就救。
    if not out.tool_calls:
        for m in RE_ACTION.finditer(text):
            name, body = m.group(1), m.group(2)
            out.tool_calls.append(ToolCall(name=name, args=_kv_fallback(body)))

    # 4) 关键判断：这段回复到底是"聊天内容"还是"坏掉的工具调用"？
    #
    #    这里有个非常容易踩的坑。如果无脑执行
    #        if not tool_calls and not answer: answer = 整段文本
    #    那么**格式崩坏的回复会被当成最终答案**：
    #        'Thought: 我要算一下\nAction: calc(expr="1+1"'   ← 括号没闭合
    #    会被当作 answer 返回，Agent 立刻停机并把这个残句当成答案交给用户。
    #    更糟的是 Agent 根本不知道出过错，第 03 章要讲的"解析失败回灌纠错"
    #    就永远不会触发 —— 这是静默错误，比崩溃危险得多。
    #
    #    所以：出现过协议关键词（Action:/Thought:/<tool_call>）却没能解析出调用，
    #    就判定为"协议违规"，**不**退化成答案，交给上层去回灌纠错。
    if not out.tool_calls and not out.answer:
        if _looks_like_broken_protocol(text):
            out.errors.append(
                "检测到 Action/tool_call 等工具调用标记，但无法解析出合法调用"
                "（常见原因：JSON 括号没闭合、缺引号、参数不是合法 JSON）"
            )
        else:
            out.answer = _clean(text)

    return out


# 协议关键词：一旦出现，就说明模型"试图"走工具调用协议
RE_PROTOCOL_HINT = re.compile(r"(Action\s*[:：]|Thought\s*[:：]|<tool_call>|Final\s*Answer)", re.I)
# JSON 关键词：没有协议标记，但出现了这些字段名，且 JSON 解析失败 → 也是写崩的调用
RE_JSON_CALL_HINT = re.compile(r'"(?:name|args|arguments|tool|parameters)"\s*:', re.I)


def _looks_like_broken_protocol(text: str) -> bool:
    """判断一段文本是否"试图调用工具但写崩了"。

    注意判据是**关键词**而不是结构：模型写崩的时候结构已经不可信了。

    两类都要抓：
      1. 有 ReAct 标记（Action:/Thought:/<tool_call>）但解析不出调用；
      2. 没有标记，但出现了 `"name":` / `"args":` 这类字段名 —— 说明模型想写
         JSON 工具调用，只是写坏了（例如 `{"expr": 1+1}` 里 1+1 没加引号）。
    第 2 类很容易漏：因为纯聊天回复里不会出现 `"args":` 这种字样。
    """
    if RE_PROTOCOL_HINT.search(text):
        return True
    return bool(RE_JSON_CALL_HINT.search(text))


def _clean(s: str) -> str:
    return s.strip().strip("`").strip()


def parse_tool_calls(text: str) -> list[ToolCall]:
    """便捷函数：只要工具调用。"""
    return parse_output(text).tool_calls
