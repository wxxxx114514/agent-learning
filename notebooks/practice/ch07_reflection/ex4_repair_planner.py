r"""第 07 章 · 练习 4 / 5 · 把笼统批评「翻译」成具体修正（RepairPlanner）

【要做什么】
  **把笼统批评「翻译」成具体修正。**
  新增一个 `RepairPlanner`：接收笼统的审查意见 + 事实源，
  输出可执行的修正条目（就是「具体派审查者」干的事），接在笼统派审查者后面。
  跑对照实验：笼统派 + 翻译器，能不能追平具体派？代价是几次调用？

【已经给你了】
  · TASK_Q1：事实源（正确合计 811 元，假模型「心算」写成 801）
  · ReviewCriticLLM(mode="vague")：笼统派审查者（只会说「建议进一步优化」）
  · ReviewCriticLLM(mode="specific")：具体派审查者（说得出「把 801 改成 811」）—— 对照组
  · TranslatedCritic：把「笼统派 + 你的翻译器」拼成一个审查者，接到循环里，不用改
  · run()：跑一次循环并打印 轮数 / 停机原因 / 最终合计 / 验证通过，不用改

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch07_reflection\ex4_repair_planner.py
  3. 验收本章：py scripts\run_all_checks.py 07
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                        # noqa: E402
from stages.stage07_reflection.demo import (                           # noqa: E402
    TASK_Q1, Critique, ReflexionAgent, ReportTask, ReportVerifier, ReportWriterLLM,
    ReviewCriticLLM, VAGUE_REVIEW, total_in, total_value,
)

# ★ 关键设定：两组都不给「验证器反馈」，只看**审查者的输出**能不能驱动修正。
USE_VERIFIER_FEEDBACK = False


class RepairPlanner:
    """把笼统的审查意见「翻译」成具体修正条目。

    它和具体派审查者干的是同一件事：**手里有事实源，所以能说出确定的话**。
    区别是它排在笼统派**后面**，只做翻译，不改变审查者的性格
    （工业界叫 `critique -> actionable plan` 两步走）。
    """

    name = "repair-planner"

    def repair(self, draft: str, task: ReportTask) -> list[str]:
        """TODO ── 读草稿 + 事实源，输出**可执行**的修正条目。

        照着具体派 `_audit` 的三要素写：**位置（哪一行）+ 事实（正确值）+ 动作（把 X 改成 Y）**。
          1. 拿草稿里的合计：got = total_value(draft)
             · got is None → "缺少「合计：{正确值} 元」这一行；请补上。"
          2. 和事实源比：got != task.correct_total() →
             "合计行有误：{task.formula_text()} = {正确值}，你写成了 {got}；"
             "请把 {got} 改成 {正确值}，其余内容不要改动。"
          3. 逐条检查分项格式：want = f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
             不在草稿里 → f"分项「{r.sku}」应写成 `{want}`；请把该行改成这个格式。"

        返回条目列表（没什么可改的就返回 []）。
        ★ 句式很重要：`ReportWriterLLM` 只认「把 X 改成 Y」这种可执行的动作，
          形容词堆得再多它也不动一个数字。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案（8~10 行）↓↓↓
        raise NotImplementedError("练习 4 · TODO  repair")
        # ↑↑↑ 你的答案 ↑↑↑


class TranslatedCritic:
    """笼统派审查者 + 你的翻译器 —— 对外仍然是一个 `.review()` 接口。"""

    def __init__(self, critic: ReviewCriticLLM, planner: RepairPlanner, task: ReportTask) -> None:
        self.critic = critic
        self.planner = planner
        self.task = task
        self.planner_rounds = 0

    def review(self, draft: str, task: ReportTask | None = None) -> Critique:
        target = task or self.task
        vague = self.critic.review(draft, target)          # ① 笼统意见（原文给你了）
        items = self.planner.repair(draft, target)         # ② ← 你写的翻译
        self.planner_rounds += 1
        return Critique(raw=vague.raw, items=items)


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def run(critic, label: str) -> tuple[object, str]:
    agent = ReflexionAgent(
        llm=ReportWriterLLM(TASK_Q1),
        critic=critic,                       # type: ignore[arg-type]
        verifier=ReportVerifier(),
        max_rounds=3,
        use_verifier_feedback=USE_VERIFIER_FEEDBACK,
    )
    r = agent.run(TASK_Q1)
    head = r.rounds[0].critique.raw.splitlines()[0][:40] if r.rounds else "（无）"
    print(f"  ── {label}")
    print(f"     审查者原话  ：{head}")
    print(f"     实际上报的条目：{len(r.rounds[0].critique.actionable) if r.rounds else 0} 条可执行")
    kv(f"     {label} · 轮数", len(r.rounds))
    kv(f"     {label} · 停机原因", r.stop_reason)
    kv(f"     {label} · 最终合计", total_in(r.final))
    kv(f"     {label} · 验证通过", "是" if r.verified else "否")
    print()
    return r, head


def check() -> str:
    planner = RepairPlanner()
    translated = TranslatedCritic(ReviewCriticLLM(TASK_Q1, mode="vague"), planner, TASK_Q1)

    print("\n" + "=" * 66)
    print("  对照实验：同一个任务、同一个写作模型，只换审查者")
    print("=" * 66)
    note("A 组 · 只有笼统派审查者，它每次说的都是这种话：")
    print(f"     「{VAGUE_REVIEW[:34]}…」")
    print()
    a, _ = run(ReviewCriticLLM(TASK_Q1, mode="vague"), "A · 笼统派")
    b, _ = run(translated, "B · 笼统派 + 你的翻译器")
    c, _ = run(ReviewCriticLLM(TASK_Q1, mode="specific"), "C · 具体派（对照组）")

    print("  ── 代价 ──")
    kv("A 组模型调用（写作 + 审查）", f"{a.llm_calls} + {len(a.rounds)}")
    kv("B 组模型调用（写作 + 审查 + 翻译轮数）",
       f"{b.llm_calls} + {len(b.rounds)} + {translated.planner_rounds}")
    kv("C 组模型调用（写作 + 审查）", f"{c.llm_calls} + {len(c.rounds)}")
    print()
    note("本练习的翻译器是**确定性代码**（重算而已，0 次模型调用）；")
    note("真实系统里它常常是另一次（更便宜的）模型调用 → B 组每轮 +1 次调用。")
    print()

    if a.verified:
        raise NotImplementedError("练习 4 · TODO  笼统派竟然通过了？先看看 A 组的停机原因（应该是 no_progress）")
    if not b.verified:
        raise NotImplementedError(
            "练习 4 · TODO  repair 还没生效：翻译器没能给出「把 801 改成 811」这种可执行条目")
    if total_value(b.final) != TASK_Q1.correct_total():
        raise NotImplementedError("练习 4 · TODO  repair 给出的正确值不对，草稿没被改对")
    warn("结论：笼统派 + 翻译器**追平了**具体派 —— 代价是多一次「翻译」调用（或一段确定性代码）。")
    bullet("这笔账划不划算，取决于你的场景：换来的是「审查者可以换成一个便宜的模型」。")
    bullet("要点永远不是「让模型再检查一遍」，而是**给审查者事实源 + 逼它说出可执行的动作**。")
    return f"A 未通过（{a.stop_reason}）→ B 追平具体派：{total_in(b.final)}，验证通过"


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
