r"""第 13 章 · 练习 4 / 5 · 把并发闸门的参数改一遍，并回答一个设计问题

【要做什么】
  **把并发闸门的参数改一遍，并回答一个设计问题。**

  把 ⑤ 的 `LIMIT` 从 5 改成 2，再改成 10，各跑一次，比较「峰值」「被拒绝」「新接入」三列。

  然后回答：为什么闸门必须放在**调模型之前**？
  如果放在「模型返回之后」再检查，会发生什么？

【已经给你了】
  · 第 13 章真正的闸门：`OverloadGuard`（runtime.py，`limit` / `try_acquire()` / `release()` /
    `snapshot()`），以及 `ProductionRuntime.submit` 真实的 429 行为
  · `burst(limit)`：把闸门放进一段突发流量里跑 10 个 tick，返回每一 tick 的三列
  · `CountingEngine`：一个假引擎，被调用几次就记几次（用来证明「模型调用根本没发生」）
  · `end_to_end(limit)`：占满闸门 → 提交一次请求 → 再放开一个名额提交一次

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch13_production\ex4_overload_gate.py
  3. 验收本章：py scripts\run_all_checks.py 13
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage13_production.journal import (  # noqa: E402
    InMemoryCheckpointStore, Request,
)
from stages.stage13_production.runtime import (  # noqa: E402
    OverloadGuard, ProductionRuntime, RunOutcome,
)

LIMIT = 5            # ← 试着改这里：2 会拒绝得更多，10 峰值更高
ARRIVALS = 4         # 每个 tick 突发几个请求
JOB_TICKS = 3        # 一次模型调用占几个 tick（= 一个请求要占住连接多久）


def table(headers: list[str], rows: list[list[str]], indent: int = 2) -> None:
    """极简表格：按**显示宽度**对齐，中日韩字符占 2 列（已经写好，不用改）。

    课程零第三方依赖，所以不引入 rich / tabulate —— 十几行自己画一个就够。
    """

    def width(text: str) -> int:
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)

    def pad(text: str, n: int) -> str:
        return text + " " * max(0, n - width(text))

    widths = [max([width(h)] + [width(r[i]) for r in rows]) for i, h in enumerate(headers)]
    print(" " * indent + "  ".join(pad(h, widths[i]) for i, h in enumerate(headers)))
    print(" " * indent + "  ".join("-" * w for w in widths))
    for r in rows:
        print(" " * indent + "  ".join(pad(c, widths[i]) for i, c in enumerate(r)))


def burst(limit: int, ticks: int = 10) -> dict:
    """把真闸门放进一段突发流量里跑一遍（已经写好，不用改）。

    每个 tick：到期的请求先释放名额 → 新到的 ARRIVALS 个请求过闸门 → 时间前进。
    返回 {"rows": [...], "snap": 闸门快照}
    """
    gate = OverloadGuard(limit=limit)
    rows, running = [], []          # running 里每个元素 = {"left": 还剩几个 tick}
    for tick in range(1, ticks + 1):
        done = [r for r in running if r["left"] <= 0]
        running = [r for r in running if r["left"] > 0]
        for _ in done:
            gate.release()
        admitted = 0
        for _ in range(ARRIVALS):
            if gate.try_acquire():
                running.append({"left": JOB_TICKS})
                admitted += 1
        for r in running:
            r["left"] -= 1
        rows.append([str(tick), str(gate.in_flight), str(admitted),
                     str(gate.rejected), str(gate.peak)])
    return {"rows": rows, "snap": gate.snapshot()}


class CountingEngine:
    """假引擎：被调用几次就记几次（已经写好，不用改）。

    ★ 它就是「模型调用到底发生了没有」的唯一证据 —— 看日志会被 429 刷屏，
      但只有这个计数器能证明「钱一分都没花」。
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, state, *, remaining: int, resume: bool = False, crash_at=None) -> RunOutcome:
        self.calls += 1
        return RunOutcome(answer="已处理", stop_reason="final_answer", steps_done=1)


