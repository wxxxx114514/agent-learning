r"""第 08 章 · 练习 3 / 5 · 加第四个专家（合规专家）：这一步真的需要模型吗？

【要做什么】
  **加第四个专家（合规专家）。**
  让它在文案专家之后跑，检查禁用词和金额，把结论用 `topic="result"` 回给主管。
  然后回答：这一步真的需要模型吗？还是 6 行 if/else 更合适？

【已经给你了】
  · good_reply()：隔离版团队产出的、**可以对外发送**的回复
  · bad_reply()：单 Agent 一把梭产出的、**含越权承诺 + 内部备注**的回复
  · deliver()：闸门 —— 合规通过就直接发出，不通过就换成 HOLD_REPLY（转人工）
  · FORBIDDEN：合规禁用词清单（由合规部门定义，不由模型定义）
  · verify_reply()：课程自带的对外回复验收器（可以和你写的规则对照看）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch08_multi_agent\ex3_compliance_node.py
  3. 验收本章：py scripts\run_all_checks.py 08
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, code, kv, note, warn                     # noqa: E402
from stages.stage08_multi_agent.demo import (                             # noqa: E402
    HOLD_REPLY, TICKET, build_team, run_single_agent, verify_reply,
)

FORBIDDEN = ("现金赔付", "50 元", "内部备注", "勿外传")     # 合规部门定的禁用词
REQUIRED_CODE = "B-2"          # 必须能溯源的条款编号
REQUIRED_FIX = "运费券"        # 必须给出的正确补偿方案


def good_reply() -> str:
    """隔离版团队的真实产出（可以对外发送）。不用改。"""
    _bus, supervisor = build_team()
    return supervisor.run(TICKET).final_reply


def bad_reply() -> str:
    """单 Agent 一把梭的真实产出（越权承诺 + 内部信息）。不用改。"""
    text, _calls, _chars = run_single_agent(TICKET)
    return text


def deliver(reply: str) -> tuple[str, list[str]]:
    """交付闸门：合规就发出，不合规就转人工。不用改。"""
    issues = compliance_check(reply)
    return (reply, []) if not issues else (HOLD_REPLY, issues)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def compliance_check(reply: str) -> list[str]:
    """TODO ① ── 用 6 行确定性代码，替代一个「模型自审」节点。

    规则（合规要求**每次判断都一样**，所以只有 if/else，没有模型）：
      1. 出现 FORBIDDEN 里的任意词 → 记一条 "出现禁用词：{词}"
      2. REQUIRED_CODE 不在回复里     → 记一条 "未引用条款编号，处理依据不可溯源"
      3. REQUIRED_FIX 不在回复里      → 记一条 "未给出正确的补偿方案（20 元运费券）"

    返回：问题清单（空 = 可以对外发送）。
    提示：for word in FORBIDDEN: if word in reply: issues.append(...)
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案（5~7 行）↓↓↓
    raise NotImplementedError("练习 3 · TODO ①  compliance_check")
    # ↑↑↑ 你的答案 ↑↑↑


def my_conclusion() -> str:
    """TODO ② ── 回答题面：这一步真的需要模型吗？为什么？

    提示：合规要求「每次判断都一样」，而模型给不了这个保证 —— 这句话本身就够写一句结论了。
    """
    # 写下你的结论：
    #
    #   ↓↓↓ 把下面这行删掉，写上 return "你的结论" ↓↓↓
    raise NotImplementedError("练习 3 · TODO ②  写下你的结论")
    # ↑↑↑ 你的答案 ↑↑↑
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def show(title: str, reply: str) -> list[str]:
    print(f"  ── {title}")
    code(reply, indent=4)
    sent, issues = deliver(reply)
    if not issues:
        print("     合规检查：✅ 0 项问题 → 直接发给客户")
    else:
        print(f"     合规检查：❌ {len(issues)} 项问题 → 换成转人工话术")
        for i in issues:
            print(f"        · {i}")
    print()
    return issues


def check() -> str:
    print("\n" + "=" * 66)
    print("  第四个专家（合规节点）：文案专家之后再过一道闸门")
    print("=" * 66)

    good = good_reply()
    bad = bad_reply()
    good_issues = show("① 隔离版团队的回复", good)
    bad_issues = show("② 单 Agent 一把梭的回复", bad)

    if good_issues:
        raise NotImplementedError(
            f"练习 3 · TODO ① 规则太严了：合规的回复被拦下 {len(good_issues)} 项 —— 误伤比漏放更糟")
    if len(bad_issues) < 3:
        raise NotImplementedError(
            f"练习 3 · TODO ① 规则太松了：坏的回复只拦下 {len(bad_issues)} 项（期望至少 3 项）")

    print("  ── 两个验收器的对照 ──")
    kv("课程自带 verify_reply(good)", f"{len(verify_reply(good))} 项问题")
    kv("课程自带 verify_reply(bad)", f"{len(verify_reply(bad))} 项问题")
    kv("你写的 compliance_check(good)", f"{len(good_issues)} 项")
    kv("你写的 compliance_check(bad)", f"{len(bad_issues)} 项")
    print()
    note("注意主管的仲裁顺序：**先合规，再交付**。合规不过 → 转人工，而不是让模型再改一版。")
    note("参考第 09 章的 node_compliance：6 行确定性代码就能替代一个「模型自审」节点。")
    bullet("合规要求「每次判断都一样」，模型给不了这个保证 —— 所以这一步属于代码，不属于模型。")
    bullet("别忘了在 arbitrate() 里加上「合规不通过 → 转人工」的分支：光检查不拦截等于没检查。")
    bullet("能写进 if/else 的规则，就别写进提示词。")

    conclusion = my_conclusion().strip()
    if len(conclusion) < 8:
        raise NotImplementedError("练习 3 · TODO ② 结论太短了，把「为什么不需要模型」写清楚")
    print()
    kv("你的结论", conclusion)
    return f"合规节点：好回复放行、坏回复拦下 {len(bad_issues)} 项并转人工"


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
