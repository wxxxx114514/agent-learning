r"""第 01 章 · 练习 4 / 5 · 让工具报错信息「像写给模型看的」

【要做什么】
  让工具报错信息更像「写给模型看的」。

  现在 `call_tool` 在参数名写错时返回的是 Python 原始报错。
  改成包含三样：哪里错了 + 正确用法 + 可用替代。

  验证：故意传错参数名，看返回的字符串能不能照着改对。

【已经给你了】
  · `FriendlyAgent`           —— 已经包好 try/except，出错时调用你写的 `explain_error`
  · `TOOLS` / `_demo_tools()` —— 工具表（`calc` / `lookup_order`）
  · `SCRIPTED`                —— 一个剧本模型（`FriendlyAgent` 需要一个 llm 才能构造）
  · `show_error(name, args)`  —— 帮你把参数名写错，看返回了什么

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch01_agent_loop\ex4_friendly_error.py
  3. 验收本章：py scripts\run_all_checks.py 01
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import inspect                                                # noqa: E402

from core.mock_llm import ScriptedLLM                         # noqa: E402
from stages.stage01_agent_loop.demo import (                  # noqa: E402
    MiniAgent,
    _demo_tools,
)

TOOLS = _demo_tools()          # {'calc': …, 'lookup_order': …}
SCRIPTED = ScriptedLLM(['Thought: 我要算一下。\nFinal Answer: 20'])


class FriendlyAgent(MiniAgent):
    """工具报错时，把原始异常交给 explain_error 翻译一遍。"""

    def _execute(self, name: str, args: dict) -> str:
        try:
            return super()._execute(name, args)
        except TypeError:
            return explain_error(name, args)


def tool_params(name: str) -> list[str]:
    """拿到某个工具真正需要的参数名（内省函数签名）。"""
    return list(inspect.signature(TOOLS[name]).parameters)


def show_error(name: str, args: dict) -> str:
    """故意用错参数名调一次工具，返回智能体看到的报错文本。"""
    agent = FriendlyAgent(llm=SCRIPTED, tools=TOOLS, verbose=False)
    return str(agent._execute(name, args))


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def explain_error(name: str, args: dict) -> str:
    """TODO ── 把原始报错翻译成「模型能照着改对」的一段话。

    要包含三样：
      ① 哪里错了   —— 哪些参数名不存在（对照 inspect.signature(TOOLS[name])）
      ② 正确用法   —— 正确参数名 + 一个示例调用
      ③ 可用替代   —— list(TOOLS) 里的其他工具

    返回一个字符串即可。

    可以直接用的东西（都已经在上面给你了）：
      · tool_params(name)                -> 该工具的正确参数名列表
      · TOOLS[name](**{正确参数: 值})     -> 真的执行一次，拿到正确输出
      · list(TOOLS)                      -> 全部可用工具名

    对比一下哪个模型能照着改对：
      ❌ TypeError: calc() got an unexpected keyword argument 'expression'
      ✅ 参数名错了…… 正确用法：calc(expr="1+1")…… 其它可用工具：['lookup_order']
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO  explain_error 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 01 章 · 练习 4 · 报错信息写给模型看")
    print("=" * 68)

    print("\n  模型的原始报错（对比用，模型基本看不懂）：")
    try:
        TOOLS["calc"](**{"expression": "1+1"})
    except TypeError as exc:
        print(f"      TypeError: {exc}")

    try:
        out = explain_error("calc", {"expression": "1+1"})
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print("\n  你写的版本（返回给模型的内容）：")
    for line in str(out).splitlines():
        print("      " + line)
    print(f"\n  长度 = {len(str(out))} 字符")

    text = str(out)
    problems = []
    if "expr" not in text:
        problems.append("没告诉模型正确参数名是 expr")
    if "expression" not in text:
        problems.append("没指出错在哪里（模型给的是 expression）")
    if "calc" not in text:
        problems.append("没给出正确用法示例（例如 calc(expr=\"1+1\")）")
    if "lookup_order" not in text:
        problems.append("没给可用替代（list(TOOLS) 里的其它工具）")

    if problems:
        print("\n❌ 还缺东西：")
        for p in problems:
            print(f"      - {p}")
        return 1

    print("\n  换个工具、换个错参数名再试一次（说明不是你写死的字符串）：")
    out2 = str(explain_error("lookup_order", {"id": "A1001"}))
    for line in out2.splitlines()[:4]:
        print("      " + line)

    print("\n✅ 跑通了")
    print("   ★ 关键设计：失败信息不是写给人看的日志，而是**写给模型的下一条上下文**。")
    print("     第 02 章会把这件事系统化：校验在执行之前，报错带上正确用法。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
