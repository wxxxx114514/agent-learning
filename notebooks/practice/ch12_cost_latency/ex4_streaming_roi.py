r"""第 12 章 · 练习 4 / 5 · 把流式的 TTFT 收益算成钱，并放进同一张 ROI 表

【要做什么】
  **把流式的 TTFT 收益算成钱。**

  假设「用户等待超过 1 秒就流失 5%」，每天 1000 次任务。
  算出把首字延迟从 2200ms 降到 700ms 能挽回多少用户、值多少钱。

  然后把它和成本收益放进同一张 ROI 表。

【已经给你了】
  · 第 12 章真正的零件：`run_pipeline` / `BASELINE` / `OPTIMIZED` / `PRICING` / `QUESTIONS` / `money`
  · `stream_timeline(text, ttft_ms, total_ms)`：切出流式片段和它们的到达时刻
  · 四个业务假设：`TASKS_PER_DAY` / `CHURN_THRESHOLD_MS` / `CHURN_RATE` / `VALUE_PER_SESSION`

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch12_cost_latency\ex4_streaming_roi.py
  3. 验收本章：py scripts\run_all_checks.py 12
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage12_cost_latency.demo import (  # noqa: E402
    BASELINE, OPTIMIZED, PRICING, QUESTIONS, money, run_pipeline, stream_timeline, table,
)

# ---- 四个业务假设（真实项目里换成你自己的数字；关键是它们必须写下来）----
TASKS_PER_DAY = 1000          # 每天跑多少次任务
CHURN_THRESHOLD_MS = 1000.0   # 首字延迟超过这条线，用户开始流失
CHURN_RATE = 0.05             # 超线的会话里，流失 5%
VALUE_PER_SESSION = 2.0       # 一次会话的业务价值（元）；换成你的客单价

TTFT_BEFORE_MS = PRICING["large"].sim_latency_ms     # 非流式：用户等到全部生成完 = 2200ms
TTFT_AFTER_MS = PRICING["large"].sim_ttft_ms         # 流式：等到第一个字 = 700ms


def yuan(x: float) -> str:
    """金额格式化：0 元就老老实实写 ¥0（已经写好，不用改）。"""
    return "¥0" if not x else money(x)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def streaming_roi(before_ms: float, after_ms: float) -> dict:
    """TODO ① ── 把「首字延迟从 before_ms 降到 after_ms」算成钱。

    要求：返回一个 dict，四个键分别是
        "lost_before"     改之前每天流失多少会话（整数）
        "lost_after"      改之后每天流失多少会话（整数）
        "saved_per_day"   每天挽回多少会话（整数）
        "value_per_month" 每月折合多少钱（元，浮点）
    判据只有一句：**只有跨过 CHURN_THRESHOLD_MS 那条线，延迟的改善才值钱。**
    提示：每天流失数 = 超过阈值 ? TASKS_PER_DAY * CHURN_RATE : 0；
          每月价值 = 每天挽回 × 30 天 × VALUE_PER_SESSION。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO ①  streaming_roi")
    # ↑↑↑ 你的答案 ↑↑↑


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   为什么「省了 ¥x」和「少流失 y 个用户」必须放进同一张表里比较？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        # ① 主场景：2200ms → 700ms
        roi = streaming_roi(TTFT_BEFORE_MS, TTFT_AFTER_MS)
        print(f"    假设：每天 {TASKS_PER_DAY} 次任务，首字超过 {CHURN_THRESHOLD_MS:.0f}ms "
              f"流失 {CHURN_RATE:.0%}，一次会话值 {money(VALUE_PER_SESSION)}")
        print()
        print(f"    流式前：首字 {TTFT_BEFORE_MS:.0f}ms → 每天流失 {roi['lost_before']} 次会话")
        print(f"    流式后：首字 {TTFT_AFTER_MS:.0f}ms → 每天流失 {roi['lost_after']} 次会话")
        print(f"    挽回  ：{roi['saved_per_day']} 次/天 ≈ {roi['saved_per_day'] * 30} 次/月 "
              f"≈ {money(roi['value_per_month'])}/月")
        assert roi["saved_per_day"] == 50, f"期望每天挽回 50 次，实际 {roi['saved_per_day']}"
        assert abs(roi["value_per_month"] - 3000.0) < 1e-6, "每月价值算错了"
        print()

        # ② 关键判据：没跨过流失线的延迟改善，一文不值
        rows = []
        for before, after, note in [
            (2200, 700, "跨过了 1 秒线 → 真的省下用户"),
            (2200, 1200, "还是超过 1 秒 → 白改"),
            (900, 700, "本来就没超线 → 只是体感好一点"),
        ]:
            r = streaming_roi(before, after)
            rows.append([f"{before:.0f}ms → {after:.0f}ms", str(r["lost_before"]),
                         str(r["lost_after"]), str(r["saved_per_day"]),
                         yuan(r["value_per_month"]), note])
        table(["首字延迟", "改前流失/天", "改后流失/天", "挽回/天", "折合/月", "说明"], rows)
        print()
        assert streaming_roi(2200, 1200)["saved_per_day"] == 0, "1200ms 仍然超线，不该算成收益"
        print("    ★ 2200ms → 1200ms 看起来「快了 45%」，挽回的会话却是 0：")
        print("      延迟优化的靶子是**那条业务线**，不是「数字变小」。")
        print()

        # ③ 同一张 ROI 表：成本收益（改代码）vs 用户收益（改交互）
        base = run_pipeline(QUESTIONS, BASELINE)
        opt = run_pipeline(QUESTIONS, OPTIMIZED)
        save_per_task = base.meter.cost - opt.meter.cost
        save_per_month = save_per_task * TASKS_PER_DAY * 30
        print(f"    ④ 成本侧（缓存 + 路由 + 并行）：每次任务 "
              f"{money(base.meter.cost)} → {money(opt.meter.cost)}")
        print(f"       模型调用 {base.meter.model_calls} → {opt.meter.model_calls} 次，"
              f"首字延迟 {base.meter.first_token_ms:.0f}ms → {opt.meter.first_token_ms:.0f}ms")
        table(["手段", "每月省的钱", "每月挽回的会话", "改的是什么"],
              [["缓存 + 路由 + 并行", yuan(save_per_month), "0", "代码（不动质量）"],
               ["流式输出", "¥0", f"{roi['saved_per_day'] * 30} 次 "
                f"≈ {yuan(roi['value_per_month'])}", "交互（不动成本）"]])
        print()
        assert save_per_month > 0, "优化后的成本应该更低"
        print("    ★ 两种收益的量纲完全不同，但**必须放进同一张表**才排得出优先级 ——")
        print("      否则你永远只会挑最容易改的那个去改。")
        print()

        # ④ 顺便看一眼流式的时间轴（真实 API）
        answer = "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890，预计 2025-01-05 送达。"
        chunks, times = stream_timeline(answer, TTFT_AFTER_MS, TTFT_BEFORE_MS)
        head = " ".join(f"{t:.0f}ms:{c!r}" for c, t in list(zip(chunks, times))[:4])
        print(f"    ⑤ 流式时间轴（共 {len(chunks)} 个片段）：{head} …")
        print(f"       总时长没变（{TTFT_BEFORE_MS:.0f}ms），但用户 "
              f"{times[0]:.0f}ms 就看到了第一个字。")
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
