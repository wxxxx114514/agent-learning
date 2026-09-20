r"""第 03 章 · 练习 4 / 5 · 给提示词加「思维预算」（Thought 最多 N 字）

【要做什么】
  现在的格式契约只要求 Thought 简短，但没有**强制**。
  试试明确限制长度（比如「Thought 最多 30 字」），
  观察它对解析成功率和 token 消耗的影响。

【已经给你了】
  · BASE        PromptBuilder 生成的系统提示词（没有长度约束）
  · BudgetLLM   行为固定的假模型：**只认一条规则** ——
                提示词里出现 `Thought 最多 N 字` 这个句式时它才守规矩。
                没有这条规则：它一思考就停不下来，把工具调用写进自然语言里。
                有这条规则：短 Thought + 规范的 Action + <tool_call>。
  · measure(system, runs)   跑 runs 次并统计三项指标的骨架（循环和求平均都写好了）
  · estimate_tokens(text) / parse_output(text, known_tools=...)   官方量尺与解析器

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch03_react_prompt\ex4_thought_budget.py
  3. 验收本章：py scripts\run_all_checks.py 03
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import re                                  # noqa: E402

from core.llm import LLM, LLMResponse, estimate_tokens   # noqa: E402
from core.message import Message                          # noqa: E402
from core.parser import parse_output                      # noqa: E402
from core.prompts import PromptBuilder                    # noqa: E402
from core.tool import build_default_registry              # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
REG = build_default_registry(ROOT)

BASE = PromptBuilder(
    style="react",
    persona="你是「小助手」，一个严谨的电商客服助理。",
    rules=["涉及金额计算一律用 calc，禁止心算。"],
).build_system(REG)

QUESTION = "计算 (12+8)*3/4"
RUNS = 3
MAX_THOUGHT_CHARS = 30        # ← 题目里的「比如 30 字」

# 模型认得的句式（你的 TODO ① 必须让它匹配上，否则模型不会理你）
BUDGET_RE = re.compile(r"Thought\s*最多\s*(\d+)\s*字")

LONG_THOUGHT = (
    "用户给的是一个包含括号和四则运算的表达式 (12+8)*3/4。我需要先判断运算优先级："
    "括号里的 12+8 先算得到 20，然后 20*3 得到 60，最后 60/4 得到 15。"
    "不过为了严谨，我应该调用 calc 工具来验证这个结果，因为心算长表达式很容易出错。"
)
SHORT_THOUGHT = "先看运算优先级，用 calc 工具算，不心算。"


class BudgetLLM(LLM):
    """只认「思维预算」这一条规则的假模型 —— 受控实验的关键。"""

    name = "budget"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        system = next((m.content for m in messages if m.role == "system"), "")
        if BUDGET_RE.search(system):
            # 有预算：短 Thought + 规范的三段式输出
            text = (f"Thought: {SHORT_THOUGHT}\n"
                    f'Action: calc(expr="(12+8)*3/4")\n'
                    f'<tool_call>{{"name": "calc", "args": {{"expr": "(12+8)*3/4"}}}}</tool_call>')
        else:
            # 没有预算：一路想下去，把工具调用写成了一句自然语言（没有 Action 行）
            text = (f"Thought: {LONG_THOUGHT}\n"
                    f"我打算用 calc 工具来算 (12+8)*3/4，这样更可靠。")
        return LLMResponse(text=text, model=self.name)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def add_thought_budget(system: str, max_chars: int = MAX_THOUGHT_CHARS) -> str:
    """在系统提示词里补一条硬约束：Thought 最多 max_chars 字。

    参数 system  ：原来的系统提示词（BASE）
         max_chars：Thought 的字数上限
    返回        ：补好规则的新系统提示词（不要改原字符串，拼一份新的返回）

    TODO ① ── 写一行拼接就够。要求写出来的句式能被 BUDGET_RE 匹配到，
              也就是必须出现 `Thought 最多 30 字` 这样的字样。
              提示：顺手说清违反的后果（比如「超了就是浪费钱」），这比单纯限制更有效。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO ①  add_thought_budget：把长度规则拼进提示词")
    # ↑↑↑ 你的答案 ↑↑↑


