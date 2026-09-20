r"""第 06 章 · 练习 4 / 5 · 加一个重排（rerank）：BM25 召回 10 条，再精排出 3 条

【要做什么】
  **加一个重排（rerank）。**
  先用 BM25 召回 top-10，再用一个更严格的打分（例如「查询词覆盖率 + 位置加权」）重排取 top-3，
  对比重排前后的 top-1 命中率。

【已经给你了】
  · RETRIEVER：已建好索引的检索器（《云雀科技 · 客户服务手册》）
  · EVAL：12 条评测用例 (问题, 答案里必须出现的关键字)
  · bm25_top()：第一段召回（BM25 top-10），不用改
  · measure()：命中率统计 + 表格打印，不用改 —— 你只要写 rerank()
  · tokenize()：中文按字符二元组切；检索和打分都用它

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch06_rag\ex4_rerank.py
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

RECALL_K = 10      # 第一段召回条数
TOPN = 3           # 重排后保留条数

# (问题, 答案里必须出现的关键字)
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


def bm25_top(query: str, k: int = RECALL_K) -> list[Hit]:
    """第一段：BM25 召回 top-k（不用改）。"""
    return RETRIEVER.search(query, top_k=k, min_score=0.0)


def answer_rank(query: str, key: str, hits: list[Hit]) -> int | None:
    """答案关键字在第几条候选里（1 开始；不在候选集里返回 None）。不用改。"""
    for i, h in enumerate(hits, 1):
        if key in h.chunk.text:
            return i
    return None


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def rerank(query: str, hits: list[Hit], top_n: int = TOPN) -> list[Hit]:
    """TODO ① ── 更严格的打分 + 重排，返回前 top_n 条。

    提示里的打分方式（「查询词覆盖率 + 位置加权」）：
        q = set(tokenize(query))                 # 查询词（中文是字符二元组）
        t = set(tokenize(h.chunk.text))          # 这一块里的词
        coverage = len(q & t) / max(len(q), 1)   # 覆盖得越全越好
        position = 1 / (1 + 第一次命中的下标)     # 命中得越靠前越好（没命中记 0）
        score    = coverage + 0.3 * position

    返回：按 score 从高到低排好的 Hit 列表，取前 top_n 条（hits 里每条是 Hit）。
    小提示：用 sorted(hits, key=...) 是稳定排序，同分时保持 BM25 的原顺序。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案（5~8 行）↓↓↓
    raise NotImplementedError("练习 4 · TODO ①  rerank")
    # ↑↑↑ 你的答案 ↑↑↑
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def measure(ranker, title: str) -> tuple[int, list[int]]:
    """跑一遍评测集，返回 (top-1 命中数, 每条答案在候选集里的位置)。不用改。"""
    hits_ok = 0
    ranks: list[int] = []
    print(f"  {title}")
    print(f"    {'问题':<24}{'答案块位置':<12}{'top-1 命中'}")
    print("    " + "-" * 52)
    for question, key in EVAL:
        cand = bm25_top(question)
        ranked = ranker(question, cand)
        rank = answer_rank(question, key, cand)
        ok = bool(ranked) and key in ranked[0].chunk.text
        hits_ok += ok
        ranks.append(rank or 0)
        print(f"    {question:<24}{('第 ' + str(rank) + ' 条') if rank else '不在候选集':<12}"
              f"{'✅' if ok else '❌'}")
    print(f"    → top-1 命中率：{hits_ok}/{len(EVAL)} = {hits_ok / len(EVAL):.1%}")
    print()
    return hits_ok, ranks


def check() -> str:
    print("\n" + "=" * 66)
    print("  召回 10 → 重排 3：规则版 rerank 到底有没有收益？")
    print("=" * 66)
    before, ranks = measure(lambda q, c: c[:TOPN], "① 重排前（直接取 BM25 前 3）")
    after, _ = measure(lambda q, c: rerank(q, c, TOPN), "② 重排后（覆盖率 + 位置加权）")

    recall_ok = sum(1 for r in ranks if r)
    kv("候选集召回率（答案块在 top-10 里的比例）", f"{recall_ok}/{len(EVAL)} = {recall_ok / len(EVAL):.1%}")
    kv("top-1 命中率（重排前 → 重排后）", f"{before}/{len(EVAL)} → {after}/{len(EVAL)}")
    print()

    sample = EVAL[0][0]
    cand = bm25_top(sample)
    print(f"  看一条具体的：「{sample}」")
    print(f"    BM25 前 3 块号  ：{[h.chunk.id for h in cand[:TOPN]]}")
    print(f"    重排后前 3 块号：{[h.chunk.id for h in rerank(sample, cand, TOPN)]}")
    print()
    if after > before:
        warn("重排有效：说明答案本来就在候选集里，只是 BM25 的排序没把它放前面。")
    elif after == before and recall_ok == len(EVAL):
        note("重排没有收益，**但这不是你写错了**：候选召回率已经是 100%，")
        note("说明这条链路的瓶颈不在排序 —— 小语料 + BM25 本来就已经排得够好。")
        warn("生产里重排的收益出现在「候选集有噪声、正确答案排在 2~5 位」的时候。")
    else:
        warn("重排反而掉了分：检查一下你的打分 —— 是不是漏了归一化，或者位置项权重过大？")
    bullet("重排的收益通常比「换一个更好的检索模型」来得更快、更便宜。")
    bullet("但先用规则版验证收益是否存在 —— 如果规则重排都没收益，问题不在排序，而在召回。")
    return (f"召回率 {recall_ok}/{len(EVAL)}；top-1：重排前 {before} → 重排后 {after}")


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
