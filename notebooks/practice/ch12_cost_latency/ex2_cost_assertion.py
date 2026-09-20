r"""第 12 章 · 练习 2 / 5 · 让成本算错一次，并把它固定成一条断言

【要做什么】
  **让成本算错一次，并把它固定成一条断言。**

  把第 ② 节的 `call_cost` 里 `prompt_tokens / 1000` 改成 `/ 100`，重跑那一格。
  观察「手算 == 计量器」那一行变成什么。

  然后写一条 `assert`，把「手算与计量器一致」固定下来。

【已经给你了】
  · 第 12 章真正的计量零件：`Price` / `PRICING` / `UsageMeter` / `money`
  · `make_meter(broken=False)`：正确的计量器；`broken=True` 时用一张「把 /1000 写成 /100」的价目表
    建出来的坏计量器 —— 这就是那个事故的替身
  · 两条已经记好的账目（正确的那条 / 坏掉的那条）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch12_cost_latency\ex2_cost_assertion.py
  3. 验收本章：py scripts\run_all_checks.py 12
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import math  # noqa: E402

from stages.stage12_cost_latency.demo import (  # noqa: E402
    PRICING, Price, UsageMeter, money,
)

TIER = "large"
PROMPT_TOKENS, COMPLETION_TOKENS = 1200, 300


def make_meter(broken: bool = False) -> UsageMeter:
    """建一个计量器并记一条账（已经写好，不用改）。

    broken=False → 正常的价目表
    broken=True  → 把「每 1K 的输入单价」放大 10 倍，等价于
                   代码里把 `prompt_tokens / 1000` 写成了 `/ 100`
    """
    if broken:
        pricing = dict(PRICING)
        good = PRICING[TIER]
        pricing[TIER] = Price(f"{good.name}(把 /1000 写成了 /100)",
                              good.prompt_per_1k * 10, good.completion_per_1k,
                              good.sim_latency_ms, good.sim_ttft_ms)
    else:
        pricing = dict(PRICING)
    meter = UsageMeter(pricing=pricing)
    meter.record_call(TIER, PROMPT_TOKENS, COMPLETION_TOKENS, 2200, 700)
    return meter


def manual_cost(tier: str, prompt_tokens: int, completion_tokens: int) -> float:
    """手算一次调用要多少钱（已经写好，不用改）。

    整个课程里唯一的成本公式：输入、输出分开计价，再相加。
    """
    price = PRICING[tier]
    return (prompt_tokens / 1000 * price.prompt_per_1k
            + completion_tokens / 1000 * price.completion_per_1k)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def assert_cost_matches_meter(meter: UsageMeter, tier: str,
                              prompt_tokens: int, completion_tokens: int) -> None:
    """TODO ① ── 用一条 assert 把「手算 == 计量器」钉死。

    要求：一致时什么都不做；不一致时抛 AssertionError，
          消息里必须能同时看到**手算值**和**计量器值**（否则排障时等于没说）。
    提示：手算用现成的 `manual_cost(tier, prompt, completion)`；
          计量器的值在 `meter.calls[0].cost`（这次只记了一条账）；
          浮点数比较用 `math.isclose(a, b, rel_tol=1e-9)` —— 别用 `==`。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 2 · TODO ①  assert_cost_matches_meter")
    # ↑↑↑ 你的答案 ↑↑↑


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   为什么「价目表改错了」必须由测试来兜，而不能指望它在线上报错？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    print(f"    条目：{TIER} 档，输入 {PROMPT_TOKENS} token，输出 {COMPLETION_TOKENS} token")
    print()

    try:
        # ① 正确的一侧：断言必须通过，而且手算与计量器逐位一致
        good = make_meter(broken=False)
        try:
            assert_cost_matches_meter(good, TIER, PROMPT_TOKENS, COMPLETION_TOKENS)
        except AssertionError as exc:
            print(f"❌ 误报：正确的计量器也被你的断言判成了错 —— {exc}")
            return 1
        print("    ① 正确价目表：断言通过 ✅")
        print(f"       手算     = {manual_cost(TIER, PROMPT_TOKENS, COMPLETION_TOKENS):.6f}")
        print(f"       计量器   = {good.calls[0].cost:.6f}")
        print()

        # ② 坏掉的一侧：断言必须抓住它（这正是这道题的全部价值）
        broken = make_meter(broken=True)
        try:
            assert_cost_matches_meter(broken, TIER, PROMPT_TOKENS, COMPLETION_TOKENS)
        except AssertionError as exc:
            print("    ② 坏价目表：你的断言抓住了它 ✅")
            print(f"       {exc}")
            ratio = broken.calls[0].cost / good.calls[0].cost
            good_prompt = PROMPT_TOKENS / 1000 * PRICING[TIER].prompt_per_1k
            bad_prompt = PROMPT_TOKENS / 1000 * broken.pricing[TIER].prompt_per_1k
            print(f"       账单翻了 {ratio:.2f} 倍（只算输入那一段是 {bad_prompt / good_prompt:.0f} 倍，"
                  f"输出那一段没受影响）—— 而且线上不会有任何报错。")
        else:
            print("    ❌ 没抓住：坏价目表也被判成一致 —— 断言写歪了")
            return 1
        print()

        # ③ 把它换算成钱：这种 bug 值多少钱
        print("    ③ 一次调用差多少（每天 1000 次任务）：")
        print(f"       每天多扣 {money((broken.cost - good.cost) * 1000)}"
              f" ≈ 每月多扣 {money((broken.cost - good.cost) * 1000 * 30)}")
        print("       ★ 账单类 bug 的可怕之处：它不抛异常、不变慢，只是悄悄多扣钱。")
        print("         所以「手算 == 计量器」必须是一条**自动化**断言，而不是一次人工核对。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print()
    print(f"    你的结论：{CONCLUSION or '（还没写 —— 写在文件里的 CONCLUSION 那一行）'}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
