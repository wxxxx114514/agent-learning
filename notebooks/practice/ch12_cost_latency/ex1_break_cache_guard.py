r"""第 12 章 · 练习 1 / 5 · 打破缓存护栏，亲手做一次「假命中」事故

【要做什么】
  **打破缓存护栏，观察会发生什么（必做）。**

  把第 ③ 节的 `THRESHOLD` 改成 `0.5`、再依次把 `ENTITY_GUARD` 改成 `False`，重跑那一格。
  然后加一句 `订单 A1003 到哪了？`，看实体约束是否兜住了它。

  最后回答：为什么「宁可命中率低一点，也不能答错对象」？

【已经给你了】
  · 第 12 章真正的缓存零件：`SemanticCache` / `entities_of` / `similarity`（来自 stage12 demo）
  · `build_cache(阈值, 实体约束)`：一个只装着「订单 A1001」那条答案的缓存
  · 四组配置 × 六个提问，以及打印表格用的 `table()`

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch12_cost_latency\ex1_break_cache_guard.py
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
    SemanticCache, entities_of, similarity, table,
)

Q_CACHED = "订单 A1001 到哪了？"                      # 缓存里已经有的那条问题
A_CACHED = "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。"
PT, CT = 1200, 40                                    # 上次那次调用花掉的 token

# 四组配置：(相似度阈值, 实体硬约束开关)
CONFIGS = [(0.72, True), (0.72, False), (0.50, True), (0.50, False)]

# 六个提问。前两个是「同一个对象、换个说法」，中间三个是「另一个对象」，
# 最后一个连相似度都够不着 —— 它们分别探测两道闸门的不同侧面。
QUESTIONS = [
    ("原问题", "订单 A1001 到哪了？"),          # 归一化后完全一致 → 精确命中
    ("换说法", "帮我查一下订单 A1001 到哪里了"),  # 相似度 0.80
    ("只问物流", "订单 A1001 的物流"),           # 相似度 0.67 —— 落在两个阈值之间
    ("A1002", "订单 A1002 到哪了？"),           # 相似度 0.78，但实体不同！
    ("A1003", "订单 A1003 到哪了？"),           # 同上，另一个订单
    ("B2043", "订单 B2043 到哪了？"),           # 相似度 0.33，够不着任何阈值
]


def build_cache(threshold: float, entity_guard: bool) -> SemanticCache:
    """建一个只装着 Q_CACHED 一条答案的缓存（已经写好，不用改）。"""
    cache = SemanticCache(threshold=threshold, entity_guard=entity_guard)
    cache.put(Q_CACHED, A_CACHED, "large", PT, CT)
    return cache


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def probe(threshold: float, entity_guard: bool, question: str) -> str:
    """TODO ① ── 用给定配置建缓存，去问 question，返回这次查询的「结果类型」。

    要求：返回一个字符串，取值只能是 exact / semantic / miss / entity_blocked 之一。
    提示：`build_cache(阈值, 实体约束)` 已经给你了；
          再 `cache.get(question)` 拿到一个 CacheLookup，返回它的 `.kind`。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO ①  probe")
    # ↑↑↑ 你的答案 ↑↑↑


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   为什么「宁可命中率低一点，也不能答错对象」？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        rows = []
        for threshold, guard in CONFIGS:
            rows.append([f"阈值={threshold} 实体={'开' if guard else '关'}"]
                        + [probe(threshold, guard, q) for _, q in QUESTIONS])
        table(["配置"] + [name for name, _ in QUESTIONS], rows)
        print()

        # ① 实体闸门：相似度说「是同一个问题」，实体说「不是同一个对象」
        bad_q = "订单 A1002 到哪了？"
        bad_q3 = "订单 A1003 到哪了？"
        assert probe(0.72, True, bad_q) == "entity_blocked", "开了实体约束，A1002 必须被挡住"
        assert probe(0.72, True, bad_q3) == "entity_blocked", "开了实体约束，A1003 必须被挡住"

        # ② 关掉实体约束 → 假命中（事故现场）
        naive = build_cache(0.72, False)          # ← 故意拆掉护栏
        look = naive.get(bad_q)
        assert look.kind == "semantic" and look.hit, "关掉实体约束后，A1002 会被判成命中"
        print("    ★ 事故现场：")
        print(f"      用户问的是：{bad_q}")
        print(f"      系统答的是：{look.entry.answer}")
        print(f"      相似度 {similarity(bad_q, Q_CACHED):.3f} ≥ 阈值 0.72，"
              f"实体 {sorted(entities_of(bad_q))} ≠ {sorted(entities_of(Q_CACHED))}")
        print("      ↑ 不报错、不变慢、格式正确 —— 只是把 A1001 的信息答给了问 A1002 的人。")
        print()

        # ③ 阈值是「命中率 ↔ 事故面」那根线
        mid_q = "订单 A1001 的物流"
        assert probe(0.72, True, mid_q) == "miss", "0.67 < 0.72，它本来不该命中"
        assert probe(0.50, True, mid_q) == "semantic", "阈值降到 0.5 之后它就会命中"
        print(f"    ★ 「{mid_q}」相似度 {similarity(mid_q, Q_CACHED):.3f}：")
        print("      阈值 0.72 → miss（多花一次调用）；阈值 0.50 → semantic（命中率涨了）")
        print("      阈值越低命中率越高、事故面也越大 —— 它必须用真实流量调，不能拍脑袋。")
        print()

        # ④ 两道闸门是互补的：相似度防「不相干」，实体防「差一点」
        assert probe(0.72, True, "订单 B2043 到哪了？") == "miss", "0.33 连阈值都够不着"
        print("    ★ 订单 B2043 相似度只有 0.33 → 直接 miss：这道门是「相似度」守的。")
        print("      A1002/A1003 相似度 0.78 → 由「实体约束」守。两道门缺一不可。")
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
