"""第 09 章 · 工作流与状态机 —— 能用确定性代码解决的，绝不用模型。

运行：
    py -m stages.stage09_workflow.demo
    py -m stages.stage09_workflow.demo --list
    py -m stages.stage09_workflow.demo --section 4
    py -m stages.stage09_workflow.demo --check

本章目标：从零手写一个状态机引擎（节点 + 边 + 条件路由），并用它驾驭一个真实的客服流程。
四个必须亲眼看到的东西：
    ① **流程骨架必须是显式的**：谁在什么时候走哪条分支，写死在图里，而不是让模型"自由发挥"；
    ② **模型只在需要判断的节点出现**：分类（兜底）、写话术 —— 其余全是纯函数；
    ③ **检查点（checkpoint）**：运行状态可以序列化成 JSON，进程挂了能从中断处继续；
    ④ **人工介入（human-in-the-loop）**：需要人拍板的节点会挂起，拿到答复后接着跑。

全部离线可跑：人工答复由**确定性剧本**提供（绝不调用 input()），
所以"挂起 → 落盘 → 恢复"这条链路你能反复验证，每次结果都一样。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

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
# 一、业务背景：三类客服工单
# ===========================================================================
# 为什么工作流这一章要用"客服工单"？
#   因为它天生就是**流程**：分类 → 路由 → 处理 → 写话术 → 合规检查 → 交付。
#   其中只有"分类"和"写话术"需要判断，其余步骤的答案早就在表里了。

State = dict[str, Any]

TICKET_REFUND = {
    "ticket_id": "T-9001", "order_id": "A1002",
    "text": "我要退款，订单 A1002 我不想要了",
}
TICKET_LOGISTICS = {
    "ticket_id": "T-9002", "order_id": "A1001",
    "text": "我的订单 A1001 快递到哪了？",
}
TICKET_CONSULT = {
    "ticket_id": "T-9003", "order_id": "",
    "text": "请问运费券怎么用？",
}
# 这条故意写得"没有关键词"：规则认不出来，才轮到模型出手（第 ③ 节的对照组）
TICKET_AMBIGUOUS = {
    "ticket_id": "T-9004", "order_id": "",
    "text": "这个券我不太懂，能解释下吗",
}
TICKET_EMPTY = {"ticket_id": "T-9005", "order_id": "", "text": "   "}

# 订单库（现实中是内部 API）
ORDERS: dict[str, dict[str, str]] = {
    "A1001": {"status": "已发货", "carrier": "顺丰", "eta": "2025-01-05"},
    "A1002": {"status": "待付款", "carrier": "", "eta": ""},
}

# 咨询类标准答案（FAQ）。有标准答案的问题，**永远不要问模型**。
FAQ: dict[str, str] = {
    "运费券": "运费券可用于抵扣下一次下单的运费，有效期 90 天，单笔订单限用一张。",
    "发票": "发票在订单完成后 24 小时内自动开具，可在「我的-发票」中下载。",
}

# 合规红线：出现这些词，草稿一律不许发给客户（由合规部门定义，不是模型说了算）
FORBIDDEN_WORDS = ("绝对保证", "100%", "内部备注", "私下")
APPROVED_AMOUNTS = {"20"}          # 唯一获批的赔付口径：20 元运费券


# ===========================================================================
# 二、图的基本零件：节点、边、条件边
# ===========================================================================
# 一个"状态机"只有三样东西：
#     节点（做什么） + 边（下一步去哪） + 状态（记住什么）
# 框架（LangGraph / Dify / Coze）多出来的部分，全是围绕这三样的工程包装：
#     检查点、并发、人工介入、可视化、重试……

START = "__start__"
END = "__end__"


class GraphError(Exception):
    """图本身有问题（连不通、指向不存在的节点）。**在构建期就该炸，而不是运行到一半才炸。**"""


class Interrupt(Exception):
    """节点主动"挂起"：我需要人拍板，先把现场存下来，等人回复再继续。

    注意它不是错误 —— 它是 human-in-the-loop 的**正常控制流**。
    """

    def __init__(self, question: str, resume_at: str = "") -> None:
        super().__init__(question)
        self.question = question
        self.resume_at = resume_at          # 拿到人工答复后，从哪个节点继续


@dataclass
class Node:
    """一个节点 = 一个纯函数（外加它的元信息）。"""

    name: str
    fn: Callable[[State, "NodeContext"], dict | None]
    kind: str = "deterministic"             # deterministic / llm / human
    title: str = ""


@dataclass
class Edge:
    """无条件边：执行完 src 就去 dst。"""

    src: str
    dst: str


@dataclass
class ConditionalEdge:
    """条件边：由 router(state) 返回一个 key，再查表决定去哪。

    为什么路由器是**纯函数**而不是模型调用？
        因为"下一步去哪"是**流程控制**，必须可预测、可测试、可审计。
        把路由交给模型，等于把系统的控制流交给概率。
    """

    src: str
    router: Callable[[State], str]
    targets: dict[str, str]
    label: str = ""


# ===========================================================================
# 三、运行期上下文：状态里只放 JSON，资源走 ctx
# ===========================================================================


class HumanChannel:
    """人工通道：真实系统里这是"发消息给人 + 等回调"。

    教学里我们用**确定性剧本**代替 input()：
        replies 里还有答复 → 直接返回（相当于"值班人在线"）
        replies 空了       → 抛 Interrupt（相当于"没人在线，先挂起"）
    这样"挂起 → 落盘 → 恢复"这条链路才能被自动化测试反复验证。
    """

    def __init__(self, replies: list[dict[str, Any]] | None = None, name: str = "审批员-张工") -> None:
        self.replies = list(replies or [])
        self.name = name
        self.asked: list[str] = []

    def try_ask(self, question: str) -> dict[str, Any] | None:
        self.asked.append(question)
        return self.replies.pop(0) if self.replies else None


@dataclass
class NodeContext:
    """节点运行时的"外部世界"：模型客户端、人工通道、计数器。

    ★ 关键设计：**这些东西绝不放进 state**。
      因为 state 要能被 json.dumps 落盘；而模型客户端、回调函数序列化不了。
      这是"检查点能不能真正落地"的分水岭 —— 新手最常在这里翻车。

    `models` 是"按角色选模型"的最小实现：分类用便宜的小模型，写话术用大模型。
    真实项目里这就是模型路由（第 12 章）。
    """

    llm: LLM
    human: HumanChannel
    models: dict[str, LLM] = field(default_factory=dict)
    llm_calls: int = 0

    def ask_llm(self, messages: list[Message], role: str = "") -> str:
        """节点里唯一允许调模型的方式（顺便记账，方便观察成本）。"""
        self.llm_calls += 1
        client = self.models.get(role, self.llm)
        return client.complete(messages).text


# ===========================================================================
# 四、状态机引擎
# ===========================================================================


@dataclass
class Checkpoint:
    """运行现场快照。**必须是纯 JSON**：能落盘、能进 Redis、能被另一个进程接手。"""

    graph: str
    node: str                       # 接下来要从哪个节点继续
    state: State
    visits: dict[str, int]
    history: list[str]
    llm_calls: int

    def to_json(self, indent: int | None = None) -> str:
        return json.dumps(
            {"graph": self.graph, "node": self.node, "state": self.state,
             "visits": self.visits, "history": self.history, "llm_calls": self.llm_calls},
            ensure_ascii=False, indent=indent, sort_keys=False,
        )

    @classmethod
    def from_json(cls, text: str) -> "Checkpoint":
        d = json.loads(text)
        return cls(graph=d["graph"], node=d["node"], state=d["state"],
                   visits=d["visits"], history=d["history"], llm_calls=d["llm_calls"])


@dataclass
class RunResult:
    status: str                     # completed / interrupted / max_visits / error
    state: State
    history: list[str]
    visits: dict[str, int]
    llm_calls: int
    checkpoint: Checkpoint | None = None
    error: str = ""

    @property
    def final_reply(self) -> str:
        return str(self.state.get("final_reply", ""))


class StateGraph:
    """状态机引擎：极简，但该有的都有。

        graph.add_node(...)             加节点
        graph.add_edge(a, b)            加边
        graph.add_conditional(a, fn, {"key": "node"})   加条件边
        graph.run(state, human)         跑
        graph.resume(checkpoint, human) 从检查点接着跑（换一个进程也行）
    """

    def __init__(self, name: str, llm: LLM, max_visits: int = 6,
                 models: dict[str, LLM] | None = None) -> None:
        self.name = name
        self.llm = llm
        self.models = dict(models or {})     # 按角色提供的额外模型（例如分类专用小模型）
        self.max_visits = max_visits
        self.nodes: dict[str, Node] = {}
        self.edges: list[Edge] = []
        self.conditionals: list[ConditionalEdge] = []
        self.entry = ""

    # ---- 构图 ---------------------------------------------------------
    def add_node(self, name: str, fn: Callable[[State, NodeContext], dict | None],
                 kind: str = "deterministic", title: str = "") -> "StateGraph":
        if name in self.nodes:
            raise GraphError(f"节点重名：{name}")
        self.nodes[name] = Node(name=name, fn=fn, kind=kind, title=title or name)
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self.edges.append(Edge(src, dst))
        return self

    def add_conditional(self, src: str, router: Callable[[State], str],
                        targets: dict[str, str], label: str = "") -> "StateGraph":
        self.conditionals.append(ConditionalEdge(src, router, targets, label))
        return self

    def set_entry(self, name: str) -> "StateGraph":
        self.entry = name
        return self

    # ---- 图校验：把错误挡在运行之前 -----------------------------------
    def validate(self) -> list[str]:
        """返回图的问题列表（空 = 合法）。生产系统里这一步应该跑在 CI 里。"""
        issues: list[str] = []
        if self.entry not in self.nodes:
            issues.append(f"入口节点未设置或不存在：{self.entry!r}")
            return issues

        for e in self.edges:
            if e.dst not in self.nodes and e.dst != END:
                issues.append(f"边 {e.src} → {e.dst} 指向不存在的节点")
        for c in self.conditionals:
            if c.src not in self.nodes:
                issues.append(f"条件边的起点不存在：{c.src}")
            for key, dst in c.targets.items():
                if dst not in self.nodes and dst != END:
                    issues.append(f"条件边 {c.src} 的分支 {key!r} 指向不存在的节点 {dst}")

        # 可达性：从入口出发，走遍所有边，看有没有"孤岛节点"
        reachable = self._reachable(self.entry)
        for name in self.nodes:
            if name not in reachable:
                issues.append(f"节点 {name} 从入口不可达（死代码）")

        # 每个节点都必须能走到 END（否则运行到一半会"卡死在图里"）
        for name in self.nodes:
            if END not in self._reachable(name):
                issues.append(f"节点 {name} 无法到达 END（可能死循环或漏了出边）")
        return issues

    def _reachable(self, start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in self._next_nodes(cur):
                if nxt not in seen:
                    stack.append(nxt)
        return seen

    def _next_nodes(self, name: str) -> list[str]:
        out = [e.dst for e in self.edges if e.src == name]
        out += [t for c in self.conditionals if c.src == name for t in c.targets.values()]
        return out

    # ---- 运行 ---------------------------------------------------------
    def run(self, state: State, human: HumanChannel | None = None) -> RunResult:
        return self._execute(self.entry, dict(state), {}, [], human or HumanChannel(), 0)

    def resume(self, checkpoint: Checkpoint, human: HumanChannel | None = None) -> RunResult:
        """从检查点继续。**注意这是"另一个进程"也能干的事** —— 前提是 state 是纯 JSON。"""
        if checkpoint.graph != self.name:
            raise GraphError(f"检查点属于图 {checkpoint.graph!r}，不能喂给 {self.name!r}")
        return self._execute(checkpoint.node, dict(checkpoint.state), dict(checkpoint.visits),
                             list(checkpoint.history), human or HumanChannel(), checkpoint.llm_calls)

    # ---- 引擎核心：一个 while 循环，仅此而已 ---------------------------
    def _execute(self, cursor: str, state: State, visits: dict[str, int],
                 history: list[str], human: HumanChannel, llm_calls: int) -> RunResult:
        ctx = NodeContext(llm=self.llm, human=human, models=dict(self.models), llm_calls=llm_calls)

        while cursor != END:
            if cursor not in self.nodes:
                return RunResult("error", state, history, visits, ctx.llm_calls,
                                 error=f"节点不存在：{cursor}")

            visits[cursor] = visits.get(cursor, 0) + 1
            history.append(cursor)

            # 循环保护：同一个节点被访问太多次 = 图里有环且没有出口 → 强制停机。
            # 和 Agent 的 max_steps 是同一个道理，只是这里保护的是"流程"而不是"对话"。
            if visits[cursor] > self.max_visits:
                return RunResult("max_visits", state, history, visits, ctx.llm_calls,
                                 error=f"节点 {cursor} 被访问 {visits[cursor]} 次，超过上限 {self.max_visits}")

            node = self.nodes[cursor]
            # 挂起前，先把人工答复塞进 state —— 这样 resume 后节点能直接读到
            if node.kind == "human" and "human_reply" not in state:
                answer = human.try_ask(node.title or "请人工确认")
                if answer is not None:
                    state["human_reply"] = answer

            try:
                update = node.fn(state, ctx)
            except Interrupt as stop:
                # ★ 挂起：保存现场后**干净地退出**（不是崩溃，是可以恢复的暂停）
                cp = Checkpoint(self.name, stop.resume_at or cursor, dict(state),
                                dict(visits), list(history), ctx.llm_calls)
                state["pending_question"] = stop.question
                cp.state = dict(state)
                return RunResult("interrupted", state, history, visits, ctx.llm_calls, checkpoint=cp)
            except Exception as exc:                      # 任何节点异常都不该让宿主进程崩掉
                return RunResult("error", state, history, visits, ctx.llm_calls,
                                 error=f"{type(exc).__name__}: {exc}")

            if update:
                # 节点只返回"它改了什么"（增量更新），而不是整个 state ——
                # 这样并发/回放/审计都容易做，也是 LangGraph 的 reducer 思路。
                state.update(update)
            if node.kind == "human":
                # 人工答复是一次性的：结算完就清掉，避免"上一轮的批准"被下一轮复用
                state.pop("human_reply", None)

            cursor = self._next(cursor, state)

        return RunResult("completed", state, history, visits, ctx.llm_calls)

    def _next(self, cursor: str, state: State) -> str:
        for c in self.conditionals:                 # 条件边优先
            if c.src == cursor:
                key = c.router(state)
                if key not in c.targets:
                    raise GraphError(f"路由器在 {cursor} 返回了未定义的分支 {key!r}，"
                                     f"已定义：{sorted(c.targets)}")
                return c.targets[key]
        for e in self.edges:
            if e.src == cursor:
                return e.dst
        return END                                   # 没有出边 = 流程结束


# ===========================================================================
# 五、节点实现：先确定性，最后才轮到模型
# ===========================================================================


def rule_classify(text: str) -> str | None:
    """关键词规则：命中就返回类别，认不出来返回 None。

    ★ 这一小节是全章的题眼：**能用确定性代码解决的，绝不用模型。**
      真实业务里，80% 的工单都带着明显的关键词。先跑规则，只有长尾才交给模型。
      收益：成本下降、延迟下降、**结果可复现**（同一句话永远分到同一类，可写单元测试）。
    """
    rules = (
        ("refund", ("退款", "退货", "不要了", "取消订单")),
        ("logistics", ("快递", "物流", "到哪", "什么时候到", "发货")),
        ("consult", ("怎么用", "怎么开", "有效期", "规则")),
    )
    for label, words in rules:
        if any(w in text for w in words):
            return label
    return None


class TicketClassifierLLM(LLM):
    """"语义分类"节点用的假模型：只处理规则认不出来的长尾表达。"""

    name = "classifier"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        text = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if "券" in text:
            label = "consult"
        elif "退" in text:
            label = "refund"
        else:
            label = "logistics"
        return as_mock_response(label, self.model)


class ReplyDrafterLLM(LLM):
    """写话术的假模型：唯一一个"必须用模型"的节点（把结论翻译成人话）。

    它有一个真实的坏习惯：**爱用绝对化措辞**（"绝对保证"）。
    这正是确定性合规检查存在的意义 —— 见第 ③ 节。
    """

    name = "drafter"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        brief = "\n".join(m.content for m in messages if m.role == "user")
        ticket = re.search(r"工单\s*(\S+)", brief)
        tid = ticket.group(1) if ticket else "T-0000"
        body = re.search(r"结论：(.+)", brief)
        decision = body.group(1).strip() if body else "已为您处理。"
        revised = "人工修改意见" in brief

        if revised:
            # 拿到人工意见后：删掉绝对化措辞、加上可验证的时限
            wording = "预计 24 小时内到账"
        else:
            wording = "绝对保证 24 小时内到账"          # ← 违规措辞，会被合规检查拦下

        return as_mock_response(
            f"【工单 {tid} 回复】您好，非常抱歉给您带来不便。\n"
            f"{decision}\n"
            f"相关补偿{wording}。如有其他问题请随时联系我们。",
            self.model,
        )


# ---- 各节点函数 -----------------------------------------------------------


def node_intake(state: State, ctx: NodeContext) -> dict:
    """入口：确定性的输入校验（护栏要在模型之前，这样脏数据连模型都碰不到）。"""
    text = str(state.get("text", "")).strip()
    if not text:
        return {"rejected": True, "reject_reason": "工单内容为空"}
    if len(text) > 200:
        return {"rejected": True, "reject_reason": "工单内容过长，疑似垃圾信息"}
    return {"rejected": False, "text": text}


def node_classify(state: State, ctx: NodeContext) -> dict:
    """分类：**规则优先，模型兜底**。"""
    label = rule_classify(state["text"])
    if label:
        return {"category": label, "classified_by": "规则（0 次模型调用）"}
    label = ctx.ask_llm([
        Message.system("你是工单分类器。只输出一个类别：refund / logistics / consult。"),
        Message.user(state["text"]),
    ], role="classifier").strip()
    return {"category": label, "classified_by": "模型（规则认不出来才用它）"}


def node_handle_refund(state: State, ctx: NodeContext) -> dict:
    """退款处理：纯查表 + 纯 if，答案本来就在规则里，模型插不上手。"""
    order = ORDERS.get(state.get("order_id", ""), {})
    status = order.get("status", "未知")
    if status == "待付款":
        decision = "您的订单尚未付款，已为您直接取消，不产生任何费用。"
    elif status == "已发货":
        decision = "您的订单已发货，可在签收后 7 天内申请退货，运费由我们承担。"
    else:
        decision = "未查询到该订单，请核对订单号后重试。"
    return {"decision": decision, "handled_by": "退款规则表"}


def node_handle_logistics(state: State, ctx: NodeContext) -> dict:
    """物流处理：同样是查表。"""
    order = ORDERS.get(state.get("order_id", ""), {})
    if order.get("status") == "已发货":
        decision = f"您的包裹已由{order['carrier']}发出，预计 {order['eta']} 送达。"
    else:
        decision = "该订单还没有发货记录，请确认订单状态。"
    return {"decision": decision, "handled_by": "物流表"}


def node_handle_consult(state: State, ctx: NodeContext) -> dict:
    """咨询处理：FAQ 里有标准答案 → 查表返回，**0 次模型调用**。"""
    for key, answer in FAQ.items():
        if key in state["text"]:
            return {"decision": answer, "handled_by": "FAQ 表"}
    return {"decision": "这个问题没有标准答案，已为您转接人工。", "handled_by": "转人工"}


def node_draft_reply(state: State, ctx: NodeContext) -> dict:
    """写话术：**这才是真正需要模型的节点**（把结论翻译成得体的中文）。"""
    brief = f"工单 {state['ticket_id']}\n结论：{state['decision']}"
    if state.get("revision_notes"):
        brief += f"\n人工修改意见：{state['revision_notes']}"
    draft = ctx.ask_llm([
        Message.system("你是客服文案，把已确认的结论写成给客户的话，不要添加未确认的承诺。"),
        Message.user(brief),
    ])
    return {"draft": draft.strip()}


def node_compliance(state: State, ctx: NodeContext) -> dict:
    """合规检查：**确定性的 6 行代码**，替代一个"模型自审"节点。

    为什么不用模型做合规？
        因为它不稳（同样的话这次说有风险、下次说没风险），而合规要求**每次判断都一样**。
        这类"有明确规则、必须可审计"的检查，是确定性代码的主场。
    """
    draft = state.get("draft", "")
    issues: list[str] = []
    for word in FORBIDDEN_WORDS:
        if word in draft:
            issues.append(f"出现禁用词「{word}」")
    for amount in re.findall(r"(\d+)\s*元", draft):
        if amount not in APPROVED_AMOUNTS:
            issues.append(f"出现未批准的金额承诺「{amount} 元」")
    if state["ticket_id"] not in draft:
        issues.append("回复中缺少工单号，无法归档")
    return {"compliance_issues": issues}


def node_human_review(state: State, ctx: NodeContext) -> dict:
    """人工介入节点：需要人拍板时**挂起**，拿到答复后继续。

    注意它有两种进入方式：
        1. 正常执行到这里，但 state 里没有人工答复 → 抛 Interrupt（引擎保存检查点退出）
        2. resume 时引擎已经把答复放进 state["human_reply"] → 直接结算
    """
    reply = state.get("human_reply")
    if reply is None:
        raise Interrupt(
            f"草稿未通过合规检查：{state.get('compliance_issues')}，请人工审批",
            resume_at="human_review",
        )
    if reply.get("decision") == "approved":
        return {"human_decision": "approved", "human_note": reply.get("note", "")}
    return {"human_decision": "rejected",
            "revision_notes": reply.get("note", "请修改后重新提交")}


def node_finalize(state: State, ctx: NodeContext) -> dict:
    """交付：确定性收口（补齐元信息、标记完成）。"""
    return {"final_reply": state.get("draft", ""), "finished": True}


# ---- 路由器（纯函数） -----------------------------------------------------


def route_after_intake(state: State) -> str:
    return "reject" if state.get("rejected") else "ok"


def route_by_category(state: State) -> str:
    return state.get("category", "consult")


def route_after_compliance(state: State) -> str:
    return "pass" if not state.get("compliance_issues") else "human"


def route_after_human(state: State) -> str:
    return "approve" if state.get("human_decision") == "approved" else "revise"


# ===========================================================================
# 六、把图搭起来：分类 → 路由 → 处理 → 汇总
# ===========================================================================


def build_graph(max_visits: int = 6) -> StateGraph:
    """客服工单处理图。**读这张图比读一千行 if/else 快得多** —— 这正是它的价值。"""
    g = StateGraph("客服工单处理", llm=ReplyDrafterLLM(), max_visits=max_visits,
                   models={"classifier": TicketClassifierLLM()})

    g.add_node("intake", node_intake, title="输入校验")
    g.add_node("classify", node_classify, title="分类（规则优先，模型兜底）")
    g.add_node("handle_refund", node_handle_refund, title="退款处理")
    g.add_node("handle_logistics", node_handle_logistics, title="物流处理")
    g.add_node("handle_consult", node_handle_consult, title="咨询处理（FAQ 查表）")
    g.add_node("draft_reply", node_draft_reply, kind="llm", title="撰写回复")
    g.add_node("compliance", node_compliance, title="合规检查")
    g.add_node("human_review", node_human_review, kind="human", title="人工审批")
    g.add_node("finalize", node_finalize, title="交付")

    g.set_entry("intake")
    # 入口用条件边：校验不通过的工单直接出局，连分类节点都不进
    g.add_conditional("intake", route_after_intake, {"ok": "classify", "reject": END}, "校验结果")

    # 分类 → 三条业务分支（这就是"分类→路由→处理"里的路由）
    g.add_conditional("classify", route_by_category,
                      {"refund": "handle_refund", "logistics": "handle_logistics",
                       "consult": "handle_consult"}, "按类别路由")
    for handler in ("handle_refund", "handle_logistics", "handle_consult"):
        g.add_edge(handler, "draft_reply")

    g.add_edge("draft_reply", "compliance")
    g.add_conditional("compliance", route_after_compliance,
                      {"pass": "finalize", "human": "human_review"}, "合规结果")
    g.add_conditional("human_review", route_after_human,
                      {"approve": "finalize", "revise": "draft_reply"}, "人工结论")
    g.add_edge("finalize", END)
    return g


# ===========================================================================
# 七、反面教材：把流程交给模型自己决定
# ===========================================================================


class AutonomousAgentLLM(LLM):
    """"你自己看着办"型 Agent：没人告诉它必须做合规检查，于是它就不做。

    它并不笨 —— 它只是**没有流程**。模型只会做你要求的事，不会替你想起来还有合规这一步。
    """

    name = "autonomous"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        tid = "T-9002"
        m = re.search(r"(T-\d+)", "\n".join(x.content for x in messages))
        if m:
            tid = m.group(1)
        return as_mock_response(
            f"【工单 {tid} 回复】您好，您的订单已经发货啦，绝对保证明天一定到！"
            f"（内部备注：该线路本月已延误 3 次）",
            self.model,
        )


def run_autonomous(ticket: State) -> tuple[str, int]:
    """让 Agent 自由发挥：一次调用直接给答案。"""
    llm = AutonomousAgentLLM()
    resp = llm.complete([
        Message.system("你是客服 Agent，请处理这张工单，直接给出给客户的回复。"),
        Message.user(f"工单 {ticket['ticket_id']}：{ticket['text']}"),
    ])
    return resp.text, llm.total_calls


def audit_reply(text: str) -> list[str]:
    """确定性审计：把"模型自由发挥"的结果放到同一把尺子下量。"""
    issues = []
    for word in FORBIDDEN_WORDS:
        if word in text:
            issues.append(f"禁用词「{word}」")
    if not re.search(r"T-\d+", text):
        issues.append("缺少工单号")
    return issues


# ===========================================================================
# 第 ① 节：没有骨架的世界
# ===========================================================================


def demo_autonomous() -> str:
    section("让模型自己决定流程：它会跳过合规检查", "①")

    reply, calls = run_autonomous(TICKET_LOGISTICS)
    code(reply, indent=4)
    print()
    kv("模型调用次数", calls)
    kv("审计结果", f"不通过（{len(audit_reply(reply))} 项）")
    for i in audit_reply(reply):
        bullet(i, indent=4)
    print()
    warn("没有任何一步叫「合规检查」，所以模型当然不会做 —— 它只做你要求的事。")
    note("顺序也不可控：这次先查订单再道歉，下次可能反过来。**不可复现 = 不可运维。**")
    note("结论：把「流程」从模型手里拿走，写进一张显式的图里。")
    return reply


# ===========================================================================
# 第 ② 节：状态机跑通三类工单
# ===========================================================================


def _run_ticket(graph: StateGraph, ticket: State, human: HumanChannel) -> RunResult:
    return graph.run(dict(ticket), human=human)


APPROVE = {"decision": "approved", "note": "合规已确认，可以发送"}


def demo_basic_flow() -> list[RunResult]:
    section("状态机跑通「分类 → 路由 → 处理 → 汇总」", "②")

    results = []
    for ticket in (TICKET_REFUND, TICKET_LOGISTICS, TICKET_CONSULT):
        graph = build_graph()
        r = _run_ticket(graph, ticket, HumanChannel([dict(APPROVE)]))
        results.append(r)
        kv(f"{ticket['ticket_id']} 类别", r.state["category"])
        kv("  分类方式", r.state["classified_by"])
        kv("  处理节点", r.state["handled_by"])
        kv("  路径", " → ".join(r.history))
        kv("  状态 / 模型调用", f"{r.status} / {r.llm_calls} 次")
        print()

    note("每条路径都是图里写死的分支，跑一百次都一样（可复现、可测试、可画出来给产品看）。")
    note("注意三条工单只有「撰写回复」这一步用了模型；分类全部命中关键词规则。")
    return results


# ===========================================================================
# 第 ③ 节：确定性优先
# ===========================================================================


def demo_deterministic_first() -> RunResult:
    section("确定性优先：能写死的，绝不用模型", "③")

    # --- A：规则认不出来的长尾工单，才轮到模型 ---
    r_rule = _run_ticket(build_graph(), TICKET_LOGISTICS, HumanChannel([dict(APPROVE)]))
    r_llm = _run_ticket(build_graph(), TICKET_AMBIGUOUS, HumanChannel([dict(APPROVE)]))
    kv("明确工单 · 分类方式", r_rule.state["classified_by"])
    kv("明确工单 · 总模型调用", r_rule.llm_calls)
    kv("模糊工单 · 分类方式", r_llm.state["classified_by"])
    kv("模糊工单 · 总模型调用", r_llm.llm_calls)
    print()

    # --- B：合规检查 —— 模型会放过，代码不会 ---
    graph = build_graph()
    r = _run_ticket(graph, TICKET_LOGISTICS, HumanChannel([dict(APPROVE)]))
    first_draft_issues = audit_reply(r.state["draft"])
    kv("模型写出的第一版草稿", r.state["draft"].splitlines()[2][:40])
    kv("确定性合规检查抓到", f"{len(first_draft_issues)} 项：{first_draft_issues}")
    kv("检查用了多少行代码", "6 行（见 node_compliance）")
    kv("检查调用了多少次模型", "0 次")
    print()

    note("节点分工表（本章的核心结论）：")
    print(f"     {'节点':<16}{'类型':<14}{'为什么'}")
    print("     " + "-" * 62)
    for name, kind, why in [
        ("intake", "确定性", "输入校验是规则，错了要能一眼看懂"),
        ("classify", "规则 + 模型兜底", "80% 有关键词；长尾才值得花一次调用"),
        ("handle_*", "确定性", "答案在订单表和 FAQ 里，模型只会读错"),
        ("draft_reply", "模型", "把结论写成人话 —— 这才是语言模型的活"),
        ("compliance", "确定性", "合规必须每次判断一致、可审计"),
        ("human_review", "人工", "责任问题，不能交给概率"),
        ("finalize", "确定性", "收口动作没什么可判断的"),
    ]:
        print(f"     {name:<16}{kind:<14}{why}")
    print()
    ok("同一张图，模型只出现在 2 个节点上；其余 7 个节点的行为 100% 可预测。")
    return r


# ===========================================================================
# 第 ④ 节：检查点与恢复
# ===========================================================================


def demo_checkpoint() -> tuple[RunResult, RunResult, RunResult]:
    section("检查点：跑到一半挂起，落盘成 JSON，再接着跑", "④")

    # --- 第一次运行：人工通道是空的（相当于"审批人不在线"） ---
    graph_a = build_graph()
    first = _run_ticket(graph_a, TICKET_LOGISTICS, HumanChannel([]))
    kv("第一次运行 · 状态", first.status)
    kv("第一次运行 · 停在哪", first.checkpoint.node if first.checkpoint else "-")
    kv("第一次运行 · 已走过的路径", " → ".join(first.history))
    kv("第一次运行 · 模型调用", first.llm_calls)
    print()
    note("挂起时保存的检查点（**这就是一个纯 JSON**，可以塞进 Redis / 数据库 / 消息队列）：")
    assert first.checkpoint is not None
    code(first.checkpoint.to_json(indent=2), indent=4)
    print()

    # --- 模拟"进程重启"：全新的图对象 + 从磁盘读回来的检查点 ---
    # 场景 A：人工直接放行 → 从断点续跑到交付
    graph_b = build_graph()                       # 全新的引擎实例，内存里什么都没有
    restored = Checkpoint.from_json(first.checkpoint.to_json())
    resumed = graph_b.resume(restored, human=HumanChannel([dict(APPROVE)]))

    kv("恢复后 · 状态", resumed.status)
    kv("恢复后 · 完整路径", " → ".join(resumed.history))
    kv("恢复后 · 模型调用总数", f"{resumed.llm_calls}（恢复过程新增 "
                                f"{resumed.llm_calls - first.llm_calls} 次）")
    kv("恢复后 · classify 被访问次数", f"{resumed.visits.get('classify')} 次（没有重新分类）")
    print()
    note("★ 恢复过程中**一次模型调用都没发生**：分类结果、订单结论、草稿全都躺在检查点里。")
    print()

    # --- 场景 C：人工要求修改 → 恢复后走 revise 分支，产出干净话术 ---
    graph_c = build_graph()
    rejection = {"decision": "rejected", "note": "删掉「绝对保证」，改成「预计」，并注明到账时限。"}
    fixed = graph_c.resume(Checkpoint.from_json(first.checkpoint.to_json()),
                           human=HumanChannel([dict(rejection), dict(APPROVE)]))
    kv("要求修改后 · 完整路径", " → ".join(fixed.history))
    kv("要求修改后 · 模型调用", f"{fixed.llm_calls} 次（多了 1 次：按人工意见重写草稿）")
    print()
    code(fixed.final_reply, indent=4)
    print()
    ok("恢复没有重跑任何已完成节点，也没有重新做已经做过的判断 —— 判断结果都在检查点里。")
    warn("前提：state 必须是纯 JSON。把模型客户端、回调函数塞进 state 的代码，是恢复不了的。")
    return first, resumed, fixed


# ===========================================================================
# 第 ⑤ 节：人工介入节点
# ===========================================================================


def demo_human_in_the_loop() -> RunResult:
    section("人工介入：模型说不通的，让人拍板", "⑤")

    rejection = {"decision": "rejected",
                 "note": "删掉「绝对保证」，改成「预计」，并注明补偿到账时限。"}
    graph = build_graph()
    r = _run_ticket(graph, TICKET_LOGISTICS, HumanChannel([dict(rejection), dict(APPROVE)]))

    kv("运行状态", r.status)
    kv("完整路径", " → ".join(r.history))
    kv("合规问题（第一次）", "草稿含禁用词「绝对保证」")
    kv("人工意见", rejection["note"])
    kv("human_review 被访问", f"{r.visits.get('human_review')} 次（答复后直接继续，全程无阻塞）")
    kv("模型调用", f"{r.llm_calls} 次（写草稿 + 按人工意见重写）")
    print()
    code(r.final_reply, indent=4)
    print()
    ok("人工拒绝 → 走 revise 分支回到 draft_reply → 重新合规检查 → 通过 → 交付。")
    note("这条回环也是**图里的边**，不是靠模型「想起来要改」—— 流程的每一条路径都可见。")
    warn("教学里人工答复由确定性剧本提供；真实系统里这一步是消息队列 + 回调，绝不阻塞进程。")
    return r


# ===========================================================================
# 第 ⑥ 节：图校验与循环保护
# ===========================================================================


def demo_graph_guardrails() -> None:
    section("图校验与循环保护：把错误挡在运行之前", "⑥")

    # --- 坏图：分支指向不存在的节点 + 存在孤岛节点 ---
    bad = StateGraph("坏图示例", llm=ReplyDrafterLLM())
    bad.add_node("a", node_intake).add_node("orphan", node_finalize)
    bad.set_entry("a")
    bad.add_conditional("a", lambda s: "go", {"go": "missing_node"}, "指向不存在的节点")
    issues = bad.validate()
    kv("坏图 · 校验发现", f"{len(issues)} 个问题")
    for i in issues:
        bullet(i, indent=4)
    print()
    ok("图的问题在**构建期**就被抓出来了，而不是运行到半夜才炸。")
    print()

    # --- 只说"不行"、不写修改意见的人工：草稿一字未变 → 流程原地打转 ---
    # 这正是第 07 章讲过的：**不可执行的反馈不产生任何进展**。
    vague_reject = {"decision": "rejected", "note": ""}
    graph = build_graph(max_visits=2)
    r = _run_ticket(graph, TICKET_LOGISTICS, HumanChannel([dict(vague_reject)] * 8))
    kv("循环保护 · 运行状态", r.status)
    kv("循环保护 · 停机原因", r.error[:52])
    kv("循环保护 · 路径", " → ".join(r.history))
    kv("循环保护 · 模型调用", f"{r.llm_calls} 次（没被无限放大）")
    print()
    ok("max_visits 生效：人工一直拒绝也不会把流程卡死或烧穿账单。")
    note("注意最终 status = max_visits 而不是 completed —— **失败要能被上层看见**，不能假装成功。")
    warn("更好的做法是**从源头**堵住：在 human_review 节点里强制校验「修改意见必填」，空的直接打回。")
    note("用一条确定性规则消灭一整类空转 —— 又是那句：能用代码解决的，绝不用模型。")
    print()
    good = build_graph().validate()
    kv("本文这张图的校验结果", "通过（0 个问题）" if not good else f"{len(good)} 个问题")


# ===========================================================================
# 第 ⑦ 节：一句话本质
# ===========================================================================


def demo_essence() -> None:
    section("收口：一句话本质", "⑦")
    essence(
        "能用确定性代码解决的，绝不用模型。\n"
        "\n"
        "  流程骨架 = 节点 + 边 + 条件路由（写死的图，可画、可测、可审计）\n"
        "  模型只出现在「需要判断」的节点：分类兜底、把结论写成人话\n"
        "  状态（state）= 纯 JSON → 才能有检查点、断点续跑、人工介入\n"
        "\n"
        "三条判据，问自己：\n"
        "  · 这件事的答案在表里 / 规则里吗？        → 写代码\n"
        "  · 这件事每次都必须给出同样的判断吗？    → 写代码\n"
        "  · 剩下的（语言、语义、开放判断）        → 交给模型\n"
        "\n"
        "给 Agent 多少自由度，是一个**架构决策**，不是模型能力问题。"
    )


# ===========================================================================
# 验收标准
# ===========================================================================


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（由 scripts/run_all_checks.py 调用）。不打印、确定性、< 1 秒。"""
    results: list[tuple[str, bool, str]] = []
    approve = lambda: HumanChannel([dict(APPROVE)])          # noqa: E731

    # ---------- 验收 1：状态机能表达「分类→路由→处理→汇总」 ----------
    routed = {}
    for ticket, want_node in ((TICKET_REFUND, "handle_refund"),
                              (TICKET_LOGISTICS, "handle_logistics"),
                              (TICKET_CONSULT, "handle_consult")):
        r = build_graph().run(dict(ticket), human=approve())
        routed[ticket["ticket_id"]] = (r, want_node)
    results.append(check_that(
        "三类工单分别路由到正确的处理节点",
        all(r.status == "completed" and want in r.history and r.state["handled_by"]
            for r, want in routed.values()),
        " / ".join(f"{k}:{r.state['handled_by']}" for k, (r, _) in routed.items())))
    results.append(check_that(
        "流程走到 END 并交付（status == completed）",
        all(r.status == "completed" and r.final_reply for r, _ in routed.values()),
        f"{len(routed)} 条工单全部完成"))
    results.append(check_that(
        "确定性护栏在模型之前：空工单被拒且 0 次模型调用",
        (lambda r: r.status == "completed" and r.state.get("rejected") and r.llm_calls == 0)(
            build_graph().run(dict(TICKET_EMPTY), human=approve())),
        "空工单不进模型"))

    # ---------- 验收 2：条件边（合规通过 / 转人工） ----------
    normal = build_graph().run(dict(TICKET_LOGISTICS), human=approve())
    results.append(check_that(
        "条件边：首版草稿违规 → 路由到人工审批",
        "human_review" in normal.history and normal.state["human_decision"] == "approved",
        " → ".join(normal.history)))
    results.append(check_that(
        "条件边：人工放行后 → finalize 交付",
        normal.history[-2:] == ["human_review", "finalize"] and normal.status == "completed",
        " → ".join(normal.history[-3:])))
    clean_first = build_graph().run(dict(TICKET_LOGISTICS), human=HumanChannel([]))
    results.append(check_that(
        "合规检查是确定性代码：禁用词被稳定抓出",
        any("绝对保证" in i for i in clean_first.state.get("compliance_issues", [])),
        f"{clean_first.state.get('compliance_issues')}"))

    # ---------- 验收 3：检查点可序列化、可恢复 ----------
    interrupted = build_graph().run(dict(TICKET_LOGISTICS), human=HumanChannel([]))
    cp = interrupted.checkpoint
    results.append(check_that(
        "无人审批时挂起并产出检查点（不是崩溃）",
        interrupted.status == "interrupted" and cp is not None and cp.node == "human_review",
        f"status={interrupted.status} / node={cp.node if cp else '-'}"))
    assert cp is not None
    text = cp.to_json()
    results.append(check_that(
        "检查点是纯 JSON（json.dumps → loads 往返完全一致）",
        Checkpoint.from_json(text).to_json() == text and json.loads(text)["state"]["category"] == "logistics",
        f"{len(text)} 字符的 JSON"))
    fresh_graph = build_graph()                       # 模拟"换个进程"
    resumed = fresh_graph.resume(Checkpoint.from_json(text), human=approve())
    results.append(check_that(
        "从检查点恢复并跑到完成（换一个引擎实例也行）",
        resumed.status == "completed" and resumed.final_reply == normal.final_reply,
        "恢复结果与一次跑完一致"))
    results.append(check_that(
        "恢复不重跑已完成节点（intake/classify/draft 各只执行一次）",
        resumed.visits.get("intake") == 1 and resumed.visits.get("classify") == 1
        and resumed.visits.get("draft_reply") == 1,
        f"visits={ {k: resumed.visits[k] for k in ('intake', 'classify', 'handle_logistics', 'draft_reply')} }"))
    results.append(check_that(
        "恢复过程没有重复调用模型（判断结果来自检查点）",
        resumed.llm_calls == interrupted.llm_calls,
        f"{interrupted.llm_calls} → {resumed.llm_calls} 次"))

    # ---------- 验收 4：人工介入是确定性注入（不调用 input） ----------
    rejection = {"decision": "rejected", "note": "删掉「绝对保证」，改成「预计」。"}
    hl = build_graph().run(dict(TICKET_LOGISTICS), human=HumanChannel([dict(rejection), dict(APPROVE)]))
    results.append(check_that(
        "人工拒绝 → 回到 draft_reply 修订 → 重新合规 → 交付",
        hl.status == "completed" and hl.visits.get("draft_reply") == 2
        and hl.visits.get("compliance") == 2 and "绝对保证" not in hl.final_reply,
        " → ".join(hl.history)))
    human_channel = HumanChannel([dict(APPROVE)])
    build_graph().run(dict(TICKET_LOGISTICS), human=human_channel)
    results.append(check_that(
        "人工答复来自确定性剧本（不阻塞、不读 stdin）",
        len(human_channel.asked) == 1 and not human_channel.replies,
        f"人工被询问 {len(human_channel.asked)} 次，剧本已消费完"))

    # ---------- 验收 5：模型只在需要判断的节点出现 ----------
    llm_nodes = {n.name for n in build_graph().nodes.values() if n.kind == "llm"}
    results.append(check_that(
        "只有 draft_reply 被标记为 llm 节点（其余节点确定性）",
        llm_nodes == {"draft_reply"},
        f"llm 节点 = {sorted(llm_nodes)}，共 {len(build_graph().nodes)} 个节点"))
    easy = build_graph().run(dict(TICKET_LOGISTICS), human=approve())
    hard = build_graph().run(dict(TICKET_AMBIGUOUS), human=approve())
    results.append(check_that(
        "规则优先：明确工单 0 次分类调用，模糊工单才用模型",
        easy.state["classified_by"].startswith("规则") and hard.state["classified_by"].startswith("模型")
        and easy.llm_calls == 1 and hard.llm_calls == 2,
        f"明确 {easy.llm_calls} 次 / 模糊 {hard.llm_calls} 次"))

    # ---------- 验收 6：图校验与循环保护 ----------
    bad = StateGraph("坏图", llm=ReplyDrafterLLM())
    bad.add_node("a", node_intake).add_node("orphan", node_finalize)
    bad.set_entry("a")
    bad.add_conditional("a", lambda s: "go", {"go": "missing_node"})
    issues = bad.validate()
    results.append(check_that(
        "坏图在构建期被拦下（悬空分支 + 不可达节点）",
        len(issues) >= 2 and any("不存在" in i for i in issues) and any("不可达" in i for i in issues),
        f"{len(issues)} 个问题"))
    results.append(check_that(
        "本文的图通过校验（每个节点都可达且都能到 END）",
        build_graph().validate() == [], "0 个问题"))
    looping = build_graph(max_visits=2).run(
        dict(TICKET_LOGISTICS),
        human=HumanChannel([{"decision": "rejected", "note": ""}] * 8))   # 只说"不行"，不说怎么改
    results.append(check_that(
        "反馈不可执行时会空转 → 被 max_visits 强制停机（不假装成功）",
        looping.status == "max_visits" and len(looping.history) < 12,
        f"status={looping.status} / {len(looping.history)} 步 / 模型调用 {looping.llm_calls} 次"))

    # ---------- 验收 7：可复现 ----------
    a = build_graph().run(dict(TICKET_REFUND), human=approve())
    b = build_graph().run(dict(TICKET_REFUND), human=approve())
    results.append(check_that(
        "同一工单两次运行结果完全一致（可复现）",
        a.final_reply == b.final_reply and a.history == b.history and a.llm_calls == b.llm_calls,
        f"路径 {' → '.join(a.history)}"))

    # ---------- 验收 8：反面教材对照 ----------
    auto_reply, auto_calls = run_autonomous(TICKET_LOGISTICS)
    results.append(check_that(
        "对照组：让模型自定流程会跳过合规（审计不通过）",
        auto_calls == 1 and len(audit_reply(auto_reply)) >= 2,
        f"{len(audit_reply(auto_reply))} 项审计问题：{audit_reply(auto_reply)}"))

    return results


# ===========================================================================
# 入口
# ===========================================================================

SECTIONS = {
    "1": ("没有骨架的世界（对照组）", demo_autonomous),
    "2": ("状态机跑通三类工单", demo_basic_flow),
    "3": ("确定性优先", demo_deterministic_first),
    "4": ("检查点与恢复", demo_checkpoint),
    "5": ("人工介入节点", demo_human_in_the_loop),
    "6": ("图校验与循环保护", demo_graph_guardrails),
    "7": ("一句话本质", demo_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 09 章 · 工作流与状态机")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 09 章 · 工作流与状态机")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 09 章", run_checks()) else 1

    banner("第 09 章 · 工作流与状态机",
           "目标：手写一个状态机引擎，看住 Agent 的「自由度」")

    chosen = [args.section] if args.section else sorted(SECTIONS)
    for key in chosen:
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 09 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
