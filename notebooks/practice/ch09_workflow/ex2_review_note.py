r"""第 09 章 · 练习 2 / 5 · 在 human_review 里强制「修改意见必填」

【要做什么】
  拒绝但 `note` 为空时，直接抛 `Interrupt` 或返回一条错误，让流程不进入 `revise` 分支。

  重跑场景 B，确认它不再空转（`draft_reply` 只被访问 1 次）。

【已经给你了】
  Interrupt            本章的「挂起」异常（不是错误，是 human-in-the-loop 的正常控制流）
  run_human_verdict(reply)  用你写的规则处理一条人工答复，返回 (是否被挂起, 结果或说明)
  HONEST / VAGUE       两条对照答复：一条写了修改意见，一条只说「不行」

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch09_workflow\ex2_review_note.py
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
    APPROVE, TICKET_LOGISTICS, HumanChannel, Interrupt, build_graph, node_draft_reply,
)

HONEST = {"decision": "rejected", "note": "删掉「绝对保证」，改成「预计」，并注明到账时限。"}
VAGUE = {"decision": "rejected", "note": ""}          # ← 只说不行，不说怎么改


def _counting_draft(counter: dict[str, int]):
    """给 draft_reply 加一个计数器（每次执行 = 一次真实模型调用）。"""

    def node(state, ctx):
        counter["draft"] += 1
        return node_draft_reply(state, ctx)

    return node


def scene_b(reply: dict) -> tuple[str, int]:
    """重跑场景 B：人工给出 `reply` 这条答复，返回 (停机状态, 草稿被访问几次)。

    ★ 注意这里把图里的 human_review 换成了**你写的** `require_revision_note` ——
      否则验证的还是课程原版节点，你的规则根本没上场。
    """
    counter = {"draft": 0}
    graph = build_graph()                       # 默认 max_visits=6
    graph.nodes["draft_reply"].fn = _counting_draft(counter)
    graph.nodes["human_review"].fn = require_revision_note
    result = graph.run(dict(TICKET_LOGISTICS), human=HumanChannel([dict(reply)] * 4))
    return result.status, counter["draft"]


def run_human_verdict(reply: dict) -> tuple[bool, str]:
    """用**你写的规则**处理一条人工答复。

    返回 (是否被挂起, 说明文字)：
        被挂起    → (True,  Interrupt 的问题文本)
        被放行    → (False, 节点返回的增量 dict)
        其它异常  → (False, "异常 类型: 内容")

    ★ NotImplementedError 会被原样抛出 —— "还没写"要和"写错了"分得清清楚楚。
    """
    from stages.stage09_workflow.demo import NodeContext, ReplyDrafterLLM, TicketClassifierLLM

    ctx = NodeContext(llm=ReplyDrafterLLM(), human=HumanChannel([]),
                      models={"classifier": TicketClassifierLLM()})
    state = {"ticket_id": "T-9002", "text": "我的订单 A1001 快递到哪了？",
             "decision": "您的包裹已由顺丰发出。", "human_reply": dict(reply)}
    try:
        return False, str(require_revision_note(state, ctx))
    except Interrupt as stop:
        return True, stop.question
    except NotImplementedError:
        raise
    except Exception as exc:
        return False, f"异常 {type(exc).__name__}: {exc}"


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def require_revision_note(state: dict, ctx) -> dict:
    """TODO ── human_review 节点里的那条确定性规则。

    输入 state 里已经有 `human_reply`（人工答复的 dict），格式是：
        {"decision": "approved" | "rejected", "note": "修改意见"}
    人工答复可能长这样：{"decision": "rejected", "note": "   "}   ← 空白 = 没写

    要求：
      ① 批准（decision == "approved"）→ 放行，返回
         {"human_decision": "approved", "human_note": 答复里的 note}
      ② 驳回但 note 是空白的          → 抛 Interrupt，把「修改意见必填」这件事说清楚，
         并且 resume_at="human_review"（拿到新答复后从这里继续）
      ③ 驳回且写了 note               → 放行，返回
         {"human_decision": "rejected", "revision_notes": 那条 note}

    提示（卡住了再看）：
        if reply.get("decision") != "approved" and not reply.get("note", "").strip():
            raise Interrupt("...", resume_at="human_review")
        ★ .strip() 不能省 —— 用户输入 "   "（几个空格）也是「没写」。
        ★ 这一行代码消灭的是**一整类**空转，而不是这一次（练习 1 的 max_visits 只能兜底）。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 2 · TODO  require_revision_note")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_2() -> None:
    # ① 空白答复必须被拦下
    held, detail = run_human_verdict({"decision": "rejected", "note": "   "})
    if not held:
        raise AssertionError(f"空白的修改意见应该被挂起（Interrupt），现在却放行了：{detail[:70]}")
    kv("驳回 + 空白意见", f"⛔ 已挂起：{detail[:52]}")

    # ② 但一个写了意见的驳回必须放行（别把正常回环也删了）
    held2, detail2 = run_human_verdict(HONEST)
    if held2:
        raise AssertionError(f"写了修改意见的驳回不该被挂起：{detail2[:70]}")
    kv("驳回 + 有意见", f"✅ 放行：{detail2[:52]}")

    # ③ 批准必须放行
    held3, detail3 = run_human_verdict(dict(APPROVE))
    if held3:
        raise AssertionError(f"批准不该被挂起：{detail3[:70]}")
    kv("批准", f"✅ 放行：{detail3[:52]}")
    print()

    # ④ 重跑场景 B：不再空转
    status_vague, drafts_vague = scene_b(VAGUE)
    status_honest, drafts_honest = scene_b(HONEST)
    print("    场景 B 对照（同一张图，只差人工答复的内容）：")
    print(f"      只说「不行」  → 停机={status_vague:<10} draft_reply 被访问 {drafts_vague} 次")
    print(f"      写明怎么改    → 停机={status_honest:<10} draft_reply 被访问 {drafts_honest} 次")
    print()

    if drafts_vague != 1:
        raise AssertionError(
            f"「只说不行」应该在第 1 次草稿之后就挂起，现在 draft_reply 被访问了 {drafts_vague} 次")
    if status_vague != "interrupted":
        raise AssertionError(f"应该以 interrupted 干净退出（不是崩溃），现在是 {status_vague}")
    if drafts_honest != 2:
        raise AssertionError(
            f"写明意见的驳回应当被放行、重写 1 次草稿，现在重写了 {drafts_honest} 次")

    kv("你的规则", "空意见 → Interrupt；有意见 → 进入 revise 分支")
    print()
    warn("★ 对比练习 1：max_visits 只能给错误**兜底**，这条规则直接从源头消灭了那一类空转。")
    bullet("确定性规则能做的事，不要留给模型、也不要留给上限")
    bullet("挂起要干净地退出（Interrupt + 检查点），而不是崩掉或阻塞在 input()")
    note("真实产品里这一步等价于：驳回表单上的「修改意见」是必填项。")


def main() -> int:
    try:
        check_2()
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
