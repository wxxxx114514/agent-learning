r"""第 00 章 · 练习 3 / 4 · 加一条总耗时保护

【要做什么】
  加一条总耗时保护。

  在循环里记录开始时间，如果超过 0.5 秒就停机，并说明因超时未完成。

【已经给你了】
  · `SlowLLM`              —— 每次调用都睡 0.2 秒的假模型（全局变量 `LLM` 就是它）
  · `FastLLM`              —— 不睡的对照模型（`LLM = FastLLM()` 可切换）
  · `BUDGET_S = 0.5`       —— 总耗时上限，单位秒
  · `MAX_ROUNDS = 8`       —— 圈数上限（另一道保险）
  · `elapsed(t0)`          —— 返回从 t0 到现在过了多少秒
  · 循环骨架（历史 / 发模型 / 解析 / 执行 / 追加）都已经写好

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch00_setup\ex3_time_budget.py
  3. 验收本章：py scripts\run_all_checks.py 00
     （第 00 章 没有 stages/stage00_* 目录，这个脚本会提示它，不影响你做题）
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                                                   # noqa: E402
import re                                                     # noqa: E402
import time                                                   # noqa: E402

from core.llm import LLM, LLMResponse                         # noqa: E402
from core.message import Message                              # noqa: E402

CALL_RE = re.compile(r"<call>(\{.*?\})</call>", re.S)
JSON_RE = re.compile(r"\{.*\}", re.S)

BUDGET_S = 0.5      # ★ 总耗时上限：整轮任务最多花这么久
MAX_ROUNDS = 8      # 圈数上限（另一道保险，两道都有才安全）


def parse_tool_call(text: str):
    """解析工具调用；解析不出来返回 None。（练习 2 已经写过，这里直接给你）"""
    m = CALL_RE.search(text)
    if not m:
        return None
    inner = JSON_RE.search(m.group(1))
    if not inner:
        return None
    try:
        obj = json.loads(inner.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "name" not in obj:
        return None
    return obj["name"], obj.get("args", {})


def calc(expr: str) -> str:
    """一个足够用的计算工具。"""
    import ast
    BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.BinOp):
            return BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp):
            return -ev(n.operand)
        raise ValueError(f"不支持的语法: {type(n).__name__}")

    v = ev(ast.parse(expr, mode="eval"))
    return f"{expr} = {int(v) if isinstance(v, float) and v.is_integer() else v}"


TOOLS = {"calc": calc}


class SlowLLM(LLM):
    """每次调用都睡 0.2 秒 —— 专门用来把总耗时撑过阈值。"""

    name = "slow"

    def _complete(self, messages, **kwargs) -> LLMResponse:
        time.sleep(0.2)
        return LLMResponse(
            text='Thought: 慢慢来。\n'
                 '<call>{"name": "calc", "args": {"expr": "1+1"}}</call>'
        )


class FastLLM(LLM):
    """不睡的对照模型：同样卡在工具调用上，但跑得飞快。"""

    name = "fast"

    def _complete(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(
            text='Thought: 很快。\n'
                 '<call>{"name": "calc", "args": {"expr": "1+1"}}</call>'
        )


LLM = SlowLLM()          # ← 想看"不超时"的情况：改成 LLM = FastLLM()


def elapsed(t0: float) -> float:
    """从 t0 到现在过了多少秒。"""
    return time.perf_counter() - t0


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def run_with_budget(question: str):
    """跑一轮闭环，并加一条「总耗时」护栏。

    返回 (答案, 圈数, 停机原因)；停机原因是 "timeout" 或 "max_steps"。

    你只需要写**每圈开头的那段超时判断**（其余骨架已经写好）：
        if elapsed(t0) > BUDGET_S:
            return (f"因超时未完成，已完成 {len(steps)} 圈", len(steps), "timeout")

    注意：`t0 = time.perf_counter()` 已经在循环外面给你了；
    返回的答案里要说明**因超时未完成 + 已经做完了几圈** ——
    宁可给部分结果加说明，也不能让用户无限等。
    """
    messages = [
        Message.system('需要工具时输出：<call>{"name": "工具名", "args": {...}}</call>'),
        Message.user(question),
    ]
    steps: list[str] = []
    t0 = time.perf_counter()                   # ← 计时起点，已经给你了

    for _ in range(MAX_ROUNDS):

        # TODO ── 就在这里写超时判断（超了就 return 部分结果 + 说明）
        #   提示：if elapsed(t0) > BUDGET_S:
        #             return (f"因超时未完成，已完成 {len(steps)} 圈", len(steps), "timeout")
        #   注意：判断写在**每圈开头**（跑之前先看还剩多少预算）
        # ↓↓↓ 在下面写你的答案 ↓↓↓

        # ↑↑↑ 你的答案 ↑↑↑

        reply = LLM.complete(messages).text
        call = parse_tool_call(reply)
        if call is None:
            return ("模型输出没法解析", len(steps), "parse_failed")
        name, args = call
        messages.append(Message.assistant(reply))
        try:
            result = TOOLS[name](**args)
        except Exception as exc:
            result = f"错误：{type(exc).__name__}: {exc}"
        messages.append(Message.tool_result(name, result))
        steps.append(f"{name}({args}) -> {result}")

    return (f"跑满 {MAX_ROUNDS} 圈了（模型一直在重复同一个动作）",
            len(steps), "max_steps")


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 00 章 · 练习 3 · 总耗时护栏")
    print("=" * 68)
    print(f"\n  模型       : {LLM.name}（每次调用睡 0.2 秒）")
    print(f"  总耗时上限 : {BUDGET_S} 秒")
    print(f"  圈数上限   : {MAX_ROUNDS} 圈\n")

    # 先探一下你写没写：没写就直接告诉你，不真跑（省得白等 1.6 秒）。
    # 判据：函数体里真的有一个 if，且它碰到了计时（注释和 docstring 里的提示不算）。
    import ast as _ast
    import inspect
    tree = _ast.parse(inspect.getsource(run_with_budget).lstrip())
    fn = tree.body[0]
    elapsed_names = {"perf_counter", "elapsed", "time"}
    has_budget_if = False
    for node in _ast.walk(fn):
        if not isinstance(node, _ast.If):
            continue
        seg = _ast.get_source_segment(inspect.getsource(run_with_budget), node.test) or ""
        if any(name in seg for name in elapsed_names):
            has_budget_if = True
            break
    if not has_budget_if:
        print("⬜ 还没写：练习 3 · TODO  run_with_budget 里的超时判断还没有写")
        return 0

    t0 = time.perf_counter()
    try:
        answer, rounds, reason = run_with_budget("帮我算点东西")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    cost = time.perf_counter() - t0

    print(f"  停机原因 : {reason}")
    print(f"  答案     : {answer}")
    print(f"  跑了     : {rounds} 圈")
    print(f"  实际耗时 : {cost:.2f} 秒")

    if reason == "timeout":
        print("\n✅ 跑通了")
        print("   ★ 体感：宁可给部分结果 + 说明，也不能无限等 ——")
        print("     这正是第 13 章「超时降级」的雏形。")
        return 0
    print(f"\n❌ 期望停机原因是 timeout，现在是 {reason}")
    print("   检查点：判断要写在**每圈开头**（跑之前先看还剩多少预算），")
    print("          比较的是 elapsed(t0) 和 BUDGET_S。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
