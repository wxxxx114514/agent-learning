r"""第 05 章 · 练习 4 / 5 · 换一种淘汰策略：按「重要性密度」淘汰

【要做什么】
  现在超窗的消息是**整轮**折进摘要（谁老谁先走）。
  请改成按「每条消息的价值 / token 数」排序淘汰，优先保留高密度的消息。

  对比一下：你的新策略和「整轮折叠」相比，同样的预算下多保住了几条事实？

【已经给你了】
  · build_turns(50)             前 4 轮是干货，后面全是噪音
  · extract_facts(turns)        用课程自带的 FactExtractor 把每轮抽出的事实收集起来
  · density_key(turn, facts_per_turn)
                                你要写的函数：返回这一轮的「价值密度」
  · select_by_density(...)      按密度贪心装填的成品代码（排序、装填、还原顺序都写好了）
  · naive_truncate(...)         对照基线：只保留最近 N 轮（新手最常写的代码）
  · KEY_FACTS / count_survived  关键事实清单 + 统计它们还剩几条

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch05_memory\ex4_density_eviction.py
  3. 验收本章：py scripts\run_all_checks.py 05
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from collections import Counter                     # noqa: E402

from core.llm import estimate_tokens                # noqa: E402
from core.message import Message                    # noqa: E402
from stages.stage05_memory.memory import (          # noqa: E402
    FactExtractor, Turn, naive_truncate,
)

SYSTEM_PROMPT = "你是团建筹备助手。只依据上下文里出现过的事实回答，不要凭猜测补充。"
QUERY = "帮我订一家餐厅，安排 24 人的团建晚餐。"
BUDGET = 200          # 留给「对话窗口」的预算
KEEP_LAST = 6         # 对照基线保留几轮

# 关键事实：丢了任意一条都会出事
KEY_FACTS = {"张三": "姓名", "海鲜": "饮食禁忌", "5000": "预算",
             "A1001": "订单号", "24": "人数"}

OPENING = [
    ("你好，我叫张三，我在筹备下个月的部门团建。", "你好张三！需要我帮你做什么？"),
    ("我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。", "好的：24 人 / 预算 5000 元 / 3 月 15 日。"),
    ("重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。", "收到，会避开海鲜。"),
    ("另外订单 A1001 的发票麻烦一起处理。", "好的，订单 A1001 的发票记下了。"),
]
NOISE_TOPICS = ["桌游道具", "交通安排", "拍照留念", "签到表", "伴手礼",
                "座位安排", "饮料清单", "背景音乐", "伴手礼包装", "游戏奖品"]


def build_turns(n: int = 50) -> list[Turn]:
    """造 n 轮对话：前 4 轮是干货，后面全是噪音。"""
    pairs = list(OPENING)
    for i in range(len(OPENING) + 1, n + 1):
        topic = NOISE_TOPICS[i % len(NOISE_TOPICS)]
        pairs.append((f"第 {i} 轮：再确认一下{topic}的事，你记一下。",
                      f"好的，第 {i} 轮关于{topic}的信息我记下了，后面安排的时候我会主动提醒你。"))
    return [Turn(index=i, user=u, assistant=a) for i, (u, a) in enumerate(pairs, 1)]


def extract_facts(turns: list[Turn]):
    """用课程自带的抽取器把每轮抽出的事实收集成一个列表。"""
    extractor = FactExtractor()
    return [f for t in turns for f in extractor.extract(t.user, turn=t.index)]


def select_by_density(turns: list[Turn], facts, budget: int = BUDGET) -> list[Turn]:
    """按密度从高到低贪心装填，直到预算用完；返回按时间顺序排好的轮次。**成品代码。**"""
    facts_per_turn = Counter(f.turn for f in facts)
    ranked = sorted(turns, key=lambda t: -density_key(t, facts_per_turn))
    picked: list[Turn] = []
    used = 0
    for turn in ranked:
        if used + turn.tokens > budget:
            continue
        picked.append(turn)
        used += turn.tokens
    return sorted(picked, key=lambda t: t.index)


def count_survived(msgs: list[Message]) -> tuple[list[str], list[str]]:
    """统计关键事实在上下文里还剩几条。返回 (保住的, 丢掉的)。"""
    text = "\n".join(m.content for m in msgs)
    kept = [name for value, name in KEY_FACTS.items() if value in text]
    lost = [name for value, name in KEY_FACTS.items() if value not in text]
    return kept, lost


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def density_key(turn: Turn, facts_per_turn: Counter) -> float:
    """返回这一轮的「价值密度」= 抽出的事实数 / 这一轮的 token 数。

    参数 turn          ：一轮对话（turn.index 是轮号，turn.tokens 是它的 token 数）
         facts_per_turn：{轮号: 这一轮抽出的事实数}（Counter，取不到就是 0）

    TODO ── 一行就够：
        return facts_per_turn.get(turn.index, 0) / max(turn.tokens, 1)

    为什么用密度而不是「事实数」？
        因为一轮话可能有 10 条事实但有 2000 token —— 它占的位置也是 10 条事实的 100 倍。
        用「每 token 换来多少事实」排序，才是在有限预算下的正确取舍。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO  density_key：事实数 / token 数")
    # ↑↑↑ 你的答案 ↑↑↑


