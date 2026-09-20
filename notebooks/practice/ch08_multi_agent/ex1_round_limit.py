r"""第 08 章 · 练习 1 / 5 · 拆掉轮数上限，看账单怎么涨（必做）

【要做什么】
  **拆掉轮数上限，看账单怎么涨（必做）。**
  把 `MAX_ROUNDS` 从 3 改成 50，重跑那一格。
  观察：消息条数、`rounds`、以及「如果每轮都要调一次模型」的调用次数。
  再想一步：如果这是一个每天 1 万单的客服系统，这个 bug 一天要花多少钱？

【已经给你了】
  · build_team(stubborn=True, max_rounds=N)：一支「互相踢皮球」的团队
    （数据专家说材料不够、政策专家说要数据，谁也不服谁 → 专门用来触发无限讨论）
  · TICKET：一张真实的客诉工单；HOLD_REPLY：触顶后的兜底话术
  · run_team()：跑一次并打印 轮数 / 消息条数 / 停机原因 / 调用次数 / 仲裁结论，不用改
  · estimate_cost() / daily_cost()：调用次数 → 钱的粗估公式（假设写在常量注释里）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch08_multi_agent\ex1_round_limit.py
  3. 验收本章：py scripts\run_all_checks.py 08
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                          # noqa: E402
from stages.stage08_multi_agent.demo import (                            # noqa: E402
    TICKET, SupervisorResult, build_team,
)

TOKENS_PER_CALL = 1200        # 教学粗估：一次专家调用的 token 量
YUAN_PER_1K_TOKENS = 0.01     # 教学粗估：每千 token 一分钱
TICKETS_PER_DAY = 10_000      # 题面里的「每天 1 万单」


def estimate_cost(calls: int) -> float:
    """调用次数 → 一次工单多少钱。不用改。"""
    return calls * TOKENS_PER_CALL / 1000 * YUAN_PER_1K_TOKENS


def daily_cost(calls: int, tickets: int = TICKETS_PER_DAY) -> float:
    """调用次数 → 每天一万单多少钱。不用改。"""
    return estimate_cost(calls) * tickets


def run_team(max_rounds: int, label: str) -> SupervisorResult:
    """跑一次踢皮球场景，打印关键指标。不用改。"""
    _bus, supervisor = build_team(stubborn=True, max_rounds=max_rounds)
    r = supervisor.run(TICKET)
    print(f"  ── {label}（max_rounds = {max_rounds}）──")
    kv("轮数", f"{r.rounds}")
    kv("停机原因", r.stop_reason)
    kv("消息条数", f"{len(r.envelopes)}")
    kv("模型调用次数", f"{r.llm_calls}")
    kv("仲裁结论", r.decision)
    kv("最终交付", "转人工安抚话术" if r.final_reply.startswith("【工单") else r.final_reply[:24])
    kv("一次工单成本（粗估）", f"{estimate_cost(r.llm_calls):.4f} 元")
    print()
    return r


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
# TODO ① ── 把轮数上限拆掉：把这个数字从 3 改成 50（这就是本题的动手部分）
MAX_ROUNDS = 3


def my_conclusion() -> str:
    """TODO ② ── 回答题面：每天 1 万单的客服系统，这个 bug 一天要花多少钱？

    用上面打印出来的「一次工单成本 × 10000」算，并写清楚：
      · 为什么「光有上限」只是把浪费截断，而没有上限才是灾难？
      · 触顶之后应该做什么（而不是硬编一个结论）？
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
            f"练习 1 · TODO ① 轮数上限还没拆掉（MAX_ROUNDS 现在 = {MAX_ROUNDS}，题面要求 50）")

    print("\n" + "=" * 66)
    print("  同一支「互相踢皮球」的团队，只改轮数上限")
    print("=" * 66)
    base = run_team(3, "对照组：有上限")
    broken = run_team(MAX_ROUNDS, "拆掉上限")

    print("  ── 账单 ──")
    kv("对照组的调用次数", f"{base.llm_calls} 次")
    kv("拆掉上限后的调用次数", f"{broken.llm_calls} 次（{broken.llm_calls / max(base.llm_calls, 1):.1f} 倍）")
    kv("对照组 · 每天 1 万单", f"{daily_cost(base.llm_calls):,.0f} 元/天")
    kv("拆掉上限 · 每天 1 万单", f"{daily_cost(broken.llm_calls):,.0f} 元/天")
    kv("多花的钱", f"{daily_cost(broken.llm_calls) - daily_cost(base.llm_calls):,.0f} 元/天")
    print()
    warn("每一轮「转达 + 回答」至少是两条消息、两次模型调用 —— 而它**什么问题都没解决**。")
    note("触顶之后主管做了什么？看最终交付：它如实给了一个保守结果，而不是硬编结论。")
    bullet("没有 max_rounds 的多智能体 = 一张会自动续费的账单：上限不是可选项。")
    bullet("光有上限还不够 —— 上限之外还要有「触顶后的行为」（转人工，不是猜一个结论）。")
    bullet("消息条数同样要设上限：讨论轮数涨 1，消息数涨得比它更快。")

    conclusion = my_conclusion().strip()
    if len(conclusion) < 8:
        raise NotImplementedError("练习 1 · TODO ② 结论太短了，把「一天多少钱」和「触顶后怎么办」都写上")
    print()
    kv("你的结论", conclusion)
    return (f"{base.llm_calls} 次 → {broken.llm_calls} 次调用；"
            f"每天 1 万单多花 {daily_cost(broken.llm_calls) - daily_cost(base.llm_calls):,.0f} 元")


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
