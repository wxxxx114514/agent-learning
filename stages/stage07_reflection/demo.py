"""第 07 章 · 反思与自我修正 —— 反思 = 换个视角检查自己的输出，并产出**具体可执行**的修正。

运行：
    py -m stages.stage07_reflection.demo
    py -m stages.stage07_reflection.demo --list
    py -m stages.stage07_reflection.demo --section 2
    py -m stages.stage07_reflection.demo --check

本章目标：亲手搭一个 Reflexion 循环（生成 → 审查 → 修正 → 再验证），并看清三件事：
    ① **笼统的批评等于没有批评** —— 模型只有拿到"哪一行、错在哪、改成什么"才会真的改；
    ② **模型的自评不可信** —— 所以必须有一个**确定性的验证器（verifier）**当裁判；
    ③ **反思必须能停下来** —— 否则模型会陷入无限自我怀疑，烧掉你的账单。

全部离线可跑：这里用几个"确定性的假模型"精确复现真实模型的两条行为规律
（对具体反馈敏感、对笼统反馈免疫），这样你才能反复观察同一条因果链。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check_that, code, essence, kv, note, ok, report,
    section, setup_console, warn,
)
from core.llm import LLM, LLMResponse  # noqa: E402
from core.message import Message  # noqa: E402
from core.mock_llm import as_mock_response  # noqa: E402

# ===========================================================================
# 一、任务与"事实源"：反思要有一个可以对照的真相
# ===========================================================================
# 反思为什么常常沦为废话？
#   因为审查者手里**没有事实**，它只能凭"读起来顺不顺"评论。
#   所以第一件事不是写审查提示词，而是准备好"可被机器复核的事实源"。
#   本章的事实源极简：一张商品明细表 + 一条"合计 = 逐项之和"的算术规则。


@dataclass(frozen=True)
class SalesRecord:
    """一条销售记录。注意是 frozen：事实源不允许在反思过程中被改写。"""

    sku: str
    qty: int
    price: int

    @property
    def subtotal(self) -> int:
        return self.qty * self.price


@dataclass(frozen=True)
class ReportTask:
    """一个"写销售速报"的任务。"""

    key: str                      # 任务编号，用于经验库溯源
    kind: str                     # 任务类型，经验库按类型复用
    title: str
    records: tuple[SalesRecord, ...]

    # ---- 事实源 -------------------------------------------------------
    def correct_total(self) -> int:
        return sum(r.subtotal for r in self.records)

    def wrong_total(self) -> int:
        """假模型"心算"出来的错误合计。

        刻意让它**少算 10 元**（模拟真实模型最常见的错误：心算漏进位/漏一项）。
        两个同类任务犯的是**同一类错**，这样第 ⑥ 节才能演示"经验库让错误不再重演"。
        """
        return self.correct_total() - 10

    def table_text(self) -> str:
        return "\n".join(f"- {r.sku}：{r.qty} 件 × {r.price} 元" for r in self.records)

    def formula_text(self) -> str:
        return " + ".join(str(r.subtotal) for r in self.records)


TASK_Q1 = ReportTask("2025Q1", "销售速报", "2025 年 Q1 销售速报", (
    SalesRecord("A 商品", 17, 23),   # 391
    SalesRecord("B 商品", 8, 45),    # 360
    SalesRecord("C 商品", 5, 12),    # 60   → 合计 811
))

# 同类任务、不同数字。用于验证"教训能不能迁移到下一次"。
TASK_Q2 = ReportTask("2025Q2", "销售速报", "2025 年 Q2 销售速报", (
    SalesRecord("A 商品", 12, 31),   # 372
    SalesRecord("B 商品", 9, 28),    # 252
    SalesRecord("C 商品", 4, 15),    # 60   → 合计 684
))


def total_value(text: str) -> int | None:
    """从文本里抠出「合计：N 元」的数字（找不到返回 None）。"""
    m = re.search(r"合计[:：]\s*(\d+)\s*元", text)
    return int(m.group(1)) if m else None


def total_in(text: str) -> str:
    """把「合计：N 元」渲染成一行便于打印的字符串。"""
    value = total_value(text)
    return f"合计：{value} 元" if value is not None else "（未找到合计行）"


# ===========================================================================
# 二、确定性"假模型"：精确复现真实模型的反馈行为
# ===========================================================================
# 为什么不用真模型？
#   因为本章要讲的是**结构**（反馈 → 修正 的因果链），不是"某个模型有多聪明"。
#   用假模型，同一条因果链你可以跑一百遍，每次结论都一样。
#
# 但这个假模型必须"像真的"，否则演示没有说服力。它遵守三条真实规律：
#   规律 1：给**具体到字符**的修改意见，它会照做；给**笼统**的意见，它只会改措辞。
#   规律 2：它自己算数不可靠（合计会算错）—— 所以必须外挂验证器。
#   规律 3：系统提示词里写清楚的历史教训，它会遵守（不再犯同一个错）。

LESSON_HINT = "写出合计前必须逐项重算"

# 审查者输出的四种"人格"。用同一个类 + mode 参数，对比时只改一个变量。
VAGUE_REVIEW = (
    "整体结构清晰、逻辑通顺、语言表达自然，建议进一步打磨细节，"
    "确保数据准确、结论更有深度，表述更加凝练。"
)
CLEAN_REVIEW = "未发现事实性错误。"
NITPICKS = (
    "结论段落缺乏前瞻性，建议重写结论，补充下季度趋势判断。",
    "结论仍然不够具体，建议加入同比与环比的口径说明。",
    "结论的措辞可以更有说服力，建议再优化一次表达。",
)


class ReportWriterLLM(LLM):
    """扮演"写作 Agent"的假模型：负责产出速报正文。

    `_complete` 是唯一要实现的钩子：把 messages 变成一段文本。
    这里它真的去**读**提示词（而不是背剧本），因为"模型看没看到教训/反馈"
    正是本章要观察的自变量。
    """

    name = "report-writer"

    def __init__(self, task: ReportTask, model: str = "mock-writer") -> None:
        super().__init__(model)
        self.task = task
        self.drafts: list[str] = []      # 每次产出的原稿，便于断言"到底改没改"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        system = messages[0].content if messages and messages[0].role == "system" else ""
        user_msgs = [m.content for m in messages if m.role == "user"]
        # 第 1 条 user 是任务书，之后追加的才是"修正意见"
        feedback = user_msgs[-1] if len(user_msgs) > 1 else ""

        # --- 规律 3：读到教训就按教训做（开写前先把合计算对） ---
        remembers = LESSON_HINT in system and self.task.kind in system
        total = self.task.correct_total() if remembers else self.task.wrong_total()
        text = self._render(total)

        # --- 规律 1：只认"把 X 改成 Y"这种可执行的反馈 ---
        applied: list[str] = []
        for m in re.finditer(r"把\s*(\d+)\s*改成\s*(\d+)", feedback):
            old, new = m.group(1), m.group(2)
            if old in text:
                text = text.replace(old, new)
                applied.append(f"{old} → {new}")
        if feedback and not applied:
            # 收到了一堆"建议"却没有具体动作 → 只能改改标题措辞，事实分毫未动。
            # 这正是真实世界里"反思了个寂寞"的样子。
            text = text.replace("销售速报", "销售速报（修订稿）")

        self.drafts.append(text)
        return as_mock_response(text, self.model)

    def _render(self, total: int) -> str:
        lines = [f"{self.task.title}", "分项："]
        lines += [f"- {r.sku}：{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" for r in self.task.records]
        lines.append(f"合计：{total} 元")
        lines.append("结论：本季度销售整体稳健，建议优先补货 A 商品。")
        return "\n".join(lines)


class ReviewCriticLLM(LLM):
    """扮演"审查者/批评者"的假模型。

    mode 决定它是哪一种审查者 —— 这是本章最重要的对照组：
        "specific" 具体派：拿到**事实源**，逐行重算，指出"哪一行、错在哪、改成什么"
        "vague"    场面话派：只会说"建议进一步优化"，一个字都落不了地
        "lazy"     放水派：永远回"未发现事实性错误"（模型自评的典型偏差）
        "nitpick"  挑刺派：永远能找出新的、无法验证的毛病 → 演示"必须设轮数上限"
    """

    name = "review-critic"

    def __init__(self, task: ReportTask, mode: str = "specific", model: str = "mock-critic") -> None:
        super().__init__(model)
        self.task = task
        self.mode = mode
        self.calls: list[str] = []       # 每次被要求审查的草稿

    # -- 业务语义的薄封装：让主循环读起来像业务代码 ----------------------
    def review(self, draft: str, task: ReportTask | None = None) -> "Critique":
        task = task or self.task
        resp = self.complete([
            Message.system(
                f"你是审查者。事实源：\n{task.table_text()}\n"
                f"正确合计：{task.formula_text()} = {task.correct_total()}"
            ),
            Message.user(draft),
        ])
        return parse_critique(resp.text)

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        draft = next((m.content for m in reversed(messages) if m.role == "user"), "")
        self.calls.append(draft)

        if self.mode == "vague":
            text = VAGUE_REVIEW
        elif self.mode == "lazy":
            text = CLEAN_REVIEW
        elif self.mode == "nitpick":
            text = f"- {NITPICKS[self.total_calls % len(NITPICKS)]}"
        else:
            text = self._audit(draft)
        return as_mock_response(text, self.model)

    def _audit(self, draft: str) -> str:
        """具体派的核心能力：**它手里有事实源，所以能说出确定的话**。

        注意它指出问题的方式 —— 三要素缺一不可：
            位置（哪一行/哪个字段） + 事实（正确值是多少） + 动作（把 X 改成 Y）
        """
        want = self.task.correct_total()
        m = re.search(r"合计[:：]\s*(\d+)\s*元", draft)
        items: list[str] = []
        if m and int(m.group(1)) != want:
            got = int(m.group(1))
            items.append(
                f"合计行有误：{self.task.formula_text()} = {want}，你写成了 {got}；"
                f"请把 {got} 改成 {want}，其余内容不要改动。"
            )
        for r in self.task.records:
            line = f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
            if line not in draft:
                items.append(f"分项「{r.sku}」应写成 `{line}`；请把该行改成这个格式。")
        return "\n".join(f"- {i}" for i in items) if items else CLEAN_REVIEW


# ===========================================================================
# 三、验证器（verifier）：不靠"感觉"，只靠重算
# ===========================================================================
# 为什么模型的自评不可信？
#   因为"自评"和"生成"用的是同一个模型、同一套先验：
#   它错的地方，它同样看不出来（self-consistency bias）。
#   而验证其实是**另一个问题**：不是"写得好不好"，而是"对不对"。
#   只要"对不对"能被代码判定，就应该交给代码 —— 快、免费、100% 稳定。


@dataclass
class Verdict:
    """验证结论。issues 为空 = 通过。"""

    ok: bool
    issues: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)   # 做了哪些检查（可审计）


class ReportVerifier:
    """确定性验证器：重算每一个数字，校验格式契约。**一次模型调用都不需要。**"""

    name = "report-verifier"

    def check(self, text: str, task: ReportTask) -> Verdict:
        issues: list[str] = []
        checked: list[str] = []

        # ① 逐项重算：不信任文本里的任何数字，直接用事实源算
        for r in task.records:
            want = f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
            checked.append(f"分项 {r.sku}：数量 × 单价 = {r.subtotal}")
            if want not in text:
                issues.append(f"分项「{r.sku}」缺失或金额不等于 {r.subtotal} 元（应为 `{want}`）")

        # ② 合计必须等于逐项之和（模型最容易错、也最容易验的一步）
        total = task.correct_total()
        checked.append(f"合计 = {task.formula_text()} = {total}")
        m = re.search(r"合计[:：]\s*(\d+)\s*元", text)
        if not m:
            issues.append(f"缺少「合计：{total} 元」这一行")
        elif int(m.group(1)) != total:
            got = int(m.group(1))
            issues.append(f"合计错误：逐项重算应为 {total}，你写成了 {got}；请把 {got} 改成 {total}")

        # ③ 格式契约：交付物必须包含结论段（下游系统靠它做摘要）
        checked.append("必须包含「结论：」段落")
        if "结论：" not in text:
            issues.append("缺少「结论：」段落，交付格式不合规")

        return Verdict(ok=not issues, issues=issues, checked=checked)


# ===========================================================================
# 四、审查意见的结构化：把"一段话"变成"能执行的任务"
# ===========================================================================


@dataclass
class Critique:
    """一次审查的结构化结果。"""

    raw: str
    items: list[str] = field(default_factory=list)

    @property
    def actionable(self) -> list[str]:
        """可执行条目：带有具体数字/位置的条目（模型照着就能改）。"""
        return [i for i in self.items if re.search(r"\d", i)]

    @property
    def vague(self) -> list[str]:
        """笼统条目：没有数字、没有位置的"建议"。改不动任何东西。"""
        return [i for i in self.items if not re.search(r"\d", i)]

    @property
    def blocking(self) -> bool:
        """审查者是否认为"还不能交付"。"""
        return bool(self.items)


def parse_critique(text: str) -> Critique:
    """把审查者的文本解析成条目列表。

    真实系统里这一步同样重要：**不可解析的反馈无法驱动修正**。
    所以提示词要规定审查者逐条输出（本章用 `- ` 开头一行一条）。
    """
    raw = (text or "").strip()
    if not raw or "未发现" in raw:
        return Critique(raw=raw, items=[])
    items = [ln.strip("-• \t") for ln in raw.splitlines() if ln.strip().startswith(("-", "•"))]
    if not items:                      # 没按规定格式输出 → 整段当成一条
        items = [raw]
    return Critique(raw=raw, items=items)


# ===========================================================================
# 五、失败经验库：让同一个坑只踩一次
# ===========================================================================


@dataclass(frozen=True)
class Lesson:
    """一条教训。注意它是**结构化**的：类型 / 错在哪 / 怎么避免 / 来自哪个任务。"""

    kind: str
    mistake: str
    fix: str
    source: str

    def render(self) -> str:
        return f"- 在「{self.source}」上犯过：{self.mistake}\n  教训：{self.fix}"


class LessonMemory:
    """跨任务的失败经验库（现实中会落库/落向量库，这里先用内存列表）。"""

    def __init__(self) -> None:
        self.items: list[Lesson] = []

    def add(self, lesson: Lesson) -> None:
        if lesson not in self.items:      # 去重：同一个坑记一次就够
            self.items.append(lesson)

    def as_prompt(self, kind: str) -> str:
        """只注入**同类任务**的教训。

        为什么不把所有教训都塞进去？
            无关教训是噪声，会挤占上下文并干扰当前任务（第 05 章的教训）。
        """
        same = [x for x in self.items if x.kind == kind]
        if not same:
            return ""
        return "历史教训（同类任务曾经失败过，开工前务必避免）：\n" + "\n".join(x.render() for x in same)

    def __len__(self) -> int:
        return len(self.items)


# ===========================================================================
# 六、Reflexion 主循环
# ===========================================================================

SYSTEM_TEMPLATE = """你是一名数据分析助理，负责撰写销售速报。

