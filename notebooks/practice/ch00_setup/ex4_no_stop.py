r"""第 00 章 · 练习 4 / 4 · 去掉 `Final Answer:` 的判断，观察后果

【要做什么】
  去掉 `Final Answer:` 的判断，观察后果。

  把判断 `Final Answer:` 的那一段删掉，改成永远尝试解析工具调用。

  跑一次，看它会不会停下来。

【已经给你了】
  · `ChattyLLM`              —— 假模型：第 1 拍申请调 calc，第 2 拍已经给出 Final Answer，
                                第 3 拍以后重复第 2 拍（脚本模型的默认行为）
  · `MODEL_CALLS`            —— 只统计模型被调用了几次（用来数圈数）
  · `parse_tool_call(text)`  —— 解析器（练习 2 已经写过，直接给你）
  · `TOOLS`                   —— 工具表：{"calc": calc}
  · 循环的**开始**和**结束**都已经写好，只空中间

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch00_setup\ex4_no_stop.py
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
import ast                                                    # noqa: E402
import json                                                   # noqa: E402
import re                                                     # noqa: E402

from core.message import Message                              # noqa: E402
from core.mock_llm import ScriptedLLM                         # noqa: E402
from core.tool import build_default_registry                  # noqa: E402

MAX_ROUNDS = 5      # ← 这就是原例子里 range(1, 6) 的上限

CALL_RE = re.compile(r"<call>(\{.*?\})</call>", re.S)
JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_tool_call(text: str):
    """解析工具调用；解析不出来返回 None。"""
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
    """计算数学表达式。"""
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

SCRIPT = [
    'Thought: 先算一下。\n<call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</call>',
    'Thought: 算出来了。\nFinal Answer: (12+8)*3/4 = 15',
]
LLM = ScriptedLLM(SCRIPT)        # 脚本用完后会重复最后一条
MODEL_CALLS = 0                  # 模型被调用了几次 = 循环跑了几圈


def ask_model(messages) -> str:
    """把历史发给模型，返回它输出的文本；顺便数一下调用次数。"""
    global MODEL_CALLS
    MODEL_CALLS += 1
    return LLM.complete(messages).text


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def naive_loop(question: str) -> dict:
    """**故意没有终止条件**的循环 —— 这就是这道题要观察的对象。

    要求（就是原文档第 ③ 节那段代码，只把 `Final Answer:` 的判断删掉）：
      1. 历史从 [Message.system("用 <call>{...}</call> 调工具"), Message.user(question)] 开始
      2. 循环 `for i in range(1, MAX_ROUNDS + 1):` —— 上限只在**最后**兜底
      3. 每圈：
           reply = ask_model(messages)
           messages.append(Message.assistant(reply))
           call = parse_tool_call(reply)
           if call is None:
               continue                     # 解析不出来就跳过这一圈
           name, args = call
           result = TOOLS[name](**args)
           messages.append(Message.tool_result(name, result))
         ★ 关键：**不要**判断 "Final Answer:"，永远只尝试解析工具调用
      4. 返回 {"messages": messages, "rounds": MAX_ROUNDS}

    ★ 为什么必须靠 range 的上限停下？这就是这道题要你亲身体会的事。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO  naive_loop 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 00 章 · 练习 4 · 循环为什么必须有个上限")
    print("=" * 68)
    print("\n  模型的剧本：")
    for i, line in enumerate(SCRIPT, 1):
        print(f"    第 {i} 拍 -> {line.replace(chr(10), ' | ')[:52]}")
    print("\n  注意第 2 拍：它明明已经说出 Final Answer 了。")

    try:
        out = naive_loop("帮我算 (12+8)*3/4")
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    messages = out["messages"]
    answered = [m for m in messages if m.role == "assistant" and "Final Answer:" in m.content]
    print(f"\n  循环跑了        : {out['rounds']} 圈（= range 的上限 {MAX_ROUNDS}）")
    print(f"  模型被调用      : {MODEL_CALLS} 次")
    print(f"  历史里的消息条数: {len(messages)}")
    print(f"  其中已给出答案的: {len(answered)} 条  ← 模型早就答完了，循环却没停")

    ok = MODEL_CALLS == MAX_ROUNDS and len(answered) >= 1 and len(messages) > 2
    if not ok:
        print("\n❌ 现象还没跑出来，检查两点：")
        print("   1. 每圈都要 ask_model(messages) 并 append 回复")
        print("   2. 循环里**不能**判断 Final Answer，只能解析工具调用")
        return 1

    print("\n✅ 跑通了")
    print("   ★ 观察到的后果：模型第 2 圈就说了 Final Answer，")
    print("     但没有终止条件，循环只好一路跑到 range 的上限。")
    print("     如果上限是 1000，它就烧 1000 次调用；没有上限，就是无限循环。")
    print("     —— 这就是 max_steps 为什么是必需品（第 01 章会讲四道停机保护）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
