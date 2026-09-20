r"""第 10 章 · 练习 4 / 5 · 把评分器换成「必须引用来源」

【要做什么】
  给 `n2_order` 加一条格式约束：答案里必须出现运单号 `SF\d{10}`。

  提示：用 `expect_regex`。然后故意让它不写运单号，观察它变红。

【已经给你了】
  with_source_required()   给 n2_order 加上运单号正则 —— ★ 就是你要写的那个函数
  grade(case)              拿一个用例去跑 v3 配置并评分，返回 CaseResult（可以看 passed / scores）
  run_n2()                 跑当前生效的 n2_order
  CASE_BY_ID / CONFIGS / CONFIG_V3 / EvalCase   课程里的这些对象
  SANE_SENTENCE            模型原本的答案（里面**确实**写着运单号 SF1234567890）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch10_evaluation\ex4_regex_scorer.py
  3. 验收本章：py scripts\run_all_checks.py 10
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from dataclasses import replace  # noqa: E402

from core.console import bullet, code, kv, note, warn  # noqa: E402
from stages.stage10_evaluation.demo import (  # noqa: E402
    CASE_BY_ID, CONFIG_V3, CONFIGS, SCRIPTS, CaseResult, EvalCase, run_case,
)

N2_ID = "n2_order"
TRACKING_PATTERN = r"SF\d{10}"           # 运单号的格式：SF + 10 位数字
SANE_SENTENCE = "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。"
NO_TRACKING = "订单 A1001 已发货，承运商是顺丰。"      # ← 关键词都在，就是**不写运单号**


def grade(case: EvalCase) -> CaseResult:
    """跑一条用例并评分（不修改任何全局状态）。"""
    return run_case(case, CONFIGS[CONFIG_V3])


def run_n2() -> CaseResult:
    """跑当前生效的 n2_order。"""
    return grade(CASE_BY_ID[N2_ID])


def scores_of(result: CaseResult) -> str:
    return "　".join(f"{'✅' if p else '❌'}{n}" for n, p, _ in result.scores)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def with_source_required(regex: str = TRACKING_PATTERN) -> str:
    r"""TODO ── 给 n2_order 加一条**格式**约束：答案里必须出现运单号。

    两步：
      ① 造新用例：case = replace(CASE_BY_ID[N2_ID], expect_regex=regex)
         （EvalCase 是 frozen dataclass，用 dataclasses.replace 造一份新的）
      ② 覆盖回去：CASE_BY_ID[N2_ID] = case
      ③ 返回一句话：为什么这里必须用 `re.search` 而不是 `re.match`？

    提示（卡住了再看）：
        ★ 答案是一整句话「订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。」，
          运单号**不在开头**：
              re.match(pattern, text) 只从开头匹配 → 永远失败（好用例也被判 0 分）
              re.search(pattern, text) 全文找      → 找得到  → 通过
          课程的 score_regex 用的正是 re.search（见 stages/stage10_evaluation/demo.py）。
        ★ `\d` 在正则里表示「一个数字」。写成字符串时要小心转义：
          r"SF\d{10}" 是 10 个数字（raw string），"SF\\d{10}" 也对；
          但 "SF\d{10}" 里的 \d 只是个普通字符 d，永远匹配不上。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO  with_source_required")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def grade_sentence(sentence: str) -> CaseResult:
    """拿一句**假的**答案去评分：把剧本换成这句话，就能看评分器怎么判它。

    （这是评估框架自己的单元测试思路：评分器必须能判正、也**必须能判负** ——
      一个永远返回 True 的评分器比没有评分器更危险。）
    """
    case = CASE_BY_ID[N2_ID]
    original = SCRIPTS[N2_ID]
    try:
        SCRIPTS[N2_ID] = replace(original, final_ok=sentence)
        return grade(case)
    finally:
        SCRIPTS[N2_ID] = original


def check_4() -> None:
    before = run_n2()
    if before.case.expect_regex:
        raise AssertionError("动手之前 n2_order 不该有 expect_regex，先检查环境")
    if not before.passed:
        raise AssertionError("动手之前 n2_order 应该是通过的（它是正常用例）")

    conclusion = with_source_required()
    if len(str(conclusion).strip()) < 10:
        raise AssertionError("第 ③ 步还没写：说明为什么必须用 re.search 而不是 re.match")

    case = CASE_BY_ID[N2_ID]
    if case.expect_regex != TRACKING_PATTERN:
        raise AssertionError(
            f"n2_order 的 expect_regex 应该正好是 {TRACKING_PATTERN!r}，现在是 {case.expect_regex!r}")

    # ① 好答案必须仍然通过（加了约束不能误伤正确输出）
    good = run_n2()
    if not good.passed:
        raise AssertionError(
            f"模型本来就写了运单号，这条用例不该变红："
            f"{[s for s in good.scores if not s[1]]}　答案={good.answer[:46]!r}")
    regex_score = next(s for s in good.scores if s[0] == "regex")
    if not regex_score[1]:
        raise AssertionError(f"regex 评分器没通过：{regex_score[2]}")

    # ② 故意不写运单号 → 必须变红，而且**只有** regex 这一项变红
    bad = grade_sentence(NO_TRACKING)
    if bad.passed:
        raise AssertionError("不写运单号的答案居然通过了 —— 格式约束没生效")
    failed = bad.failed_scorers
    if failed != ["regex"]:
        raise AssertionError(
            f"这里应当只有 regex 评分器判负（其余仍然通过），实际失败的是 {failed}")

    kv("你的正则", repr(case.expect_regex))
    kv("模型原答案", good.answer[:48])
    kv("  评分", scores_of(good))
    print()
    kv("去掉运单号后", NO_TRACKING[:48])
    kv("  评分", scores_of(bad))
    kv("  判负的评分器", f"{failed}（其余评分器仍然通过 —— 说明约束是**独立**的）")
    print()
    code(r're.search(r"SF\d{10}", "订单 A1001 已发货……运单号 SF1234567890。")  → 匹配 ✅' + "\n"
         r're.match (r"SF\d{10}", 上面那句话)                                → None ❌（从头对不上）',
         indent=4)
    print()
    kv("你的结论", str(conclusion).strip()[:56])
    print()
    note("★ 评分器要能判正、也**必须能判负**：一个永远返回 True 的评分器比没有评分器更危险。")
    warn("★ 自由文本别用精确匹配，要用「包含关键词」和「正则格式」；")
    warn("  而一旦你用正则约束了格式，就必须确认它不会把正确的长答案误判成失败。")
    bullet("格式约束（expect_regex）适合：JSON、单号、日期、编号 —— 结构化的东西")
    bullet("措辞类的东西不要用正则卡：换个说法就误伤，那是「宁可错杀」")


def main() -> int:
    try:
        check_4()
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
