r"""第 00 章 · 练习 1 / 4 · 让模型一次申请两个工具调用

【要做什么】
  让 `CalcLLM` 一次申请两个工具调用。

  现在的解析器只处理一个 `<call>`。改成用 `CALL_RE.findall(text)` 找出全部调用，
  逐个执行，并把每个结果都追加成一条 `tool_result` 消息。

  验证：让模型一次申请算两个表达式。

【已经给你了】
  · `calc(expr)`              —— 会算数的工具（ast 白名单，不用 eval）
  · `TOOLS`                   —— 工具表：{"calc": calc}
  · `CALL_RE` / `JSON_RE`     —— 从模型输出里抠出调用的两条正则
  · `parse_one_call(fragment)`—— 把一段 JSON 文本变成 (工具名, 参数字典)
  · `TwoCallLLM`              —— 一次申请算两个表达式的假模型（全局变量 `LLM` 就是它）
  · `SYSTEM`                  —— 已经写好的系统提示词
  · `ask_model(messages)`     —— 把整段历史发给模型，返回它输出的一段文本

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch00_setup\ex1_multi_calls.py
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

from core.llm import LLM, LLMResponse                         # noqa: E402
from core.message import Message                              # noqa: E402


def calc(expr: str) -> str:
    """计算数学表达式。参数 expr：表达式字符串。返回：结果字符串。"""
    BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp):
            return -ev(node.operand)
        raise ValueError(f"不支持的语法: {type(node).__name__}")

    value = ev(ast.parse(expr, mode="eval"))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{expr} = {value}"


TOOLS = {"calc": calc}          # 工具表：名字 -> 函数

SYSTEM = (
    "你可以调用这些工具：" + ", ".join(TOOLS) + "\n"
    '需要工具时输出：<call>{"name": "工具名", "args": {...}}</call>\n'
    "可以回答时输出：Final Answer: ...\n"
    "如果一次要做两件事，可以连着写两个 <call>。"
)

CALL_RE = re.compile(r"<call>(\{.*?\})</call>", re.S)   # re.S：让 . 也能匹配换行
JSON_RE = re.compile(r"\{.*\}", re.S)


def parse_one_call(fragment: str):
    """把一段抓出来的 JSON 文本变成 (工具名, 参数字典)；解析不了返回 None。"""
    m = JSON_RE.search(fragment)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "name" not in obj:
        return None
    return obj["name"], obj.get("args", {})


class TwoCallLLM(LLM):
    """假模型：第一拍一次申请算两个表达式，第二拍看到两个结果后给答案。"""

    name = "two-call"

    def _complete(self, messages, **kwargs) -> LLMResponse:
        if not any(m.role == "tool" for m in messages):
            return LLMResponse(text=(
                "Thought: 两个式子一起算，省一轮。\n"
                '<call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</call>\n'
                '<call>{"name": "calc", "args": {"expr": "6*7"}}</call>'
            ))
        results = [m.content for m in messages if m.role == "tool"]
        return LLMResponse(text="Final Answer: " + "；".join(results))


LLM = TwoCallLLM()               # ← 想换模型：改这一行就行


def ask_model(messages) -> str:
    """把整段历史发给模型，返回它输出的那段文本。"""
    return LLM.complete(messages).text


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def run_two_calls(question: str) -> list[Message]:
    """跑一轮闭环，把「模型一次申请两个调用」全部执行完。

    要求：
      1. 历史列表从 [Message.system(SYSTEM), Message.user(question)] 开始
      2. 调用 ask_model(messages) 拿到模型的输出
      3. 用 CALL_RE.findall(text) 找出**全部**调用（不是 search 只找一个）
      4. 每个调用：解析 -> TOOLS[名字](**参数) 执行 -> 追加一条 tool_result
      5. 把模型的输出本身也追加成一条 assistant 消息
      6. 返回最后的历史列表

    返回 messages 而不是打印，是为了让下面的验证能检查里面到底有几条 tool_result。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO  run_two_calls 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    try:
        messages = run_two_calls("帮我算 (12+8)*3/4 和 6*7")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    tool_msgs = [m for m in messages if m.role == "tool"]
    print("=" * 68)
    print("  第 00 章 · 练习 1 · 一次申请两个工具调用")
    print("=" * 68)
    print("\n  历史里的消息：")
    for m in messages:
        body = m.content.replace("\n", " ")[:58]
        print(f"    [{m.role:<9}] {body}")
    print(f"\n  tool_result 条数 = {len(tool_msgs)}   ← 期望 2")
    for m in tool_msgs:
        print(f"    {m.name}(…) -> {m.content}")
    print(f"\n  最后一条 = {messages[-1].content[:58]}")

    if len(tool_msgs) != 2:
        print(f"\n❌ 两条调用没有都被执行（现在只有 {len(tool_msgs)} 条 tool_result）")
        print("   检查点：findall 返回的是**字符串列表**，不是 Match 对象；")
        print("          循环里对每个 fragment 都要调用 parse_one_call。")
        return 1
    print("\n✅ 跑通了")
    print("   ★ 体感：一个回合里可以申请多个动作 —— 这正是第 04 章要展开的")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
