r"""第 10 章 · 练习 1 / 5 · 给评估集加一条「你的业务」用例

【要做什么】
  在第 ③ 节的数据集里加一条 `n7_xxx` 正常用例，要求它既有 `expect_contains`，
  又有 `required_tools`，并写清 `goal`。

  然后跑第 ⑤ 节，确认它出现在报告里。

【已经给你了】
  add_case(...)        往数据集里加一条用例（同时给它配好假模型剧本）——★ 就是你要写的东西
  EVAL_DATASET         课程自带的 14 条用例（会被你追加）
  SCRIPTS / CASE_BY_ID 假模型剧本表 / 用例索引（都会被 add_case 更新）
  run_suite(CONFIGS[CONFIG_V3])   跑一整套，返回 SuiteResult（可以看 passed / failures()）
  TOOL_FACTS           四个可用工具的"标准答案"，帮你把 expected 写对

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch10_evaluation\ex1_business_case.py
  3. 验收本章：py scripts\run_all_checks.py 10
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn  # noqa: E402
from stages.stage10_evaluation.demo import (  # noqa: E402
    CASE_BY_ID, CASE_BY_NORM_Q, CONFIG_V3, CONFIGS, EVAL_DATASET, NORMAL, SCRIPTS,
    EvalCase, Script, _norm, build_eval_registry, run_case, run_suite,
)

# 四个可用工具的"标准答案"——照着它写 expect_contains，才不会写出一条永远失败的用例
TOOL_FACTS = {
    "calc": "计算 (12+8)*3/4 → 答案是 15；(6*7) → 42",
    "lookup_order": "A1001 → 已发货 / 顺丰 / SF1234567890；A1002 → 待付款",
    "count_words": "count_words 返回 dict：总字符数 / 中文字数 / 英文单词数 / 行数",
    "search_kb": "返回一段退款政策文本（7 天无理由 + 3 个工作日到账）",
}
N7_ID = "n7_my_business"        # ← 你的新用例 id 必须是 n7_ 开头


def add_case(case_id: str, question: str, goal: str, *, expect_contains=(), expect_any=(),
             required_tools=(), forbidden_text=(), steps=(), final_ok: str = "",
             naive: str = "") -> EvalCase:
    """TODO ── 把一条用例同时注册到数据集和假模型剧本表里。

    这是评估框架最容易被忽略的一步：**用例和剧本必须成对出现**。
    只加用例不加剧本 → 假模型不知道该怎么答 → 报告里出现一条"永远失败"的用例，
    而失败的原因只是你没给它写剧本（这叫**评估框架自身的 bug**）。

    要做四件事：
      ① 造用例：
             case = EvalCase(id=case_id, category=NORMAL, question=question, goal=goal,
                             expect_contains=tuple(expect_contains),
                             expect_any=tuple(expect_any),
                             required_tools=tuple(required_tools),
                             forbidden_text=tuple(forbidden_text))
      ② 追加进数据集：      EVAL_DATASET.append(case)
      ③ 登记进索引：        CASE_BY_ID[case_id] = case
                            CASE_BY_NORM_Q[_norm(question)] = case     ← ★ 假模型靠它认出问题
      ④ 配剧本：            SCRIPTS[case_id] = Script(steps=tuple(steps), final_ok=final_ok,
                                                      naive=naive or final_ok)
         （steps 的格式：(("工具名", {"参数": 值}), …)）

    返回 case。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO  add_case：注册用例 + 剧本")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def build_my_case() -> EvalCase:
    """★ 这里是你选题目、选工具、写期望的地方（改这个函数，不用改别处）。

    要求（题目原文）：
      · id 形如 n7_xxx
      · 既有 expect_contains（答案里必须出现的关键词）
      · 又有 required_tools（这条用例必须真的调用哪个工具 —— 这是轨迹约束）
      · 写清 goal（"我在考什么"，写不出来的用例就是凑数的用例）
      · 仿照课程的写法：必须真的是被假模型答对的，否则报告里会多一条永远失败的用例

    下面这个例子可以直接用，也可以改成你自己业务的题目（推荐改一个）：
        计算 (12+8)*3/4
        · expect_contains=("15",)        ← calc 真的算得出 15
        · required_tools=("calc",)       ← 不许心算，必须调工具
        · steps=(("calc", {"expr": "(12+8)*3/4"}),)
        · final_ok="计算结果：(12+8)*3/4 = 15。"
    """
    return add_case(
        N7_ID,
        question="计算 (12+8)*3/4",
        goal="多步算术必须调用 calc，且不能心算错",
        expect_contains=("15",),
        required_tools=("calc",),
        steps=(("calc", {"expr": "(12+8)*3/4"}),),
        final_ok="计算结果：(12+8)*3/4 = 15。",
        naive="关于这道题，我的直接回答是：结果大约是 15。",
    )


