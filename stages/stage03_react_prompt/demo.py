"""第 03 章 · ReAct 提示工程 —— 让模型"先想再做"，并且说得能被解析。

运行：
    py -m stages.stage03_react_prompt.demo
    py -m stages.stage03_react_prompt.demo -s 3

本章要回答两个问题：
    ① 为什么要"先想再做"（Thought 到底有什么用）？
    ② 提示词到底该怎么组织，才能让模型的输出**可以被程序解析**？

第 01 章我们发现了一个规律：**Agent 的能力上限，由"模型输出能否被可靠解析"决定。**
模型再聪明，如果它输出的格式你解析不了，整个循环就是空转。

本章的核心论点：
    提示词 = 身份与规则 + 工具说明书 + **输出格式契约** + 参考资料
    「输出格式契约」是 Agent 特有的、也是最重要的一块 —— 它不是写给用户看的，
    而是写给**解析器**看的。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check_that, code, essence, kv, note, ok, report,
    section, setup_console, warn,
)
from core.llm import LLM, LLMResponse  # noqa: E402
from core.message import Message  # noqa: E402
from core.mock_llm import ScriptedLLM, SpyLLM, default_mock  # noqa: E402
from core.parser import parse_output  # noqa: E402
from core.prompts import (  # noqa: E402
    FUNCTION_CALLING_SYSTEM, PLAIN_SYSTEM, PromptBuilder,
)
from core.tool import build_default_registry  # noqa: E402


# ===========================================================================
# 第 1 节：没有协议的世界 —— 模型很聪明，但程序读不懂它
# ===========================================================================
# 这两个假模型演示了同一件事的两面：
#   ChattyLLM    模型"能力"够（知道该算数、知道订单号），但不会按协议说话
#   CooperativeLLM 模型愿意按协议说话
# 区别不在模型，而在**我们有没有把格式契约写清楚**。


class ChattyLLM(LLM):
    """一个"很热情但不会按协议输出"的模型。

    它的输出像极了真实世界里没做过提示词工程的模型：
    把该说的话都说在自然语言里，程序一个字段都提取不到。
    """

    name = "chatty"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        user = _last_user(messages)
        expr = _pick_expression(user)
        if expr:
            value = _eval_simple(expr)
            text = (f"当然可以！我来帮你算一下。你给的表达式是 {expr}，"
                    f"按照先乘除后加减的顺序计算，结果是 {value}。")
        else:
            text = "你好！我是你的智能助手，有什么可以帮你的吗？"
        return LLMResponse(text=text, model=self.name)


class CooperativeLLM(LLM):
    """一个"愿意按协议输出"的模型 —— 但只有收到格式契约时才会这么做。

    它的行为逻辑很朴素（关键词匹配），因为我们考察的不是"智能"，
    而是**提示词能否决定输出格式**。把变量控制住，结论才可信。
    """

    name = "cooperative"

    def __init__(self, model: str = "cooperative") -> None:
        super().__init__(model)
        self.tools: list[str] = []

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        user = _last_user(messages)
        tool_msgs = [m for m in messages if m.role == "tool"]

        # 是否收到了"输出格式契约"？—— 这是本模型唯一的开关
        has_contract = ("Action:" in system and "<tool_call>" in system)
        if not has_contract:
            return LLMResponse(text=ChattyLLM()._complete(messages).text, model=self.name)

        if tool_msgs:
            body = _strip_tags(tool_msgs[-1].content)
            return LLMResponse(
                text=f"Thought: 工具 {tool_msgs[-1].name} 返回了结果，可以作答了。\n"
                     f"Final Answer: 计算结果是 {body}",
                model=self.name,
            )

        expr = _pick_expression(user)
        if expr:
            return LLMResponse(
                text="Thought: 这是一个算术问题，我应该用 calc 工具，而不是自己心算"
                     "（模型心算长表达式很容易出错）。\n"
                     f"Action: calc(expr=\"{expr}\")\n"
                     f'<tool_call>{{"name": "calc", "args": {{"expr": "{expr}"}}}}</tool_call>',
                model=self.name,
            )
        return LLMResponse(text="Thought: 无需工具。\nFinal Answer: 请告诉我你想算什么？",
                           model=self.name)


def _last_user(messages: list[Message]) -> str:
    for m in reversed(messages):
        if m.role == "user":
            return m.content
    return ""


def _strip_tags(content: str) -> str:
    text = re.sub(r"</?result\b[^>]*>", "", content, flags=re.I).strip()
    return re.sub(r"\s*\n\s*", "；", text)[:200]


_EXPR_CHARS = set("0123456789.+-*/() \t")
_OPEN, _CLOSE = "([{", ")]}"


def _pick_expression(text: str) -> str:
    """从用户提问里抠出一个算术表达式。

    ★ 为什么不能只写一个正则？
        因为括号是**成对**的，正则表达式不擅长配对。用 `[0-9.+-*/()]+` 这类
        字符类去匹配 "计算 (12+8)*3/4"，会在第一个 `)` 处就停下，得到 "(12+8"
        —— 一个括号不配对的残缺表达式（实测就会报 `SyntaxError: unmatched ')'`）。

    ★ 正确做法：手写一个小扫描器，做对两件事：
        1. **确定起点**：找到第一个数字后，还要**向前回溯**，把紧邻的未闭合左括号
           一起纳入。否则 "计算 (12+8)*3/4" 会从 `12` 开始，结果只剩 "12+8)*3/4"。
        2. **确定终点**：维护括号深度，只有深度归零时表达才算完整，
           这样 "(12+8)*3/4" 能整段取出，而不会被第一个 `)` 截断。
    """
    n = len(text)
    for start in range(n):
        if not text[start].isdigit():
            continue

        # --- ① 向前回溯：把紧邻的、尚未闭合的左括号纳入 ---
        i = start
        while i > 0 and text[i - 1] in _OPEN:
            i -= 1
            start = i

        # --- ② 向后扫描：维护括号深度直到归零 ---
        depth = 0
        end = start
        for j in range(start, n):
            ch = text[j]
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE:
                depth -= 1
                if depth < 0:
                    break
            elif ch not in _EXPR_CHARS:
                break
            end = j + 1
        expr = text[start:end].strip().rstrip("+-*/. ")

        # 必须含运算符，且括号配平，才算一个合法表达式
        # （避免把 "2025年"、"订单 A1001" 这种普通文本误当成算式）
        if any(op in expr for op in "+-*/") and _brackets_balanced(expr):
            return expr
    return ""


def _brackets_balanced(expr: str) -> bool:
    depth = 0
    for ch in expr:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _eval_simple(expr: str) -> str:
    """给 ChattyLLM 用的心算模拟（只处理最简单的四则）。

    注意这是**假模型假装心算**，故意做得又笨又脆：
    真实模型心算长表达式也会出错，而且你无法校验它的中间步骤。
    """
    try:
        import ast
        import operator

        ops = {ast.Add: operator.add, ast.Sub: operator.sub,
               ast.Mult: operator.mul, ast.Div: operator.truediv}

        def ev(n):
            if isinstance(n, ast.Expression):
                return ev(n.body)
            if isinstance(n, ast.Constant):
                return n.value
            if isinstance(n, ast.BinOp):
                return ops[type(n.op)](ev(n.left), ev(n.right))
            raise ValueError

        v = ev(ast.parse(expr, mode="eval"))
        return str(int(v) if float(v).is_integer() else v)
    except Exception:
        return "我算不出来"


def demo_no_protocol() -> None:
    section("没有格式契约：模型说得对，但程序读不懂", "①")

    registry = build_default_registry(ROOT)
    question = "计算 (12+8)*3/4"

    for label, llm in [("ChattyLLM（没收到格式契约）", ChattyLLM()),
                       ("CooperativeLLM（没收到格式契约）", CooperativeLLM())]:
        agent = _mini_agent(llm)
        result = agent.run(question)
        answer, steps, calls, reason = result
        print(f"\n  【{label}】")
        kv("模型原始输出", steps[0]["raw"][:78])
        kv("解析出的工具调用", f"{len(calls)} 个")
        kv("最终答案", (answer or "(无)")[:60])
        kv("停机原因", reason)

    print()
    warn("两个模型都知道该算数 —— 但第一个把话说在自然语言里，程序一个字段都提取不到。")
    note("ChattyLLM 甚至直接自己心算给出了答案（碰巧算对了）。")
    warn("危险的地方在这里：模型心算长表达式经常出错，而且**你无法校验**。")
    note("它没有调用 calc 工具，所以：算错了你不知道、算对了也没法复现。")
    print()
    essence(
        "Agent 的能力上限 = min(模型的智能, 你能可靠解析的输出格式)。\n"
        "格式契约不是「锦上添花」的提示词技巧，它是 Agent 能工作的**前提条件**。"
    )


# ===========================================================================
# 第 2 节：三段式提示词架构
# ===========================================================================


def demo_prompt_anatomy() -> None:
    section("提示词的三段式结构：每块都有明确的读者", "②")
    registry = build_default_registry(ROOT)

    builder = PromptBuilder(
        style="react",
        persona="你是「小助手」，一个严谨的电商客服助理，回答必须基于工具返回的真实数据。",
        rules=[
            "不要猜测订单状态，一律用 lookup_order 查询。",
            "涉及金额计算一律用 calc，禁止心算。",
            "回答要简洁，不要复述工具的原始输出格式。",
        ],
        extra_context="当前时间：2025-01-01 09:00（北京时间）",
    )
    system = builder.build_system(registry)

    print()
    note("这是真实的系统提示词（由 PromptBuilder 生成）：")
    print()
    _show_blocks(system)

    print()
    note("四块结构的读者与职责：")
    rows = [
        ("① 身份与规则", "模型（行为约束）", "我是谁、我遵守什么业务规则"),
        ("② 工具说明书", "模型（决策依据）", "我能用什么、参数是什么格式"),
        ("③ 输出格式契约", "**解析器**（可解析性）", "我必须怎么说话，程序才读得懂"),
        ("④ 参考资料", "模型（事实来源）", "RAG 片段、长期记忆、当前时间"),
    ]
    print(f"  {'块':<16}{'读者':<24}{'职责'}")
    print("  " + "-" * 76)
    for a, b, c in rows:
        print(f"  {a:<16}{b:<24}{c}")

    print()
    warn("新手最常犯的错：把四块揉成一大坨字符串。")
    note("后果：① 改一处影响全局，无法回归测试；② RAG 注入时无处安放；")
    note("      ③ 工具变了要手改提示词正文，容易漏改导致格式不一致。")
    print()
    note("三段式的好处是**每一块都能单独断言**（这就是第 10 章要做提示词回归测试的基础）：")
    code(
        'assert "Action:" in system            # 格式契约在\n'
        'assert "calc" in system               # 工具说明在\n'
        'assert "禁止心算" in system            # 业务规则在\n'
        'assert "2025-01-01" in system         # 动态上下文在',
        indent=4,
    )


def _show_blocks(system: str) -> None:
    """把系统提示词按 # 标题切块展示。"""
    parts = re.split(r"\n(?=# )", system)
    for i, part in enumerate(parts, 1):
        lines = part.splitlines()
        head = lines[0] if lines else f"(第 {i} 块)"
        print(f"  ┌─ {head}")
        for line in lines[1:14]:
            print(f"  │ {line}")
        if len(lines) > 15:
            print(f"  │ …（还有 {len(lines) - 14} 行）")
        print("  └" + "─" * 60)


