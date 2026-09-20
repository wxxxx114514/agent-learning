r"""第 04 章 · 练习 1 / 5 · 给 Step 加 `optional` 字段：可选步骤失败不触发重规划

【要做什么】
  给 `Step` 加一个 `optional: bool` 字段。
  可选步骤失败时**不触发重规划**，只记一条警告继续跑。

  改完之后，用一个「第 2 步是可选的、且必然失败」的计划验证：任务仍然能走到 completed。

【已经给你了】
  · OptionalStep(Step)     `Step` 的子类，字段声明那一行留给你写
                           （`Step` 来自 stages/stage04_planning/planner.py）
  · World / TOOLS          会变的订单系统，build_tools() 给出 6 个真实工具
  · _attempt(step, plan, tools)
                           执行一步并记账：成功返回 None，失败返回原因（**不抛异常**）
  · run_plan(...)          确定性执行器的骨架：静态校验、依赖检查、执行记账、
                           重规划预算都写好了，只有「失败之后怎么办」那一段留给你
  · Planner / ScriptedLLM  重规划器（这里配的是一个只会说空计划的假模型）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch04_planning\ex1_optional_step.py
  3. 验收本章：py scripts\run_all_checks.py 04
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                        # noqa: E402
from dataclasses import dataclass  # noqa: E402

from core.mock_llm import ScriptedLLM           # noqa: E402
from stages.stage04_planning.planner import (   # noqa: E402
    Plan, Planner, RefError, Step, World, resolve_args, validate_plan,
)

TASK = "订单 A1001：算加急运费，拟一条发货通知发给客户。"
WORLD = World()                       # 订单 A1001 状态 = 已发货（正常状态）
TOOLS = WORLD.build_tools()

# 重规划器：本练习的剧本不会真的用到它，只需要它「存在」
PLANNER = Planner(
    llm=ScriptedLLM([json.dumps({"steps": []})]),
    tools=TOOLS, max_replans=2, verbose=False,
)

# 一个必然失败的工具调用：订单还是「已发货」，所以查退款一定报错
ALWAYS_FAILS = {"tool": "query_refund", "args": {"order_id": "A1001"}}


def _attempt(step: Step, plan: Plan, tools) -> str | None:
    """执行一步。成功返回 None 并把结果写进 step；失败返回原因字符串。

    ★ 注意它**永远不抛异常** —— 失败是信息，不是崩溃（本章的核心纪律）。
    """
    try:
        args = resolve_args(step.args, plan)
    except RefError as exc:
        step.status, step.error = "failed", str(exc)
        return str(exc)

    r = tools.execute(step.tool, args)
    if r.ok:
        step.status, step.observation = "done", r.content
        step.result = json.loads(r.content) if r.content.startswith("{") else r.content
        return None
    step.status, step.error = "failed", (r.error or r.content)
    return step.error


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
@dataclass
class OptionalStep(Step):
    """Step 的子类：多一个 `optional` 字段。

    TODO ① ── 在下面加**一行**字段声明：optional: bool = False

    提示：@dataclass 会把「带类型注解的类属性」变成字段；
          这一行必须给默认值（父类字段都有默认值，子类字段也得有）。
    """
    # ↓↓↓ 在下面写上你的答案 ↓↓↓

    # ↑↑↑ 你的答案 ↑↑↑


def run_plan(plan: Plan, max_replans: int = 2, verbose: bool = True) -> dict:
    """确定性执行器：逐步跑计划，失败就带原因去找重规划器。

    前后都写好了（静态校验、执行记账、重规划预算），
    你只写中间「失败之后怎么办」那一段。

    返回：{"stop_reason": ..., "warnings": [...], "replans": 0, "done": n}
    """
    result: dict = {"stop_reason": "completed", "warnings": [], "replans": 0, "done": 0}

    problems = validate_plan(plan, TOOLS)
    if problems:
        result["stop_reason"] = "plan_invalid"
        result["warnings"] = problems
        return result

    for _ in range(max_replans + 1):
        failed_step, failed_reason = None, ""

        for step in plan.steps:
            if step.status == "done":
                if verbose:
                    print(f"   [跳过] 第 {step.id} 步（已完成，复用结果）")
                continue

            reason = _attempt(step, plan, TOOLS)
            if reason is None:
                result["done"] += 1
                if verbose:
                    print(f"   [完成] 第 {step.id} 步：{step.goal}")
                continue

            # TODO ② ── 失败之后怎么办？两种情况分开处理：
            #   · 可选步骤（step.optional 为真）：
            #       result["warnings"].append(f"第 {step.id} 步失败（可选，跳过）：{reason}")
            #       然后 continue —— 继续跑下一步
            #   · 必做步骤：
            #       failed_step, failed_reason = step, reason
            #       然后 break —— 跳出去走下面的重规划分支（第 ⑤ 节的闭环）
            # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
            raise NotImplementedError("练习 1 · TODO ②  run_plan 里的失败分支")
            # ↑↑↑ 你的答案 ↑↑↑

        if failed_step is None:
            result["stop_reason"] = "completed"
            return result

        if result["replans"] >= max_replans:
            result["stop_reason"] = "replan_exhausted"
            if verbose:
                print(f"   [停机] 重规划次数已达上限 {max_replans}")
            return result

        result["replans"] += 1
        if verbose:
            print(f"   [重规划] 第 {result['replans']} 次：{failed_reason[:48]}")
        plan = PLANNER.replan(TASK, plan, failed_step, failed_reason)

    return result


# TODO ③ ── 纯思考题：写下你的结论（一两句话就行）
#   提示：读操作（查订单、查物流）基本都可以标可选；写操作（发短信、扣款）几乎都不行 ——
#         因为「写失败」往往意味着**状态不确定**，那正是最不能忽略的情况。
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def make_plan(optional: bool) -> Plan:
    """造一份 3 步计划：第 2 步「查退款」必然失败，看它的失败会不会拖垮整个任务。"""
    return Plan(version=1, reason=f"optional={optional}", steps=[
        OptionalStep(1, "查询订单 A1001 的真实状态", "lookup_order", {"order_id": "A1001"}),
        OptionalStep(2, "顺手查一下退款进度（订单没取消，这一步必然失败）",
                     **ALWAYS_FAILS, optional=optional),
        OptionalStep(3, "拟发货通知", "draft_reply",
                     {"order_id": "A1001", "kind": "shipped", "detail": "加急"}),
    ])


def main() -> int:
    report: list[str] = []
    try:
        if "optional" not in getattr(OptionalStep, "__dataclass_fields__", {}):
            raise NotImplementedError("练习 1 · TODO ①  OptionalStep 还没有 optional 字段 "
                                      f"（现在只有 {list(getattr(OptionalStep, '__dataclass_fields__', {}))}）")

        print("=" * 66)
        print("  【可选步骤】第 2 步失败，但它是可选的")
        print("=" * 66)
        optional_run = run_plan(make_plan(optional=True))

        print()
        print("=" * 66)
        print("  【必做步骤】同一个计划，只把第 2 步的 optional 去掉")
        print("=" * 66)
        required_run = run_plan(make_plan(optional=False), max_replans=0)

        if optional_run["stop_reason"] != "completed":
            raise AssertionError(
                f"可选步骤失败不该拖垮任务，实际停机原因 = {optional_run['stop_reason']}")
        if len(optional_run["warnings"]) != 1:
            raise AssertionError(
                f"可选步骤失败应该记**一条**警告，实际 {optional_run['warnings']}")
        if optional_run["done"] != 2:
            raise AssertionError(f"应该有 2 步成功完成，实际 {optional_run['done']}")
        if optional_run["replans"] != 0:
            raise AssertionError(f"可选步骤失败不该触发重规划，实际重规划 {optional_run['replans']} 次")
        if required_run["stop_reason"] != "replan_exhausted":
            raise AssertionError(
                f"必做步骤失败应该去走重规划/停机分支，实际 = {required_run['stop_reason']}")

        report.append("")
        report.append("=" * 66)
        for label, run in (("optional（第 2 步是可选的）", optional_run),
                           ("必做（第 2 步是必做的）", required_run)):
            report.append(f"    {label}")
            report.append(f"        停机原因 = {run['stop_reason']:<16}"
                          f" 成功 {run['done']} 步"
                          f" | 警告 {len(run['warnings'])} 条"
                          f" | 重规划 {run['replans']} 次")
        report.append("")
        report.append(f"    可选那次的警告：{optional_run['warnings']}")
        report.append("")
        report.append("★ 同一个失败，两种后果：")
        report.append("  · 必做步骤失败 -> 任务停下来找重规划器（宁可停，也不能带着错假设往前跑）")
        report.append("  · 可选步骤失败 -> 记一条警告继续走完（不能因为一个锦上添花的步骤报废整个任务）")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 1 · TODO ③  写下你的结论：哪些步骤适合标成可选？")
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
