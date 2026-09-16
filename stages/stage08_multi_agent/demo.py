"""第 08 章 · 多智能体协作 —— 多智能体 = 角色分工 + 消息传递 + 结果仲裁。

运行：
    py -m stages.stage08_multi_agent.demo
    py -m stages.stage08_multi_agent.demo --list
    py -m stages.stage08_multi_agent.demo --section 3
    py -m stages.stage08_multi_agent.demo --check

本章目标：亲手搭一套 Supervisor（主管）+ Worker（专家）架构，并亲手把它**搞坏一次**，
看清多智能体的两个真相：
    ① 收益来自**专业化 + 上下文隔离**（每个专家只看自己该看的）；
    ② 代价是**通信开销与不可控性**（共享上下文会污染结论、膨胀成本、泄露内部信息）。
    结论先行：**多智能体不是自动更好** —— 单 Agent 能干的事，别上三个 Agent。

全部离线可跑：三个专家都是确定性的假模型，但它们的**行为规律是真的**
（会被上下文里的既有结论锚定、会互相踢皮球、会照抄自己看到的东西）。
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
# 一、业务背景：一张客诉工单
# ===========================================================================
# 为什么多智能体的例子必须带"业务事实"？
#   因为"分工"这件事只有在**不同角色需要不同知识**时才有意义。
#   如果三个专家看的是同一份资料，那它们就是同一个 Agent 的三次调用，纯浪费钱。


@dataclass(frozen=True)
class Ticket:
    """一张客服工单。"""

    ticket_id: str
    order_id: str
    customer: str
    complaint: str


TICKET = Ticket(
    ticket_id="T-2025-0117",
    order_id="A1001",
    customer="李先生",
    complaint="说好 1 月 5 日送到，现在还没到，我要赔付！",
)

# 订单系统的真实数据（现实中来自内部 API）。注意最后那条"内部备注"：
# 它是**不该给客户看到**的信息 —— 第 ③ 节会用它来验证"上下文隔离"是否真的生效。
ORDER = {
    "order_id": "A1001",
    "status": "已发货",
    "carrier": "顺丰",
    "tracking": "SF1234567890",
    "eta": "2025-01-05",
    "trace": "2025-01-06 09:20 到达本市网点（轨迹正常，延迟 24 小时）",
    "delay_hours": 24,
    "internal_note": "内部备注：该承运商本月已有 3 起同类延误（内部数据，勿外传）",
}


@dataclass(frozen=True)
class PolicyRule:
    """一条赔付条款。`match` 是给人看的说明；真正的判断在 PolicyWorkerLLM 里。"""

    code: str
    match: str
    action: str


POLICY_RULES: tuple[PolicyRule, ...] = (
    PolicyRule("A-1", "订单状态为「待付款」或「已取消」", "无需赔付"),
    PolicyRule("A-2", "状态为「已发货」且超过承诺日 72 小时、物流无轨迹", "现金赔付 50 元"),
    PolicyRule("B-2", "状态为「已发货」且轨迹正常、仅延迟不超过 48 小时", "不现金赔付；补偿 20 元运费券"),
)
POLICY_BY_ID = {r.code: r for r in POLICY_RULES}


# ===========================================================================
# 二、消息总线：多智能体最难查的 bug 是「谁把什么告诉了谁」
# ===========================================================================


@dataclass(frozen=True)
class Envelope:
    """一条消息。生产系统里它还必须带：唯一 id、时间戳、trace_id、重试次数。"""

    sender: str
    recipient: str
    topic: str          # task / result / question / arbitration
    payload: str
    round: int = 1

    def render(self) -> str:
        return f"[R{self.round}] {self.sender} → {self.recipient} ({self.topic}) {self.payload}"


class MessageBus:
    """消息总线：只负责投递与记账，**不做任何智能**。

    两个设计要点：
      1. 消息是**显式**的：谁发给谁、什么主题、第几轮，全都留痕（可审计、可回放）；
      2. 总线**不共享上下文**：投递的是"结论"，不是"对方的完整思考过程"。
         这一条是多智能体能不能省钱、能不能不互相污染的**分水岭**。
    """

    def __init__(self) -> None:
        self.log: list[Envelope] = []

    def send(self, env: Envelope) -> Envelope:
        self.log.append(env)
        return env

    def to(self, recipient: str) -> list[Envelope]:
        return [e for e in self.log if e.recipient == recipient]

    def topics(self) -> list[str]:
        return [e.topic for e in self.log]

    def __len__(self) -> int:
        return len(self.log)


# ===========================================================================
# 三、专家（Worker）：一人一岗、一份资料、一个结论
# ===========================================================================


@dataclass
class WorkerReport:
    """专家交回来的**结构化**汇报。

    为什么要结构化而不是"返回一段话"？
        因为主管要能把它**安全地转发给下一个专家**。
        一段自由文本里什么都有（包括不该外传的内部备注），
        而结构化字段让我们可以只挑需要的传下去 —— 这就是隔离的落地方式。
    """

    worker: str
    conclusion: str                 # 一句话结论
    facts: dict[str, str] = field(default_factory=dict)
    evidence: str = ""              # 依据（例如条款编号）
    needs_help: bool = False        # 踢皮球信号：我干不了，需要别人补材料
    prompt_chars: int = 0           # 这次它看了多少字（成本可观测）


class Worker:
    """专家基类：**自己的系统提示词 + 自己的上下文 + 自己的结论**。

    注意 handle() 里的 messages 是怎么构造的 —— 只有两块：
        自己的岗位说明书 + 主管给的子任务。
    它**看不到**别的专家说过什么，也看不到用户的原始长对话。
    这不是"省 token"的小技巧，而是多智能体可靠性的结构性保证。
    """

    role = "worker"
    title = "专家"

    def __init__(self, llm: LLM, system_prompt: str) -> None:
        self.llm = llm
        self.system_prompt = system_prompt
        self.contexts: list[str] = []       # 记录"我到底看到了什么"，用于验证隔离
        self.outputs: list[str] = []        # 记录"我说了什么"，用于验证信息流向

    def handle(self, instruction: str) -> WorkerReport:
        messages = [Message.system(self.system_prompt), Message.user(instruction)]
        self.contexts.append("\n".join(m.content for m in messages))
        resp = self.llm.complete(messages)
        self.outputs.append(resp.text)
        report = self.parse(resp.text)
        report.prompt_chars = sum(len(m.content) for m in messages)
        return report

    def parse(self, text: str) -> WorkerReport:
        raise NotImplementedError

    @property
    def seen_chars(self) -> int:
        return sum(len(c) for c in self.contexts)


# --- 三个假模型：确定性地复现"专家行为" ------------------------------------
# 再次强调：它们看起来像在"读提示词做判断"，这正是重点 ——
# 专家能不能干好，取决于**主管给它的那段上下文**够不够、干不干净。


class DataAnalystLLM(LLM):
    """数据专家：只会查数据、报事实，不做任何判断。"""

    name = "worker-data"

    def __init__(self, stubborn: bool = False, model: str = "mock-data") -> None:
        super().__init__(model)
        self.stubborn = stubborn

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        if self.stubborn:
            # 永远说"材料不够" —— 模拟真实团队里的踢皮球
            return as_mock_response(
                "我还需要政策专家先给出赔付口径，否则不知道该查哪些字段。", self.model)
        return as_mock_response(
            "已核实订单数据：\n"
            f"- 订单号：{ORDER['order_id']}，状态：{ORDER['status']}\n"
            f"- 承运商：{ORDER['carrier']}（运单号 {ORDER['tracking']}）\n"
            f"- 承诺送达：{ORDER['eta']}\n"
            f"- 实际轨迹：{ORDER['trace']}\n"
            f"{ORDER['internal_note']}",
            self.model,
        )


class PolicyExpertLLM(LLM):
    """政策专家：只做条款匹配，不碰数据获取、不写话术。"""

    name = "worker-policy"

    def __init__(self, stubborn: bool = False, model: str = "mock-policy") -> None:
        super().__init__(model)
        self.stubborn = stubborn

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        if self.stubborn:
            return as_mock_response(
                "我需要数据专家提供物流轨迹的逐条时间戳，否则无法判断条款。", self.model)

        task = next((m.content for m in reversed(messages) if m.role == "user"), "")
        # ★ 教学重点：专家能不能干好，取决于主管把事实**以什么格式**交给它。
        #   这里解析的是结构化字段（`- 键：值`），而不是让人去读一段自由文本。
        #   真实项目里这一步就是"交接单/JSON schema"—— 格式含糊，专家必然出错。
        facts = {k.strip(): v.strip() for k, v in re.findall(r"^- ([^：\n]+)：([^\n]+)$", task, re.M)}
        status = facts.get("状态", "未知")
        trace_ok = facts.get("轨迹") == "正常"
        try:
            delay = int(facts.get("延迟小时数", "-1"))
        except ValueError:
            delay = -1

        # 真正的"判断"只有两行 if —— 但它必须**拿到干净的事实**才能判断对。
        # 单 Agent 版本之所以错，是因为它把 A-2 和 B-2 记混了（见第 ① 节）。
        if status == "已发货" and trace_ok and 0 <= delay <= 48:
            rule = POLICY_BY_ID["B-2"]
        elif status == "已发货" and delay > 72:
            rule = POLICY_BY_ID["A-2"]
        else:
            rule = POLICY_BY_ID["A-1"]

        return as_mock_response(
            f"依据条款 {rule.code}（{rule.match}）：{rule.action}", self.model)


class ReplyWriterLLM(LLM):
    """文案专家：只负责把"已经定好的结论"翻译成对客户说的话。

    它的关键行为规律（第 ③④ 节会用到）：
        它**照抄自己看到的东西**。看到干净结论就写干净话术；
        看到上下文里有"现金赔付 50 元"，它就会把这句抄进对客回复。
    """

    name = "worker-reply"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        seen = "\n".join(m.content for m in messages)
        if "现金赔付 50 元" in seen:
            # 污染路径：上下文里已经有一个"结论"，模型只会顺着写（锚定效应）
            return as_mock_response(
                f"【工单 {TICKET.ticket_id} 回复】{TICKET.customer}您好，非常抱歉。"
                f"经核实订单 {TICKET.order_id} 延误，我们将在 3 个工作日内现金赔付 50 元。"
                f"{ORDER['internal_note']}",
                self.model,
            )

        # 干净路径：它**只**依据主管给的仲裁结论写话术（不自己判断该不该赔）
        rule_code = re.search(r"([AB]-\d)", seen)
        action = re.search(r"(不现金赔付；补偿 20 元运费券|无需赔付|现金赔付 50 元)", seen)
        chosen = action.group(1) if action else "不现金赔付；补偿 20 元运费券"
        body = {
            "不现金赔付；补偿 20 元运费券": "我们将为您补偿 20 元运费券，将于 24 小时内到账。",
            "无需赔付": "经核实本单无需赔付，感谢您的理解。",
            "现金赔付 50 元": "我们将为您办理现金赔付 50 元。",
        }[chosen]
        return as_mock_response(
            f"【工单 {TICKET.ticket_id} 回复】{TICKET.customer}您好，非常抱歉给您带来不便。\n"
            f"经核实：订单 {TICKET.order_id} 已于 2025-01-06 到达本市网点"
            f"（较承诺时间晚 24 小时），物流轨迹正常。\n"
            f"依据服务条款 {rule_code.group(1) if rule_code else 'B-2'}，{body}\n"
            f"感谢您的耐心等待，如有其他问题请随时联系我们。",
            self.model,
        )


class DataWorker(Worker):
    role, title = "data", "数据专家"

    def parse(self, text: str) -> WorkerReport:
        if "还需要" in text or "需要政策专家" in text:
            return WorkerReport(self.title, text, needs_help=True)
        facts = {}
        for key, label in (("order_id", "订单号"), ("status", "状态"),
                           ("carrier", "承运商"), ("eta", "承诺送达")):
            facts[label] = str(ORDER[key])
        m = re.search(r"延迟\s*(\d+)\s*小时", ORDER["trace"])
        facts["延迟小时数"] = m.group(1) if m else "?"
        facts["轨迹"] = "正常" if "轨迹正常" in ORDER["trace"] else "异常"
        # 只把**该下游知道**的字段放进 facts（内部备注故意不放进去）
        return WorkerReport(self.title, "订单数据已核实：状态已发货、延迟 24 小时、轨迹正常。", facts)


class PolicyWorker(Worker):
    role, title = "policy", "政策专家"

    def parse(self, text: str) -> WorkerReport:
        if "我需要" in text or "需要数据专家" in text:
            return WorkerReport(self.title, text, needs_help=True)
        m = re.search(r"([AB]-\d)", text)
        code = m.group(1) if m else ""
        rule = POLICY_BY_ID.get(code)
        return WorkerReport(
            self.title,
            f"结论：{rule.action if rule else '无法判定'}（依据条款 {code or '缺失'}）",
            facts={"条款": code, "处理方案": rule.action if rule else ""},
            evidence=code,
        )


class ReplyWorker(Worker):
    role, title = "reply", "文案专家"

    def parse(self, text: str) -> WorkerReport:
        return WorkerReport(self.title, text.strip())


# ===========================================================================
# 四、主管（Supervisor）：分解 → 分派 → 仲裁
# ===========================================================================


@dataclass
class SupervisorResult:
    ticket_id: str
    final_reply: str
    decision: str
    stop_reason: str                    # completed / round_limit
    rounds: int
    envelopes: list[Envelope]
    reports: dict[str, WorkerReport]
    llm_calls: int
    prompt_chars: int


HOLD_REPLY = (
    f"【工单 {TICKET.ticket_id} 回复】{TICKET.customer}您好，我们已收到您的反馈，"
    "正在为您核实处理，将在 24 小时内由专人回复您。"
)


class Supervisor:
    """主管：只做三件事 —— **分解、分派、仲裁**。

    它**不**参与专业推理（那是专家的事），也**不**把自己的上下文借给专家。
    它的上下文里只有短小的结构化汇报（WorkerReport），不放专家们的原始长文本。

    两条硬保护：
        max_rounds      专家之间"踢皮球"的轮数上限；
        arbitrate()     仲裁规则是**确定性的 if/else**，不是又一次模型调用。
    """

    def __init__(self, bus: MessageBus, data: Worker, policy: Worker, reply: Worker,
                 max_rounds: int = 3) -> None:
        self.bus = bus
        self.workers = {"data": data, "policy": policy, "reply": reply}
        self.max_rounds = max_rounds

    # ------------------------------------------------------------------
    def run(self, ticket: Ticket) -> SupervisorResult:
        reports: dict[str, WorkerReport] = {}
        rounds = 1
        stop_reason = "completed"

        # ---- ① 分派给数据专家（无依赖，可以先跑） ----
        self.bus.send(Envelope("supervisor", "data", "task",
                               f"请核实工单 {ticket.ticket_id}（订单 {ticket.order_id}）的物流事实。", rounds))
        reports["data"] = self.workers["data"].handle(
            f"工单 {ticket.ticket_id}：客户投诉订单 {ticket.order_id} 未按时送达。请给出该订单的客观事实。")
        self.bus.send(Envelope("data", "supervisor", "result", reports["data"].conclusion, rounds))

        # ---- ② 分派给政策专家：**只传它需要的事实**，不传原始对话 ----
        reports["policy"] = self._ask_policy(reports["data"], rounds)

        # ---- ③ 踢皮球保护：专家互相要材料时，主管在中间转达，但**有轮数上限** ----
        while reports["policy"].needs_help or reports["data"].needs_help:
            if rounds >= self.max_rounds:
                stop_reason = "round_limit"
                self.bus.send(Envelope("supervisor", "arbiter", "arbitration",
                                       f"达到轮数上限 {self.max_rounds}，强制结束讨论。", rounds))
                break
            rounds += 1
            if reports["policy"].needs_help:
                question, target = reports["policy"], "data"
            else:
                question, target = reports["data"], "policy"
            self.bus.send(Envelope("supervisor", target, "question",
                                   f"转达对方诉求：{question.conclusion}", rounds))
            reports[target] = self.workers[target].handle(question.conclusion)
            self.bus.send(Envelope(target, "supervisor", "result", reports[target].conclusion, rounds))
            if target == "data":
                reports["policy"] = self._ask_policy(reports["data"], rounds)

        # ---- ④ 仲裁（确定性规则，不是模型调用） ----
        decision, final_reply = self.arbitrate(reports)
        if decision.startswith("转人工"):
            # 拿不到可溯源的条款依据时，宁可转人工，也不猜一个结论给客户
            final_reply = HOLD_REPLY
        else:
            # ---- ⑤ 分派给文案专家：**只给结论** ----
            self.bus.send(Envelope("supervisor", "reply", "task",
                                   f"请依据仲裁结论撰写对客回复。{decision}", rounds))
            reports["reply"] = self.workers["reply"].handle(
                f"请为工单 {ticket.ticket_id} 撰写对客回复。\n"
                f"已确认事实：订单 {ticket.order_id} 延迟 24 小时，轨迹正常。\n"
                f"仲裁结论：{decision}\n"
                f"（只写对客话术，不要添加任何未确认的承诺，不要提及内部信息。）")
            self.bus.send(Envelope("reply", "supervisor", "result", "对客回复已生成", rounds))
            final_reply = reports["reply"].conclusion

        calls = sum(getattr(w.llm, "total_calls", 0) for w in self.workers.values())
        chars = sum(r.prompt_chars for r in reports.values())
        return SupervisorResult(
            ticket_id=ticket.ticket_id, final_reply=final_reply, decision=decision,
            stop_reason=stop_reason, rounds=rounds, envelopes=list(self.bus.log),
            reports=reports, llm_calls=calls, prompt_chars=chars,
        )

    # ------------------------------------------------------------------
    def _ask_policy(self, data_report: WorkerReport, rounds: int) -> WorkerReport:
        """把数据专家的事实**挑字段**后交给政策专家。

        注意 instruction 里出现的是 `facts`（结构化字典），而不是数据专家的原始输出。
        内部备注就死在数据专家的上下文里了 —— 这就是隔离带来的安全性。
        """
        facts_text = "\n".join(f"- {k}：{v}" for k, v in data_report.facts.items())
        self.bus.send(Envelope("supervisor", "policy", "task",
                               f"请依据条款判断本单处理方案。（随附事实 {len(data_report.facts)} 项）", rounds))
        report = self.workers["policy"].handle(
            f"请判断订单 {TICKET.order_id} 是否应赔付。\n已知事实：\n{facts_text}")
        self.bus.send(Envelope("policy", "supervisor", "result", report.conclusion, rounds))
        return report

    def arbitrate(self, reports: dict[str, WorkerReport]) -> tuple[str, str]:
        """仲裁：把专家结论合成一个可交付的决定。

        **仲裁必须是确定性的**（谁权威、冲突听谁的、缺依据怎么办）。
        如果连仲裁都交给模型，你就等于把"流程控制权"交给了概率 —— 那正是第 09 章要治的病。
        """
        policy = reports.get("policy")
        data = reports.get("data")
        if data is None or data.needs_help:
            return "转人工：事实缺失", HOLD_REPLY
        if policy is None or policy.needs_help or not policy.evidence:
            return "转人工：条款依据缺失（专家未达成一致）", HOLD_REPLY
        if policy.evidence not in POLICY_BY_ID:
            return f"转人工：依据 {policy.evidence} 不可溯源", HOLD_REPLY
        rule = POLICY_BY_ID[policy.evidence]
        return f"依据条款 {rule.code}：{rule.action}", ""


# ===========================================================================
# 五、验收器：对客回复的硬性合规检查（确定性）
# ===========================================================================
# 多智能体最容易"看起来热闹、结果不对"。所以一定要有一个**独立于所有专家**的验收器。
# 它由合规部门（而不是模型）定义，检查的是"能不能发出去"。


def verify_reply(text: str) -> list[str]:
    """返回不合规项列表（空 = 可对外发送）。"""
    issues: list[str] = []
    if TICKET.ticket_id not in text:
        issues.append("缺少工单号，无法归档")
    if "B-2" not in text:
        issues.append("未引用条款编号，处理依据不可溯源")
    if "50 元" in text or "现金" in text:
        issues.append("出现未经批准的现金赔付承诺（应按 B-2 补偿运费券）")
    if "运费券" not in text:
        issues.append("未给出正确的补偿方案（20 元运费券）")
    if "内部" in text or "勿外传" in text:
        issues.append("泄露内部备注（数据外泄事故）")
    return issues


# ===========================================================================
# 六、两个反面教材
# ===========================================================================
# 反面教材 A：单 Agent 什么都干 —— 便宜，但漏掉了条款里的例外。
# 反面教材 B：朴素多智能体（共享上下文 + 自由讨论）—— 贵，而且会互相污染。


class SingleAgentLLM(LLM):
    """一个"什么都懂一点"的万能 Agent。

    它的问题不是笨，而是**注意力被摊薄**：数据、条款、话术挤在一个提示词里，
    它记住了"延误要赔 50 元"这条显眼的规则，却漏掉了 B-2 的例外条件。
    这正是第 ① 节要暴露的失败模式。
    """

    name = "single-agent"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        return as_mock_response(
            f"【工单 {TICKET.ticket_id} 回复】{TICKET.customer}您好，非常抱歉。"
            f"经核实订单 {TICKET.order_id} 存在延误，按赔付规则我们将在 3 个工作日内现金赔付 50 元。"
            f"（{ORDER['internal_note']}）",
            self.model,
        )


SHARED_SYSTEM = "你们是一个客服团队，共用一个对话记录。请各自发言，自由讨论如何处理工单。"


class SharedScratchpadLLM(LLM):
    """朴素多智能体的"万能专家"：所有角色共用同一个大上下文。

    它的每一次调用都要把**全部历史**重读一遍 —— 而且它会照抄上下文里的结论。
    两条真实的坏结果都会在这里出现：
        成本：提示词字符数随轮数快速膨胀；
        污染：早期那条错误草稿（"现金赔付 50 元"）变成了所有人的"共识"。
    """

    name = "shared-scratchpad"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        seen = "\n".join(m.content for m in messages)
        speaker = messages[-1].content if messages else ""
        if "数据专家" in speaker:
            text = (f"[数据专家] 订单 {ORDER['order_id']} 状态已发货，延迟 24 小时，轨迹正常。"
                    f"{ORDER['internal_note']}")
        elif "政策专家" in speaker:
            # 被上下文里的既有结论锚定：它顺着草稿说，而不是回去查条款
            text = "[政策专家] 同意草稿的判断，本单应现金赔付 50 元。"
        else:
            text = (f"[文案专家] 【工单 {TICKET.ticket_id} 回复】{TICKET.customer}您好，"
                    f"我们将现金赔付 50 元。{ORDER['internal_note']}")
        return as_mock_response(text, self.model)


def run_single_agent(ticket: Ticket) -> tuple[str, int, int]:
    """反面教材 A：一个 Agent 一把梭。返回 (回复, 调用次数, 提示词字符数)。"""
    llm = SingleAgentLLM()
    messages = [
        Message.system("你是客服 Agent，请自行查询订单、判断赔付、撰写回复，一次完成。"),
        Message.user(f"工单 {ticket.ticket_id}：{ticket.complaint}\n"
                     f"订单数据：{ORDER}\n赔付条款：{[r.code + r.action for r in POLICY_RULES]}"),
    ]
    resp = llm.complete(messages)
    return resp.text, llm.total_calls, sum(len(m.content) for m in messages)


def run_shared_context(ticket: Ticket, rounds: int = 2) -> tuple[str, list[int]]:
    """反面教材 B：共享上下文 + 自由讨论。

    返回 (最终回复, 每次模型调用时的上下文总字符数)。
    """
    llm = SharedScratchpadLLM()
    # 共享草稿纸上先躺着一条"早期草稿"——这是真实团队里最常见的信息污染源
    transcript: list[Message] = [
        Message.system(SHARED_SYSTEM),
        Message.user(f"工单 {ticket.ticket_id}：{ticket.complaint}"),
        Message.assistant("[早期草稿] 结论：按 A-2 现金赔付 50 元。（待确认）"),
    ]
    sizes: list[int] = []
    final = ""
    for r in range(1, rounds + 1):
        for speaker in ("数据专家", "政策专家", "文案专家"):
            transcript.append(Message.user(f"第 {r} 轮，请 {speaker} 发言。"))
            sizes.append(sum(len(m.content) for m in transcript))   # 它这次读了多少字
            resp = llm.complete(transcript)
            transcript.append(Message.assistant(resp.text))
            if speaker == "文案专家":
                final = resp.text
    return final, sizes


# ===========================================================================
# 第 ① 节：一个 Agent 全干
# ===========================================================================


def demo_single_agent() -> str:
    section("单 Agent 一把梭：便宜，但漏掉了条款里的例外", "①")

    reply, calls, chars = run_single_agent(TICKET)
    code(reply, indent=4)
    print()
    issues = verify_reply(reply)
    kv("模型调用次数", calls)
    kv("提示词字符数", chars)
    kv("合规检查", "通过" if not issues else f"不通过（{len(issues)} 项）")
    for i in issues:
        bullet(i, indent=4)
    print()
    warn("它记住了「延误赔 50 元」，漏掉了 B-2 的例外：轨迹正常且延迟 ≤ 48 小时只补运费券。")
    note("失败原因不是模型笨，而是**数据、条款、话术全挤在一个上下文里**，注意力被摊薄了。")
    note("于是我们想到：能不能让懂条款的人专门管条款？—— 这就是分工的动机。")
    return reply


# ===========================================================================
# 第 ② 节：主管 + 三个专家
# ===========================================================================


def build_team(stubborn: bool = False, max_rounds: int = 3) -> tuple[MessageBus, "Supervisor"]:
    """一行组装一支团队，方便各小节只改一个变量做对照。"""
    bus = MessageBus()
    return bus, Supervisor(
        bus=bus,
        data=DataWorker(DataAnalystLLM(stubborn=stubborn), "你是数据专家，只负责查证订单与物流事实，不做判断。"),
        policy=PolicyWorker(PolicyExpertLLM(stubborn=stubborn),
                            "你是赔付政策专家，只负责条款匹配。条款：\n"
                            + "\n".join(f"{r.code}｜{r.match}｜{r.action}" for r in POLICY_RULES)),
        reply=ReplyWorker(ReplyWriterLLM(),
                          "你是客服文案专家，只负责把已确认的结论写成对客户的话术。"
                          "严禁添加未确认的承诺，严禁提及任何内部信息。"),
        max_rounds=max_rounds,
    )


def demo_team() -> SupervisorResult:
    section("主管 + 三个专家：分工、分派、仲裁", "②")

    bus, supervisor = build_team()
    result = supervisor.run(TICKET)

    note("消息总线上的完整通信记录（谁在什么时候把什么告诉了谁）：")
    for env in result.envelopes:
        print(f"     {env.render()[:96]}")
    print()
    code(result.final_reply, indent=4)
    print()
    issues = verify_reply(result.final_reply)
    kv("主管的仲裁结论", result.decision)
    kv("轮数", result.rounds)
    kv("停机原因", result.stop_reason)
    kv("消息条数", len(result.envelopes))
    kv("模型调用次数", result.llm_calls)
    kv("专家上下文合计字符", result.prompt_chars)
    kv("合规检查", "通过" if not issues else f"不通过（{len(issues)} 项）")
    print()
    ok("同一条工单，多了两次调用，换来了正确的条款引用（B-2）和干净的对外话术。")
    note("注意主管**没有**把数据专家的原文转发给政策专家 —— 只转发了结构化事实。")
    return result


# ===========================================================================
# 第 ③ 节：上下文隔离到底隔离了什么
# ===========================================================================


def demo_isolation() -> SupervisorResult:
    section("上下文隔离：每个专家只看自己该看的", "③")

    bus, supervisor = build_team()
    result = supervisor.run(TICKET)

    for role in ("data", "policy", "reply"):
        w = supervisor.workers[role]
        kv(f"{w.title} · 看了多少字", w.seen_chars)
        for ctx in w.contexts:
            preview = ctx.replace("\n", " ")[:70]
            print(f"        [{w.title}] {preview}…")
    print()

    reply_ctx = "\n".join(supervisor.workers["reply"].contexts)
    policy_ctx = "\n".join(supervisor.workers["policy"].contexts)
    kv("文案专家是否看到内部备注", "是（隔离失败）" if "内部备注" in reply_ctx else "否 ✅")
    kv("文案专家是否看到订单原文", "是" if "运单号" in reply_ctx else "否 ✅")
    kv("政策专家是否看到内部备注", "是" if "内部备注" in policy_ctx else "否 ✅")
    kv("最终回复是否泄露内部信息", "是" if "内部" in result.final_reply else "否 ✅")
    print()
    bullet("数据专家知道：订单原始数据（含内部备注）")
    bullet("政策专家知道：条款表 + 结构化事实（不含内部备注）")
    bullet("文案专家知道：仲裁结论 + 该说的事实（不含条款表、不含内部备注）")
    print()
    ok("隔离 = 每个专家只拿到「完成自己那一小块」所需的最小信息。")
    warn("顺带一提：隔离也是**成本控制**手段 —— 上下文越小，每次调用越便宜（第 12 章细讲）。")
    return result


# ===========================================================================
# 第 ④ 节：反面教材 —— 共享上下文 + 自由讨论
# ===========================================================================


def demo_shared_context() -> tuple[str, int, "SupervisorResult"]:
    section("反面教材：共享上下文 + 自由讨论会怎样", "④")

    shared_final, sizes = run_shared_context(TICKET, rounds=2)
    print("  共享上下文版的模型调用（每次调用要重读的历史）：")
    for i, s in enumerate(sizes, 1):
        print(f"     第 {i} 次调用：上下文 {s} 字符")
    print()
    code(shared_final, indent=4)
    print()

    bus, supervisor = build_team()
    isolated = supervisor.run(TICKET)

    shared_chars = sum(sizes)
    kv("共享版 · 模型调用次数", len(sizes))
    kv("共享版 · 提示词总字符", shared_chars)
    kv("隔离版 · 模型调用次数", isolated.llm_calls)
    kv("隔离版 · 提示词总字符", isolated.prompt_chars)
    kv("成本倍数", f"{shared_chars / max(isolated.prompt_chars, 1):.2f} 倍")
    kv("共享版 · 合规检查", f"不通过（{len(verify_reply(shared_final))} 项）")
    for i in verify_reply(shared_final):
        bullet(i, indent=4)
    print()
    warn("共享上下文里，一条「早期草稿」变成了所有人的共识：政策专家不再查条款，直接附和。")
    warn("内部备注也被文案专家照抄进了对客回复 —— 这已经不是效果问题，是事故。")
    note("共享的不是「记忆」，是「偏见」：谁先说话，谁就定义了讨论的起点。")
    return shared_final, shared_chars, isolated


# ===========================================================================
# 第 ⑤ 节：踢皮球与轮数上限
# ===========================================================================


def demo_round_limit() -> SupervisorResult:
    section("踢皮球：两个专家互相要材料，谁来喊停？", "⑤")

    bus, supervisor = build_team(stubborn=True, max_rounds=3)
    result = supervisor.run(TICKET)

    for env in result.envelopes:
        print(f"     {env.render()[:96]}")
    print()
    kv("轮数", f"{result.rounds}（上限 {supervisor.max_rounds}）")
    kv("停机原因", result.stop_reason)
    kv("主管的仲裁结论", result.decision)
    kv("最终交付", "转人工安抚话术（不猜结论）")
    kv("模型调用次数", result.llm_calls)
    print()
    code(result.final_reply, indent=4)
    print()
    ok("max_rounds 生效：讨论在第 3 轮被强制结束，没有无限踢皮球。")
    note("注意停机后的行为：主管**如实交付**一个保守结果（转人工），而不是硬编一个结论。")
    warn("没有轮数上限的多智能体 = 一张会自动续费的账单。上限不是可选项。")
    return result


# ===========================================================================
# 第 ⑥ 节：三个方案对比
# ===========================================================================


def demo_compare() -> None:
    section("三个方案对比：多智能体不是自动更好", "⑥")

    single_reply, single_calls, single_chars = run_single_agent(TICKET)
    shared_reply, sizes = run_shared_context(TICKET, rounds=2)
    bus, supervisor = build_team()
    team = supervisor.run(TICKET)

    rows = [
        ("单 Agent 一把梭", single_calls, single_chars,
         "漏条款例外", len(verify_reply(single_reply))),
        ("共享上下文讨论", len(sizes), sum(sizes),
         "结论被污染 + 泄密", len(verify_reply(shared_reply))),
        ("主管 + 隔离专家", team.llm_calls, team.prompt_chars,
         team.decision[:14], len(verify_reply(team.final_reply))),
    ]
    print(f"  {'方案':<18}{'调用':>4}{'提示字符':>9}   结论 / 合规问题")
    print("  " + "-" * 64)
    for name, calls, chars, decision, bad in rows:
        flag = "✅" if bad == 0 else f"❌{bad} 项"
        print(f"  {name:<18}{calls:>4}{chars:>9}   {decision:<20}{flag}")
    print()
    bullet("单 Agent：最便宜，但专业判断容易出错 —— 先试它，别一上来就上多智能体。")
    bullet("共享上下文：最贵，而且会互相污染 —— 除非任务真的需要「头脑风暴」。")
    bullet("主管 + 隔离专家：调用数居中，但结论可溯源、可审计、可局部替换（换个政策专家即可）。")
    print()
    ok("选型原则：**先单 Agent；只有当子任务需要不同知识、且上下文能切干净时，才分工。**")


# ===========================================================================
# 第 ⑦ 节：一句话本质
# ===========================================================================


def demo_essence() -> None:
    section("收口：一句话本质", "⑦")
    essence(
        "多智能体 = 角色分工 + 消息传递 + 结果仲裁\n"
        "\n"
        "  收益来自：专业化（各管一摊） + 上下文隔离（各看一份）\n"
        "  代价来自：通信开销（N 倍调用） + 不可控性（谁说了算？）\n"
        "\n"
        "三条工程铁律：\n"
        "  · 传「结论」，不传「上下文」—— 隔离是可靠性的结构性保证\n"
        "  · 仲裁必须是确定性的 if/else，不能是又一次模型调用\n"
        "  · 必须设轮数上限，否则踢皮球会一直踢到你的账单上\n"
        "\n"
        "先问一句：这个任务，一个 Agent 真的干不了吗？"
    )


# ===========================================================================
# 验收标准
# ===========================================================================


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（由 scripts/run_all_checks.py 调用）。不打印、确定性、< 1 秒。"""
    results: list[tuple[str, bool, str]] = []

    bus, supervisor = build_team()
    team = supervisor.run(TICKET)

    # ---------- 验收 1：主管能把任务分给正确的专家并汇总 ----------
    tasks = [e for e in team.envelopes if e.topic == "task"]
    results.append(check_that(
        "主管把任务分派给了三个正确的专家",
        [e.recipient for e in tasks] == ["data", "policy", "reply"],
        f"实际 {[e.recipient for e in tasks]}"))
    results.append(check_that(
        "专家结论回到主管并被汇总（消息方向正确）",
        {e.recipient for e in team.envelopes if e.topic == "result"} == {"supervisor"}
        and len([e for e in team.envelopes if e.topic == "result"]) == 3,
        f"{len([e for e in team.envelopes if e.topic == 'result'])} 条 result 消息"))
    results.append(check_that(
        "最终交付可对外发送（结论正确 + 引用条款 + 无越权承诺）",
        not verify_reply(team.final_reply) and "B-2" in team.final_reply and "运费券" in team.final_reply,
        team.decision))
    results.append(check_that(
        "仲裁是确定性规则（不额外调用模型）",
        team.llm_calls == 3 and team.decision == "依据条款 B-2：不现金赔付；补偿 20 元运费券",
        f"{team.llm_calls} 次调用 / {team.decision[:24]}"))

    # ---------- 验收 2：专家之间上下文隔离 ----------
    reply_ctx = "\n".join(supervisor.workers["reply"].contexts)
    policy_ctx = "\n".join(supervisor.workers["policy"].contexts)
    results.append(check_that(
        "隔离：文案专家看不到内部备注与订单原文",
        "内部备注" not in reply_ctx and "运单号" not in reply_ctx,
        f"文案专家上下文 {len(reply_ctx)} 字符"))
    results.append(check_that(
        "隔离：政策专家只拿到结构化事实（不含内部备注）",
        "内部备注" not in policy_ctx and "延迟小时数" in policy_ctx,
        "facts 字段被挑选后传递"))
    results.append(check_that(
        "隔离：数据专家的原始长文本没有被广播给全队",
        "内部备注" in "".join(supervisor.workers["data"].outputs)
        and "内部备注" not in reply_ctx and "内部备注" not in policy_ctx,
        "内部备注留在数据专家自己的上下文/输出里，未进入他人工上下文"))
    results.append(check_that(
        "最终回复不泄露内部信息",
        "内部" not in team.final_reply and "勿外传" not in team.final_reply,
        team.final_reply[:36]))

    # ---------- 验收 3：轮数上限，避免踢皮球式无限对话 ----------
    bus2, stubborn = build_team(stubborn=True, max_rounds=3)
    stuck = stubborn.run(TICKET)
    results.append(check_that(
        "踢皮球场景被轮数上限拦住（不会无限对话）",
        stuck.stop_reason == "round_limit" and stuck.rounds == 3,
        f"{stuck.rounds} 轮 / {stuck.stop_reason}"))
    results.append(check_that(
        "踢皮球场景消息数有界（不随讨论无限增长）",
        # 4 条开场消息 + 每轮最多 4 条往返 + 1 条强制仲裁 = 上限 17，与实际内容无关
        len(stuck.envelopes) <= 4 + 4 * stubborn.max_rounds + 1,
        f"{len(stuck.envelopes)} 条消息（上限 {4 + 4 * stubborn.max_rounds + 1}）"))
    results.append(check_that(
        "触顶后主管给出保守兜底（转人工），不硬编结论",
        stuck.decision.startswith("转人工") and stuck.final_reply == HOLD_REPLY,
        stuck.decision))

    # ---------- 验收 4：共享上下文的失败模式（用于说明代价）----------
    shared_final, sizes = run_shared_context(TICKET, rounds=2)
    results.append(check_that(
        "共享上下文版：结论被早期草稿污染",
        "现金赔付 50 元" in shared_final and "B-2" not in shared_final,
        shared_final[:44]))
    results.append(check_that(
        "共享上下文版：内部信息外泄 + 合规不通过",
        "内部" in shared_final and len(verify_reply(shared_final)) >= 2,
        f"{len(verify_reply(shared_final))} 项不合规"))
    results.append(check_that(
        "共享上下文版：上下文随轮次膨胀（成本更高）",
        len(sizes) == 6 and sizes[-1] > sizes[0] * 2 and sum(sizes) > team.prompt_chars,
        f"共享 {sum(sizes)} 字符 vs 隔离 {team.prompt_chars} 字符"))

    # ---------- 验收 5：单 Agent 基线对比 ----------
    single_reply, single_calls, _single_chars = run_single_agent(TICKET)
    results.append(check_that(
        "单 Agent 基线：调用最少但专业判断出错",
        single_calls == 1 and len(verify_reply(single_reply)) >= 1,
        f"{single_calls} 次调用 / {len(verify_reply(single_reply))} 项不合规"))
    results.append(check_that(
        "多智能体并非自动更好：隔离版确实通过验证",
        not verify_reply(team.final_reply) and verify_reply(single_reply),
        "同一条工单：单 Agent 不通过，主管+专家通过"))

    # ---------- 验收 6：可复现 ----------
    bus3, sup3 = build_team()
    again = sup3.run(TICKET)
    results.append(check_that(
        "同一输入两次运行结果完全一致（可复现）",
        again.final_reply == team.final_reply and again.llm_calls == team.llm_calls,
        f"{again.llm_calls} 次调用 / {len(again.envelopes)} 条消息"))

    return results


# ===========================================================================
# 入口
# ===========================================================================

SECTIONS = {
    "1": ("单 Agent 一把梭（基线）", demo_single_agent),
    "2": ("主管 + 三个专家", demo_team),
    "3": ("上下文隔离", demo_isolation),
    "4": ("反面教材：共享上下文", demo_shared_context),
    "5": ("踢皮球与轮数上限", demo_round_limit),
    "6": ("三个方案对比", demo_compare),
    "7": ("一句话本质", demo_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 08 章 · 多智能体协作")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 08 章 · 多智能体协作")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 08 章", run_checks()) else 1

    banner("第 08 章 · 多智能体协作",
           "目标：搭一套主管+专家架构，并亲手看清它的代价")

    chosen = [args.section] if args.section else sorted(SECTIONS)
    for key in chosen:
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 08 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
