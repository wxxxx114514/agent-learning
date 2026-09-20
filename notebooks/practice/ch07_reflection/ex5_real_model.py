r"""第 07 章 · 练习 5 / 5 · 换一个真实模型：输出更脏，笼统的「再检查一遍」依然救不回来

【要做什么】
  **换一个真实模型试试（可选，需要 API Key）。**
  把写作模型换成 `core.real_llm` 里的真实模型，跑同一套流程。
  你会观察到两件事：① 真实模型第一次**未必**算错（它可能直接给出 811）；
  ② 但它一旦算错，笼统的「再检查一遍」依然救不回来。

  没配 Key 也能做完：下面用 DirtyWriterLLM 精确复现真实模型的两条坏习惯
  （先说一句废话、关键数字加 Markdown 加粗），现象是一样的。

【已经给你了】
  · DirtyWriterLLM：脏输出写作模型（`first_correct=True` 时第一次就写对，模拟"未必算错"）
  · TolerantVerifier：把「合计」那一步换成**你写的** extract_total，其余规则照旧
  · TolerantCritic：具体派审查者 + 你的宽容解析
  · REVIEW_* / run()：四个场景的对照实验和打印，不用改
  · REAL_LLM：检测环境里的 API Key（没有就是 None → 自动跳过真实模型那一格）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch07_reflection\ex5_real_model.py
  3. 验收本章：py scripts\run_all_checks.py 07
"""

# ── 环境（不用改）──────────────────────────────────────────
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, code, kv, note, warn                  # noqa: E402
from core.message import Message                                       # noqa: E402
from core.mock_llm import as_mock_response                             # noqa: E402
from core.real_llm import from_env                                     # noqa: E402
from stages.stage07_reflection.demo import (                           # noqa: E402
    CLEAN_REVIEW, REQUEST_TEMPLATE, SYSTEM_TEMPLATE, TASK_Q1, ReflexionAgent,
    ReportVerifier, ReportWriterLLM, ReviewCriticLLM, Verdict,
)

REAL_LLM = from_env()               # 没配 API Key → None（离线照常跑完）
DIRTY_PREFIX = "好的，这是我的报告：\n\n"


class DirtyWriterLLM(ReportWriterLLM):
    """真实模型的坏习惯：先说一句废话，再把关键数字加粗。"""

    def __init__(self, task=TASK_Q1, first_correct: bool = False, model: str = "mock-dirty") -> None:
        super().__init__(task, model)
        self.first_correct = first_correct

    def _complete(self, messages, **kwargs):
        resp = super()._complete(messages, **kwargs)      # 父类负责「按反馈把 801 改成 811」
        text = resp.text
        if self.first_correct and len(self.drafts) == 1:  # 真实模型第一次未必算错
            text = text.replace(str(self.task.wrong_total()), str(self.task.correct_total()))
        text = DIRTY_PREFIX + text
        text = re.sub(r"合计：(\d+) 元", lambda m: f"合计：**{m.group(1)}** 元", text)
        text = text.replace(self.task.title, f"## {self.task.title}", 1)
        return as_mock_response(text, self.model)


class TolerantCritic(ReviewCriticLLM):
    """具体派审查者 + 宽容解析：它用**你写的** extract_total 找合计。"""

    def _audit(self, draft: str) -> str:
        want = self.task.correct_total()
        got = extract_total(draft)                        # ← 你的解析器
        items: list[str] = []
        if got is None:
            items.append(f"找不到「合计」行；请补上「合计：{want} 元」。")
        elif got != want:
            items.append(f"合计行有误：{self.task.formula_text()} = {want}，你写成了 {got}；"
                         f"请把 {got} 改成 {want}，其余内容不要改动。")
        for r in self.task.records:
            line = f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
            if line not in draft:
                items.append(f"分项「{r.sku}」应写成 `{line}`；请把该行改成这个格式。")
        return "\n".join(f"- {i}" for i in items) if items else CLEAN_REVIEW


