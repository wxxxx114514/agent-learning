r"""第 06 章 · 练习 2 / 5 · 做一份迷你评测集：先有数字，再做优化

【要做什么】
  **做一份迷你评测集。**
  写一个 `EVAL = [(问题, 应命中的文档标题), ...]`，至少 10 条，
  其中包含 3 条**该拒答**的。然后写一个 `evaluate()` 统计 top-1 命中率与拒答正确率。

【已经给你了】
  · RETRIEVER：已经把《云雀科技 · 客户服务手册》建好索引的检索器（7 篇文档）
  · 语料标题清单 DOCS：退货与换货政策 / 发票与报销 / 配送与时效 / 会员等级与权益 /
                      售后响应时效（SLA）/ 保修与维修 / 数据与隐私
  · evaluate() 的循环、计数、除法都写好了 —— 你只需要补「一条用例算不算答对」
  · MIN_SCORE 就是拒答闸门：检索最高分低于它 → 没有命中 → 该拒答

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch06_rag\ex2_mini_eval.py
  3. 验收本章：py scripts\run_all_checks.py 06
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import kv, note, warn                        # noqa: E402
from stages.stage06_rag.demo import DOCS, RETRIEVER            # noqa: E402
from stages.stage06_rag.rag import Hit                         # noqa: E402

TOP_K, MIN_SCORE = 3, 2.0


def search(question: str) -> list[Hit]:
    """检索一个问题，返回命中列表（空 = 该拒答）。不用改。"""
    return RETRIEVER.search(question, top_k=TOP_K, min_score=MIN_SCORE)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
EVAL: list[tuple[str, str | None]] = [
    # TODO ① ── 写至少 10 条评测用例：格式 (问题, 应命中的文档标题)
    #   该拒答的用例，期望值写 None（问一个手册里根本没有的东西）。
    #   可用标题：退货与换货政策 / 发票与报销 / 配送与时效 / 会员等级与权益 /
    #             售后响应时效（SLA）/ 保修与维修 / 数据与隐私
    #
    #   ↓↓↓ 在下面写你的评测集 ↓↓↓
    ("无理由退货是几天？", "退货与换货政策"),
    ("退货运费谁承担？", "退货与换货政策"),
    ("电子发票多久发到邮箱？", "发票与报销"),
    ("修改发票抬头有什么时限？", "发票与报销"),
    ("加急配送要多久？", "配送与时效"),
    ("金卡会员有什么权益？", "会员等级与权益"),
    ("工单多久给解决方案？", "售后响应时效（SLA）"),
    ("整机保修多久？", "保修与维修"),
    ("数据注销后多久删除？", "数据与隐私"),
    ("员工内购折扣是多少？", None),
    ("支持比特币付款吗？", None),
    ("CEO 的私人手机号是多少？", None),
    #   ↑↑↑ 你的评测集 ↑↑↑
]


def is_correct(hits: list[Hit], expect: str | None) -> bool:
    """TODO ② ── 一条评测用例算不算答对？

      · expect is None（该拒答）：检索结果为空 → 对，否则 → 错
      · 否则（该命中）        ：检索结果非空，且 top-1 的文档标题 == expect → 对
      提示：hits 是 Retriever.search() 的返回值，元素是 Hit；文档标题在 h.chunk.doc。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案（3~4 行）↓↓↓
    raise NotImplementedError("练习 2 · TODO ②  is_correct")
    # ↑↑↑ 你的答案 ↑↑↑
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def evaluate(cases: list[tuple[str, str | None]]) -> tuple[float, float]:
    """跑评测集，返回 (top-1 命中率, 拒答正确率)。不用改。"""
    hit = answered = refused_ok = n_refuse = 0
    rows: list[tuple[str, str, str, bool]] = []
    for question, expect in cases:
        hits = search(question)
        good = bool(is_correct(hits, expect))
        if expect is None:
            n_refuse += 1
            refused_ok += good
            got = "（无命中 = 拒答）" if not hits else f"《{hits[0].chunk.doc}》"
            want = "（该拒答）"
        else:
            answered += 1
            hit += good
            got = f"《{hits[0].chunk.doc}》" if hits else "（无命中）"
            want = f"《{expect}》"
        rows.append((question, want, got, good))
    print(f"  {'问题':<24}{'期望':<22}{'实际':<22}判定")
    print("  " + "-" * 78)
    for question, want, got, good in rows:
        print(f"  {question:<24}{want:<22}{got:<22}{'✅' if good else '❌'}")
    print()
    rate_1 = hit / max(answered, 1)
    rate_r = refused_ok / max(n_refuse, 1)
    kv("评测集规模", f"{len(cases)} 条（该命中 {answered} / 该拒答 {n_refuse}）")
    kv("top-1 命中率", f"{hit}/{answered} = {rate_1:.1%}")
    kv("拒答正确率", f"{refused_ok}/{n_refuse} = {rate_r:.1%}")
    print()
    note("这就是第 10 章评估框架的雏形：**先有数字，再做优化**。")
    warn("有了它，你改 size / overlap / min_score 时才不是凭感觉 —— 每次改完跑一遍，看指标是涨还是跌。")
    return rate_1, rate_r


def check() -> str:
    if len(EVAL) < 10:
        raise NotImplementedError(f"练习 2 · TODO ① 评测集至少 10 条（现在 {len(EVAL)} 条）")
    n_refuse = sum(1 for _, expect in EVAL if expect is None)
    if n_refuse < 3:
        raise NotImplementedError(
            f"练习 2 · TODO ① 至少 3 条「该拒答」的用例（期望值写 None），现在 {n_refuse} 条")
    bad_title = [want for _, want in EVAL if want is not None and want not in {d.title for d in DOCS}]
    if bad_title:
        warn(f"这些期望标题在语料里不存在，永远不可能命中：{bad_title}")

    print("\n" + "=" * 66)
    print("  迷你评测集：top-1 命中率 + 拒答正确率")
    print("=" * 66)
    rate_1, rate_r = evaluate(EVAL)
    return f"top-1 命中率 {rate_1:.1%} / 拒答正确率 {rate_r:.1%}（{len(EVAL)} 条用例）"


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