# 任务
根据给定的商品明细产出速报，格式必须严格如下：
{title}
分项：
- <商品>：<数量> 件 × <单价> 元 = <小计> 元
合计：<逐项之和> 元
结论：<一句话结论>

# 事实源（只读，不得修改）
{table}

{lessons}"""

REQUEST_TEMPLATE = "请写出「{title}」。只输出报告正文，不要解释。"


def build_feedback(critique: Critique, verdict: Verdict, use_verifier_feedback: bool = True) -> str:
    """把"审查意见 + 验证结论"合成下一轮给模型的反馈。

    两个工程决定：
      1. **验证器的结论排在最前面** —— 它是事实，优先级高于主观意见；
      2. 只保留**可执行**条目 —— 笼统建议对模型是噪声，写进去只会稀释真正的修改点。
    """
    lines: list[str] = []
    if use_verifier_feedback:
        lines += [f"- [验证器] {i}" for i in verdict.issues]
    lines += [f"- [审查者] {i}" for i in critique.actionable]
    if not lines:
        return ""
    return "【修正意见】请逐条落实（只改被指出的地方，不要重写全文）：\n" + "\n".join(lines)


@dataclass
class Round:
    """一轮反思的完整记录 —— 生产环境里这就是你要打点到日志里的东西。"""

    index: int
    draft: str
    critique: Critique
    verdict: Verdict
    feedback: str


@dataclass
class ReflexionResult:
    """一次 Reflexion 运行的最终结果。"""

    task_key: str
    final: str
    rounds: list[Round]
    stop_reason: str            # verified_pass / max_rounds / no_progress / no_reflection
    llm_calls: int = 0

    @property
    def reflections(self) -> int:
        """真正发生的"反思轮数" = 总轮数 - 1（第一轮是初次生成）。"""
        return max(len(self.rounds) - 1, 0)

    @property
    def verified(self) -> bool:
        return bool(self.rounds) and self.rounds[-1].verdict.ok

    @property
    def unresolved(self) -> list[str]:
        """停机时仍未解决的问题（交付时必须如实告诉用户）。"""
        if not self.rounds:
            return []
        last = self.rounds[-1]
        return list(last.verdict.issues) + list(last.critique.items)


class ReflexionAgent:
    """生成 → 审查 → 修正 → 再验证 的循环。

    三个**必须存在**的刹车（缺一个都会出事）：
        max_rounds            轮数上限，防止无限自我怀疑；
        no_progress           事实错误原封不动 → 反馈没被采纳，再跑也是白跑；
        verifier              唯一的裁判，防止"模型说通过了"就真的交付。
    """

    def __init__(
        self,
        llm: LLM,
        critic: ReviewCriticLLM,
        verifier: ReportVerifier,
        max_rounds: int = 3,
        memory: LessonMemory | None = None,
        use_verifier_feedback: bool = True,
    ) -> None:
        self.llm = llm
        self.critic = critic
        self.verifier = verifier
        self.max_rounds = max_rounds
        self.memory = memory
        self.use_verifier_feedback = use_verifier_feedback

    # ------------------------------------------------------------------
    def run(self, task: ReportTask) -> ReflexionResult:
        lessons = self.memory.as_prompt(task.kind) if self.memory else ""
        messages: list[Message] = [
            Message.system(SYSTEM_TEMPLATE.format(
                title=task.title, table=task.table_text(),
                lessons=lessons or "（暂无历史教训）",
            )),
            Message.user(REQUEST_TEMPLATE.format(title=task.title)),
        ]

        rounds: list[Round] = []
        feedback = ""
        last_issue_key: tuple[str, ...] = ()
        stop_reason = "max_rounds"

        for i in range(1, self.max_rounds + 1):
            if feedback:
                messages.append(Message.user(feedback))

            # ① 生成（第一轮）/ 修正（后续轮）—— 对模型来说都是"接着写一段"
            draft = self.llm.complete(messages).text
            messages.append(Message.assistant(draft))

            # ② 两条独立的检查线：一条靠事实（verifier），一条靠语言（critic）
            verdict = self.verifier.check(draft, task)
            critique = self.critic.review(draft, task)

            key = tuple(verdict.issues)
            rounds.append(Round(index=i, draft=draft, critique=critique, verdict=verdict, feedback=feedback))

            # ③ 停机判定 1：事实无误 **且** 审查者不再提意见 → 收工
            if verdict.ok and not critique.blocking:
                stop_reason = "verified_pass"
                break

            # ④ 停机判定 2：事实错误一字未改 → 反馈没被采纳，继续跑纯属浪费
            if key and key == last_issue_key:
                stop_reason = "no_progress"
                break

            last_issue_key = key
            feedback = build_feedback(critique, verdict, self.use_verifier_feedback)

        result = ReflexionResult(
            task_key=task.key, final=rounds[-1].draft if rounds else "",
            rounds=rounds, stop_reason=stop_reason, llm_calls=self.llm.total_calls,
        )

        # ⑤ 收尾：只要**初次生成**是错的，就把这次的失败沉淀成教训。
        #    注意判据是"第一轮错了"，而不是"最终没通过" —— 反思把错误改对了，
        #    不代表这个坑不存在；教训要能被下一次同类任务读到。
        if self.memory is not None and rounds and not rounds[0].verdict.ok:
            first = rounds[0].verdict.issues
            self.memory.add(Lesson(
                kind=task.kind,
                mistake=first[0] if first else "未通过验证",
                fix=LESSON_HINT,
                source=f"{task.key} {task.title}",
            ))
        return result


def first_draft(task: ReportTask) -> str:
    """单独拿到"第一次生成"的原稿，用于展示审查者的意见长什么样。"""
    writer = ReportWriterLLM(task)
    return writer.complete([
        Message.system(SYSTEM_TEMPLATE.format(
            title=task.title, table=task.table_text(), lessons="（暂无历史教训）")),
        Message.user(REQUEST_TEMPLATE.format(title=task.title)),
    ]).text


def make_agent(task: ReportTask, mode: str = "specific", max_rounds: int = 3,
               memory: LessonMemory | None = None,
               use_verifier_feedback: bool = True) -> ReflexionAgent:
    """一行组装一个 Reflexion Agent，让各小节的差异一眼可见。"""
    return ReflexionAgent(
        llm=ReportWriterLLM(task),
        critic=ReviewCriticLLM(task, mode=mode),
        verifier=ReportVerifier(),
        max_rounds=max_rounds,
        memory=memory,
        use_verifier_feedback=use_verifier_feedback,
    )


# ===========================================================================
# 第 ① 节：没有反思的世界
# ===========================================================================


def demo_naive() -> ReflexionResult:
    section("一次生成，直接交付：错在哪都不知道", "①")

    draft = first_draft(TASK_Q1)
    code(draft, indent=4)
    print()

    verdict = ReportVerifier().check(draft, TASK_Q1)
    got = total_value(draft)
    kv("模型自己的说法", "报告已生成（它并不知道自己算错了）")
    kv("文本里的合计", total_in(draft))
    kv("验证器逐项重算", f"{TASK_Q1.formula_text()} = {TASK_Q1.correct_total()} 元")
    kv("差了多少", f"{TASK_Q1.correct_total() - got} 元" if got is not None else "?")
    kv("验证器结论", "不通过" if not verdict.ok else "通过")
    print()
    warn("模型不会主动说「我算错了」—— 它连自己错了都不知道。")
    note("反思要解决的第一个问题：**先要有能力发现错误**（而这需要一个事实源）。")
    return ReflexionResult(TASK_Q1.key, draft, [], "no_reflection")


# ===========================================================================
# 第 ② 节：笼统的批评 vs 具体的修正（本章最重要的一组对照）
# ===========================================================================


def _run_critic_scenario(mode: str, title: str) -> ReflexionResult:
    """固定其它所有变量，只改"审查者的人格"，看结果差多少。"""
    agent = make_agent(TASK_Q1, mode=mode, max_rounds=3, use_verifier_feedback=False)
    result = agent.run(TASK_Q1)
    kv(f"{title} · 轮数", len(result.rounds))
    kv(f"{title} · 停机原因", result.stop_reason)
    kv(f"{title} · 最终合计", total_in(result.final))
    kv(f"{title} · 验证通过", "是" if result.verified else "否")
    return result


def demo_critique_quality() -> tuple[ReflexionResult, ReflexionResult]:
    section("笼统的批评 vs 具体的修正：一个改不动，一个一次改对", "②")

    note("对照实验：同一个任务、同一个写作模型，**只换审查者的说话方式**。")
    print()

    note("A 组 · 笼统派审查者的原话：")
    code(VAGUE_REVIEW, indent=4)
    print()
    a = _run_critic_scenario("vague", "笼统派")
    print()

    note("B 组 · 具体派审查者的原话：")
    code(ReviewCriticLLM(TASK_Q1, mode="specific").review(first_draft(TASK_Q1), TASK_Q1).raw, indent=4)
    print()
    b = _run_critic_scenario("specific", "具体派")
    print()

    ok("具体派一轮就把 801 改成了 811；笼统派改了两轮，数字一动没动。")
    bullet("可执行的批评 = 位置（哪一行）+ 事实（正确值）+ 动作（把 X 改成 Y）")
    bullet("不可执行的批评 = 形容词的堆积，模型只能改措辞")
    warn("所以「让它自己再检查一遍」几乎从来不是有效的修复手段 —— 你要给的是检查的**依据**。")
    return a, b


# ===========================================================================
# 第 ③ 节：完整的 Reflexion 循环
# ===========================================================================


def demo_reflexion_loop() -> ReflexionResult:
    section("Reflexion 循环：生成 → 审查 → 修正 → 再验证", "③")
    note("这一次把**验证器反馈**打开（工程上的推荐做法：事实优先于意见）。")
    print()

    result = make_agent(TASK_Q1, mode="specific", max_rounds=3).run(TASK_Q1)

    for rd in result.rounds:
        head = rd.critique.raw.splitlines()[0][:56] if rd.critique.raw else "（无）"
        print(f"  ┌─ 第 {rd.index} 轮 " + "─" * 44)
        if rd.feedback:
            # 这一轮的草稿，就是模型读完这段反馈之后改出来的
            print("  │ 收到的反馈：")
            for line in rd.feedback.splitlines()[1:]:
                print(f"  │   {line[:62]}")
        print(f"  │ 产出      : {total_in(rd.draft)}")
        print(f"  │ 审查意见  : {head}")
        print(f"  │ 验证结论  : {'通过' if rd.verdict.ok else '不通过 · ' + rd.verdict.issues[0][:46]}")
        print("  └" + "─" * 48)

    print()
    kv("总轮数", len(result.rounds))
    kv("反思轮数（除初次生成）", result.reflections)
    kv("停机原因", result.stop_reason)
    kv("模型调用次数", result.llm_calls)
    kv("最终验证", "通过" if result.verified else "未通过")
    print()
    ok("循环收敛：第 2 轮就通过验证 —— 反思**不是越多越好**，够用就停。")
    return result


# ===========================================================================
# 第 ④ 节：验证器 —— 为什么模型的自评不能当裁判
# ===========================================================================


def demo_verifier() -> None:
    section("验证器：模型说「没问题」的时候，谁来拍板？", "④")

    draft = first_draft(TASK_Q1)
    kv("被测草稿的合计", total_in(draft))
    print()
    kv("放水派审查者",
       ReviewCriticLLM(TASK_Q1, mode="lazy").review(draft, TASK_Q1).raw)
    kv("具体派审查者",
       ReviewCriticLLM(TASK_Q1, mode="specific").review(draft, TASK_Q1).items[0][:52])
    verdict = ReportVerifier().check(draft, TASK_Q1)
    kv("验证器（重算）", "不通过 · " + verdict.issues[0][:48])
    print()
    note("验证器做了哪些确定性检查（可审计、可回归、可写进测试）：")
    for c in verdict.checked:
        bullet(c, indent=4)
    print()
    ok(f"验证器 0 次模型调用，结论 100% 可复现：合计必须是 {TASK_Q1.correct_total()} 元。")
    warn("凡是「对错能被代码判定」的东西（算术、格式、schema、单元测试、SQL 结果），都交给代码判。")
    note("剩下的才是模型的活：翻译、措辞、风格、语义一致性 —— 这些没有唯一答案。")
    print()

    # 反例：验证器说 No、审查者说「很好」—— 只听自评的后果
    r = make_agent(TASK_Q1, mode="lazy", max_rounds=3, use_verifier_feedback=False).run(TASK_Q1)
    kv("只听自评的循环 · 停机原因", r.stop_reason)
    kv("只听自评的循环 · 最终验证", "通过" if r.verified else "未通过（交付了错误内容）")
    warn("没有验证器，模型会带着错误「自我感觉良好」地停下 —— 这是最危险的静默失败。")


# ===========================================================================
# 第 ⑤ 节：什么时候停止反思
# ===========================================================================


def demo_stop_conditions() -> ReflexionResult:
    section("什么时候停止反思：轮数上限是必需品，不是可选项", "⑤")
    note("换上一个「永远能挑出新毛病」的审查者，看会发生什么。")
    print()

    agent = make_agent(TASK_Q1, mode="nitpick", max_rounds=3)
    r = agent.run(TASK_Q1)

    for rd in r.rounds:
        item = rd.critique.items[0][:38] if rd.critique.items else "（无）"
        print(f"  · 第 {rd.index} 轮：验证{'通过' if rd.verdict.ok else '不通过'}"
              f" / 审查意见：{item}")
    print()
    kv("轮数", f"{len(r.rounds)}（上限 {agent.max_rounds}）")
    kv("停机原因", r.stop_reason)
    kv("事实层", "已通过验证" if r.verified else "未通过")
    kv("未解决的审查意见", f"{len(r.unresolved)} 条")
    print()
    ok("max_rounds 生效：事实早就对了，审查者却永远不满意 —— 第 3 轮强制停机。")
    warn("没有上限，这个循环会一直改下去：每轮都是真金白银，而且永远没有「完成」的时刻。")
    note("工程做法：停机时**如实交付 + 标注未闭环**（把 unresolved 一起给用户），绝不假装完美。")
    return r


# ===========================================================================
# 第 ⑥ 节：失败经验库
# ===========================================================================


def demo_lesson_memory() -> tuple[ReflexionResult, ReflexionResult]:
    section("失败经验库：同一个坑，第二次不要再踩", "⑥")

    memory = LessonMemory()

    # --- 第一次：没有经验库，犯错后把教训写下来 ---
    first = make_agent(TASK_Q2, mode="specific", max_rounds=3, memory=memory).run(TASK_Q2)
    kv("第一遍 · 任务", f"{TASK_Q2.key} {TASK_Q2.title}")
    kv("第一遍 · 首轮合计", total_in(first.rounds[0].draft))
    kv("第一遍 · 轮数", len(first.rounds))
    kv("第一遍 · 最终验证", "通过" if first.verified else "未通过")
    kv("第一遍 · 经验库条数", len(memory))
    print()
    note("自动写进经验库的教训（结构化存储，下次可直接注入提示词）：")
    for lesson in memory.items:
        code(lesson.render(), indent=4)
    print()

    # --- 第二次：同类任务，带着教训开工（模型实例是全新的） ---
    second = make_agent(TASK_Q2, mode="specific", max_rounds=3, memory=memory).run(TASK_Q2)
    kv("第二遍 · 同类任务 + 经验库", TASK_Q2.key)
    kv("第二遍 · 首轮合计", total_in(second.rounds[0].draft))
    kv("第二遍 · 轮数", len(second.rounds))
    kv("第二遍 · 反思轮数", second.reflections)
    kv("第二遍 · 最终验证", "通过" if second.verified else "未通过")
    kv("第二遍 · 模型调用次数", second.llm_calls)
    print()

    # --- 对照组：不带经验库再跑一次，证明"变好"确实来自经验库 ---
    control = make_agent(TASK_Q2, mode="specific", max_rounds=3).run(TASK_Q2)
    kv("对照组 · 无经验库 · 首轮合计", total_in(control.rounds[0].draft))
    kv("对照组 · 无经验库 · 反思轮数", control.reflections)
    print()

    ok("带着教训开工：第 1 轮就写出正确合计，反思轮数 = 0（省下 1 次模型调用）。")
    note("这才是反思真正的价值：**不是把这一次改对，而是让下一次不再错**。")
    return first, second


# ===========================================================================
# 第 ⑦ 节：一句话本质
# ===========================================================================


def demo_essence() -> None:
    section("收口：一句话本质", "⑦")
    essence(
        "反思 = 换个视角检查自己的输出\n"
        "      → 产出**具体可执行**的修正\n"
        "      （位置 + 事实 + 动作，缺一不可）\n"
        "\n"
        "三个必需件：\n"
        "  · 验证器（verifier）：能代码判定的对错，绝不交给模型\n"
        "  · 轮数上限（max_rounds）：反思是成本，不是越多越好\n"
        "  · 经验库（lessons）  ：把「这一次的错」变成「下一次的对」\n"
        "\n"
        "没有具体修正的反思只是废话；没有验证器的反思只是自我安慰。"
    )


# ===========================================================================
# 验收标准
# ===========================================================================


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（由 scripts/run_all_checks.py 调用）。

    契约：不打印任何东西、确定性、< 1 秒、不联网、不需要 API Key。
    """
    results: list[tuple[str, bool, str]] = []

    # ---------- 验收 1：第一次输出有错时，反思能定位并修正 ----------
    r = make_agent(TASK_Q1, mode="specific", max_rounds=3).run(TASK_Q1)
    first_verdict = r.rounds[0].verdict
    results.append(check_that(
        "初次生成的错误能被定位（合计 801 ≠ 811）",
        bool(first_verdict.issues) and "811" in first_verdict.issues[0] and "801" in first_verdict.issues[0],
        first_verdict.issues[0][:56] if first_verdict.issues else "未发现问题"))
    results.append(check_that(
        "反思后修正：最终合计 = 811",
        r.verified and f"合计：{TASK_Q1.correct_total()} 元" in r.final,
        total_in(r.final)))
    results.append(check_that(
        "修正后逐项分项未被破坏（只改该改的地方）",
        all(f"= {x.subtotal} 元" in r.final for x in TASK_Q1.records),
        "三个分项金额均正确"))
    results.append(check_that(
        "收敛停机：stop_reason == verified_pass",
        r.stop_reason == "verified_pass", f"实际 {r.stop_reason}（{len(r.rounds)} 轮）"))

    # ---------- 验收 2：具体修正 vs 笼统批评 ----------
    vague = make_agent(TASK_Q1, mode="vague", max_rounds=3, use_verifier_feedback=False).run(TASK_Q1)
    results.append(check_that(
        "笼统批评改不动事实（合计仍为 801）",
        "合计：801 元" in vague.final and not vague.verified,
        total_in(vague.final)))
    results.append(check_that(
        "笼统批评被识别为「不可执行」（无具体数字）",
        bool(vague.rounds[0].critique.vague) and not vague.rounds[0].critique.actionable,
        f"可执行 {len(vague.rounds[0].critique.actionable)} 条 / 笼统 {len(vague.rounds[0].critique.vague)} 条"))
    specific_c = ReviewCriticLLM(TASK_Q1, mode="specific").review(first_draft(TASK_Q1), TASK_Q1)
    results.append(check_that(
        "具体修正三要素齐全（位置 + 正确值 + 改法）",
        bool(specific_c.actionable) and "把 801 改成 811" in specific_c.raw,
        specific_c.items[0][:56]))

    # ---------- 验收 3：反思有最大轮数限制 ----------
    nit = make_agent(TASK_Q1, mode="nitpick", max_rounds=2).run(TASK_Q1)
    results.append(check_that(
        "挑剔的审查者不会导致无限反思（轮数 = max_rounds）",
        len(nit.rounds) == 2 and nit.stop_reason == "max_rounds",
        f"{len(nit.rounds)} 轮 / {nit.stop_reason}"))
    results.append(check_that(
        "上限停机时如实标注未解决的问题",
        len(nit.unresolved) > 0, f"{len(nit.unresolved)} 条未闭环"))

    # ---------- 验收 4：验证器独立于模型 ----------
    draft = first_draft(TASK_Q1)
    verdict = ReportVerifier().check(draft, TASK_Q1)
    lazy_critique = ReviewCriticLLM(TASK_Q1, mode="lazy").review(draft, TASK_Q1)
    results.append(check_that(
        "模型自评会放水，验证器不会（自评通过 / 验证不通过）",
        (not lazy_critique.blocking) and (not verdict.ok),
        "自评：未发现事实性错误；验证器：合计 801 ≠ 811"))
    results.append(check_that(
        "验证器给出可审计的检查清单（重算过程可见）",
        len(verdict.checked) >= 3, f"{len(verdict.checked)} 项检查：{verdict.checked[0][:28]}"))

    # ---------- 验收 5：无进展早停 ----------
    lazy_loop = make_agent(TASK_Q1, mode="lazy", max_rounds=3, use_verifier_feedback=False).run(TASK_Q1)
    results.append(check_that(
        "反馈无法执行时提前停机（no_progress，不烧满轮数）",
        lazy_loop.stop_reason == "no_progress" and len(lazy_loop.rounds) < 3,
        f"{len(lazy_loop.rounds)} 轮 / {lazy_loop.stop_reason}"))

    # ---------- 验收 6：失败教训被记录，同类任务第二次不再犯 ----------
    memory = LessonMemory()
    first_run = make_agent(TASK_Q2, mode="specific", max_rounds=3, memory=memory).run(TASK_Q2)
    lessons_text = memory.items[0].fix if memory.items else "（空）"
    results.append(check_that(
        "失败后教训被写入经验库",
        len(memory) == 1 and memory.items[0].kind == TASK_Q2.kind and LESSON_HINT in memory.items[0].fix,
        f"{len(memory)} 条：{lessons_text}"))
    results.append(check_that(
        "对照组（不带经验库）仍会犯同样的错",
        (not first_run.rounds[0].verdict.ok) and first_run.reflections >= 1,
        f"首轮 {total_in(first_run.rounds[0].draft)}，用了 {first_run.reflections} 轮反思"))
    second_run = make_agent(TASK_Q2, mode="specific", max_rounds=3, memory=memory).run(TASK_Q2)
    results.append(check_that(
        "同类任务第二次不再犯：首轮即通过，反思 0 轮",
        second_run.verified and second_run.reflections == 0 and second_run.llm_calls == 1,
        f"首轮 {total_in(second_run.rounds[0].draft)} / 调用 {second_run.llm_calls} 次"))
    results.append(check_that(
        "教训按任务类型隔离（无关任务读不到）",
        memory.as_prompt("周报") == "" and memory.as_prompt(TASK_Q2.kind) != "",
        "周报任务不会读到销售速报的教训"))

    # ---------- 验收 7：确定性与可复现 ----------
    a = make_agent(TASK_Q1, mode="specific", max_rounds=3).run(TASK_Q1)
    b = make_agent(TASK_Q1, mode="specific", max_rounds=3).run(TASK_Q1)
    results.append(check_that(
        "同一输入两次运行结果完全一致（可复现）",
        a.final == b.final and len(a.rounds) == len(b.rounds) and a.stop_reason == b.stop_reason,
        f"{len(a.rounds)} 轮 / {a.stop_reason}"))

    return results


# ===========================================================================
# 入口
# ===========================================================================

SECTIONS = {
    "1": ("没有反思的世界", demo_naive),
    "2": ("笼统批评 vs 具体修正", demo_critique_quality),
    "3": ("Reflexion 循环", demo_reflexion_loop),
    "4": ("验证器：谁说了算", demo_verifier),
    "5": ("什么时候停止反思", demo_stop_conditions),
    "6": ("失败经验库", demo_lesson_memory),
    "7": ("一句话本质", demo_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 07 章 · 反思与自我修正")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 07 章 · 反思与自我修正")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 07 章", run_checks()) else 1

    banner("第 07 章 · 反思与自我修正",
           "目标：亲手搭一个 Reflexion 循环，弄清「什么样的反思才有用」")

    chosen = [args.section] if args.section else sorted(SECTIONS)
    for key in chosen:
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 07 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
