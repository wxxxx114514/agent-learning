r"""第 08 章 · 练习 4 / 5 · 给 Envelope 加 trace_id 和 elapsed_ms

【要做什么】
  **给 `Envelope` 加 `trace_id` 和 `elapsed_ms`。**
  然后写一句话回答：为什么这两个字段必须从第一天就有？

【已经给你了】
  · TracedEnvelope：Envelope 的子类，已经把这两个字段加上去了（frozen dataclass）
  · build_traced_team()：用带标记的消息总线组装一支完整的团队（数据/政策/文案三个专家）
  · TracedBus：消息总线的子类 —— **唯一要写的就是它的 send()**
  · 一次运行的消息日志会被完整打印出来（谁发的、耗时多少）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch08_multi_agent\ex4_trace_id.py
  3. 验收本章：py scripts\run_all_checks.py 08
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                          # noqa: E402
from stages.stage08_multi_agent.demo import (                            # noqa: E402
    POLICY_RULES, TICKET, DataAnalystLLM, DataWorker, Envelope, MessageBus,
    PolicyExpertLLM, PolicyWorker, ReplyWorker, ReplyWriterLLM, Supervisor,
    SupervisorResult,
)

TRACE_ID = "trace-0001"


@dataclass(frozen=True)
class TracedEnvelope(Envelope):
    """Envelope + 题面要求你加的两个字段。

    继承过来之后，`sender / recipient / topic / payload / round` 全都在，
    render() 覆盖成带 trace 信息的版本。
    """

    trace_id: str = "-"
    elapsed_ms: float = 0.0

    def render(self) -> str:
        return (f"({self.trace_id} +{self.elapsed_ms:6.1f}ms) "
                f"[R{self.round}] {self.sender} → {self.recipient} ({self.topic}) {self.payload}")


def build_traced_team(bus: "TracedBus") -> Supervisor:
    """和课程 demo 的 build_team() 一样，只是总线换成了你的 TracedBus。不用改。"""
    return Supervisor(
        bus=bus,
        data=DataWorker(DataAnalystLLM(), "你是数据专家，只负责查证订单与物流事实，不做判断。"),
        policy=PolicyWorker(PolicyExpertLLM(),
                            "你是赔付政策专家，只负责条款匹配。条款：\n"
                            + "\n".join(f"{r.code}｜{r.match}｜{r.action}" for r in POLICY_RULES)),
        reply=ReplyWorker(ReplyWriterLLM(),
                          "你是客服文案专家，只负责把已确认的结论写成对客户的话术。"
                          "严禁添加未确认的承诺，严禁提及任何内部信息。"),
        max_rounds=3,
    )


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class TracedBus(MessageBus):
    """带「关联键」和「耗时」的消息总线。

    主管发消息时只知道自己发了什么（Envelope），
    是**总线的责任**把 trace_id 和 elapsed_ms 盖上去 —— 所以这件事只需要改一个地方。
    """

    def __init__(self, trace_id: str = TRACE_ID) -> None:
        super().__init__()
        self.trace_id = trace_id
        self.t0 = time.perf_counter()          # 计时起点，已经给你了

    def send(self, env: Envelope) -> Envelope:
        # TODO ① ── 把进来的 Envelope 换成 TracedEnvelope 再入账。
        #   提示（一行就能写完）：
        #       stamped = TracedEnvelope(env.sender, env.recipient, env.topic, env.payload,
        #                                env.round, self.trace_id,
        #                                (time.perf_counter() - self.t0) * 1000)
        #       return super().send(stamped)
        #   ★ 注意：两个新字段必须是**消息产生的那一刻**盖上去的 —— 这正是「事后补不上」的原因。
        #   ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 4 · TODO ①  TracedBus.send")
        #   ↑↑↑ 你的答案 ↑↑↑


def my_conclusion() -> str:
    """TODO ② ── 写一句话：为什么 trace_id 和 elapsed_ms 必须从第一天就有？

    提示：trace_id 是把一次运行的**所有**消息串起来的关联键
          （真实系统里它就是 OpenTelemetry 的 trace_id）；elapsed_ms 是性能回归的第一手证据。
    """
    # 写下你的结论：
    #
    #   ↓↓↓ 把下面这行删掉，写上 return "你的结论" ↓↓↓
    raise NotImplementedError("练习 4 · TODO ②  写下你的结论")
    # ↑↑↑ 你的答案 ↑↑↑
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def check() -> str:
    print("\n" + "=" * 66)
    print(f"  一次完整的团队运行，消息带上 trace_id = {TRACE_ID}")
    print("=" * 66)

    bus = TracedBus(TRACE_ID)
    supervisor = build_traced_team(bus)
    result: SupervisorResult = supervisor.run(TICKET)

    for env in result.envelopes:
        print(f"    {env.render()[:104]}")
    print()

    unstamped = [e for e in result.envelopes
                 if not isinstance(e, TracedEnvelope)
                 or e.trace_id != TRACE_ID
                 or e.elapsed_ms <= 0]
    if unstamped:
        raise NotImplementedError(
            f"练习 4 · TODO ① 还有 {len(unstamped)}/{len(result.envelopes)} 条消息没盖上传记"
            "（trace_id / elapsed_ms 缺失）")

    times = [e.elapsed_ms for e in result.envelopes]
    if times != sorted(times):
        warn("耗时不是单调递增的？检查一下是不是忘了用同一次运行的计时起点（self.t0）。")
    slowest = max(result.envelopes, key=lambda e: e.elapsed_ms)
    gaps = [(b.elapsed_ms - a.elapsed_ms, b) for a, b in zip(result.envelopes, result.envelopes[1:])]
    gap, after = max(gaps, key=lambda t: t[0]) if gaps else (0.0, slowest)

    kv("消息条数", f"{len(result.envelopes)}")
    kv("带同一个 trace_id 的消息", f"{sum(1 for e in result.envelopes if e.trace_id == TRACE_ID)}"
                                  f"/{len(result.envelopes)}")
    kv("最慢的一步", f"{after.sender} → {after.recipient}（{after.topic}）用掉 {gap:.1f}ms")
    kv("整轮总耗时", f"{times[-1]:.1f}ms")
    kv("仲裁结论", result.decision)
    print()
    note("有了 trace_id，出问题时你可以把**一次运行的所有消息**捞出来按顺序回放；")
    note("有了 elapsed_ms，你能一眼看出是模型慢了，还是某个专家慢了。")
    warn("事后补是补不上的：你不可能回头给已经跑过的消息补一个「当时」的 id 和时间。")
    bullet("这两个字段必须在**消息产生的那一刻**写进去 —— 所以它们要进 Envelope 的定义。")
    bullet("真实系统里对应 OpenTelemetry 的 trace_id / span 时长（第 10、13 章会反复用它）。")

    conclusion = my_conclusion().strip()
    if len(conclusion) < 8:
        raise NotImplementedError("练习 4 · TODO ② 结论太短了，把「串联」和「性能证据」都写上")
    print()
    kv("你的结论", conclusion)
    return f"{len(result.envelopes)} 条消息全部带 trace_id 与耗时；最慢一步 {gap:.1f}ms"


def main() -> int:
    try:
        summary = check()
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    print()
    print(f"  → {summary}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
