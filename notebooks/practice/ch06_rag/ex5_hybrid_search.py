r"""第 06 章 · 练习 5 / 5 · 混合检索：BM25 + 字符级 Jaccard 加权融合

【要做什么】
  **做一次混合检索。**
  给你的检索器加一路「字符级 Jaccard 相似度」，与 BM25 分数加权融合，
  用练习 2 的评测集对比效果。

【已经给你了】
  · RETRIEVER / CHUNKS / BM25_INDEX：索引和语料块都已经建好了
  · EVAL：12 条评测用例 (问题, 答案里必须出现的关键字) —— 和练习 4 同一份
  · all_scores()：把两路的**原始分**都算好（BM25 一路已经能用，Jaccard 一路用你写的函数）
  · bm25_search() / measure()：单路基线和命中率统计，不用改
  · hybrid_search() 的排序、取证、截断都写好了 —— 你只需要填融合公式那一行

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch06_rag\ex5_hybrid_search.py
  3. 验收本章：py scripts\run_all_checks.py 06
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                # noqa: E402
from stages.stage06_rag.demo import RETRIEVER                  # noqa: E402
from stages.stage06_rag.rag import Hit, tokenize               # noqa: E402

TOPN = 3
ALPHA = 0.5                     # BM25 的权重；(1 - ALPHA) 是 Jaccard 的权重
CHUNKS = RETRIEVER.chunks
BM25_INDEX = RETRIEVER.index    # 一个 BM25 实例：BM25_INDEX.score(tokens, i) -> (分数, 明细)

EVAL: list[tuple[str, str]] = [
    ("无理由退货是几天？", "15 天"),
    ("退货运费谁承担？", "客户承担"),
    ("电子发票多久发到邮箱？", "24 小时"),
    ("修改发票抬头有什么时限？", "7 天内"),
    ("加急配送运费是几倍？", "2 倍"),
    ("金卡会员有什么权益？", "9 折"),
    ("工单多久给解决方案？", "72 小时"),
    ("整机保修多久？", "12 个月"),
    ("积分多久清零？", "24 个月"),
    ("生鲜类商品能退货吗？", "不支持退货"),
    ("会员等级什么时候重新核算？", "每月 1 日"),
    ("发票金额按什么算？", "实际支付金额"),
]


def bm25_search(query: str, top_k: int = TOPN) -> list[Hit]:
    """单路基线：只用 BM25。不用改。"""
    return RETRIEVER.search(query, top_k=top_k, min_score=0.0)


def all_scores(query: str) -> tuple[list[float], list[float]]:
    """把两路原始分都算出来（idx 对齐 CHUNKS）。不用改。"""
    tokens = tokenize(query)
    bm25 = [BM25_INDEX.score(tokens, i)[0] for i in range(len(CHUNKS))]
    jac = [char_jaccard(query, c.text) for c in CHUNKS]      # ← 用你写的 TODO ①
    return bm25, jac


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def char_jaccard(query: str, text: str) -> float:
    """TODO ① ── 字符级 Jaccard 相似度 = |交集| / |并集|。

    提示：
        a = set(query)     # 字符集合（中文按单字就够了，零依赖）
        b = set(text)
        return len(a & b) / len(a | b)，**别忘了分母为 0 的保护**（返回 0.0）。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案（3 行）↓↓↓
    raise NotImplementedError("练习 5 · TODO ①  char_jaccard")
    # ↑↑↑ 你的答案 ↑↑↑


def hybrid_search(query: str, top_k: int = TOPN, alpha: float = ALPHA) -> list[Hit]:
    """两路分数归一化后融合，再排序取前 top_k。只有中间一行要你写。"""
    bm25, jac = all_scores(query)
    bm = max(bm25) or 1.0        # 各自的最大值 —— 归一化要用它
    jm = max(jac) or 1.0

    fused: list[tuple[float, int]] = []
    for i, _chunk in enumerate(CHUNKS):
        # TODO ② ── 融合两路分数（就一行）。
        #   目标：alpha * (bm25[i] / bm) + (1 - alpha) * (jac[i] / jm)
        #   ★ 两路必须先各自除以自己的最大值再融合，否则量纲不同，加权毫无意义。
        #   ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ②  融合两路分数")
        #   ↑↑↑ 你的答案 ↑↑↑
        fused.append((score, i))

    fused.sort(key=lambda t: (-t[0], t[1]))          # 同分按块号，保证可复现
    return [Hit(chunk=CHUNKS[i], score=s) for s, i in fused[:top_k]]


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def measure(ranker, title: str) -> int:
    """跑一遍评测集，返回 top-1 命中数。不用改。"""
    ok_count = 0
    print(f"  {title}")
    print(f"    {'问题':<24}{'top-1 命中块':<34}{'判定'}")
    print("    " + "-" * 62)
    for question, key in EVAL:
        ranked = ranker(question)
        ok = bool(ranked) and key in ranked[0].chunk.text
        ok_count += ok
        head = ranked[0] if ranked else None
        got = f"块#{head.chunk.id}《{head.chunk.doc}》" if head else "（无）"
        print(f"    {question:<24}{got:<34}{'✅' if ok else '❌'}")
    print(f"    → top-1 命中率：{ok_count}/{len(EVAL)} = {ok_count / len(EVAL):.1%}")
    print()
    return ok_count


def check() -> str:
    print("\n" + "=" * 66)
    print("  两路分数融合：BM25 vs BM25 + 字符 Jaccard")
    print("=" * 66)
    demo_q = EVAL[0][0]
    bm25, jac = all_scores(demo_q)
    kv("样例问题的 BM25 最高分", f"{max(bm25):.2f}")
    kv("样例问题的 Jaccard 最高分", f"{max(jac):.4f}")
    note("两路量纲差了几个数量级 —— 这就是「必须先归一化」的原因。")
    print()

    single = measure(bm25_search, f"① 只用 BM25（基线，alpha={ALPHA} 时对照）")
    hybrid = measure(hybrid_search, f"② 混合检索（alpha={ALPHA}）")

    print("  同一块上两路分数各是多少（看前 3 块）：")
    for i, h in enumerate(bm25_search(demo_q, TOPN), 1):
        idx = CHUNKS.index(h.chunk)
        print(f"    第 {i} 名 块#{h.chunk.id}：BM25 {bm25[idx]:6.2f}（归一 {bm25[idx] / (max(bm25) or 1):.2f}）"
              f"｜Jaccard {jac[idx]:.4f}（归一 {jac[idx] / (max(jac) or 1):.2f}）")
    print()
    if hybrid > single:
        warn("融合有效：Jaccard 这一路补上了 BM25 漏掉的候选。")
    elif hybrid == single:
        note("两路融合没有提升 —— 小语料下 BM25 已经够强，这是正常结果。")
        note("它的价值在大语料 / 口语化提问（说法和文档不一致）时才显现。")
    else:
        warn("融合掉分了：调 alpha（比如 0.7）、或者把 Jaccard 算在句子级而不是整块上。")
    bullet("这就是 Hybrid Search 的最小版本；向量检索只是把第二路换成一个更聪明的相似度。")
    bullet("别忘了生产里还要配一个 min_score 闸门，否则融合后连无关问题都会给出 top-3。")
    return f"top-1 命中率：BM25 单路 {single}/{len(EVAL)} → 混合检索 {hybrid}/{len(EVAL)}"


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
