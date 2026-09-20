r"""第 08 章 · 练习 5 / 5 · 设计一个「真的需要多智能体」的任务

【要做什么】
  **设计一个「真的需要多智能体」的任务。**
  从下面三个候选人里挑，并写出理由：
    ① 把这段中文翻译成英文并检查语法；
    ② 读三份不同格式的财报，各自抽取关键指标，再合成一张对比表；
    ③ 帮我写一首诗。

【已经给你了】
  · 三个候选人 + 一套跑得起来的成本模型（子任务数 → 调用次数 / 上下文字符数）
  · 三种方案的账单模拟：单 Agent 一把梭 / 隔离式分工 / 共享上下文自由讨论
  · 两个判据（题面提示里的原话），打印出来给你当检查表

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch08_multi_agent\ex5_task_design.py
  3. 验收本章：py scripts\run_all_checks.py 08
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                          # noqa: E402

# (任务描述, 能切出几块互不依赖的子任务)  —— 子任务数是**成本模型的假设**，你可以质疑它
CANDIDATES: dict[str, tuple[str, int]] = {
    "①": ("把这段中文翻译成英文并检查语法", 2),
    "②": ("读三份不同格式的财报，各自抽取关键指标，再合成一张对比表", 3),
    "③": ("帮我写一首诗", 1),
}

CRITERIA = (
    "子任务需要**不同的知识**吗？",
    "上下文能**切干净**吗？",
)

# 成本模型的常量（和课程 ③ 节的估算用的是同一套）
SYSTEM_CHARS = 60      # 每个专家的岗位说明书
TASK_CHARS = 40        # 主管给的子任务
FACT_CHARS = 120       # 主管随附的结构化事实
SPEECH_CHARS = 90      # 每次发言的长度


def single_agent(experts: int) -> tuple[int, int]:
    """方案 A：一个 Agent 全干（1 次调用，但要把所有资料塞进一个上下文）。"""
    return 1, 900


def split_agents(experts: int) -> tuple[int, int]:
    """方案 B：隔离式分工 —— 每个专家只读自己的说明书 + 子任务。"""
    return experts, experts * (SYSTEM_CHARS + TASK_CHARS + FACT_CHARS)


def shared_agents(experts: int, rounds: int = 2) -> tuple[int, int]:
    """方案 C：共享上下文自由讨论 —— 每次发言都要重读全部历史。"""
    calls = experts * rounds
    sizes = [SYSTEM_CHARS + TASK_CHARS + i * SPEECH_CHARS for i in range(calls)]
    return calls, sum(sizes)


def cost_table() -> None:
    """把三种方案的账单打印出来。不用改。"""
    print(f"  {'候选人':<6}{'子任务':<8}{'A 单Agent':<16}{'B 隔离分工':<16}{'C 共享讨论'}")
    print("  " + "-" * 72)
    for key, (desc, n) in CANDIDATES.items():
        a = single_agent(n)
        b = split_agents(n)
        c = shared_agents(n)
        print(f"  {key:<6}{n:<8}"
              f"{f'{a[0]} 次 / {a[1]} 字':<16}"
              f"{f'{b[0]} 次 / {b[1]} 字':<16}"
              f"{f'{c[0]} 次 / {c[1]} 字'}")
    print()


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def my_choice() -> str:
    """TODO ── 选一个任务，并写出理由。

    写法（一行，以 ①/②/③ 开头，带上「理由：」）：
        return "② ｜ 理由：三份财报的解析互不依赖、格式各自独立，最后合成表是确定性汇总步骤"

    自检清单（就是上面打印的那两个判据）：
      · 子任务需要不同的知识吗？  —— 不需要 → 那是「同一个 Agent 调两次」，分工只会多花钱
      · 上下文能切干净吗？        —— 切不干净 → 隔离出来的专家会缺材料，反而更容易出错
    """
    # 写下你的结论：
    #
    #   ↓↓↓ 把下面这行删掉，写上 return "你的选择 ｜ 理由：…" ↓↓↓
    raise NotImplementedError("练习 5 · TODO  选出真正需要多智能体的任务并写出理由")
    # ↑↑↑ 你的答案 ↑↑↑
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


REFERENCE = {
    "①": "更像是「同一个 Agent 调两次」：翻译和语法检查用的是同一份知识、同一段上下文，"
          "分出去只会多花两次调用的钱。",
    "②": "最像正确答案：三份财报的解析互不依赖、格式各自独立，"
          "最后合成一张表需要的是一个**确定性**的汇总步骤。",
    "③": "一首诗不需要两套知识、也不需要切上下文 —— 单 Agent 写完就完事。",
}


def check() -> str:
    print("\n" + "=" * 66)
    print("  先算账：三个候选人，三种方案的调用次数与上下文字符数")
    print("=" * 66)
    cost_table()
    note("子任务数只是成本模型的假设 —— 关键是问自己：**这个任务真的能切吗？**")
    print()

    print("  ── 判据（题面提示里的两个问题）──")
    for i, c in enumerate(CRITERIA, 1):
        print(f"     {i}. {c}")
    print()

    choice = my_choice().strip()
    if not choice or choice[0] not in CANDIDATES:
        raise NotImplementedError("练习 5 · TODO  答案要以 ①/②/③ 开头（例如：② ｜ 理由：…）")
    if "理由" not in choice or len(choice) < 15:
        raise NotImplementedError(
            "练习 5 · TODO  理由还没写：用上面两个判据（需要不同知识吗？上下文能切干净吗？）说清楚")

    picked = choice[0]
    print("  ── 你的选择 ──")
    print(f"     {choice}")
    kv("候选任务", CANDIDATES[picked][0])
    kv("子任务数（成本模型）", CANDIDATES[picked][1])
    calls_single, chars_single = single_agent(CANDIDATES[picked][1])
    calls_split, chars_split = split_agents(CANDIDATES[picked][1])
    kv("单 Agent", f"{calls_single} 次调用 / {chars_single} 字上下文")
    kv("隔离式分工", f"{calls_split} 次调用 / {chars_split} 字上下文")
    print()

    print("  ── 参考分析（课程提示里的原话）──")
    for key, text in REFERENCE.items():
        mark = "★" if key == picked else " "
        print(f"   {mark} {key} {text}")
    print()
    if picked == "②":
        note("选对了：三份财报的解析互不依赖、格式各自独立 —— 这正是「能切干净」的样子。")
    else:
        note("选它不是错，但要能说服自己：**它切出来的子任务真的需要不同的知识吗？**")
    warn("记住选型原则：**先单 Agent；只有当子任务需要不同知识、且上下文能切干净时，才分工。**")
    bullet("分工的收益：专业化 + 上下文隔离；代价：N 倍调用 + 责任边界变模糊。")
    bullet("「谁来审查审查者」是多智能体天然带来的新问题（第 07 章已经见过一半）。")
    return f"你选了 {picked}：{CANDIDATES[picked][0]}（分工 {calls_split} 次调用 vs 单 Agent {calls_single} 次）"


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
