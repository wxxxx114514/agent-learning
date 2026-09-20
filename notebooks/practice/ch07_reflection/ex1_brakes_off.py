r"""第 07 章 · 练习 1 / 5 · 拆掉刹车：一个「永远不满意」的审查者有多贵

【要做什么】
  **把刹车拆掉，观察会发生什么。**
  把 `MAX_ROUNDS` 改成 50，用挑刺派审查者跑一次，看 `轮数` 和 `模型调用次数`。
  然后回答：如果这是线上系统，一个「永远不满意」的审查者会花掉你多少钱？

【已经给你了】
  · make_agent(task, mode=..., max_rounds=...)：一行组装一个 Reflexion Agent
  · TASK_Q1：写销售速报的任务（正确答案 811 元，假模型「心算」会写成 801）
  · mode="nitpick"：挑刺派审查者，它永远能挑出一条新的、**无法验证**的毛病 → 天然不收敛
  · estimate_cost() / daily_cost()：把「调用次数」换算成钱的粗略公式（假设写在常量注释里）
  · run_case()：跑一次并打印 轮数 / 停机原因 / 调用次数 / 未闭环意见，不用改

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch07_reflection\ex1_brakes_off.py
  3. 验收本章：py scripts\run_all_checks.py 07
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                        # noqa: E402
from stages.stage07_reflection.demo import (                           # noqa: E402
    TASK_Q1, ReflexionResult, make_agent, total_in,
)

TOKENS_PER_CALL = 1200        # 教学粗估：一次「写报告」或「审查」调用的 token 量
YUAN_PER_1K_TOKENS = 0.01     # 教学粗估：每千 token 一分钱
TICKETS_PER_DAY = 10_000      # 放大到线上：每天 1 万单


def estimate_cost(calls: int) -> float:
    """把「调用次数」换算成「一次任务多少钱」。不用改。"""
    return calls * TOKENS_PER_CALL / 1000 * YUAN_PER_1K_TOKENS


def daily_cost(calls: int, tickets: int = TICKETS_PER_DAY) -> float:
    """一次任务的调用次数 → 放到每天一万单上的钱。不用改。"""
    return estimate_cost(calls) * tickets


def run_case(max_rounds: int, label: str) -> tuple[ReflexionResult, int]:
    """跑一次挑刺派审查者的循环，打印关键指标。返回 (结果, 模型调用次数)。不用改。"""
    agent = make_agent(TASK_Q1, mode="nitpick", max_rounds=max_rounds)
    r = agent.run(TASK_Q1)
    writer_calls = r.llm_calls                    # 写作模型的调用次数
    critic_calls = len(r.rounds)                  # 每一轮审查者也各调用一次
    total_calls = writer_calls + critic_calls
    print(f"  ── {label}（MAX_ROUNDS = {max_rounds}）──")
    kv("轮数", f"{len(r.rounds)}")
    kv("停机原因", r.stop_reason)
    kv("模型调用次数", f"{writer_calls} 写作 + {critic_calls} 审查 = {total_calls}")
    kv("最终合计", total_in(r.final))
    kv("验证通过", "是" if r.verified else "否")
    kv("未闭环的审查意见", f"{len(r.unresolved)} 条")
    kv("一次任务成本（粗估）", f"{estimate_cost(total_calls):.4f} 元")
    print()
    return r, total_calls


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
# TODO ① ── 把刹车拆掉：把下面这个数字从 3 改成 50（这就是本题的动手部分）
MAX_ROUNDS = 3


def my_conclusion() -> str:
    """TODO ② ── 回答题面里的两个问题（写成一句话）。

      · 如果这是线上系统，一个「永远不满意」的审查者会花掉你多少钱？
        （用上面打印出来的 一次任务成本 × 每天 1 万单 算一下）
      · 为什么「把轮数调大」不能提高质量？
    """
    # 写下你的结论：
    #
    #   ↓↓↓ 把下面这行删掉，写上 return "你的结论" ↓↓↓
    raise NotImplementedError("练习 1 · TODO ②  写下你的结论")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def check() -> str:
    if MAX_ROUNDS < 50:
        raise NotImplementedError(
            f"练习 1 · TODO ① 刹车还没拆掉（MAX_ROUNDS 现在 = {MAX_ROUNDS}，题面要求 50）")

    print("\n" + "=" * 66)
    print("  对照实验：同一个任务、同一个挑刺派审查者，只改轮数上限")
    print("=" * 66)
    base, base_calls = run_case(3, "对照组：有刹车")
    broken, broken_calls = run_case(MAX_ROUNDS, "拆掉刹车")

    print("  ── 账单 ──")
    kv("对照组总调用", f"{base_calls} 次 → {estimate_cost(base_calls):.4f} 元/单")
    kv("拆刹车后总调用", f"{broken_calls} 次 → {estimate_cost(broken_calls):.4f} 元/单")
    kv(f"放大到每天 {TICKETS_PER_DAY:,} 单",
       f"对照组 {daily_cost(base_calls):,.0f} 元/天 → 拆刹车后 {daily_cost(broken_calls):,.0f} 元/天")
    print()
    warn("每一轮都是**一次真实的模型调用**，而它连结果都没改对 —— 钱花在了原地打转上。")
    note("为什么调大轮数不能提高质量？主观标准下它根本**不收敛**：")
    note("它只增加了成本，没有增加任何确定性。")
    bullet("刹车的三件套：max_rounds（轮数）/ no_progress（没进展）/ verifier（事实裁判）")
    bullet("停机时必须分类（verified_pass / no_progress / max_rounds），否则定位不到问题。")

    conclusion = my_conclusion().strip()
    if len(conclusion) < 8:
        raise NotImplementedError("练习 1 · TODO ② 结论太短了，把成本和质量这两点都写进去")
    print()
    kv("你的结论", conclusion)
    return (f"{base_calls} 次调用 → {broken_calls} 次调用；"
            f"每天 {TICKETS_PER_DAY:,} 单要多花 "
            f"{daily_cost(broken_calls) - daily_cost(base_calls):,.0f} 元")


def main() -> int:
    try:
        summary = check()
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    print()
    print(f"  → {summary}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
