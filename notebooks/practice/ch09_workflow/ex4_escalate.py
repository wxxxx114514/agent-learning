r"""第 09 章 · 练习 4 / 5 · 加一个「超时升级」节点

【要做什么】
  新增节点 `escalate`：当 `visits['human_review'] >= 2`（人工两次没拍板）时，
  条件边路由到它，把工单交给主管并结束流程。

【已经给你了】
  ESCALATE_REPLY                升级时交给客户的固定话术（确定性，不用模型）
  ESCALATE_LIMIT                = 2，人工提交几次结论还没拍板就升级
  route_human_verdict(state, visits)  已经写好的路由器（读结论 + 访问次数，返回分支 key）
  make_human_review_node(visits)      human_review 的包装：每次执行时记一次访问
  node_escalate                      升级节点本身（写答复 + 标记已升级）
  install_stubborn_drafter(graph)     让草稿"改了两版都过不了合规"（这样流程才需要升级）
  check_escalation()                  反复驳回的工单跑一遍，返回 (状态, 路径, 答复, 校验问题)

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch09_workflow\ex4_escalate.py
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
    END, TICKET_LOGISTICS, HumanChannel, StateGraph, build_graph, node_human_review,
)

ESCALATE_REPLY = (
    "您好，非常抱歉：这张工单我们已经多次复核仍未达成一致。"
    "已为您升级至客服主管跟进，主管会在 2 小时内与您联系，请您留意来电。"
)
ESCALATE_LIMIT = 2          # 人工提交 2 次结论还没拍板 → 升级

REJECTION = {"decision": "rejected", "note": "删掉「绝对保证」，改成「预计」，并注明到账时限。"}


def route_human_verdict(state: dict, visits: dict[str, int]) -> str:
    """人工审批之后的路由（纯函数，已经写好）。

    它读两样东西：
      · state["human_decision"]   —— 人工的结论（approved / rejected）
      · visits["human_review"]    —— 这个节点已经被访问过几次（由 make_human_review_node 记）

    返回三个分支 key 之一：
      "approve"  → 交付
      "revise"   → 回到 draft_reply 重写
      "escalate" → 交给主管（★ 这个分支要你来接线）
    """
    if state.get("human_decision") == "approved":
        return "approve"
    if visits.get("human_review", 0) >= ESCALATE_LIMIT:
        return "escalate"
    return "revise"


def make_human_review_node(visits: dict[str, int]):
    """human_review 节点的包装：**每次执行时把访问次数记进 visits**。

    为什么需要它？因为路由器要判断「人工是不是已经被问过 2 次了」，
    而引擎只会把 state 交给路由器 —— 这个数字得你自己数、自己带进去。
    """
    def node(state, ctx):
        visits["human_review"] = visits.get("human_review", 0) + 1
        return node_human_review(state, ctx)

    return node


def node_escalate(state: dict, ctx) -> dict:
    """升级节点（已经写好，你只要把它接进图里）。

    它做两件事：写最终答复 + 标记这条工单已经升级过（可审计）。
    注意它**不需要模型** —— 「交给主管」是一条规定，不是一次判断。
    """
    return {"final_reply": ESCALATE_REPLY, "escalated": True}


def install_stubborn_drafter(graph: StateGraph) -> None:
    """让流程真的需要升级：草稿改了两版都过不了合规。

    为什么要有这一步？因为课程原版的草稿"被人工意见改一次"就干净了，
    于是流程第二次进 human_review 之前就合规通过、直接交付 —— 根本走不到升级。

    这里模拟的是更真实的一种情况：**模型改了一版，但改出了新毛病**
    （它把「绝对保证」换成了「预计」，却又擅自承诺了未获批的金额），
    合规检查再次拦下 → 人工第二次摇头 → 这才是「人工两次没拍板」。
    """
    def drafter(state, ctx) -> dict:
        if state.get("revision_notes"):
            wording = "预计 24 小时内到账"
            compensate = "额外补偿 30 元"          # ← 未获批的金额，合规会拦下
        else:
            wording = "绝对保证 24 小时内到账"      # ← 违规措辞，合规会拦下
            compensate = "相关补偿"
        return {"draft": (
            f"【工单 {state['ticket_id']} 回复】您好，非常抱歉给您带来不便。\n"
            f"{state['decision']}\n"
            f"{compensate}{wording}。如有其他问题请随时联系我们。"
        )}

    graph.nodes["draft_reply"].fn = drafter


def check_escalation(max_visits: int = 8) -> tuple[str, list[str], str, list[str]]:
    """反复驳回的工单跑一遍。

    返回 (停机状态, 历史路径, 最终答复, 图校验问题列表)。
    """
    graph: StateGraph = build_graph(max_visits=max_visits)
    install_stubborn_drafter(graph)
    register_escalation(graph)                       # ← 用你写的代码接线
    result = graph.run(dict(TICKET_LOGISTICS),
                       human=HumanChannel([dict(REJECTION)] * 6))
    return result.status, list(result.history), result.final_reply, graph.validate()


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def register_escalation(graph: StateGraph) -> None:
    """TODO ── 给图加上「超时升级」这条路。

    四步（前三步缺一不可）：
      ① 自己数访问次数：
             visits: dict[str, int] = {}
             graph.nodes["human_review"].fn = make_human_review_node(visits)
      ② 加节点 + 接边。别忘了 escalate 要能走到 END，否则 validate() 会报
         「节点 escalate 无法到达 END」—— 这就是**构建期校验的价值**：
             graph.add_node("escalate", node_escalate, title="超时升级")
             graph.add_edge("escalate", END)
      ③ 把 human_review 的条件边换成三路。旧的那条要先摘掉：
             graph.conditionals = [c for c in graph.conditionals if c.src != "human_review"]
             graph.add_conditional(
                 "human_review",
                 lambda state: route_human_verdict(state, visits),   # ← 闭包，看得见 visits
                 {"approve": "finalize", "revise": "draft_reply", "escalate": "escalate"},
                 "人工结论",
             )

    ★ 为什么路由器能看见 visits？因为 lambda 是个**闭包**，捕获了 ① 里那个字典。
      引擎只把 state 传进来，看不见的数字得你自己带进去。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO  register_escalation")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_4() -> None:
    # ① 先做构建期校验：图必须自己就是合法的
    graph = build_graph()
    register_escalation(graph)
    if "escalate" not in graph.nodes:
        raise AssertionError("图里没有 escalate 节点 —— 第 ② 步还没做")
    issues = graph.validate()
    if issues:
        raise AssertionError(
            "图没通过构建期校验（这正是练习提示里说的那件事）：\n      - "
            + "\n      - ".join(issues))
    kv("escalate 节点", "已接好，且图通过 validate()（每个节点都可达、都能到 END）")
    print()

    # ② 真跑一遍：人工一直驳回，看它会不会升级
    status, history, final_reply, _ = check_escalation()
    kv("停机状态", status)
    kv("路径", " → ".join(history))
    kv("最终答复", final_reply[:52])
    print()

    if "escalate" not in history:
        raise AssertionError("走了半天没走到 escalate：检查路由分支和 add_edge('escalate', END)")
    if status != "completed":
        raise AssertionError(f"升级后应当干净收口（completed），现在是 {status}")
    if final_reply != ESCALATE_REPLY:
        raise AssertionError("最终答复应该由 escalate 节点写进 final_reply")
    if history.count("human_review") != ESCALATE_LIMIT:
        raise AssertionError(
            f"人工只该被问 {ESCALATE_LIMIT} 次就升级，"
            f"实际问了 {history.count('human_review')} 次")
    if history.count("draft_reply") != ESCALATE_LIMIT:
        raise AssertionError(
            f"草稿只该被重写 {ESCALATE_LIMIT} 次（每次人工驳回重写一次），"
            f"实际 {history.count('draft_reply')} 次")
    print()
    warn("★ 对比练习 1：max_visits 是「撞上上限就停机」，escalate 是「到点就交给能拍板的人」。")
    note("  前者把问题变成一次失败，后者把问题变成一次升级 —— 后者才是业务想要的。")
    bullet("升级 = 图里的一条普通分支，不是「异常处理」：它可画、可测、可审计")
    bullet("新节点必须能走到 END，否则 validate() 直接拦下（构建期校验 + 循环保护）")
    bullet(f"草稿被重写 {ESCALATE_LIMIT} 次 = {ESCALATE_LIMIT} 次真实模型调用，账是算得出来的")


def main() -> int:
    try:
        check_4()
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
