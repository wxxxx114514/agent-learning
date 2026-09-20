r"""第 01 章 · 练习 3 / 5 · 加一道「总耗时」护栏

【要做什么】
  加一道「总耗时」护栏。

  除了限制步数，再限制整轮任务的总耗时（比如 0.5 秒）。
  超时后停机，并在答案里说明「因超时未完成，已完成的部分是……」。

【已经给你了】
  · `MiniAgent` / `Step`      —— 第 01 章的 Agent 本体
  · `_extract_tool_call`      —— 解析函数
  · `_demo_tools()`           —— 现成工具表
  · `SlowLLM`                 —— 每次调用都睡 0.2 秒，专门把总耗时撑过阈值
  · `TimeoutAgent.run()` 骨架  —— 计时起点 `t0` 已经给你了，只空超时判断

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch01_agent_loop\ex3_time_budget.py
  3. 验收本章：py scripts\run_all_checks.py 01
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import time                                                   # noqa: E402

from core.llm import LLM, LLMResponse                         # noqa: E402
from core.message import Message                              # noqa: E402
from stages.stage01_agent_loop.demo import (                  # noqa: E402
    MiniAgent,
    Step,
    _demo_tools,
    _extract_tool_call,
)

TOOLS = _demo_tools()          # ★ 只有 calc / lookup_order，假模型必须调这两个之一


class SlowLLM(LLM):
    """每次调用都睡 0.2 秒 —— 专门用来把总耗时撑过阈值。"""

    name = "slow"

    def _complete(self, messages, **kwargs) -> LLMResponse:
        time.sleep(0.2)
        return LLMResponse(
            text='Thought: 慢慢来。\n'
                 '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>'
        )


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class TimeoutAgent(MiniAgent):
    """除了 max_steps，再加一道「总耗时」护栏。"""

    budget_s = 0.5

    def run(self, question: str):
        messages = [Message.system("你可以调用工具。"), Message.user(question)]
        steps: list[Step] = []
        t0 = time.perf_counter()               # ← 计时起点，已经给你了

        for i in range(1, self.max_steps + 1):

            # TODO ── 写超时判断：超了就带着「已完成的部分」停机
            #   提示：if time.perf_counter() - t0 > self.budget_s:
            #             return (f"因超时未完成，已完成 {len(steps)} 圈", steps, "timeout")
            #   注意：判断写在**每圈开头**（跑之前先看还剩多少预算）
            # ↓↓↓ 在下面写你的答案 ↓↓↓

            # ↑↑↑ 你的答案 ↑↑↑

            step = Step(index=i)
            steps.append(step)
            reply = self.llm.complete(messages).text
            call = _extract_tool_call(reply)
            if call is None:
                break
            name, args = call
            messages.append(Message.assistant(reply))
            step.observation = self._execute(name, args)
            messages.append(Message.tool_result(name, step.observation))

        return "正常结束", steps, "final_answer"


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 01 章 · 练习 3 · 总耗时护栏")
    print("=" * 68)
    print(f"\n  模型       : SlowLLM（每次调用睡 0.2 秒）")
    print(f"  耗时预算   : {TimeoutAgent.budget_s} 秒")
    print(f"  圈数上限   : 8 圈（如果只靠它，要跑 1.6 秒）")

    # 先探一下你写没写：没写就直接告诉你，不真跑 1.6 秒
    import inspect
    body = "".join(inspect.getsourcelines(TimeoutAgent.run)[0])
    code_only = "\n".join(ln.split("#")[0] for ln in body.splitlines())
    if not any("if" in ln and ("perf_counter()" in ln or "elapsed(" in ln)
               for ln in code_only.splitlines()):
        print("\n⬜ 还没写：练习 3 · TODO  超时判断还没有写")
        return 0

    t0 = time.perf_counter()
    try:
        agent = TimeoutAgent(llm=SlowLLM(), tools=TOOLS, max_steps=8, verbose=False)
        answer, steps, reason = agent.run("随便问点什么")
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    cost = time.perf_counter() - t0

    print(f"\n  停机原因 = {reason}")
    print(f"  答案     = {answer}")
    print(f"  跑了     = {len(steps)} 圈")
    print(f"  实际耗时 = {cost:.2f} 秒")

    if reason != "timeout":
        print(f"\n❌ 练习 3 · TODO 还没写超时判断")
        print(f"   （停机原因 = {reason}，期望 timeout）")
        print("   检查点：`time.perf_counter() - t0 > self.budget_s` 写在 for 循环体的第一行")
        return 1
    if "超时" not in str(answer):
        print("\n❌ 停机了，但答案里没有说明「因超时未完成」——")
        print("   用户看到空答案会以为任务成功了，这是最糟的降级方式。")
        return 1

    print("\n✅ 跑通了")
    print("   ★ 体感：宁可给部分结果 + 说明，也不能无限等；")
    print("     只限步数不够 —— 慢模型 8 圈能拖十几秒，用户早就关页面了。")
    print("     这是第 13 章「超时降级」的雏形。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