def measure(system: str, runs: int = RUNS) -> dict:
    """跑 runs 次，返回三项指标的平均值：Thought 字数 / completion token / 可解析率。

    前后都写好了（循环、累加后的求平均、返回结构），你只写中间那三行累加。
    """
    stats = {"thought_chars": 0, "tokens": 0, "parsable": 0}
    for _ in range(runs):
        # 每次都用全新的模型实例 —— 保证可复现
        reply = BudgetLLM().complete([Message.system(system), Message.user(QUESTION)]).text

        # TODO ② ── 累加三项指标
        #   ① stats["thought_chars"] += len(parse_output(reply).thought)
        #   ② stats["tokens"]        += estimate_tokens(reply)
        #   ③ 能解析出工具调用（parse_output(reply, known_tools=REG.names()).has_tool_call）
        #      就把 stats["parsable"] 加 1
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 4 · TODO ②  measure：累加三项指标")
        # ↑↑↑ 你的答案 ↑↑↑

    return {
        "thought_chars": stats["thought_chars"] / runs,
        "tokens": stats["tokens"] / runs,
        "parsable": stats["parsable"] / runs,
    }


# TODO ③ ── 纯思考题：写下你的结论
#   提示：Thought 变短之后，token 降了多少？可解析率达到 100% 了吗？
#         再想一步：如果限制得太狠（比如「最多 5 字」），模型会不会反而想不清楚？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        budgeted_system = add_thought_budget(BASE, MAX_THOUGHT_CHARS)
        if not isinstance(budgeted_system, str) or not BUDGET_RE.search(budgeted_system):
            raise AssertionError(
                "TODO ① 拼出来的提示词里找不到「Thought 最多 N 字」这个句式，"
                "模型认不出来（BUDGET_RE 匹配不上）")
        if budgeted_system == BASE:
            raise AssertionError("TODO ① 要返回补好规则的新提示词，不能原样返回 BASE")
        before = measure(BASE)
        after = measure(budgeted_system)

        if before["parsable"] != 0.0:
            raise AssertionError(f"没有预算的基线应该解析不出来，实测 {before['parsable']:.0%}")
        if after["parsable"] != 1.0:
            raise AssertionError(f"加了预算之后应该 100% 可解析，实测 {after['parsable']:.0%}")
        if after["thought_chars"] >= before["thought_chars"]:
            raise AssertionError("加了长度上限之后 Thought 反而没变短，检查 TODO ② 的累加")

        report.append(f"同一段提示词，各跑 {RUNS} 次（只多了一行「思维预算」）：")
        report.append("")
        for label, m in (("基线（没有长度约束）", before),
                         (f"加了「Thought 最多 {MAX_THOUGHT_CHARS} 字」", after)):
            report.append(f"    {label}")
            report.append(f"        Thought 平均 {m['thought_chars']:>4.0f} 字"
                          f" | 平均 {m['tokens']:>4.0f} token"
                          f" | 可解析率 {m['parsable']:>4.0%}")
        report.append("")
        saved = before["tokens"] - after["tokens"]
        report.append(f"    Thought 从 {before['thought_chars']:.0f} 字压到 "
                      f"{after['thought_chars']:.0f} 字，单次省下约 {saved:.0f} token")
        report.append(f"    可解析率：{before['parsable']:.0%} -> {after['parsable']:.0%}")
        report.append("")
        report.append("★ 一个反直觉但重要的结论：**限制 Thought 长度不只省钱，它还提高可靠性。**")
        report.append("  因为「想得太多」的模型会把工具调用写进自然语言里 ——")
        report.append("  那时候你不是多花了钱，而是彻底解析不出来（第 ⑤ 节的静默错误）。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 4 · TODO ③  写下你的结论")
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
