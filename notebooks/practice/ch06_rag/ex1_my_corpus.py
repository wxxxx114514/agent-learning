r"""第 06 章 · 练习 1 / 5 · 换一份语料，亲手跑通「切块 → 建索引 → 检索」

【要做什么】
  **换一份语料。**
  把 `DOCS` 换成你自己的文档（周报、课程笔记、产品说明书）—— 注意保持「标题 + 若干条列表项」的结构。
  然后跑 ④ 和 ⑤ 两格，看检索效果如何，并找一个「答非所问」的例子。

【已经给你了】
  · SAMPLE_CORPUS：一份「标题 + 列表项」样例语料（先拿它跑一遍，看清输出长什么样）
  · build_index()：把 (标题, [条目…]) 变成 (文档, 检索器)，省掉自己拼字符串的杂活
  · 本章真实 API：Document / build_chunks / Retriever / tokenize（stages/stage06_rag/rag.py）
  · CONTROL_QUERIES：三条对着样例语料的问题，用来对照

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch06_rag\ex1_my_corpus.py
  3. 验收本章：py scripts\run_all_checks.py 06
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import kv, note, warn                      # noqa: E402
from stages.stage06_rag.rag import (                         # noqa: E402
    Document, Retriever, build_chunks, tokenize,
)

CHUNK_SIZE, CHUNK_OVERLAP = 150, 40      # 和课程 demo 一致
TOP_K, MIN_SCORE = 3, 2.0                # MIN_SCORE 就是「拒答闸门」

# 样例语料：结构必须是 (标题, [条目, 条目, …])。条目不用自己加 "- "。
SAMPLE_CORPUS: list[tuple[str, list[str]]] = [
    ("退货与换货政策",
     ["自签收之日起 15 天内，商品未拆封可无理由退货。",
      "定制类商品不支持无理由退货。",
      "退货审核通过后 3 个工作日内原路退款。"]),
    ("发票与报销",
     ["电子发票在订单完成后 24 小时内发送到订单预留邮箱。",
      "需要修改发票抬头的，请在开票后 7 天内提交工单。"]),
    ("会员等级与权益",
     ["金卡会员：累计消费满 10000 元，享受 9 折优惠与专属客服通道。",
      "积分有效期 24 个月，逾期未使用自动清零。"]),
]

CONTROL_QUERIES = ["无理由退货是几天？", "修改发票抬头有什么时限？", "员工内购折扣是多少？"]


def build_index(corpus: list[tuple[str, list[str]]]) -> tuple[list[Document], Retriever]:
    """把 (标题, [条目…]) 变成 (文档列表, 检索器)。不用改。"""
    docs = [Document(title, "\n".join(f"- {line}" for line in lines)) for title, lines in corpus]
    chunks = build_chunks(docs, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    return docs, Retriever(chunks)


def show(queries: list[str], retriever: Retriever, indent: str = "    ") -> None:
    """对每个问题打印 top-K 检索结果。不用改。"""
    for question in queries:
        hits = retriever.search(question, top_k=TOP_K, min_score=MIN_SCORE)
        if not hits:
            print(f"{indent}「{question}」 → 无命中（最高分没过闸门 {MIN_SCORE}）—— 这是**拒答**")
            continue
        print(f"{indent}「{question}」")
        for rank, h in enumerate(hits, 1):
            preview = h.chunk.text.replace("\n", " / ")[:46]
            print(f"{indent}   [片段 {rank}]《{h.chunk.doc}》块#{h.chunk.id} "
                  f"得分 {h.score:.2f} │ {preview}…")


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
MY_CORPUS: list[tuple[str, list[str]]] = [
    # TODO ① ── 把语料换成你自己的：至少 3 个标题，每个标题至少 2 条条目。
    #   结构：(标题, [条目, 条目, …])，照着 SAMPLE_CORPUS 的格式写。
    #   建议用你的周报 / 课程笔记 / 产品说明书 —— 越像真实资料越好。
    #
    #   ↓↓↓ 在下面写你的语料 ↓↓↓

    #   ↑↑↑ 你的语料 ↑↑↑
]

MY_QUERIES: list[str] = [
    # TODO ② ── 写 3~4 个「对着你自己的语料」的问题（最后一个故意问语料里没有的东西）
    #   ↓↓↓ 在下面写你的问题 ↓↓↓

    #   ↑↑↑ 你的问题 ↑↑↑
]
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def check() -> str:
    if len(MY_CORPUS) < 3:
        raise NotImplementedError("练习 1 · TODO ① 语料至少要有 3 个标题（现在是空的或不够）")
    if any(len(lines) < 2 for _, lines in MY_CORPUS):
        raise NotImplementedError("练习 1 · TODO ① 每个标题至少 2 条条目（列表项结构别丢）")
    if not MY_QUERIES:
        raise NotImplementedError("练习 1 · TODO ② 至少写 3 个问题（记得留一个问不出来的）")

    print("\n" + "=" * 66)
    print("  ① 先看样例语料：链路长什么样")
    print("=" * 66)
    docs, retriever = build_index(SAMPLE_CORPUS)
    kv("样例语料", f"{len(docs)} 篇 / {retriever.size} 块")
    print()
    show(CONTROL_QUERIES, retriever)
    print()
    note("分词长这样（中文按字符二元组）：" + str(tokenize(CONTROL_QUERIES[0]))[:64] + " …")

    print("\n" + "=" * 66)
    print("  ② 换成你的语料：同一套代码，跑你自己的文档")
    print("=" * 66)
    my_docs, my_retriever = build_index(MY_CORPUS)
    kv("你的语料", f"{len(my_docs)} 篇 / {my_retriever.size} 块")
    for d in my_docs:
        print(f"        《{d.title}》 {len(d.text)} 字")
    print()
    show(MY_QUERIES, my_retriever)
    print()
    note("★ 从上面挑一条「答非所问」的，判断它属于哪一类问题：")
    print("        · 切块问题（一句话被切开了）      → 调 size / overlap")
    print("        · 分词问题（关键词被切碎/没保留）→ 看 token 列表")
    print("        · 词面匹配问题（说法不同）        → 查询扩展 / 向量检索")
    warn("先归类，再改参数 —— 否则你只是在瞎试。")

    missed = sum(1 for q in MY_QUERIES
                 if not my_retriever.search(q, top_k=TOP_K, min_score=MIN_SCORE))
    return f"你的语料：{len(my_docs)} 篇 / {my_retriever.size} 块；{len(MY_QUERIES)} 个问题里 {missed} 个拒答"


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
