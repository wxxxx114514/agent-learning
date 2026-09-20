r"""第 07 章 · 练习 2 / 5 · 让验证器更严：结论里提到的商品必须出现在分项里

【要做什么】
  **让验证器更严。**
  给验证器加一条检查：**结论段里提到的商品必须出现在分项里**
  （防止模型在结论里编一个「补货 D 商品」）。
  然后构造一个「合计对、但结论编了商品」的草稿做反向验证。

【已经给你了】
  · TASK_Q1：事实源（A/B/C 三个商品，正确合计 811 元）
  · ReportVerifier：课程自带的三条规则（逐项重算 / 合计 / 格式契约）
  · GOOD_DRAFT：一份「完全正确」的草稿（由事实源拼出来，一定通过）
  · RE_SKU：抓商品名的正则，`RE_SKU.findall("建议优先补货 A 商品")` → ['A 商品']
  · StrictVerifier.check()：把父类三条 + 你的第 ④ 条拼在一起，不用改

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch07_reflection\ex2_stricter_verifier.py
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
from core.console import bullet, kv, note, warn                        # noqa: E402
from stages.stage07_reflection.demo import (                           # noqa: E402
    TASK_Q1, ReportTask, ReportVerifier, Verdict,
)

RE_SKU = re.compile(r"([A-Za-z]{1,3}\s*商品)")     # 抓「A 商品」「D 商品」这种商品名

# 一份完全正确的草稿：分项、合计、结论都从事实源拼出来，所以它必须通过验证。
GOOD_DRAFT = (
    f"{TASK_Q1.title}\n分项：\n"
    + "\n".join(f"- {r.sku}：{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" for r in TASK_Q1.records)
    + f"\n合计：{TASK_Q1.correct_total()} 元\n"
    + "结论：本季度销售整体稳健，建议优先补货 A 商品。"
)


class StrictVerifier(ReportVerifier):
    """课程自带的三条规则 + 你要写的第 ④ 条。"""

    def extra_issues(self, text: str, task: ReportTask) -> list[str]:
        """TODO ① ── 返回新规则发现的问题（没问题就返回 []）。

        照着提示里的做法：**用正则从结论段里抽出商品名，与 records 里的 sku 做差集**。
          1. 取出结论段那一行：
             line = next((ln for ln in text.splitlines() if ln.startswith("结论：")), "")
          2. 抽出商品名：RE_SKU.findall(line)
          3. 已知商品：known = {r.sku for r in task.records}
             ★ 两边都 .replace(" ", "") 再比 —— 「A商品」和「A 商品」是同一个人
          4. 差集非空 → 返回 ["结论里提到了分项里没有的商品：D 商品"]；空 → 返回 []
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案（4~5 行）↓↓↓
        raise NotImplementedError("练习 2 · TODO ①  extra_issues")
        # ↑↑↑ 你的答案 ↑↑↑

    def check(self, text: str, task: ReportTask) -> Verdict:
        """父类三条 + 你的第 ④ 条（不用改）。"""
        verdict = super().check(text, task)
        extra = self.extra_issues(text, task)
        verdict.checked.append("结论段里提到的商品必须出现在分项里")
        if not extra:
            return verdict
        return Verdict(ok=False, issues=list(verdict.issues) + extra, checked=verdict.checked)


# TODO ② ── 构造一个「合计仍然对、但结论里编了一个商品」的坏草稿（一行就够）。
#   提示：BAD_DRAFT = GOOD_DRAFT.replace("补货 A 商品", "补货 A 商品与 D 商品")
#   ↓↓↓ 在下面写你的坏草稿 ↓↓↓
BAD_DRAFT = ""
#   ↑↑↑ 你的坏草稿 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def show(title: str, draft: str) -> Verdict:
    verdict = StrictVerifier().check(draft, TASK_Q1)
    print(f"  ── {title}：{'通过 ✅' if verdict.ok else '不通过 ❌'}")
    for line in draft.splitlines():
        if line.startswith("结论："):
            print(f"     结论段：{line}")
    for issue in verdict.issues:
        print(f"     · {issue}")
    print(f"     做过的检查：{verdict.checked}")
    print()
    return verdict


def check() -> str:
    print("\n" + "=" * 66)
    print("  新规则的两面：正例必须放过，坏例必须拦住")
    print("=" * 66)

    good = show("① 正向验证（完全正确的草稿）", GOOD_DRAFT)

    if not BAD_DRAFT.strip():
        raise NotImplementedError("练习 2 · TODO ② 坏草稿还是空的（用 GOOD_DRAFT.replace 造一个）")
    bad = show("② 反向验证（合计对、结论编了商品）", BAD_DRAFT)

    line = next((ln for ln in BAD_DRAFT.splitlines() if ln.startswith("结论：")), "")
    known = {r.sku.replace(" ", "") for r in TASK_Q1.records}
    invented = sorted({n.replace(" ", "") for n in RE_SKU.findall(line)} - known)
    if not invented:
        raise NotImplementedError(
            "练习 2 · TODO ② 坏草稿的结论段里没有「分项里不存在的商品」—— 这样验不出新规则")
    if bad.ok:
        raise NotImplementedError(
            "练习 2 · TODO ① 新规则没生效：坏草稿（结论编了 " + "、".join(invented) + "）居然被放过了")
    if not any(any(name in issue for name in invented) for issue in bad.issues):
        raise NotImplementedError(
            "练习 2 · TODO ① 拦住了，但问题描述里没点名那个编造的商品 —— 模型照着改不动")

    if not good.ok:
        warn("正例被误伤了！新规则不能把「只提 A 商品」这种正确草稿也拦下来。")
    kv("正向", "通过" if good.ok else "被误伤")
    kv("反向", f"拦住 {len(bad.issues)} 项，点名了 {'、'.join(invented)}")
    print()
    note("★ 关键是最后那半句：**新加的检查必须有一个「该拦住的坏例子」来验证**，")
    note("  否则你不知道它到底有没有生效 —— 这也是所有验证器/护栏的通用验收方式。")
    bullet("能靠代码判定对错的东西（算术、格式、schema、白名单），一律交给代码。")
    bullet("规则要「宽进严出」：宁可只拦明确错的，也不要误伤正确的输出。")
    return f"新规则：正例通过 = {good.ok}；坏例拦住 = {not bad.ok}（{'、'.join(invented)}）"


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
