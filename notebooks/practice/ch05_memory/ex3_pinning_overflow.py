r"""第 05 章 · 练习 3 / 5 · 破坏护栏：把「钉住」变成「什么都钉住」

【要做什么】
  把 `MAX_PINNED` 改成 `1000`，把抽取阈值改成 `0.0`，然后跑一跑。

  观察两件事：钉住区的 token 涨到多少？对话窗口被挤到只剩几轮？

【已经给你了】
  · build_turns(n)     50 轮对话，后面几十轮每轮都会带出一个新的订单号事实
                       —— 专门用来把钉住区撑爆
  · measure(...)       跑对话 + 组装上下文 + 取指标的**成品代码**，
                       只有「抽取器阈值」那一行留给你
  · FactExtractor      事实抽取器：threshold 以下的重要性不钉住（默认 0.75）
  · memory.MAX_PINNED  钉住区上限（默认 8）。你没法改课程源文件，所以这里
                       **在运行时**临时改这个模块常量（measure 里已经包好 try/finally）
  · MemoryManager.build(query) 返回 ContextPack，pack.sections 就是那张预算账本

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch05_memory\ex3_pinning_overflow.py
  3. 验收本章：py scripts/run_all_checks.py 05
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage05_memory import memory                          # noqa: E402
from stages.stage05_memory.memory import (                        # noqa: E402
    PIN_THRESHOLD, FactExtractor, MemoryManager, RuleSummarizer,
)

SYSTEM_PROMPT = "你是团建筹备助手。只依据上下文里出现过的事实回答，不要凭猜测补充。"
QUERY = "帮我订一家餐厅，安排 24 人的团建晚餐。"
BUDGET = 500         # ← 故意给小一点：钉住区一膨胀，窗口立刻就没了

OPENING = [
    ("你好，我叫张三，我在筹备下个月的部门团建。", "你好张三！需要我帮你做什么？"),
    ("我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。", "好的：24 人 / 预算 5000 元 / 3 月 15 日。"),
    ("重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。", "收到，会避开海鲜。"),
]


def build_turns(n: int = 50) -> list[tuple[str, str]]:
    """50 轮对话：后面每一轮都带出一个**新的订单号**（都会被抽成事实）。"""
    turns = list(OPENING)
    for i in range(len(OPENING) + 1, n + 1):
        turns.append((f"第 {i} 轮：订单 A{1000 + i} 的事情你记一下。", "好的，记下了。"))
    return turns


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def measure(budget: int = BUDGET, threshold: float = PIN_THRESHOLD,
            max_pinned: int = memory.MAX_PINNED, rounds: int = 50) -> dict:
    """跑 rounds 轮对话，返回钉住区 / 窗口的实测指标。**只有一行留给你写。**"""
    original = memory.MAX_PINNED
    memory.MAX_PINNED = max_pinned          # ★ 运行时改常量（课程源文件一个字都没动）
    try:
        mgr = MemoryManager(SYSTEM_PROMPT, budget=budget, window_turns=6,
                            summarizer=RuleSummarizer(max_chars=200))

        # TODO ① ── 换掉事实抽取器，让它的阈值等于参数 threshold
        #   提示：mgr.extractor = FactExtractor(threshold=threshold)
        #   为什么要在构造之后换？因为 MemoryManager 内部写死了 FactExtractor()，
        #   而 threshold=0.0 时**任何**被规则抽到的事实都会被判为「该钉住」。
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 3 · TODO ①  把 mgr.extractor 换成 threshold=threshold 的抽取器")
        # ↑↑↑ 你的答案 ↑↑↑

        for user, assistant in build_turns(rounds):
            mgr.add_turn(user, assistant)

        pack = mgr.build(QUERY)
        by_name = {s.name: s for s in pack.sections}
        pin = by_name.get("钉住事实")
        win = by_name.get("对话窗口")
        return {
            "pinned_items": pin.items if pin else 0,
            "pinned_tokens": pin.tokens if pin else 0,
            "window_turns": win.items if win else 0,
            "window_tokens": win.tokens if win else 0,
            "total_tokens": pack.tokens,
            "dropped_turns": pack.dropped_turns,
            "max_pinned": max_pinned,
            "threshold": threshold,
        }
    finally:
        memory.MAX_PINNED = original        # 一定要还原，否则会影响同一进程里的后续实验


# TODO ② ── 纯思考题：写下你的结论（一两句话就行）
#   提示：窗口只剩 1 轮时，如果用户问「我刚才说的最后一句话是什么」，
#         窗口里还有东西吗？而排在最后、占掉大部分预算的那 50 条「订单号」，
#         真的是他这次要问的吗？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        safe = measure(threshold=PIN_THRESHOLD, max_pinned=memory.MAX_PINNED)
        broken = measure(threshold=0.0, max_pinned=1000)

        if broken["pinned_items"] <= safe["pinned_items"]:
            raise AssertionError(
                f"「什么都钉住」之后钉住条数应该暴涨，"
                f"实际 {safe['pinned_items']} -> {broken['pinned_items']}")
        if broken["pinned_tokens"] <= safe["pinned_tokens"] * 3:
            raise AssertionError(
                f"钉住区 token 应该涨好几倍，实际 {safe['pinned_tokens']} -> "
                f"{broken['pinned_tokens']}")
        if broken["window_turns"] >= safe["window_turns"]:
            raise AssertionError(
                f"钉住区膨胀之后，对话窗口应该被挤小，"
                f"实际 {safe['window_turns']} -> {broken['window_turns']} 轮")

        report.append(f"同一个 50 轮任务，预算都是 {BUDGET} token：")
        report.append("")
        for label, m in (("安全配置（阈值 0.75 / 上限 8）", safe),
                         ("破坏配置（阈值 0.0 / 上限 1000）", broken)):
            report.append(f"    {label}")
            report.append(f"        钉住事实 : {m['pinned_items']:>3} 条 / {m['pinned_tokens']:>4} token")
            report.append(f"        对话窗口 : {m['window_turns']:>3} 轮 / {m['window_tokens']:>4} token")
            report.append(f"        合计     : {m['total_tokens']:>4} token"
                          f"（被折叠 {m['dropped_turns']} 轮）")
            report.append("")
        drop = safe["window_turns"] - broken["window_turns"]
        report.append(f"★ 只是把「钉住」的门槛拿掉，对话窗口就从 {safe['window_turns']} 轮掉到 "
                      f"{broken['window_turns']} 轮（少了 {drop} 轮）。")
        report.append("  那 50 条「订单号」把预算全吃掉了，而它们**全都是噪音**。")
        report.append("")
        report.append("★ 这条实证对应本章的一句话：")
        report.append("  **任何「永不淘汰」的机制都必须自带配额** ——")
        report.append("  钉住区没有上限，它自己就会变成新的超支来源，")
        report.append("  而且它挤掉的恰恰是「最近几轮原文」这种最不可替代的信息。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 3 · TODO ②  写下你的结论")
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
