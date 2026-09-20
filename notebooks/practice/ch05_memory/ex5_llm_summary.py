r"""第 05 章 · 练习 5 / 5 · 把规则摘要换成模型摘要（以及它失败时怎么办）

【要做什么】
  写一个假模型（继承 `core.llm.LLM`，实现 `_complete()`），让它扮演摘要模型，
  用 `SUMMARY_PROMPT` 那种提示词。对比两种摘要的 token 数与关键信息保留量。

  然后回答一个工程问题：**摘要调用失败时（返回空 / 超长 / 胡说）怎么办？**

【已经给你了】
  · OPENING / PIECES      要压缩的对话（前 4 轮，里面有全部关键事实）
  · KEEP_HINTS            值得保留的句子特征词（规则摘要器就是靠它挑句子的）
  · FakeSummaryLLM        假摘要模型：`mode` 四种取值 ok / empty / huge / boom，
                          其中只有 ok 那一支留给你写
  · RuleSummarizer        规则版摘要器（确定性，用来做对照）
  · LLMSummarizer         真实做法：`summarize(pieces)` 内部会渲染 SUMMARY_PROMPT
                          并调用模型的 `complete()` —— 它**不会**处理失败，正是本练习要补的
  · safe_summarize(...)   你要写的函数：带失败处理的摘要调用

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch05_memory\ex5_llm_summary.py
  3. 验收本章：py scripts\run_all_checks.py 05
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.llm import LLM, LLMResponse, estimate_tokens   # noqa: E402
from core.message import Message                          # noqa: E402
from stages.stage05_memory.memory import (                # noqa: E402
    LLMSummarizer, RuleSummarizer, SUMMARY_PROMPT,
)

MAX_CHARS = 200

OPENING = [
    ("你好，我叫张三，我在筹备下个月的部门团建。", "你好张三！需要我帮你做什么？"),
    ("我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。", "好的：24 人 / 预算 5000 元 / 3 月 15 日。"),
    ("重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。", "收到，会避开海鲜。"),
    ("另外订单 A1001 的发票麻烦一起处理。", "好的，订单 A1001 的发票记下了。"),
    ("顺便说一句，今天天气不错。", "是的，今天天气很好。"),          # 寒暄，应该被丢掉
]
PIECES = [f"{user}。{assistant}" for user, assistant in OPENING]

KEEP_HINTS = ("预算", "日期", "过敏", "人数", "订单", "发票", "元", "一共", "人")

OLD_SUMMARY = "我们一共 24 人，预算 5000 元。"        # 上一轮的旧摘要


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class FakeSummaryLLM(LLM):
    """扮演摘要模型的假模型（确定性，零依赖）。

    mode = "ok"    ：正常写摘要       -> 你来实现
    mode = "empty" ：返回空白         -> 模拟「模型什么都没说」
    mode = "huge"  ：返回超长废话     -> 模拟「模型刹不住车」
    mode = "boom"  ：直接抛异常       -> 模拟「摘要服务 500/超时」
    """

    name = "fake-summary"

    def __init__(self, mode: str = "ok", model: str = "fake-summary") -> None:
        super().__init__(model)
        self.mode = mode

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        # ---- 三种「坏掉」的行为已经写好了，不用改 ----
        if self.mode == "boom":
            raise RuntimeError("模拟摘要服务 500")
        if self.mode == "empty":
            return LLMResponse(text="   \n  ", model=self.name)
        if self.mode == "huge":
            return LLMResponse(text="这段摘要越写越长" * 400, model=self.name)

        # ---- 正常模式：你来写 ----
        # TODO ① ── 从 messages 里取出提示词（最后一条 user 消息），
        #          把「对话：」之后的内容按行挑一遍：
        #            · 只保留含 KEEP_HINTS 里任意一个词的句子（寒暄会被自动丢掉）
        #            · 用「；」把它们拼成一段话，并截断到 MAX_CHARS
        #            · 包成 LLMResponse(text=..., model=self.name) 返回
        #
        #   提示（照这个改就行）：
        #       prompt = messages[-1].content
        #       transcript = prompt.split("对话：", 1)[-1]
        #       kept = [ln.strip() for ln in transcript.splitlines()
        #               if any(h in ln for h in KEEP_HINTS)]
        #       return LLMResponse(text="；".join(kept)[:MAX_CHARS], model=self.name)
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ①  FakeSummaryLLM._complete 的正常模式")
        # ↑↑↑ 你的答案 ↑↑↑


def safe_summarize(summarizer, pieces, old_summary: str,
                   max_chars: int = MAX_CHARS) -> tuple[str, str]:
    """带失败处理的摘要调用。返回 (新摘要, 告警)。

    三条纪律（题目要求，一条都不能少）：
      ① 返回空/空白      -> 保留旧摘要，并记一条告警（**绝不因为摘要失败而丢历史**）
      ② 返回超长         -> 截断到 max_chars，并记一条告警
      ③ 抛异常           -> 保留旧摘要，并记一条告警

    前后都写好了（告警变量、异常分支、返回值），你只写 try 里那几行。

    TODO ② ── 在 try 里写：
        text = summarizer.summarize(pieces).strip()
        if not text:
            return old_summary, "摘要返回空，保留旧摘要"
        if len(text) > max_chars:
            warning = f"摘要超长（{len(text)} 字），已截断"
            text = text[:max_chars]
    注意：结尾直接 `return text, warning` —— 它已经在下面写好了。
    """
    warning = ""
    try:
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ②  safe_summarize 里的三步处理")
        # ↑↑↑ 你的答案 ↑↑↑
    except NotImplementedError:
        raise                      # ★ 别把「还没写」当成模型故障吞掉
    except Exception as exc:
        return old_summary, f"摘要调用失败（{type(exc).__name__}: {exc}），保留旧摘要"
    return text, warning


# TODO ③ ── 纯思考题：写下你的结论（一两句话就行）
#   提示：摘要是有损压缩、而且它自己也是一次可能失败的调用。
#         如果摘要失败时你选择「用空摘要覆盖旧的」，会发生什么？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        # ---- ⓪ 先单独验一下假摘要模型本身（TODO ①）----
        # 这里直接调 _complete（而不是 complete），是为了让「还没写」原样冒出来 ——
        # complete() 会把任何异常包装成 LLMError，把 NotImplementedError 也一起吞掉。
        probe_prompt = SUMMARY_PROMPT.format(max_chars=MAX_CHARS,
                                             transcript="\n".join(PIECES))
        probe = FakeSummaryLLM("ok")._complete(
            [Message.system("你是一个擅长压缩对话的助手。"), Message.user(probe_prompt)]).text
        if not probe.strip():
            raise AssertionError("TODO ① 输出的摘要不该是空的（检查是不是把句子全过滤掉了）")
        if "预算" not in probe or "过敏" not in probe:
            raise AssertionError(
                f"TODO ① 应该保留含 KEEP_HINTS 的句子，实际拿到：{probe[:60]!r}")
        if "天气" in probe:
            raise AssertionError("寒暄那句（今天天气不错）应该被丢掉，摘要里不该出现它")

        # ---- ① 正常模式：模型摘要 vs 规则摘要 ----
        rule = RuleSummarizer(max_chars=MAX_CHARS).summarize(PIECES)
        llm_sum = LLMSummarizer(FakeSummaryLLM("ok"), max_chars=MAX_CHARS)
        model_sum, warning = safe_summarize(llm_sum, PIECES, OLD_SUMMARY)
        if warning:
            raise AssertionError(f"正常模式下不该有告警，实际：{warning}")
        if not model_sum.strip():
            raise AssertionError("模型摘要不该是空的 —— 检查 TODO ① 是不是把句子都过滤掉了")
        if len(model_sum) > MAX_CHARS:
            raise AssertionError(f"摘要长度应该被截断到 {MAX_CHARS}，实际 {len(model_sum)}")
        if llm_sum.calls != 1:
            raise AssertionError(f"应该正好调用了一次模型，实际 {llm_sum.calls} 次")

        # ---- ② 失败注入：空 / 超长 / 抛异常 ----
        empty_sum, empty_warn = safe_summarize(
            LLMSummarizer(FakeSummaryLLM("empty")), PIECES, OLD_SUMMARY)
        huge_sum, huge_warn = safe_summarize(
            LLMSummarizer(FakeSummaryLLM("huge")), PIECES, OLD_SUMMARY)
        boom_sum, boom_warn = safe_summarize(
            LLMSummarizer(FakeSummaryLLM("boom")), PIECES, OLD_SUMMARY)

        if empty_sum != OLD_SUMMARY or not empty_warn:
            raise AssertionError(
                f"空摘要必须保留旧摘要并告警，实际 ({empty_sum!r}, {empty_warn!r})")
        if len(huge_sum) > MAX_CHARS + 1 or not huge_warn:
            raise AssertionError(
                f"超长摘要必须截断到 {MAX_CHARS} 并告警，实际长度 {len(huge_sum)}、告警 {huge_warn!r}")
        if boom_sum != OLD_SUMMARY or not boom_warn:
            raise AssertionError(
                f"调用抛异常时必须保留旧摘要并告警，实际 ({boom_sum!r}, {boom_warn!r})")

        raw_tokens = sum(estimate_tokens(p) for p in PIECES)
        report.append(f"要压缩的对话：{len(PIECES)} 段 / {raw_tokens} token")
        report.append("")
        report.append("① 两种摘要器对比（都截到 "
                      f"{MAX_CHARS} 字以内）：")
        for label, text in (("规则摘要器 RuleSummarizer", rule),
                            ("模型摘要器 LLMSummarizer(FakeSummaryLLM)", model_sum)):
            report.append(f"    {label}")
            report.append(f"        {estimate_tokens(text):>4} token | {text[:88]}")
        report.append("")
        report.append("    关键事实保留情况：")
        for value, name in (("张三", "姓名"), ("海鲜", "饮食禁忌"), ("5000", "预算"),
                            ("A1001", "订单号"), ("24", "人数")):
            mark_model = "✅" if value in model_sum else "—"
            mark_rule = "✅" if value in rule else "—"
            report.append(f"        {name:<6} 模型 {mark_model}   规则 {mark_rule}")
        report.append("")
        report.append("② 三种失败注入的结果（这才是本练习的重点）：")
        for label, text, warn in (("模型返回空白", empty_sum, empty_warn),
                                  ("模型返回超长", huge_sum, huge_warn),
                                  ("模型调用抛异常", boom_sum, boom_warn)):
            report.append(f"    {label}")
            report.append(f"        摘要 = {text[:52]!r}")
            report.append(f"        告警 = {warn}")
        report.append("")
        report.append("★ 三条纪律背后的同一个原则：**绝不因为摘要失败而丢历史。**")
        report.append("  摘要是有损压缩，又依赖一次可能失败的外部调用 ——")
        report.append("  把它当成「唯一的历史来源」，就等于把全部记忆押在一次 500 上。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 5 · TODO ③  写下你的结论")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    for line in report:
        print(line)
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
