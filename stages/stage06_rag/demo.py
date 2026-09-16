"""第 06 章 · RAG 检索增强 —— 检索质量决定上限，生成质量只是下限。

运行：
    py -m stages.stage06_rag.demo
    py -m stages.stage06_rag.demo --list
    py -m stages.stage06_rag.demo --section 4
    py -m stages.stage06_rag.demo --check

本章要回答的问题：
    模型不知道我们公司的退货政策是 15 天还是 7 天 —— 它没见过这份文档。
    硬把文档塞进提示词？贵、慢、改一次要重来。
    RAG 的答案是：**不改模型，改上下文** —— 需要什么，现查现给。

本章要实现一条完整的零依赖 RAG 链路：
    切块 → 建索引（BM25）→ 检索 → 注入 [片段 N] → 带引用作答 → 检索不到就拒答
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check_that, code, essence, kv, note, ok, report,
    section, setup_console, warn,
)
from core.llm import LLM, LLMResponse  # noqa: E402

from stages.stage06_rag.rag import (  # noqa: E402
    REFUSAL, RagAgent, Retriever, build_chunks, build_rag_messages, check_citations,
    cut_sentences, load_documents, tokenize,
)

KB_PATH = Path(__file__).resolve().parent / "knowledge_base.md"

# 切块参数。语料只有几百字，所以块也取得小 —— 真实语料常用 200~500 字。
CHUNK_SIZE = 150
CHUNK_OVERLAP = 40
# 对照实验专用的更小块：只有在"一块装不下一个文档"时，切块边界才会落在句子中间。
# 做这类实验最常见的坑就是块比文档还大 —— 那样两种切法看起来毫无差别。
CHUNK_DEMO_SIZE = 90

# ===========================================================================
# 一、两个假模型：一个"凭记忆编"，一个"只照着资料答"
# ===========================================================================
# 对比是本章的教学主线：同样的模型能力，喂不同的上下文，答案质量天差地别。
# 这正好证明那句话 —— **检索质量决定上限**。


class ParametricBotLLM(LLM):
    """没有任何资料的模型：只能靠"训练数据里的记忆"回答。

    它的答案写死在代码里，代表**模型的先验知识**（真实模型是从训练语料里学来的）。
    注意它答得非常自信 —— 幻觉从来不是"模型在犹豫"，而是"模型很确定地错了"。
    """

    name = "parametric-bot"

    # 模型"以为"的常识（全都是错的，因为这是某家公司的私有政策）
    PRIORS = {
        "退货": "根据《消费者权益保护法》，网购商品一般支持 7 天无理由退货。",
        "发票": "电子发票通常在 1 到 3 个工作日内开具，具体以商家为准。",
        "运费": "退货运费一般由买家承担，这是行业惯例。",
        "保修": "电子产品一般保修 1 年，具体以厂商保修卡为准。",
        "会员": "会员等级通常按消费金额划分，具体规则请咨询客服。",
    }

    def _complete(self, messages, **kwargs):
        question = messages[-1].content
        for key, answer in self.PRIORS.items():
            if key in question:
                return LLMResponse(text=f"Final Answer: {answer}", model=self.model)
        return LLMResponse(text="Final Answer: 关于这个问题，一般情况下的做法是……", model=self.model)


class RagBotLLM(LLM):
    """只读「参考资料」的抽取式答题模型（确定性）。

    真实模型做的是生成式问答，这里用"抽句子"来保证**完全可复现**。
    它的行为刻意做得很"死板"，正好对应系统提示词里的铁律：
        · 只在片段里找答案；
        · 找到就带上出处编号；
        · 找不到就说「资料里没有相关内容」。
    """

    name = "rag-bot"

    def __init__(self, min_overlap: int = 1) -> None:
        super().__init__("mock-rag")
        self.min_overlap = min_overlap
        self.last_prompt = ""

    def _complete(self, messages, **kwargs):
        prompt = messages[-1].content
        self.last_prompt = prompt
        if "没有任何参考资料" in prompt:
            return LLMResponse(text=REFUSAL, model=self.model)

        question = ""
        m = re.search(r"# 问题\s*\n(.+)", prompt)
        if m:
            question = m.group(1).strip()

        blocks = re.findall(r"\[片段\s*(\d+)\]\s*\n(.*?)(?=\n\[片段\s*\d+\]|\n# 问题|\Z)", prompt, re.S)
        q_tokens = set(tokenize(question))
        best: tuple[float, str, int] = (0.0, "", 0)
        for num, body in blocks:
            for sentence in re.split(r"[\n。；;]+", body):
                s = sentence.strip().lstrip("-").strip()
                # 「来源：《…》」是出处标注，不是答案 —— 真实模型也会被这种行干扰，
                # 所以显式跳过它（这类"格式行"混进候选集是 RAG 里很常见的一类脏答案）。
                if len(s) < 6 or s.startswith("来源："):
                    continue
                overlap = len(q_tokens & set(tokenize(s)))
                if overlap > best[0]:
                    best = (float(overlap), s, int(num))
        overlap, sentence, num = best
        if overlap < self.min_overlap or not sentence:
            return LLMResponse(text=f"Final Answer: {REFUSAL}", model=self.model)
        return LLMResponse(text=f"Final Answer: {sentence}。[片段 {num}]", model=self.model)


# ===========================================================================
# 二、语料与索引（模块级构建一次，所有小节共用）
# ===========================================================================

def build_index(size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> tuple[list, Retriever]:
    docs = load_documents(KB_PATH)
    chunks = build_chunks(docs, size=size, overlap=overlap)
    return docs, Retriever(chunks)


DOCS, RETRIEVER = build_index()

# ===========================================================================
# 三、教学小节
# ===========================================================================


def demo_no_rag() -> None:
    section("反面教材：没有检索，模型只能编", "①")
    question = "你们公司的无理由退货是几天？"
    kv("用户提问", question)
    print()

    bot = ParametricBotLLM()
    from core.message import Message

    naive = bot.complete([Message.user(question)]).text.replace("Final Answer: ", "")
    kv("无检索 · 模型回答", naive)
    print()
    warn("它答得**非常自信**，而且是错的 —— 我们公司的政策是 15 天，不是 7 天。")
    warn("幻觉最危险的地方就在这里：不是模型在犹豫，而是模型很确定地错了。")
    print()
    note("为什么它会错？因为这份《客户服务手册》**从来没有出现在它的训练数据里**：")
    bullet("私有政策（15 天 / 2000 元门槛 / 72 小时 SLA）—— 训练语料里不可能有；")
    bullet("昨天刚改的价格表、刚上线的产品文档 —— 模型的知识永远停在训练截止日；")
    bullet("公司内部规范、你的个人笔记 —— 根本没公开过。")
    print()
    note("三条出路，各自代价不同：")
    print(f"      {'方案':<14}{'代价':<34}{'什么时候用'}")
    print("      " + "-" * 66)
    print(f"      {'微调':<14}{'贵、慢、改一次要重训，且仍会编':<34}{'风格/能力对齐'}")
    print(f"      {'全塞进提示词':<14}{'token 爆炸、贵、每次都要重发':<34}{'资料极少的场景'}")
    print(f"      {'RAG（本章）':<14}{'要建检索链路，检索不好就白搭':<34}{'知识量大且会变'}")
    print()

    agent = RagAgent(RETRIEVER, RagBotLLM(), min_score=2.0)
    rag = agent.ask(question)
    kv("RAG · 检索到的片段", len(rag.hits))
    for line in rag.sources:
        print(f"        {line}")
    print(f"        检索到第 1 条 = 《{rag.hits[0].chunk.doc}》，回答里的 [片段 1] 指的就是它"
          if rag.hits else "")
    kv("RAG · 回答", rag.answer)
    print()
    ok("同一个问题：没有资料时它只能编，有资料时它答得又准又可溯源。")


def demo_chunking() -> None:
    section("第一步：切块 —— 粒度决定检索的上限", "②")
    docs = load_documents(KB_PATH)
    kv("语料文档数", len(docs))
    for d in docs:
        print(f"        《{d.title}》 {len(d.text)} 字")
    print()

    note("为什么不能整篇塞进去？")
    bullet("一篇 200 字里只有一句是答案，其余全是干扰（稀释注意力，第 05 章讲过）；")
    bullet("检索的粒度 = 引用的粒度。整篇文档做引用，等于没有引用。")
    print()

    chunks = build_chunks(docs, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    kv("切块结果", f"{len(chunks)} 块（size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}）")
    code("\n".join(f"[片段 {c.id}] 《{c.doc}》 ({c.tokens} token)\n    {c.text[:70]}…"
                   for c in chunks[:3]), indent=4)
    print()

    # ---- 朴素切法 vs 语义切法 ------------------------------------------
    note("**怎么切？** 先看新手最常写的那一版：按固定字数硬切（chunk_fixed）。")
    note("再看按语义单元打包的那一版（chunk_text，本章默认）。")
    print()
    print(f"      {'切法':<26}{'块数':<8}{'被切断的句子':<14}{'自检索完整命中'}")
    print("      " + "-" * 66)
    rows = [
        (f"硬切 size={CHUNK_DEMO_SIZE} overlap=0", "fixed", 0),
        (f"硬切 size={CHUNK_DEMO_SIZE} overlap=40", "fixed", 40),
        (f"按语义单元 size={CHUNK_DEMO_SIZE} overlap=0", "unit", 0),
        (f"按语义单元 size={CHUNK_DEMO_SIZE} overlap=40", "unit", 40),
    ]
    for label, mode, ov in rows:
        cs = build_chunks(docs, size=CHUNK_DEMO_SIZE, overlap=ov, mode=mode)
        broken = _count_broken_sentences(cs, docs)
        hit, total = _self_recall(docs, mode, CHUNK_DEMO_SIZE, ov)
        print(f"      {label:<26}{len(cs):<8}{broken:<14}{hit}/{total}")
    print()
    warn("「自检索完整命中」= 拿语料里每个句子本身去检索，命中的片段里是否还找得到完整的那句。")
    warn("硬切 + 不重叠时它掉得最狠 —— 句子被砍成两半，检索到的那半块根本答不了问题。")
    print()
    warn(f"注意块大小是刻意调小的（{CHUNK_DEMO_SIZE} < 文档长度）：块比文档还大的话，")
    warn("两种切法看起来毫无差别 —— 这是做切块实验时最常踩的一个坑。")
    warn("看第一行：硬切 + 不重叠，会把「定制类商品不支持无理由退货」拦腰砍成两半。")
    note("后果不是「检索不到」，而是更糟的**检索到了半句**：")
    bullet("上半句「…定制类商品不支持」丢了宾语，模型可能理解成「支持」；")
    bullet("下半句「无理由退货。已拆封但…」丢了主语，模型会张冠李戴到别的商品上；")
    bullet("而且模型**不知道自己漏了** —— 它只会自信地基于半句话作答。")
    print()
    note("两个修法，成本不同：")
    bullet("① 加重叠（overlap）：让每个事实至少完整地出现在一个块里 —— 便宜、通用、必做；")
    bullet("② 按语义单元切：从根本上避免切断句子，但需要结构化的语料（Markdown/HTML 友好）；")
    bullet("生产里通常两个都用：先按语义切，再给相邻块加一点重叠做保险。")
    print()
    note("工程上的经验值（先照抄，再用评测集调，见第 10 章）：")
    print(f"      {'参数':<14}{'常见取值':<24}{'调大的后果'}")
    print("      " + "-" * 62)
    print(f"      {'块大小':<14}{'200~500 字':<24}{'掺入无关内容，检索精度下降'}")
    print(f"      {'重叠':<14}{'块大小的 10%~25%':<24}{'块数变多、索引变大、召回重复'}")
    print(f"      {'最小块':<14}{'不低于 1 个语义单元':<24}{'碎片块永远检索不到'}")
    print()
    note(f"本章语料只有几百字，所以 size 取 {CHUNK_SIZE}（比生产值小）—— "
         f"调参要跟着语料走，没有放之四海皆准的数字。")


def _self_recall(docs, mode: str, size: int, overlap: int) -> tuple[int, int]:
    """端到端度量：拿每个句子本身当查询，检索到的块里还找不找得到**完整的那句**。

    这是"切块质量"最诚实的度量 —— 不看切得多漂亮，只看检索回来能不能用。
    """
    chunks = build_chunks(docs, size=size, overlap=overlap, mode=mode)
    retriever = Retriever(chunks)
    hit = total = 0
    for doc in docs:
        for sentence in cut_sentences(doc.text):
            total += 1
            hits = retriever.search(_norm(sentence)[:10], top_k=1)
            if hits and _norm(sentence) in _norm(hits[0].chunk.text):
                hit += 1
    return hit, total


def _norm(text: str) -> str:
    """比较时统一去掉空白 —— 因为"硬切"那种朴素实现会把换行和空格全部删掉，
    不归一化就没法公平比较两种切法（这是做对照实验时很容易忽略的一个坑）。"""
    return re.sub(r"\s+", "", text or "")


def _count_broken_sentences(chunks, docs) -> int:
    """统计有多少句子"**在任何一块里都不完整**" —— 切块切断事实的直接证据。

    判据要够严：必须是整句都能在某一块里找到。用"前 N 个字能对上"来判会严重低估 ——
    一句话被砍成 20+10 两截时，前 15 个字仍然在前半截里，看起来"没断"，其实已经断了。
    """
    texts = [_norm(c.text) for c in chunks]
    broken = 0
    for doc in docs:
        for sentence in cut_sentences(doc.text):
            s = _norm(sentence)
            if not any(s in t for t in texts):
                broken += 1
    return broken


def _fact_intact(chunks, fact: str) -> bool:
    return any(_norm(fact) in _norm(c.text) for c in chunks)


def demo_bm25() -> None:
    section("第二步：BM25 打分 —— 为什么是这一块，而不是那一块", "③")
    note("BM25 只问一句话：**这个词在这篇文档里出现得多，且在别的文档里出现得少，就重要。**")
    code("score(q,d) = Σ  IDF(t) ·  tf(t,d)·(k1+1) / [ tf(t,d) + k1·(1-b+b·|d|/avgdl) ]\n"
         "              t∈q\n\n"
         "IDF(t) = ln(1 + (N - n(t) + 0.5) / (n(t) + 0.5))    ← 稀有词权重高\n"
         "k1 ≈ 1.5  词频饱和：出现 10 次不比 3 次重要 10 倍\n"
         "b  ≈ 0.75 长度归一化：长文档天然更容易命中，要惩罚", indent=4)
    print()

    # ---- 分词先看一眼 --------------------------------------------------
    sample = "退货运费由客户承担"
    kv("分词示例", f"「{sample}」→ {tokenize(sample)}")
    kv("中英混排", f"「订单 A1001 的 SLA」→ {tokenize('订单 A1001 的 SLA')}")
    note("中文用字符二元组（无需分词库），英文和数字整体保留（订单号不能被拆碎）。")
    print()

    # ---- 检索并解释得分 -------------------------------------------------
    question = "退货运费谁承担？"
    kv("查询", question)
    kv("查询分词", tokenize(question))
    print()
    hits = RETRIEVER.search(question, top_k=3)
    for h in hits:
        print(f"      [片段 {h.chunk.id}] 得分 {h.score:.3f}  《{h.chunk.doc}》")
        print(f"          {h.chunk.preview(56)}")
        for term, part in h.terms[:4]:
            print(f"            + {term:<6} {part:.3f}")
    print()
    note("IDF 的作用：")
    bullet("「退货」这种词只在少数片段出现 → IDF 高 → 一命中就是强信号；")
    bullet("「我们」「可以」这种词到处都是 → IDF 接近 0 → 几乎不影响排序。")
    print()
    note("BM25 的局限（知道边界才能选对工具）：")
    bullet("不懂同义词：「退钱」召不回「退款」；")
    bullet("不懂语义：「怎么把钱要回来」召不回「退款流程」；")
    bullet("不懂否定：「不能退货吗」和「能退货吗」的分数几乎一样。")
    print()
    note("实测一个失败案例 —— 换个问法，检索就会「答非所问」：")
    for q in ("无理由退货是几天？", "退货政策是几天？"):
        top = RETRIEVER.search(q, top_k=1)
        got = top[0].chunk.preview(34) if top else "（无命中）"
        print(f"      {q:<14} → {got}")
    print()
    note("第二句问的是同一件事，但「几天」和正文里的「15 天内」在字面上毫无重叠，")
    note("BM25 只能退而求其次，把「退货」出现次数最多的那条（退款/赔付）排到了第一。")
    note("这正是向量检索（embedding）要解决的问题 —— 生产里常见的是 Hybrid：")
    note("BM25（精确匹配）+ 向量（语义近似）→ 融合重排。")
    print()
    note("本章选 BM25 的原因不是它最好，而是它**零依赖、可解释、可复现** ——")
    note("你要先看得懂打分，才有能力判断向量检索到底改善了什么。")


def demo_end_to_end() -> None:
    section("第三步：端到端 —— 检索 → 注入 → 带引用作答", "④")
    questions = [
        "无理由退货是几天？",
        "发票抬头能改吗？",
        "金卡会员有什么权益？",
        "账号被盗了多久能响应？",
    ]
    agent = RagAgent(RETRIEVER, RagBotLLM(), top_k=3, min_score=2.0)
    for q in questions:
        ans = agent.ask(q)
        print()
        kv("问题", q)
        if ans.refused:
            kv("回答", ans.answer)
            continue
        # 打印时把"引用编号"和"语料块编号"都标出来 —— 这两者不是一回事
        kv("检索", " | ".join(f"[{i}]#{h.chunk.id}《{h.chunk.doc}》({h.score:.1f})"
                             for i, h in enumerate(ans.hits, 1)))
        kv("回答", ans.answer)
        problems = check_citations(ans)
        kv("引用校验", "通过" if not problems else problems)
    print()
    note("★ 注意「引用编号」和「语料块编号」的区别：")
    bullet("回答里的 [片段 1] 指的是**本次检索结果的第 1 条**（不是语料库里的第 1 块）；")
    bullet("上面那行 `[1]#3《发票与报销》` 的意思是：引用编号 1 ↔ 语料块 #3；")
    bullet("混淆这两者，溯源就会指到一篇完全无关的文档，而且**看起来一切正常**。")
    print()
    note("注入提示词的实际样子（`--section 4` 里打印的是真实构造结果）：")
    ans = agent.ask("无理由退货是几天？")
    messages = build_rag_messages("无理由退货是几天？", ans.hits)
    code(messages[1].content[:520] + "……", indent=4)
    print()
    note("三个细节决定这套流程能不能用：")
    bullet("① 片段带**出处**（《退货与换货政策》）—— 引用才对得上号；")
    bullet("② 片段的编号（[片段 1]）与注入顺序一致 —— 编号错乱会让引用彻底失效；")
    bullet("③ 系统提示词里写死「只依据资料」+ 拒答格式 —— 这是防幻觉的第一道闸门。")
    print()
    warn("引用还必须被**代码校验**：模型会写出 [片段 5]，而本次只检索到 3 条。")
    kv("引用校验器发现的问题", check_citations(ans) or "无")


def demo_refusal() -> None:
    section("第四步：检索不到就明确说没有 —— 不编造", "⑤")
    note("这是 RAG 最重要的一条：**知道什么时候不该回答**。")
    print()

    out_of_scope = [
        "员工内购折扣是多少？",
        "你们支持比特币付款吗？",
    ]
    for q in out_of_scope:
        hits = RETRIEVER.search(q, top_k=3)
        agent = RagAgent(RETRIEVER, RagBotLLM(), min_score=2.0)
        ans = agent.ask(q)
        print()
        kv("问题", q)
        kv("最高得分", f"{hits[0].score:.2f}" if hits else "0.00（没有任何片段命中）")
        kv("是否调用模型", "否（资料不足，直接拒答）" if ans.refused else "是")
        kv("回答", ans.answer)
    print()
    warn("注意「是否调用模型 = 否」：资料不足时**连模型都不调用**。")
    warn("让模型看着空资料回答，就是在赌博 —— 它多半会用训练数据里的常识把空填上。")
    print()

    # ---- 阈值调参 ------------------------------------------------------
    note("闸门阈值（min_score）怎么影响行为？同一批问题，扫一遍阈值：")
    print()
    probe = ["无理由退货是几天？", "金卡会员有什么权益？", "员工内购折扣是多少？", "支持比特币吗？"]
    print(f"      {'阈值':<8}" + "".join(f"{q[:8]:<12}" for q in probe))
    print("      " + "-" * 60)
    for threshold in (0.5, 2.0, 6.0, 12.0):
        row = ""
        for q in probe:
            hits = RETRIEVER.search(q, top_k=3, min_score=threshold)
            row += f"{'作答' if hits else '拒答':<12}"
        print(f"      {threshold:<8}" + row)
    print()
    bullet("阈值太低 → 什么都能答一点，于是拿不相关的资料去凑答案（**答非所问**）；")
    bullet("阈值太高 → 该答的也拒答（**可用性下降**，用户觉得这机器人什么都不会）；")
    bullet("阈值必须用**评测集**调（第 10 章）：准备一批「该答」和「该拒」的问题，看两边的通过率。")
    print()
    ok("拒答不是失败，是能力 —— 一个永远不拒答的 RAG，等于一个会编造的公司发言人。")


def demo_essence() -> None:
    section("收口：一句话本质", "⑥")
    essence(
        "RAG = 切块 → 建索引 → 检索 → 注入上下文 → 带引用作答。\n"
        "**检索质量决定上限，生成质量只是下限。**\n"
        "\n"
        "四句话记住整章：\n"
        "  1. 切块是 RAG 的第一道工序：粒度决定你能检索到什么，重叠决定事实完不完整；\n"
        "  2. BM25 靠统计就能干活（零训练、可解释），但不懂同义词 —— 那是向量的活；\n"
        "  3. 引用 [片段 N] 是验收机制：让答案可溯源，让错误可归因（检索错还是读错）；\n"
        "  4. 拒答是一等公民：检索不到就明说「资料里没有」，连模型都不要调用。\n"
        "\n"
        "一句话判断你的 RAG 好不好用：\n"
        "  把检索到的片段单独拿给人看 —— 人能答对吗？\n"
        "  如果人都答不对，那不是模型的问题，是检索的问题。"
    )


# ===========================================================================
# 四、验收标准（由 scripts/run_all_checks.py 调用）
# ===========================================================================
# 铁律：快、确定、不打印。语料在磁盘上、索引在内存里，全程无网络无随机。

def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（对应 ROADMAP.md 第 06 章的三条）。"""
    results: list[tuple[str, bool, str]] = []
    docs = load_documents(KB_PATH)
    chunks = build_chunks(docs, size=CHUNK_SIZE, overlap=CHUNK_OVERLAP)
    retriever = Retriever(chunks)
    agent = RagAgent(retriever, RagBotLLM(), top_k=3, min_score=2.0)

    # --- 验收 1：能从文档里检索出正确片段并注入提示词 -------------------
    ans = agent.ask("无理由退货是几天？")
    results.append(check_that(
        "语料被正确加载并切块（≥7 篇文档、≥10 个片段）",
        len(docs) >= 7 and len(chunks) >= 10, f"{len(docs)} 篇文档 / {len(chunks)} 个片段"))
    results.append(check_that(
        "能检索出正确片段（top-1 命中退货政策且含 15 天）",
        bool(ans.hits) and ans.hits[0].chunk.doc == "退货与换货政策" and "15 天" in ans.hits[0].chunk.text,
        f"top-1 《{ans.hits[0].chunk.doc}》 得分 {ans.hits[0].score:.2f}" if ans.hits else "无命中"))
    messages = build_rag_messages(ans.question, ans.hits)
    results.append(check_that(
        "检索结果被注入提示词，且带 [片段 N] 编号",
        len(messages) == 2 and "[片段 1]" in messages[1].content
        and "《退货与换货政策》" in messages[1].content,
        f"提示词 {len(messages[1].content)} 字，含 {len(ans.hits)} 条片段"))
    results.append(check_that(
        "检索结果按得分降序排列（排序稳定、可复现）",
        all(ans.hits[i].score >= ans.hits[i + 1].score for i in range(len(ans.hits) - 1)),
        f"得分序列 {[round(h.score, 2) for h in ans.hits]}"))

    # --- 验收 2：答案里带 [片段 N] 引用，可溯源 -------------------------
    results.append(check_that(
        "答案里带 [片段 N] 引用，且编号在本次检索范围内",
        bool(ans.citations) and not check_citations(ans)
        and all(1 <= c <= len(ans.hits) for c in ans.citations),
        f"引用 {ans.citations}；本次检索 {len(ans.hits)} 条"))
    cited = [ans.source_of(c) for c in ans.citations]
    results.append(check_that(
        "引用可溯源：被引片段确实包含答案中的关键事实",
        bool(cited) and all(c is not None for c in cited)
        and any("15 天" in c.text for c in cited if c) and "15 天" in ans.answer,
        ans.answer[:56]))
    results.append(check_that(
        "引用编号 → 真实语料块的映射正确（[片段 1] 指向本次第 1 条命中）",
        ans.source_of(1) is ans.hits[0].chunk and ans.source_of(99) is None
        and "语料块 #" in " ".join(ans.sources),
        " ".join(ans.sources[:1])))
    results.append(check_that(
        "引用校验器能抓出伪造的片段号（[片段 99]）",
        "不存在" in "".join(check_citations(_fake_answer(ans))),
        "伪造编号被拦下"))
    results.append(check_that(
        "多问题端到端稳定（发票/会员/SLA 三类问题都能答对）",
        _multi_qa_ok(agent), "3/3 命中正确文档且带引用"))

    # --- 验收 3：检索不到时明确说"资料里没有"，不编造 -------------------
    # 用全新的 agent 计数：模型调用次数必须是 0
    fresh = RagAgent(retriever, RagBotLLM(), top_k=3, min_score=2.0)
    miss = fresh.ask("员工内购折扣是多少？")
    results.append(check_that(
        "资料里没有的问题 → 明确拒答，且不调用模型",
        miss.refused and miss.answer == REFUSAL and fresh.calls == 0 and not miss.hits,
        f"refused={miss.refused}, 模型调用 {fresh.calls} 次"))
    results.append(check_that(
        "拒答时不编造任何数字（答案里不含期限/金额）",
        not re.search(r"\d", miss.answer), miss.answer[:40]))
    results.append(check_that(
        "闸门阈值生效：高阈值把弱相关也拦掉",
        len(retriever.search("员工内购折扣是多少？", top_k=3, min_score=2.0)) == 0
        and len(retriever.search("无理由退货是几天？", top_k=3, min_score=2.0)) > 0,
        "弱相关被拦、强相关放行"))

    # --- 加分项：切块与检索机制 -----------------------------------------
    results.append(check_that(
        "切块策略有效：硬切会切断句子，语义切 + 重叠能保证事实完整",
        _chunking_ok(docs), _chunking_detail(docs)))
    results.append(check_that(
        "BM25 的 IDF 生效：稀有词查询能精准命中对应文档",
        _idf_works(retriever), "「退款」「保修」「发票抬头」各命中自己的文档"))
    results.append(check_that(
        "中文/英文/数字分词都正确（订单号不被拆碎）",
        {"a1001", "sla"} <= set(tokenize("订单 A1001 的 SLA")),
        f"{tokenize('订单 A1001 的 SLA')}"))
    results.append(check_that(
        "边界：空查询 / 空语料 / 超长查询都不崩",
        _edge_ok(), "三种边界都返回空结果而不是异常"))

    return results