# ===========================================================================
# 第 3 节：受控实验 —— 提示词质量 vs 可解析率
# ===========================================================================


def demo_experiment() -> None:
    section("受控实验：提示词质量直接决定可解析率", "③")
    note("固定问题：「计算 (12+8)*3/4」，只改变**提示词风格**与**模型性格**两个变量。")
    print()

    question = "计算 (12+8)*3/4"
    styles = [
        ("A. plain（无工具无格式契约）", PromptBuilder(style="plain")),
        ("B. react 契约 + 一条业务规则",
         PromptBuilder(style="react", rules=["需要计算时必须使用 calc 工具，禁止心算。"])),
        ("C. react 契约，无额外规则", PromptBuilder(style="react")),
    ]
    models = [("ChattyLLM", ChattyLLM), ("CooperativeLLM", CooperativeLLM)]

    print(f"  {'提示词配置':<36}{'模型':<18}{'解析出工具调用':<16}{'可解析'}")
    print("  " + "-" * 86)

    matrix: dict[tuple[str, str], bool] = {}
    for style_name, builder in styles:
        for model_name, factory in models:
            agent = _mini_agent(factory(), builder=builder)
            _, steps, calls, _ = agent.run(question)
            parsable = len(calls) > 0
            matrix[(style_name, model_name)] = parsable
            print(f"  {style_name:<36}{model_name:<18}{len(calls):<16}"
                  f"{'✅ 是' if parsable else '❌ 否'}")

    print()
    note("先说明一个容易误读的点：B 和 C 的差别只有那条业务规则，")
    note("而**两者都含格式契约**（因为 style='react' 会把 Action:/<tool_call> 写进系统提示词）。")
    note("所以 B 与 C 结果相同 —— 这恰好证明了本节的论点。")
    print()
    note("从这张表能读出三条结论：")
    for line in [
        "1. **没有格式契约 → 一定解析不出来**：A 行两种模型都是 0 个工具调用。"
        "因为模型没有任何理由按你的私有格式说话。",
        "2. **格式契约才是那个开关**：B/C 行里，愿意配合的 CooperativeLLM 立刻产出可解析输出。"
        "业务规则只是锦上添花，它约束的是「行为」，不是「格式」。",
        "3. **模型本身仍是变量**：ChattyLLM 即使拿到完整契约也不遵守 —— 这就是为什么"
        "选模型时要实测「指令遵循能力」，而不只看跑分。",
    ]:
        print(f"     {line}")
    print()
    note("结论：可解析率 = f(提示词格式契约, 模型的指令遵循能力)。两者缺一不可。")

    # 保存结果供自检使用
    globals()["_EXPERIMENT_MATRIX"] = matrix