def extract_total(text: str) -> int | None:
    """TODO ① ── 宽容地抠出「合计：N 元」—— 真实模型的输出比假模型脏得多。

    要能处理（真实模型都会这么干）：
      · 加粗：合计：**801** 元          ← 课程自带的正则在这里就瞎了
      · 前后有空格 / 全角冒号：合计 ： 801 元
      · 多行前言：好的，这是我的报告：…
    建议两步走：
      1. 先洗一遍：cleaned = re.sub(r"[*`\s]", "", text)
      2. 再找数字：re.search(r"合计[:：](\d+)元", cleaned)
    返回：整数；找不到返回 None。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案（3~4 行）↓↓↓
    raise NotImplementedError("练习 5 · TODO ①  extract_total")
    # ↑↑↑ 你的答案 ↑↑↑


class TolerantVerifier(ReportVerifier):
    """只把「合计」那一步换成你的宽容解析，其余三条规则照旧。"""

    def check(self, text: str, task=TASK_Q1) -> Verdict:
        issues: list[str] = []
        checked: list[str] = []
        clean = re.sub(r"[*`]", "", text)
        for r in task.records:
            want = f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
            checked.append(f"分项 {r.sku}：数量 × 单价 = {r.subtotal}")
            if want not in clean:
                issues.append(f"分项「{r.sku}」缺失或金额不等于 {r.subtotal} 元（应为 `{want}`）")
        total = task.correct_total()
        checked.append(f"合计 = {task.formula_text()} = {total}")
        got = extract_total(text)                          # ← 你的解析器
        if got is None:
            issues.append(f"解析不出「合计：N 元」这一行（逐项重算应为 {total}）")
        elif got != total:
            issues.append(f"合计错误：逐项重算应为 {total}，你写成了 {got}；请把 {got} 改成 {total}")
        checked.append("必须包含「结论：」段落")
        if "结论：" not in text:
            issues.append("缺少「结论：」段落，交付格式不合规")
        return Verdict(ok=not issues, issues=issues, checked=checked)


def dirty_draft() -> str:
    """先看看「脏输出」到底长什么样。不用改。"""
    return DirtyWriterLLM().complete([
        Message.system(SYSTEM_TEMPLATE.format(
            title=TASK_Q1.title, table=TASK_Q1.table_text(), lessons="（暂无历史教训）")),
        Message.user(REQUEST_TEMPLATE.format(title=TASK_Q1.title)),
    ]).text


def my_conclusion() -> str:
    """TODO ② ── 写下你的结论（两句话：① 第一次未必错 ② 错了以后笼统意见救不回来）。"""
    # 写下你的结论：
    #
    #   ↓↓↓ 把下面这行删掉，写上 return "你的结论" ↓↓↓
    raise NotImplementedError("练习 5 · TODO ②  写下你的结论")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def run(label: str, llm, critic, verifier, max_rounds: int = 3):
    agent = ReflexionAgent(llm=llm, critic=critic, verifier=verifier,
                           max_rounds=max_rounds, use_verifier_feedback=False)
    r = agent.run(TASK_Q1)
    head = r.rounds[0].critique.raw.splitlines()[0][:44] if r.rounds else "（无）"
    got = extract_total(r.final)                       # ← 用**你写的**解析器读最终稿
    print(f"  ── {label}")
    print(f"     第 1 轮审查者原话：{head}")
    kv(f"     {label} · 轮数", len(r.rounds))
    kv(f"     {label} · 停机原因", r.stop_reason)
    kv(f"     {label} · 最终合计（你的解析器读出）", f"{got} 元（正确 {TASK_Q1.correct_total()} 元）")
    kv(f"     {label} · 验证通过", "是" if r.verified else "否")
    print()
    return r


def check() -> str:
    print("\n" + "=" * 66)
    print("  真实模型的输出长什么样（离线用 DirtyWriterLLM 复现）")
    print("=" * 66)
    code(dirty_draft(), indent=4)
    print()
    note("课程自带的正则 r\"合计[:：]\\s*(\\d+)\\s*元\" 在这里**匹配不到** —— 加粗的 ** 挡在中间。")
    print()

    print("=" * 66)
    print("  四个场景：脏输出 × 不同审查者")
    print("=" * 66)
    a = run("A · 脏输出 + 第一次就写对 + 放水派审查者",
            DirtyWriterLLM(first_correct=True), ReviewCriticLLM(TASK_Q1, mode="lazy"), TolerantVerifier())
    b = run("B · 脏输出 + 写错了 + 笼统派审查者（不给验证器反馈）",
            DirtyWriterLLM(), ReviewCriticLLM(TASK_Q1, mode="vague"), TolerantVerifier())
    c = run("C · 脏输出 + 写错了 + 课程自带的具体派（正则很严）",
            DirtyWriterLLM(), ReviewCriticLLM(TASK_Q1, mode="specific"), TolerantVerifier())
    d = run("D · 脏输出 + 写错了 + 宽容解析的具体派（用你的 extract_total）",
            DirtyWriterLLM(), TolerantCritic(TASK_Q1, mode="specific"), TolerantVerifier())

    print("  ── 真实模型（可选）──")
    if REAL_LLM is None:
        note("未检测到 API Key → 跳过真实模型这一格（本练习的全部结论离线也能得到）")
        note("想试的话：设置 DEEPSEEK_API_KEY（或 OPENAI/MOONSHOT/… 之一）再重跑本文件。")
    else:
        note(f"检测到真实模型：{REAL_LLM.model} @ {REAL_LLM.base_url}")
        try:
            resp = REAL_LLM.complete([
                Message.system(SYSTEM_TEMPLATE.format(
                    title=TASK_Q1.title, table=TASK_Q1.table_text(), lessons="（暂无历史教训）")),
                Message.user(REQUEST_TEMPLATE.format(title=TASK_Q1.title)),
            ])
            code(resp.text, indent=4)
            kv("你的解析器从真实输出里读出的合计", extract_total(resp.text))
            kv("事实源里的正确合计", TASK_Q1.correct_total())
        except Exception as exc:                       # 网络/额度/Key 都可能失败
            warn(f"真实模型调用失败：{type(exc).__name__}: {exc}")
    print()

    if not a.verified or len(a.rounds) != 1:
        raise NotImplementedError("练习 5 · TODO ① 场景 A 应该 1 轮就通过：解析器还没读懂加粗的合计")
    if b.verified or extract_total(b.final) == TASK_Q1.correct_total():
        raise NotImplementedError("练习 5 · TODO ① 场景 B 不该被修好（笼统意见救不回来），检查解析器")
    if c.verified:
        raise NotImplementedError("练习 5 · TODO ① 场景 C 不该通过：课程自带的具体派读不出脏合计")
    if not d.verified:
        raise NotImplementedError("练习 5 · TODO ① 场景 D 应该一轮改对：宽容解析 + 具体派")

    kv("A 一次调用就收工", f"{a.llm_calls} 次")
    kv("B 花了多少次调用才停", f"{b.llm_calls} 次")
    kv("D 花了几轮改对", f"{len(d.rounds)} 轮 / {d.llm_calls} 次调用")
    print()
    warn("这说明本章的结构与模型强弱无关：**反思是架构问题，不是模型问题。**")
    bullet("真实模型第一次未必算错 —— 但你不能赌它每次都对，所以验证器是必需品。")
    bullet("它一旦算错，笼统的「再检查一遍」依然救不回来；能救的是「事实源 + 可执行修正」。")
    bullet("真实输出更脏（前言、Markdown、全角），所以解析器要更宽容 —— 否则验证器先瞎了。")

    conclusion = my_conclusion().strip()
    if len(conclusion) < 8:
        raise NotImplementedError("练习 5 · TODO ② 结论太短了，把「未必算错」和「救不回来」都写上")
    print()
    kv("你的结论", conclusion)
    return (f"A {a.llm_calls} 次调用通过；B 跑 {len(b.rounds)} 轮仍错；"
            f"C 具体派被脏格式骗过；D {len(d.rounds)} 轮改对")


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
