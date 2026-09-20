r"""第 13 章 · 练习 2 / 5 · 给幂等账本加 TTL，并想清楚 TTL 该设多长

【要做什么】
  **给幂等缓存加 TTL，并想清楚 TTL 该设多长。**

  1. 给 ④ 的账本加一个 `ttl_s` 参数和基于时钟的惰性过期（读的时候判断）；
  2. 用 `FakeClock` 写一个自检：**TTL 内命中缓存、TTL 外重新执行**；
  3. 回答：TTL 设长了会怎样？设短了又会怎样？

【已经给你了】
  · 第 13 章真正的零件：`SideEffectLedger` / `STATS`（handlers.py）、`FakeClock` / `real_clock`（virtual.py）
  · `TtlLedger`：`__init__` 已经写好（多了一个 `_stored_at` 记账表和 `expired` 计数器）
  · `ttl_probe(ttl_s, second_gap_s)`：跑「第 1 次扣款 → 隔 N 秒后又来一次一模一样的提交」
  · `table()`：打印三种 TTL 的对照表

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch13_production\ex2_idempotency_ttl.py
  3. 验收本章：py scripts\run_all_checks.py 13
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage13_production.handlers import (  # noqa: E402
    STATS, SideEffectLedger, reset_world,
)
from stages.stage13_production.virtual import FakeClock, real_clock  # noqa: E402

IDEM_KEY = "idem-u42-350"     # 客户端给的幂等键：同一笔业务意图永远用同一个
USER, CENTS = "u_42", 350     # 给 u_42 扣 350 分（3.5 元）


def table(headers: list[str], rows: list[list[str]], indent: int = 2) -> None:
    """极简表格：按**显示宽度**对齐，中日韩字符占 2 列（已经写好，不用改）。

    课程零第三方依赖，所以不引入 rich / tabulate —— 十几行自己画一个就够。
    """

    def width(text: str) -> int:
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)

    def pad(text: str, n: int) -> str:
        return text + " " * max(0, n - width(text))

    widths = [max([width(h)] + [width(r[i]) for r in rows]) for i, h in enumerate(headers)]
    print(" " * indent + "  ".join(pad(h, widths[i]) for i, h in enumerate(headers)))
    print(" " * indent + "  ".join("-" * w for w in widths))
    for r in rows:
        print(" " * indent + "  ".join(pad(c, widths[i]) for i, c in enumerate(r)))


class TtlLedger(SideEffectLedger):
    """给幂等账本加 TTL：过期之后，同一个幂等键会被当成「没做过」。"""

    def __init__(self, ttl_s: float = 60.0, clock=real_clock) -> None:
        """已经写好，不用改。"""
        super().__init__()
        self.ttl_s = ttl_s
        self.clock = clock                          # 秒；注入假时钟才能确定性地测
        self._stored_at: dict[str, float] = {}      # 完整键 -> 记账时刻
        self.expired = 0                            # 被 TTL 判死的条数（生产里要进看板）

    # =======================================================================
    # ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
    # =======================================================================
    def _expire_if_needed(self, full_key: str) -> bool:
        """TODO ① ── 惰性过期：这个键过期了吗？过期就当成没有（顺手删掉），返回是否过期。

        要求：① 过期时把 `self.entries` 和 `self._stored_at` 里的这条都删掉；
              ② `self.expired` 累加 1（这个计数器就是「TTL 替你放行了多少次重复请求」）；
              ③ 没过期、或者根本没记过时刻 → 返回 False。
        提示：`full_key` 是 `f"{scope}:{key}"`（父类就是这么拼账本键的）；
              判断条件是 `self.clock() - 记账时刻 > self.ttl_s`。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 2 · TODO ①  _expire_if_needed")
        # ↑↑↑ 你的答案 ↑↑↑

    def apply_once(self, key: str, scope: str, subject: str, cents: int = 0) -> dict:
        """TODO ② ── 先过期检查，再走父类的 apply_once；**首次**真正生效时记下时刻。

        要求：① 先对 `f"{scope}:{key}"` 做一次 `self._expire_if_needed(...)`；
              ② 调用 `super().apply_once(key, scope, subject, cents)` 拿结果；
              ③ 这次不是重放（`res["replayed"]` 为 False）就记下当前时刻；
              ④ 原样返回父类的结果 —— 调用方要靠里面的 `replayed` 判断真相。
        提示：③ 不能省：只有「真的扣了款」的那一次才需要开始计时。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 2 · TODO ②  apply_once")
        # ↑↑↑ 你的答案 ↑↑↑
    # =======================================================================
    # ↑↑↑ 你的答案 ↑↑↑
    # =======================================================================


def ttl_probe(ttl_s: float, second_gap_s: float) -> dict:
    """跑一次「扣款 → 隔 N 秒后又来一次一模一样的提交」（已经写好，不用改）。

    返回 {"replayed": 第 2 次是不是重放, "applied": 外部世界真正扣了几次,
          "amount": 一共扣了多少钱（分）, "expired": TTL 放行了几次}
    """
    clock = FakeClock()
    led = TtlLedger(ttl_s=ttl_s, clock=clock)
    reset_world(led)                                    # 每次实验都从干净的世界开始
    led.apply_once(IDEM_KEY, "charge", USER, CENTS)     # 第 1 次提交：真的扣款
    clock.advance(second_gap_s)
    res = led.apply_once(IDEM_KEY, "charge", USER, CENTS)   # 第 2 次提交：同一个幂等键
    return {"replayed": bool(res["replayed"]),
            "applied": STATS["charge_applied"].get(USER),
            "amount": STATS["charge_amount"].get(USER),
            "expired": led.expired}


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   TTL 设长了会怎样？设短了又会怎样？支付类业务你打算设多长？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        print(f"    场景：同一笔扣款（{USER} / {CENTS} 分）用同一个幂等键提交两次")
        print()

        # ① 自检：TTL 内必须命中缓存（不重复扣款）
        inside = ttl_probe(60.0, 30.0)
        assert inside["replayed"] is True, "30 秒 < TTL 60 秒，第 2 次必须被判成重放"
        assert inside["applied"] == 1 and inside["amount"] == CENTS, \
            f"TTL 内不该重复扣款，实际扣了 {inside['applied']} 次 / {inside['amount']} 分"
        print("    ① TTL 内（60 秒的 TTL，30 秒后重试）")
        print(f"       第 2 次提交 → replayed={inside['replayed']}，"
              f"外部世界只扣了 {inside['applied']} 次（{inside['amount']} 分）✅")
        print()

        # ② 自检：TTL 外必须重新执行（这就是 TTL 的代价）
        outside = ttl_probe(60.0, 72000.0)          # 20 小时后
        assert outside["replayed"] is False, "TTL 之外必须重新执行"
        assert outside["applied"] == 2, "TTL 之外会真的再扣一次款"
        assert outside["expired"] == 1, "过期计数器要能看见这次放行"
        print("    ② TTL 外（60 秒的 TTL，20 小时后重试）")
        print(f"       第 2 次提交 → replayed={outside['replayed']}，"
              f"外部世界扣了 {outside['applied']} 次（{outside['amount']} 分）")
        print(f"       TTL 放行了 {outside['expired']} 次 —— 网络重试如果落在 TTL 之外，"
              f"重复扣款就回来了 ❌")
        print()

        # ③ 三种 TTL 放在一起看：这才叫「想清楚 TTL 该设多长」
        def verdict(r: dict) -> str:
            return "replayed（挡住了）" if r["replayed"] else "重新执行（又扣了一次）"

        rows = []
        for label, ttl in [("1 秒", 1.0), ("60 秒", 60.0), ("24 小时", 86400.0)]:
            retry = ttl_probe(ttl, 30.0)            # 网络重试：30 秒后到达
            later = ttl_probe(ttl, 72000.0)         # 用户 20 小时后真的想再充一次
            rows.append([label, verdict(retry), verdict(later)])
        table(["TTL", "网络重试（+30 秒才到）", "20 小时后真的再充一次"], rows)
        print()
        print("    ★ 读表提示：第 2 列里「replayed」才是对的（挡住重复）；")
        print("      第 3 列里「重新执行」才是对的（那是**新的一次**充钱，不该被挡住）。")
        print("    ★ 太短（1 秒）：网络重试落在 TTL 之外 → **重复扣款**（P0 事故）")
        print("    ★ 太长（24 小时）：用户当天真的想再充一次 → 被判成重复 → **业务被误伤**")
        print("    ★ 所以 TTL 是**业务问题**，不是技术问题：先问业务能容忍多旧的数据、")
        print("      以及「多长窗口内的重复提交算同一笔」。支付类通常 24 小时，点赞类可能 5 分钟。")
        print()
        print("    ⚠️ 最后一句提醒：TTL 只是 API 层的省钱手段。真正兜住「只扣一次」的，")
        print("       是数据库上的**唯一索引** —— 少一层都不行（第 13 章 ④ 讲过三层防御）。")
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
