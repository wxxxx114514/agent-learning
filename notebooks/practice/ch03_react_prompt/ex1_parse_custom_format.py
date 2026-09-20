r"""第 03 章 · 练习 1 / 5 · 给解析器加一种新格式：TOOL: name | ARGS: {...}

【要做什么】
  现在解析器不支持 `TOOL: calc | ARGS: {"expr":"1+1"}` 这种自定义分隔符格式。
  自己写一个正则，把它也解析出来。

  思考：应该加在分级降级的哪一级？为什么？

【已经给你了】
  · CUSTOM_SAMPLE / CUSTOM_MULTI / CUSTOM_BROKEN
        三条样例输出，直接拿来测（一条正常、一条多调用、一条写崩）
  · parse_output(text)       课程自带的分级降级解析器 —— 用它做「加之前」的对照
  · parse_tool_calls(text)   只要工具调用的便捷函数
  · ToolCall(name, args)     你的解析结果要装成这个类型（来自 core.message）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch03_react_prompt\ex1_parse_custom_format.py
  3. 验收本章：py scripts\run_all_checks.py 03
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json       # noqa: E402
import re         # noqa: E402
from ast import literal_eval  # noqa: E402

from core.message import ToolCall      # noqa: E402
from core.parser import parse_output   # noqa: E402

ROOT = Path(__file__).resolve().parents[3]

# 三条样例：分别是「一条正常」「一次回复里两条」「参数写崩了」
CUSTOM_SAMPLE = 'TOOL: calc | ARGS: {"expr": "1+1"}'

CUSTOM_MULTI = (
    "好的，我分两步做。\n"
    'TOOL: lookup_order | ARGS: {"order_id": "A1001"}\n'
    'TOOL: draft_reply | ARGS: {"order_id": "A1001", "kind": "shipped"}\n'
)

CUSTOM_BROKEN = 'TOOL: calc | ARGS: {expr: 1+1}'          # 键没加引号，不是合法 JSON

# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

# TODO ① ── 写出能匹配下面这种写法的正则，要求：
#             group(1) = 工具名        group(2) = ARGS 后面那段（连花括号一起）
#
#             TOOL: calc | ARGS: {"expr": "1+1"}
#
#           提示：`TOOL\s*:\s*(\w+)` 匹配工具名；`ARGS\s*:\s*(\{.*?\})` 匹配参数段。
#           你要自己想清楚两件事：
#             · `.` 要不要跨行（re.S）？—— 想想模型把两条调用写在不同行时会发生什么
#             · `.*?` 和 `.*` 差在哪？—— 想想一条回复里出现**两个** ARGS 时会怎样
CUSTOM_RE = None          # ← 把它换成 re.compile(...)


def parse_custom_format(text: str) -> list[ToolCall]:
    """把 `TOOL: name | ARGS: {...}` 解析成 ToolCall 列表。

    前后都写好了（查重、循环、返回值），你只写中间那几行。
    """
    if CUSTOM_RE is None:
        raise NotImplementedError("练习 1 · TODO ①  CUSTOM_RE 还没写（现在还是 None）")

    calls: list[ToolCall] = []
    for m in CUSTOM_RE.finditer(text or ""):
        name, raw = m.group(1), m.group(2)

        # TODO ② ── 把 raw 这段文本变成 dict，赋值给 args
        #   要求：先按标准 JSON 解析；失败时再救一次单引号写法（{'expr': '1+1'}）
        #   提示：json.loads(raw)  →  失败就 literal_eval(raw)  →  再失败就跳过这一条
        #        （解析不出来的调用，宁可丢掉也不要塞半个坏参数进去）
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 1 · TODO ②  ARGS 那段的 JSON 解析")
        # ↑↑↑ 你的答案 ↑↑↑

        calls.append(ToolCall(name=name, args=args))
    return calls


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        # ① 加之前：课程自带的解析器认得它吗？
        before = parse_output(CUSTOM_SAMPLE)
        report.append("【加之前】core.parser.parse_output 对这条自定义格式的处理：")
        report.append(f"    解析出的工具调用 : {[c.signature() for c in before.tool_calls]}   <- 空")
        report.append(f"    退化成最终答案   : {before.answer!r}")
        report.append(f"    解析错误         : {before.errors or '（没有报错！）'}")
        report.append("    ★ 注意：它既没报错、也没解析出调用，而是把整行当成了答案 ——")
        report.append("      这正是第 ⑤ 节讲的「静默错误」。")

        # ② 你写的解析器
        one = parse_custom_format(CUSTOM_SAMPLE)
        multi = parse_custom_format(CUSTOM_MULTI)
        broken = parse_custom_format(CUSTOM_BROKEN)

        if [c.name for c in one] != ["calc"] or one[0].args != {"expr": "1+1"}:
            raise AssertionError(f"单条样例解析结果不对：{[(c.name, c.args) for c in one]}")
        if [c.name for c in multi] != ["lookup_order", "draft_reply"]:
            raise AssertionError(
                f"一次回复里应该有两条调用，实际拿到 {[c.name for c in multi]}"
                "（想想是不是 `.*` 太贪心，或者 `.` 没跨行）")
        if multi[1].args != {"order_id": "A1001", "kind": "shipped"}:
            raise AssertionError(f"第二条调用的参数不对：{multi[1].args}")
        if broken:
            raise AssertionError(f"写崩的那条不该解析出调用，实际拿到 {broken}")

        report.append("")
        report.append("【加之后】你的 parse_custom_format：")
        report.append(f"    单条    : {[c.signature() for c in one]}")
        report.append(f"    两条    : {[c.signature() for c in multi]}")
        report.append(f"    写崩的  : {[c.signature() for c in broken]}   <- 空，正确地拒绝了")
        report.append("")
        report.append("★ 分级的原则：越靠前 = 模型越可能专门学过 = 越可靠。")
        report.append("  这种自定义分隔符格式比 `Action: name(...)` 更不规范，")
        report.append("  所以它应该排在 Action 那一级**之后**，做成第 6 级兜底。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    for line in report:
        print(line)
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