# ===========================================================================
# 第 4 节：解析器 —— 六种畸形输出都要能处理
# ===========================================================================


def demo_parser() -> None:
    section("解析器：现实世界里模型的输出有多脏", "④")
    note("下面六种都是真实会遇到的形态（core/parser.py 全部支持）。")
    print()

    cases: list[tuple[str, str, str]] = [
        ("① 标准 ReAct",
         'Thought: 用 calc 算。\nAction: calc(expr="1+1")\n'
         '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>',
         "最理想：Thought + Action + 结构化标签"),
        ("② 只有 Markdown 代码块",
         'Thought: 我来算。\n```json\n{"name": "calc", "args": {"expr": "1+1"}}\n```',
         "很多模型默认输出 ```json 围栏"),
        ("③ 单引号 JSON",
         "Thought: 算一下。\n<tool_call>{'name': 'calc', 'args': {'expr': '1+1'}}</tool_call>",
         "Python 风格的引号，不是合法 JSON"),
        ("④ 尾逗号",
         'Thought: 算一下。\n<tool_call>{"name": "calc", "args": {"expr": "1+1",},}</tool_call>',
         "JSON 不允许尾逗号，但模型很爱写"),
        ("⑤ 参数值缺引号（KV 兜底）",
         "Thought: 算一下。\nAction: calc(expr=1+1)",
         "连 JSON 都没有，靠 Action: name(k=v) 兜底"),
        ("⑥ 括号没闭合 / 彻底崩坏",
         'Thought: 我要算一下\nAction: calc(expr="1+1"',
         "★ 最危险的一种：容易把半截话当成答案"),
    ]

    for title, raw, why in cases:
        parsed = parse_output(raw)
        print(f"  {title}")
        kv("模型输出", raw.replace("\n", " ")[:66])
        kv("为什么会出现", why)
        kv("解析结果", f"thought={bool(parsed.thought)} / "
                       f"calls={[c.signature() for c in parsed.tool_calls]} / "
                       f"answer={parsed.answer[:24]!r}")
        if parsed.errors:
            kv("解析错误", parsed.errors[0][:66])
        print()

    warn("重点看第 ⑥ 种：它既没有工具调用，也没有 Final Answer。")
    note("如果解析器的兜底逻辑是「都没有 → 整段当答案」，那么这半截坏 JSON 会被当成")
    note("最终答案交给用户，而且 Agent 完全不知道出过错 —— 这是**静默错误**。")
    print()
    note("core/parser.py 的做法：检测到 Action/tool_call 等协议标记却解析不出调用时，")
    note("标记为「协议违规」，不退化成答案，交给上层回灌纠错：")
    code(
        'if not out.tool_calls and not out.answer:\n'
        '    if _looks_like_broken_protocol(text):\n'
        '        out.errors.append("检测到 Action/tool_call 等工具调用标记，但无法解析出合法调用")\n'
        '    else:\n'
        '        out.answer = _clean(text)     # 真正的聊天内容才当答案',
        indent=4,
    )
    print()
    note("解析策略是**分级降级**的（可靠性从高到低，任一级成功就停止）：")
    code(
        "1. <tool_call>{...}</tool_call>      ← 最可靠，模型专门学过\n"
        "2. ```json {...}``` 代码块            ← 次可靠\n"
        "3. Action: name({...}) 内联 JSON      ← 常见\n"
        "4. Action: name(k=v) 键值对兜底       ← JSON 全崩了也能救\n"
        "5. 整段里第一个像 JSON 的片段         ← 最后手段",
        indent=4,
    )


