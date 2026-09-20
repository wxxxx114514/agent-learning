r"""第 05 章 · 练习 2 / 5 · 给摘要加一个「覆盖度自检」

【要做什么】
  写一个 `summary_covers(summary, facts)`：检查所有被抽出的事实是否都能在摘要里找到，
  并统计漏检率。目标是**量化摘要的漏检**，而不是假设它不漏。

【已经给你了】
  · build_turns(n)       50 轮对话：**前 4 轮是干货**（姓名/人数/预算/日期/过敏/订单号），
                         后面 46 轮全是噪音
  · SYSTEM_PROMPT / QUERY
  · MemoryManager        四件套的成品实现（窗口 + 摘要 + 钉住 + 长期存储）
  · RuleSummarizer       确定性的规则摘要器（模拟"摘要模型"这个角色）
  · bigrams(text)        中文按字符二元组切分，用它算重叠度

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch05_memory\ex2_summary_coverage.py
  3. 验收本章：py scripts\run_all_checks.py 05
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage05_memory.memory import (   # noqa: E402
    MemoryManager, RuleSummarizer, bigrams,
)

SYSTEM_PROMPT = "你是团建筹备助手。只依据上下文里出现过的事实回答，不要凭猜测补充。"
QUERY = "帮我订一家餐厅，安排 24 人的团建晚餐。"

OPENING = [
    ("你好，我叫张三，我在筹备下个月的部门团建。", "你好张三！需要我帮你做什么？"),
    ("我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。", "好的：24 人 / 预算 5000 元 / 3 月 15 日。"),
    ("重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。", "收到，会避开海鲜。"),
    ("另外订单 A1001 的发票麻烦一起处理。", "好的，订单 A1001 的发票记下了。"),
]
NOISE_TOPICS = ["桌游道具", "交通安排", "拍照留念", "签到表", "伴手礼",
                "座位安排", "饮料清单", "背景音乐", "伴手礼包装", "游戏奖品"]


def build_turns(n: int = 50) -> list[tuple[str, str]]:
    """造 n 轮对话：前 4 轮是干货，后面全是噪音（真实对话就是这样）。"""
    turns = list(OPENING)
    for i in range(len(OPENING) + 1, n + 1):
        topic = NOISE_TOPICS[i % len(NOISE_TOPICS)]
        turns.append((f"第 {i} 轮：再确认一下{topic}的事，你记一下。",
                      f"好的，第 {i} 轮关于{topic}的信息我记下了。"))
    return turns


def build_manager(rounds: int = 50, use_pinning: bool = True) -> MemoryManager:
    """跑完 rounds 轮对话，返回那个 MemoryManager（里面已经有事实、摘要、存储了）。"""
    mgr = MemoryManager(SYSTEM_PROMPT, budget=1200, window_turns=6,
                        summarizer=RuleSummarizer(max_chars=200), use_pinning=use_pinning)
    for user, assistant in build_turns(rounds):
        mgr.add_turn(user, assistant)
    return mgr


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def summary_covers(summary: str, facts) -> dict:
    """检查每条事实是否能在摘要里找到 —— 量化「摘要漏了什么」。

    参数 summary：摘要文本
         facts  ：要检查的事实列表（list[Fact]）
    返回        ：{"covered": [事实文本...], "missing": [事实文本...], "coverage": 0~1}

    前后都写好了（循环、返回结构、漏检率计算），你只写中间那个判断。

    TODO ── 用字符二元组算重叠：重叠 >= 1 就算「摘要里提到了这条事实」。
        提示：
            hits = bigrams(fact.text) & bigrams(summary)
            if len(hits) >= 1:
                covered.append(fact.text)
            else:
                missing.append(fact.text)

    为什么用二元组而不是 `in`？
        因为摘要几乎不可能一字不差地复述原句（"我对海鲜过敏" -> "餐厅要避开海鲜"），
        用二元组重叠才能抓住「同一个信息换了个说法」。
    """
    covered: list[str] = []
    missing: list[str] = []
    for fact in facts:
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 2 · TODO  summary_covers：用 bigrams() 算重叠判定")
        # ↑↑↑ 你的答案 ↑↑↑

    total = len(covered) + len(missing)
    return {
        "covered": covered,
        "missing": missing,
        "coverage": (len(covered) / total) if total else 1.0,
    }


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        mgr = build_manager(50)
        if not mgr.facts:
            raise AssertionError("50 轮对话之后一条事实都没抽到，检查 build_turns 的输入")

        result = summary_covers(mgr.summary_text, mgr.facts)
        for key in ("covered", "missing", "coverage"):
            if key not in result:
                raise AssertionError(f"返回的 dict 里缺少 {key!r}")
        if len(result["covered"]) + len(result["missing"]) != len(mgr.facts):
            raise AssertionError(
                f"covered + missing 应该等于事实总数 {len(mgr.facts)}，"
                f"实际 {len(result['covered'])} + {len(result['missing'])}")
        if not result["missing"]:
            raise AssertionError(
                "摘要不可能不漏 —— 一条都没漏，说明判定太宽松了（检查重叠阈值）")

        # 对照实验：拆掉钉住区之后，摘要漏掉的那条还能不能救回来？
        pack_pinned = mgr.build(QUERY)
        ctx_pinned = "\n".join(m.content for m in pack_pinned.messages)
        no_pin_mgr = build_manager(50, use_pinning=False)
        pack_no_pin = no_pin_mgr.build(QUERY)
        ctx_no_pin = "\n".join(m.content for m in pack_no_pin.messages)

        report.append(f"50 轮对话，抽出 {len(mgr.facts)} 条事实（窗口只留最近 6 轮）：")
        for f in mgr.facts:
            report.append(f"    - {f.text}（重要性 {f.importance:.2f}）")
        report.append("")
        report.append(f"摘要全文（{len(mgr.summary_text)} 字）：")
        report.append(f"    {mgr.summary_text[:120]}…")
        report.append("")
        report.append(f"覆盖度自检结果：coverage = {result['coverage']:.0%}"
                      f"（{len(result['covered'])}/{len(mgr.facts)} 条能在摘要里找到）")
        report.append(f"    摘要里找不到的：{result['missing']}")
        report.append("")
        report.append("★ 摘要一直都在漏 —— 这很正常，它就是有损压缩。")
        report.append("  关键在于：漏掉的那条，别的地方兜住了吗？")
        report.append("")
        for label, ctx, missing_list in (
                ("钉住区开着（默认）", ctx_pinned, result["missing"]),
                ("钉住区关掉（use_pinning=False）", ctx_no_pin, result["missing"])):
            lost = [m for m in missing_list if m.split("：")[-1] not in ctx]
            report.append(f"    {label}")
            report.append(f"        这些漏检的事实，有几条在最终上下文里彻底消失了：{len(lost)} 条 {lost}")
        report.append("")
        report.append("★ 结论：**摘要一定会漏，钉住区就是给漏检兜底的那一层。**")
        report.append("  拆掉钉住区，第 1 轮说的「姓名：张三」就从上下文里彻底消失了 ——")
        report.append("  而用户下一句很可能就是「你还记得我叫什么吗」。")
        report.append("  这就是「四层纵深防御」的意思：摘要漏掉的靠钉住兜，钉住装不下的靠存储兜。")
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
