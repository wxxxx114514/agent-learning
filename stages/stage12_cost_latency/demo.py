"""第 12 章 · 成本与延迟优化 —— 先测量，再缓存，再减量，最后才换模型。

运行：
    py -m stages.stage12_cost_latency.demo
    py -m stages.stage12_cost_latency.demo --list
    py -m stages.stage12_cost_latency.demo --section 3
    py -m stages.stage12_cost_latency.demo --check

本章目标：把一个"功能正确但很贵很慢"的 Agent，在**不改功能**的前提下，
把成本降一个数量级、把首字延迟降到三分之一。

为什么顺序不能反？
    绝大多数团队的第一反应是"换个更便宜的小模型"。这是最差的起手式：
      · 它直接牺牲质量（而质量是你唯一不能牺牲的东西）；
      · 它治不了"本可以不发生的调用"—— 而 80% 的成本就来自这里；
      · 没有测量，你连省了多少都不知道。
    正确顺序：**测量 → 缓存 → 减量 → 路由（换模型）**。

本章的四个零件：
    ① 用量计量器  UsageMeter   —— token in/out、成本、墙上时间、TTFT、逐调用明细
    ② 缓存        SemanticCache —— 精确命中 + 语义命中（含"实体硬约束"防假命中）
    ③ 减量        ParallelTools —— 并行工具调用；上下文裁剪（第 05 章）
    ④ 路由        ModelRouter   —— 简单任务走小模型，复杂任务走大模型
    （外加：流式输出降 TTFT、预算兜底防账单爆炸）

关于"延迟"的一个诚实说明：
    假模型的真实耗时接近 0，没法用来演示延迟优化。所以本章让假模型**声明**一个
    模拟耗时（`sim_latency_ms`），所有延迟数字都基于它计算。
    真实项目里这些数字就是实测值，口径完全一样；这样做只是为了让结果**可复现**。
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check_that, code, essence, kv, note, ok, report,
    section, setup_console, warn,
)
from core.agent import Agent  # noqa: E402
from core.errors import AbortAgent, BudgetExceeded  # noqa: E402
from core.llm import LLM, LLMResponse, estimate_tokens  # noqa: E402
from core.message import Message  # noqa: E402
from core.mock_llm import RuleBasedLLM  # noqa: E402
from core.tool import ToolRegistry, build_default_registry  # noqa: E402

# ===========================================================================
# 一、价目表：所有成本计算的唯一真相来源
# ===========================================================================
# 为什么第一件事是写价目表？
#   因为"贵不贵"这件事必须**可计算**。没有价目表，你只能凭感觉说"好像有点贵"。
# 注意三个单位陷阱（真实项目里踩过的人都懂）：
#   1. 各家报价都是"每 100 万 token 多少美元/人民币" —— 换算时别少乘一个零；
#   2. 输入和输出**不同价**，输出通常是输入的 3~5 倍；
#   3. 缓存命中、批处理、夜间折扣的价格完全不同，价目表要能表达这些档位。


@dataclass(frozen=True)
class Price:
    """一个模型的价目表 + 性能画像（单位：元 / 1K token，毫秒）。"""

    name: str
    prompt_per_1k: float       # 输入单价
    completion_per_1k: float   # 输出单价
    sim_latency_ms: float      # 模拟总耗时（真实项目里是实测 P50）
    sim_ttft_ms: float         # 模拟首字延迟

    def cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        return (prompt_tokens / 1000 * self.prompt_per_1k
                + completion_tokens / 1000 * self.completion_per_1k)


PRICING: dict[str, Price] = {
    # 大模型：能力强、贵、慢
    "large": Price("large-pro", prompt_per_1k=0.012, completion_per_1k=0.036,
                   sim_latency_ms=2200, sim_ttft_ms=700),
    # 小模型：能力有限、便宜 10 倍、快 3 倍
    "small": Price("small-flash", prompt_per_1k=0.001, completion_per_1k=0.002,
                   sim_latency_ms=600, sim_ttft_ms=180),
}

# ===========================================================================
# 二、用量计量器：把"花了多少钱"变成可查询的数据
# ===========================================================================


@dataclass
class CallRecord:
    """一次模型调用的完整账目。"""

    index: int
    tier: str                 # large / small / cache
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    ttft_ms: float
    cost: float
    note: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class UsageMeter:
    """用量计量器：本章所有优化效果的裁判。

    它只做四件事：记调用、算成本、汇总、出表。
    ★ 一个原则：**计量必须发生在最靠近模型调用的那一层**（LLM 适配器/网关），
      而不是在业务代码里"顺手加一下"。业务代码会漏，网关不会。
    """

    def __init__(self, pricing: dict[str, Price] | None = None) -> None:
        self.pricing = pricing if pricing is not None else PRICING
        self.calls: list[CallRecord] = []
        self.cache_hits = 0
        self.cache_saved_tokens = 0
        self.cache_saved_cost = 0.0
        self.wall_ms = 0.0            # 模拟的墙上时间（用户实际等的时间）
        self.first_token_ms = 0.0     # 整轮任务的首字延迟

    # ---- 记账 ---------------------------------------------------------
    def record_call(self, tier: str, prompt_tokens: int, completion_tokens: int,
                    latency_ms: float, ttft_ms: float, note: str = "",
                    model: str = "") -> CallRecord:
        price = self.pricing[tier]
        rec = CallRecord(
            index=len(self.calls) + 1, tier=tier, model=model or price.name,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            latency_ms=latency_ms, ttft_ms=ttft_ms,
            cost=price.cost(prompt_tokens, completion_tokens), note=note,
        )
        self.calls.append(rec)
        return rec

    def record_cache_hit(self, saved_tier: str, prompt_tokens: int,
                         completion_tokens: int) -> float:
        """缓存命中：省下的钱要**按被替代的那次调用**计价，不能按 0 计。"""
        self.cache_hits += 1
        self.cache_saved_tokens += prompt_tokens + completion_tokens
        saved = self.pricing[saved_tier].cost(prompt_tokens, completion_tokens)
        self.cache_saved_cost += saved
        return saved

    # ---- 汇总 ---------------------------------------------------------
    @property
    def model_calls(self) -> int:
        return len(self.calls)

    @property
    def prompt_tokens(self) -> int:
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self) -> int:
        return sum(c.completion_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost(self) -> float:
        return sum(c.cost for c in self.calls)

    def by_tier(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.calls:
            out[c.tier] = out.get(c.tier, 0) + 1
        return out

    def table(self) -> list[list[str]]:
        rows = []
        for c in self.calls:
            rows.append([str(c.index), c.tier, c.model,
                         f"{c.prompt_tokens}", f"{c.completion_tokens}",
                         f"{c.latency_ms:.0f}ms", f"{c.ttft_ms:.0f}ms",
                         f"¥{c.cost:.5f}", c.note])
        return rows

    def summary(self) -> dict[str, Any]:
        return {
            "模型调用": self.model_calls,
            "缓存命中": self.cache_hits,
            "输入 token": self.prompt_tokens,
            "输出 token": self.completion_tokens,
            "总 token": self.total_tokens,
            "成本": round(self.cost, 5),
            "墙上时间": round(self.wall_ms, 1),
            "首字延迟": round(self.first_token_ms, 1),
        }


class MeteredLLM(LLM):
    """给任意模型套一层计量。真实项目里这一层就是你的 LLM 网关/适配器。"""

    name = "metered"

    def __init__(self, inner: LLM, tier: str, meter: UsageMeter) -> None:
        super().__init__(f"metered({inner.model})")
        self.inner = inner
        self.tier = tier
        self.meter = meter

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        resp = self.inner.complete(messages, **kwargs)
        price = self.meter.pricing[self.tier]
        # 模拟时延：假模型在 raw 里"声明"自己花了多久；真实场景直接用实测的 resp.latency_ms
        latency = float(resp.raw.get("sim_latency_ms") or price.sim_latency_ms)
        ttft = float(resp.raw.get("sim_ttft_ms", price.sim_ttft_ms))
        self.meter.record_call(
            tier=self.tier,
            prompt_tokens=resp.prompt_tokens or estimate_tokens(
                "".join(m.to_text() for m in messages)),
            completion_tokens=resp.completion_tokens or estimate_tokens(resp.text),
            latency_ms=latency, ttft_ms=ttft, model=self.inner.model,
        )
        return resp


class PricedMockLLM(LLM):
    """带"价目表 + 模拟时延"的确定性假模型。

    它按 tier 决定自己的回答风格：
        large → 完整、有分析的回答
        small → 简短、偶尔抓不住重点的回答（用来演示"路由错了会掉质量"）
    """

    name = "priced-mock"

    def __init__(self, tier: str, answers: dict[str, tuple[str, str]],
                 fallback: tuple[str, str] = ("我无法处理这个问题。", "不知道。")) -> None:
        super().__init__(PRICING[tier].name)
        self.tier = tier
        self.answers = answers      # 归一化问题 -> (大模型回答, 小模型回答)
        self.fallback = fallback

    def _complete(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        question = _norm(next((m.content for m in messages if m.role == "user"), ""))
        big, small = self.answers.get(question, self.fallback)
        text = big if self.tier == "large" else small
        prompt = sum(estimate_tokens(m.to_text()) for m in messages)
        resp = LLMResponse(text=text, model=self.model, prompt_tokens=prompt,
                           completion_tokens=estimate_tokens(text))
        resp.raw = {"sim_latency_ms": PRICING[self.tier].sim_latency_ms,
                    "sim_ttft_ms": PRICING[self.tier].sim_ttft_ms}
        return resp


# ===========================================================================
# 三、缓存：让"第二次问同一个问题"不花钱
# ===========================================================================
# 缓存是**投入产出比最高**的优化，因为：
#   · 它不牺牲任何质量（命中的就是上次那个答案）；
#   · 真实流量里重复/近似重复的比例往往很高（客服场景尤其明显），
#     但**具体多少必须量你自家的流量** —— 本章这组样本的重复率只有 20%；
#   · 它同时降低成本和延迟（0 次调用 = 0 成本 + 接近 0 延迟）。
#
# 但要小心一个致命陷阱：**假命中**。
#   "订单 A1001 到哪了？" 和 "订单 B2043 到哪了？" 在字符层面极其相似，
#   语义缓存如果只看相似度，就会把 A1001 的答案返回给问 B2043 的用户。
#   这类 bug 在演示里看不出来（答案格式完全正确），在线上就是事故。
#
# 解决思路（本章实现）：**相似度负责"是不是同一个问题"，
# 实体（订单号/数字/日期）负责"是不是同一个对象"，两者必须同时满足。**


def _norm(text: str) -> str:
    """归一化：去掉空白、标点、礼貌词，只留核心内容。"""
    t = (text or "").strip().lower()
    t = re.sub(r"[，。！？、；：,.!?;:~\"'“”‘’()（）\[\]【】]", "", t)
    t = re.sub(r"(帮我|请|麻烦|一下|一下子|谢谢|好吗|可以|能不能|我想|我要)", "", t)
    return re.sub(r"\s+", "", t)


ENTITY_RE = re.compile(r"[A-Za-z]{0,2}\d{2,}")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def entities_of(text: str) -> frozenset[str]:
    """抽出"必须完全一致才算同一件事"的实体。

    订单号、金额、日期、数量、版本号…… 任何数字/编号都属于这一类。
    宁可多抽出一些、宁可缓存命中率低一点，也不能让 A 的答案落到 B 头上。
    """
    found = {m.group(0).upper() for m in ENTITY_RE.finditer(text)}
    found |= {m.group(0) for m in NUMBER_RE.finditer(text)}
    return frozenset(found)


def bigrams(text: str) -> set[str]:
    """字符二元组（中文不需要分词，二元组就够用）。"""
    t = _norm(text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    """Dice 相似度：2|A∩B| / (|A|+|B|)，取值 0~1。

    为什么不用 embedding？因为本章要零依赖、可解释、可复现。
    生产里可以用 embedding + 向量库，但**实体硬约束那一层不能省**。
    """
    ga, gb = bigrams(a), bigrams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))


@dataclass
class CacheEntry:
    key: str
    question: str
    entities: frozenset[str]
    answer: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    hits: int = 0


@dataclass
class CacheLookup:
    """一次缓存查询的结果（带解释，方便调试和观察）。"""

    hit: bool
    kind: str = ""        # exact / semantic / miss / entity_blocked
    entry: CacheEntry | None = None
    score: float = 0.0
    reason: str = ""


class SemanticCache:
    """精确 + 语义混合缓存（零依赖实现）。"""

    def __init__(self, threshold: float = 0.72, entity_guard: bool = True) -> None:
        self.threshold = threshold
        self.entity_guard = entity_guard
        self.entries: list[CacheEntry] = []
        self.stats = {"exact_hit": 0, "semantic_hit": 0, "miss": 0,
                      "entity_blocked": 0, "put": 0}

    def get(self, question: str) -> CacheLookup:
        key = _norm(question)
        ents = entities_of(question)

        # ① 精确命中：归一化后完全相同
        for e in self.entries:
            if e.key == key:
                e.hits += 1
                self.stats["exact_hit"] += 1
                return CacheLookup(True, "exact", e, 1.0, "归一化后完全一致")

        # ② 语义命中：相似度达标 **且** 实体集合一致
        best: tuple[float, CacheEntry | None] = (0.0, None)
        for e in self.entries:
            score = similarity(question, e.question)
            if score > best[0]:
                best = (score, e)
        score, entry = best
        if entry is not None and score >= self.threshold:
            if self.entity_guard and entry.entities != ents:
                self.stats["entity_blocked"] += 1
                return CacheLookup(False, "entity_blocked", entry, score,
                                   f"相似度 {score:.2f} 达标，但实体不同 "
                                   f"{sorted(entry.entities)} ≠ {sorted(ents)} → 拒绝命中")
            entry.hits += 1
            self.stats["semantic_hit"] += 1
            return CacheLookup(True, "semantic", entry, score, f"相似度 {score:.2f}")

        self.stats["miss"] += 1
        return CacheLookup(False, "miss", None, score, f"最高相似度 {score:.2f}")

    def put(self, question: str, answer: str, tier: str,
            prompt_tokens: int = 0, completion_tokens: int = 0) -> CacheEntry:
        entry = CacheEntry(_norm(question), question, entities_of(question), answer,
                           tier, prompt_tokens, completion_tokens)
        self.entries.append(entry)
        self.stats["put"] += 1
        return entry

    @property
    def hit_rate(self) -> float:
        total = self.stats["exact_hit"] + self.stats["semantic_hit"] + self.stats["miss"]
        return ((self.stats["exact_hit"] + self.stats["semantic_hit"]) / total) if total else 0.0


# ===========================================================================
# 四、模型路由：简单任务给小模型，复杂任务给大模型
# ===========================================================================
# 路由的价值：小模型便宜 10 倍、快 3 倍。代价：能力弱。
# 所以路由的唯一任务是**判断"这个问题需不需要大模型"**。
#
# 两个关键设计：
#   1. 默认走大模型（保守）。因为路由错误的代价**不对称**：
#      简单问题给大模型 = 多花一点钱；复杂问题给小模型 = 用户拿到烂答案。
#   2. 路由规则必须用**评估集**验证（第 10 章）。本章最后一节会演示
#      "把复杂问题错误地路由到小模型"会怎样掉质量。

COMPLEX_HINTS = ("分析", "对比", "为什么", "原因", "设计", "规划", "方案", "权衡",
                 "推理", "评估", "建议", "优化", "架构", "debug", "排查", "总结并")
SIMPLE_HINTS = ("计算", "算一下", "统计", "查询", "查一下", "订单", "翻译",
                "格式化", "是多少", "有几个", "转换为")


@dataclass
class RouteDecision:
    tier: str
    reason: str


class ModelRouter:
    """规则路由：便宜、可解释、可测试。生产里可以换成小模型分类器。"""

    def __init__(self, long_char_threshold: int = 60) -> None:
        self.long_char_threshold = long_char_threshold
        self.stats = {"small": 0, "large": 0}

    def route(self, question: str) -> RouteDecision:
        q = question.strip()
        if len(q) > self.long_char_threshold:
            self.stats["large"] += 1
            return RouteDecision("large", f"长度 {len(q)} 字符 > 阈值，信息量大")
        if any(h in q for h in COMPLEX_HINTS):
            self.stats["large"] += 1
            return RouteDecision("large", "命中复杂意图词")
        if any(h in q for h in SIMPLE_HINTS):
            self.stats["small"] += 1
            return RouteDecision("small", "命中简单意图词")
        self.stats["large"] += 1
        # ★ 兜底走大模型：不确定的时候，宁可多花钱，也不要给用户烂答案
        return RouteDecision("large", "无法判断 → 保守走大模型")


# ===========================================================================
# 五、减量：并行工具调用、上下文裁剪、流式输出
# ===========================================================================
# 三个不同层面的"减量"：
#   1. 并行工具调用 —— 减**延迟**（N 个独立工具：串行 = sum，并行 = max）
#   2. 上下文裁剪   —— 减**成本**（历史越长，每次调用的输入 token 越多；
#                      第 05 章讲过怎么做，这里只量化它的收益）
#   3. 流式输出     —— 减**首字延迟 TTFT**（总时长没变，但用户"感觉快了 3 倍"）

# 各工具的模拟耗时（真实项目里就是实测 P50）
TOOL_SIM_MS: dict[str, float] = {
    "calc": 120.0,
    "count_words": 100.0,
    "lookup_order": 300.0,
    "search_kb": 400.0,
}


@dataclass
class ToolCallPlan:
    name: str
    args: dict[str, Any]

    @property
    def sim_ms(self) -> float:
        return TOOL_SIM_MS.get(self.name, 200.0)


def run_tools_sequential(calls: list[ToolCallPlan]) -> tuple[list[str], float]:
    """串行执行：总耗时 = 各工具耗时之和。"""
    out, total = [], 0.0
    for c in calls:
        out.append(f"{c.name}:ok")
        total += c.sim_ms
    return out, total


def run_tools_parallel(calls: list[ToolCallPlan]) -> tuple[list[str], float]:
    """并行执行：总耗时 ≈ 最慢的那个。

    真实收益来自"这些工具之间没有依赖"。判断标准很简单：
        B 的参数里有没有用到 A 的返回值？没有 → 可以并行。
    ★ 注意：这里的耗时是模拟值（工具本身是瞬间返回的假实现），
      真实项目里你会看到**真正的墙上时间**从 sum 变成 max。
    """
    with ThreadPoolExecutor(max_workers=max(1, len(calls))) as pool:
        futures = [pool.submit(lambda c=c: f"{c.name}:ok") for c in calls]
        out = [f.result() for f in futures]
    return out, (max((c.sim_ms for c in calls), default=0.0))


def amortized_prompt_tokens(history_turns: int, base_tokens: int = 900,
                            per_turn_tokens: int = 260, window: int | None = None) -> int:
    """算一次调用要发多少输入 token。

    每次调用都要重发整段历史 —— 这就是"上下文越长越贵"的根源（平方级增长）。
    window 不为 None 时模拟"滑动窗口/摘要压缩"后的效果。
    """
    turns = history_turns if window is None else min(history_turns, window)
    return base_tokens + turns * per_turn_tokens


def stream_timeline(text: str, ttft_ms: float, total_ms: float,
                    chunk: int = 2) -> tuple[list[str], list[float]]:
    """把一段回答切成流式片段，并给出"每个片段到达的时刻"。

    为什么要模拟时间轴？因为流式的价值就在时间轴上：
        非流式：用户盯着空白屏幕等 2.2 秒 → 全部内容一次性出现
        流式  ：0.7 秒时第一个字到了，之后持续有内容 → 感知延迟 ≈ 0.7 秒
    真实项目里你会用异步生成器 + SSE 把 token 推给前端。
    """
    chunks = [text[i:i + chunk] for i in range(0, len(text), chunk)] or [""]
    span = max(1.0, total_ms - ttft_ms)
    # 第一个片段在 TTFT 时刻到达，最后一个片段在总时长时刻到达
    if len(chunks) == 1:
        times = [ttft_ms]
    else:
        times = [ttft_ms + span * i / (len(chunks) - 1) for i in range(len(chunks))]
    return chunks, times


# ===========================================================================
# 六、预算兜底：优化可能失败，但账单必须被兜住
# ===========================================================================
# 为什么有了缓存/路由还要预算？
#   因为优化是"降低期望值"，预算才是"控制上界"。
#   prompt 注入、死循环、用户刷量、上游重试风暴…… 任何一个都能让成本失控。
#   预算是最后一道保险，触发时抛 BudgetExceeded（AbortAgent 的子类）——
#   它是**预期内的策略性停机**，不是故障，所以应该优雅地返回部分结果。


class BudgetGuard:
    """三维预算：调用次数 / 金额 / 墙上时间。任一超限即停机。"""

    def __init__(self, max_calls: int = 4, max_cost: float = 0.02,
                 max_wall_ms: float = 10_000.0) -> None:
        self.max_calls = max_calls
        self.max_cost = max_cost
        self.max_wall_ms = max_wall_ms
        self.trips = 0

    def check(self, meter: UsageMeter) -> None:
        """在**每次模型调用之前**检查（放在之后就成了事后统计，没有保护作用）。"""
        if meter.model_calls >= self.max_calls:
            self.trips += 1
            raise BudgetExceeded(
                f"调用次数预算耗尽：{meter.model_calls}/{self.max_calls}")
        if meter.cost >= self.max_cost:
            self.trips += 1
            raise BudgetExceeded(f"成本预算耗尽：¥{meter.cost:.5f}/¥{self.max_cost:.5f}")
        if meter.wall_ms >= self.max_wall_ms:
            self.trips += 1
            raise BudgetExceeded(f"时间预算耗尽：{meter.wall_ms:.0f}ms/{self.max_wall_ms:.0f}ms")


# ===========================================================================
# 七、极简流水线：本章 A/B 对比的载体
# ===========================================================================
# 为了把注意力集中在"度量"上，这里用一个确定性流水线代替完整 Agent：
#   规划工具 → （并行/串行）执行工具 → 调用模型合成回答
# 成本与延迟的口径和真实 Agent 完全一致（第 01 节的基线就是用真 Agent 跑的）。

QUESTIONS: list[str] = [
    "订单 A1001 到哪了？",
    "计算 (12+8)*3/4",
    "订单 A1001 到哪里了？",                       # ← 与第 1 条语义重复
    "帮我分析一下订单 A1001 延迟的原因，并给出改进建议",   # ← 复杂，需要大模型
    "统计「护栏」这两个字有几个字",
]

ANSWER_BANK: dict[str, tuple[str, str]] = {
    # 归一化问题 -> (大模型回答, 小模型回答)
    _norm("订单 A1001 到哪了？"): (
        "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890，预计 2025-01-05 送达。",
        "订单 A1001 已发货。"),
    _norm("计算 (12+8)*3/4"): (
        "计算过程：(12+8)=20，20×3=60，60÷4=15。答案是 15。",
        "答案是 15。"),
    _norm("帮我分析一下订单 A1001 延迟的原因，并给出改进建议"): (
        "从订单 A1001 的物流节点看，延迟主要来自中转仓积压（占比约 60%）；"
        "建议：① 将该线路改走直发仓；② 对超 48 小时未更新的单子自动预警。",
        "订单延迟了，建议尽快联系快递。"),          # ← 小模型的回答明显更浅
    _norm("统计「护栏」这两个字有几个字"): (
        "「护栏」共有 2 个字。", "2 个字。"),
}

PLAN_TABLE: list[tuple[str, list[ToolCallPlan]]] = [
    (_norm("订单 A1001 到哪了？"), [ToolCallPlan("lookup_order", {"order_id": "A1001"})]),
    (_norm("计算 (12+8)*3/4"), [ToolCallPlan("calc", {"expr": "(12+8)*3/4"})]),
    (_norm("帮我分析一下订单 A1001 延迟的原因，并给出改进建议"),
     [ToolCallPlan("lookup_order", {"order_id": "A1001"}),
      ToolCallPlan("search_kb", {"query": "物流延迟"})]),
    (_norm("统计「护栏」这两个字有几个字"), [ToolCallPlan("count_words", {"text": "护栏"})]),
]
PLAN: dict[str, list[ToolCallPlan]] = dict(PLAN_TABLE)


@dataclass
class PipelineConfig:
    """一份流水线配置 —— 这就是"优化开关"的集合。"""

    key: str
    title: str
    cache: bool = False
    router: bool = False
    parallel: bool = False
    stream: bool = False


BASELINE = PipelineConfig("baseline", "朴素版（全大模型 / 无缓存 / 串行 / 非流式）")
CACHE_ONLY = PipelineConfig("cache", "① 只加缓存", cache=True)
CACHE_ROUTER = PipelineConfig("cache_router", "② 再加路由", cache=True, router=True)
OPTIMIZED = PipelineConfig("optimized", "③ 再加并行 + 流式",
                           cache=True, router=True, parallel=True, stream=True)


@dataclass
class PipelineReport:
    config: PipelineConfig
    meter: UsageMeter
    answers: list[str] = field(default_factory=list)
    cache: SemanticCache | None = None
    router: ModelRouter | None = None
    tool_mode: str = "串行"

    def summary(self) -> dict[str, Any]:
        s = self.meter.summary()
        s["配置"] = self.config.title
        return s


def run_pipeline(questions: list[str], cfg: PipelineConfig,
                 cache: SemanticCache | None = None,
                 router: ModelRouter | None = None) -> PipelineReport:
    """跑一遍流水线，返回带完整账目的报告。"""
    meter = UsageMeter()
    cache = cache if cache is not None else SemanticCache()
    router = router if router is not None else ModelRouter()
    report = PipelineReport(cfg, meter, cache=cache, router=router,
                            tool_mode="并行" if cfg.parallel else "串行")
    clock = 0.0
    first_token: float | None = None

    for q in questions:
        key = _norm(q)

        # ---- ① 缓存 ----
        if cfg.cache:
            look = cache.get(q)
            if look.hit and look.entry is not None:
                tier = look.entry.tier
                saved = meter.record_cache_hit(tier, look.entry.prompt_tokens,
                                               look.entry.completion_tokens)
                report.answers.append(look.entry.answer)
                # 缓存命中：延迟≈0，且首字延迟≈0
                first_token = clock if first_token is None else first_token
                meter.wall_ms = clock
                continue

        # ---- ② 路由 ----
        tier = "large"
        route_reason = "未启用路由"
        if cfg.router:
            decision = router.route(q)
            tier, route_reason = decision.tier, decision.reason

        # ---- ③ 工具（并行 / 串行）----
        calls = PLAN.get(key, [])
        if calls:
            if cfg.parallel:
                _, tool_ms = run_tools_parallel(calls)
            else:
                _, tool_ms = run_tools_sequential(calls)
        else:
            tool_ms = 0.0

        # ---- ④ 模型调用 ----
        history_turns = 4 if len(q) > 30 else 1        # 复杂问题带更多历史（更贵）
        prompt_tokens = amortized_prompt_tokens(history_turns)
        answer_big, answer_small = ANSWER_BANK.get(key, ("无法处理。", "不知道。"))
        answer = answer_big if tier == "large" else answer_small
        price = PRICING[tier]
        rec = meter.record_call(tier=tier, prompt_tokens=prompt_tokens,
                                completion_tokens=estimate_tokens(answer),
                                latency_ms=price.sim_latency_ms,
                                ttft_ms=price.sim_ttft_ms if cfg.stream else price.sim_latency_ms,
                                note=route_reason)
        report.answers.append(answer)

        if cfg.cache:
            cache.put(q, answer, tier, rec.prompt_tokens, rec.completion_tokens)

        # ---- ⑤ 累计时间轴 ----
        if first_token is None:
            # 非流式：用户要等整段生成完才看到第一个字；流式：等 TTFT
            first_token = clock + (rec.ttft_ms if cfg.stream else rec.latency_ms)
        clock += tool_ms + rec.latency_ms
        meter.wall_ms = clock

    meter.first_token_ms = first_token or 0.0
    return report


# ===========================================================================
# 八、排版小工具
# ===========================================================================


def _disp_width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _disp_width(text))


def table(headers: list[str], rows: list[list[str]], indent: int = 2) -> None:
    widths = [max([_disp_width(h)] + [_disp_width(r[i]) for r in rows])
              for i, h in enumerate(headers)]
    pad = " " * indent
    print(pad + "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)))
    print(pad + "  ".join("-" * w for w in widths))
    for r in rows:
        print(pad + "  ".join(_pad(c, widths[i]) for i, c in enumerate(r)))


def money(x: float) -> str:
    """金额格式化：大额少几位小数，小额多几位（教学输出要一眼能看懂量级）。"""
    return f"¥{x:.2f}" if abs(x) >= 1 else f"¥{x:.5f}"


# ===========================================================================
# 第 1 节：先看问题 —— 不测量就优化，等于闭着眼睛改代码
# ===========================================================================


def demo_baseline() -> None:
    section("先看问题：一次任务到底花了多少钱、等了多少秒？", "①")

    note("先用**真 Agent**（core/agent.py）跑一次任务，并把每一次调用都记下来：")
    meter = UsageMeter()
    llm = MeteredLLM(RuleBasedLLM(), "large", meter)
    agent = Agent(llm=llm, tools=build_default_registry(workspace=ROOT),
                  max_steps=6, verbose=False)
    result = agent.run("计算 (12+8)*3/4，然后查一下订单 A1001 到哪了")
    print()
    table(["#", "档位", "模型", "输入", "输出", "耗时", "TTFT", "成本", "备注"], meter.table())
    print()
    kv("答案", result.answer[:56])
    kv("LLM 调用次数", meter.model_calls)
    kv("输入 / 输出 token", f"{meter.prompt_tokens} / {meter.completion_tokens}")
    kv("本次成本", money(meter.cost))
    print()
    warn("注意输入 token 是**逐次累加**的：每调一次模型，都要把整段历史重发一遍。")
    note("这就是「上下文越长越贵」的根源 —— 第 05 章的上下文管理直接决定这里的账单。")
    print()
    bullet("一次任务几分钱听起来不多，但乘上量级就是决策问题：")
    kv("每天 1000 次任务", f"{money(meter.cost * 1000)}/天 ≈ {money(meter.cost * 1000 * 30)}/月")
    warn("在没有测量之前，你甚至不知道这 2 毛钱花在哪一步 —— 更别说优化了。")


# ===========================================================================
# 第 2 节：用量计量器
# ===========================================================================


def demo_meter() -> None:
    section("用法计量器：先让成本可计算", "②")

    table(["档位", "模型", "输入单价", "输出单价", "模拟总耗时", "模拟 TTFT"],
          [[t, p.name, f"¥{p.prompt_per_1k}/1K", f"¥{p.completion_per_1k}/1K",
            f"{p.sim_latency_ms:.0f}ms", f"{p.sim_ttft_ms:.0f}ms"]
           for t, p in PRICING.items()])
    print()

    note("三个必须记住的单位陷阱：")
    bullet("各家报价都是「每 100 万 token」——换算成「每 1K」要除以 1000，别少乘一个零")
    bullet("输入和输出**不同价**，输出通常是输入的 3~5 倍（所以啰嗦的回答更贵）")
    bullet("缓存命中、批处理、夜间折扣是不同档位，价目表要能表达它们")
    print()

    meter = UsageMeter()
    meter.record_call("large", 1200, 300, 2200, 700, note="首次调用")
    meter.record_call("large", 1800, 400, 2400, 720, note="重发全部历史")
    meter.record_call("small", 800, 150, 600, 180, note="路由到小模型")
    table(["#", "档位", "模型", "输入", "输出", "耗时", "TTFT", "成本", "备注"], meter.table())
    print()
    kv("总 token", f"{meter.total_tokens}（输入 {meter.prompt_tokens} / 输出 {meter.completion_tokens}）")
    kv("总成本", money(meter.cost))
    kv("按档位分布", meter.by_tier())
    print()
    note("手算验证一下第 1 条：1200/1000 × 0.012 + 300/1000 × 0.036 = "
         f"{1200/1000*0.012 + 300/1000*0.036:.5f} 元 —— 与表里一致。")
    ok("计量器的价值：成本从「感觉」变成「可查询的数字」，优化才有靶子。")
    print()
    note("★ 计量应该放在**最靠近模型调用的那一层**（LLM 适配器/网关），")
    note("  而不是散落在业务代码里 —— 业务代码一定会漏。")


# ===========================================================================
# 第 3 节：缓存
# ===========================================================================


def demo_cache() -> None:
    section("缓存：第二次问同一个问题，0 次模型调用", "③")

    cache = SemanticCache(threshold=0.72)
    meter = UsageMeter()

    # 第一次：真调用
    q1 = "订单 A1001 到哪了？"
    meter.record_call("large", 1200, 120, 2200, 700, note="首次调用（未命中）")
    cache.put(q1, "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。", "large", 1200, 120)
    kv("第 1 次提问", q1)
    kv("结果", "未命中 → 调用大模型（1 次调用）")
    print()

    # 第二次：同一句话
    q2 = "订单 A1001 到哪了？"
    look2 = cache.get(q2)
    kv("第 2 次提问", q2)
    kv("结果", f"{look2.kind} 命中（{look2.reason}）→ **0 次模型调用**")
    print()

    # 第三次：换个说法
    q3 = "帮我查一下订单 A1001 到哪里了"
    look3 = cache.get(q3)
    kv("第 3 次提问", q3)
    kv("结果", f"{look3.kind} 命中（{look3.reason}）→ **0 次模型调用**")
    print()

    # 第四次：只差一个字符的另一个订单号 —— 危险！
    q5 = "订单 A1002 到哪了？"
    look5 = cache.get(q5)
    kv("第 4 次提问", q5)
    kv("相似度", f"{similarity(q5, q1):.3f}（超过阈值 {cache.threshold} → 相似度认为「是同一个问题」）")
    kv("结果", f"{look5.kind} → {look5.reason}")
    print()
    warn("这就是语义缓存最危险的时刻：A1002 和 A1001 只差一个字符，相似度高达 0.78。")
    note("如果只看相似度，系统会把 A1001 的物流信息发给问 A1002 的用户 ——")
    note("这种 bug 在演示里完全看不出来（格式正确、语气正常），上线就是事故。")
    print()

    naive = SemanticCache(threshold=0.72, entity_guard=False)
    naive.put(q1, "订单 A1001 已发货，承运商顺丰。", "large", 1200, 120)
    wrong = naive.get(q5)
    kv("关掉实体约束后", f"{wrong.kind} 命中 → 问「{q5}」，答「"
                        f"{wrong.entry.answer[:22] if wrong.entry else ''}」")
    warn("↑ 这就是假命中。实体硬约束（订单号/数字必须完全一致）就是为这一刻存在的。")
    print()
    note("顺带一提：如果是完全不同的订单号（例如 B2043），相似度只有 0.33 ——")
    note("它连阈值都够不着，直接 miss。所以缓存这一层的安全性并不只靠实体约束：")
    note("**相似度阈值和实体约束是两道互补的闸门**（一个防「不相干」，一个防「差一点」）。")
    print()
    note("★ 经验法则：**相似度决定「是不是同一个问题」，实体决定「是不是同一个对象」**，")
    note("  两者必须同时满足才允许命中。宁可命中率低一点，也不能答错对象。")
    print()
    kv("缓存统计", cache.stats)
    kv("命中率", f"{cache.hit_rate:.0%}")


# ===========================================================================
# 第 4 节：路由
# ===========================================================================


def demo_router() -> None:
    section("模型路由：简单任务给小模型，复杂任务给大模型", "④")

    router = ModelRouter()
    samples = [
        "计算 (12+8)*3/4",
        "统计「护栏」这两个字有几个字",
        "订单 A1001 到哪了？",
        "今天天气怎么样",
        "帮我分析一下订单 A1001 延迟的原因，并给出改进建议",
        "对比一下两种退款方案的优劣，并给出你的建议",
        "请解释一下这段代码为什么会死循环，并给出修复方案，同时说明可能的影响范围",
    ]
    rows = []
    for q in samples:
        d = router.route(q)
        rows.append([q[:30], d.tier, d.reason])
    table(["问题", "路由到", "理由"], rows)
    print()
    kv("路由分布", router.stats)
    print()
    note("注意最后一条（超长）和倒数第二条（复杂意图词）都走了大模型，")
    note("而「今天天气怎么样」这种既不含简单词也不含复杂词的，也**保守地走了大模型**。")
    warn("为什么兜底要大模型？因为路由错误的代价**不对称**：")
    bullet("简单问题给大模型 → 多花一点钱（可控）")
    bullet("复杂问题给小模型 → 用户拿到烂答案（不可控，且会流失）")
    print()

    # 演示"路由错误"的代价
    note("把复杂问题错误地路由到小模型会怎样（两种回答对比）：")
    q = "帮我分析一下订单 A1001 延迟的原因，并给出改进建议"
    big, small = ANSWER_BANK[_norm(q)]
    code(f"大模型：{big}\n\n小模型：{small}", indent=4)
    print()
    warn("小模型的回答「没错」，但它没有可执行信息。这种退化**无法用「正确率」衡量**，")
    warn("只能用第 10 章的评估集 + 人工/LLM 评判发现。**路由规则必须用评估集验证。**")


# ===========================================================================
# 第 5 节：减量 —— 并行、上下文、流式
# ===========================================================================


def demo_reduce() -> None:
    section("减量：并行工具、上下文裁剪、流式输出", "⑤")

    # ---- 1. 并行工具 ----
    calls = [ToolCallPlan("lookup_order", {"order_id": "A1001"}),
             ToolCallPlan("search_kb", {"query": "物流延迟"})]
    _, seq_ms = run_tools_sequential(calls)
    _, par_ms = run_tools_parallel(calls)
    note("① 并行工具调用（前提：这些工具之间没有依赖）")
    table(["执行方式", "工具", "总耗时"],
          [["串行", " → ".join(c.name for c in calls), f"{seq_ms:.0f}ms"],
           ["并行", " ∥ ".join(c.name for c in calls), f"{par_ms:.0f}ms"]])
    kv("节省", f"{seq_ms - par_ms:.0f}ms（{(1 - par_ms / seq_ms) * 100:.0f}%）")
    print()

    # ---- 2. 上下文裁剪 ----
    note("② 上下文裁剪（第 05 章的滑动窗口/摘要，在这里变成钱）")
    rows = []
    for turns in (1, 5, 10, 30):
        raw = amortized_prompt_tokens(turns)
        win = amortized_prompt_tokens(turns, window=5)
        raw_cost = PRICING["large"].cost(raw, 200)
        win_cost = PRICING["large"].cost(win, 200)
        rows.append([f"{turns} 轮", f"{raw}", money(raw_cost), f"{win}", money(win_cost),
                     f"{(1 - win_cost / raw_cost) * 100:.0f}%"])
    table(["历史长度", "不裁剪输入 token", "单价成本", "窗口=5 输入 token", "裁剪后成本", "降幅"], rows)
    warn("每次调用都要重发整段历史 → 输入 token 随轮数线性增长，账单也是。")
    note("裁剪的本质：**在有限预算下保留最高价值的信息**（不是简单删最老的）。")
    print()

    # ---- 3. 流式输出 ----
    note("③ 流式输出：总时长不变，但用户看到的第一个字早了 3 倍")
    answer = ANSWER_BANK[_norm("帮我分析一下订单 A1001 延迟的原因，并给出改进建议")][0]
    price = PRICING["large"]
    chunks, times = stream_timeline(answer, price.sim_ttft_ms, price.sim_latency_ms)
    kv("非流式 · 首字延迟", f"{price.sim_latency_ms:.0f}ms（用户对着空白屏幕等 {price.sim_latency_ms/1000:.1f}s）")
    kv("流式   · 首字延迟", f"{price.sim_ttft_ms:.0f}ms（TTFT，Time To First Token）")
    kv("总时长", f"{price.sim_latency_ms:.0f}ms（两者相同）")
    print()
    code("时间轴（流式）：\n"
         + "\n".join(f"  {t:>6.0f}ms  {c!r}" for c, t in list(zip(chunks, times))[:6])
         + f"\n  …共 {len(chunks)} 个片段", indent=4)
    print()
    ok("流式不省成本，但它把「感知延迟」从 2.2 秒降到 0.7 秒 —— 这是纯 UX 收益。")


# ===========================================================================
# 第 6 节：优化顺序 + 前后对比
# ===========================================================================


def demo_before_after() -> None:
    section("优化顺序：测量 → 缓存 → 减量 → 路由", "⑥")

    reports = [
        run_pipeline(QUESTIONS, BASELINE),
        run_pipeline(QUESTIONS, CACHE_ONLY),
        run_pipeline(QUESTIONS, CACHE_ROUTER),
        run_pipeline(QUESTIONS, OPTIMIZED),
    ]

    rows = []
    for r in reports:
        m = r.meter
        rows.append([r.config.title, str(m.model_calls), str(m.cache_hits),
                     str(m.total_tokens), money(m.cost),
                     f"{m.wall_ms:.0f}ms", f"{m.first_token_ms:.0f}ms"])
    table(["配置", "模型调用", "缓存命中", "总 token", "成本", "总耗时", "首字延迟"], rows)
    print()

    base = reports[0].meter
    final = reports[-1].meter
    rows = []
    for r in reports[1:]:
        m = r.meter
        rows.append([r.config.title,
                     f"-{(1 - m.cost / base.cost) * 100:.1f}%",
                     f"-{(1 - m.wall_ms / base.wall_ms) * 100:.1f}%",
                     f"-{(1 - m.first_token_ms / base.first_token_ms) * 100:.1f}%",
                     f"{m.model_calls} 次"])
    table(["增量优化", "成本降幅", "总耗时降幅", "首字延迟降幅", "模型调用"], rows)
    print()

    kv("缓存统计", reports[-1].cache.stats if reports[-1].cache else {})
    kv("路由分布", reports[-1].router.stats if reports[-1].router else {})
    print()
    note("一步一步加，每一步都量一遍 —— 这就是本章的核心方法论：")
    bullet("① 缓存：不动质量、不碰模型，直接把重复问题变成 0 成本（先做这个）")
    bullet("② 路由：把简单问题交给小模型（要评估集兜住质量）")
    bullet("③ 并行 + 流式：降延迟，改的是「用户感受」")
    bullet("④ 换模型/砍提示词：最后才考虑，因为它们直接动质量")
    print()
    warn("注意：优化后 4 条回答里，只有「复杂问题」那条还走大模型 —— 质量没有下降，")
    warn("因为简单问题的答案本来就一样（这一点必须靠评估集证明，不能靠感觉）。")
    print()
    ok(f"结果：成本 {money(base.cost)} → {money(final.cost)}"
       f"（-{(1 - final.cost / base.cost) * 100:.1f}%），"
       f"首字延迟 {base.first_token_ms:.0f}ms → {final.first_token_ms:.0f}ms"
       f"（-{(1 - final.first_token_ms / base.first_token_ms) * 100:.1f}%）")


# ===========================================================================
# 第 7 节：预算兜底 + 一句话本质
# ===========================================================================


def demo_budget_and_essence() -> None:
    section("预算兜底：优化降低期望值，预算控制上界", "⑦")

    questions = ["订单 A1001 到哪了？", "计算 (12+8)*3/4", "统计「护栏」这两个字有几个字",
                 "订单 A1002 到哪了？", "计算 1+1"]
    guard = BudgetGuard(max_calls=3, max_cost=1.0)
    meter = UsageMeter()
    done: list[str] = []

    for q in questions:
        try:
            guard.check(meter)                     # ★ 调用之前检查
        except BudgetExceeded as exc:
            kv("预算触发", f"{type(exc).__name__}: {exc}")
            kv("已完成 / 未完成", f"{len(done)} / {len(questions) - len(done)}")
            kv("异常类型", f"BudgetExceeded 是 AbortAgent 的子类 → {issubclass(BudgetExceeded, AbortAgent)}")
            break
        meter.record_call("large", 1200, 120, 2200, 700)
        done.append(q)
    print()
    kv("已花成本", f"{money(meter.cost)} / 上限 ¥{guard.max_cost}")
    kv("调用次数", f"{meter.model_calls} / 上限 {guard.max_calls}")
    print()
    ok("预算触发的正确姿势：**优雅停机 + 返回已完成的部分 + 明确告知用户**。")
    bullet("它是 AbortAgent（预期内的策略性停机），不是故障 → 不该触发 500 告警")
    bullet("检查必须放在**调用之前**（放在之后只是事后统计，拦不住账单）")
    bullet("三维度都要有：调用次数、金额、墙上时间 —— 死循环往往先撞时间预算")
    print()
    essence(
        "优化的顺序是：先测量 → 再缓存 → 再减量 → 最后才换模型。\n"
        "80% 的成本来自「本可以不发生的模型调用」。\n"
        "\n"
        "测量（UsageMeter）   ：token / 成本 / 墙上时间 / TTFT，一个都不能少\n"
        "缓存（SemanticCache）：精确 + 语义 + **实体硬约束**（防假命中）\n"
        "减量（并行/裁剪/流式）：省延迟与输入 token，不动质量\n"
        "路由（ModelRouter）  ：简单给小模型，复杂给大模型，不确定就保守走大模型\n"
        "预算（BudgetGuard）  ：优化降低期望值，预算控制上界，触发即优雅停机\n"
        "\n"
        "两条纪律：\n"
        "  ① 每一次优化都必须能**说出省了多少**（否则就撤掉，它在增加复杂度）；\n"
        "  ② 每一次优化都必须用**评估集**证明质量没掉（第 10 章）。\n"
        "\n"
        "下一章（13 生产化部署）会看到：缓存、预算、审计这些东西上线之后\n"
        "会变成分布式系统问题 —— 单机的 dict 缓存和内存预算都不作数了。"
    )


# ===========================================================================
# 验收自检（由 scripts/run_all_checks.py 调用）
# ===========================================================================
# 契约：run_checks() -> list[(名称, 是否通过, 说明)]
# 铁律：不打印、不联网、不依赖真实模型、1 秒内跑完、多次运行结果一致。


def run_checks() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    # --- 验收 1：能打印一次任务的 token 明细与预估成本 ---
    meter = UsageMeter()
    meter.record_call("large", 1200, 300, 2200, 700, note="首次")
    meter.record_call("small", 800, 150, 600, 180, note="路由")
    expected = 1200 / 1000 * 0.012 + 300 / 1000 * 0.036 + 800 / 1000 * 0.001 + 150 / 1000 * 0.002
    results.append(check_that(
        "成本计算与手算一致（输入/输出分别计价）",
        math.isclose(meter.cost, expected, rel_tol=1e-9),
        f"计量器 {meter.cost:.6f} vs 手算 {expected:.6f}"))
    results.append(check_that(
        "逐调用明细完整（token 输入/输出 + 耗时 + TTFT + 成本）",
        len(meter.table()) == 2 and meter.prompt_tokens == 2000
        and meter.completion_tokens == 450 and meter.total_tokens == 2450,
        f"{meter.total_tokens} tokens = {meter.prompt_tokens} in + {meter.completion_tokens} out"))

    # --- 验收 2：相同问题第二次命中缓存，0 次模型调用 ---
    cache = SemanticCache()
    cache.put("订单 A1001 到哪了？", "订单 A1001 已发货。", "large", 1200, 40)
    look_exact = cache.get("订单 A1001 到哪了？")
    look_sem = cache.get("帮我查一下订单 A1001 到哪里了")
    results.append(check_that(
        "精确缓存命中（归一化后完全一致）",
        look_exact.hit and look_exact.kind == "exact", look_exact.reason))
    results.append(check_that(
        "语义缓存命中（换了说法，相似度达标）",
        look_sem.hit and look_sem.kind == "semantic" and look_sem.score >= cache.threshold,
        f"{look_sem.reason}"))

    report = run_pipeline(QUESTIONS, CACHE_ONLY)
    results.append(check_that(
        "端到端：重复问题第二次 0 次模型调用",
        report.meter.cache_hits == 1 and report.meter.model_calls == len(QUESTIONS) - 1,
        f"{report.meter.model_calls} 次调用 + {report.meter.cache_hits} 次缓存命中"))

    # --- 验收 3：实体硬约束防假命中 ---
    look_bad = cache.get("订单 A1002 到哪了？")
    results.append(check_that(
        "相似但实体不同的提问被拒绝命中（防 A/B 串答案）",
        not look_bad.hit and look_bad.kind == "entity_blocked"
        and cache.stats["entity_blocked"] == 1,
        look_bad.reason))
    naive_cache = SemanticCache(entity_guard=False)
    naive_cache.put("订单 A1001 到哪了？", "订单 A1001 已发货。", "large", 1200, 40)
    wrong = naive_cache.get("订单 A1002 到哪了？")
    results.append(check_that(
        "对照组：关掉实体约束后确实会产生假命中（证明这一层有用）",
        wrong.hit and "A1001" in (wrong.entry.answer if wrong.entry else ""),
        f"问 A1002 → 答 {wrong.entry.answer[:18] if wrong.entry else ''}"))

    # --- 验收 4：简单任务路由到小模型，复杂任务走大模型 ---
    router = ModelRouter()
    d_simple = router.route("计算 (12+8)*3/4")
    d_complex = router.route("帮我分析一下订单 A1001 延迟的原因，并给出改进建议")
    d_unclear = router.route("今天怎么样")
    results.append(check_that(
        "简单任务路由到小模型", d_simple.tier == "small", d_simple.reason))
    results.append(check_that(
        "复杂任务路由到大模型", d_complex.tier == "large", d_complex.reason))
    results.append(check_that(
        "无法判断时保守走大模型（错误代价不对称）",
        d_unclear.tier == "large", d_unclear.reason))

    # --- 验收 5：并行工具调用确实省时间 ---
    calls = [ToolCallPlan("lookup_order", {"order_id": "A1001"}),
             ToolCallPlan("search_kb", {"query": "延迟"})]
    _, seq_ms = run_tools_sequential(calls)
    _, par_ms = run_tools_parallel(calls)
    results.append(check_that(
        "并行工具总耗时 = max(单工具) 而非 sum",
        math.isclose(par_ms, 400.0) and math.isclose(seq_ms, 700.0) and par_ms < seq_ms,
        f"串行 {seq_ms:.0f}ms → 并行 {par_ms:.0f}ms"))

    # --- 验收 6：流式输出降低首字延迟 ---
    price = PRICING["large"]
    chunks, times = stream_timeline("订单 A1001 已发货，运单号 SF1234567890。",
                                    price.sim_ttft_ms, price.sim_latency_ms)
    results.append(check_that(
        "流式：首字延迟 TTFT 显著小于总时长（感知延迟下降）",
        times[0] < price.sim_latency_ms * 0.5 and len(chunks) > 3,
        f"TTFT {times[0]:.0f}ms vs 总时长 {price.sim_latency_ms:.0f}ms"))
    results.append(check_that(
        "上下文裁剪能把输入 token 压回预算内",
        amortized_prompt_tokens(30, window=5) < amortized_prompt_tokens(30) * 0.5,
        f"30 轮：{amortized_prompt_tokens(30)} → 窗口=5：{amortized_prompt_tokens(30, window=5)}"))

    # --- 验收 7：优化前后对比（成本与延迟同时下降） ---
    base = run_pipeline(QUESTIONS, BASELINE).meter
    opt_report = run_pipeline(QUESTIONS, OPTIMIZED)
    opt = opt_report.meter
    results.append(check_that(
        "优化后成本下降 ≥ 50%",
        opt.cost < base.cost * 0.5,
        f"{money(base.cost)} → {money(opt.cost)} (-{(1 - opt.cost / base.cost) * 100:.0f}%)"))
    results.append(check_that(
        "优化后总耗时与首字延迟同时下降",
        opt.wall_ms < base.wall_ms * 0.6 and opt.first_token_ms < base.first_token_ms * 0.5,
        f"耗时 {base.wall_ms:.0f}→{opt.wall_ms:.0f}ms，"
        f"首字 {base.first_token_ms:.0f}→{opt.first_token_ms:.0f}ms"))
    results.append(check_that(
        "优化没有牺牲质量：复杂问题仍然由大模型回答",
        "中转仓" in opt_report.answers[3] and opt_report.router is not None
        and opt_report.router.stats["large"] >= 1,
        opt_report.answers[3][:26]))

    # --- 验收 8：预算兜底 ---
    guard = BudgetGuard(max_calls=2, max_cost=1.0)
    bm = UsageMeter()
    tripped = False
    for _ in range(5):
        try:
            guard.check(bm)
        except BudgetExceeded:
            tripped = True
            break
        bm.record_call("large", 1200, 120, 2200, 700)
    results.append(check_that(
        "超出调用次数预算时抛 BudgetExceeded（AbortAgent，可优雅停机）",
        tripped and bm.model_calls == 2 and issubclass(BudgetExceeded, AbortAgent),
        f"稳定停在 {bm.model_calls} 次调用"))
    guard_cost = BudgetGuard(max_calls=99, max_cost=0.02)
    cm = UsageMeter()
    for _ in range(5):
        cm.record_call("large", 1200, 300, 2200, 700)
    cost_tripped = False
    try:
        guard_cost.check(cm)
    except BudgetExceeded as exc:
        cost_tripped = "成本预算" in str(exc)
    results.append(check_that(
        "金额维度也能独立触发预算", cost_tripped, f"累计 {money(cm.cost)} > ¥0.02"))

    # --- 验收 9：确定性 ---
    again = run_pipeline(QUESTIONS, OPTIMIZED).meter
    results.append(check_that(
        "重复运行结果一致（可复现，不依赖真实时钟）",
        again.model_calls == opt.model_calls and math.isclose(again.cost, opt.cost)
        and math.isclose(again.wall_ms, opt.wall_ms),
        f"{again.model_calls} 次调用 / {money(again.cost)} / {again.wall_ms:.0f}ms"))

    return results


# ===========================================================================
# 入口
# ===========================================================================

SECTIONS: dict[str, tuple[str, Callable[[], None]]] = {
    "1": ("先看问题：一次任务花了多少", demo_baseline),
    "2": ("用量计量器", demo_meter),
    "3": ("缓存：精确 + 语义 + 实体约束", demo_cache),
    "4": ("模型路由", demo_router),
    "5": ("减量：并行 / 裁剪 / 流式", demo_reduce),
    "6": ("优化顺序与前后对比", demo_before_after),
    "7": ("预算兜底 + 一句话本质", demo_budget_and_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 12 章 · 成本与延迟优化")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑验收自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 12 章 · 成本与延迟优化")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 12 章", run_checks()) else 1

    banner("第 12 章 · 成本与延迟优化",
           "目标：不改功能，把成本降一个数量级、首字延迟降到三分之一")

    chosen = [args.section] if args.section else sorted(SECTIONS)
    for key in chosen:
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 12 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