# ===========================================================================
# 第 5 节：解析失败回灌 —— 最重要的纠错机制
# ===========================================================================


def demo_parse_feedback() -> None:
    section("解析失败回灌：最重要的纠错机制", "⑤")
    note("模型写崩了格式，不要放弃 —— 把「哪里崩了 + 正确格式」回灌给它，让它重写。")
    print()

    # 一个"第一次写崩、被纠正后改对"的假模型：这正是真实模型的行为
    broken = 'Thought: 我要算一下\nAction: calc(expr="1+1"'          # 括号没闭合
    fixed = ('Thought: 抱歉，刚才格式写错了。\n'
             'Action: calc(expr="1+1")\n'
             '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>')
    final = 'Thought: 算出来了。\nFinal Answer: 1+1 = 2'

    llm = ScriptedLLM([broken, fixed, final])
    answer, steps, calls, reason = _mini_agent(llm, max_parse_retries=2).run("计算 1+1")

    print()
    for s in steps:
        kv(f"第 {s['index']} 圈", s["note"] or ("有工具调用" if s["calls"] else "无动作"))
        kv("  模型输出", s["raw"].replace("\n", " ")[:62])
    print()
    kv("最终答案", answer)
    kv("停机原因", reason)
    print()
    ok("纠错成功：模型第一次写崩 → 回灌 → 第二次写对 → 任务完成。")
    print()
    note("回灌的原文长这样（core/prompts.py 的 parse_error_feedback）：")
    from core.prompts import PromptBuilder as PB

    code(PB.parse_error_feedback(
        "检测到 Action/tool_call 等工具调用标记，但无法解析出合法调用（JSON 括号没闭合）"
    ), indent=4)
    print()
    warn("但回灌不是无限制的。如果模型连续 N 次都写不对，说明它根本没能力遵守这个协议，")
    warn("继续重试只是烧钱。所以必须有 max_parse_retries，超了就停机并如实报告。")

    # 演示"永远写不对"的情形
    always_bad = ScriptedLLM([broken], repeat_last=True)
    _, steps2, _, reason2 = _mini_agent(always_bad, max_parse_retries=2).run("计算 1+1")
    print()
    kv("永远写不对的模型 · 圈数", len(steps2))
    kv("永远写不对的模型 · 停机原因", reason2)
    ok("max_parse_retries 生效：连错 3 次后主动停机，而不是无限重试烧钱。")


