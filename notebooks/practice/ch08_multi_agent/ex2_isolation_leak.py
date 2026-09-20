r"""第 08 章 · 练习 2 / 5 · 让隔离「漏一点」，看哪几条断言变红（必做）

【要做什么】
  **让隔离「漏一点」，看哪几条断言变红（必做）。**
  把 `_ask_policy()` 里的 `facts_text` 换成数据专家的**原始输出**
  （也就是把内部备注一起转发给政策专家），重跑隔离验收。
  观察：哪几条 ✅ 变成了 ❌？

【已经给你了】
  · run_safe()：课程原版（安全）的团队 + 跑一次
  · isolated_checks()：5 条隔离断言（和课程 demo 里的一样）—— 你要观察的就是它们的红绿
  · LeakySupervisor：主管的子类，`_ask_policy()` 抄自原版，只把 facts_text 那一行留成 TODO
  · 三个专家模型 / Worker 类 / Envelope / MessageBus / verify_reply 都是课程原件

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch08_multi_agent\ex2_isolation_leak.py
  3. 验收本章：py scripts\run_all_checks.py 08
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                          # noqa: E402
from stages.stage08_multi_agent.demo import (                            # noqa: E402
    POLICY_RULES, TICKET, DataAnalystLLM, DataWorker, Envelope, MessageBus,
    PolicyExpertLLM, PolicyWorker, ReplyWorker, ReplyWriterLLM, Supervisor,
    SupervisorResult, WorkerReport, build_team, verify_reply,
)

SYSTEM_DATA = "你是数据专家，只负责查证订单与物流事实，不做判断。"
SYSTEM_POLICY = ("你是赔付政策专家，只负责条款匹配。条款：\n"
                 + "\n".join(f"{r.code}｜{r.match}｜{r.action}" for r in POLICY_RULES))
SYSTEM_REPLY = ("你是客服文案专家，只负责把已确认的结论写成对客户的话术。"
                "严禁添加未确认的承诺，严禁提及任何内部信息。")


def run_safe() -> tuple[Supervisor, SupervisorResult]:
    """安全版：主管只把结构化 facts 转发给政策专家。不用改。"""
    _bus, supervisor = build_team()
    return supervisor, supervisor.run(TICKET)


def isolated_checks(workers: dict, result: SupervisorResult) -> list[tuple[str, bool]]:
    """5 条隔离断言 —— 这就是「回归测试」的样子。不用改。"""
    reply_ctx = "\n".join(workers["reply"].contexts)
    policy_ctx = "\n".join(workers["policy"].contexts)
    return [
        ("文案专家没看到内部备注", "内部备注" not in reply_ctx),
        ("文案专家没看到订单原文（运单号）", "运单号" not in reply_ctx),
        ("政策专家没看到内部备注", "内部备注" not in policy_ctx),
        ("政策专家拿到了结构化事实（延迟小时数）", "延迟小时数" in policy_ctx),
        ("最终回复可以对外发送（无合规问题）", not verify_reply(result.final_reply)),
    ]


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class LeakySupervisor(Supervisor):
    """把隔离「漏一点」：政策专家拿到的不是结构化事实，而是数据专家的原话。"""

    def _ask_policy(self, data_report: WorkerReport, rounds: int) -> WorkerReport:
        # TODO ① ── 就改这一行：把「结构化事实」换成「数据专家的原始输出」。
        #   安全写法（别抄它，它现在就在注释里）：
        #       facts_text = "\n".join(f"- {k}：{v}" for k, v in data_report.facts.items())
        #   漏一点的写法：从数据专家上一次的**原话**里取 —— self.workers["data"].outputs[-1]
        #   （那句原话里带着「内部备注：…（内部数据，勿外传）」，这正是要观察的泄漏）
        #   ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 2 · TODO ①  把 facts_text 换成数据专家的原始输出")
        #   ↑↑↑ 你的答案 ↑↑↑
        self.bus.send(Envelope("supervisor", "policy", "task",
                               f"请依据条款判断本单处理方案。（随附事实 {len(data_report.facts)} 项）", rounds))
        report = self.workers["policy"].handle(
            f"请判断订单 {TICKET.order_id} 是否应赔付。\n已知事实：\n{facts_text}")
        self.bus.send(Envelope("policy", "supervisor", "result", report.conclusion, rounds))
        return report
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def run_leaky() -> tuple[LeakySupervisor, SupervisorResult]:
    """漏一点版：和 build_team() 一样的组装，只是主管换成了 LeakySupervisor。不用改。"""
    bus = MessageBus()
    supervisor = LeakySupervisor(
        bus=bus,
        data=DataWorker(DataAnalystLLM(), SYSTEM_DATA),
        policy=PolicyWorker(PolicyExpertLLM(), SYSTEM_POLICY),
        reply=ReplyWorker(ReplyWriterLLM(), SYSTEM_REPLY),
        max_rounds=3,
    )
    return supervisor, supervisor.run(TICKET)


def check() -> str:
    print("\n" + "=" * 66)
    print("  隔离验收：课程原版 vs 漏一点版（同一条工单）")
    print("=" * 66)

    safe, safe_r = run_safe()
    leaky, leaky_r = run_leaky()
    rows_safe = isolated_checks(safe.workers, safe_r)
    rows_leak = isolated_checks(leaky.workers, leaky_r)

    print(f"  {'断言':<36}{'隔离版':<8}{'漏一点版'}")
    print("  " + "-" * 58)
    flipped: list[str] = []
    for (name, ok_safe), (_name, ok_leak) in zip(rows_safe, rows_leak):
        print(f"  {name:<36}{'✅' if ok_safe else '❌':<8}{'✅' if ok_leak else '❌'}")
        if ok_safe and not ok_leak:
            flipped.append(name)
    print()

    policy_ctx = "\n".join(leaky.workers["policy"].contexts)
    safe_policy_chars = len("\n".join(safe.workers["policy"].contexts))
    if "内部备注" not in policy_ctx:
        raise NotImplementedError(
            "练习 2 · TODO ① 还没漏：政策专家的上下文里没有内部备注（原始输出没转发过去）")

    kv("政策专家这次看到的字符数", f"{len(policy_ctx)}（隔离版 {safe_policy_chars}）")
    kv("漏一点版的仲裁结论", leaky_r.decision)
    kv("变红的断言", f"{len(flipped)} 条：{'；'.join(flipped)}")
    print()
    note("为什么政策专家会给出不同的条款？它的输入从「- 键：值」变成了自由文本，")
    note("于是它解析不到「状态 / 轨迹 / 延迟小时数」这几个字段 —— 判断自然就错了。")
    warn("顺手想一想：如果代码里没有这条断言，这个改动会在什么时候被发现？")
    warn("—— 大概率是客户投诉的时候。**这就是回归测试的价值。**")
    bullet("隔离不是靠提示词「请不要泄露」实现的，而是靠**结构**：只传它需要的最小信息。")
    bullet("传「结论」（结构化 facts）而不是「上下文」（原始输出）—— 省钱和防泄露是同一个动作。")
    return f"漏一点后变红 {len(flipped)} 条：{'、'.join(flipped)}"


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
