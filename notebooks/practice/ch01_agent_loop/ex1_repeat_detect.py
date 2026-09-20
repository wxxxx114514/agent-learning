r"""第 01 章 · 练习 1 / 5 · 给 `MiniAgent` 加「重复动作检测」

【要做什么】
  给 `MiniAgent.run()` 加重复动作检测。

  记录每次工具调用的指纹（`name + json.dumps(args, sort_keys=True)`），
  同一个指纹出现超过 2 次时，往历史里插一条提醒。

  然后跑 `LoopingLLM` 验证：提醒有没有出现在它的上下文里？

【已经给你了】
  · `MiniAgent` / `Step`      —— 第 01 章的 Agent 本体和一圈循环的记录
  · `_demo_tools()`           —— 现成工具表 {calc, lookup_order}
  · `LoopingLLM`              —— 永远重复同一个动作的假模型（专门触发复读）
  · `ScriptedLLM`             —— 一个「正常」的剧本模型，用来做对照
  · `GuardedAgent` 的类骨架    —— 只剩两个方法体留给你写

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch01_agent_loop\ex1_repeat_detect.py
  3. 验收本章：py scripts\run_all_checks.py 01
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                                                   # noqa: E402

from core.message import Message                              # noqa: E402
from core.mock_llm import LoopingLLM, ScriptedLLM             # noqa: E402
from stages.stage01_agent_loop.demo import (                  # noqa: E402
    MiniAgent,
    Step,
    _demo_tools,
)

TOOLS = _demo_tools()          # {'calc': …, 'lookup_order': …}
# ★ action 必须用 TOOLS 里真实存在的工具，否则"重复"会变成"重复报错"，现象就不对了
loopy = LoopingLLM(action="calc", args={"expr": "1+1"})   # 永远重复同一个动作 → 专门触发复读
SCRIPTED = ScriptedLLM([       # 一个"正常"的剧本模型，用来做对照
    'Thought: 我要算一下。\n<tool_call>{"name": "calc", "args": {"expr": "12+8"}}</tool_call>',
    'Thought: 算出来了。\nFinal Answer: 20',
])


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class GuardedAgent(MiniAgent):
    """带「重复动作检测」的 MiniAgent。

    【为什么写在 _execute 里】
      MiniAgent.run() 里的 `messages` 是局部变量，外面拿不到；
      但每次工具调用都经过 _execute，而它的返回值会被原样塞进 messages
      （作为 tool_result）。所以在这里补一句提醒，模型下一圈就看得见。
    """

    repeat_limit = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen: dict[str, int] = {}        # 指纹 -> 出现过几次

    def _fingerprint(self, name: str, args: dict) -> str:
        """TODO ① ── 返回这次工具调用的指纹。

        要求：同一个「工具名 + 参数」永远得到同一个字符串。
        提示：f"{name}({json.dumps(args, sort_keys=True)})"
              —— sort_keys 不能省，否则 {"a":1,"b":2} 和 {"b":2,"a":1} 会被当成两次。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 1 · TODO ①  _fingerprint 还没有写")
        # ↑↑↑ 你的答案 ↑↑↑

    def _execute(self, name: str, args: dict) -> str:
        """TODO ② ── 先拿正常结果，再判断「是不是重复太多次了」。

        三步：
          1. out = super()._execute(name, args)      ← 正常执行，别绕过它
          2. 用 self._fingerprint(name, args) 取指纹，在 self._seen 里计数 +1
          3. 计数超过 self.repeat_limit 时，往 out 后面追加一句提醒
        提示：out 是字符串，out += "\n\n<你的提醒>" 即可。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 1 · TODO ②  _execute 还没有写")
        # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 01 章 · 练习 1 · 重复动作检测")
    print("=" * 68)

    try:
        agent = GuardedAgent(llm=loopy, tools=TOOLS, max_steps=6, verbose=False)
        _, steps, reason = agent.run("随便问点什么")
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        # LLM.complete 会给异常包一层，这里把内层的 NotImplementedError 挖出来
        cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
        if isinstance(cause, NotImplementedError):
            print(f"\n⬜ 还没写：{cause}")
            return 0
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    obs = [s.observation for s in steps if s.observation]
    print(f"\n  跑了 {len(steps)} 圈，停机原因 = {reason}")
    print(f"  工具结果共 {len(obs)} 条")
    print("\n  指纹计数（应该能看到 calc 累计到 3 次以上）：")
    for sig, n in agent._seen.items():
        print(f"    {n} 次  {sig[:56]}")

    if not obs:
        print("\n❌ 一条工具结果都没有 —— _execute 必须调用 super()._execute()")
        return 1
    print("\n  最后一次工具结果：")
    for line in str(obs[-1]).splitlines()[:6]:
        print("      " + line)

    if len(obs) < 3:
        print(f"\n❌ 圈数不够（只有 {len(obs)} 条结果），跑不出「超过 2 次」的现象")
        return 1
    if not any("重复" in str(o) or "提醒" in str(o) or "已出现" in str(o) for o in obs):
        print("\n❌ 没看到你加的提醒 —— 检查：计数超过 repeat_limit 时有没有 out += 提示")
        return 1

    print("\n✅ 跑通了")
    print("   ★ 体感：提醒之后模型往往会换方法 —— 所以先提醒，而不是直接停机。")
    print("     框架版的做法在 core/agent.py 的 _call_history + repeat_limit。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