# ===========================================================================
# 第 6 节：用 SpyLLM 看上下文如何逐圈膨胀
# ===========================================================================


def demo_spy_context() -> None:
    section("用 SpyLLM 看模型的完整输入", "⑥")
    note("学习提示词工程最有效的方法：把模型每次看到的东西**完整打印出来**。")
    print()

    spy = SpyLLM(default_mock())
    agent = _mini_agent(spy).__class__(
        llm=spy, max_steps=6, verbose=False,
    )
    agent.run("计算 (12+8)*3/4")
    print(spy.diff_summary())
    print()
    note("观察：每次调用，消息数和字符数都在增长 —— 因为历史被完整重发。")
    print()
    note("第 1 次调用时，模型看到的是（前 30 行）：")
    for line in spy.last_prompt().splitlines()[:1]:
        pass
    first = spy.seen[0] if spy.seen else []
    for m in first:
        preview = m.content.replace("\n", " ")[:70]
        print(f"      [{m.role:<9}] {preview}")
    print()
    warn("这引出两个后续章节的核心问题：")
    print("     · 历史无限增长 → 上下文窗口会爆 → 第 05 章「记忆与上下文工程」")
    print("     · 每次重发全部历史 → token 成本平方级增长 → 第 12 章「成本优化」")
    print()
    note("还有一个立即可用的技巧：**把提示词存起来做版本对比**。")
    code(
        "# 改提示词前后各存一份，diff 一下就知道自己改了什么\n"
        "Path('prompt_v1.txt').write_text(system, encoding='utf-8')\n"
        "# 第 10 章会讲怎么把提示词改动变成可量化的回归测试",
        indent=4,
    )


# ===========================================================================
# 第 7 节：三种协议对比 + 收口
# ===========================================================================


