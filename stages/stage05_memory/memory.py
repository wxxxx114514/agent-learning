"""第 05 章 · 记忆与上下文工程 —— 在有限的预算里，保留最高价值的信息。

--------------------------------------------------------------------------
一句话本质：
    记忆 = 短期（消息窗） + 工作（当前任务状态） + 长期（外部存储）。
    上下文管理的本质是：**在有限预算下保留最高价值的信息**。
--------------------------------------------------------------------------

为什么"把历史全塞进去"不是答案？
    1. 物理上塞不下：上下文窗口是硬上限，超了 API 直接报错；
    2. 经济上不划算：每一轮都要重发全部历史，成本随轮数**平方级**增长（第 12 章）；
    3. 效果上更差：上下文越长，模型对中间部分的注意力越弱（"丢失中间信息"），
       而且无关信息会干扰判断 —— 长 ≠ 好。

为什么"截断最老的消息"也不是答案？
    因为**信息价值和出现时间无关**。第 1 轮说的"我对海鲜过敏"，
    比第 40 轮说的"今天天气不错"重要得多。
    按时间淘汰 = 按无关性淘汰，早晚会把关键事实删掉。

本模块给出工业界的标准解法（四件套）：
    ┌──────────────┬────────────────────────────────────────────┐
    │ ① 滑动窗口    │ 最近 N 轮原文保留（近因效应，细节最全）      │
    │ ② 摘要压缩    │ 更早的对话压成一段摘要（有损，但保留主干）    │
    │ ③ 事实钉住    │ 关键事实（姓名/禁忌/预算/订单号）永不被淘汰  │
    │ ④ 长期存储    │ 事实落库，跨会话按需检索回来                 │
    └──────────────┴────────────────────────────────────────────┘
    四者缺一不可：只有窗口会忘事，只有摘要会失真，只有钉住会爆预算，只有存储取不回来。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from core.llm import LLM, estimate_tokens
from core.message import Message

# ===========================================================================
# 一、预算表：先算账，再决定放什么
# ===========================================================================
# 上下文工程的第一步不是"压缩"，而是**算账**：
# 我的预算是多少 token？每一块（系统提示/事实/摘要/窗口）能分到多少？
# 没有预算表的"压缩"是凭感觉的，最后一定会失控。


def meter(used: int, total: int, width: int = 30) -> str:
    """把预算用量画成一根进度条 —— 教学里最直观的"算账"工具。"""
    ratio = min(used / total, 1.0) if total else 0.0
    filled = int(round(width * ratio))
    return f"[{'#' * filled}{'.' * (width - filled)}] {used:>5}/{total} token ({ratio * 100:>3.0f}%)"


@dataclass
class Section:
    """上下文里的一块。`note` 说明这一块为什么存在。"""

    name: str
    tokens: int = 0
    chars: int = 0
    items: int = 0
    note: str = ""
    budget: int = 0

    def line(self) -> str:
        cap = f"/{self.budget}" if self.budget else ""
        return f"{self.name:<12} {self.tokens:>5}{cap:<7} token  {self.items:>2} 条  {self.note}"


# ===========================================================================
# 二、事实抽取：什么样的信息值得"钉住"
# ===========================================================================
# 判断标准只有一个：**这条信息在后面还会不会被用到？用错了会不会出事？**
#   姓名/称呼   → 会反复用到，叫错了很难受
#   禁忌/过敏   → 用错了会出人命（真实案例：模型推荐了含花生酱的餐厅）
#   预算/约束   → 是后续所有决策的边界
#   订单号/单号 → 是工具调用的参数，错一位就查不到
# 反过来，"今天天气不错"这类寒暄，价值≈0，第一个该被压缩掉。


@dataclass
class Fact:
    """一条结构化事实。**结构化是关键**：可以判重、可以打分、可以排序、可以落库。"""

    key: str
    value: str
    turn: int = 0
    importance: float = 0.5
    pinned: bool = False
    session: int = 1

    @property
    def text(self) -> str:
        return f"{self.key}：{self.value}"

    @property
    def fingerprint(self) -> str:
        return f"{self.key}={self.value}"


# 规则表：(正则, 字段名, 重要性)。重要性 >= PIN_THRESHOLD 的事实会被钉住。
FACT_RULES: list[tuple[str, str, float]] = [
    (r"我叫([\u4e00-\u9fa5A-Za-z]{2,4})", "姓名", 1.00),
    (r"我是([\u4e00-\u9fa5A-Za-z]{2,4})(?:[，,。]|$)", "姓名", 0.90),
    (r"我(?:对|吃)?([\u4e00-\u9fa5]{2,6})过敏", "饮食禁忌", 1.00),
    (r"预算(?:是|为|大概)?\s*([0-9,]+)\s*(?:元|块|万)", "预算", 0.98),
    (r"订单\s*([A-Za-z]{0,2}\d{3,})", "订单号", 0.92),
    (r"(?:不要|别|禁止|务必不要)([\u4e00-\u9fa5]{2,10}?)(?:[，,。]|$)", "禁忌", 0.88),
    (r"日期(?:定在|是|为|改到)\s*([0-9]{1,2}\s*月\s*[0-9]{1,2}\s*[日号])", "日期", 0.80),
    (r"一共\s*([0-9]+)\s*(?:人|位|个)", "人数", 0.78),
    (r"我(?:喜欢|偏好|习惯|希望)([\u4e00-\u9fa5]{2,8}?)(?:[，,。]|$)", "偏好", 0.55),
]

PIN_THRESHOLD = 0.75          # 重要性阈值：达到就钉住
MAX_PINNED = 8                # ★ 钉住区也必须有上限，否则"钉住"会变成新的超支来源


class FactExtractor:
    """规则版事实抽取器（生产环境常用 LLM 抽取，但规则版可测试、可解释、零成本）。"""

    def __init__(self, threshold: float = PIN_THRESHOLD) -> None:
        self.threshold = threshold
        self.rules = [(re.compile(p), k, imp) for p, k, imp in FACT_RULES]

    def extract(self, text: str, turn: int = 0, session: int = 1) -> list[Fact]:
        facts: list[Fact] = []
        for pattern, key, importance in self.rules:
            for m in pattern.finditer(text or ""):
                value = m.group(1).strip()
                if not value:
                    continue
                facts.append(Fact(key=key, value=value, turn=turn, importance=importance,
                                  pinned=importance >= self.threshold, session=session))
        return facts


# ===========================================================================
# 三、摘要压缩：把"说过的话"变成"记下的事"
# ===========================================================================
# 摘要是有损压缩，所以必须遵守两条纪律：
#   ① 摘要要**增量滚动**（新摘要 = 压缩(旧摘要 + 新淘汰的对话)），不能每次从头重算
#      —— 否则老信息会在反复重算中一点点漂移丢失（"摘要的摘要"衰减）；
#   ② 关键事实不能只靠摘要活着，必须**同时**进钉住区和长期存储（双保险）。
#
# 摘要预算也要封顶：摘要自己无限膨胀的话，压缩就白做了。

SUMMARY_PROMPT = """请把下面的对话压缩成不超过 {max_chars} 字的摘要，用于后续对话的上下文。

