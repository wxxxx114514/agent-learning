"""第 01 章 · 最小 Agent 循环 —— 一个 while 循环就是一个 Agent。

运行：
    py -m stages.stage01_agent_loop.demo
    py -m stages.stage01_agent_loop.demo --list      # 只看目录
    py -m stages.stage01_agent_loop.demo --section 3 # 只看第 3 节

本章目标：**从零手写**一个 60 行的 Agent，亲眼看见它和"一次问答"的差别。
这里刻意**不用 core/agent.py**，因为我们要先看懂循环本身；
本章最后会把我们手写的 MiniAgent 与框架里的 Agent 放在一起对比。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# 允许 `py stages/stage01_agent_loop/demo.py` 这种直接运行方式
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check_that, code, essence, kv, note, ok, report,
    section, setup_console, warn,
)
from core.llm import LLM  # noqa: E402
from core.message import Message  # noqa: E402
from core.mock_llm import ScriptedLLM  # noqa: E402

# ===========================================================================
# 第 1 节：先看看"没有循环"的世界有多无力
# ===========================================================================


def demo_no_loop() -> str:
    """最朴素的做法：问一次，答一次。"""
    question = "帮我算一下 (12+8)*3/4，然后告诉我订单 A1001 到哪了"
    fake_model_reply = "抱歉，我无法进行计算，也无法查询订单信息。"

    section("没有循环的问答：一次调用，一次回答", "①")
    kv("用户提问", question)
    kv("模型回答", fake_model_reply)
    print()
    warn("模型没有手（不能算数）、没有眼（看不到订单系统）。")
    note("只靠一次调用，它只能'凭记忆瞎猜'。要突破这个限制，它需要一个循环 + 工具。")
    return fake_model_reply


# ===========================================================================
# 第 2 节：手写最小循环（本章的核心）
# ===========================================================================
# 读代码的顺序建议：
#   先看 MiniAgent.run() 的 while 循环（约 30 行），那才是 Agent 的本质；
#   其余都是"让它别崩"的工程细节。

TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
FINAL_RE = re.compile(r"Final Answer\s*[:：]\s*(.*)", re.S)


@dataclass
class Step:
    """一圈循环的记录。为什么第一天就要记录？因为 Agent 出错时你只有它。"""

    index: int
    thought: str = ""
    action: str = ""
    observation: str = ""
    answer: str = ""


class MiniAgent:
    """最小可用 Agent：一个 while 循环 + 一个会调工具的模型 + 一个历史列表。

    这就是**全部**核心了。后面 12 章都是在它的基础上解决具体问题：
    工具变多怎么办（02）、提示词怎么写（03）、任务变复杂怎么办（04）……
    """

    def __init__(self, llm: LLM, tools: dict, max_steps: int = 6, verbose: bool = True) -> None:
        self.llm = llm
        self.tools = tools          # 极简工具表：{名字: 可调用对象}
        self.max_steps = max_steps  # ★ 必需的保护，不是可选项
        self.verbose = verbose

    # ------------------------------------------------------------------
    def run(self, question: str) -> tuple[str, list[Step], str]:
        """返回 (答案, 步骤列表, 停机原因)。"""
        # ① 历史列表 —— 这就是 Agent 的"记忆"，也是它唯一的上下文
        messages: list[Message] = [
            Message.system(
                "你可以调用工具。需要工具时输出：\n"
                "Thought: ...\n"
                'Action: 工具名(参数)\n<tool_call>{"name": "工具名", "args": {...}}</tool_call>\n'
                "可以回答时输出：\nThought: ...\nFinal Answer: ...\n"
                f"可用工具：{list(self.tools)}\n"
                "调用示例：calc(expr=\"1+1\")"
            ),
            Message.user(question),
        ]
        steps: list[Step] = []
        stop_reason = "max_steps"

        # ② 主循环：想 → 做 → 看 → 记，一圈一圈直到给出答案
        for i in range(1, self.max_steps + 1):
            step = Step(index=i)
            steps.append(step)

            # --- 想：把历史交给模型，让它写下一段 ---
            reply = self.llm.complete(messages).text
            step.thought = _extract_thought(reply)

            # --- 它是想回答问题，还是想调工具？ ---
            answer_match = FINAL_RE.search(reply)
            call = _extract_tool_call(reply)

            if answer_match and not call:
                step.answer = answer_match.group(1).strip()
                messages.append(Message.assistant(reply))
                stop_reason = "final_answer"
                self._log(step)
                break

            if not call:
                # 既没答案也没动作 → 把错误回灌，让它重写
                messages.append(Message.assistant(reply))
                messages.append(Message.user(
                    "你的输出无法解析。请严格用 Action: 工具名(参数) + "
                    '<tool_call>{"name":..., "args":{...}}</tool_call>，或 Final Answer: ...'
                ))
                self._log(step, extra="解析失败，已回灌纠错")
                continue

            # --- 做：真正执行工具（这是模型做不到的事） ---
            name, args = call
            step.action = f"{name}({', '.join(f'{k}={v!r}' for k, v in args.items())})"
            messages.append(Message.assistant(reply))

            # --- 看：把结果变成文字喂回去 ---
            step.observation = self._execute(name, args)
            messages.append(Message.tool_result(name, step.observation))

            # --- 记：历史列表已经自动记住了上面两步（这就是"记忆"） ---
            self._log(step)

        return _last_answer(steps), steps, stop_reason

    # ------------------------------------------------------------------
    def _execute(self, name: str, args: dict) -> str:
        """执行工具。**关键设计：任何失败都不抛异常，而是变成一句可读的观察结果。**

        这里的 `**args` 是关键：模型给的是**参数字典**（{"expr": "1+1"}），
        而工具是普通 Python 函数（calc(expr)）。必须展开成关键字参数。
        新手最容易写成 `self.tools[name](args)` —— 那样 expr 收到的是整个字典，
        工具会在内部莫名报错，而且报错信息很难看出真正原因。
        """
        if name not in self.tools:
            return (f"错误：工具 {name!r} 不存在。"
                    f"可用工具：{list(self.tools)}。请换一个工具，或直接给出 Final Answer。")
        try:
            result = self.tools[name](**args)
            return f"<result tool=\"{name}\">\n{result}\n</result>"
        except TypeError as exc:
            return (f"错误：参数不对（{exc}）。"
                    f"工具 {name} 需要参数：{_tool_params(self.tools[name])}")
        except Exception as exc:
            return f"错误：{type(exc).__name__}: {exc}"

    def _log(self, step: Step, extra: str = "") -> None:
        if not self.verbose:
            return
        print(f"\n  ┌─ 第 {step.index} 圈 " + "─" * 40)
        if step.thought:
            print(f"  │ 💭 想 : {step.thought[:70]}")
        if step.action:
            print(f"  │ 🔧 做 : {step.action[:70]}")
        if step.observation:
            print(f"  │ 👁  看 : {_preview(step.observation)}")
        if step.answer:
            print(f"  │ ✅ 答 : {step.answer[:70]}")
        if extra:
            print(f"  │ ⚠️  {extra}")
        print("  └" + "─" * 48)


def _extract_thought(text: str) -> str:
    m = re.search(r"Thought\s*[:：]\s*(.*?)(?=\n\s*(?:Action|Final Answer)|$)", text, re.S)
    return m.group(1).strip() if m else ""


def _tool_params(fn) -> str:
    """内省出工具的参数名 —— 出错时告诉模型"这个工具到底要什么参数"。"""
    import inspect

    try:
        return str(list(inspect.signature(fn).parameters))
    except (TypeError, ValueError):
        return "(无法内省)"


def _preview(observation: str, width: int = 70) -> str:
    """把 observation 压成一行预览；成功的 <result> 包裹去掉，只看内容。"""
    body = observation.strip()
    if body.startswith("<result"):
        body = body.split(">", 1)[-1].rsplit("</result>", 1)[0].strip()
    return body.replace("\n", " ")[:width]


def _extract_tool_call(text: str) -> tuple[str, dict] | None:
    """极简解析：只认 <tool_call>{"name":..., "args":{...}}</tool_call>。

    第 03 章会看到工业级解析器要处理多少种畸形输出 —— 这里先保持简单。
    """
    import json

    m = TOOL_CALL_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except Exception:
        return None
    if not isinstance(obj, dict) or "name" not in obj:
        return None
    args = obj.get("args", obj.get("arguments", {}))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            args = {"input": args}
    if not isinstance(args, dict):
        args = {"input": args}
    return str(obj["name"]), args


def _last_answer(steps: list[Step]) -> str:
    for s in reversed(steps):
        if s.answer:
            return s.answer
    return ""


# ===========================================================================
# 第 3 节：真跑一次，并看清 messages 是怎么长的
# ===========================================================================


def _demo_tools() -> dict:
    """两个真实的小工具。注意：它们就是普通 Python 函数，没有任何魔法。"""
    return {
        "calc": lambda expr: _safe_calc(expr),
        "lookup_order": _lookup_order,
    }


# 教学用的假订单表（真实场景这里是查数据库/调内部 API）
_FAKE_ORDERS = {
    "A1001": "订单 A1001：已发货，顺丰 SF1234567890，预计 2025-01-05 送达",
    "B2043": "订单 B2043：运输中，中通 ZT9988776655，预计 2025-01-03 送达",
}


def _lookup_order(order_id: str) -> str:
    """查订单。查不到时抛 ValueError —— 由 _execute 转成可读的 observation。"""
    key = order_id.upper()
    if key not in _FAKE_ORDERS:
        raise ValueError(f"订单 {key} 不存在。已知示例订单：{sorted(_FAKE_ORDERS)}")
    return _FAKE_ORDERS[key]


def _safe_calc(expr: str) -> str:
    """安全计算：白名单字符 + 受限 AST。绝不用 eval。"""
    import ast
    import math

    allowed = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
               ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
    funcs = {"sqrt": math.sqrt}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in allowed:
            return allowed[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in funcs:
            return funcs[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"不支持的表达式语法: {type(node).__name__}")

    value = ev(ast.parse(expr, mode="eval"))
    return f"{expr} = {int(value) if float(value).is_integer() else value}"


def demo_run() -> tuple[str, list[Step], str]:
    section("真跑一次：循环如何把'做不到'变成'做得到'", "③")

    # 剧本模型：一个"听话但不会思考"的假模型。它的每一步输出都是我们写死的，
    # 这样才能确定性地观察循环结构（真实模型同理，只是它自己决定下一步）。
    script = [
        # 第 1 圈：模型选择先算数
        'Thought: 先解决算术部分。\nAction: calc(expr="(12+8)*3/4")\n'
        '<tool_call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</tool_call>',
        # 第 2 圈：算完了，接着查订单
        'Thought: 算术完成，现在查订单。\nAction: lookup_order(order_id="A1001")\n'
        '<tool_call>{"name": "lookup_order", "args": {"order_id": "A1001"}}</tool_call>',
        # 第 3 圈：信息齐了，给答案
        'Thought: 两个信息都有了，可以回答了。\n'
        'Final Answer: (12+8)*3/4 = 15；订单 A1001 已发货，顺丰 SF1234567890，预计 2025-01-05 送达。',
    ]
    agent = MiniAgent(llm=ScriptedLLM(script), tools=_demo_tools(), max_steps=6)
    answer, steps, reason = agent.run("帮我算一下 (12+8)*3/4，然后告诉我订单 A1001 到哪了")

    print()
    kv("最终答案", answer)
    kv("循环圈数", len(steps))
    kv("停机原因", reason)
    return answer, steps, reason


def demo_message_growth() -> None:
    section("关键洞察：模型的'记忆'就是这个 messages 列表", "④")
    note("Agent 没有记忆，它只是每次把整段历史重新发给模型。历史列表 = 记忆。")
    print()

    script = [
        'Thought: 需要算一下。\nAction: calc(expr="6*7")\n'
        '<tool_call>{"name": "calc", "args": {"expr": "6*7"}}</tool_call>',
        'Thought: 算好了。\nFinal Answer: 6*7 = 42',
    ]
    llm = ScriptedLLM(script)
    agent = MiniAgent(llm=llm, tools=_demo_tools(), max_steps=4, verbose=False)
    agent.run("计算 6*7")

    for i, msgs in enumerate(llm.calls, 1):
        chars = sum(len(m.content) for m in msgs)
        kv(f"第 {i} 次调用", f"{len(msgs)} 条消息 / {chars} 字符")
        for m in msgs:
            preview = m.content.replace("\n", " ")[:58]
            print(f"        [{m.role:<9}] {preview}")
        print()

    note("看到没？每次调用模型，历史都比上一次更长。")
    warn("这直接引出第 05 章的问题：历史无限增长，上下文窗口会爆。")
    warn("也引出第 12 章的问题：每次都要重发全部历史，token 成本是平方级增长的。")


# ===========================================================================
# 第 4 节：四道"保险"——为什么会停，比为什么会跑更重要
# ===========================================================================


class AlwaysToolLLM(LLM):
    """永远返回同一个工具调用的假模型（模拟真实世界里"模型卡住了"）。"""

    name = "always-tool"

    def _complete(self, messages, **kwargs):
        from core.llm import LLMResponse

        return LLMResponse(
            text='Thought: 我再确认一次。\nAction: calc(expr="1+1")\n'
                 '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>',
            model="always-tool",
        )


def demo_stop_conditions() -> None:
    section("四道保险：Agent 为什么会停下来", "⑤")
    bullet("① final_answer —— 模型给出了答案（正常结束）")
    bullet("② max_steps    —— 步数用完，强制停机（防止烧钱）")
    bullet("③ loop_detected—— 同样的动作反复出现（模型卡住）")
    bullet("④ parse_failed —— 模型输出永远解析不了（协议没对齐）")
    print()

    # 保险 ②：死循环 —— 把 max_steps 设成 3，看它怎么被拦住
    agent = MiniAgent(llm=AlwaysToolLLM(), tools=_demo_tools(), max_steps=3, verbose=False)
    answer, steps, reason = agent.run("随便问点什么")
    kv("死循环实验 · 圈数", len(steps))
    kv("死循环实验 · 停机原因", reason)
    ok("max_steps 生效：模型卡住时，我们只损失 3 次调用，而不是无限次。")
    print()
    note("如果去掉 max_steps，这段代码会一直跑到你没钱或者没耐心为止。")
    note("这就是为什么 max_steps 是必需品：它是唯一能兜住'模型犯傻'的机制。")
    print()

    # 保险 ④：输出格式崩坏
    bad = ScriptedLLM(["我觉得这个问题的答案是 15 吧", "嗯……让我再想想"], repeat_last=True)
    agent2 = MiniAgent(llm=bad, tools=_demo_tools(), max_steps=4, verbose=False)
    _, steps2, reason2 = agent2.run("计算 (12+8)*3/4")
    kv("格式崩坏实验 · 圈数", len(steps2))
    kv("格式崩坏实验 · 停机原因", reason2)
    note("模型不会写协议 → 每圈都白跑 → max_steps 兜底停机。")
    warn("这说明'输出格式契约'本身是 Agent 可靠性的关键，第 03 章专门解决它。")


def demo_compare_framework() -> None:
    section("对比：框架版 Agent（core/agent.py）多做了什么", "⑥")
    from core import Agent
    from core.mock_llm import RuleBasedLLM

    agent = Agent(llm=RuleBasedLLM(), max_steps=6, verbose=False)
    result = agent.run("计算 (12+8)*3/4")
    kv("答案", result.answer)
    kv("停机原因", result.stop_reason)
    kv("LLM 调用次数", result.llm_calls)
    kv("消耗 token", result.total_tokens)
    kv("耗时", f"{result.elapsed_ms:.0f}ms")
    print()
    note("框架与我们手写的 MiniAgent 结构完全一样，只是多了这些工程能力：")
    for line in [
        "1. 解析器更鲁棒（容忍 5 种畸形格式，见 core/parser.py）",
        "2. 解析失败有预算（连续失败 N 次才停机，而不是立刻放弃）",
        "3. LLM 调用带重试（网络抖动不该让整轮任务失败）",
        "4. 重复动作检测（发现复读会主动提醒模型，而不是干等）",
        "5. 上下文保护（超长历史会折叠，见第 05 章）",
        "6. 完整的 StepRecord 轨迹（每一步的耗时/token/错误都可查）",
        "7. 工具审批钩子（高危操作先问人，见第 11 章）",
    ]:
        print(f"     {line}")
    print()
    print(result.trace()[:900] if result.trace() else "")


# ===========================================================================
# 第 5 节：一句话本质 + 自检
# ===========================================================================


def demo_essence() -> None:
    section("收口：一句话本质", "⑦")
    essence(
        "Agent = 一个 while 循环\n"
        "      + 一个会调工具的模型\n"
        "      + 一个能记住历史的列表\n"
        "\n"
        "循环的每一圈只做四件事：想（LLM）→ 做（Tool）→ 看（Observation）→ 记（History）。\n"
        "\n"
        "把这句话讲清楚，你就已经掌握 Agent 开发 80% 的骨架了；\n"
        "剩下 12 章，都在解决这个骨架在真实世界里会遇到的具体麻烦。"
    )


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（由 scripts/run_all_checks.py 调用）。"""
    results: list[tuple[str, bool, str]] = []

    # --- 验收 1：能跑通多步任务并正常结束 ---
    script = [
        'Thought: 先算数。\nAction: calc(expr="(12+8)*3/4")\n'
        '<tool_call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</tool_call>',
        'Thought: 再查订单。\nAction: lookup_order(order_id="A1001")\n'
        '<tool_call>{"name": "lookup_order", "args": {"order_id": "A1001"}}</tool_call>',
        'Thought: 齐了。\nFinal Answer: 结果是 15；订单 A1001 已发货。',
    ]
    agent = MiniAgent(llm=ScriptedLLM(script), tools=_demo_tools(), max_steps=6, verbose=False)
    answer, steps, reason = agent.run("算一下 (12+8)*3/4 并查订单 A1001")
    results.append(check_that(
        "多步任务跑通，stop_reason == final_answer", reason == "final_answer", f"实际 {reason}"))
    results.append(check_that(
        "循环执行了 3 圈（两次工具 + 一次作答）", len(steps) == 3, f"实际 {len(steps)} 圈"))
    results.append(check_that(
        "第一次工具调用被正确执行", "15" in steps[0].observation, steps[0].observation[:40]))
    results.append(check_that(
        "最终答案包含两部分结果", "15" in answer and "A1001" in answer, answer[:50]))

    # --- 验收 2：max_steps 保护生效 ---
    a2 = MiniAgent(llm=AlwaysToolLLM(), tools=_demo_tools(), max_steps=3, verbose=False)
    _, steps2, reason2 = a2.run("随便问")
    results.append(check_that(
        "模型卡住时 max_steps 兜底停机", reason2 == "max_steps" and len(steps2) == 3,
        f"reason={reason2}, steps={len(steps2)}"))

    # --- 验收 3：工具报错不崩，变成 observation 回灌 ---
    a3 = MiniAgent(llm=ScriptedLLM([
        'Action: lookup_order(order_id="ZZZ999")\n'
        '<tool_call>{"name": "lookup_order", "args": {"order_id": "ZZZ999"}}</tool_call>',
        'Final Answer: 没查到。',
    ]), tools=_demo_tools(), max_steps=3, verbose=False)
    _, steps3, _ = a3.run("查订单 ZZZ999")
    results.append(check_that(
        "工具报错不抛异常，转为可读 observation",
        len(steps3) >= 1 and "错误" in steps3[0].observation, steps3[0].observation[:40]))

    # --- 验收 4：不存在的工具会给出可用清单（幻觉工具纠正） ---
    a4 = MiniAgent(llm=ScriptedLLM([
        'Action: search_google(q="x")\n'
        '<tool_call>{"name": "search_google", "args": {"q": "x"}}</tool_call>',
        'Final Answer: 我换个工具。',
    ]), tools=_demo_tools(), max_steps=3, verbose=False)
    _, steps4, reason4 = a4.run("搜索一下")
    results.append(check_that(
        "幻觉工具被纠正（提示可用工具清单）",
        "不存在" in steps4[0].observation and "calc" in steps4[0].observation,
        steps4[0].observation[:50]))
    results.append(check_that(
        "纠正后模型仍能收尾", reason4 == "final_answer", reason4))

    # --- 验收 5：历史列表随循环增长（记忆的本质） ---
    llm = ScriptedLLM([
        'Action: calc(expr="6*7")\n<tool_call>{"name": "calc", "args": {"expr": "6*7"}}</tool_call>',
        'Final Answer: 42',
    ])
    MiniAgent(llm=llm, tools=_demo_tools(), max_steps=4, verbose=False).run("计算 6*7")
    sizes = [len(c) for c in llm.calls]
    results.append(check_that(
        "历史列表逐圈增长（模型靠重发历史'记忆'）",
        len(sizes) == 2 and sizes[1] > sizes[0], f"消息数序列 {sizes}"))

    # --- 验收 6：格式崩坏时不崩，且能被 max_steps 拦住 ---
    a6 = MiniAgent(llm=ScriptedLLM(["我觉得是 15 吧"], repeat_last=True),
                   tools=_demo_tools(), max_steps=2, verbose=False)
    _, steps6, reason6 = a6.run("算一下")
    results.append(check_that(
        "输出无法解析时不崩溃", len(steps6) == 2, f"跑了 {len(steps6)} 圈"))
    results.append(check_that(
        "解析失败最终被停机保护拦截", reason6 == "max_steps", reason6))

    # --- 验收 7：框架版 Agent 与手写版行为一致 ---
    from core import Agent
    from core.mock_llm import RuleBasedLLM

    res = Agent(llm=RuleBasedLLM(), max_steps=6, verbose=False).run("计算 (12+8)*3/4")
    results.append(check_that(
        "框架版 Agent 同样得到 final_answer",
        res.stop_reason == "final_answer" and "15" in res.answer,
        f"{res.stop_reason} / {res.answer[:40]}"))
    results.append(check_that(
        "框架版提供完整轨迹（StepRecord）", len(res.steps) >= 1, f"{len(res.steps)} 步"))

    return results


# ===========================================================================
# 入口
# ===========================================================================

SECTIONS = {
    "1": ("没有循环的世界", demo_no_loop),
    "2": ("真跑一次最小循环", demo_run),
    "3": ("messages 如何增长", demo_message_growth),
    "4": ("四道停机保险", demo_stop_conditions),
    "5": ("对比框架版", demo_compare_framework),
    "6": ("一句话本质", demo_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 01 章 · 最小 Agent 循环")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--real", action="store_true", help="使用真实模型（需配置 API Key）")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 01 章 · 最小 Agent 循环")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 01 章", run_checks()) else 1

    banner("第 01 章 · 最小 Agent 循环",
           "目标：从零手写一个 60 行的 Agent，看清它和'一次问答'的差别")

    if args.real:
        from core.real_llm import get_llm
        llm, desc = get_llm(prefer_real=True)
        note(f"模型：{desc}")
        if "真实" not in desc:
            warn("没检测到 API Key，本节仍用脚本化 Mock 模型演示（教学效果完全一致）。")

    chosen = [args.section] if args.section else sorted(SECTIONS)
    for key in chosen:
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 01 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
