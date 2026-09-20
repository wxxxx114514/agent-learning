r"""第 12 章 · 练习 5 / 5 · 给缓存加 TTL 与写失效（invalidate_entities）

【要做什么】
  **进阶：给 `SemanticCache` 加 TTL 与写失效。**

  加一个 `ttl_ms` 参数（过期就不许命中），再加一个 `invalidate_entities(实体集合)` 方法。

  然后想清楚两个问题：哪些缓存**必须**失效？过期时长设多少？

【已经给你了】
  · 第 12 章真正的缓存零件：`SemanticCache` / `CacheEntry` / `entities_of`
  · `TtlCache`：已经把 `__init__` 和 `put` 写好了（记下每条答案的写入时刻）
  · `FakeClock`：可以手动推进的假时钟 —— 测试 TTL 不能靠 `time.sleep`
  · 三组自检在 main() 里：TTL 内命中 / TTL 外失效 / 写失效只删该删的

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch12_cost_latency\ex5_cache_ttl.py
  3. 验收本章：py scripts\run_all_checks.py 12
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import time  # noqa: E402

from stages.stage12_cost_latency.demo import (  # noqa: E402
    CacheEntry, SemanticCache, entities_of,
)


class FakeClock:
    """可以手动推进的假时钟（已经写好，不用改）。

    ★ 为什么不能 `time.sleep(6)` 去等 TTL 过期？
      测试会慢 6 秒、结果还不确定（CI 机器慢一点就变样），
      而且根本没法演示「再过一会儿才过期」。
      第 13 章的 `stages/stage13_production/virtual.py` 里有一个一模一样的 `FakeClock`，
      生产里这叫「注入时钟」（Clock Injection）。
    """

    def __init__(self, start: float = 1000.0) -> None:
        self._now = float(start)

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += float(seconds)
        return self._now


Q1 = "订单 A1001 到哪了？"
A1 = "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。"
Q2 = "订单 A1002 到哪了？"
A2 = "订单 A1002 待付款。"


class TtlCache(SemanticCache):
    """给缓存补上两个生产必备能力：TTL（过期不许命中）与写失效（按实体作废）。"""

    def __init__(self, ttl_ms: float = 5000.0, clock=None, **kwargs) -> None:
        """已经写好，不用改。"""
        super().__init__(**kwargs)
        self.ttl_ms = ttl_ms                      # 超过这么久就算过期
        self.clock = clock or time.monotonic      # 秒；注入假时钟才能测
        self._stored_at: dict[int, float] = {}    # id(条目) -> 写入时刻
        self.expired = 0                          # 被 TTL 判死的条数（生产里要进看板）

    def put(self, *args, **kwargs) -> CacheEntry:
        """已经写好，不用改：写缓存时顺手记下时刻。"""
        entry = super().put(*args, **kwargs)
        self._stored_at[id(entry)] = self.clock()
        return entry

    # =======================================================================
    # ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
    # =======================================================================
    def _is_expired(self, entry: CacheEntry) -> bool:
        """TODO ① ── 这条记录过期了吗？

        要求：写入时刻在 `self._stored_at[id(entry)]`（是**秒**），
              和 `self.ttl_ms`（**毫秒**）比较时别忘了换算。
        提示：`(self.clock() - 写入时刻) * 1000 > self.ttl_ms`；
              查不到写入时刻就当成没过期（宁可多命中一次，也不要误删）。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ①  _is_expired")
        # ↑↑↑ 你的答案 ↑↑↑

    def purge(self) -> int:
        """TODO ② ── 惰性过期：把过期的条目清掉，返回清了几条。

        要求：① `self.entries` 里不再留下过期条目（顺手把 `self._stored_at` 里的记录也删掉）；
              ② `self.expired` 累加清掉的条数（生产里这个计数器必须被监控）；
              ③ 返回清掉的条数。
        提示：`self.entries = [e for e in self.entries if not ...]` 一句话就能筛出来，
              条数用「原来的长度 - 现在的长度」。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ②  purge")
        # ↑↑↑ 你的答案 ↑↑↑

    def get(self, question: str):
        """TODO ③ ── 先惰性过期，再交给父类去查。

        要求：过期条目**不允许**被命中 —— 它们必须像从来没存在过一样。
        提示：一行 `self.purge()`，再 `return super().get(question)`。
              顺序不能反：先查再清的话，这条过期答案就被返回出去了。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ③  get")
        # ↑↑↑ 你的答案 ↑↑↑

    def invalidate_entities(self, entities) -> int:
        """TODO ④ ── 写失效：把「实体集合和它**有交集**」的条目全部作废，返回作废几条。

        要求：用户改了收货地址之后，所有含这个订单号的缓存都必须立刻作废 ——
              **哪怕还没到 TTL**（TTL 只兜「数据自己变旧」，兜不住「数据被改」）。
        提示：参数 `entities` 可以直接 `frozenset(...)`；
              两个集合有交集写成 `e.entities & targets`（非空就说明沾边）。
              返回条数，并且别忘了从 `self._stored_at` 里清掉对应记录。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ④  invalidate_entities")
        # ↑↑↑ 你的答案 ↑↑↑
    # =======================================================================
    # ↑↑↑ 你的答案 ↑↑↑
    # =======================================================================


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   TTL 设长了会怎样？设短了又会怎样？哪些缓存**必须**立刻失效？
CONCLUSION = ""


# ===========================================================================
# 下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        # ---- ① TTL：内命中、外失效 -------------------------------------
        clock = FakeClock()
        cache = TtlCache(ttl_ms=5000.0, clock=clock, threshold=0.72, entity_guard=True)
        cache.put(Q1, A1, "large", 1200, 40)

        assert cache.get(Q1).kind == "exact", "刚写进去就该精确命中"
        print("    ① TTL = 5000ms")
        print(f"       t=0.0s  问「{Q1}」→ exact 命中 ✅（TTL 内）")

        clock.advance(4.0)
        look = cache.get("帮我查一下订单 A1001 到哪里了")
        assert look.hit and look.kind == "semantic", "4 秒还没过期，换个说法也该命中"
        assert cache.expired == 0, "不该有过期条目"
        print(f"       t=4.0s  换个说法问同一件事 → semantic 命中 ✅（还没过期）")

        clock.advance(2.0)                       # 累计 6 秒 > 5 秒
        look = cache.get(Q1)
        assert not look.hit, "6 秒 > TTL，绝不允许命中"
        assert cache.expired == 1, f"应该判死 1 条，实际 {cache.expired}"
        assert cache.entries == [], "过期条目必须被真的清掉，而不是留在缓存里占地方"
        print(f"       t=6.0s  再问「{Q1}」→ {look.kind}（过期，老老实实调模型）✅")
        print(f"       累计过期 {cache.expired} 条；缓存里还剩 {len(cache.entries)} 条")
        print()

        # ---- ② 写失效：按实体作废，且只删该删的 -------------------------
        clock2 = FakeClock()
        cache2 = TtlCache(ttl_ms=60_000.0, clock=clock2)
        cache2.put(Q1, A1, "large", 1200, 40)
        cache2.put(Q2, A2, "large", 1200, 40)
        removed = cache2.invalidate_entities(entities_of("订单 A1001 到哪了？"))
        assert removed == 1, f"只该作废 A1001 那条，实际删了 {removed} 条"
        assert not cache2.get(Q1).hit, "A1001 必须已经不在了"
        assert cache2.get(Q2).kind == "exact", "A1002 那条不许被误伤"
        print("    ② 写失效：用户改了 A1001 的收货地址")
        print(f"       invalidate_entities(['1001', 'A1001']) → 作废 {removed} 条")
        print(f"       再问 A1001 → {cache2.get(Q1).kind}（拒绝命中）")
        print(f"       再问 A1002 → {cache2.get(Q2).kind}（没被误伤）✅")
        print("       ★ 注意 A1001 那次不是 miss 而是 entity_blocked：")
        print("         缓存里还剩 A1002 那条相似的答案，实体闸门替我们挡住了它。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print()
    print("    ★ 两个问题想清楚了吗：")
    print("      哪些缓存必须失效 → 任何被写操作影响到的实体（订单状态、收货地址、价格……）")
    print("      过期时长设多少   → 由业务能容忍多旧的数据决定，不是技术决定：")
    print("                        订单状态可能 5 分钟，商品价格可能 10 秒，汇率可能 1 秒")
    print(f"    你的结论：{CONCLUSION or '（还没写 —— 写在文件里的 CONCLUSION 那一行）'}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
