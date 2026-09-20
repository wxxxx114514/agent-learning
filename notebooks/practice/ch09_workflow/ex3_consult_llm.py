r"""第 09 章 · 练习 3 / 5 · 把 handle_consult 换成模型，量一量代价

【要做什么】
  现在的咨询处理是 FAQ 查表（0 次调用）。改成调用模型回答同样的问题，
  对比 `llm_calls` 和两次运行的结果一致性。

【已经给你了】
  build_graph()                 课程原版的图（handle_consult = FAQ 查表）
  build_consult_graph(handler)  把 handle_consult 节点换成 `handler`，并换成"每次说法都不一样"的模型
  answer_table()                课程原版实现（FAQ 查表），拿来做对照
  WobblyAnswerLLM               一个"同一问题、不同措辞"的假模型（真实模型的日常）
  FAQ_CONSULT                   咨询工单：「请问运费券怎么用？」——FAQ 表里有标准答案

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch09_workflow\ex3_consult_llm.py
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
from core.llm import LLM, LLMResponse  # noqa: E402
from core.message import Message  # noqa: E402
from stages.stage09_workflow.demo import (  # noqa: E402
    FAQ, TICKET_CONSULT, HumanChannel, StateGraph, build_graph, node_handle_consult,
)

FAQ_CONSULT = dict(TICKET_CONSULT)          # {"ticket_id": "T-9003", "text": "请问运费券怎么用？"}
APPROVE = {"decision": "approved", "note": "合规已确认，可以发送"}


class WobblyAnswerLLM(LLM):
    """"每次说法都不一样"的假模型 —— 真实模型的日常，这里只是被放大了。

    它模拟的正是合规部门最怕的那件事：**同样的问题，不一样的措辞**。
    三个模板轮着来，所以第 1 次和第 2 次一定不同。
    """

    name = "wobbly"

    _TEMPLATES = (
        "运费券能抵扣一次下单的运费，有效期 90 天，一单限用一张。",
        "亲，运费券就是用来抵运费的哦，90 天内有效，每单只能用一张～",
        "按照平台规则，运费券可抵扣运费，有效期九十天，单笔订单限用一张。",
    )

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        n = self.total_calls
        return LLMResponse(text=self._TEMPLATES[n % len(self._TEMPLATES)], model=self.model)


def answer_table(state: dict, ctx) -> dict:
    """课程原版实现：查 FAQ 表（0 次模型调用，永远同一句话）。"""
    return node_handle_consult(state, ctx)


def build_consult_graph(handler, model: LLM | None = None) -> StateGraph:
    """把 handle_consult 换成 `handler`，并把写话术的模型换成 WobblyAnswerLLM。

    为什么连模型也换掉？因为课程自带的 ReplyDrafterLLM 是模板模型，
    你观察不到"模型的不确定性"；换成 Wobbly 之后，两次运行才会真的不一样。
    """
    graph: StateGraph = build_graph()
    graph.nodes["handle_consult"].fn = handler
    graph.llm = model or WobblyAnswerLLM()
    return graph


def run_table() -> tuple[dict, int]:
    """对照组：原版图（FAQ 查表 + 模板模型）。返回 (state, llm_calls)。"""
    result = build_graph().run(dict(FAQ_CONSULT), human=HumanChannel([dict(APPROVE)]))
    return result.state, result.llm_calls


def run_model(handler, model: LLM) -> tuple[str, int]:
    """实验组：你写的 handler。返回 (decision, llm_calls)。

    ★ model 由调用方传进来并**跨两次运行复用** —— 因为"同一个模型"本来就是一个
      长期存在的东西，它的不确定性也来自"同一个模型在不同时刻给出的不同答案"。

    ★ 注意：状态机引擎会把节点里的任何异常变成 `RunResult(status="error")`，
      所以我们在这里把它还原成异常抛出去 —— "还没写"要和"写错了"分得清清楚楚。
    """
    result = build_consult_graph(handler, model).run(
        dict(FAQ_CONSULT), human=HumanChannel([dict(APPROVE)]))
    if result.status == "error":
        raise NotImplementedError(result.error)
    return result.state.get("decision", ""), result.llm_calls


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def answer_with_llm(state: dict, ctx) -> dict:
    """TODO ── 用模型回答咨询问题，而不是查 FAQ 表。

    要求：
      ① 用 ctx.ask_llm([...]) 调模型（**不要**自己 new 一个 LLM，那样绕过了记账）
      ② 消息里带上用户的问题 state["text"]，并说明"只依据已知规则回答"
      ③ 返回这一项增量：{"decision": 模型的回答, "handled_by": "模型（咨询也用模型）"}

    提示（卡住了再看）：
        text = ctx.ask_llm([
            Message.system("你是客服。只依据已知规则回答，不要添加未确认的承诺。"),
            Message.user(state["text"]),
        ]).strip()
        return {"decision": text, "handled_by": "模型（咨询也用模型）"}

    ★ 关键：ctx.ask_llm 会记一次账（llm_calls +1）—— 这正是你要量出来的"代价"。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 3 · TODO  answer_with_llm")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_3() -> None:
    # ① 先确认你确实换掉了 FAQ 表：咨询节点应该产出"模型"处理的标记
    table_decision, _ = run_table()
    if not table_decision.get("decision"):
        raise AssertionError("对照组（FAQ 查表）没给出答案，先检查环境")
    wobbly = WobblyAnswerLLM()
    decision_probe, _ = run_model(answer_with_llm, wobbly)
    if not decision_probe or decision_probe == table_decision.get("decision"):
        raise AssertionError(
            f"咨询节点看起来还在查表（两次都得到 {table_decision.get('decision', '')[:34]!r}）；"
            f"你要用 ctx.ask_llm 真的调一次模型")

    # ② 两种实现各跑两次：量代价 + 量一致性
    #    ★ 用一个**全新的** model 实例跑对照，这样"第 1 次 / 第 2 次"从同一起点开始
    wobbly = WobblyAnswerLLM()
    print("    对照实验（同一张图，只换 handle_consult 的实现）：")
    pairs = {}
    for label, run in (("FAQ 查表（课程原版）", lambda: run_table()),
                       ("模型回答（你写的）", lambda: run_model(answer_with_llm, wobbly))):
        runs = [run() for _ in range(2)]
        pair = [(r[0] if isinstance(r[0], str) else r[0].get("decision", ""), r[1]) for r in runs]
        pairs[label] = pair
        same = pair[0][0] == pair[1][0]
        print(f"      {label:<20} llm_calls=({pair[0][1]}, {pair[1][1]})  两次回答一致={same}")
        print(f"        ├─ 第 1 次：{pair[0][0][:50]}")
        print(f"        └─ 第 2 次：{pair[1][0][:50]}")
    print()

    table_pair = pairs["FAQ 查表（课程原版）"]
    model_pair = pairs["模型回答（你写的）"]
    if table_pair[0][0] != table_pair[1][0]:
        raise AssertionError("FAQ 查表两次结果必须完全一致（这正是它的价值）")
    if table_pair[1][1] != table_pair[0][1]:
        raise AssertionError("对照组的调用次数不该波动（它是确定性的）")
    if model_pair[0][1] <= table_pair[0][1]:
        raise AssertionError(
            f"换成模型之后 llm_calls 应当上升"
            f"（查表 {table_pair[0][1]} 次 → 模型 {model_pair[0][1]} 次）：咨询节点要多花一次调用")
    if model_pair[0][0] == model_pair[1][0]:
        raise AssertionError("实验没有生效：两次模型回答不该一模一样（那说明你还在查表）")

    kv("FAQ 查表", f"llm_calls={table_pair[0][1]}，两次回答字字相同 ✅")
    kv("换成模型", f"llm_calls={model_pair[0][1]}（多花 {model_pair[0][1] - table_pair[0][1]} 次），"
                   f"两次回答不同 ⚠️")
    print()
    note(f"★ 本章 FAQ 表里只有 {len(FAQ)} 条标准答案 —— 有标准答案的问题，本来就不该问模型。")
    warn("★ 合规部门会喜欢哪一个？答案是查表：一个「每次说法都不一样」的客服系统连话术审核")
    warn("  都没法做（审核通过的是哪一版？），在这里**可复现性就是合规性**。")
    bullet("换模型不是免费的能力升级：它同时买来了成本、延迟和不确定性")
    bullet("正确的第一个问题是「这件事的答案在表里吗」——在表里就写代码")


def main() -> int:
    try:
        check_3()
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
