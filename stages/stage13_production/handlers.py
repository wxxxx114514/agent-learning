"""带副作用的工具：用来演示"重复提交"为什么是生产事故。

------------------------------------------------------------
一句话本质：
    幂等不是"重试时不要报错"，而是**重试时副作用不发生第二次**。
    所以幂等必须做在**副作用那一层**，而不是在 API 层糊一层"看起来没报错"。
------------------------------------------------------------

本模块给出四个非常普通、非常真实的工具：

    lookup_order    只读查询（重复执行无害，但很浪费 —— 真实里是一次 200ms 的 RPC）
    archive_order   归档订单（写操作：重复执行会覆盖审计记录，真实里是写数据库）
    charge_user     扣款（**重复执行 = 用户被扣两次 = P0 事故**）
    count_words     纯本地计算（不碰外部世界，天然幂等）

设计要点：把"业务副作用"和"执行次数"分开统计。
    calls       被调用了几次   （便宜，只反映流量）
    applied     真正生效几次   （贵，反映真实世界被改了几次）
    合格的生产实现应该让 calls 可以很大，而 applied 永远等于"业务上应该发生的次数"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.mock_llm import RuleBasedLLM
from core.tool import ToolRegistry


# ===========================================================================
# 一、统计器
# ===========================================================================
class Counter:
    """极简计数器（有序，便于终端里稳定输出）。"""

    def __init__(self) -> None:
        self._data: dict[str, int] = {}

    def incr(self, key: str, n: int = 1) -> int:
        self._data[key] = self._data.get(key, 0) + n
        return self._data[key]

    def get(self, key: str) -> int:
        return self._data.get(key, 0)

    def total(self) -> int:
        return sum(self._data.values())

    def as_dict(self) -> dict[str, int]:
        return dict(self._data)


# 全局统计：工具是"外部系统"，进程内共享（真实里它在数据库那边）
STATS = {
    "lookup_calls": Counter(),      # 各订单被查了几次
    "archive_applied": Counter(),   # 归档真正生效的次数（★ 副作用次数）
    "notify_calls": Counter(),      # 通知接口被调用了几次（含被幂等挡回的）
    "notify_applied": Counter(),    # 通知真正发出去的次数（★ 副作用次数）
    "charge_calls": Counter(),      # 扣款接口被调用了几次（含被幂等挡回的）
    "charge_applied": Counter(),    # 真正扣款成功的次数（★ 这个才是钱）
    "charge_amount": Counter(),     # 累计扣款金额（分）
}


def reset_stats() -> None:
    for c in STATS.values():
        c._data.clear()


def reset_world(ledger: SideEffectLedger | None = None) -> None:
    """把"外部世界"恢复干净：计数清零 + 账本清空。

    为什么要专门有这个函数？
        因为幂等账本、订单表、计数器模拟的是**进程外部的状态**，
        它们在多次实验之间会互相污染 —— 一次"已经收过款了"的残留
        会让下一次实验的输出莫名其妙。
        生产里的对应动作是"测试环境数据复位"，而它之所以必须有，
        恰恰证明了这条最重要的工程事实：
        **副作用是不可逆的，只有幂等键能让重复执行变得安全。**
    """
    reset_stats()
    led = ledger if ledger is not None else LEDGER
    led.entries.clear()
    led.seq = 0
    led.hits = 0
    led.applied = 0


# ===========================================================================
# 二、副作用账本：幂等的落点
# ===========================================================================
@dataclass
class SideEffectLedger:
    """一张"幂等账本"：key → 副作用结果。

    真实系统里它就是数据库里带 **唯一索引** 的一张表：
        CREATE TABLE charges (
            idem_key TEXT PRIMARY KEY,     -- ← 唯一索引是幂等的最终保证
            user_id  TEXT NOT NULL,
            cents    INTEGER NOT NULL,
            seq      INTEGER NOT NULL
        );
    为什么强调唯一索引？因为"先 SELECT 再 INSERT"在并发下会双双通过检查
    （check-then-act 竞态），只有数据库的唯一约束能真正兜住。
    教学里我们用单线程字典模拟那张表。

    注意 key 里带了 `scope`（业务命名空间）：
        归档订单和扣款可能碰巧算出同样的指纹，
        加上作用域前缀就不会互相误伤 —— 这是幂等键设计里最容易漏的一点。
    """

    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    seq: int = 0
    hits: int = 0             # 被幂等挡回（没有产生第二次副作用）的次数
    applied: int = 0          # 真正生效的次数

    # ---- 天真做法：每次调用都真的执行 ----
    def apply_naive(self, scope: str, subject: str) -> dict[str, Any]:
        """**没有幂等键的版本** —— demo 第 3 节要展示它怎么造成重复扣款。"""
        self.seq += 1
        self.applied += 1
        STATS["charge_calls"].incr(subject)
        STATS["charge_applied"].incr(subject)
        return {"charged": True, "seq": self.seq, "user_id": subject,
                "idempotent": False, "replayed": False}

    # ---- 正确做法：先查账本，命中就返回第一次的结果 ----
    def apply_once(self, key: str, scope: str, subject: str, cents: int = 0) -> dict[str, Any]:
        """**同一个 key，无论调用多少次，只产生一次副作用。**

        注意返回值的区别：第二次返回的是**第一次的原始结果 + replayed 标记**。
        为什么必须返回原始结果而不是重新算一个？
            因为调用方（Agent）会把它写进上下文交给模型。
            如果第二次返回一个不一样的东西，模型就会以为"又扣了一笔"，
            进而对用户说"已为你扣款两次" —— 副作用没错，**叙述错了**，
            用户照样投诉。幂等要幂等到"用户体验"这一层。
        """
        full_key = f"{scope}:{key}"
        STATS["charge_calls"].incr(subject)
        found = self.entries.get(full_key)
        if found is not None:
            self.hits += 1
            return {**found, "replayed": True, "idempotent": True}
        self.seq += 1
        self.applied += 1
        STATS["charge_applied"].incr(subject)
        if cents:
            STATS["charge_amount"].incr(subject, cents)
        record = {"ok": True, "seq": self.seq, "scope": scope, "subject": subject,
                  "cents": cents}
        self.entries[full_key] = record
        return {**record, "replayed": False, "idempotent": True}


# 进程级共享的单例（真实里是数据库/支付网关）
LEDGER = SideEffectLedger()


# ===========================================================================
# 三、工具集
# ===========================================================================
FAKE_ORDERS = {
    "A1001": {"status": "已发货", "carrier": "顺丰", "tracking": "SF1234567890",
              "eta": "2025-01-05"},
    "A1002": {"status": "待付款", "carrier": None, "tracking": None, "eta": None},
    "B2043": {"status": "运输中", "carrier": "中通", "tracking": "ZT9988776655",
              "eta": "2025-01-03"},
}


def demo_tools(ledger: SideEffectLedger | None = None) -> ToolRegistry:
    """构建本章的演示工具集。"""
    led = ledger if ledger is not None else LEDGER
    reg = ToolRegistry()

    @reg.tool(
        "lookup_order",
        "根据订单号查询订单状态、承运商和预计送达时间。订单号形如 A1001。",
        {"type": "object",
         "properties": {"order_id": {"type": "string", "description": "订单号，例如 A1001"}},
         "required": ["order_id"], "additionalProperties": False},
        tags=["data"],
    )
    def lookup_order(order_id: str) -> dict[str, Any]:
        """查订单（模拟一次 200ms 的 RPC 调用）。**只读，天然幂等。**"""
        key = order_id.upper()
        STATS["lookup_calls"].incr(key)
        if key not in FAKE_ORDERS:
            raise ValueError(f"订单 {key} 不存在。已知示例订单：{sorted(FAKE_ORDERS)}")
        return {"order_id": key, **FAKE_ORDERS[key]}

    @reg.tool(
        "archive_order",
        "把订单标记为已归档（**有副作用的写操作**）。幂等键由服务端按订单号推导。",
        {"type": "object",
         "properties": {"order_id": {"type": "string", "description": "订单号，例如 A1001"}},
         "required": ["order_id"], "additionalProperties": False},
        tags=["data", "write"],
    )
    def archive_order(order_id: str) -> dict[str, Any]:
        """归档订单。

        ★ 这里演示的是**服务端推导幂等键**：归档这件事的业务语义就是"这个订单归档过没有"，
        所以 key 直接取 order_id —— 同一个订单归档一万次，账本里也只有一条。
        对比下面 charge_user 用的是**客户端提供的键**，两者适用场景不同：
            服务端推导：操作本身天然有业务唯一性（归档某订单、初始化某账号）
            客户端提供：操作没有天然唯一性，只有调用方知道"这次算不算新的一次"（扣款、下单）
        """
        key = order_id.upper()
        res = led.apply_once(key, "archive", key)
        if not res["replayed"]:
            STATS["archive_applied"].incr(key)
        return {**res, "order_id": key,
                "落库": "已归档" if not res["replayed"] else "此前已归档（未重复写入）"}

    @reg.tool(
        "charge_user",
        "给指定用户扣款（单位：分）。**有副作用**，调用时必须带上幂等键，重复调用不会重复扣款。",
        {"type": "object",
         "properties": {
             "user_id": {"type": "string", "description": "用户 ID，例如 u_42"},
             "cents": {"type": "integer", "description": "扣款金额（分）", "minimum": 1},
             "idempotency_key": {
                 "type": "string",
                 "description": "幂等键。由调用方（客户端或服务端按业务意图）生成，"
                                "同一个键重复调用只会扣一次款。",
                 "minLength": 4,
             },
         },
         "required": ["user_id", "cents", "idempotency_key"],
         "additionalProperties": False},
        tags=["payment"],
    )
    def charge_user(user_id: str, cents: int, idempotency_key: str) -> dict[str, Any]:
        """扣款。**幂等键是这个工具的必填参数** —— 这是本章最关键的几行代码。

        为什么把幂等键做成"工具参数"而不是在函数内部自己算？
            因为只有调用方知道"这次操作在业务上等价于哪一次"。
            函数内部只能看到 user_id 和 cents，它无从判断
            "用户是真的要再充一次，还是网络重发"。
            → 这条经验可以推广：**幂等键必须由掌握业务语义的那一层生成**。
        """
        if len(str(idempotency_key).strip()) < 4:
            # 弱键比没有键更危险：它给人"已经幂等了"的错觉。
            raise ValueError("幂等键太短，拒绝执行（弱幂等键 = 假安全感）")
        return led.apply_once(str(idempotency_key), "charge", user_id, cents)

    @reg.tool(
        "notify_user",
        "给用户发送一条订单通知（**有副作用的写操作**）。同一个订单只会通知一次。",
        {"type": "object",
         "properties": {"order_id": {"type": "string", "description": "订单号，例如 A1001"},
                        "message": {"type": "string", "description": "通知内容", "minLength": 1}},
         "required": ["order_id", "message"], "additionalProperties": False},
        tags=["notify", "write"],
    )
    def notify_user(order_id: str, message: str) -> dict[str, Any]:
        """发通知。同样用"业务语义推导幂等键"的做法。"""
        key = order_id.upper()
        STATS["notify_calls"].incr(key)
        res = led.apply_once(key, "notify", key)
        if not res["replayed"]:
            STATS["notify_applied"].incr(key)
        return {"order_id": key, "message": message, "replayed": res["replayed"],
                "seq": res["seq"],
                "发送结果": "已发送" if not res["replayed"] else "此前已发送（未重复发送）"}

    @reg.tool(
        "count_words",
        "统计一段文本的字符数、中文字数、英文单词数。纯本地计算，没有副作用。",
        {"type": "object",
         "properties": {"text": {"type": "string", "description": "要统计的文本",
                                "minLength": 1}},
         "required": ["text"], "additionalProperties": False},
        tags=["text"],
    )
    def count_words(text: str) -> dict[str, Any]:
        """统计文本长度。"""
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        return {"总字符数": len(text), "中文字数": cjk,
                "英文单词数": len(re.findall(r"[A-Za-z]+", text))}

    return reg


# ===========================================================================
# 四、演示用模型
# ===========================================================================
RE_ORDER = re.compile(r"([A-Za-z]{1,2}\d{3,})")
RE_CHARGE = re.compile(r"(u[_\-]?\w+)[^\d]{0,12}(\d+)")


class ProductionLLM(RuleBasedLLM):
    """一个**确定性**的假模型：会调用工具、会失败、会根据版本给出不同答案。

    为什么要自己写假模型，而不是直接用真实模型？
        因为本章要演示的是**运行时行为**（崩溃、超时、重复提交、灰度），
        这些实验必须 100% 可复现：模型在第几步做什么、什么时候失败、
        失败的是哪个版本，都得由我们说了算。真实模型是随机的，做不到。
        （这本身就是一条工程经验：**故障演练必须用可注入的假依赖**。）

    三档可控行为：
        plan_steps   指定要依次调用的工具（默认按任务文本推导）
        fail_at_step 到第几步开始抛异常（模拟模型服务 500）
        force_charge 强制发起一笔扣款（模拟"给用户扣款"这类业务动作）
    """

    name = "production-demo"

    def __init__(self, *, plan_steps: list[tuple[str, dict[str, Any]]] | None = None,
                 force_charge: tuple[str, int] | None = None,
                 request_id: str = "", idempotency_key: str = "",
                 charge_mode: str = "safe", fail_at_step: int | None = None,
                 model: str = "mock-prod") -> None:
        super().__init__(model=model)
        self.plan_steps = list(plan_steps or [])
        self.force_charge = force_charge
        self.request_id = request_id
        self.idempotency_key = idempotency_key
        # "safe"   = 用客户端/服务端的幂等键（正确做法）
        # "narrow" = 用本次请求 ID（天真做法：重试换了 request_id 就失效）
        self.charge_mode = charge_mode
        self.fail_at_step = fail_at_step
        self.step_seen = 0
        # 本次调用收到的会话（用于"从会话里推断已完成动作"）。
        self._messages: list = []
        # 本次调用内累积的工具事实（工具名, 人读摘要）。
        # 注意它只是"渲染缓存"：真相在会话里，见 _done_actions 的注释。
        self.results: list[tuple[str, str]] = []

    def _complete(self, messages, **kwargs: Any):
        # 记住本次拿到的会话 —— 下面的"已完成动作"必须从这里读，而不是从内存读。
        self._messages = list(messages)
        return super()._complete(messages, **kwargs)

    # ---- 计划：本章的"任务分解"由它决定 ---------------------------------
    def plan(self, user_msg: str) -> list[tuple[str, dict[str, Any]]]:
        if self.plan_steps:
            return list(self.plan_steps)
        if self.force_charge is not None:
            uid, cents = self.force_charge
            key = self.idempotency_key if self.charge_mode == "safe" else self.request_id
            return [("charge_user",
                     {"user_id": uid, "cents": cents, "idempotency_key": key or uid})]
        return self._plan_from_task(user_msg)

    @staticmethod
    def _plan_from_task(user_msg: str) -> list[tuple[str, dict[str, Any]]]:
        """把任务文本翻译成"该按顺序做哪几件事"。"""
        found = RE_ORDER.search(user_msg)
        oid = found.group(1).upper() if found else ""
        steps: list[tuple[str, dict[str, Any]]] = []
        if oid:
            steps.append(("lookup_order", {"order_id": oid}))
            if "归档" in user_msg:
                steps.append(("archive_order", {"order_id": oid}))
        if "字数" in user_msg:
            steps.append(("count_words", {"text": "生产化部署"}))
        if "通知" in user_msg and oid:
            steps.append(("notify_user",
                          {"order_id": oid, "message": f"订单 {oid} 已处理完成"}))
        return steps

    # ---- ★ 让模型"从会话里读事实"，而不是靠自己的内存 --------------------
    @staticmethod
    def _done_actions(messages) -> set[str]:
        """已完成动作**只能从会话里推断** —— 这是本章最重要的设计之一。

        为什么不能只维护一个 `self.seen_actions` 集合？
            因为那个集合活在**进程内存**里。进程一死（我们的假崩溃、真实的
            OOM Killer、Pod 被驱逐），新进程里它是空的 —— 于是模型从头再做一遍，
            "恢复"就变成了"重放事故"。

            真实生产里这条更硬：Worker 是**无状态**的，同一个用户的请求
            可能被负载均衡打到任何一台机器上。所以"我已经做过什么"这件事，
            唯一的权威来源只能是**持久化的会话/状态**，不能是进程内存。
            （这正是"有状态长任务 + 无状态 Worker"必须靠检查点弥合的原因。）

        判据用**因果依赖**而不是单纯罗列：能归档说明查询早就做完了，
        所以看到 archive_order 的结果，就要同时标记 lookup_order 已完成。
        """
        done: set[str] = set()
        for msg in messages:
            if msg.role != "tool":
                continue
            if not msg.metadata.get("ok", True):
                # 失败的工具调用**不算"做过"**：预算里不许把它当成已完成，
                # 否则模型会以为"这件事处理过了"而直接跳过（静默漏做）。
                continue
            if msg.name == "archive_order":
                # 能归档 → 说明查询早就做完了（因果依赖，不是简单罗列）
                done.update({"lookup_order", "archive_order"})
            elif msg.name == "notify_user":
                # 能通知 → 说明查询和归档都已完成
                done.update({"lookup_order", "archive_order", "notify_user"})
            elif msg.name:
                done.add(msg.name)
        return done

    def _resume_note(self, messages) -> str:
        """如果这是"续跑"，在 Thought 里说明白 —— 教学输出靠它一眼可见。"""
        done = self._done_actions(messages)
        if not done:
            return ""
        return f"（会话里已有 {sorted(done)} 的结果，只做剩下的）"

    # ---- 第一拍 -------------------------------------------------------
    def _before_tools(self, user_msg: str, idx: int) -> str:
        self.step_seen += 1
        if self.fail_at_step is not None and self.step_seen >= self.fail_at_step:
            # 模拟"模型服务 500"：LLM.complete 会把它包装成 LLMError。
            raise RuntimeError("模拟模型服务不可用（503）")

        plan = self.plan(user_msg)
        if not plan:
            return super()._before_tools(user_msg, idx)
        done = self._done_actions(self._messages)
        todo = [(n, a) for n, a in plan if n not in done]
        if not todo:
            return self._summarize(user_msg)
        name, args = todo[0]
        import json

        payload = json.dumps(args, ensure_ascii=False)
        return (
            f"Thought: 计划 {[n for n, _ in plan]}，下一步做 {name}。"
            f"{self._resume_note(self._messages)}\n"
            f"Action: {name}({payload})\n"
            f'<tool_call>{{"name": "{name}", "args": {payload}}}</tool_call>'
        )

    # ---- 第二拍 -------------------------------------------------------
    def _after_tools(self, user_msg: str, tool_msgs, idx: int) -> str:
        import json

        last = tool_msgs[-1]
        body = re.sub(r"</?result\b[^>]*>", "", last.content, flags=re.I).strip()
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}
        if last.metadata.get("ok", True):
            self.results.append((last.name, self._short(last)))

        if last.name == "charge_user":
            if not last.metadata.get("ok", True):
                # ★ 扣款调用**失败**时必须如实上报。
                #   注意观察发生顺序：弱幂等键在**参数校验层**就被拦住了
                #   （schema 里写了 minLength: 4），所以工具函数根本没被执行、
                #   一次扣款请求都没发生。这就是"纵深防御"：
                #     第 1 层 schema 校验（便宜、拦在入口）
                #     第 2 层 函数内断言（防住绕过 schema 的调用方）
                #     第 3 层 数据库唯一索引（并发下唯一真正可靠的一层）
                #   三层都要有，因为任何一层的假设都可能被绕过。
                return ("Thought: 扣款工具被拒绝了（参数不合法），我不能谎称成功。\n\n"
                        f"Final Answer: 扣款未执行：{body[:150]}")
            # 读的是工具返回里的 `replayed` 字段 ——
            # **模型看到的事实来自工具，而不是来自它的猜测**。
            # 幂等要想在"用户体验"这一层也成立，就必须把"这是重放"的事实透给模型，
            # 否则模型会照着"又调了一次扣款工具"编出"已扣款两次"的说法，
            # 副作用没错、叙述错了，用户照样投诉。
            replayed = bool(payload.get("replayed"))
            cents = self.force_charge[1] if self.force_charge else payload.get("cents", "?")
            head = "这次请求此前已处理过，**没有重复扣款**" if replayed else "已完成扣款"
            return (f"Thought: 扣款工具返回了结果，{'这是重放' if replayed else '这是首次执行'}。\n\n"
                    f"Final Answer: {head}（第 {payload.get('seq', '?')} 笔，{cents} 分）。")

        if not last.metadata.get("ok", True):
            # 工具失败 → 如实上报，并说明"卡在哪一步"（这正是超时降级要传达的信息）。
            return (f"Thought: 工具 {last.name} 失败了，我不该编造结果。\n\n"
                    f"Final Answer: 执行 {last.name} 时失败：{body[:160]}")

        # 继续推进计划：算出"还剩哪一步没做"，把它写出来。
        plan = self._plan_from_task(user_msg)
        done = self._done_actions(self._messages)
        todo = [(n, a) for n, a in plan if n not in done]
        if todo:
            name, args = todo[0]
            payload_text = json.dumps(args, ensure_ascii=False)
            return (f"Thought: {last.name} 完成，计划里还剩 {[n for n, _ in todo]}，继续。\n"
                    f"Action: {name}({payload_text})\n"
                    f'<tool_call>{{"name": "{name}", "args": {payload_text}}}</tool_call>')

        return self._summarize(user_msg)

    def _summarize(self, user_msg: str = "") -> str:
        """把所有已拿到的工具结果拼成一句人话（模拟真实模型"总结答案"）。

        ★ 结果是从**会话**里读的，不是从 `self.results` 这个内存列表里读的。
          所以续跑时（新进程、新 LLM 实例、内存全空）它照样能总结出
          崩溃前那两步的结果 —— 这就是"状态在检查点里，不在进程里"的直接体现。
        """
        bits: list[str] = []
        for msg in self._messages:
            if msg.role == "tool" and msg.metadata.get("ok", True):
                bits.append(f"{msg.name} → {self._short(msg)}")
        body = "；".join(bits) or "（没有拿到任何工具结果）"
        return f"Thought: 计划里的步骤做完了，我可以回答了。\n\nFinal Answer: {body}"

    @staticmethod
    def _short(msg) -> str:
        body = re.sub(r"</?result\b[^>]*>", "", msg.content, flags=re.I).strip()
        body = re.sub(r"\s+", " ", body)
        return body[:140]


__all__ = [
    "Counter", "STATS", "reset_stats", "SideEffectLedger", "LEDGER",
    "demo_tools", "ProductionLLM", "FAKE_ORDERS",
]