def check_1() -> None:
    before = len(EVAL_DATASET)
    case = build_my_case()
    added = len(EVAL_DATASET) - before

    if added != 1:
        raise AssertionError(f"数据集应该正好多出 1 条用例，现在多了 {added} 条")
    if case.category != NORMAL:
        raise AssertionError(f"练习要求的是**正常**用例（category={NORMAL}），现在 {case.category}")
    if not case.id.startswith("n7_"):
        raise AssertionError(f"用例 id 要以 n7_ 开头，现在是 {case.id!r}")
    if not case.goal.strip():
        raise AssertionError("没有写 goal —— 写不出 goal 的用例就是凑数的用例")
    if not case.expect_contains:
        raise AssertionError("缺少 expect_contains：结果评分是「答案里必须出现什么」")
    if not case.required_tools:
        raise AssertionError("缺少 required_tools：轨迹评分是「它有没有真的去查」")

    # 声明的工具必须是真实存在的工具
    available = set(build_eval_registry().names())
    unknown = [t for t in case.required_tools if t not in available]
    if unknown:
        raise AssertionError(
            f"required_tools 里有不存在的工具 {unknown}；可用工具：{sorted(available)}")
    if case.id not in SCRIPTS:
        raise AssertionError("没有给新用例配剧本 —— 假模型不知道该怎么答它")

    # 剧本必须真的去调它声明要调的工具，否则这条用例不可能通过
    script_tools = [s[0] for s in SCRIPTS[case.id].steps]
    missing = [t for t in case.required_tools if t not in script_tools]
    if missing:
        raise AssertionError(
            f"剧本里没有调用 {missing}，但用例要求必须调它 —— 这条用例会永远失败；"
            f"剧本调的是 {script_tools or '（什么都没调）'}")

    kv("新用例", f"{case.id}（{case.category}）")
    kv("  题目", case.question[:56])
    kv("  我在考什么", case.goal[:56])
    kv("  结果期望", f"expect_contains={case.expect_contains}")
    kv("  轨迹期望", f"required_tools={case.required_tools}")
    kv("  剧本", f"先调 {script_tools}，再作答")
    print()

    # 真的跑一遍：它必须出现在报告里，而且是通过的
    result = run_case(case, CONFIGS[CONFIG_V3])
    suite = run_suite(CONFIGS[CONFIG_V3])
    ids = [r.case.id for r in suite.results]
    if case.id not in ids:
        raise AssertionError("新用例没有出现在这次的报告里")
    if not result.passed:
        raise AssertionError(
            f"新用例没通过：{[s for s in result.scores if not s[1]]}；"
            f"答案={result.answer[:50]!r}")
    if list(result.called_tools) != list(case.required_tools):
        raise AssertionError(
            f"轨迹不符：用例要求 {case.required_tools}，实际调用 {result.called_tools}")

    kv("跑第 ⑤ 节", f"共 {suite.total} 条用例（原来 14 条 + 你加的 1 条）")
    kv("  新用例结果", f"✅ 通过　工具轨迹={result.called_tools}")
    kv("  它启用的评分器", ", ".join(n for n, _, _ in result.scores))
    print()
    note("★ 用例 + 剧本必须成对出现：改数据集而忘了改剧本，报告里就会出现一条")
    note("  「永远失败」的用例，而失败的原因只是评估框架自己的 bug。")
    warn("★ 评估框架必须先用假模型自测通过 —— 否则你分不清是框架有 bug 还是模型发挥不好。")
    bullet("新用例要同时有结果期望（expect_contains）和轨迹期望（required_tools）")


def main() -> int:
    try:
        check_1()
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
