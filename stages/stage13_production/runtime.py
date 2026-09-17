"""生产运行时：把"本地能跑的 Agent"改造成"敢上线的服务"。

------------------------------------------------------------
一句话本质：
    生产化 = 检查点续跑 + 幂等 + 并发准入 + 超时降级 + 熔断 + 结构化日志。
    而这一切之所以必要，是因为一个根本矛盾：
        **Agent 是有状态的长任务，HTTP 是无状态的短连接。**
------------------------------------------------------------

本模块的角色：它是 Agent 外面的那层"服务外壳"。
    Agent（core/agent.py）只负责"想 → 做 → 看 → 记"；
    Runtime 负责"它挂了怎么办、重复提交怎么办、排队怎么办、太慢怎么办"。

    ┌──────────────┐   submit(req)   ┌─────────────────────────────┐
    │  调用方/网关  │ ──────────────► │  ProductionRuntime          │
    └──────────────┘                 │   ① 幂等闸门（重放缓存）      │
                                     │   ② 熔断闸门（快速失败）      │
                                     │   ③ 并发准入（拒绝而非排队）  │
                                     │   ④ 执行（可续跑引擎）        │
                                     │   ⑤ 记录（结构化日志+指标）   │
                                     └─────────────────────────────┘
                                                  │
                                     ┌────────────▼────────────┐
                                     │ CheckpointStore（状态） │
                                     └─────────────────────────┘

一个刻意的设计决定：**所有闸门都在"执行之前"，且都不依赖模型**。
    生产事故里最忌讳的就是"用模型来判断要不要调用模型"。
    准入、去重、熔断必须是纯确定性的代码 —— 这也是第 09 章的同一句话：
    "能用确定性代码解决的，绝不用模型"。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from core.agent import Agent
from core.errors import AgentError, BudgetExceeded

from .journal import (
    STATUS_CRASHED,
    STATUS_DONE,
    STATUS_FAILED,
    STATUS_RUNNING,
    CheckpointStore,
    EventLog,
    IdempotencyCache,
    Metrics,
    Request,
    RunState,
    message_to_dict,
)
from .virtual import Budget, Clock, real_clock


# ===========================================================================
# 一、故障注入：用"抛异常"代替"杀进程"
# ===========================================================================
class SimulatedCrash(BaseException):
    """模拟"进程在第 N 步被 kill"。

    为什么不去真的 kill 进程？
        1. 教学代码不该有权限杀进程，更不该留下半截状态；
        2. 真 kill 之后**没法在同一个测试里继续验证**恢复逻辑；
        3. 从被恢复者的视角看，两者完全一样：
           都是"run() 中途断了，检查点停在半路"。
    生产里对应的真实事件：OOM Killer、Pod 被驱逐、发布重启、机器掉电。

    ★ 为什么继承 **BaseException** 而不是 Exception？
        这是个非常刻意的选择，也是本课一个真实到肉痛的教训：
        core/agent.py 的 run() 最后有一句
            except Exception as exc: stop_reason = "error"
        （本意是"任何意外都不该让宿主进程崩掉"）。
        于是我们抛出的"进程被杀"会被它**翻译成一次正常的 error 返回值** ——
        崩溃演练看起来跑完了、其实根本没崩。

        "进程死亡"在语义上就不该被业务代码的 `except Exception` 兜住，
        它和 KeyboardInterrupt / SystemExit 是同一类东西：
        **必须一路向上冒泡，直到进程边界**（这里由运行时接住）。
        这也是为什么 Python 把 KeyboardInterrupt 放在 BaseException 分支：
        兜底逻辑可以兜"错误"，但不能兜"中断"。
        至于 `except Exception` 与 `except BaseException` 的区别，值得你专门记一笔。
    """


class _BudgetSignal(BaseException):
    """预算耗尽的**内部信号**（只在引擎内部使用）。

    为什么不能直接在观察者里 `raise BudgetExceeded(...)`？
        因为 core/agent.py 的 run() 里有一句
            except AgentError as exc: stop_reason = "error"
        而 BudgetExceeded 正是 AgentError 的子类（它属于"预期内的策略性停机"）。
        于是我们精心抛出的"超时"会被翻译成一次普通的 "error"，
        语义彻底丢失 —— 用户看到的不是"超时降级"，而是"跑挂了"。

    这和 SimulatedCrash 是**同一类问题**：上层为了"别让宿主进程崩掉"而写的兜底
    `except`，会把我们有意制造的"中断"吃掉。
    解法也一样：用一个 `except Exception` 抓不到的 BaseException 子类当信使，
    让它在 Agent 的兜底之外被抛出，再由引擎翻译回语义明确的 BudgetExceeded。

    这条经验在生产里叫 **"不要把中断混进错误体系"**：
    超时、取消、关机信号应该走独立通道，否则它们迟早会被某个
    "兜底错误处理"吞掉，表现成"偶发地不生效"。
    """


# ===========================================================================
# 二、并发准入：拒绝，而不是排队
# ===========================================================================
class OverloadGuard:
    """并发闸门（信号量）。

    为什么必须有它？
        每个 Agent run 都占着"一条模型连接 + 一份内存 + 一个线程/协程"。
        如果 200 个请求同时进来而无上限，你会得到：
        模型端 429（限流）→ 全部重试 → 更多请求 → 雪崩式超时。
        这就是"**过载不是慢，是死**"。

    两种过载策略，本章选第二种，理由要记住：
        (A) 排队等（队列无限长）：延迟不可控地增长，用户等到 3 分钟后超时，
            白白占着连接 —— 排队把"过载"变成了"必然超时"。
        (B) **快速拒绝**（返回 429 + Retry-After）：诚实地告诉调用方"现在不行，
            0.5 秒后再试"。用户重试的成本远低于挂死。
        生产的标准答案：短队列（吸收抖动）+ 队列满就拒绝（保护自己）。
    """

    def __init__(self, limit: int = 4, retry_after_s: float = 0.5) -> None:
        if limit < 1:
            raise ValueError("并发上限必须 >= 1")
        self.limit = limit
        self.retry_after_s = retry_after_s
        self.in_flight = 0
        self.peak = 0            # 观测到的最大并发（用来自证"没有超过上限"）
        self.acquired = 0
        self.rejected = 0
        self.waited = 0          # 排队过的请求数（教学用：我们不做真排队）

    # ---- 两个原语：获取 / 释放 ----------------------------------------
    def try_acquire(self) -> bool:
        if self.in_flight >= self.limit:
            self.rejected += 1
            return False
        self.in_flight += 1
        self.acquired += 1
        self.peak = max(self.peak, self.in_flight)
        return True

    def release(self) -> None:
        self.in_flight = max(0, self.in_flight - 1)

    def snapshot(self) -> dict[str, int]:
        return {"limit": self.limit, "in_flight": self.in_flight, "peak": self.peak,
                "acquired": self.acquired, "rejected": self.rejected}


class Overloaded(RuntimeError):
    """准入被拒（生产里映射成 HTTP 429 + Retry-After）。"""

    def __init__(self, message: str, retry_after_s: float) -> None:
        super().__init__(message)
        self.retry_after_s = retry_after_s


# ===========================================================================
# 三、熔断器
# ===========================================================================
class CircuitBreaker:
    """熔断器：**连续失败到阈值就停止调用下游，直接快速失败。**

    直觉：下游已经躺了，你每个请求还去敲它一次、等它超时，
    只会把上游的线程/连接也拖死（故障扩散）。
    断开之后立刻返回错误，给下游留出恢复时间。

    三个状态（这是所有熔断器的标准形状，Hystrix / Resilience4j 都一样）：

        CLOSED   ──失败率超阈值──►  OPEN
          ▲                          │
          │                   冷却时间到
     探测成功                     │
          └──── HALF_OPEN ◄────────┘

        CLOSED     正常放行，统计失败
        OPEN       一律拒绝，不再打下游（快速失败）
        HALF_OPEN  **应当**只放一个探测请求过去：成功→恢复；失败→重新计时
                   ★ 当前实现没有强制这一点 —— allow() 在 HALF_OPEN 下无条件放行，
                     并发来了会全部放过去。补上它是 README 的练习 4。

    为什么 HALF_OPEN 只放一个？
        如果放一批，而下游还是坏的，你就又把它打死了 —— 这叫"熔断抖动"。
    """

    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

    def __init__(self, threshold: int = 3, cooldown_s: float = 30.0,
                 clock: Clock = real_clock) -> None:
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.clock = clock
        self.failures = 0            # 连续失败次数
        self.state = self.CLOSED
        self.opened_at = 0.0
        self.short_circuited = 0     # 被"快速失败"挡掉的请求数（越大越省资源）
        self.trips = 0               # 跳闸次数
        self.events: list[str] = []

    # ---- 查询 ---------------------------------------------------------
    def allow(self) -> bool:
        """现在能调用下游吗？"""
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            if self.clock() - self.opened_at >= self.cooldown_s:
                self._to(self.HALF_OPEN, "冷却结束，放一个探测请求过去")
                return True
            self.short_circuited += 1
            return False
        # HALF_OPEN：本应"只放一个探测"，但这里是无条件放行 —— 见类文档串的 ★
        return True

    def retry_after(self) -> float:
        """还要等多久才可能恢复（给用户一个诚实的估计，而不是让他盲等）。"""
        if self.state != self.OPEN:
            return 0.0
        return max(0.0, self.cooldown_s - (self.clock() - self.opened_at))

    # ---- 反馈 ---------------------------------------------------------
    def record_success(self) -> None:
        if self.state == self.HALF_OPEN:
            self._to(self.CLOSED, "探测成功，恢复正常")
        self.failures = 0

    def record_failure(self, reason: str = "") -> None:
        self.failures += 1
        if self.state == self.HALF_OPEN:
            self._to(self.OPEN, f"探测失败，重新熔断（{reason}）")
            self.opened_at = self.clock()
            return
        if self.failures >= self.threshold:
            self._to(self.OPEN, f"连续失败 {self.failures} 次 ≥ 阈值 {self.threshold}")
            self.opened_at = self.clock()

    def _to(self, state: str, why: str) -> None:
        if state == self.OPEN and self.state != self.OPEN:
            self.trips += 1
        self.state = state
        self.events.append(f"[{self.clock():.2f}s] {state}: {why}")

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state, "failures": self.failures, "trips": self.trips,
                "short_circuited": self.short_circuited,
                "retry_after_s": round(self.retry_after(), 2)}


# ===========================================================================
# 四、一次尝试的结果 / 对外的响应
# ===========================================================================
@dataclass
class RunOutcome:
    """引擎跑完（或被中断）之后交回来的东西。"""

    answer: str = ""
    stop_reason: str = ""          # final_answer / max_steps / error / timeout / crashed
    steps_done: int = 0
    tool_hits: dict[str, int] = field(default_factory=dict)
    partial: bool = False          # True = 这不是完整答案，是降级产物
    error: str = ""
    # ★ 失败发生在"第几步"。注意它和 steps_done 是两件事：
    #   steps_done = 完整做完了几步（用于判断还剩几步预算）
    #   last_step  = 最后**进入过**的那一步（用于回答"卡在哪一步"）
    #   一次在第 2 步失败的运行，steps_done 可能只有 1，但 last_step 是 2。
    #   排障时你要的是后者 —— 只报"完成了 1 步"根本定位不到问题。
    last_step: int = 0


@dataclass
class RunResponse:
    """**对外唯一的返回结构**。它是"HTTP 响应体"的教学替身。

    几个字段的设计意图，值得逐条想清楚：
        replayed   你拿到的是缓存回声，不是新的执行 —— 调用方据此可以安全重试
        degraded   结果是半成品（超时了），extra 里有降级原因
        partial_answer  半成品内容本身：**有半成品远好过什么都没有**
        reason     停机原因，必须透出。生产系统里"静默失败"比崩溃更可怕。
    """

    run_id: str
    answer: str = ""
    reason: str = ""
    status: str = ""
    steps: int = 0
    tool_hits: dict[str, int] = field(default_factory=dict)
    cached: bool = False        # 幂等缓存命中
    replayed: bool = False      # 同上，语义更明确的别名
    degraded: bool = False      # 降级返回（超时）
    rejected: bool = False      # 被准入/熔断拒绝
    retry_after_s: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.reason == "final_answer" and not self.rejected

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ===========================================================================
# 五、可续跑引擎：Agent 与检查点之间的桥
# ===========================================================================
class CheckpointedEngine:
    """把 core.Agent 包一层，让它在**每一步之后写检查点**。

    为什么"每步之后"而不是"跑完再存"？
        因为"跑完再存"等于没存 —— 崩的那一刻恰恰是没跑完的时候。
        检查点必须落在**步骤边界**上：一个步骤要么没开始、要么完整完成。
        这就是数据库事务的"原子性"思想在 Agent 上的翻版。

    为什么不用真的线程/子进程去杀？
        见 SimulatedCrash 的注释。异常与 kill 对恢复逻辑来说等价。

    ★ 关键点：检查点里存的是 **messages_before（起点）** 而不是"当前进度"。
      恢复时我们从起点重放、一次性把会话恢复成"已完成 N 步"的样子。
      这带来两个好处：
        1. 状态是**幂等可重建**的（重放起点 → 得到确定的中途状态）；
        2. 崩溃发生在"第 N 步写到一半"时，那次半成品写操作**自动作废**，
           不会污染恢复后的状态 —— 因为我们从上一个**完整边界**重放。
    """

    def __init__(self, agent: Agent, store: CheckpointStore, log: EventLog,
                 clock: Clock = real_clock) -> None:
        self.agent = agent
        self.store = store
        self.log = log
        self.clock = clock

    def __call__(self, state: RunState, *, remaining: int, resume: bool = False,
                 crash_at: int | None = None) -> RunOutcome:
        """让引擎可以像函数一样被调用（Engine 协议）。"""
        return self.start(state, remaining=remaining, resume=resume, crash_at=crash_at)

    def start(self, state: RunState, *, remaining: int, resume: bool = False,
              crash_at: int | None = None) -> RunOutcome:
        budget = Budget(max_seconds=state.request.max_seconds, max_steps=remaining, clock=self.clock)
        conv = state.to_conversation()
        # ★★★ 恢复时的"重放技巧"：把末尾那条用户消息摘掉，再交给 Agent.run()。
        #
        #   为什么？因为 Agent.run() 的第一步永远是 `conversation.add(Message.user(task))`。
        #   如果我们把"已经含用户消息的完整会话"塞回去，用户消息会被追加第二次，
        #   模型就会看到重复的问题、误判"什么都没做"，于是从头再跑一遍 ——
        #   最终答案看起来是对的，**工具调用却悄悄翻倍**（本课要防的事故本身）。
        #
        #   所以恢复的正确姿势是：把会话倒回"用户消息之前"，
        #   让 Agent 自己把那条消息重新追加一次 —— 历史就被**精确复原**。
        #   这也是所有 checkpoint 系统的通用语义：
        #       **恢复 = 倒回一个干净的边界 + 重放，而不是"接着上次的中间状态写"。**
        if resume and conv.messages and conv.messages[-1].role == "user":
            conv.messages.pop()
        state.snapshot_start(conv)
        steps_before = state.steps_done        # ★ 续跑时这里不是 0
        self.agent.conversation = conv
        self.agent._call_history = [c.signature() for m in conv.messages for c in m.tool_calls]
        self.agent.max_steps = remaining

        self.log.emit("run_start" if not resume else "run_resume", run_id=state.run_id,
                      messages=len(conv.messages), budget=state.request.max_seconds,
                      before=len(state.messages_before), captured=state.start_captured)

        # 观察者：每一步结束时被调用一次 —— 这就是**检查点边界**。
        #
        # ★ 已完成步骤用一个**列表**记录（内容 + 顺序），而不是一个累加计数器。
        #   理由见下面 completed.append 处的注释：事实清单可自愈，累计数字不行。
        #   续跑时我们把**上一次已经记录的事实**先装回来，再继续追加。
        completed: list[dict[str, Any]] = list(state.completed_steps)
        # ★ 续跑时的"起始偏移"：本次 run 里第 1 步其实是整条 run 的第 (steps_before+1) 步。
        #   没有它，恢复后的步号会从 1 重新数，
        #   于是同一个 checkpoint_saved 会同时出现 step=1 和 step=3 两种口径，
        #   日志一对齐就露馅 —— 排障的人会以为自己看错了 run。
        steps_before = len(completed)
        # 最后"进入过"的步号（用于回答"失败发生在哪一步"）
        last_step = 0

        def observer(event: str, payload: dict[str, Any]) -> None:
            nonlocal last_step
            step = int(payload.get("index", 0) or 0)
            if step:
                last_step = steps_before + step   # 换算成整条 run 的绝对步号

            # ★★ 三个关键时刻，都必须钉在**干净的步骤边界**上：
            #      step_start   → 准备进入下一步（检查预算，别一开始就来不及）
            #      llm_output   → 模型刚回来（★ 在这里检查预算：工具还没执行，
            #                     所以绝不会出现"已经超时了，却又发了一条通知"）
            #      tool_result / final_answer → 一步完整做完（写检查点 / 注入崩溃）
            #    绝不能钉在一圈的中间 —— 中间状态既不能安全收手，也不能安全续跑。
            if event == "step_start":
                budget.check(about_to=f"第 {step} 步的模型调用", signal=_BudgetSignal)

            self.log.emit(event, run_id=state.run_id, step=step, ms=payload.get("elapsed_ms", 0.0))
            if event == "llm_output":
                # 只有预算在这个时机检查才有意义：此刻模型已经回来了，
                # 工具还没执行 —— 停在这里，就绝不会出现"超时了却还发了一条通知"。
                budget.check(about_to=f"第 {step} 步的工具执行", signal=_BudgetSignal)
                return
            # ★ 只有这两类事件才算"完成了一步"。
            #   注意 run_end / user_input / step_start / parsed 都会走到这里，
            #   早期版本漏了这个判断，导致步号 1→3→6→10 一路翻倍。
            #   生产里"指标口径算错"比"没有指标"更危险 —— 你会在错误的数据上做决策。
            if event not in {"tool_result", "final_answer"}:
                return
            # ★ 用"做了哪几步"的**列表**来记账，而不是用累加计数器。
            #   为什么？因为一旦进程中途死过、续跑过，
            #   "逻辑步号 = 之前步数 + 本次步数"这种推导极容易算重（我们真的踩过）。
            #   而"把每一步的名字追加进一个列表"天然幂等：死多少次都只是补几条。
            #
            #   这也是一般化的工程建议：**状态尽量存"事实清单"，而不是"累计数字"**。
            #   累计数字一旦重复计算就无法自愈，事实清单可以随时重新求值。
            completed.append({
                "step": len(completed) + 1,
                "kind": "tool" if event == "tool_result" else "final_answer",
                "tool": str(payload.get("tool", "")),
                "ok": bool(payload.get("ok", True)) if event == "tool_result" else True,
            })
            state.steps_done = len(completed)
            if event == "tool_result":
                tool = str(payload.get("tool", ""))
                if payload.get("ok"):
                    # 只有"真执行成功"才算业务副作用；失败/被拒不算 —— 这个判断很重要，
                    # 否则"降级"会污染指标（第 10 章：指标口径错了比没指标更糟）。
                    state.tool_hits[tool] = state.tool_hits.get(tool, 0) + 1
                    state.partial_answer = f"已通过 {tool} 拿到结果"
            else:
                state.partial_answer = str(payload.get("text", ""))[:200]
            state.state = STATUS_RUNNING
            state.set_conversation(conv)
            state.completed_steps = [dict(c) for c in completed]
            self.store.save(state)                          # ← 每一步之后落盘
            self.log.emit("checkpoint_saved", run_id=state.run_id, step=state.steps_done,
                          messages=len(conv.messages), tool_hits=dict(state.tool_hits))

        # ★★★ 这里有一个非常真实、非常容易踩的坑，值得单独讲：
        #
        #     最直觉的写法是在 observer 里直接 `raise SimulatedCrash(...)`。
        #     但 core/agent.py 的 _emit() 是这样写的：
        #         try:
        #             self.observer(event, payload)
        #         except Exception:
        #             pass            # ← 观察者崩了不能拖垮主流程
        #     这个"防御性"的 try/except 会把我们的崩溃**静默吞掉**，
        #     于是"模拟进程被杀"变成了"什么也没发生"，实验看起来是对的、其实没崩。
        #
        #     这是生产代码里极常见的一类事故：**错误被兜底逻辑吃掉**。
        #     （第 10 章讲的"结构化日志里看不到 error 事件"往往就是这个原因：
        #       不是没出错，而是错在别处被 except: pass 了。）
        #
        #     退一步说，就算不被观察者吞掉，Agent.run() 最外层还有一个
        #     `except Exception` 兜底（"任何意外都不应该让宿主进程崩掉"）——
        #     它会把崩溃翻译成 stop_reason="error" 的正常返回值。
        #
        #     所以正确做法是**两段式**：
        #       ① 观察者照常工作（写日志、写检查点）—— 但它的异常会被吞；
        #       ② 崩溃注入放在 _emit 的**外层包装**里，并且：
        #          先让原 _emit 跑完（事件已派发、检查点已落盘），
        #          再抛出一个**不被 agent._emit 兜住**的异常 ——
        #          也就是在包装函数里 catch 住自己抛的崩溃，然后原样 re-raise，
        #          这样就跳出了 agent._emit 的 try 范围。
        #     最终效果：崩溃精确发生在一个**干净的步骤边界**上，
        #     而且永远不会被任何兜底 try/except 吃掉。
        agent_emit = self.agent._emit
        crash_armed = crash_at is not None

        def emit_and_arm(event: str, payload: dict[str, Any]) -> None:
            try:
                agent_emit(event, payload)                   # 正常派发（日志/检查点都写完了）
            except SimulatedCrash:
                # 这是"我们自己抛的"，必须放它走 —— agent._emit 会吞掉它。
                raise
            if crash_armed and event in {"tool_result", "final_answer"}:
                # 用 == 而不是 >= ：步号必须是**精确踩中**那一步才崩，
                # 否则续跑时 steps_before 已经很大，>= 会让"续跑"立刻又崩一次
                # —— 那就变成了"永远起不来"的崩溃循环（生产里叫 crash loop）。
                if state.steps_done == crash_at:
                    raise SimulatedCrash(
                        f"模拟进程在第 {state.steps_done} 步之后被 kill"
                        f"（检查点已持久化到磁盘，可续跑）"
                    )

        self.agent.observer = observer
        self.agent._emit = emit_and_arm                      # type: ignore[method-assign]
        self.agent.verbose = False

        # ★★★ 第二个同类坑：core/agent.py 的 run() 外面还有一层
        #     `except AgentError as exc: stop_reason = "error"`。
        #     而 BudgetExceeded 恰恰是 AgentError 的子类（它本来就是
        #     "预期内的策略性停机"，见 core/errors.py）。
        #     结果：我们精心抛出的"超时"会被翻译成一次普通的 "error"，
        #     语义彻底丢失（用户看到的不是"超时降级"，而是"跑挂了"）。
        #
        #     解法同样是"在外层接住"：给这次 run 套一层壳，
        #     让预算耗尽在 Agent 的兜底之外被翻译回 BudgetExceeded。
        #     这并不是 hack —— 生产里所有超时控制的实现（context deadline、
        #     asyncio.wait_for、gRPC deadline）本质都是"在外层拦截"。
        raw_run = self.agent.run

        def run_guarded(task: str, **kw: Any):
            budget.check(about_to="调用模型", signal=_BudgetSignal)
            try:
                return raw_run(task, **kw)
            except _BudgetSignal as sig:
                # ★ 信使回来了：翻译成语义明确的"预算耗尽"，交给下面的 except 处理。
                raise BudgetExceeded(str(sig)) from None

        self.agent.run = run_guarded                          # type: ignore[method-assign]
        try:
            result = self.agent.run(state.request.task, reset=False)
        except BudgetExceeded as exc:
            # ★ 超时不等于崩溃：预算耗尽是一次**设计好的收手**。
            #   状态留在"可续跑"上，但对外返回的是"半成品 + 说明"。
            #
            #   注意这里用 `patch(...)` 而不是直接 `save(state)`：
            #   崩溃路径只负责"标记状态"，绝不该顺带把"起点会话"也重写一遍
            #   （那正是把恢复搞成重放事故的元凶）。
            state.set_conversation(conv)
            self.store.patch(state, state=STATUS_CRASHED)
            self.log.emit("run_timeout", run_id=state.run_id, step=state.steps_done,
                          level="warn", reason=str(exc))
            return RunOutcome(answer=state.partial_answer, stop_reason="timeout",
                              steps_done=state.steps_done, tool_hits=dict(state.tool_hits),
                              partial=True, error=str(exc), last_step=last_step)
        except BaseException:
            # 崩溃路径：只把状态标成 crashed（检查点内容以最后一次成功保存的为准），
            # 这样续跑时能从一个**自洽的步骤边界**继续。
            state.set_conversation(conv)
            self.store.patch(state, state=STATUS_CRASHED)
            raise
        finally:
            self.agent.observer = None
            self.agent._emit = agent_emit                    # type: ignore[method-assign]
            self.agent.run = raw_run                         # type: ignore[method-assign]
            self.agent.verbose = True

        # ② 半段已经不需要了：崩溃在 ① 里就抛出去了（见上）。
        outcome = RunOutcome(
            answer=result.answer,
            stop_reason=result.stop_reason,
            steps_done=state.steps_done,
            tool_hits=dict(state.tool_hits),
            error=result.error,
            last_step=last_step,
        )
        return outcome


# 引擎的形态：给一个 state + 还能跑几步，交回一个 outcome。
# 用"注入引擎"而不是"硬编码 Agent"，是为了让"超时/崩溃"这些故障
# 能用几行假引擎在测试里精确复现（依赖注入的经典收益）。
Engine = Callable[..., RunOutcome]


# ===========================================================================
# 六、生产运行时
# ===========================================================================
class ProductionRuntime:
    """服务外壳：幂等 → 熔断 → 并发准入 → 执行 → 记录。

    它的 `submit()` 就是"一个 HTTP 端点应该做的事"：
    任何一步的失败都有明确的返回结构，**永远不会把异常抛给调用方**
    （抛出去 = 用户看到 500 = 你不知道发生了什么）。
    """

    def __init__(
        self,
        engine: Engine,
        store: CheckpointStore,
        *,
        log: EventLog | None = None,
        cache: IdempotencyCache | None = None,
        limiter: OverloadGuard | None = None,
        breaker: CircuitBreaker | None = None,
        metrics: Metrics | None = None,
        clock: Clock = real_clock,
        version: str = "stable",
    ) -> None:
        self.engine = engine
        self.store = store
        self.log = log if log is not None else EventLog()
        self.cache = cache if cache is not None else IdempotencyCache()
        self.limiter = limiter if limiter is not None else OverloadGuard()
        self.breaker = breaker if breaker is not None else CircuitBreaker(clock=clock)
        self.metrics = metrics if metrics is not None else Metrics()
        self.clock = clock
        self.version = version

    # ------------------------------------------------------------------
    # 对外主入口：一次提交
    # ------------------------------------------------------------------
    def submit(self, req: Request, *, crash_at: int | None = None,
               resume: bool = False) -> RunResponse:
        """提交一次请求。**这是唯一应该被 HTTP 层调用的方法。**"""
        self.metrics.incr("submitted")
        rid = req.request_id

        # ---- 闸门 ①：幂等（最便宜，放最前面） -------------------------
        # 顺序不是随便定的：便宜的确定性检查一定排在贵的操作前面。
        # 幂等命中率在真实系统里可以高达 10%~30%（用户双击、客户端重试、
        # 网关重发），这意味着**这部分流量一次模型调用都不该花**。
        #
        # ★ 注意 cache_key：客户端的幂等键必须和 (user_id, 任务) 拼起来用。
        #   直接用客户端 key 会让"另一个用户碰巧用了同样的 key"错误命中缓存
        #   —— 那等于把钱记到别人头上。见 IdempotencyCache.cache_key 的注释。
        ck = IdempotencyCache.cache_key(req.idempotency_key, req.user_id, req.task)
        # 注意：这里是 get-then-execute，**不是原子操作** —— 并发下同一个键可能被算两次。
        # 这一层省的是**钱**，不是**正确性**；正确性归副作用层的唯一键
        # （生产里是数据库唯一索引 / Redis SETNX，见 README 1.3 与第 3 层说明）。
        hit = self.cache.get(ck)
        if hit is not None:
            self.metrics.incr("duplicates_blocked")
            self.metrics.incr("cached_hits")
            self.log.emit("idempotent_replay", run_id=rid, key=req.idempotency_key,
                          first_run=hit["run_id"])
            return RunResponse(
                run_id=rid, answer=hit["answer"], reason="idempotent_replay",
                status=STATUS_DONE, cached=True, replayed=True,
                extra={"first_run_id": hit["run_id"],
                       "note": "命中幂等缓存：没有第二次执行，没有第二次副作用"},
            )

        # ---- 闸门 ②：熔断（下游已经挂了就别再打它） -------------------
        if not self.breaker.allow():
            self.metrics.incr("breaker_short_circuit")
            wait = self.breaker.retry_after()
            self.log.emit("breaker_short_circuit", run_id=rid, level="warn",
                          state=self.breaker.state, retry_after_s=round(wait, 2))
            return RunResponse(
                run_id=rid, reason="circuit_open", status=STATUS_FAILED, rejected=True,
                retry_after_s=wait,
                extra={"note": f"熔断器处于 {self.breaker.state}，快速失败（未调用下游）"},
            )

        # ---- 闸门 ③：并发准入 ----------------------------------------
        if not self.limiter.try_acquire():
            self.metrics.incr("rejected_overload")
            self.log.emit("overload_rejected", run_id=rid, level="warn",
                          in_flight=self.limiter.in_flight, limit=self.limiter.limit)
            return RunResponse(
                run_id=rid, reason="overloaded", status=STATUS_FAILED, rejected=True,
                retry_after_s=self.limiter.retry_after_s,
                extra={"in_flight": self.limiter.in_flight, "limit": self.limiter.limit,
                       "note": "并发已满，选择快速拒绝而不是把请求堆在队列里"},
            )

        # ---- 闸门 ④：执行 --------------------------------------------
        try:
            return self._publish(req, crash_at=crash_at, resume=resume)
        except Overloaded:
            raise
        finally:
            self.limiter.release()
            self.metrics.counters["_peak_in_flight"] = max(
                self.metrics.get("_peak_in_flight"), self.limiter.peak)

    # ------------------------------------------------------------------
    # 执行管道（submit 与故障注入实验都走这里）
    # ------------------------------------------------------------------
    def _publish(self, req: Request, *, crash_at: int | None = None,
                 resume: bool = False) -> RunResponse:
        state = self._load_or_create(req, resume=resume)
        if state is None:
            # 恢复请求找不到检查点：这是运维事故（检查点过期被清掉了）。
            self.log.emit("resume_missing_checkpoint", run_id=req.request_id, level="error")
            return RunResponse(run_id=req.request_id, reason="no_checkpoint",
                               status=STATUS_FAILED, rejected=True,
                               extra={"note": "找不到检查点，无法续跑"})

        remaining = max(1, req.max_steps - state.steps_done)
        outcome = self.engine(state, remaining=remaining, resume=resume, crash_at=crash_at)
        return self._finalize(state, outcome)

    def _load_or_create(self, req: Request, *, resume: bool) -> RunState | None:
        if resume:
            state = self.store.load(req.request_id)
            if state is None:
                return None
            state.attempts += 1
            state.state = STATUS_RUNNING
            self.metrics.incr("resumed")
            self.store.save(state)
            return state

        state = RunState(
            run_id=req.request_id,
            request=req,
            version=self.version,
            attempts=1,
            created_at=self.clock(),
        )
        self.store.save(state)
        return state

    def _finalize(self, state: RunState, outcome: RunOutcome) -> RunResponse:
        """把引擎的原始结果翻译成"对外响应 + 持久化状态 + 指标 + 日志"。"""
        state.steps_done = max(state.steps_done, outcome.steps_done)
        state.tool_hits = dict(outcome.tool_hits)

        if outcome.stop_reason == "final_answer":
            state.state = STATUS_DONE
            state.answer = outcome.answer
            state.stop_reason = "final_answer"
            self.store.save(state)
            # ★ 任务成功才写幂等缓存。绝不能提前写 —— 提前写会把"失败"
            #   缓存成"成功"，用户重试拿到一个假成功，比重复执行更糟。
            #   （缓存键要和读取时用同一套作用域拼接规则，否则写进去也读不出来。）
            self.cache.put(
                IdempotencyCache.cache_key(state.request.idempotency_key,
                                           state.request.user_id, state.request.task),
                run_id=state.run_id, answer=state.answer,
                meta={"steps": state.steps_done})
            self.metrics.incr("completed")
            self.log.emit("run_done", run_id=state.run_id, step=state.steps_done,
                          answer_chars=len(state.answer))
            self.breaker.record_success()
            return RunResponse(run_id=state.run_id, answer=state.answer,
                               reason="final_answer", status=STATUS_DONE,
                               steps=state.steps_done, tool_hits=dict(state.tool_hits))

        if outcome.stop_reason == "timeout":
            # ★★ 超时降级：**不做无谓的重试，而是给出半成品 + 明确说明**。
            #    "返回部分结果"远比"挂死到连接超时"体验好，也比"直接报错"信息量大：
            #    用户至少知道已经完成了哪部分，可以只重试缺的那部分。
            state.state = STATUS_CRASHED      # 可续跑：检查点仍在
            state.stop_reason = "timeout"
            state.partial_answer = state.partial_answer or outcome.answer
            self.store.save(state)
            self.metrics.incr("degraded_total")
            self.log.emit("run_degraded", run_id=state.run_id, step=state.steps_done,
                          level="warn", reason=outcome.error)
            self.breaker.record_success()     # 超时是"我们主动收手"，不算下游故障
            return RunResponse(
                run_id=state.run_id, answer=outcome.answer, reason="timeout",
                status=STATUS_CRASHED, degraded=True, steps=state.steps_done,
                tool_hits=dict(state.tool_hits),
                extra={"partial_answer": state.partial_answer,
                       "explain": f"任务超出时间预算已停止（已完成 {state.steps_done} 步）；"
                                  f"检查点已保留，可用 run_id 续跑",
                       "resumable": True},
            )

        if outcome.stop_reason == "crashed":
            state.state = STATUS_CRASHED
            self.store.save(state)
            return RunResponse(run_id=state.run_id, status=STATUS_CRASHED,
                               reason="crashed", steps=state.steps_done,
                               extra={"resumable": True})

        # 其余都算失败：error / max_steps / loop_detected / parse_failed
        state.state = STATUS_FAILED
        state.stop_reason = outcome.stop_reason
        state.error = outcome.error
        self.store.save(state)
        self.metrics.incr("failed_total")
        self.log.emit("run_failed", run_id=state.run_id,
                      step=outcome.last_step or state.steps_done,
                      level="error", reason=outcome.stop_reason, error=outcome.error[:200])
        self.breaker.record_failure(outcome.stop_reason)
        return RunResponse(run_id=state.run_id, answer=outcome.answer,
                           reason=outcome.stop_reason, status=STATUS_FAILED,
                           steps=state.steps_done, tool_hits=dict(state.tool_hits),
                           extra={"error": outcome.error})

    # ------------------------------------------------------------------
    # 续跑
    # ------------------------------------------------------------------
    def resume(self, run_id: str, *, crash_at: int | None = None) -> RunResponse:
        """从检查点续跑。**这就是"进程被杀之后运维敲的那条命令"。**

        生产里它有三种触发方式：
            1. 用户带 Idempotency-Key 重试，网关发现 run 还活着 → 挂到旧 run 上；
            2. 后台补偿任务扫描 `status=crashed AND updated_at < now-1min`；
            3. 人工介入（值班同学拿到 run_id，手动 retry）。
        """
        state = self.store.load(run_id)
        if state is None:
            return RunResponse(run_id=run_id, reason="no_checkpoint", rejected=True,
                               extra={"note": f"没有 run_id={run_id} 的检查点"})
        req = state.request
        self.log.emit("resume_requested", run_id=run_id, steps_done=state.steps_done,
                      tool_hits=dict(state.tool_hits))
        return self._publish(req, crash_at=crash_at, resume=True)

    def crash_after(self, run_id: str, n: int) -> int:
        """算出"再跑 n 步就崩"对应的**绝对步号**。

        这个小小的辅助函数体现了一个重要的接口设计原则：
            外部调用者说的是"再跑 2 步就崩"（相对语义），
            而检查点里存的是绝对步号。两者之间的换算必须由懂得
            "当前已经跑到第几步"的那一层来做 —— 也就是运行时，
            而不是调用方。否则每个调用方都要自己去读检查点，重复且易错。
        """
        state = self.store.load(run_id)
        return (state.steps_done if state else 0) + n

    def status(self, run_id: str) -> RunState | None:
        return self.store.load(run_id)

    def snapshot(self) -> dict[str, Any]:
        """运维看板：把"服务的健康状况"一次说清。"""
        return {
            "version": self.version,
            "limiter": self.limiter.snapshot(),
            "breaker": self.breaker.snapshot(),
            "metrics": self.metrics.as_dict(),
            "cache_entries": len(self.cache),
            "runs": len(self.store.list_run_ids()),
        }


__all__ = [
    "SimulatedCrash", "TimeoutDegraded", "OverloadGuard", "Overloaded",
    "CircuitBreaker", "RunOutcome", "RunResponse", "CheckpointedEngine",
    "ProductionRuntime", "Engine",
]
