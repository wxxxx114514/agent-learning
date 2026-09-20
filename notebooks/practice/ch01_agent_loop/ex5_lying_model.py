r"""第 01 章 · 练习 5 / 5 · 注入一个会撒谎的模型

【要做什么】
  注入一个会撒谎的模型。

  写一个假模型，让它**不调用工具**，直接编一个订单状态返回。
  观察 Agent 会不会发现。

  然后修改系统提示词，加入「订单状态必须来自 lookup_order 的真实返回」，
  再看能否拦住它。

【已经给你了】
  · `MiniAgent` / `Step`      —— 第 01 章的 Agent 本体
  · `_extract_tool_call`      —— 解析函数（和 MiniAgent.run 里用的同一个）
  · `Message`                 —— 发消息用；`Message.system()` 就是系统提示词
  · `TOOLS` / `TRUTH`         —— 现成工具表，以及 `lookup_order("A1001")` 的真实返回
  · `SYSTEM_PROMPT`           —— 一个**没有**约束的普通系统提示词
  · `STRICT_PROMPT`           —— 加了「订单状态必须来自真实返回」的版本
  · `run_with_system(...)`    —— 用指定系统提示词跑一遍（= MiniAgent 的循环，只是换了提示词）
  · `LyingLLM` 的类骨架        —— 只空 `_complete()` 一个方法

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch01_agent_loop\ex5_lying_model.py
  3. 验收本章：py scripts\run_all_checks.py 01
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.llm import LLM, LLMResponse                         # noqa: E402
from core.message import Message                              # noqa: E402
from stages.stage01_agent_loop.demo import (                  # noqa: E402
    MiniAgent,
    Step,
    _demo_tools,
    _extract_tool_call,
    _last_answer,
)

TOOLS = _demo_tools()

SYSTEM_PROMPT = "你可以调用工具。需要工具时输出 Action: 工具名(参数)"
STRICT_PROMPT = (
    SYSTEM_PROMPT + "\n"
    "订单状态必须来自 lookup_order 的真实返回，不要凭记忆回答订单相关问题。"
)

# 先偷偷看一眼"真话"长什么样 —— 这样你才知道模型编得有多像
TRUTH = TOOLS["lookup_order"]("A1001")
QUESTION = "订单 A1001 到哪了？"


def run_with_system(sys_prompt: str, llm: LLM, question: str, max_steps: int = 3):
    """用指定的系统提示词跑一遍 MiniAgent 的循环（只是把 SYSTEM 换成了参数）。

    返回 (答案, 步骤列表, 停机原因)。逻辑与 MiniAgent.run() 完全一致，
    唯一区别是系统提示词由你指定 —— 这样才好在两轮之间做对照。
    """
    agent = MiniAgent(llm=llm, tools=TOOLS, max_steps=max_steps, verbose=False)
    messages = [Message.system(sys_prompt), Message.user(question)]
    steps: list[Step] = []
    stop_reason = "max_steps"

    for i in range(1, max_steps + 1):
        step = Step(index=i)
        steps.append(step)
        reply = llm.complete(messages).text
        call = _extract_tool_call(reply)

        if "Final Answer:" in reply and not call:
            step.answer = reply.split("Final Answer:", 1)[1].strip()
            messages.append(Message.assistant(reply))
            stop_reason = "final_answer"
            break
        if not call:
            messages.append(Message.assistant(reply))
            continue

        name, args = call
        step.action = f"{name}({args})"
        messages.append(Message.assistant(reply))
        step.observation = agent._execute(name, args)
        messages.append(Message.tool_result(name, step.observation))

    return _last_answer(steps), steps, stop_reason


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class LyingLLM(LLM):
    """一个不查工具、直接编答案的假模型。"""

    name = "lying"

    def _complete(self, messages, **kwargs) -> LLMResponse:
        """TODO ── 返回一个「直接给答案、不调用工具」的回复。

        要求：
          · 输出里**不能**出现 `<tool_call>`
            （出现了 MiniAgent 就会去执行工具，那就不是"撒谎"了）
          · 要给出 `Final Answer:`，内容是一个具体、自信、听上去可信的订单状态
          · 提示：LLMResponse(text='Thought: 我知道。\\nFinal Answer: 订单 A1001 已发货')

        写完对比一下 `TRUTH`：真话里有承运商和运单号。
        你编的那句少了哪些字段？这就是"没查过数据"露出的马脚。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO  LyingLLM._complete 还没有写")
        # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 01 章 · 练习 5 · 撒谎的模型")
    print("=" * 68)

    # 先探一下你写没写：没写就直接告诉你（LLM.complete 会把异常包成 LLMError）
    from core.errors import LLMError
    try:
        probe = LyingLLM().complete([Message.user(QUESTION)]).text
    except LLMError:
        print("\n⬜ 还没写：练习 5 · TODO  LyingLLM._complete 还没有写")
        return 0
    if "<tool_call>" in probe:
        print("\n❌ 这个模型不该调用工具（你返回的内容里出现了 <tool_call>）")
        return 1

    print(f"\n  用户问     : {QUESTION}")
    print(f"  真实的工具 : {TRUTH}")

    try:
        answer, steps, reason = run_with_system(SYSTEM_PROMPT, LyingLLM(), QUESTION)
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    calls = sum(1 for s in steps if s.action)
    print(f"\n  〔第 1 轮：普通系统提示词〕")
    print(f"    模型回答   : {answer!r}")
    print(f"    工具调用次数: {calls}    ← 期望 0")
    print(f"    停机原因   : {reason}")

    if not str(answer).strip():
        print("\n❌ 答案为空 —— 要让 Final Answer 后面跟上一句编好的订单状态")
        return 1
    if calls != 0:
        print("\n❌ 这个模型不该调工具（这道题要观察的正是「它不查也敢答」）")
        return 1
    if "A1001" not in str(answer):
        print("\n❌ 答案里要提到订单 A1001 —— 编得越像真的，后面的对照越明显")
        return 1

    # 对照：改成带约束的系统提示词，看同一张"嘴"会不会改口
    answer2, steps2, reason2 = run_with_system(STRICT_PROMPT, LyingLLM(), QUESTION)
    calls2 = sum(1 for s in steps2 if s.action)
    print("\n  〔第 2 轮：加了「订单状态必须来自 lookup_order 的真实返回」〕")
    print(f"    模型回答   : {answer2!r}")
    print(f"    工具调用次数: {calls2}")
    print(f"    停机原因   : {reason2}")
    if calls2 == 0:
        print("    ^ 同一句编好的答案 —— 提示词**没有**拦住它")
        print("      （真实模型会更「听话」一些，但你无法保证它 100% 照做）")
    else:
        print("    ^ 这次它去查了 —— 提示词对「听话」的模型有效，但不是保证")

    print("\n✅ 跑通了")
    print("   ★ 体感：Agent 不会自己发现答案没查过数据。")
    print("     提示词能减少撒谎，但拦不住 —— 真正管用的是")
    print("     第 07 章（反思 / 验证器）和第 11 章（护栏：答案必须带证据）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
