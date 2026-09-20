r"""第 06 章 · 练习 3 / 5 · 拆掉拒答护栏，看模型会说什么

【要做什么】
  **破坏护栏并观察：删掉拒答分支。**
  把 `ask()` 里 `if not hits:` 那个分支删掉，让它照样调用模型。
  观察假模型收到「（没有任何参考资料）」时会输出什么，以及「员工内购折扣」这个问题的答案变成了什么。

【已经给你了】
  · 带护栏的 `RagAgent`（课程原版）：检索不到 → 直接拒答，**连模型都不调用**
  · `NoGuardRag`：把 ask() 抄了一遍，只把拒答那一行换成 TODO —— 你只需要把它拆掉
  · 两个对照模型：RagBotLLM（只照着资料答）和 DiscountBotLLM（凭记忆编）
  · 全部都是第 06 章的真实 API：build_rag_messages / RagAnswer / extract_citations

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch06_rag\ex3_break_refusal.py
  3. 验收本章：py scripts\run_all_checks.py 06
"""

# ── 环境（不用改）──────────────────────────────────────────
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import kv, note, warn                                  # noqa: E402
from core.llm import estimate_tokens                                     # noqa: E402
from stages.stage06_rag.demo import ParametricBotLLM, RagBotLLM, RETRIEVER  # noqa: E402
from stages.stage06_rag.rag import (                                     # noqa: E402
    REFUSAL, RagAgent, RagAnswer, build_rag_messages, extract_citations,
)


class DiscountBotLLM(ParametricBotLLM):
    """① 节那个「凭记忆作答」的模型 + 一条关于折扣的常识（当然也是编的）。

    它代表真实模型的行为：**不知道也会答**，而且答得很自信。
    """

    PRIORS = dict(ParametricBotLLM.PRIORS,
                  **{"折扣": "员工内购一般可以享受 8 折优惠，具体以公司政策为准。"})


QUESTION = "员工内购折扣是多少？"        # 手册里根本没有这一条


class NoGuardRag(RagAgent):
    """把拒答护栏拆掉的版本：检索不到也照样调用模型。"""

    def ask(self, question: str) -> RagAnswer:
        hits = self.retriever.search(question, top_k=self.top_k, min_score=self.min_score)
        if not hits:
            # TODO ① ── 这里原本是拒答护栏（课程原版的一等公民）：
            #       return RagAnswer(question=question, answer=REFUSAL, hits=[], refused=True)
            #   它拦在模型之前，所以模型**根本没机会编**。
            #   现在把护栏拆掉：写一行 `pass`，让代码继续往下走（照样调模型）。
            #   ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
            raise NotImplementedError("练习 3 · TODO ①  把拒答护栏拆掉（写一行 pass）")
            # ↑↑↑ 你的答案 ↑↑↑
        messages = build_rag_messages(question, hits)
        self.calls += 1
        answer = self.llm.complete(messages).text.strip()
        answer = re.sub(r"^(Final Answer|答案)\s*[:：]\s*", "", answer).strip()
        return RagAnswer(
            question=question, answer=answer, hits=hits, refused=False,
            prompt_tokens=sum(estimate_tokens(m.content) for m in messages),
            citations=extract_citations(answer),
        )


def my_conclusion() -> str:
    """TODO ② ── 用一句话写下你观察到的现象。

    提示：把「有护栏」和「没护栏」两列对比一下 —— 拒答这个决定，到底该由谁来做？
    """
    # 写下你的结论：
    #
    #   ↓↓↓ 把下面这行删掉，写上 return "你的结论" ↓↓↓
    raise NotImplementedError("练习 3 · TODO ②  写下你的结论")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def check() -> str:
    print("\n" + "=" * 66)
    print(f"  同一个问题：「{QUESTION}」")
    print("=" * 66)

    guarded = RagAgent(RETRIEVER, RagBotLLM(), top_k=3, min_score=2.0)
    a = guarded.ask(QUESTION)
    kv("① 有护栏 · 检索命中", len(a.hits))
    kv("① 有护栏 · 模型被调用了几次", guarded.calls)
    kv("① 有护栏 · 回答", a.answer[:56])

    print()
    for name, llm in (("RagBotLLM（只照资料答）", RagBotLLM()),
                      ("DiscountBotLLM（凭记忆答）", DiscountBotLLM())):
        agent = NoGuardRag(RETRIEVER, llm, top_k=3, min_score=2.0)
        ans = agent.ask(QUESTION)
        kv(f"② 拆掉护栏 · {name}", f"调用了 {agent.calls} 次模型")
        print(f"       回答：{ans.answer[:70]}")
        print(f"       像是拒答吗？refused={ans.refused}｜回答全文等于课程拒答语？"
              f"{ans.answer.strip() == REFUSAL}｜引用：{ans.citations}")
        print()

    if guarded.calls != 0:
        warn("带护栏的版本不该调用模型 —— 拒答是在调模型之前就完成了")
    warn("拆掉护栏之后，**要不要拒答变成了模型的自由发挥**：它可能碰巧说「资料里没有」，")
    warn("也可能像 DiscountBotLLM 那样，用训练数据里的常识把空填上 —— 这就是幻觉事故的入口。")
    note("再看一眼 citations：没有资料时它照样能写出「[片段 N]」这种看起来可溯源的东西。")

    conclusion = my_conclusion().strip()
    if len(conclusion) < 8:
        raise NotImplementedError("练习 3 · TODO ② 结论太短了，把观察到的现象写清楚一点")
    print()
    kv("你的结论", conclusion)
    return "拒答护栏：护栏在 → 0 次调用；护栏拆掉 → 模型自己决定要不要编"


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