# ---- 检查用的小工具（都不打印） -------------------------------------------

def _fake_answer(ans):
    """伪造一个引用了不存在片段的答案，验证校验器能抓住。"""
    from dataclasses import replace

    return replace(ans, answer="这是一条引用了不存在片段的答案。[片段 99]", citations=[99])


def _multi_qa_ok(agent: RagAgent) -> bool:
    expect = {"发票抬头能改吗？": "发票与报销", "金卡会员有什么权益？": "会员等级与权益",
              "账号被盗了多久能响应？": "售后响应时效（SLA）"}
    for q, doc in expect.items():
        a = agent.ask(q)
        if not a.hits or a.hits[0].chunk.doc != doc or not a.citations:
            return False
    return True


def _chunking_ok(docs) -> bool:
    """硬切 + 不重叠一定会切断句子；语义切 + 重叠必须零切断。"""
    naive_broken = _count_broken_sentences(
        build_chunks(docs, size=CHUNK_DEMO_SIZE, overlap=0, mode="fixed"), docs)
    fixed_broken = _count_broken_sentences(
        build_chunks(docs, size=CHUNK_DEMO_SIZE, overlap=CHUNK_OVERLAP, mode="fixed"), docs)
    smart_broken = _count_broken_sentences(
        build_chunks(docs, size=CHUNK_DEMO_SIZE, overlap=CHUNK_OVERLAP, mode="unit"), docs)
    naive_hit = _self_recall(docs, "fixed", CHUNK_DEMO_SIZE, 0)
    smart_hit = _self_recall(docs, "unit", CHUNK_DEMO_SIZE, CHUNK_OVERLAP)
    return (naive_broken > 0 and fixed_broken < naive_broken and smart_broken == 0
            and naive_hit[0] < naive_hit[1] and smart_hit[0] == smart_hit[1])


