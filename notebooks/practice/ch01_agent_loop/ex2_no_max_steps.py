r"""第 01 章 · 练习 2 / 5 · 去掉 `max_steps`，观察后果

【要做什么】
  去掉 `max_steps`，观察后果。

  把 `for i in range(1, self.max_steps + 1)` 改成 `while True`，
  用 `LoopingLLM` 跑一次。

  ⚠️ 记得先设个计数器保护自己（比如跑到 200 圈就 break）。

【已经给你了】
  · `MiniAgent` / `Step`      —— 第 01 章的 Agent 本体
  · `_extract_tool_call`      —— 从模型输出里取出工具调用的解析函数
  · `_demo_tools()`           —— 现成工具表
  · `loopy` (`LoopingLLM`)    —— 永远重复同一个动作，用来演示"停不下来"
  · `NoGuardAgent` 的完整 `run()` —— 只剩一两行保护给你写

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch01_agent_loop\ex2_no_max_steps.py
  3. 验收本章：py scripts\run_all_checks.py 01
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.message import Message                              # noqa: E402
from core.mock_llm import LoopingLLM, ScriptedLLM             # noqa: E402
from stages.stage01_agent_loop.demo import (                  # noqa: E402
    MiniAgent,
    Step,
    _demo_tools,
    _extract_tool_call,
)

TOOLS = _demo_tools()
# ★ action 必须用 TOOLS 里真实存在的工具（这里只有 calc / lookup_order）
loopy = LoopingLLM(action="calc", args={"expr": "1+1"})   # 重复同一个动作 —— 没有护栏就永远不停


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class NoGuardAgent(MiniAgent):
    """没有 max_steps 的版本 —— 故意危险，所以留了 HARD_LIMIT 兜底。"""

    HARD_LIMIT = 200

    def run(self, question: str):
        messages = [
            Message.system("你可以调用工具。需要工具时输出 Action: 工具名(参数)"),
            Message.user(question),
        ]
        steps: list[Step] = []

        i = 0
        while True:                            # ← 这就是「拿掉了 max_steps」
            i += 1
            step = Step(index=i)
            steps.append(step)

            reply = self.llm.complete(messages).text
            call = _extract_tool_call(reply)
            if call is None:
                break
            name, args = call
            step.action = f"{name}({args})"
            messages.append(Message.assistant(reply))
            step.observation = self._execute(name, args)
            messages.append(Message.tool_result(name, step.observation))

            # TODO ── 写一行「跑满 HARD_LIMIT 就 break」的保护
            #   提示：if i >= self.______: break
            # ↓↓↓ 在下面写你的答案 ↓↓↓

            # ↑↑↑ 你的答案 ↑↑↑
            break          # ← 写完保护后把这行删掉，否则现在只跑一圈

        return "（没有上限的话本来会跑更多圈）", steps, "loop"


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 01 章 · 练习 2 · 拿掉 max_steps 会怎样")
    print("=" * 68)

    # 先探一下你写没写：没写就直接告诉你，不真跑 200 圈
    import inspect
    body = "".join(inspect.getsourcelines(NoGuardAgent.run)[0])
    code_only = "\n".join(ln.split("#")[0] for ln in body.splitlines())
    if not any("if" in ln and "HARD_LIMIT" in ln for ln in code_only.splitlines()):
        print("\n⬜ 还没写：练习 2 · TODO  「跑满 HARD_LIMIT 就 break」的保护还没有写")
        print("   （写完后记得把骨架里那行多余的 break 删掉）")
        return 0

    try:
        agent = NoGuardAgent(llm=loopy, tools=TOOLS, verbose=False)
        _, steps, _ = agent.run("随便问点什么")
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print(f"\n  兜底计数器上限 = {NoGuardAgent.HARD_LIMIT} 圈")
    print(f"  实际跑了       = {len(steps)} 圈")
    if steps:
        print(f"  每一圈都在做   = {steps[0].action}（一模一样）")

    if len(steps) != NoGuardAgent.HARD_LIMIT:
        print(f"\n❌ 练习 2 · TODO 还没写保护")
        print(f"   （现在只跑了 {len(steps)} 圈，期望 {NoGuardAgent.HARD_LIMIT} 圈）")
        print("   检查点：判断要写在 append 之后、别让那行多余的 break 留着")
        return 1

    # 对照组：同样一个"复读"模型，有 max_steps 的版本只损失 3 次调用
    _, guarded_steps, guarded_reason = MiniAgent(
        llm=LoopingLLM(action="calc", args={"expr": "1+1"}), tools=TOOLS,
        max_steps=3, verbose=False).run("随便问点什么")
    _, scripted_steps, scripted_reason = MiniAgent(
        llm=ScriptedLLM(['Thought: 算一下。\n<tool_call>{"name": "calc", "args": {"expr": "6*7"}}</tool_call>',
                         'Thought: 好了。\nFinal Answer: 42']),
        tools=TOOLS, max_steps=6, verbose=False).run("计算 6*7")

    print(f"\n  对照组 1 · 有 max_steps=3 的复读模型：{len(guarded_steps)} 圈后停机（{guarded_reason}）")
    print(f"  对照组 2 · 正常剧本模型            ：{len(scripted_steps)} 圈后停机（{scripted_reason}）")

    print("\n✅ 跑通了")
    print("   ★ 体感：没有 max_steps，这个循环永远不会自己停 ——")
    print("     只能靠我们自己加的计数器兜底。")
    print("     你写的 HARD_LIMIT 就是 max_steps 的替身，只不过它停得不体面：")
    print("     正常版是够用就停，兜底版是撞墙才停。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
