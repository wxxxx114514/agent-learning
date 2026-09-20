r"""第 04 章 · 练习 2 / 5 · 拆掉护栏：把「依赖方向」校验去掉会怎样

【要做什么】
  把 `validate_plan` 里最后那条 `elif d > s.id:` 分支删掉（就是「依赖只能指向更小的编号」），
  再用第 ③ 节的「循环依赖」坏计划跑一次。

  观察：静态校验还拦得住吗？拦不住的话，执行时会发生什么？

【已经给你了】
  · REG / WORLD              真实工具注册表（World.build_tools()）
  · CYCLIC_JSON              一份循环依赖的坏计划（第 1 步等第 2 步，第 2 步等第 1 步）
  · validate_plan(plan, tools)  课程自带的静态校验（护栏完好，来自 planner.py）
  · Executor / Planner       真实执行器与规划器；`Executor._execute(plan)` 可以**跳过静态校验**
                             直接执行（本练习正是要用它来模拟「护栏被拆掉之后」）
  · STUCK_JSON               一份「静态校验能过、但执行期必然卡住」的计划，
                             配合一个只会重复同一份计划的假规划器，用来看预算兜底

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch04_planning\ex2_drop_dep_guard.py
  3. 验收本章：py scripts\run_all_checks.py 04
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                                  # noqa: E402

from core.mock_llm import ScriptedLLM        # noqa: E402
from stages.stage04_planning.planner import (  # noqa: E402
    Executor, Plan, Planner, Step, World, validate_plan,
)

TASK = "订单 A1001：算加急运费，拟一条发货通知发给客户。"
WORLD = World()
REG = WORLD.build_tools()

# ① 循环依赖的坏计划：第 1 步等第 2 步，第 2 步等第 1 步
CYCLIC_JSON = {"steps": [
    {"id": 1, "goal": "先做第二步", "tool": "lookup_order",
     "args": {"order_id": "A1001"}, "depends_on": [2]},
    {"id": 2, "goal": "再做第一步", "tool": "calc_freight",
     "args": {"order_id": "A1001", "weight_kg": 2.5, "speed": "加急"}, "depends_on": [1]},
]}

# ② 静态校验能过、执行期却必然卡住的计划：
#    第 1 步查退款（订单没取消 -> 一定失败），第 2 步依赖第 1 步 -> 一定被阻塞
STUCK_JSON = {"steps": [
    {"id": 1, "goal": "查退款进度", "tool": "query_refund",
     "args": {"order_id": "A1001"}, "depends_on": []},
    {"id": 2, "goal": "拟发货通知", "tool": "draft_reply",
     "args": {"order_id": "A1001", "kind": "shipped"}, "depends_on": [1]},
]}


def make_plan(payload: dict) -> Plan:
    """把一份 JSON 计划变成 Plan 对象（第 ② 节的结构化计划）。"""
    steps = [Step(id=s["id"], goal=s["goal"], tool=s["tool"],
                  args=dict(s.get("args", {})), depends_on=list(s.get("depends_on", [])))
             for s in payload["steps"]]
    return Plan(version=1, reason="练习用的计划", steps=steps)


def make_planner(payload: dict, max_replans: int = 2) -> Planner:
    """造一个「每次都给出同一份计划」的假规划器 —— 模型写不出新计划时就是这样。"""
    return Planner(llm=ScriptedLLM([json.dumps(payload, ensure_ascii=False)]),
                   tools=REG, max_replans=max_replans, verbose=False)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def validate_without_direction_check(plan: Plan, tools) -> list[str]:
    """模拟「把 `elif d > s.id:` 那条分支删掉」之后，静态校验还剩什么。

    做法：先跑真正的 validate_plan，再把它因为「依赖方向」报出来的问题过滤掉。

    前后都写好了（调用真校验 + 返回），你只写中间那一行过滤。

    TODO ① ── 一行列表推导：滤掉信息里含「依赖了后面的第」的那些问题。

    提示：`problems = validate_plan(plan, tools)` 已经给你了，
          你要写的是 `return [p for p in problems if ...]`
    """
    problems = validate_plan(plan, tools)
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 2 · TODO ①  过滤掉「依赖方向」那一类问题")
    # ↑↑↑ 你的答案 ↑↑↑


# TODO ② ── 纯思考题：写下你的结论（一两句话就行）
#   提示：静态校验被拆掉之后，谁成了最后一道防线？它是「第一道」还是「最后一道」？
#         再想：如果连预算都没有，这个任务会怎么结束？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        # ---- ① 护栏完好时：循环依赖被静态校验拦下，一步都不执行 ----
        real_problems = validate_plan(make_plan(CYCLIC_JSON), REG)
        if not real_problems:
            raise AssertionError("课程自带的校验应该能拦下循环依赖")

        guarded = Executor(tools=REG, planner=make_planner(CYCLIC_JSON),
                           verbose=False).run(TASK, plan=make_plan(CYCLIC_JSON))
        calls_before = WORLD.count()

        # ---- ② 护栏拆掉后：你的函数放行，然后直接进执行器 ----
        loose_problems = validate_without_direction_check(make_plan(CYCLIC_JSON), REG)
        if loose_problems:
            raise AssertionError(
                f"拆掉方向校验之后应该放行，实际还剩 {loose_problems}"
                "（检查 TODO ① 过滤的关键词对不对）")

        # `_execute` 会跳过静态校验 —— 正好用来模拟「校验被拆掉」的世界
        cyclic_plan = make_plan(CYCLIC_JSON)
        outcome = Executor(tools=REG, planner=make_planner(CYCLIC_JSON),
                           verbose=False)._execute(cyclic_plan)

        if outcome is None:
            raise AssertionError("循环依赖不该执行成功（两个步骤互相等，谁也跑不了）")
        blocked_step, blocked_reason = outcome
        if blocked_step.status != "blocked":
            raise AssertionError(f"应该被标成 blocked，实际 status={blocked_step.status!r}")

        # ---- ③ 就算过程序校验，执行期也会 blocked -> 只能靠预算兜底 ----
        stuck = Executor(tools=REG, planner=make_planner(STUCK_JSON, max_replans=2),
                         verbose=False).run(TASK, plan=make_plan(STUCK_JSON))
        if stuck.stop_reason != "replan_exhausted":
            raise AssertionError(
                f"模型反复给出同一份跑不通的计划时，应该靠预算停机，"
                f"实际 stop_reason={stuck.stop_reason!r}")

        report.append("① 护栏完好（课程自带的 validate_plan）：")
        for p in real_problems:
            report.append(f"      - {p}")
        report.append(f"    执行器停机原因 = {guarded.stop_reason}   （一步都没跑，副作用为零）")
        report.append("")
        report.append("② 护栏拆掉（你的 validate_without_direction_check）：")
        report.append(f"    静态校验返回 = {loose_problems}   <- 放行了！")
        report.append(f"    执行器实际结果 = 第 {blocked_step.id} 步被标为 "
                      f"{blocked_step.status}：{blocked_reason}")
        report.append("      ^ 两个步骤互相等，谁也跑不了 —— 只能整单交回重规划")
        report.append("")
        report.append("③ 那谁来兜底？看一份「静态校验能过、执行期必然卡住」的计划：")
        report.append(f"    停机原因 = {stuck.stop_reason}"
                      f"（重规划 {stuck.replans} 次后放弃）")
        report.append(f"    工具调用 {stuck.tool_calls} 次 —— 每次都撞在同一堵墙上")
        report.append(f"    真实发生的调用：{WORLD.calls[calls_before:]}")
        report.append("")
        report.append("★ 结论：没有静态校验时，你只能靠预算兜底。")
        report.append("  预算是**最后一道防线**，不是第一道 —— 它保证程序会停，")
        report.append("  但停下来的代价是：前面每一步的钱都白花了。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 2 · TODO ②  写下你的结论")
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