要求：
1. 保留：已确认的事实（人名、数字、日期、金额、订单号）、用户的明确要求与禁忌、未完成的待办；
2. 丢弃：寒暄、重复内容、已经被推翻的中间讨论；
3. 用陈述句罗列，不要写"用户说……"这样的叙述；
4. 不确定的信息不要写进摘要（宁可缺失，不可写错）。

对话：
{transcript}
"""


class RuleSummarizer:
    """确定性的抽取式摘要器（零依赖、可测试）。

    它模拟的是"摘要模型"这个角色：真实项目里换成一次 LLM 调用即可
    （提示词见上面的 SUMMARY_PROMPT），本课程用规则版保证输出完全可复现。
    """

    KEEP_HINTS = ("预算", "日期", "过敏", "人数", "订单", "发票", "元", "必须", "不要",
                  "禁忌", "地址", "电话", "确认", "一共", "人")

    def __init__(self, max_chars: int = 260) -> None:
        self.max_chars = max_chars

    def summarize(self, pieces: Sequence[str]) -> str:
        """从若干段文本里挑出"值得记住"的句子。"""
        kept: list[str] = []
        seen: set[str] = set()
        for piece in pieces:
            for sentence in re.split(r"[。；;\n]+", piece or ""):
                s = sentence.strip()
                if len(s) < 4 or s in seen:
                    continue
                if any(h in s for h in self.KEEP_HINTS):
                    seen.add(s)
                    kept.append(s)
        text = "；".join(kept)
        if len(text) > self.max_chars:
            text = text[: self.max_chars].rstrip("；") + "…"
        return text


class LLMSummarizer:
    """真实做法：让模型写摘要。**摘要本身也是一次模型调用，也要花钱**。"""

    def __init__(self, llm: LLM, max_chars: int = 260) -> None:
        self.llm = llm
        self.max_chars = max_chars
        self.calls = 0
        self.last_prompt = ""

    def summarize(self, pieces: Sequence[str]) -> str:
        self.calls += 1
        self.last_prompt = SUMMARY_PROMPT.format(max_chars=self.max_chars,
                                                 transcript="\n".join(pieces))
        messages = [Message.system("你是一个擅长压缩对话的助手。"),
                    Message.user(self.last_prompt)]
        return self.llm.complete(messages).text.strip()


# ===========================================================================
# 四、长期记忆：跨会话的事实库
# ===========================================================================
# 短期记忆（窗口+摘要）解决"这一轮对话记不住"，长期记忆解决"下次来又忘了"。
# 它和 RAG（第 06 章）在机制上是一回事：**写入 → 索引 → 按相关性检索 → 注入上下文**。
# 区别只在数据来源：RAG 检索的是文档，长期记忆检索的是"关于这个用户的事实"。


def bigrams(text: str) -> set[str]:
    """中文按字符二元组切分 —— 零依赖、无需分词库，检索效果足够好。

    为什么二元组有效？因为中文的词边界不明确，但**相邻字对的搭配**很有区分度：
    "海鲜过敏" → {海鲜, 鲜过, 过敏}，查询"有什么忌口"命中不了，
    但查询"海鲜"就能命中 —— 这正是我们想要的"关键词级"召回。
    """
    clean = re.sub(r"\s+", "", text or "")
    return {clean[i:i + 2] for i in range(len(clean) - 1)} or ({clean} if clean else set())


@dataclass
class MemoryItem:
    """长期记忆里的一条。带 source（哪一轮说的）便于溯源 —— 和无出处的记忆没法核对。"""

    text: str
    key: str = ""
    session: int = 1
    turn: int = 0
    importance: float = 0.5
    hits: int = 0

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


class LongTermStore:
    """极简长期记忆：写入 + 关键词检索（生产用向量库，但接口就这两个）。"""

    def __init__(self) -> None:
        self.items: list[MemoryItem] = []

    def write(self, fact: Fact) -> MemoryItem:
        """写入事实。**判重是必须的**：同一个事实重复写入会挤占检索位。"""
        for it in self.items:
            if it.key == fact.key and it.text == fact.text:
                it.hits += 1
                return it
        item = MemoryItem(text=fact.text, key=fact.key, session=fact.session,
                          turn=fact.turn, importance=fact.importance)
        self.items.append(item)
        return item

    def search(self, query: str, top_k: int = 3, min_score: float = 1.0) -> list[MemoryItem]:
        """按字符二元组重叠度打分。min_score 是**闸门**：不相关就不注入。

        为什么必须有闸门？因为注入无关记忆比不注入更糟：
        模型会把不相关的旧信息当成当前任务的约束（"上次说要 24 人，这次只有 6 人也按 24 人办"）。
        """
        q = bigrams(query)
        if not q:
            return []
        scored: list[tuple[float, MemoryItem]] = []
        for it in self.items:
            overlap = len(q & bigrams(it.text))
            if overlap >= min_score:
                # 相关性 + 重要性加权：重要的事实更容易被想起来
                scored.append((overlap + it.importance, it))
        scored.sort(key=lambda pair: (-pair[0], pair[1].text))
        return [it for _, it in scored[:top_k]]

    def render(self, items: Sequence[MemoryItem]) -> str:
        return "\n".join(f"- {it.text}（第 {it.session} 次会话）" for it in items)


# ===========================================================================
# 五、记忆管理器：四件套的组装
# ===========================================================================
@dataclass
class Turn:
    """一轮对话（一问一答）。窗口的最小单位是"轮"而不是"条消息"。"""

    index: int
    user: str
    assistant: str = ""

    @property
    def messages(self) -> list[Message]:
        out = [Message.user(self.user)]
        if self.assistant:
            out.append(Message.assistant(self.assistant))
        return out

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.user) + estimate_tokens(self.assistant)


@dataclass
class ContextPack:
    """组装好的一次上下文 + 它的预算账本。"""

    messages: list[Message] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    dropped_turns: int = 0
    recalled: list[MemoryItem] = field(default_factory=list)
    summary: str = ""

    @property
    def tokens(self) -> int:
        return sum(estimate_tokens(m.content) for m in self.messages)

    def render(self) -> str:
        return "\n\n".join(m.to_text() for m in self.messages)

    def ledger(self) -> str:
        lines = [s.line() for s in self.sections]
        lines.append(f"{'合计':<12} {self.tokens:>5} token    "
                     f"（窗口内 {len(self.messages)} 条消息，被折叠 {self.dropped_turns} 轮）")
        return "\n".join(lines)


class MemoryManager:
    """滑动窗口 + 摘要压缩 + 事实钉住 + 长期存储。

    预算分配顺序（**顺序本身就是策略**）：
        ① 系统提示  —— 必须完整，不可压缩（压缩它等于改程序）
        ② 钉住事实  —— 有硬上限（MAX_PINNED），按重要性排序
        ③ 长期召回  —— 有硬上限，且必须过相关性闸门
        ④ 摘要      —— 有硬上限，是"更早对话"的唯一代表
        ⑤ 窗口      —— 拿走剩下的全部（最新的原文，细节最全）
    优先级 = 不可替代性。系统提示不可替代，最新一轮也不可替代（它带着当前问题）。
    """

    def __init__(
        self,
        system_prompt: str,
        budget: int = 1200,
        window_turns: int = 6,
        summary_chars: int = 260,
        summarizer: Any | None = None,
        store: LongTermStore | None = None,
        max_recall: int = 3,
        recall_min_score: float = 1.0,
        use_pinning: bool = True,
    ) -> None:
        self.system_prompt = system_prompt
        self.budget = budget
        self.window_turns = window_turns
        self.extractor = FactExtractor()
        self.summarizer = summarizer or RuleSummarizer(max_chars=summary_chars)
        self.store = store if store is not None else LongTermStore()
        self.max_recall = max_recall
        self.recall_min_score = recall_min_score
        # use_pinning=False 只用于教学对照：把护栏拆掉，亲眼看到事实丢失。
        # 生产代码里永远不要暴露这个开关（能关掉的安全机制等于没有）。
        self.use_pinning = use_pinning

        self.turns: list[Turn] = []
        self.facts: list[Fact] = []
        self.summary_text: str = ""
        self.compressed_turns = 0        # 已经被摘要吸收掉的轮数
        self.summarize_calls = 0

    # ---- 写入 -----------------------------------------------------------
    def add_turn(self, user_text: str, assistant_text: str = "") -> list[Fact]:
        turn = Turn(index=len(self.turns) + 1, user=user_text, assistant=assistant_text)
        self.turns.append(turn)
        fresh = self.extractor.extract(user_text, turn=turn.index)
        for fact in fresh:
            if fact.fingerprint not in {f.fingerprint for f in self.facts}:
                self.facts.append(fact)
            if fact.pinned:
                self.store.write(fact)      # ★ 关键事实同时落库（双保险）
        self._compress_if_needed()
        return fresh

    # ---- 压缩 -----------------------------------------------------------
    def _compress_if_needed(self) -> None:
        """超出窗口的旧对话 → 摘要。**增量滚动**，不是每次重算。"""
        keep = self.window_turns
        if len(self.turns) <= keep:
            return
        aged = self.turns[: len(self.turns) - keep]
        if len(aged) <= self.compressed_turns:
            return
        new_pieces = [t.user + "。" + t.assistant for t in aged[self.compressed_turns:]]
        # 旧摘要参与新一轮压缩 → 保证"很久以前的事实"不会因为反复重算而消失
        pieces = ([self.summary_text] if self.summary_text else []) + new_pieces
        self.summary_text = self.summarizer.summarize(pieces)
        self.compressed_turns = len(aged)
        self.summarize_calls += 1

    # ---- 组装上下文 -----------------------------------------------------
    def build(self, query: str = "") -> ContextPack:
        pack = ContextPack()
        used = 0

        # ① 系统提示（不参与压缩）
        sys_tokens = estimate_tokens(self.system_prompt)
        pack.messages.append(Message.system(self.system_prompt))
        pack.sections.append(Section("系统提示", sys_tokens, len(self.system_prompt), 1,
                                     "不可压缩", budget=sys_tokens))
        used += sys_tokens

        # ② 钉住的事实（按重要性排序，取前 MAX_PINNED 条）
        pinned = sorted([f for f in self.facts if f.pinned],
                        key=lambda f: (-f.importance, f.turn))[:MAX_PINNED] if self.use_pinning else []
        if pinned:
            text = "已确认的关键事实（**必须遵守**）：\n" + "\n".join(f"- {f.text}" for f in pinned)
            t = estimate_tokens(text)
            pack.messages.append(Message.system(text))
            pack.sections.append(Section("钉住事实", t, len(text), len(pinned),
                                         f"永不淘汰（上限 {MAX_PINNED} 条）"))
            used += t

        # ③ 长期召回（过闸门才注入，防止用无关旧信息污染当前任务）
        recalled = self.store.search(query, top_k=self.max_recall, min_score=self.recall_min_score) \
            if query else []
        pinned_keys = {f.fingerprint for f in pinned}
        recalled = [it for it in recalled if it.text not in pinned_keys]
        if recalled:
            text = "可能相关的历史记忆（仅供参考，冲突时以本轮对话为准）：\n" + self.store.render(recalled)
            t = estimate_tokens(text)
            pack.messages.append(Message.system(text))
            pack.sections.append(Section("长期召回", t, len(text), len(recalled), "过相关性闸门"))
            used += t
        pack.recalled = recalled

        # ④ 摘要（更早对话的唯一代表）
        if self.summary_text:
            text = f"更早对话的摘要（共 {self.compressed_turns} 轮，已压缩）：\n{self.summary_text}"
            t = estimate_tokens(text)
            pack.messages.append(Message.system(text))
            pack.sections.append(Section("滚动摘要", t, len(text), 1, f"覆盖 {self.compressed_turns} 轮"))
            used += t

        # ⑤ 最近的对话窗口（原文，细节最全；拿走剩下的预算）
        remaining = max(self.budget - used, estimate_tokens(query) + 8)
        picked: list[Turn] = []
        for turn in reversed(self.turns[-self.window_turns:] if self.window_turns else []):
            if turn.tokens > remaining:
                break
            picked.append(turn)
            remaining -= turn.tokens
        picked.reverse()
        win_tokens = 0
        win_chars = 0
        for turn in picked:
            for msg in turn.messages:
                pack.messages.append(msg)
                win_tokens += estimate_tokens(msg.content)
                win_chars += len(msg.content)
        pack.sections.append(Section("对话窗口", win_tokens, win_chars, len(picked),
                                     f"最近 {len(picked)} 轮原文"))
        used += win_tokens

        # ⑥ 当前问题（永远放在最后 —— 位置本身就是一种强调）
        if query:
            pack.messages.append(Message.user(query))
            pack.sections.append(Section("当前问题", estimate_tokens(query), len(query), 1,
                                         "永远放最后"))
        pack.dropped_turns = max(len(self.turns) - len(picked), 0)
        return pack

    # ---- 观测 -----------------------------------------------------------
    def stats(self) -> dict[str, Any]:
        return {
            "轮数": len(self.turns),
            "事实数": len(self.facts),
            "钉住事实": sum(1 for f in self.facts if f.pinned),
            "摘要字数": len(self.summary_text),
            "摘要压缩次数": self.summarize_calls,
            "长期记忆条数": len(self.store.items),
            "全量历史 token": sum(t.tokens for t in self.turns),
        }


# ===========================================================================
# 六、两个"朴素做法"：作为对照实验的基线
# ===========================================================================
# 有了基线，你才能说清"记忆管理"到底带来了什么。没有对比的优化都是玄学。

def full_history(system_prompt: str, turns: Sequence[Turn], query: str = "") -> list[Message]:
    """基线 A：把全部历史原样塞进去。窗口够大时效果最好，但**一定会撑爆**。"""
    msgs = [Message.system(system_prompt)]
    for t in turns:
        msgs.extend(t.messages)
    if query:
        msgs.append(Message.user(query))
    return msgs


def naive_truncate(system_prompt: str, turns: Sequence[Turn], keep_last: int = 6,
                   query: str = "") -> list[Message]:
    """基线 B：只保留最近 N 轮。

    这是新手最常写的代码（连"记忆管理"都算不上），
    但它**按时间淘汰**而不是按价值淘汰 —— 于是最早说出的关键事实最先被扔掉。
    """
    msgs = [Message.system(system_prompt)]
    for t in turns[-keep_last:] if keep_last else []:
        msgs.extend(t.messages)
    if query:
        msgs.append(Message.user(query))
    return msgs


def count_tokens(messages: Sequence[Message]) -> int:
    return sum(estimate_tokens(m.content) for m in messages)


__all__ = [
    "meter", "Section", "Fact", "FactExtractor", "RuleSummarizer", "LLMSummarizer",
    "MemoryItem", "LongTermStore", "bigrams", "Turn", "ContextPack", "MemoryManager",
    "full_history", "naive_truncate", "count_tokens", "PIN_THRESHOLD", "MAX_PINNED",
    "SUMMARY_PROMPT",
]