def demo_protocol_comparison() -> None:
    section("三种工具调用协议：怎么选", "⑦")
    rows = [
        ("纯文本 ReAct", "自己写正则/分级解析", "任何模型都能用、完全可解释、易调试",
         "可靠性最低、消耗 token（格式说明很长）、容易解析失败"),
        ("原生 Function Calling", "解析 API 返回的 tool_calls 字段", "可靠性最高、格式由厂商保证",
         "绑定厂商、模型受限、调试时看不到「黑盒」决策"),
        ("JSON Mode", "强制模型输出合法 JSON（`response_format={\"type\":\"json_object\"}`）",
         "保证能被 `json.loads()` 解析",
         "**不保证字段符合你的 Schema**（可能缺字段、类型不对、枚举乱写）"),
        ("严格结构化输出（strict）", "把 Schema 编译成语法，逐 token 约束采样",
         "字段、类型、必填都按 Schema 来",
         "Schema 必须写完整（常要求 `additionalProperties: false` + 全部字段必填）；部分服务商不提供"),
    ]
    print(f"  {'协议':<22}{'实现方式':<26}{'优点':<32}{'代价'}")
    print("  " + "-" * 108)
    for a, b, c, d in rows:
        print(f"  {a:<22}{b:<26}{c:<32}{d}")

    print()
    note("工程上的务实选择（按场景）：")
    for line in [
        "· 生产环境优先用**原生 Function Calling** —— 可靠性带来的收益远大于厂商绑定成本；",
        "· 需要兼容本地开源模型 / 多厂商时，用**纯文本 ReAct**，但要写足分级降级解析；",
        "· 两种协议由 PromptBuilder(style=...) 切换：选 function_calling 时 core/agent.py 通过 API 的",
        "  tools / tool_choice 下发工具规格；选 react 时工具说明走系统提示词；原生 tool_calls 会被",
        "  core/real_llm.py 归一成同一套文本协议，**上层解析逻辑一行都不用改**（适配器模式的价值）。",
    ]:
        print(f"     {line}")

    print()
    note("无论用哪种，都别忘了这三条保命措施：")
    for line in [
        "1. max_parse_retries —— 解析连续失败要停机，不能无限重试；",
        "2. 协议违规 ≠ 最终答案 —— 别把半截坏 JSON 当答案交给用户；",
        "3. 完整的原始输出要落日志 —— 排查解析问题时，你需要看到模型到底吐了什么。",
    ]:
        print(f"     {line}")

    print()
    essence(
        "ReAct = 把「思考」显式写出来，让推理可观察、可调试、可回灌纠错。\n"
        "\n"
        "提示词 = 身份与规则 + 工具说明书 + 输出格式契约 + 参考资料。\n"
        "其中「输出格式契约」是 Agent 特有的，它的读者不是用户，而是**解析器**。\n"
        "\n"
        "一句话记住本章：\n"
        "  Agent 的可靠性 = 模型的指令遵循能力 × 你的格式契约清晰度 × 解析器的健壮性。\n"
        "  三者中，只有后两个是你完全可控的 —— 所以先把它们做到极致。"
    )


# ===========================================================================
# 迷你 Agent（复用第 01 章的结构，便于本章聚焦"提示词与解析"）
# ===========================================================================


class _MiniResult:
    """一个轻量结果对象，比元组可读。"""

    def __init__(self, answer, steps, calls, reason):
        self.answer = answer
        self.steps = steps
        self.calls = calls
        self.reason = reason

    def __iter__(self):
        """兼容 `answer, steps, calls, reason = result` 的解包写法。"""
        return iter((self.answer, self.steps, self.calls, self.reason))


class MiniAgent:
    """第 01 章 MiniAgent 的精简版，加上**解析失败回灌**与 max_parse_retries。"""

    def __init__(self, llm: LLM, builder: PromptBuilder | None = None,
                 max_steps: int = 6, max_parse_retries: int = 2,
                 verbose: bool = False) -> None:
        self.llm = llm
        self.builder = builder or PromptBuilder(style="react")
        self.max_steps = max_steps
        self.max_parse_retries = max_parse_retries
        self.verbose = verbose
        self.tools = build_default_registry(ROOT)

    def run(self, question: str) -> _MiniResult:
        system = self.builder.build_system(self.tools)
        messages = [Message.system(system), Message.user(question)]
        steps: list[dict] = []
        parse_fail_streak = 0
        reason = "max_steps"

        for i in range(1, self.max_steps + 1):
            raw = self.llm.complete(messages).text
            parsed = parse_output(raw, known_tools=self.tools.names())
            step = {"index": i, "raw": raw, "note": "",
                    "calls": parsed.tool_calls, "errors": parsed.errors}

            # 是最终答案吗？
            if parsed.is_final:
                step["note"] = "给出最终答案"
                steps.append(step)
                messages.append(Message.assistant(raw))
                reason = "final_answer"
                return _MiniResult(parsed.answer, steps, self._all_calls(steps), reason)

            # 解析失败 → 回灌纠错
            if not parsed.has_tool_call:
                parse_fail_streak += 1
                step["note"] = f"解析失败（第 {parse_fail_streak} 次），已回灌纠错提示"
                steps.append(step)
                messages.append(Message.assistant(raw))
                messages.append(Message.user(self.builder.parse_error_feedback(
                    "; ".join(parsed.errors) or "没有找到 Action 或 Final Answer")))
                if parse_fail_streak > self.max_parse_retries:
                    reason = "parse_failed"
                    return _MiniResult("", steps, [], reason)
                continue

            parse_fail_streak = 0
            step["note"] = "执行工具"
            steps.append(step)
            messages.append(Message.assistant(parsed.thought or "", parsed.tool_calls))
            for call in parsed.tool_calls:
                r = self.tools.execute(call.name, call.args)
                messages.append(Message.tool_result(call.name, r.to_observation(),
                                                    ok=r.ok))

        return _MiniResult("", steps, self._all_calls(steps), reason)

    @staticmethod
    def _all_calls(steps: list[dict]) -> list:
        return [c for s in steps for c in s["calls"]]