def end_to_end(limit: int) -> dict:
    """占满闸门 → 提交一次 → 再放开一个名额提交一次（已经写好，不用改）。"""
    engine = CountingEngine()
    rt = ProductionRuntime(engine, InMemoryCheckpointStore(),
                           limiter=OverloadGuard(limit=limit))
    fill_the_gate(rt, limit)                       # ← 你的答案在这里生效
    resp = rt.submit(Request(request_id="run-429", user_id="u_42", task="随便问点什么"))
    calls_after_reject = engine.calls
    rt.limiter.release()                           # 一个请求跑完了，名额还回去
    resp2 = rt.submit(Request(request_id="run-ok", user_id="u_42", task="再来一次"))
    return {"reason": resp.reason, "rejected": resp.rejected,
            "retry_after_s": resp.retry_after_s, "note": resp.extra.get("note", ""),
            "calls_after_reject": calls_after_reject, "engine_calls": engine.calls,
            "reason2": resp2.reason}


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def fill_the_gate(runtime: ProductionRuntime, limit: int) -> None:
    """TODO ① ── 模拟「已经有 limit 个请求正在跑」：把运行时的并发闸门占满。

    要求：占满之后，下一个 `submit()` 必须**被闸门挡住**，
          而且引擎（= 模型调用）**一次都不能被调用**。
    提示：`runtime.limiter` 上只有两个原语：一个占名额（返回 bool），一个放名额。
          占满就是循环 limit 次；顺手 `assert` 一下每次都占到了（占不到说明 limit 传错了）。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO ①  fill_the_gate")
    # ↑↑↑ 你的答案 ↑↑↑


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   为什么闸门必须放在「调模型之前」？放在「模型返回之后」再检查会怎样？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        # ① 三档 LIMIT 的对照表
        print(f"    每个 tick 突发 {ARRIVALS} 个请求，一次模型调用占 {JOB_TICKS} 个 tick")
        print()
        snaps = {}
        for limit in (2, LIMIT, 10):
            result = burst(limit)
            snaps[limit] = result["snap"]
            if limit == LIMIT:              # 逐 tick 的细节只打一档（三档都一样长，会刷屏）
                table([f"LIMIT={limit} · tick", "在飞", "新接入", "被拒绝", "峰值"], result["rows"])
                print()
        for limit, snap in snaps.items():
            assert snap["peak"] <= limit, f"LIMIT={limit} 时峰值冲到 {snap['peak']} —— 闸门漏了"
        assert snaps[2]["rejected"] > snaps[10]["rejected"], "LIMIT 越小，拒绝应该越多"
        table(["LIMIT", "峰值", "新接入", "被拒绝"],
              [[str(k), str(v["peak"]), str(v["acquired"]), str(v["rejected"])]
               for k, v in snaps.items()])
        print()
        print("    ★ 峰值**永远不超过 LIMIT** —— 不管外面来多少，这就是闸门的全部意义。")
        print("    ★ LIMIT 越小：保护更强、拒绝更多（体验更差）；越大则相反。")
        print("      这个值就是「容量规划」那根线，由压测 + 模型端的限流配额共同决定。")
        print()

        # ② 端到端：真的被 429 挡住，而且引擎一次都没被调用
        e2e = end_to_end(LIMIT)
        print(f"    ② 闸门占满后再提交一次（LIMIT={LIMIT}）")
        print(f"       reason={e2e['reason']!r}  rejected={e2e['rejected']}  "
              f"retry_after_s={e2e['retry_after_s']}")
        print(f"       模型调用次数：{e2e['calls_after_reject']}  ← 期望 0")
        assert e2e["reason"] == "overloaded", f"应该返回 overloaded，实际 {e2e['reason']!r}"
        assert e2e["rejected"] is True, "被拒绝的请求必须显式标记 rejected"
        assert e2e["retry_after_s"] > 0, "必须告诉调用方「多久之后可以重试」"
        assert e2e["calls_after_reject"] == 0, "被挡住时引擎绝不该被调用（钱一分没花）"
        print("       ★ 这就是「快速拒绝」：0 秒返回 429 + Retry-After，")
        print("         而不是把请求堆在队列里等 3 分钟再超时 —— 排队只是把过载变成必然超时。")
        print()

        # ③ 名额还回去之后，闸门重新放行
        print(f"    ③ 一个请求跑完、名额还回去之后再提交")
        print(f"       reason={e2e['reason2']!r}，模型调用累计 {e2e['engine_calls']} 次")
        assert e2e["reason2"] == "final_answer", "名额释放后应该能正常执行"
        assert e2e["engine_calls"] == 1, "只有第二条请求真正跑到了引擎"
        print("       ★ 闸门是「限流」不是「关机」：名额回来，服务照常。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print()
    print("    ★ 关于「为什么必须在调模型之前」：")
    print("      放在模型返回之后再检查，等于连接已经占上了、模型调用已经发生了、钱已经花了，")
    print("      你再拒绝只是「拒绝把结果给用户」—— 该占的资源一个都没省下。")
    print("      准入控制的价值就在于「**在花钱之前**就挡住」。")
    print()
    print("    ⚠️ 另外记住：闸门是纯确定性代码，一个模型调用都不花（第 09 章那句：")
    print("       能用确定性代码解决的，绝不用模型）。")
    print(f"    你的结论：{CONCLUSION or '（还没写 —— 写在文件里的 CONCLUSION 那一行）'}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
