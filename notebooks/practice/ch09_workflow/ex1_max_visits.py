r"""第 09 章 · 练习 1 / 5 · 把 max_visits 护栏拆掉，观察错误发生时的最大代价

【要做什么】
  把第 ⑧ 节的 `MAX_VISITS` 从 2 改成 100，用「只说不行、不说怎么改」的人工重跑场景 B。

  观察 `draft_reply` 被访问了几次、模型调用涨到几次。然后再改回 2。

【已经给你了】
  build_graph(max_visits=…)      本章的状态机（9 个节点 / 客服工单流程）
  HumanChannel([…])             人工通道，剧本用完就抛 Interrupt（不阻塞、不读 stdin）
  run_revision_loop(max_visits) 把场景 B 跑一遍，返回 (RunResult, 草稿被重写的次数)
  TICKET_LOGISTICS              场景 B 用的工单

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch09_workflow\ex1_max_visits.py
  3. 验收本章：py scripts\run_all_checks.py 09
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn  # noqa: E402
from stages.stage09_workflow.demo import (  # noqa: E402
    TICKET_LOGISTICS, HumanChannel, RunResult, build_graph, node_draft_reply,
)

# ★ 安全性说明：下面的 max_visits 是**参数**，不是改源文件。
#   所以你把上限开到 100 也不会真的跑 100 圈 —— 剧本里只有 8 条「不行」，
#   第 9 圈人工通道就空了，节点会改抛 Interrupt（挂起），流程干净地停下。
VAGUE_REJECT = {"decision": "rejected", "note": ""}     # 只说不行，不说怎么改


def _counting_draft(counter: dict[str, int]):
    """把 draft_reply 包一层计数 —— 每次执行 = 一次真实的模型调用。"""

    def node(state, ctx):
        counter["draft"] += 1
        return node_draft_reply(state, ctx)

    return node


def run_revision_loop(max_visits: int) -> tuple[RunResult, int]:
    """重跑「场景 B」：人工一直只说「不行」，不写任何修改意见。

    返回 (运行结果, 草稿被真实重写了几次)。
    """
    counter = {"draft": 0}
    graph = build_graph(max_visits=max_visits)
    # 就地换掉 draft_reply 的实现（宁可直接改内部字段，也不新建一个同名的图）
    graph.nodes["draft_reply"].fn = _counting_draft(counter)
    human = HumanChannel([dict(VAGUE_REJECT)] * 8)
    result = graph.run(dict(TICKET_LOGISTICS), human=human)
    return result, counter["draft"]


def probe(max_visits: int) -> None:
    """跑一次并打印观察结果（想多试几个数字就在 check_1 里多调几次）。"""
    result, drafts = run_revision_loop(max_visits)
    kv(f"max_visits={max_visits}", f"状态={result.status} / 步数={len(result.history)}")
    kv("  草稿被重写", f"{drafts} 次（= {drafts} 次真实模型调用）")
    kv("  路径", " → ".join(result.history))
    kv("  停机原因", (result.error or "（正常结束，没有报错）")[:58])
    print()


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def visit_limit() -> tuple[int, str]:
    """TODO ── 返回 (你选择的最大访问次数上限, 一句话结论)。

    第 ① 问：把上限设成几？（课程里被拆掉的那个值是 2）
    第 ② 问：一句话回答 —— `max_visits` 到底在保护什么？
             （提示：它保护的不是「正确性」，而是「错误发生时的最大代价」；
               想清楚这一点，你就知道为什么"把上限调大"不是解决办法。）

    返回形如：(2, "它保护的不是正确性，而是……")
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO  visit_limit：返回 (上限, 一句话结论)")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_1() -> None:
    limit, conclusion = visit_limit()

    if not isinstance(limit, int) or limit < 1:
        raise AssertionError(f"上限应该是一个 ≥1 的整数，现在拿到的是 {limit!r}")

    probe(limit)

    print("    对照：把同一个场景的上限开大，代价会怎么涨 ——")
    for probe_limit in (2, 6, 100):
        result, drafts = run_revision_loop(probe_limit)
        print(f"      max_visits={probe_limit:<4} 草稿重写 {drafts} 次，"
              f"模型调用 {result.llm_calls} 次，停机={result.status}")
    print()

    if limit != 2:
        raise AssertionError(
            f"课程里的答案是 2 —— 你填的是 {limit}。"
            f"注意上面那张对照表：上限越大，同一次「人工说不出所以然」的代价就越大。")
    if len(conclusion.strip()) < 10:
        raise AssertionError("第 ② 问还没写：用一句话说明 max_visits 保护的是什么")

    kv("你的上限", limit)
    kv("你的结论", conclusion.strip())
    kv("第 ⑧ 节的原结论", "max_visits 不保证流程正确，它划定「一次错误最多花多少钱」的上限")
    print()
    warn("★ 注意 status = max_visits 而不是 completed —— 失败必须被上层看见，不能假装成功。")
    note("★ 更根本的解法不是调大上限，而是在 human_review 里强制「修改意见必填」——")
    note("  那就是练习 2 要做的事（也是练习 4 的 escalate 想解决的）。")
    bullet("每一次 draft_reply 都是一次真实的模型调用：循环 = 账单")


def main() -> int:
    try:
        check_1()
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
