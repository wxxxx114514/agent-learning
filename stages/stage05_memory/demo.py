"""第 05 章 · 记忆与上下文工程 —— 在有限的预算里，保留最高价值的信息。

运行：
    py -m stages.stage05_memory.demo
    py -m stages.stage05_memory.demo --list
    py -m stages.stage05_memory.demo --section 4
    py -m stages.stage05_memory.demo --check

本章的问题来自第 04 章暴露的麻烦：
    规划会产出大量中间结果（每一版计划、每一步的观测、每一次重规划的原因），
    它们全都堆在上下文里 —— 几十轮之后，上下文窗口就不够用了。

本章用一个 50 轮的对话把这个问题放大到肉眼可见，然后给出工业界的四件套解法：
    滑动窗口 + 摘要压缩 + 关键事实钉住 + 长期存储。
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
from core.llm import LLM, LLMResponse, estimate_tokens  # noqa: E402
from core.message import Message  # noqa: E402

from stages.stage05_memory.memory import (  # noqa: E402
    MAX_PINNED, FactExtractor, LLMSummarizer, LongTermStore, MemoryManager,
    Turn, count_tokens, full_history, meter, naive_truncate,
)

# ===========================================================================
# 一、教学用的 50 轮对话
# ===========================================================================
# 关键事实全部埋在**最前面 4 轮**里 —— 这正是真实对话的样子：
# 用户一上来就把最重要的信息（身份、约束、预算）交代完，然后开始聊细节。
# 于是"按时间淘汰最老的消息"就必然先把这些关键事实扔掉。

SYSTEM_PROMPT = "你是一个团建筹备助手，请根据上下文回答用户的问题。"

CRITICAL_TURNS: list[tuple[str, str]] = [
    ("你好，我叫张三，我在筹备下个月的部门团建。",
     "你好张三，我来帮你安排。"),
    ("我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。",
     "收到：24 人、预算 5000 元、3 月 15 日。"),
    ("重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。",
     "记下了，全程避开海鲜。"),
    ("另外订单 A1001 的发票麻烦一起处理。",
     "好的，发票我会跟进。"),
]

FILLER_TOPICS = [
    "会议室预订", "大巴车租赁", "团建服装", "摄影跟拍", "活动保险", "签到表",
    "奖品采购", "雨天备选方案", "午餐菜单", "下午茶", "桌游道具", "音响设备",
    "横幅制作", "分组名单", "破冰游戏", "往返路线", "停车位", "医药箱",
    "垃圾分类", "拍照打卡点", "背景音乐", "纪念品", "费用分摊",
]


def build_transcript() -> list[tuple[str, str]]:
    """确定性地造出 50 轮对话：4 轮关键 + 46 轮噪音。"""
    turns = list(CRITICAL_TURNS)
    for i, topic in enumerate(FILLER_TOPICS, 1):
        for j in (1, 2):
            turns.append((
                f"第 {i}-{j} 项：关于{topic}的安排，我这边还有几个细节想跟你聊一下，"
                f"下次再展开，你先记着。",
                f"好的，第 {i}-{j} 项（{topic}）我先记下，下次展开。",
            ))
    return turns


def make_turns(pairs: list[tuple[str, str]]) -> list[Turn]:
    return [Turn(index=i, user=u, assistant=a) for i, (u, a) in enumerate(pairs, 1)]


# ===========================================================================
# 二、一个"只会照着上下文回答"的假模型
# ===========================================================================
# 这样设计是为了让"上下文管理好不好"变成**可测量的结果**：
# 上下文里有的事实它才答得出，没有的就答不出。
# 真实的模型也是这个道理，只是它比这里的正则宽容一些（也更会编）。

FACT_KEYS = ("姓名", "饮食禁忌", "预算", "订单号")


class MemoryBotLLM(LLM):
    """从上下文里"读"事实并作答的假模型。

    参数 middle_blind=True 时模拟"丢失中间信息"（Lost in the Middle）：
    真实模型对上下文**开头和结尾**的注意力明显高于中间部分，
    所以关键的参考资料放在中间，被用到的概率会大幅下降。
    """

    name = "memory-bot"

    def __init__(self, middle_blind: bool = False, window: int = 420) -> None:
        super().__init__("mock-memory")
        self.middle_blind = middle_blind
        self.window = window
        self.last_context = ""

    def _complete(self, messages, **kwargs):
        context = "\n".join(m.content for m in messages)
        self.last_context = context
        text = context
        if self.middle_blind:
            # 只读首尾 —— 这就是"中间被忽略"的模型行为
            text = context[: self.window] + "\n……（中间内容没被读到）……\n" + context[-self.window:]
        found = self.read_facts(text)
        missing = [k for k in FACT_KEYS if k not in found]
        if missing:
            answer = ("Final Answer: 我在当前上下文里只能确认："
                      + ("；".join(f"{k}={v}" for k, v in found.items()) if found else "（什么都没有）")
                      + f"。\n以下信息在上下文里找不到：{'、'.join(missing)}。")
        else:
            answer = "Final Answer: 根据上下文：" + "；".join(f"{k}={v}" for k, v in found.items()) + "。"
        return LLMResponse(text=answer, model=self.model)

    @staticmethod
    def read_facts(text: str) -> dict[str, str]:
        """两条路都走：先找结构化写法（`姓名：张三`），再用规则抽取自然语言。"""
        found: dict[str, str] = {}
        for key in FACT_KEYS:
            m = re.search(rf"{key}\s*[:：]\s*([^\n；;，,。]+)", text)
            if m:
                found[key] = m.group(1).strip()
        for fact in FactExtractor().extract(text):
            found.setdefault(fact.key, fact.value)
        return {k: v for k, v in found.items() if k in FACT_KEYS}


class FakeSummaryLLM(LLM):
    """用来演示"摘要由模型生成"这条路（真实项目里的做法）。"""

    name = "fake-summary"

    def __init__(self, summary: str) -> None:
        super().__init__("mock-summary")
        self.summary = summary

    def _complete(self, messages, **kwargs):
        return LLMResponse(text=self.summary, model=self.model)


# ===========================================================================
# 三、教学小节
# ===========================================================================

QUERY = "帮我确认三件事：我的姓名、预算和忌口分别是什么？"

# 位置效应实验用的语料：**必须比 2 倍窗口长**，否则首尾窗口会重叠、
# 把放在中间的事实也覆盖进去，实验就测不出东西了（这是做这类实验最常见的坑）。
FACTS_BLOCK = "已确认的关键事实：\n- 姓名：张三\n- 预算：5000 元\n- 饮食禁忌：海鲜"


def demo_naive_fails() -> None:
    section("反面教材：50 轮之后，Agent 把最重要的事忘了", "①")
    pairs = build_transcript()
    turns = make_turns(pairs)
    budget = 1200

    note(f"对话共 {len(turns)} 轮。关键事实全在**最前面 4 轮**（真实对话就是这样）：")
    for i, (u, _) in enumerate(CRITICAL_TURNS, 1):
        bullet(f"第 {i} 轮：{u}")
    print()

    # ---- 方案 A：全量塞进去 -------------------------------------------
    full = full_history(SYSTEM_PROMPT, turns, QUERY)
    full_tokens = count_tokens(full)
    kv("方案 A · 全量历史", f"{len(full)} 条消息 / {full_tokens} token")
    print("      " + meter(full_tokens, budget))
    warn(f"超出预算 {full_tokens / budget:.1f} 倍。真实 API 到这里会直接报错（上下文超限），")
    warn("而且每一轮都要重发全部历史 —— 成本随轮数是平方级增长的（第 12 章）。")
    print()

    # ---- 方案 B：只留最近 N 轮 ----------------------------------------
    kept = 6
    trunc = naive_truncate(SYSTEM_PROMPT, turns, keep_last=kept, query=QUERY)
    trunc_tokens = count_tokens(trunc)
    kv(f"方案 B · 只留最近 {kept} 轮", f"{len(trunc)} 条消息 / {trunc_tokens} token")
    print("      " + meter(trunc_tokens, budget))
    bot = MemoryBotLLM()
    answer = bot.complete(trunc).text
    print()
    kv("Agent 的回答", answer.replace("Final Answer: ", ""))
    print()
    warn("预算问题解决了，但**关键事实全丢了** —— 姓名、预算、忌口、订单号一个都不剩。")
    warn("这不是「模型不行」，而是我们喂给它的上下文里真的没有这些信息。")
    print()
    note("为什么「截断最老的消息」是危险的？因为**信息价值和出现时间无关**：")
    bullet("第 1 轮说的「我对海鲜过敏」比第 46 轮说的「桌游道具」重要得多；")
    bullet("按时间淘汰 = 按无关性淘汰，早晚会把要命的那条删掉；")
    bullet("真实案例：模型因此推荐了含花生的餐厅 —— 上下文里没有过敏信息，它只能猜。")
    print()
    ok("修法不是「换个大模型」，而是把记忆分层：窗口 + 摘要 + 钉住 + 长期存储。")


def demo_budget() -> MemoryManager:
    section("第一步：先算账，再决定放什么", "②")
    note("上下文工程的第一步不是「压缩」，而是**预算表**：每块分多少 token，为什么。")
    print()

    mgr = MemoryManager(SYSTEM_PROMPT, budget=1200, window_turns=6)
    for user, assistant in build_transcript():
        mgr.add_turn(user, assistant)

    pack = mgr.build(QUERY)
    print("  预算账本：")
    print("  " + "-" * 66)
    code(pack.ledger(), indent=2)
    print("      " + meter(pack.tokens, mgr.budget))
    print()
    note("分配顺序本身就是策略（优先级 = 不可替代性）：")
    bullet("① 系统提示 —— 不可压缩（压缩它等于改程序）")
    bullet("② 钉住事实 —— 有硬上限 MAX_PINNED=%d，按重要性排序" % MAX_PINNED)
    bullet("③ 长期召回 —— 必须过相关性闸门（宁可不注入，也不要注入无关信息）")
    bullet("④ 滚动摘要 —— 是「更早的对话」的唯一代表，也有字数上限")
    bullet("⑤ 对话窗口 —— 拿走剩下的全部（最新的原文，细节最全）")
    print()
    kv("被折叠的轮数", pack.dropped_turns)
    full_tokens = count_tokens(full_history(SYSTEM_PROMPT, mgr.turns, QUERY))
    kv("对照 · 全量历史", f"{full_tokens} token")
    ok(f"上下文从 {full_tokens} token 压到 {pack.tokens} token，而且关键事实一条没丢。")
    return mgr


def demo_window_and_summary() -> MemoryManager:
    section("第二步：滚动摘要 —— 把「说过的话」变成「记下的事」", "③")

    mgr = MemoryManager(SYSTEM_PROMPT, budget=1200, window_turns=6)
    pairs = build_transcript()

    note("观察摘要随对话推进是怎么「滚动」的（每加 10 轮打印一次）：")
    print()
    for i, (user, assistant) in enumerate(pairs, 1):
        mgr.add_turn(user, assistant)
        if i % 10 == 0:
            kv(f"第 {i} 轮后", f"摘要 {len(mgr.summary_text)} 字，已折叠 {mgr.compressed_turns} 轮")
            code(mgr.summary_text or "（还没开始压缩）", indent=6)
            print()
    kv("摘要压缩调用次数", mgr.summarize_calls)
    note("注意三件事：")
    bullet("① 摘要是**增量滚动**的（新摘要 = 压缩(旧摘要 + 新折叠的对话)），不是每次从头重算；")
    bullet("② 旧摘要参与下一轮压缩，保证很久以前的事不会在反复重算中悄悄消失；")
    bullet("③ 摘要里保留的全是「会再用到」的信息（预算/日期/禁忌/订单），寒暄一句不留。")
    print()
    warn("但摘要再聪明也是**有损**的：它一定会漏掉点东西。")
    warn("所以关键事实不能只靠摘要活着 —— 下一节就是给它们上保险。")
    print()
    note("真实项目里摘要是让模型写的（提示词见 memory.py 的 SUMMARY_PROMPT）：")
    fake = LLMSummarizer(FakeSummaryLLM("预算 5000 元；24 人；3 月 15 日；忌口海鲜；订单 A1001 的发票待跟进"))
    fake.summarize(["……"])
    code(fake.last_prompt[:300] + "……", indent=4)
    warn("代价：摘要本身也是一次模型调用，也要花钱、也有延迟（第 12 章会算这笔账）。")
    return mgr


def demo_pinning() -> None:
    section("第三步：关键事实钉住 —— 给要命的信息上保险", "④")
    pairs = build_transcript()

    # 三组对照：把护栏一层层拆掉，看关键事实在哪一层才真的丢
    cases = (
        ("完整方案（钉住 + 摘要 + 窗口 + 召回）", dict(use_pinning=True, max_recall=3)),
        ("拆掉钉住（长期召回还在）", dict(use_pinning=False, max_recall=3)),
        ("拆掉钉住 + 拆掉召回（只剩摘要和窗口）", dict(use_pinning=False, max_recall=0)),
    )
    for label, kwargs in cases:
        mgr = MemoryManager(SYSTEM_PROMPT, budget=1200, window_turns=6, **kwargs)
        for user, assistant in pairs:
            mgr.add_turn(user, assistant)
        pack = mgr.build(QUERY)
        answer = MemoryBotLLM().complete(pack.messages).text.replace("Final Answer: ", "")
        print()
        kv(label, f"{pack.tokens} token")
        print(f"      回答：{answer}")
    print()
    warn("只看第一行，你会以为「钉住」没什么用 —— 因为长期召回把漏掉的事实又捞回来了。")
    warn("但是拆到第三行，事实就真的找不回来了：**每一层都在承重**。")
    print()
    note("这就是「纵深防御」（defense in depth）：不指望任何一层永远可靠，")
    note("而是让每一层各自覆盖别人的盲区 —— 摘要会漏，钉住兜住；钉住满了，存储兜住。")
    print()
    note("钉住区的两条纪律（见 memory.py 的 MAX_PINNED / PIN_THRESHOLD）：")
    bullet("① 只钉「用错了会出事」的事实（身份/禁忌/预算/单号），不要把什么都钉上；")
    bullet(f"② 钉住区必须有上限（当前 {MAX_PINNED} 条）—— 否则钉住会变成新的超支来源。")
    print()
    ok("钉住 + 摘要 + 窗口 + 存储 是四重冗余：任何一条路断了，关键事实都还有备份。")


def demo_long_term() -> LongTermStore:
    section("第四步：长期记忆 —— 下次来还记得你", "⑤")
    note("滑动窗口和摘要都是「这一次会话」内的事。用户关掉页面再回来，它们全归零。")
    print()

    store = LongTermStore()

    # ---- 第一次会话 ---------------------------------------------------
    session1 = MemoryManager(SYSTEM_PROMPT, budget=1200, window_turns=6, store=store)
    for user, assistant in build_transcript():
        session1.add_turn(user, assistant)
    kv("第 1 次会话结束", f"长期库里有 {len(store.items)} 条事实")
    for item in store.items:
        print(f"        · {item.text}（来自第 {item.turn} 轮，重要性 {item.importance:.2f}）")
    print()

    # ---- 第二次会话（全新的上下文，什么都不记得） ----------------------
    session2 = MemoryManager(SYSTEM_PROMPT, budget=1200, window_turns=6, store=store)
    session2.add_turn("你好，我们又见面了。", "你好！有什么可以帮你的？")

    recall_query = "我上次说的预算和饮食禁忌，你还记得吗？"
    pack = session2.build(recall_query)
    kv("第 2 次会话的召回", f"{len(pack.recalled)} 条")
    for item in pack.recalled:
        print(f"        · {item.text}")
    kv("召回后上下文 token", pack.tokens)
    print()
    note("召回靠的是**字符二元组重叠打分**（memory.py 的 bigrams）：")
    code('查询 "我上次说的预算和饮食禁忌" 的二元组里含 {预算, 饮食, 食禁, 禁忌}\n'
         '记忆 "预算：5000 元"     命中 {预算}            → 分数 = 重叠数 + 重要性\n'
         '记忆 "饮食禁忌：海鲜"     命中 {饮食, 食禁, 禁忌}  → 分数更高，排更前', indent=4)
    print()
    warn("但二元组检索**不懂同义词**：换个问法「我上次说的忌口」就召不回来了（下面实测）。")
    synonym = session2.build("我上次说的预算和忌口，你还记得吗？")
    kv("换个问法（忌口）的召回", f"{len(synonym.recalled)} 条（禁忌那条丢了）")
    note("这正是向量检索（embedding）要解决的问题 —— 第 06 章 RAG 里会看到同一个坑。")
    print()
    note("为什么必须有相关性闸门（min_score）？因为**注入无关记忆比不注入更糟**：")
    bullet("模型会把旧任务的约束当成当前任务的约束（上次 24 人，这次 6 人也按 24 人办）；")
    bullet("检索是「宁可少召回，不可乱召回」 —— 这一点在第 06 章 RAG 里同样成立。")
    print()
    unrelated = session2.build("今天天气怎么样？")
    kv("不相关提问时的召回", f"{len(unrelated.recalled)} 条（闸门拦住了）")
    return store


def position_ctx(position: str, window: int = 300) -> list[Message]:
    """构造"事实放开头 / 放中间"两种上下文，用于演示丢失中间信息。

    60 条噪音（约 1800 字）确保首尾各 300 字的窗口**覆盖不到中间**。
    """
    filler = [f"第 {i} 项：关于安排{i}的细节，下次再展开，你先记着别急着定。" for i in range(1, 61)]
    msgs = [Message.system(SYSTEM_PROMPT)]
    if position == "head":
        msgs.append(Message.system(FACTS_BLOCK))
        msgs.extend(Message.user(f) for f in filler)
    else:
        msgs.extend(Message.user(f) for f in filler[:30])
        msgs.append(Message.system(FACTS_BLOCK))
        msgs.extend(Message.user(f) for f in filler[30:])
    msgs.append(Message.user(QUERY))
    return msgs


def demo_lost_in_middle() -> None:
    section("第五步：位置也是信息 —— 「丢失中间信息」", "⑥")
    note("同样的内容，放在上下文的不同位置，被模型用到的概率完全不同。")
    note("这不是玄学：研究表明模型对**开头和结尾**的注意力显著高于中间（Lost in the Middle）。")
    print()

    answer_head = ""
    answer_middle = ""
    for position, label in (("head", "事实放在开头（紧跟系统提示）"), ("middle", "事实放在中间（第 30 条噪音之后）")):
        msgs = position_ctx(position)
        total = count_tokens(msgs)
        answer = MemoryBotLLM(middle_blind=True).complete(msgs).text.replace("Final Answer: ", "")
        if position == "head":
            answer_head = answer
        else:
            answer_middle = answer
        kv(label, f"{total} token")
        print(f"      回答：{answer[:100]}")
    print()
    warn("同一份内容，只是换了位置：放在中间时，模型「看不见」它。")
    print()
    note("工程结论（本章的布局就是照这个来的）：")
    bullet("① 钉住的关键事实放在**最前面**（紧跟系统提示，首因位置）；")
    bullet("② 当前的问题放在**最后面**（近因位置，且天然引导模型续写）；")
    bullet("③ 大段的参考资料（RAG 片段）不要堆在中间，要按相关性排序后靠前放。")
    print()
    note("这也解释了为什么「把 20 个文档片段全塞进去」通常不如「精挑 3 个」：")
    note("塞得越多，每条越可能落在中间 —— 你付出了 token，却买到了更低的被使用率。")


def demo_essence() -> None:
    section("收口：一句话本质", "⑦")
    essence(
        "记忆 = 短期（消息窗） + 工作（当前任务状态） + 长期（外部存储）。\n"
        "上下文管理的本质是：**在有限预算下保留最高价值的信息**。\n"
        "\n"
        "四件套缺一不可：\n"
        "  窗口 —— 最新的原文，细节最全，但只覆盖最近几轮；\n"
        "  摘要 —— 覆盖全部历史，但有损，会悄悄漏掉东西；\n"
        "  钉住 —— 关键事实永不淘汰，但必须有上限；\n"
        "  长期 —— 跨会话不丢，但要过相关性闸门。\n"
        "\n"
        "三条最实用的经验：\n"
        "  1. 按**价值**淘汰，不要按**时间**淘汰；\n"
        "  2. 关键事实要多层冗余（钉住 + 摘要 + 落库），任何一条断了都还有备份；\n"
        "  3. 位置也是信息 —— 最重要的内容放开头和结尾，不要塞中间。"
    )


# ===========================================================================
# 四、验收标准（由 scripts/run_all_checks.py 调用）
# ===========================================================================
# 铁律：快、确定、不打印。全部用内存里的确定性数据，不涉及任何网络/随机/等待。

BUDGET = 1200


def _filled(pairs: list[tuple[str, str]] | None = None, **kwargs) -> MemoryManager:
    mgr = MemoryManager(SYSTEM_PROMPT, budget=kwargs.pop("budget", BUDGET),
                        window_turns=kwargs.pop("window_turns", 6), **kwargs)
    for user, assistant in (pairs if pairs is not None else build_transcript()):
        mgr.add_turn(user, assistant)
    return mgr


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（对应 ROADMAP.md 第 05 章的三条）。"""
    results: list[tuple[str, bool, str]] = []
    pairs = build_transcript()
    turns = make_turns(pairs)

    # --- 验收 1：注入 50 轮对话后，上下文长度被控制在预算内 -------------
    mgr = _filled()
    pack = mgr.build(QUERY)
    results.append(check_that(
        "注入 50 轮对话后，上下文被控制在预算内",
        len(turns) == 50 and pack.tokens <= BUDGET,
        f"{len(turns)} 轮 → {pack.tokens}/{BUDGET} token"))
    full_tokens = count_tokens(full_history(SYSTEM_PROMPT, turns, QUERY))
    results.append(check_that(
        "对照：全量历史会超预算（说明压缩确实必要）",
        full_tokens > BUDGET * 2,
        f"全量 {full_tokens} token = 预算的 {full_tokens / BUDGET:.1f} 倍"))
    ledger_sum = sum(s.tokens for s in pack.sections)
    results.append(check_that(
        "预算账本自洽：各块之和 == 上下文总量（账算得清才管得住）",
        ledger_sum == pack.tokens,
        f"分块合计 {ledger_sum} vs 实际 {pack.tokens}"))
    results.append(check_that(
        "上下文结构正确：system 在最前、当前问题在最后、窗口在钉住之后",
        pack.messages[0].role == "system" and pack.messages[-1].content == QUERY
        and pack.messages[-1].role == "user",
        f"首条={pack.messages[0].role}, 末条={pack.messages[-1].role}"))

    # --- 验收 2：关键事实（如用户姓名）在压缩后仍然不丢失 ---------------
    text = pack.render()
    results.append(check_that(
        "压缩后关键事实仍在（姓名/忌口/预算/订单号）",
        all(k in text for k in ("张三", "海鲜", "5000", "A1001")),
        f"命中 {[k for k in ('张三', '海鲜', '5000', 'A1001') if k in text]}"))
    answer = MemoryBotLLM().complete(pack.messages).text
    results.append(check_that(
        "据此回答时四项事实齐全（没有「找不到」）",
        all(k in answer for k in ("姓名", "饮食禁忌", "预算", "订单号"))
        and "找不到" not in answer,
        answer.replace("Final Answer: ", "")[:70]))
    results.append(check_that(
        "对照：朴素截断会丢掉关键事实（这就是「按时间淘汰」的错）",
        _truncate_loses_facts(turns), "截断后 4 项事实全部丢失，模型只能说「找不到」"))
    no_pin = _filled(use_pinning=False, max_recall=0).build(QUERY)
    no_pin_answer = MemoryBotLLM().complete(no_pin.messages).text
    results.append(check_that(
        "拆掉钉住且关掉召回后，关键事实真的会丢（证明每一层都在承重）",
        "找不到" in no_pin_answer and "姓名" in no_pin_answer
        and "张三" not in no_pin.render(),
        no_pin_answer.replace("Final Answer: ", "")[:60]))
    results.append(check_that(
        "但只拆钉住、保留召回时仍能兜住（冗余设计的价值）",
        "张三" in MemoryBotLLM().complete(
            _filled(use_pinning=False).build(QUERY).messages).text,
        "长期召回补上了钉住的缺口"))

    # --- 验收 3：能解释"为什么简单截断最老消息是危险的" ----------------
    summary = _filled().summary_text
    results.append(check_that(
        "摘要覆盖了被折叠的绝大多数轮次",
        _filled().compressed_turns >= 40,
        f"折叠 {_filled().compressed_turns} 轮"))
    results.append(check_that(
        "摘要里保留了早期对话的关键信息（可解释：截断会连摘要一起丢）",
        "5000" in summary and "海鲜" in summary,
        summary[:60]))
    results.append(check_that(
        "摘要长度受控（压缩比 > 60%）",
        len(summary) < count_tokens(full_history(SYSTEM_PROMPT, turns)) * 0.4,
        f"摘要 {len(summary)} 字 vs 全量 {count_tokens(full_history(SYSTEM_PROMPT, turns))} token"))
    results.append(check_that(
        "事实判重：同一事实说两次只留一条（钉住区不会被重复撑爆）",
        _dedup_ok(), "重复陈述后事实数不变"))

    # --- 加分项：长期记忆与位置效应 -------------------------------------
    store = LongTermStore()
    s1 = _filled(store=store)
    _ = s1
    s2 = MemoryManager(SYSTEM_PROMPT, budget=BUDGET, window_turns=6, store=store)
    s2.add_turn("你好，我们又见面了。", "你好！")
    recalled = s2.build("我上次说的预算和饮食禁忌，你还记得吗？").recalled
    results.append(check_that(
        "跨会话长期记忆能被召回并注入",
        any("预算" in it.text for it in recalled) and any("海鲜" in it.text for it in recalled),
        f"召回 {[it.text for it in recalled]}"))
    results.append(check_that(
        "不相关的提问不注入记忆（相关性闸门生效）",
        s2.build("今天天气怎么样？").recalled == [],
        "无关查询召回 0 条"))
    results.append(check_that(
        "边界：极小预算不崩，且仍保留 system 与当前问题",
        _tiny_budget_ok(), "120 token 预算下结构完整"))

    # --- 加分项：丢失中间信息 -------------------------------------------
    results.append(check_that(
        "位置效应：同样的事实放中间会被漏读，放开头的不会",
        _position_effect(), "中间漏读 / 开头命中"))

    return results


