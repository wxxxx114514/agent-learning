r"""第 12 章 · 练习 3 / 5 · 给路由加一条规则，并用评估集证明它是安全的

【要做什么】
  **给路由加一条规则，并用评估集验证它。**

  现在的 `SIMPLE_HINTS` 里没有「总结」。加一条把「总结一下这段文字」路由到小模型的规则，
  重跑第 ⑥ 节观察分布变化。

  然后回答：你**凭什么**说这条规则是安全的？

【已经给你了】
  · 第 12 章真正的路由零件：`ModelRouter` / `RouteDecision` / `COMPLEX_HINTS` / `SIMPLE_HINTS`
  · `EVAL_SET`：8 条评估用例 + 它们**现在**被判到哪一档（第 10 章说的「评估集」就是它）
  · `tiers(router, questions)`：一次把一组问题的路由结果取出来
  · `table()`：打印对比表

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch12_cost_latency\ex3_router_rule.py
  3. 验收本章：py scripts\run_all_checks.py 12
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage12_cost_latency.demo import (  # noqa: E402
    COMPLEX_HINTS, SIMPLE_HINTS, ModelRouter, RouteDecision, table,
)

# 评估集：第 10 章的做法 —— 改路由之前先固定一批用例，改完逐条对比。
# 右边是「改之前它走哪一档」，就是现在的行为（基线）。
EVAL_SET = [
    ("计算 (12+8)*3/4", "small"),
    ("统计「护栏」这两个字有几个字", "small"),
    ("订单 A1001 到哪了？", "small"),
    ("把这段文字翻译成英文", "small"),
    ("今天天气怎么样", "large"),                       # 判不出来 → 保守走大模型
    ("帮我分析一下订单 A1001 延迟的原因，并给出改进建议", "large"),
    ("对比一下两种退款方案的优劣，并给出你的建议", "large"),
    ("请解释一下这段代码为什么会死循环，并给出修复方案，同时说明可能的影响范围", "large"),
]

# 这次要新增的用例：左边两条是「新规则应该生效」的，右边两条是「不许被新规则抢走」的
NEW_CASES = [
    ("总结一下这段文字", "small"),
    ("帮我总结这段话的要点", "small"),
    ("总结并对比两种方案的优劣", "large"),      # 含「总结并」→ 复杂意图词必须优先
    ("总结一下这段物流延迟的分析报告，并给出改进建议和风险提示", "large"),   # 超长 → 也走大模型
]


def tiers(router: ModelRouter, questions: list[str]) -> list[str]:
    """一次取出一组问题的路由结果（已经写好，不用改）。"""
    return [router.route(q).tier for q in questions]


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
class SummarizeRouter(ModelRouter):
    """在原来的规则之上，多加一条：把「总结」当成简单意图，交给小模型。

    注意：原来的 `ModelRouter` 一条规则都不改，本类只**追加**一条。
    """

    EXTRA_SIMPLE = ("总结",)      # ← 这就是新加的那条规则

    def route(self, question: str) -> RouteDecision:
        """TODO ① ── 命中 EXTRA_SIMPLE 就走小模型，其余原样交给父类。

        要求（下面两个用例必须同时成立）：
          · "总结一下这段文字"                → small（新规则生效，省钱）
          · "总结并对比两种方案的优劣"        → large（复杂意图词优先，质量不许掉）
        提示：两条路 ——
          ① 命中 `self.EXTRA_SIMPLE` **且不命中** `COMPLEX_HINTS` → 自己返回 small；
             别忘了同步 +1 `self.stats["small"]`（父类就是这么统计的）；
          ② 其余一律 `return super().route(question)`（长度规则和「判不出来就保守走大模型」
             都在父类里，别自己重写一遍）。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 3 · TODO ①  SummarizeRouter.route")
        # ↑↑↑ 你的答案 ↑↑↑


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   你凭什么说这条新规则是安全的？（凭感觉不算证明）
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        base = ModelRouter()
        mine = SummarizeRouter()

        # ① 新用例：左边两条必须变便宜，右边两条必须一条都不许被抢走
        rows = []
        for q, expect in NEW_CASES:
            before = base.route(q).tier
            after = mine.route(q).tier
            rows.append([q[:26], expect, before, after,
                         "✅" if after == expect else "❌"])
        table(["新增用例", "期望", "改之前", "改之后", ""], rows)
        print()
        for q, expect in NEW_CASES:
            got = mine.route(q).tier
            assert got == expect, f"「{q}」应该路由到 {expect}，现在是 {got}"
        print("    ★ 新规则生效：两句话变成小模型（便宜 10 倍、快 3 倍）")
        print("    ★ 复杂意图词优先：含「总结并」的那条仍然走大模型 —— 它会被抢走的话")
        print("      用户就拿不到分析结论了，而这正是路由错误中最贵的那一类。")
        print()

        # ② 评估集回归：老用例一条都不许变（这才叫「证明」，凭感觉不算）
        base2, mine2 = ModelRouter(), SummarizeRouter()
        changed = []
        rows = []
        for q, expect in EVAL_SET:
            before = base2.route(q).tier
            after = mine2.route(q).tier
            if before != after:
                changed.append((q, before, after))
            rows.append([q[:34], expect, before, after, "✅" if before == after else "❌ 变了"])
        table(["评估用例", "基线期望", "改之前", "改之后", "回归"], rows)
        print()
        assert not changed, f"评估集里有 {len(changed)} 条被改坏了：{changed}"
        assert all(base2.route(q).tier == expect for q, expect in EVAL_SET), \
            "基线本身就和 EVAL_SET 对不上 —— 说明课程里的规则被改过了"
        print(f"    ★ {len(EVAL_SET)} 条评估用例全部与基线一致：这就是「这条规则是安全的」"
              f"的全部依据。")
        print()

        # ③ 分布变化 = 省钱的空间，两者必须一起看
        all_qs = [q for q, _ in NEW_CASES] + [q for q, _ in EVAL_SET]
        base_all, mine_all = ModelRouter(), SummarizeRouter()
        tiers(base_all, all_qs)
        tiers(mine_all, all_qs)
        moved = base_all.stats["large"] - mine_all.stats["large"]
        print(f"    ★ {len(all_qs)} 条用例上的路由分布："
              f"改之前 {base_all.stats} → 改之后 {mine_all.stats}")
        print(f"      有 {moved} 条从大模型挪到了小模型（便宜 10 倍、快 3 倍）——"
              f"这就是这条规则省下的钱。")
        print("      分布变化 = 省钱的空间；评估集不变 = 质量没掉。两者必须一起看。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print()
    print(f"    你的结论：{CONCLUSION or '（还没写 —— 写在文件里的 CONCLUSION 那一行）'}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
