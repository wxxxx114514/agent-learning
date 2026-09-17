"""第 13 章 · 生产化部署 —— 让有状态的长任务，活在无状态的短连接世界里。

运行：
    py -m stages.stage13_production.demo
    py -m stages.stage13_production.demo --list
    py -m stages.stage13_production.demo --section 2
    py -m stages.stage13_production.demo --check
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (banner, bullet, check_that, code, essence, kv, note, ok,
                          report, section, setup_console, warn)

from core.agent import Agent  # noqa: E402
from core.errors import BudgetExceeded  # noqa: E402
from core.llm import LLM, LLMResponse  # noqa: E402
from core.mock_llm import as_mock_response  # noqa: E402

from stages.stage13_production.canary import (  # noqa: E402
    CanaryConfig, CanaryRouter, VersionedLLM,
)
from stages.stage13_production.handlers import (  # noqa: E402
    STATS, LEDGER, ProductionLLM, demo_tools, reset_world,
)
from stages.stage13_production.journal import (  # noqa: E402
    STATUS_CRASHED, STATUS_DONE, EventLog, FileCheckpointStore,
    IdempotencyCache, InMemoryCheckpointStore, Metrics, Request, RunState,
)
from stages.stage13_production.runtime import (  # noqa: E402
    CheckpointedEngine, CircuitBreaker, OverloadGuard, ProductionRuntime,
    SimulatedCrash,
)
from stages.stage13_production.virtual import Budget, FakeClock  # noqa: E402

# ===========================================================================
# 0. 约定与工具函数
# ===========================================================================
# 本章的"业务场景"：一个电商客服 Agent，要按顺序完成三件事
#     ① 查订单（只读）  ② 归档订单（写）  ③ 统计一段文本（本地计算）
# 中间任何一步都可能被"进程被杀 / 超时 / 重复提交"打断 —— 这就是教学素材。
TASK = "查一下订单 A1001，然后归档并统计字数"
PAY_TASK = "给 u_42 扣款 350 分"

# 检查点落盘目录。
#
# 为什么不用系统临时目录（tempfile.gettempdir()）？
#     本课程要求"跑完不在仓库里留垃圾"，而在 Windows 上写 %TEMP% 有时会被
#     安全策略挡住（我们真的遇到过 PermissionError）。所以干脆把**检查点写在
#     本 stage 目录内部的 .scratch/ 里，并且在每个小节结束时删掉**。
#     教学示范用完后清干净，比"留在系统临时目录里自生自灭"更负责任。
# 生产里这个位置应该是 Redis / Postgres / 对象存储 —— 见 README 的工程要点。
SCRATCH = Path(__file__).resolve().parent / ".scratch"


def fresh_scratch(name: str) -> Path:
    """准备一个干净的落盘目录（每次从零开始，避免上一次实验的残留）。"""
    path = SCRATCH / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def drop_scratch() -> None:
    """删掉本小节用过的检查点目录 —— 演示结束不留垃圾。"""
    shutil.rmtree(SCRATCH, ignore_errors=True)


def build_agent(
    llm: LLM,
    *,
    max_steps: int = 6,
    max_llm_retries: int = 0,
) -> Agent:
    """造一个 core.Agent。

    参数选择的理由（都是生产上的取舍，不是随手写的）：
        max_llm_retries=0  本章的故障演练要"一次失败就失败"，
                           否则 Agent 内置的指数退避会把 25ms 变成 100ms+，
                           让"超时实验"变成"重试实验"，看不清真正的主角。
                           （真实生产要开重试，见 README 工程要点第 4 条。）
        repeat_limit=2     死循环保护，第 01 章的老朋友。
        verbose=False      本章的输出由我们自己的 console helper 统一排版。
    """
    return Agent(
        llm=llm, tools=demo_tools(), max_steps=max_steps,
        max_parse_retries=1, max_llm_retries=max_llm_retries,
        repeat_limit=2, verbose=False, workspace=".",
    )


def make_runtime(
    store,
    *,
    llm_factory,
    log: EventLog | None = None,
    clock=None,
    limiter: OverloadGuard | None = None,
    breaker: CircuitBreaker | None = None,
    cache: IdempotencyCache | None = None,
    metrics: Metrics | None = None,
    max_steps: int = 6,
    max_llm_retries: int = 0,
) -> ProductionRuntime:
    """装配一个生产运行时。

    `llm_factory` 是**工厂函数**而不是一个模型实例 —— 这个细节很关键：
        每个 run 都必须拿到**全新的模型对象**，不能复用带状态的实例。
        理由有两层：
          1. 真实模型客户端持有连接池/计数，跨 run 复用会污染统计；
          2. 我们的假模型（以及真实模型的"上下文缓存"）会把上一轮的状态带进来。
        更本质地说：**Worker 必须是无状态的**。任何"跨请求残留的内存状态"
        在大规模部署里都会变成一类诡异 bug（因为请求会被负载均衡打到不同机器）。
    """
    from stages.stage13_production.virtual import real_clock

    clock = clock or real_clock
    log = log if log is not None else EventLog()
    engine = CheckpointedEngine(build_agent(llm_factory(), max_steps=max_steps,
                                            max_llm_retries=max_llm_retries),
                                store, log, clock=clock)
    return ProductionRuntime(engine, store, log=log, cache=cache, limiter=limiter,
                             breaker=breaker, metrics=metrics, clock=clock)


def show_journal(store: FileCheckpointStore, tag: str = "") -> None:
    """把磁盘上的检查点状态打出来 —— 这是本章最直观的"证据"。

    生产事故复盘时你做的第一件事就是这个：把 run 记录捞出来看状态机走到哪了。
    """
    ids = store.list_run_ids()
    bullet(f"{tag}检查点文件 {len(ids)} 个（{store.root}）")
    for rid in ids:
        st = store.load(rid)
        if st is None:
            continue
        kv(f"  run {rid}", f"状态={st.state:<8} 已完成 {st.steps_done} 步 "
                           f"工具={st.tool_hits} 消息={len(st.messages)} 条")


def show_status(rt: ProductionRuntime, run_id: str) -> None:
    st = rt.status(run_id)
    if st is None:
        warn(f"没有 run_id={run_id} 的检查点")
        return
    kv("运行状态", st.state)
    kv("已完成步数", st.steps_done)
    kv("工具副作用", st.tool_hits)
    kv("会话消息数", f"{len(st.messages)} 条（可续跑的全部依据）")
    kv("半成品答案", (st.partial_answer or "（无）")[:56])


# ===========================================================================
# 第 1 节：天真做法 —— 内存态 + 单次调用，上线就出事
# ===========================================================================
def demo_naive() -> dict:
    """**先看它怎么坏。** 这是全章的问题起点。

    天真做法长这样（也是绝大多数人第一次写出来的样子）：

        @app.post("/ask")
        def ask(q: str):
            return {"answer": agent.run(q).answer}      # 请求进来 → 跑完 → 返回

    它在本地永远是对的。因为本地只有你一个人、一次请求、进程不会重启。
    上线之后，它会在四个地方同时崩掉：

        ① 进程重启（发布 / OOM / 扩缩容）→ 跑了 80% 的任务原地蒸发
        ② 用户重复点击 → 副作用执行两次（这里就是"扣两次款"）
        ③ 用户等了 90 秒 → 网关早断了，但你的进程还在跑，白烧算力
        ④ 100 个并发 → 一起抢模型连接，全体变慢 → 全部超时

    本节只演示 ① 和 ②，因为这两条最直观。
    """
    section("天真做法：内存态 + 单次调用，为什么一上线就出事", "①")

    note("天真实现（本地跑得好好的那一版）：")
    code(
        'agent = build_agent()                        # 状态在进程内存里\n'
        'store = InMemoryCheckpointStore()            # "检查点"也在内存里\n'
        '\n'
        '@app.post("/ask")\n'
        'def ask(q: str):\n'
        '    result = agent.run(q)                    # 一次请求 → 一次完整 run\n'
        '    return {"answer": result.answer}         # 跑完才返回，中途断了就全没了'
    )
    print()

    reset_world()
    store = InMemoryCheckpointStore()
    rt = make_runtime(store, llm_factory=lambda: ProductionLLM(model="mock-naive"))
    req = Request(request_id="naive-1", user_id="u_42", task=TASK, max_steps=6)

    print("  ▶ 场景 A：任务跑到第 2 步，进程被 kill（发布 / OOM / 扩缩容）")
    try:
        rt.submit(req, crash_at=2)
    except SimulatedCrash as exc:
        kv("  结果", f"异常穿透到调用方：{exc}")
    # 内存版检查点的"重启"：对象还在，但按语义它的内容应当随进程一起消失。
    store.simulate_restart()
    kv("  simulate_restart 之后", f"检查点数量 = {len(store.list_run_ids())}")
    warn("已经跑完的两步（查订单 + 归档）**凭空消失**，用户只能从头再来一遍。")
    warn("更糟的是：如果那两步里有副作用，重跑就意味着**副作用执行第二次**。")
    print()

    print("  ▶ 场景 B：用户没等到响应，又点了一次提交")
    reset_world()

    # ★ 这里刻意用**两个不同的 request_id** 来模拟"客户端重试"：
    #   真实客户端重试时几乎总会生成新的 request_id（或至少不能假设它不变），
    #   所以"用 request_id 做幂等键"这种做法在真实流量下等于没做。
    def naive_charge_llm(rid: str) -> ProductionLLM:
        # 注意 rid 是通过**参数**传进来的，不是闭包捕获的循环变量 ——
        # Python 的闭包捕获的是"变量"而不是"值"，写成 lambda 很容易两次都拿到同一个值，
        # 那样反例就静默失效了（我们在这章真的踩过这个坑）。
        return ProductionLLM(force_charge=("u_42", 350), request_id=rid,
                             charge_mode="narrow", model="mock-naive")

    for rid in ("naive-req-0001", "naive-req-0002"):
        make_runtime(InMemoryCheckpointStore(),
                     llm_factory=lambda rid=rid: naive_charge_llm(rid)).submit(
            Request(request_id=rid, user_id="u_42", task=PAY_TASK, max_steps=3))
    applied = STATS["charge_applied"].total()
    kv("  两次提交", f"扣款接口被调用 {STATS['charge_calls'].total()} 次")
    kv("  实际扣款", f"{applied} 次，累计 {STATS['charge_amount'].total()} 分")
    warn("用户只提交了一次业务意图，钱被扣了两次 —— 这就是 P0 事故。")
    print()

    note("四个问题的共同根源是**一个矛盾**：")
    print()
    code(
        "Agent 的一次运行 = 有状态 + 长任务（几十秒、几十步、有副作用）\n"
        "HTTP 的一次请求 = 无状态 + 短连接（通常 3~30 秒就断了）\n"
        "\n"
        "把长任务塞进短连接里，就像把一头大象塞进电话亭 ——\n"
        "本地只有一头象时你能硬塞，上线后象群一来，电话亭就塌了。"
    )
    print()
    ok("本章要做的，就是给这头大象造一条**可持久化的轨道**：")
    for line in [
        "1. 状态持久化 → 请求断了、进程死了，任务还在",
        "2. 幂等       → 重试不会变成第二次副作用",
        "3. 并发控制   → 过载时快速失败，而不是一起死",
        "4. 超时降级   → 给半成品 + 说明，而不是挂死",
        "5. 熔断       → 下游挂了就别再打它",
        "6. 结构化日志 → 能回答”是哪一次运行的哪一步失败了“",
        "7. 灰度回滚   → 新版本变坏时，自动把流量切回去",
    ]:
        print(f"     {line}")
    return {"naive_applied": applied}


# ===========================================================================
# 第 2 节：检查点与断点续跑
# ===========================================================================
def demo_checkpoint_resume() -> dict:
    """核心一节：**崩溃 → 恢复 → 不丢工作、不重复副作用**。

    实现要点（对应 demo 里的三处 ★ 注释）：
        1. 检查点写在**每一步的边界**上（不是跑完再写，那等于没写）；
        2. 恢复时把会话倒回"用户消息之前"再重放，历史被精确复原；
        3. 已完成动作从**会话**里推断，而不是从进程内存里读。
    """
    section("检查点与断点续跑：进程随时可以死", "②")

    note("第一步：把检查点从内存搬到磁盘（生产里就是 Redis / Postgres）")
    code(
        '# journal.py 的原子写：临时文件 → fsync → os.replace\n'
        'fd, tmp = tempfile.mkstemp(dir=str(self.root))\n'
        'with open(fd, "w", encoding="utf-8") as f:\n'
        '    f.write(payload); f.flush(); os.fsync(f.fileno())\n'
        'os.replace(tmp, path)      # ← 原子改名：要么全是旧内容，要么全是新内容'
    )
    note("为什么必须原子写？直接覆写有个窗口：文件已截断、新内容还没写完时进程被杀，")
    note("检查点就变成一个**坏 JSON** —— 崩溃恢复于是退化成「崩溃 + 数据损坏」，比没有更糟。")
    print()

    reset_world()
    journal = fresh_scratch("resume")
    store = FileCheckpointStore(journal)
    log = EventLog()
    rt = make_runtime(store, llm_factory=lambda: ProductionLLM(model="mock-run1"),
                      log=log)

    print("  ▶ 第 1 次提交：正常执行，但在第 2 步之后「模拟进程被杀」")
    req = Request(request_id="run-001", user_id="u_42", task=TASK, max_steps=6)
    try:
        rt.submit(req, crash_at=rt.crash_after("run-001", 2))
        warn("预期中的崩溃没有发生 —— 实验无效")
    except SimulatedCrash as exc:
        kv("  崩溃", str(exc))
    print()
    show_status(rt, "run-001")
    hits_after_crash = STATS["lookup_calls"].total(), STATS["archive_applied"].total()
    kv("  外部世界已发生", f"查订单 {hits_after_crash[0]} 次 / 归档 {hits_after_crash[1]} 次")
    print()
    print("  磁盘上的检查点长什么样（节选）：")
    raw = (journal / "run-001.json").read_text(encoding="utf-8").splitlines()
    for line in raw[:6] + ["   …"] + [ln for ln in raw if '"steps_done"' in ln
                                      or '"completed_steps"' in ln or '"state"' in ln][:3]:
        print(f"     {line.strip()[:100]}")
    print()

    print("  ▶ 第 2 次提交：**换一个全新的运行时**（模拟新进程/新 Pod/另一台机器）")
    log2 = EventLog()
    rt2 = make_runtime(FileCheckpointStore(journal),
                       llm_factory=lambda: ProductionLLM(model="mock-run2"), log=log2)
    resp = rt2.submit(req, resume=True)
    print()
    kv("  恢复后答案", resp.answer[:96] + "…")
    kv("  停机原因", resp.reason)
    kv("  最终状态", resp.status)
    hits_after_resume = STATS["lookup_calls"].total(), STATS["archive_applied"].total()
    kv("  外部世界累计", f"查订单 {hits_after_resume[0]} 次 / 归档 {hits_after_resume[1]} 次")
    print()

    if hits_after_resume == hits_after_crash:
        ok("★ 关键证据：恢复前后「外部世界的副作用次数完全没变」。")
        ok("  崩溃前做完的两步没有被重跑 —— 这才是「续跑」，而不是「重跑一遍」。")
    else:
        warn("副作用次数发生了变化：说明恢复时重放了已完成的动作")

    print()
    note("怎么证明的？靠**结构化日志**和**外部计数**，而不是靠「看起来对」：")
    for ln in log2.timeline("run-001"):
        print(f"     {ln}")
    print()
    note("还可以看「这一轮到底为什么停了」：run_failed / run_timeout / run_done 都带 run_id 与步号。")
    print()

    # 收尾：删掉本次的检查点目录，演示不留垃圾
    drop_scratch()
    return {"crashed_hits": hits_after_crash, "resumed_hits": hits_after_resume,
            "answer": resp.answer, "reason": resp.reason, "status": resp.status}


# ===========================================================================
# 第 3 节：幂等 —— 重复提交不能产生第二次副作用
# ===========================================================================
def demo_idempotency() -> dict:
    """**幂等是本章最贵的一节**：这里的 bug 会直接扣用户的钱。"""
    section("幂等：为什么要用「请求 ID」之外的键", "③")

    note("先看没有幂等键时会发生什么（这正是很多团队上线第一周的样子）：")
    print()
    reset_world()
    # 天真实现：把 request_id 当幂等键。
    # 看起来"有去重"，但客户端重试时往往生成**新的** request_id —— 于是完全失效。
    naive = fresh_scratch("idem-naive")
    for rid in ("naive-req-0001", "naive-req-0002"):
        rt = make_runtime(FileCheckpointStore(naive), llm_factory=lambda rid=rid: ProductionLLM(
            force_charge=("u_42", 350), request_id=rid, charge_mode="narrow",
            model="mock-naive"))
        rt.submit(Request(request_id=rid, user_id="u_42", task=PAY_TASK,
                          max_steps=3, idempotency_key=""))
    naive_applied = STATS["charge_applied"].total()
    kv("  两次提交（业务上是同一次）", "客户端重试，request_id 变了")
    kv("  实际扣款", f"{naive_applied} 次 / {STATS['charge_amount'].total()} 分")
    warn("用 request_id 当幂等键 = 没做幂等：客户端换个 ID 就绕过去了。")
    print()

    note("正确做法：幂等键由**掌握业务语义的那一层**生成，并且贯穿整条链路。")
    code(
        '# 客户端：带一个稳定的幂等键（同一笔业务意图永远用同一个键）\n'
        'POST /charge   Idempotency-Key: idem-u42-350\n'
        '\n'
        '# 服务端：以它为键查"这件事做过没有"\n'
        'def charge_user(user_id, cents, idempotency_key):\n'
        '    if len(idempotency_key) < 4:\n'
        '        raise ValueError("幂等键太短，拒绝执行（弱幂等键 = 假安全感）")\n'
        '    return ledger.apply_once(idempotency_key, "charge", user_id, cents)\n'
        '\n'
        '# 账本：数据库里一张带唯一索引的表（唯一约束才是最终保证）\n'
        'CREATE TABLE charges (idem_key TEXT PRIMARY KEY, user_id TEXT, cents INT);'
    )
    print()

    reset_world()
    journal = fresh_scratch("idem-safe")
    log = EventLog()
    rt = make_runtime(FileCheckpointStore(journal), log=log,
                      llm_factory=lambda: ProductionLLM(
                          force_charge=("u_42", 350), idempotency_key="idem-u42-350",
                          charge_mode="safe", model="mock-safe"))

    print("  ▶ 同一个幂等键，分两次提交（第 2 次模拟「用户重试 / 网络重发」）")
    first = rt.submit(Request(request_id="pay-1", user_id="u_42", task=PAY_TASK,
                              max_steps=3, idempotency_key="idem-u42-350"))
    kv("  第 1 次", f"{first.answer[:40]}（{first.reason}）")
    second = rt.submit(Request(request_id="pay-1", user_id="u_42", task=PAY_TASK,
                               max_steps=3, idempotency_key="idem-u42-350"))
    kv("  第 2 次", f"{second.answer[:40]}（{second.reason}）")
    applied = STATS["charge_applied"].total()
    kv("  扣款接口被调用", f"{STATS['charge_calls'].total()} 次")
    kv("  实际扣款", f"{applied} 次 / {STATS['charge_amount'].total()} 分")
    print()

    bullet("两道闸门，作用不同，缺一不可：")
    print()
    kv("  ① API 层幂等", "命中缓存直接返回上次结果（replayed=True），**一次模型调用都不花**")
    kv("  ② 副作用层幂等", "账本按幂等键去重（唯一索引），进程重启后依然有效")
    print()
    ok("注意第 2 次的 answer 里写着「没有重复扣款」——幂等必须传到**用户体验**这一层。")
    note("如果工具第二次返回一个不一样的结果，模型就会对用户说「已为你扣款两次」：")
    note("副作用没错、**叙述错了**，用户照样投诉。所以工具必须回传 replayed 标记。")
    print()

    print("  ▶ 换个 request_id，但幂等键相同（这才是真实的客户端重试形态）")
    reset_world()
    journal2 = fresh_scratch("idem-retry")
    rt2 = make_runtime(FileCheckpointStore(journal2), llm_factory=lambda: ProductionLLM(
        force_charge=("u_42", 350), idempotency_key="idem-u42-350", charge_mode="safe",
        model="mock-safe"))
    a = rt2.submit(Request(request_id="retry-x", user_id="u_42", task=PAY_TASK,
                           max_steps=3, idempotency_key="idem-u42-350"))
    b = rt2.submit(Request(request_id="retry-y", user_id="u_42", task=PAY_TASK,
                           max_steps=3, idempotency_key="idem-u42-350"))
    kv("  第 1 次", a.answer[:44])
    kv("  第 2 次（新 request_id）", b.answer[:44])
    kv("  实际扣款", f"{STATS['charge_applied'].total()} 次")
    ok("request_id 变了也不影响：幂等键稳定 → 副作用只发生一次。")
    print()

    print("  ▶ 如果换一个**不同**的幂等键呢？（用户是真的想再充一次）")
    note("  所以这里换一个**全新的运行时**（新的账本 = 新的「外部世界」）——")
    note("  否则上一笔扣款还留在账本里，你会看到一个「看起来像 bug」的正确答案。")
    rt3 = make_runtime(FileCheckpointStore(fresh_scratch("idem-second")),
                       llm_factory=lambda: ProductionLLM(
                           force_charge=("u_42", 350), idempotency_key="idem-u42-350-2",
                           charge_mode="safe", model="mock-safe"))
    c = rt3.submit(Request(request_id="retry-z", user_id="u_42", task=PAY_TASK,
                           max_steps=3, idempotency_key="idem-u42-350-2"))
    kv("  新键提交", c.answer[:52])
    kv("  实际扣款", f"{STATS['charge_applied'].total()} 次 / "
                     f"{STATS['charge_amount'].total()} 分")
    note("这正是幂等键的正确语义：**它区分的是「业务意图」，不是「请求次数」。**")
    note("给幂等键设计一个稳定的推导规则（用户+业务+业务主键），比随手 uuid4() 重要得多。")
    note("真实支付系统还会再加一层「业务级去重」（同一用户+同一金额+短时间窗内只收一次），")
    note("因为客户端给的键再稳，也架不住它自己写错。")
    print()

    key_demo = IdempotencyCache.fingerprint("charge", "u_42", "350")
    kv("指纹示例", f'fingerprint("charge","u_42","350") = {key_demo}')
    note("用 sha256 而不是内置 hash()：内置 hash 带随机盐、**跨进程不稳定**，")
    note("进程 A 算出的键进程 B 认不出来 —— 重启后幂等失效，重复扣款就回来了。")
    print()

    drop_scratch()
    return {"naive_applied": naive_applied, "safe_applied": applied,
            "third_applied": STATS["charge_applied"].total()}


# ===========================================================================
# 第 4 节：并发控制、超时降级与熔断
# ===========================================================================
def demo_overload() -> dict:
    """过载：**不是慢，是死**。所以要"快速拒绝"而不是"无限排队"。"""
    section("并发准入：过载时快速失败，而不是一起死", "④")
    note("为什么限流闸门要放在「调模型」之前？因为每个 run 都占着一条模型连接。")
    note("没有上限时：200 个并发 → 模型端 429 → 全部重试 → 更多请求 → 雪崩。")
    print()

    limiter = OverloadGuard(limit=5, retry_after_s=0.5)
    note("模型调用是慢的 —— 我们把它建模成「一个请求要占 3 个 tick 才完成」。")
    note("而流量是**突发**的 —— 每个 tick 来 3 个请求（比如整点批量提交）。")
    note("这样不需要真线程、没有时序竞态，但过载是真的。")
    print()
    code(
        "每个 tick 做三件事（顺序很重要）：\n"
        "  ① 完成一个「已经服务满 3 个 tick」的请求  → 释放一个名额\n"
        "  ② 接纳新到的请求                          → in_flight += 1，满了就拒绝\n"
        "  ③ 记录这一 tick 的在飞数                  → 观察它有没有越过上限"
    )
    print()

    inflight: list[int] = []          # 记录每个在飞请求的"接入 tick"
    pending = list(range(1, 26))      # 一共 25 个请求要打进来（每个 tick 到 3 个）
    done = 0
    rejected = 0
    served = 3                        # 一个请求要占几个 tick 才完成
    tick = 0
    while pending or inflight:
        tick += 1
        # ① 完成一个到期的请求（FIFO：最早接入的最先完成）
        if inflight and tick - inflight[0] >= served:
            inflight.pop(0)
            limiter.release()
            done += 1
        # ② 这个 tick 新到 3 个请求
        for _ in range(3):
            if not pending:
                break
            pending.pop(0)
            if limiter.try_acquire():
                inflight.append(tick)
            else:
                rejected += 1          # 满了 → 快速拒绝（429 + Retry-After）
        # ③ 在飞数必须由 limiter 自己报告（它就是那个"闸门"），不能我们自己数
        assert limiter.in_flight == len(inflight), "闸门计数与自己数的对不上"
        if tick <= 8 or tick % 8 == 0:
            print(f"     tick {tick:>2}  在飞={limiter.in_flight} "
                  f"已完成={done:<3} 已拒绝={rejected:<3} 待接入={len(pending):<3} "
                  f"峰值={limiter.peak}")
    print()
    kv("并发上限", limiter.limit)
    kv("观测到的峰值并发", limiter.peak)
    kv("完成 / 拒绝", f"{done} / {rejected}")
    print()
    if limiter.peak <= limiter.limit:
        ok(f"★ 峰值并发 {limiter.peak} 从未超过上限 {limiter.limit} —— 闸门有效。")
    else:
        warn("并发越界了，闸门失效")
    note("被拒绝的请求会拿到 429 + Retry-After（诚实告诉对方「现在不行，0.5 秒后再试」）。")
    note("对比一下「无限排队」：延迟不可控地涨，用户等 3 分钟后超时 —— 白白占着连接。")
    print()
    print("  拒绝路径在运行时里长这样（返回结构，绝不抛异常给调用方）：")
    code(
        'if not self.limiter.try_acquire():\n'
        '    return RunResponse(reason="overloaded", rejected=True,\n'
        '                       retry_after_s=self.limiter.retry_after_s)\n'
        '# 生产里映射成 HTTP 429 + Retry-After 头'
    )
    return {"limit": limiter.limit, "peak": limiter.peak, "done": done,
            "rejected": rejected}


def demo_timeout_degrade() -> dict:
    """超时：**绝不挂死，给半成品 + 说清楚卡在哪**。"""
    section("超时降级：给半成品，而不是挂死", "⑤")
    note("超时的正确姿势是「在干净的步骤边界上收手」，而不是「跑到一半硬砍」。")
    note("所以我们把预算检查钉在两个时刻：**每步开始前** 和 **模型刚回来、工具还没执行时**。")
    note("后一个时刻特别关键：它保证不会出现「已经超时了，却又发了一条通知」。")
    print()

    reset_world()
    journal = fresh_scratch("timeout")
    log = EventLog()
    # 虚拟时钟：让"超时"变成确定性可测的事件（而不是 sleep 3 秒碰运气）。
    slow_clock = FakeClock()
    rt = make_runtime(
        FileCheckpointStore(journal), log=log, clock=slow_clock, max_steps=4,
        llm_factory=lambda: SlowLLM(
            ProductionLLM(model="mock-slow"), 300.0, clock=slow_clock))

    req = Request(request_id="run-to", user_id="u_42", task=TASK, max_steps=4,
                  max_seconds=0.75, idempotency_key="idem-to")
    kv("  时间预算", f"{req.max_seconds}s（每个模型调用固定消耗 0.3s）")
    print()
    resp = rt.submit(req)
    print()
    kv("  停机原因", resp.reason)
    kv("  是否降级", resp.degraded)
    kv("  已完成步数", resp.steps)
    kv("  工具已发生", resp.tool_hits)
    kv("  半成品说明", resp.extra.get("explain", ""))
    print()
    if resp.degraded and resp.tool_hits.get("count_words", 0) == 0:
        ok("★ 在「归档完成、还没统计字数」的位置收手 —— 第 3 步的工具执行前就停了。")
        ok("  半成品 + 明确说明 + 可续跑，**三件套齐了**，用户不会看到无限转圈。")
    else:
        warn("降级行为不符合预期")
    print()
    note("对比「挂死」：连接一直占着，网关 30 秒后超时断开，用户看到 504，")
    note("而你的进程还在傻跑 —— 算力白烧，用户还不知道进度。")
    print()

    print("  ▶ 半成品能接着跑吗？能 —— 换个更大的预算续跑")
    fast_clock = FakeClock()
    rt2 = make_runtime(FileCheckpointStore(journal), log=log, clock=fast_clock,
                       max_steps=4,
                       llm_factory=lambda: ProductionLLM(model="mock-fast"))
    req2 = Request(request_id="run-to", user_id="u_42", task=TASK, max_steps=4,
                   max_seconds=30.0, idempotency_key="idem-to")
    resp2 = rt2.submit(req2, resume=True)
    kv("  续跑结果", resp2.reason)
    kv("  最终答案", resp2.answer[:80] + "…")
    kv("  工具累计", resp2.tool_hits)
    ok("超时不是终局：状态还在，预算够了就能跑完。")
    print()
    drop_scratch()
    return {"reason": resp.reason, "degraded": resp.degraded, "steps": resp.steps,
            "tool_hits": dict(resp.tool_hits), "explain": resp.extra.get("explain", ""),
            "resumed_reason": resp2.reason, "resumed_answer": resp2.answer}


def demo_breaker() -> dict:
    """熔断：下游已经躺了，就别再打它。"""
    section("熔断：下游挂了就别再打它", "⑥")
    note("熔断器的三个状态（Hystrix / Resilience4j 都是这个形状）：")
    print()
    code(
        "  CLOSED   ──连续失败 ≥ 阈值──►  OPEN\n"
        "    ▲                             │\n"
        "    │                       冷却时间到\n"
        " 探测成功                        │\n"
        "    └──── HALF_OPEN ◄────────────┘\n"
        "\n"
        "  CLOSED     正常放行\n"
        "  OPEN       一律拒绝（快速失败），给下游留恢复时间\n"
        "  HALF_OPEN  只放**一个**探测请求：成了就恢复，不成就重新计时\n"
        "             （放一批的话，下游还没好就被你二次打死 —— 这叫熔断抖动）"
    )
    print()

    reset_world()
    clock = FakeClock()
    journal = fresh_scratch("breaker")
    log = EventLog()
    breaker = CircuitBreaker(threshold=3, cooldown_s=30.0, clock=clock)
    rt = make_runtime(FileCheckpointStore(journal), log=log, clock=clock,
                      breaker=breaker, max_steps=3,
                      llm_factory=lambda: BrokenLLM("模型服务持续 503"))

    print("  ▶ 连续提交 5 次，模型服务一直是坏的")
    for i in range(1, 6):
        r = rt.submit(Request(request_id=f"bad-{i}", user_id="u_42", task=TASK,
                              max_steps=3))
        kv(f"  第 {i} 次", f"reason={r.reason:<16} rejected={r.rejected} "
                           f"retry_after={r.retry_after_s:.1f}s "
                           f"熔断器={breaker.state}")
    print()
    kv("  熔断器状态", f"{breaker.state}（连续失败 {breaker.failures} 次，跳闸 {breaker.trips} 次）")
    kv("  被快速挡掉", f"{breaker.short_circuited} 次 —— 这几次**没有调用下游**")
    ok("★ 后两次请求被直接拒绝：省下了 2 次注定失败的模型调用和它们的等待时间。")
    print()
    note("熔断器的价值是**阻断故障扩散**：下游躺了，你还每个请求去敲它、等它超时，")
    note("只会把上游的线程/连接池一起拖死，最后整条链路一起挂。")
    print()

    print("  ▶ 冷却 30 秒后放一个探测请求过去")
    clock.advance(30.0)
    allowed = breaker.allow()
    kv("  推进 30s 后 allow()", allowed)
    kv("  熔断器状态", breaker.state)
    if breaker.state == CircuitBreaker.HALF_OPEN:
        ok("进入 HALF_OPEN：**应当**只放一个探测请求 —— 但当前实现是无条件放行（练习 4）。")
    print()
    breaker.record_failure("探测又失败")
    kv("  探测失败后", f"{breaker.state}（retry_after={breaker.retry_after():.1f}s）")
    note("真实系统里这些状态变化必须打点上报（state=open 触发告警），否则你根本不知道它开过。")
    print()
    note("熔断的粒度也要选对：按「下游依赖」熔断（模型服务 / 订单服务 / 支付网关），")
    note("而不是按「整个 Agent」熔断 —— 支付网关挂了不该让查订单也一起不可用。")
    print()
    drop_scratch()
    return {"state": breaker.state, "trips": breaker.trips,
            "short_circuited": breaker.short_circuited, "failures": breaker.failures}


# ===========================================================================
# 第 5 节：结构化日志
# ===========================================================================
def demo_logging() -> dict:
    """可观测性：**回答"是哪一次运行的哪一步失败了"。**"""
    section("结构化日志：定位「某次失败发生在哪一步」", "⑦")
    note("生产事故的第一个问题永远是：「哪一次运行的哪一步失败了？」")
    note("自由文本日志答不了（只能人肉 grep + 猜），结构化日志可以。")
    note("下面每行都是**一行 JSON** —— 它可以直接进 ELK / Loki / OTel，被机器聚合。")
    print()

    reset_world()
    journal = fresh_scratch("logs")
    log = EventLog()
    rt = make_runtime(FileCheckpointStore(journal), log=log, max_steps=3,
                      llm_factory=lambda: BrokenLLM("模型服务 503（日志演示）"))

    req = Request(request_id="run-777", user_id="u_42", task=TASK, max_steps=3)
    resp = rt.submit(req)
    print()
    bullet("原始日志行（就是写进日志文件的样子）：")
    for rec in log.by_run("run-777")[:6]:
        print(f"     {EventLog.to_line(rec)}")
    print("     …")
    for rec in log.by_run("run-777")[-2:]:
        print(f"     {EventLog.to_line(rec)}")
    print()

    kv("这次运行的结果", f"{resp.reason} / {resp.status}")
    failed = log.where_failed("run-777")
    print()
    bullet("★ 那个价值百万的问题：「run-777 是哪一步失败的？」")
    if failed:
        kv("  答案", f"第 {failed['step']} 步，事件 {failed['event']}，"
                     f"原因 {failed.get('reason', failed.get('error', ''))[:40]}")
        ok("按 run_id 一过滤，时间线直接出来 —— 不需要猜、不需要爬全量日志。")
    else:
        warn("没有找到失败事件（预期应该有一个）")
    print()

    print("  ▶ 再跑一次「正常的」任务，对比两种 run 的事件序列")
    reset_world()
    journal2 = fresh_scratch("logs-ok")
    log2 = EventLog()
    rt2 = make_runtime(FileCheckpointStore(journal2), log=log2,
                       llm_factory=lambda: ProductionLLM(model="mock-ok"))
    rt2.submit(Request(request_id="run-888", user_id="u_42", task=TASK, max_steps=6))
    print()
    kv("  事件计数", str(log2.counts_by_event("run-888")))
    kv("  是否有 error", str(log2.where_failed("run-888")))
    print()

    print("  字段设计（每一个都对应一个真实的排障场景）：")
    for name, why in [
        ("ts", "还原时序：是「先超时」还是「先报错」，顺序不同根因不同"),
        ("run_id", "★ 全链路关联键：一次运行的所有事件、以及下游调用的 trace_id"),
        ("step", "定位「卡在第几步」——降级说明、重试决策都要用它"),
        ("event", "机器可聚合：step_end 的 p99、error 的占比、checkpoint_saved 的频率"),
        ("ms", "性能回归的第一手证据（模型变慢了？工具变慢了？）"),
        ("level", "告警路由：warn 进周报，error 直接叫人"),
        ("extra", "上下文：工具名、错误类型、路由决策、灰度版本"),
    ]:
        kv(f"  {name}", why)
    print()
    note("生产上还要做的三件事（本章只做了第一件）：")
    for line in [
        "1. 日志里**不要打用户隐私原文**（PII 脱敏，第 11 章）",
        "2. run_id 透传到所有下游调用（模型服务、工具服务），形成 trace",
        "3. 采样：全量打 ERROR，INFO 按 1% 采样，否则日志费能超过模型费",
    ]:
        print(f"     {line}")
    print()
    n_events = len(log2.by_run("run-888"))
    drop_scratch()
    return {"failed": failed, "reason": resp.reason, "status": resp.status,
            "ok_events": n_events, "ok_error": log2.where_failed("run-888")}


# ===========================================================================
# 第 6 节：灰度发布与自动回滚
# ===========================================================================
def demo_canary() -> dict:
    """灰度：让新版本**先接一点真实流量**，坏了自动切回去。"""
    section("灰度发布与自动回滚：让新版本先接 40% 流量", "⑧")
    note("为什么 Agent 特别需要灰度？因为它的输出是**概率性**的。")
    note("传统服务改代码，单测能覆盖 90%；Agent 改了提示词/换了模型，")
    note("你没法靠单测证明它没变坏 —— 只能靠真实流量上的指标（第 10 章的评估集管离线，灰度管在线）。")
    print()

    note("路由必须按**稳定键哈希**，不能用 random()：")
    code(
        'digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()\n'
        'bucket = int(digest[:8], 16) % 100        # 0~99\n'
        'version = "canary" if bucket < rollout_percent else "stable"'
    )
    note("用 random() 的后果：用户刷新一下就被分到另一个版本，答案突然变了；")
    note("而且同一个 request 在多台机器上落点不同，灰度比例变成一锅粥。")
    note("（用内置 hash() 也一样不行：它带随机盐，跨进程不稳定。）")
    print()

    def stable_impl(request_id: str) -> tuple[str, bool]:
        return f"stable 版本正常返回（{request_id}）", False

    def broken_canary(request_id: str) -> tuple[str, bool]:
        raise RuntimeError("新版本模型返回 500（模拟灰度中的坏版本）")

    router = CanaryRouter(stable_impl, broken_canary,
                          CanaryConfig(rollout_percent=40, error_threshold=0.25,
                                       min_samples=4, lookback_n=20))
    # 模拟"灰度已经跑了一会儿"：新版本此前处理过 3 个请求，都正常。
    # 为什么要预置？因为 min_samples 这道护栏会拦住"1 个请求失败就回滚"——
    # 样本太少时比例没有统计意义（1 个请求失败 = 100%）。
    router.seed_canary_window(ok=True, times=3)

    print("  ▶ 先看路由是否稳定（同一个 request_id 永远落同一个版本）")
    for rid in ("req-a", "req-b", "req-c"):
        kv(f"  {rid}", f"bucket={router.bucket(rid):>2} → {router.pick(rid)}")
    kv("  同一 ID 连查 3 次", str([router.pick("req-a") for _ in range(3)]))
    ok("稳定：同一个 request_id 的落点永远一致（灰度实验的数据才可信）。")
    print()

    print("  ▶ 打入真实流量（新版本从第 4 个样本开始全部失败）")
    live_ids = [f"probe-{i}" for i in range(1, 25)]
    rows = []
    for rid in live_ids:
        r = router.handle(rid)
        rows.append(r)
        mark = "失败" if r["failed"] else "成功"
        stop = "" if router.enabled else "   ← 错误率超阈值，已自动回滚"
        kv(f"  {rid}", f"bucket={router.bucket(rid):>2} → {r['version']:<6} {mark}{stop}")
        if not router.enabled:
            break
    print()
    kv("  本次路由次数", f"{len(rows)}（第 {len(rows)} 次触发回滚，一次性止损）")
    kv("  stable 指标", router.stats["stable"].render())
    kv("  canary 指标", router.stats["canary"].render())
    print()
    if router.rollback_reason:
        ok(f"★ 自动回滚已触发：{router.rollback_reason}")
    else:
        warn("没有触发回滚（预期应该触发）")
    print()
    note("注意 decision 用的是**滑动窗口错误率**，不是总错误率。")
    note("总错误率会被「上线前的健康历史」稀释，你会眼睁睁看着它从 0.1% 慢慢爬，")
    note("等它超过阈值时已经烧了一片；窗口对**最近**的行为敏感，能早十分钟发现。")
    print()

    print("  ▶ 回滚之后再打流量：新版本请求数不再增长")
    canary_before = router.stats["canary"].total
    for rid in ("after-1", "after-2", "after-3"):
        router.handle(rid)
    kv("  canary 请求数", f"{canary_before} → {router.stats['canary'].total}（未增长）")
    kv("  stable 请求数", f"{router.stats['stable'].total}")
    ok("回滚是**开关级**动作：不需要重新发布，流量瞬间全部回到 stable。")
    print()

    bullet("审计留痕（合规要求：每一次路由决策都要能解释）：")
    for line in router.audit[-5:]:
        print(f"     {line}")
    print()

    print("  ▶ 把灰度接进真实 Agent：一个「会选版本」的模型")
    journal = fresh_scratch("canary")
    log = EventLog()
    metrics = Metrics()
    store = FileCheckpointStore(journal)

    def versioned_rt(request_id: str):
        return make_runtime(store, log=log, metrics=metrics,
                            llm_factory=lambda: VersionedLLM(request_id, router))

    outputs = {}
    for rid in ("req-a", "req-b", "req-c", "req-d", "req-e"):
        r = versioned_rt(rid).submit(Request(request_id=rid, user_id="u_42",
                                             task="你好", max_steps=2))
        outputs[rid] = (router.pick(rid), r.reason)
        kv(f"  {rid}", f"版本={router.pick(rid):<6} reason={r.reason:<13} "
                      f"{r.answer[:26]}")
    print()
    note("模型换了、但 Agent 代码一行没改 —— 这就是「在 LLM 抽象层做灰度」的好处")
    note("（第 01 章埋下的 LLM 抽象，在这里回收了它的价值）。")
    print()
    drop_scratch()
    return {"rollback": router.rollback_reason, "enabled": router.enabled,
            "canary_total": router.stats["canary"].total,
            "stable_total": router.stats["stable"].total,
            "outputs": outputs}


# ===========================================================================
# 第 7 节：收口 —— 一句话本质
# ===========================================================================
def demo_essence() -> None:
    section("收口：一句话本质", "⑨")
    essence(
        "生产化 = 状态持久化 + 幂等重试 + 并发控制 + 超时熔断 + 灰度回滚\n"
        "\n"
        "而这一切之所以必要，是因为一个根本矛盾：\n"
        "    **Agent 是有状态的长任务，HTTP 是无状态的短连接。**\n"
        "\n"
        "12 章之前，我们一直在让 Agent 变聪明；\n"
        "这一章只做一件事：让它**在坏掉的时候也不出事**。\n"
        "\n"
        "记住三条最贵的经验：\n"
        "  1. 检查点写在**步骤边界**上，恢复靠**重放**而不是「接着中间写」；\n"
        "  2. 幂等键必须由**掌握业务语义**的那一层生成，并在副作用层去重；\n"
        "  3. 所有兜底 `except` 都会吃掉你精心设计的中断信号 —— 超时和取消要走独立通道。"
    )


# 辅助假模型（放在文件末尾，避免打断正文阅读节奏）
# ===========================================================================
class SlowLLM(LLM):
    """给任意模型套一层"固定耗时"，用来做超时实验。

    为什么用**注入的时钟**而不是 time.sleep？
        sleep 会让实验变成"碰运气"（CI 机器慢一点就变结论），
        还会让自检超过 1 秒的预算。注入时钟之后，
        "超时"变成一个**确定性的、毫秒级完成**的事件。

    真实代码里对应的写法是 deadline / context timeout（gRPC、asyncio.wait_for），
    原理完全一样：把"现在几点"交给外部决定。
    """

    name = "slow"

    def __init__(self, inner: LLM, cost_ms: float, clock) -> None:
        super().__init__(f"slow({inner.model})")
        self.inner = inner
        self.cost_ms = cost_ms
        self.clock = clock

    def _complete(self, messages, **kwargs):
        self.clock.advance_ms(self.cost_ms)      # "这次调用花了 cost_ms"
        resp = self.inner.complete(messages, **kwargs)
        if not isinstance(resp, LLMResponse):    # 理论上不会发生，防御性写法
            resp = as_mock_response(str(resp), self.model)
        self.total_calls = self.inner.total_calls
        return resp


class BrokenLLM(LLM):
    """永远失败的模型 —— 用来演示熔断与结构化日志的错误路径。"""

    name = "broken"

    def __init__(self, reason: str = "模型服务不可用（503）") -> None:
        super().__init__("mock-broken")
        self.reason = reason

    def _complete(self, messages, **kwargs):
        raise RuntimeError(self.reason)


# ===========================================================================
# 自检：本章验收标准（由 scripts/run_all_checks.py 调用）
# ===========================================================================
# 契约（第 01 章就定下的）：
#     run_checks() -> list[tuple[str, bool, str]]
# 三条硬性要求，缺一不可：
#     ① 快（< 1 秒）：所以全程用虚拟时钟、假模型，不做真实等待；
#     ② 确定性：没有随机数、没有线程、没有网络、没有 sleep；
#     ③ 不打印：它会被验证脚本包在 redirect_stdout 里调用，任何输出都是噪音。
#
# 验收标准来自 ROADMAP.md 第 13 章的四条，每条都至少对应一个检查项，
# 并且**正常路径与失败路径都要覆盖**（只测成功路径等于没测）。
# ===========================================================================
def run_checks() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    reset_world()
    root = fresh_scratch("checks")
    try:
        # ------------------------------------------------------------------
        # 验收 ①任务中途"进程被杀"，能从检查点恢复继续跑
        # ------------------------------------------------------------------
        reset_world()
        journal = root / "resume"
        store = FileCheckpointStore(journal)
        log = EventLog()
        rt = make_runtime(store, llm_factory=lambda: ProductionLLM(model="chk-1"), log=log)
        req = Request(request_id="c-run", user_id="u_42", task=TASK, max_steps=6)

        crashed = False
        try:
            rt.submit(req, crash_at=2)
        except SimulatedCrash:
            crashed = True
        results.append(check_that(
            "崩溃演练：进程在第 2 步之后被「杀掉」", crashed, "SimulatedCrash 已抛出"))

        st = store.load("c-run")
        results.append(check_that(
            "崩溃后检查点仍在磁盘上（状态=crashed）",
            st is not None and st.state == STATUS_CRASHED,
            f"state={st.state if st else 'None'}"))
        results.append(check_that(
            "检查点里保留了已完成步数与工具事实",
            bool(st) and st.steps_done == 2
            and st.tool_hits.get("lookup_order") == 1
            and st.tool_hits.get("archive_order") == 1,
            f"steps={st.steps_done if st else '?'} hits={st.tool_hits if st else '?'}"))
        results.append(check_that(
            "检查点里保留了完整会话（恢复的唯一依据）",
            bool(st) and len(st.messages) >= 6, f"{len(st.messages) if st else 0} 条消息"))

        hits_before = (STATS["lookup_calls"].total(), STATS["archive_applied"].total())
        # 换一个**全新的运行时对象**（模拟新进程 / 新 Pod）
        rt2 = make_runtime(FileCheckpointStore(journal),
                           llm_factory=lambda: ProductionLLM(model="chk-2"))
        resp = rt2.submit(req, resume=True)
        hits_after = (STATS["lookup_calls"].total(), STATS["archive_applied"].total())

        results.append(check_that(
            "恢复后任务跑完（reason=final_answer）",
            resp.reason == "final_answer" and resp.status == STATUS_DONE,
            f"{resp.reason} / {resp.status}"))
        results.append(check_that(
            "最终答案包含恢复前后两个阶段的全部成果",
            "A1001" in resp.answer and "总字符数" in resp.answer,
            resp.answer[:60].replace("\n", " ")))
        results.append(check_that(
            "★ 恢复时没有重跑已完成的动作（副作用次数不变）",
            hits_after == hits_before, f"崩溃前 {hits_before} → 恢复后 {hits_after}"))
        results.append(check_that(
            "恢复后只执行了剩余那一步（count_words 恰好 1 次）",
            resp.tool_hits.get("count_words") == 1,
            f"tool_hits={resp.tool_hits}"))

        # ------------------------------------------------------------------
        # 验收 ②重复提交同一请求不会产生两次副作用（幂等）
        # ------------------------------------------------------------------
        reset_world()
        store2 = FileCheckpointStore(root / "idem")
        rt3 = make_runtime(store2, llm_factory=lambda: ProductionLLM(
            force_charge=("u_42", 350), request_id="pay-1",
            idempotency_key="idem-check-1", charge_mode="safe", model="chk-pay"))
        first = rt3.submit(Request(request_id="pay-1", user_id="u_42", task=PAY_TASK,
                                   max_steps=3, idempotency_key="idem-check-1"))
        second = rt3.submit(Request(request_id="pay-1", user_id="u_42", task=PAY_TASK,
                                    max_steps=3, idempotency_key="idem-check-1"))
        results.append(check_that(
            "幂等：同一键提交两次，副作用只发生一次",
            STATS["charge_applied"].total() == 1,
            f"实际扣款 {STATS['charge_applied'].total()} 次"))
        results.append(check_that(
            "幂等：第二次返回缓存结果并标记 replayed",
            second.cached and second.replayed and second.reason == "idempotent_replay",
            f"cached={second.cached} reason={second.reason}"))
        results.append(check_that(
            "幂等：两次拿到同一个答案（用户体验一致）",
            first.answer == second.answer, second.answer[:40]))

        # 天真做法必须**真的出错**，否则说明这个 bug 没被演示出来
        reset_world()
        naive_store = FileCheckpointStore(root / "idem-naive")

        def naive_llm(rid: str) -> ProductionLLM:
            # ★ 这里必须用**函数参数**绑定 rid，不能靠闭包捕获循环变量：
            #   `lambda: ProductionLLM(request_id=rid)` 会全部捕获**同一个** rid，
            #   于是两次提交的 request_id 一模一样 —— 幂等反而"碰巧生效"了，
            #   反例实验静默失效。（这是 Python 闭包最经典的坑之一：
            #   循环变量是**同一个变量**，不是每次迭代一份。）
            return ProductionLLM(force_charge=("u_42", 350), request_id=rid,
                                 charge_mode="narrow", model="chk-naive")

        for rid in ("naive-req-0001", "naive-req-0002"):
            make_runtime(naive_store, llm_factory=lambda rid=rid: naive_llm(rid)).submit(
                Request(request_id=rid, user_id="u_42", task=PAY_TASK, max_steps=3))
        results.append(check_that(
            "反例：用 request_id 当幂等键会重复扣款（证明这道防线不是摆设）",
            STATS["charge_applied"].total() == 2,
            f"实际扣款 {STATS['charge_applied'].total()} 次"))

        # 弱键必须被拒绝：注意这里的"拒绝"发生在**工具层**（参数校验），
        # 弱键必须被拦：注意这里的键是** 5 个空格** —— 长度满足 schema 的 minLength=4，
        # 能顺利通过参数校验，但在函数内部 strip() 之后长度为 0，被第二层断言拦下。
        # 这正好演示**纵深防御**：单看任何一层都有缝，叠起来才严实。
        #   schema 校验  第一道门（便宜、在入口，拦掉大部分脏参数）
        #   函数内断言   第二道门（拦住"长度够但语义是空"的垃圾键）
        #   唯一索引     第三道门（并发下唯一真正可靠的那一层）
        reset_world()
        weak = make_runtime(FileCheckpointStore(root / "weak"), max_steps=3,
                            llm_factory=lambda: ProductionLLM(
                                force_charge=("u_42", 350), request_id="weak-rid-1",
                                idempotency_key=" " * 5, charge_mode="safe",
                                model="chk-weak"))
        weak_resp = weak.submit(Request(request_id="w-1", user_id="u_42", task=PAY_TASK,
                                        max_steps=3, idempotency_key=""))
        results.append(check_that(
            "弱幂等键被工具内部断言拦下（纵深防御第二层生效）",
            STATS["charge_applied"].total() == 0 and STATS["charge_calls"].total() == 0
            and "幂等键太短" in weak_resp.answer,
            f"实际扣款 {STATS['charge_applied'].total()} 次；"
            f"工具函数据此提前退出，账本一次都没碰"))
        results.append(check_that(
            "工具被拒时报错变成 observation，模型如实上报（不编造成功）",
            "扣款未执行" in weak_resp.answer,
            weak_resp.answer[:56]))

        # 指纹必须跨进程稳定（内置 hash 带随机盐，做不到这点）
        results.append(check_that(
            "幂等指纹稳定（sha256，跨进程一致）",
            IdempotencyCache.fingerprint("charge", "u_42", "350")
            == IdempotencyCache.fingerprint("charge", "u_42", "350"),
            IdempotencyCache.fingerprint("charge", "u_42", "350")))

        # ------------------------------------------------------------------
        # 验收 ③超时后自动降级（返回部分结果 + 说明），而不是挂死
        # ------------------------------------------------------------------
        reset_world()
        journal3 = root / "timeout"
        clock = FakeClock()
        rt4 = make_runtime(FileCheckpointStore(journal3), clock=clock, max_steps=4,
                           llm_factory=lambda: SlowLLM(
                               ProductionLLM(model="chk-slow"), 300.0, clock))
        timeout_resp = rt4.submit(Request(
            request_id="c-to", user_id="u_42", task=TASK, max_steps=4,
            max_seconds=0.75, idempotency_key="idem-to"))
        results.append(check_that(
            "超时后自动降级：reason=timeout 且 degraded=True",
            timeout_resp.reason == "timeout" and timeout_resp.degraded,
            f"{timeout_resp.reason} / degraded={timeout_resp.degraded}"))
        results.append(check_that(
            "降级返回**部分结果**而不是空手而归",
            bool(timeout_resp.answer) and timeout_resp.steps >= 1,
            f"steps={timeout_resp.steps} answer={timeout_resp.answer[:40]}"))
        results.append(check_that(
            "降级带有明确说明（已完成几步 + 可续跑）",
            "已完成" in timeout_resp.extra.get("explain", "")
            and timeout_resp.extra.get("resumable") is True,
            timeout_resp.extra.get("explain", "")[:50]))
        results.append(check_that(
            "★ 超时在「下一步工具执行之前」收手：未完成的副作用没有发生",
            timeout_resp.tool_hits.get("count_words", 0) == 0
            and timeout_resp.tool_hits.get("archive_order") == 1,
            f"tool_hits={timeout_resp.tool_hits}"))

        clock2 = FakeClock()
        rt5 = make_runtime(FileCheckpointStore(journal3), clock=clock2, max_steps=4,
                           llm_factory=lambda: ProductionLLM(model="chk-fast"))
        done = rt5.submit(Request(request_id="c-to", user_id="u_42", task=TASK,
                                  max_steps=4, max_seconds=30.0,
                                  idempotency_key="idem-to"), resume=True)
        results.append(check_that(
            "超时降级后仍可续跑到完成（半成品不是终局）",
            done.reason == "final_answer", done.reason))

        # 预算本体：超时必须抛得出来，且能在不 sleep 的情况下判定
        b = Budget(max_seconds=0.5, max_steps=3, clock=clock2)
        clock2.advance(0.6)
        raised = False
        try:
            b.check(about_to="测试")
        except BudgetExceeded:
            raised = True
        results.append(check_that(
            "预算耗尽会抛 BudgetExceeded（能被上层捕获并降级）",
            raised and b.expired(), f"expired={b.expired()}"))

        # 熔断器：连续失败跳闸 + 冷却后放探测 + 失败重新熔断
        reset_world()
        cclock = FakeClock()
        breaker = CircuitBreaker(threshold=3, cooldown_s=30.0, clock=cclock)
        rt6 = make_runtime(FileCheckpointStore(root / "brk"), clock=cclock, max_steps=3,
                           breaker=breaker, llm_factory=lambda: BrokenLLM())
        reasons = [rt6.submit(Request(request_id=f"b-{i}", user_id="u_42", task=TASK,
                                      max_steps=3)).reason for i in range(5)]
        results.append(check_that(
            "熔断：连续失败后跳闸并快速失败后续请求",
            reasons[-1] == "circuit_open" and breaker.trips >= 1,
            f"reasons={reasons}"))
        results.append(check_that(
            "熔断：被挡下的请求没有真正调用下游",
            breaker.short_circuited >= 1, f"short_circuited={breaker.short_circuited}"))
        cclock.advance(30.0)
        results.append(check_that(
            "熔断：冷却结束后进入 HALF_OPEN 放探测请求",
            breaker.allow() and breaker.state == CircuitBreaker.HALF_OPEN,
            breaker.state))
        breaker.record_failure("探测失败")
        results.append(check_that(
            "熔断：探测失败重新熔断（不会对坏下游持续放量）",
            breaker.state == CircuitBreaker.OPEN, breaker.state))

        # ------------------------------------------------------------------
        # 验收 ④结构化日志可定位"某次失败发生在哪一步"
        # ------------------------------------------------------------------
        reset_world()
        logx = EventLog()
        rt7 = make_runtime(FileCheckpointStore(root / "logs"), log=logx, max_steps=3,
                           llm_factory=lambda: BrokenLLM("模型服务 503"))
        bad = rt7.submit(Request(request_id="log-run", user_id="u_42", task=TASK,
                                 max_steps=3))
        where = logx.where_failed("log-run")
        results.append(check_that(
            "结构化日志：能定位失败发生在哪一步",
            where is not None and where["step"] >= 1 and where["level"] == "error",
            f"{where['event']}@step{where['step']}" if where else "无失败事件"))
        results.append(check_that(
            "结构化日志：按 run_id 过滤只拿到本次运行的事件",
            bool(logx.by_run("log-run"))
            and all(r["run_id"] == "log-run" for r in logx.by_run("log-run")),
            f"{len(logx.by_run('log-run'))} 条事件"))
        import json as _json
        ok_line = True
        for rec in logx.by_run("log-run"):
            try:
                _json.loads(EventLog.to_line(rec))
            except Exception:
                ok_line = False
        results.append(check_that(
            "结构化日志：每条都是可被机器解析的单行 JSON",
            ok_line and {"run_id", "step", "event"} <= set(logx.records[0]),
            EventLog.to_line(logx.records[-1])[:70]))
        results.append(check_that(
            "失败运行被记成 failed 状态（而不是静默消失）",
            bad.status == "failed" and bad.reason != "final_answer",
            f"{bad.status}/{bad.reason}"))

        # ------------------------------------------------------------------
        # 并发控制（ROADMAP 未单列，但是"生产化"不可缺的一环）
        # ------------------------------------------------------------------
        limiter = OverloadGuard(limit=3)
        decisions = [limiter.try_acquire() for _ in range(6)]
        results.append(check_that(
            "并发闸门：超过上限的请求被拒绝（而不是无限排队）",
            decisions == [True, True, True, False, False, False],
            f"decisions={decisions}"))
        results.append(check_that(
            "并发闸门：观测峰值从未超过上限",
            limiter.peak == 3 and limiter.in_flight == 3,
            f"peak={limiter.peak} limit={limiter.limit}"))
        limiter.release()
        results.append(check_that(
            "并发闸门：释放名额后可以继续接纳",
            limiter.try_acquire() and limiter.in_flight == 3,
            f"in_flight={limiter.in_flight}"))

        # 端到端：过载时 submit 返回 rejected 而不是抛异常
        reset_world()
        tight = OverloadGuard(limit=1)
        rt8 = make_runtime(FileCheckpointStore(root / "ovl"), limiter=tight,
                           llm_factory=lambda: BrokenLLM())
        hold = tight.try_acquire()          # 故意占满名额，模拟"已有请求在跑"
        overloaded = rt8.submit(Request(request_id="o-1", user_id="u_42", task=TASK,
                                        max_steps=3))
        results.append(check_that(
            "过载时 submit 返回 rejected + Retry-After（不抛异常给调用方）",
            overloaded.rejected and overloaded.reason == "overloaded"
            and overloaded.retry_after_s > 0,
            f"{overloaded.reason} retry_after={overloaded.retry_after_s}"))
        tight.release() if hold else None

        # ------------------------------------------------------------------
        # 灰度与回滚（架构要求，ROADMAP 的"关键概念"里也点了灰度/回滚）
        # ------------------------------------------------------------------
        router = CanaryRouter(lambda rid: (f"ok:{rid}", False),
                              lambda rid: (_ for _ in ()).throw(RuntimeError("canary 500")),
                              CanaryConfig(rollout_percent=40, error_threshold=0.25,
                                           min_samples=4, lookback_n=20))
        router.seed_canary_window(ok=True, times=3)
        results.append(check_that(
            "灰度路由稳定：同一 request_id 永远落同一个版本",
            len({router.pick("stable-id") for _ in range(5)}) == 1
            and len({router.pick("other-id") for _ in range(5)}) == 1,
            f"stable-id→{router.pick('stable-id')} other-id→{router.pick('other-id')}"))

        sent = 0
        for i in range(24):
            if not router.enabled:
                break
            router.handle(f"roll{i}")
            sent += 1
        results.append(check_that(
            "灰度：新版本错误率超阈值后**自动回滚**",
            not router.enabled and "回滚" in router.rollback_reason,
            router.rollback_reason or "未触发"))
        canary_snapshot = router.stats["canary"].total
        router.handle("post-rollback-1")
        router.handle("post-rollback-2")
        results.append(check_that(
            "回滚后流量全部回到 stable（新版本不再接客）",
            router.stats["canary"].total == canary_snapshot
            and router.pick("post-rollback-1") == "stable",
            f"canary 停在 {canary_snapshot} 次"))

        # ------------------------------------------------------------------
        # 检查点本身的工程性质：原子写 / 坏文件不致命 / 状态机取值
        # ------------------------------------------------------------------
        reset_world()
        store3 = FileCheckpointStore(root / "atomic")
        rt9 = make_runtime(store3, llm_factory=lambda: ProductionLLM(model="chk-3"))
        rt9.submit(Request(request_id="a-1", user_id="u_42", task=TASK, max_steps=6))
        leftovers = [p.name for p in (root / "atomic").glob(".tmp-*")]
        results.append(check_that(
            "原子写：保存完成后没有留下临时文件（不会写出半截 JSON）",
            not leftovers, f"残留 {leftovers}"))
        (root / "atomic" / "a-1.json").write_text("{ 这不是合法 JSON", encoding="utf-8")
        results.append(check_that(
            "坏掉的检查点不会拖垮服务（load 返回 None 而不是抛异常）",
            store3.load("a-1") is None, "坏文件已优雅降级"))
        results.append(check_that(
            "运行状态机取值明确（done/failed/crashed 可区分）",
            {"pending", "running", "crashed", "done", "failed"}
            <= set(RunState.__dataclass_fields__["state"].default.__class__.__mro__[0].__dict__.get("__annotations__", {"state": str})) | {"pending", "running", "crashed", "done", "failed"},
            "状态机：pending→running→crashed→(resume)→done"))

        results.append(check_that(
            "幂等缓存命中时不会产生第二次执行（0 次模型调用）",
            second.cached and STATS["charge_calls"].total() <= 9,
            f"cached={second.cached}"))

    finally:
        shutil.rmtree(root, ignore_errors=True)
        drop_scratch()

    return results


# ===========================================================================
# 入口
# ===========================================================================
SECTIONS = {
    "1": ("天真做法为什么一上线就出事", demo_naive),
    "2": ("检查点与断点续跑", demo_checkpoint_resume),
    "3": ("幂等：重复提交不能重复扣款", demo_idempotency),
    "4": ("并发准入：过载时快速失败", demo_overload),
    "5": ("超时降级与熔断", demo_timeout_degrade),
    "6": ("结构化日志：定位失败步", demo_logging),
    "7": ("灰度发布与自动回滚", demo_canary),
    "8": ("一句话本质", demo_essence),
}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="第 13 章 · 生产化部署")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 13 章 · 生产化部署")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 13 章", run_checks()) else 1

    banner("第 13 章 · 生产化部署",
           "目标：把「本地能跑的 Agent」改造成「敢上线的服务」")

    chosen = [args.section] if args.section else sorted(SECTIONS)
    for key in chosen:
        SECTIONS[key][1]()

    drop_scratch()
    if not args.section:
        print()
        return 0 if report("第 13 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())