# TODO ② ── 纯思考题：写下你的结论（一两句话就行）
#   提示：看运行结果的最后两行 —— 同样的（甚至更小的）预算，
#         你的策略保住了几条关键事实？「只留最近 6 轮」保住了几条？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        turns = build_turns(50)
        facts = extract_facts(turns)
        if not facts:
            raise AssertionError("一轮事实都没抽到，检查 build_turns 的输入")

        probe = density_key(turns[1], Counter({2: 3}))       # 第 2 轮：3 条事实
        if probe <= 0:
            raise AssertionError("第 2 轮明明有 3 条事实，密度不该是 0")
        if density_key(turns[9], Counter({2: 3})) != 0.0:
            raise AssertionError("噪音轮（0 条事实）的密度应该是 0")

        kept_turns = select_by_density(turns, facts, BUDGET)
        density_msgs = [Message.system(SYSTEM_PROMPT)]
        for t in kept_turns:
            density_msgs.extend(t.messages)
        density_msgs.append(Message.user(QUERY))

        naive_msgs = naive_truncate(SYSTEM_PROMPT, turns, keep_last=KEEP_LAST, query=QUERY)

        d_kept, d_lost = count_survived(density_msgs)
        n_kept, n_lost = count_survived(naive_msgs)

        if not d_kept:
            raise AssertionError("按密度挑选之后一条关键事实都没保住，检查 density_key 的方向（越大越先留）")
        if len(d_kept) <= len(n_kept):
            raise AssertionError(
                f"密度策略应该比「只留最近 6 轮」保住更多关键事实，"
                f"实际 {len(d_kept)} vs {len(n_kept)}"
                "（检查密度是不是被算反了：应该按密度**从高到低**装填）")

        report.append(f"{len(turns)} 轮对话 / {len(facts)} 条事实 / 窗口预算 {BUDGET} token")
        report.append("")
        for label, msgs, kept, lost in (
                (f"只留最近 {KEEP_LAST} 轮（对照基线）", naive_msgs, n_kept, n_lost),
                ("按重要性密度淘汰（你的策略）", density_msgs, d_kept, d_lost)):
            # 窗口占用 = 除「系统提示」和「当前问题」之外的那些消息
            used = sum(estimate_tokens(m.content) for m in msgs[1:-1])
            report.append(f"    {label}")
            report.append(f"        保住的关键事实 : {len(kept)}/{len(KEY_FACTS)}  {kept}")
            report.append(f"        丢掉的关键事实 : {lost}")
            report.append(f"        窗口占用       : 约 {used} token")
            report.append("")
        report.append("★ 读表要点：")
        report.append("  · 「只留最近 6 轮」把最早说的姓名/忌口/预算/订单号**全丢了** ——")
        report.append("    因为按时间淘汰 = 按无关性淘汰；")
        report.append("    （如果它侥幸留下一条，多半是噪音里凑巧出现了同样的字符，"
                      "比如「第 24 轮」里的 24）；")
        report.append("  · 密度策略花更少的 token，却把高价值的那几轮全保住了；")
        report.append("  · 这就是「先有数字，再谈改进」（第 10 章评测集）的雏形。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 4 · TODO ②  写下你的结论")
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