def _mini_agent(llm: LLM, builder: PromptBuilder | None = None,
                max_parse_retries: int = 2) -> MiniAgent:
    return MiniAgent(llm=llm, builder=builder, max_parse_retries=max_parse_retries)


# ===========================================================================
# 自检
# ===========================================================================


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（由 scripts/run_all_checks.py 调用）。"""
    results: list[tuple[str, bool, str]] = []
    registry = build_default_registry(ROOT)

    # --- 验收 1：提示词四块结构都能单独断言 ---
    system = PromptBuilder(
        style="react",
        persona="你是电商客服",
        rules=["禁止心算"],
        extra_context="当前时间：2025-01-01",
    ).build_system(registry)
    results.append(check_that("格式契约存在（Action:）", "Action:" in system))
    results.append(check_that("格式契约存在（<tool_call>）", "<tool_call>" in system))
    results.append(check_that("工具说明书被注入（含 calc）",
                              "calc" in system and "expr" in system))
    results.append(check_that("业务规则被注入", "禁止心算" in system))
    results.append(check_that("动态上下文被注入", "2025-01-01" in system))
    results.append(check_that("身份被注入", "电商客服" in system))

    # --- 验收 2：plain 风格不注入工具 ---
    plain = PromptBuilder(style="plain").build_system(registry)
    results.append(check_that("plain 风格不注入工具说明书",
                              "calc" not in plain and "Action:" not in plain))

    # --- 验收 3：SpyLLM 能看到完整上下文且逐圈增长 ---
    spy = SpyLLM(default_mock())
    MiniAgent(llm=spy, max_steps=6).run("计算 (12+8)*3/4")
    sizes = [len(c) for c in spy.seen]
    results.append(check_that("SpyLLM 记录了每次调用", len(spy.seen) >= 2,
                              f"{len(spy.seen)} 次"))
    results.append(check_that("上下文逐圈增长（历史被重发）",
                              len(sizes) >= 2 and sizes[-1] > sizes[0], f"{sizes}"))
    results.append(check_that("SpyLLM 能导出完整提示词文本",
                              "system" in spy.last_prompt() or "【系统】" in spy.last_prompt()))

    # --- 验收 4：解析器五种分级降级都能工作 ---
    results.append(check_that("① <tool_call> 标签解析",
                              len(parse_output(
                                  'Thought: x\n<tool_call>{"name":"calc","args":{"expr":"1+1"}}</tool_call>'
                              ).tool_calls) == 1))
    results.append(check_that("② ```json 代码块解析",
                              len(parse_output(
                                  '```json\n{"name":"calc","args":{"expr":"1+1"}}\n```'
                              ).tool_calls) == 1))
    results.append(check_that("③ 单引号 JSON 解析",
                              len(parse_output(
                                  "<tool_call>{'name':'calc','args':{'expr':'1+1'}}</tool_call>"
                              ).tool_calls) == 1))
    results.append(check_that("④ 尾逗号 JSON 解析",
                              len(parse_output(
                                  '<tool_call>{"name":"calc","args":{"expr":"1+1",},}</tool_call>'
                              ).tool_calls) == 1))
    results.append(check_that("⑤ Action: name(k=v) 键值兜底",
                              len(parse_output("Action: calc(expr=1+1)").tool_calls) == 1))
    p5 = parse_output("Action: calc(expr=1+1)")
    results.append(check_that("⑤ 键值兜底的参数被正确还原",
                              p5.tool_calls and p5.tool_calls[0].args.get("expr") == "1+1",
                              str(p5.tool_calls[0].args if p5.tool_calls else {})))

    # --- 验收 5：畸形输出不崩，且不把半截话当答案 ---
    results.append(check_that("畸形输出不抛异常", _no_raise(
        lambda: parse_output('Thought: x\nAction: calc(expr="1+1"'))))
    broken = parse_output('Thought: 我要算一下\nAction: calc(expr="1+1"')
    results.append(check_that("协议违规不退化成最终答案", broken.answer == ""))
    results.append(check_that("协议违规给出可读错误", bool(broken.errors)))
    results.append(check_that("协议违规错误信息可读（含原因提示）",
                              broken.errors and "Action" in broken.errors[0],
                              broken.errors[0][:40] if broken.errors else ""))
    results.append(check_that("真正的聊天内容仍然当答案",
                              parse_output("你好呀，今天天气不错").answer
                              == "你好呀，今天天气不错"))
    results.append(check_that("正常 Final Answer 解析",
                              parse_output("Thought: x\nFinal Answer: 15").answer == "15"))

    # --- 验收 6：解析失败回灌纠错链路 ---
    broken_txt = 'Thought: 我要算一下\nAction: calc(expr="1+1"'
    fixed_txt = ('Thought: 改好了。\nAction: calc(expr="1+1")\n'
                 '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>')
    final_txt = 'Thought: 好了。\nFinal Answer: 1+1 = 2'
    r = _mini_agent(ScriptedLLM([broken_txt, fixed_txt, final_txt])).run("计算 1+1")
    results.append(check_that("解析失败后回灌纠错并最终成功",
                              r.reason == "final_answer", r.reason))
    results.append(check_that("纠错后确实执行了工具",
                              any(c.name == "calc" for c in r.calls),
                              str([c.name for c in r.calls])))

    # --- 验收 7：连续失败会被停机保护 ---
    r2 = _mini_agent(ScriptedLLM([broken_txt], repeat_last=True),
                     max_parse_retries=2).run("计算 1+1")
    results.append(check_that("连续解析失败触发 parse_failed 停机",
                              r2.reason == "parse_failed", r2.reason))
    results.append(check_that("停机前重试次数受 max_parse_retries 限制（3 圈）",
                              len(r2.steps) == 3, f"{len(r2.steps)} 圈"))

    # --- 验收 8：格式契约确实改变输出格式（受控实验）---
    chatty_free = _mini_agent(ChattyLLM()).run("计算 (12+8)*3/4")
    coop_plain = _mini_agent(CooperativeLLM(),
                             builder=PromptBuilder(style="plain")).run("计算 (12+8)*3/4")
    coop_react = _mini_agent(CooperativeLLM(),
                             builder=PromptBuilder(style="react")).run("计算 (12+8)*3/4")
    results.append(check_that("无格式契约时模型不产出可解析调用",
                              len(chatty_free.calls) == 0, f"{len(chatty_free.calls)} 个"))
    results.append(check_that("plain 风格下也不产出可解析调用",
                              len(coop_plain.calls) == 0, f"{len(coop_plain.calls)} 个"))
    results.append(check_that("react 格式契约下产出可解析调用",
                              len(coop_react.calls) >= 1, f"{len(coop_react.calls)} 个"))
    results.append(check_that("react 契约下任务成功完成并算出 15",
                              "15" in coop_react.answer, coop_react.answer[:40]))

    # --- 验收 9：框架版把原生 tool_calls 还原成文本协议（适配器一致性）---
    from core.parser import parse_tool_calls

    native = ('<tool_call>{"id": "call_1", "name": "calc", "args": {"expr": "6*7"}}</tool_call>')
    calls = parse_tool_calls(native)
    results.append(check_that("原生 tool_calls 转文本协议后可被同一解析器解析",
                              len(calls) == 1 and calls[0].name == "calc",
                              str([c.name for c in calls])))

    return results


def _no_raise(fn) -> bool:
    try:
        fn()
        return True
    except Exception:
        return False


# ===========================================================================
# 入口
# ===========================================================================

SECTIONS = {
    "1": ("没有格式契约的世界", demo_no_protocol),
    "2": ("提示词的三段式结构", demo_prompt_anatomy),
    "3": ("受控实验：提示词质量 vs 可解析率", demo_experiment),
    "4": ("解析器：六种畸形输出", demo_parser),
    "5": ("解析失败回灌纠错", demo_parse_feedback),
    "6": ("用 SpyLLM 看上下文膨胀", demo_spy_context),
    "7": ("三种协议对比 + 收口", demo_protocol_comparison),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 03 章 · ReAct 提示工程")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 03 章 · ReAct 提示工程")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 03 章", run_checks()) else 1

    banner("第 03 章 · ReAct 提示工程",
           "目标：搞清怎么跟模型说话，才能让它的输出被程序可靠解析")

    for key in ([args.section] if args.section else sorted(SECTIONS)):
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 03 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