def _chunking_detail(docs) -> str:
    naive = _count_broken_sentences(
        build_chunks(docs, size=CHUNK_DEMO_SIZE, overlap=0, mode="fixed"), docs)
    fixed = _count_broken_sentences(
        build_chunks(docs, size=CHUNK_DEMO_SIZE, overlap=CHUNK_OVERLAP, mode="fixed"), docs)
    smart = _count_broken_sentences(
        build_chunks(docs, size=CHUNK_DEMO_SIZE, overlap=CHUNK_OVERLAP, mode="unit"), docs)
    hit0 = _self_recall(docs, "fixed", CHUNK_DEMO_SIZE, 0)
    hit1 = _self_recall(docs, "unit", CHUNK_DEMO_SIZE, CHUNK_OVERLAP)
    return (f"被切断句子：硬切 {naive} → 硬切+重叠 {fixed} → 语义切+重叠 {smart}；"
            f"自检索完整命中：硬切 {hit0[0]}/{hit0[1]} vs 语义切 {hit1[0]}/{hit1[1]}")


def _idf_works(retriever: Retriever) -> bool:
    for q, doc in (("退款多久到账", "退货与换货政策"), ("保修期多久", "保修与维修"),
                   ("发票抬头修改", "发票与报销")):
        hits = retriever.search(q, top_k=1)
        if not hits or hits[0].chunk.doc != doc:
            return False
    return True


def _edge_ok() -> bool:
    empty_index = Retriever([])
    return (empty_index.search("随便问问") == []
            and RETRIEVER.search("") == []
            and isinstance(RETRIEVER.search("退" * 4000, top_k=2), list))


# ===========================================================================
# 入口
# ===========================================================================
SECTIONS = {
    "1": ("反面教材：没有检索只能编", demo_no_rag),
    "2": ("切块与重叠", demo_chunking),
    "3": ("BM25 打分原理", demo_bm25),
    "4": ("端到端 RAG 与引用", demo_end_to_end),
    "5": ("拒答与阈值", demo_refusal),
    "6": ("一句话本质", demo_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 06 章 · RAG 检索增强")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 06 章 · RAG 检索增强")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 06 章", run_checks()) else 1

    banner("第 06 章 · RAG 检索增强",
           "目标：手写零依赖的 BM25 检索链路，让 Agent 用上它没训练过的私有知识")

    for key in ([args.section] if args.section else sorted(SECTIONS)):
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 06 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