def _dedup_ok() -> bool:
    """同一事实说两次，钉住区里只留一条（否则重复陈述会挤爆预算）。"""
    mgr = MemoryManager(SYSTEM_PROMPT, budget=BUDGET, window_turns=6)
    mgr.add_turn("我叫张三。")
    n1 = len(mgr.facts)
    mgr.add_turn("再确认一下，我叫张三。")
    return len(mgr.facts) == n1 == 1


def _truncate_loses_facts(turns: list[Turn]) -> bool:
    """朴素截断之后，四项关键事实**在上下文里一条都找不到**。"""
    text = "\n".join(m.content for m in naive_truncate(SYSTEM_PROMPT, turns, keep_last=6, query=QUERY))
    return not any(k in text for k in ("张三", "海鲜", "5000", "A1001"))


def _tiny_budget_ok() -> bool:
    mgr = _filled(budget=120)
    pack = mgr.build(QUERY)
    return (pack.messages[0].role == "system"
            and pack.messages[-1].content == QUERY
            and estimate_tokens(pack.render()) >= 0)


def _position_effect() -> bool:
    """同样的事实：放开头能被读到，放中间（首尾窗口之外）就被漏掉。"""
    head = MemoryBotLLM(middle_blind=True).complete(position_ctx("head")).text
    middle = MemoryBotLLM(middle_blind=True).complete(position_ctx("middle")).text
    return "张三" in head and "张三" not in middle


# ===========================================================================
# 入口
# ===========================================================================
SECTIONS = {
    "1": ("反面教材：50 轮后忘掉关键事实", demo_naive_fails),
    "2": ("预算表：先算账再放内容", demo_budget),
    "3": ("滚动摘要压缩", demo_window_and_summary),
    "4": ("关键事实钉住", demo_pinning),
    "5": ("长期记忆与召回", demo_long_term),
    "6": ("丢失中间信息", demo_lost_in_middle),
    "7": ("一句话本质", demo_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 05 章 · 记忆与上下文工程")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 05 章 · 记忆与上下文工程")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 05 章", run_checks()) else 1

    banner("第 05 章 · 记忆与上下文工程",
           "目标：在有限的 token 预算里，保留最高价值的信息 —— 而不是把历史全塞进去")

    for key in ([args.section] if args.section else sorted(SECTIONS)):
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 05 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
