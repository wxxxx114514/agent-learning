"""第 04 章 · 规划与任务分解 —— 计划是假设，执行是验证，偏差就要修计划。

运行：
    py -m stages.stage04_planning.demo
    py -m stages.stage04_planning.demo --list
    py -m stages.stage04_planning.demo --section 2
    py -m stages.stage04_planning.demo --check

本章要回答的问题：
    第 01~03 章的 Agent 是"走一步看一步"的（ReAct）。任务一复杂，它就露馅：
    做到第 5 步才发现方向错了，前面 4 步的钱和时间全白花。
    规划要解决的就是这件事 —— **把"想"和"做"分开，让错误尽早暴露**。

本章的核心不是"让模型写出一份漂亮的计划"，而是三件事：
    ① 计划必须是**结构化数据**（可校验、可执行、可 diff、可统计）；
    ② 执行必须**确定性**（同一份计划跑两次，行为一致，否则没法归因）；
    ③ 偏差必须触发**重规划**（而不是硬跑、也不是整条链崩掉）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 允许 `py stages/stage04_planning/demo.py` 这种直接运行方式
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check_that, code, essence, kv, note, ok, report,
    section, setup_console, warn,
)
from core.llm import LLM, LLMResponse  # noqa: E402
from core.tool import ToolRegistry  # noqa: E402

from stages.stage04_planning.planner import (  # noqa: E402
    Executor, Plan, Planner, Step, World, validate_plan,
)

# ===========================================================================
# 一、一个确定性的假"规划模型"
# ===========================================================================
# 为什么用假模型而不是真模型？
#   本章要讲的是**规划的结构**（步骤、依赖、重规划），不是"模型能不能写 JSON"。
#   假模型让每一次运行都完全一样，你才能对照着输出理解每一行代码的作用。
#   想换真模型？把 PlanBotLLM 换成 core.real_llm.from_env() 即可，其余代码不用改
#   —— 这正是 core/llm.py 那层抽象的价值。

TASK = "订单 A1001：算一下加急运费，拟一条发货通知发给客户。"

# --- 正常粒度的初始计划：4 步，每步只做一件事 ---------------------------
PLAN_NORMAL = {"steps": [
    {"id": 1, "goal": "查询订单 A1001 的真实状态与重量", "tool": "lookup_order",
     "args": {"order_id": "A1001"}, "depends_on": []},
    {"id": 2, "goal": "用订单里的重量算出加急运费", "tool": "calc_freight",
     "args": {"order_id": "$1.order_id", "weight_kg": "$1.weight_kg", "speed": "加急"},
     "depends_on": [1]},
    {"id": 3, "goal": "按订单真实状态生成发货通知文案", "tool": "draft_reply",
     "args": {"order_id": "$1.order_id", "kind": "shipped", "detail": "已为您加急，运费以账单为准"},
     "depends_on": [1, 2]},
    {"id": 4, "goal": "把通知真正发给客户", "tool": "send_reply",
     "args": {"order_id": "$1.order_id", "text": "$3.text"}, "depends_on": [3]},
]}

# --- 重规划结果（正常粒度）：复用第 1 步，把"算运费"换成"查退款" ----------
#     注意它做对了三件事：保留已验证的事实（第 1 步）、只改必须改的步骤、
#     在 goal 里写清了目标为什么变了。
PLAN_NORMAL_REPAIR = {"steps": [
    {"id": 1, "goal": "查询订单 A1001 的真实状态与重量", "tool": "lookup_order",
     "args": {"order_id": "A1001"}, "depends_on": []},
    {"id": 2, "goal": "订单已取消 → 改查退款进度", "tool": "query_refund",
     "args": {"order_id": "$1.order_id"}, "depends_on": [1]},
    {"id": 3, "goal": "改拟订单取消通知（附退款进度）", "tool": "draft_reply",
     "args": {"order_id": "$1.order_id", "kind": "cancelled",
              "detail": "退款进度：$2.status，预计 $2.eta_days 个工作日到账"},
     "depends_on": [1, 2]},
    {"id": 4, "goal": "把通知真正发给客户", "tool": "send_reply",
     "args": {"order_id": "$1.order_id", "text": "$3.text"}, "depends_on": [3]},
]}

# --- 粗粒度计划：把"查状态 + 算运费 + 拟稿"压成一步，运费数字是**猜的** ---
#     这就是"计划里藏假设"的典型：33.75 元这个数字在计划期根本没人验证过。
PLAN_COARSE = {"steps": [
    {"id": 1, "goal": "直接拟好发货通知（查状态/算运费/拟稿合成一步）", "tool": "draft_reply",
     "args": {"order_id": "A1001", "kind": "shipped", "detail": "加急运费 33.75 元"},
     "depends_on": []},
    {"id": 2, "goal": "发给客户", "tool": "send_reply",
     "args": {"order_id": "A1001", "text": "$1.text"}, "depends_on": [1]},
]}
PLAN_COARSE_REPAIR = {"steps": [
    {"id": 1, "goal": "按已取消状态重拟通知", "tool": "draft_reply",
     "args": {"order_id": "A1001", "kind": "cancelled", "detail": ""}, "depends_on": []},
    {"id": 2, "goal": "发给客户", "tool": "send_reply",
     "args": {"order_id": "A1001", "text": "$1.text"}, "depends_on": [1]},
]}

# --- 细粒度计划：每个字段单独读一次（8 步） ------------------------------
PLAN_FINE = {"steps": [
    {"id": 1, "goal": "查询订单全貌", "tool": "lookup_order",
     "args": {"order_id": "A1001"}, "depends_on": []},
    {"id": 2, "goal": "单独读取 status", "tool": "get_field",
     "args": {"order_id": "A1001", "field": "status"}, "depends_on": [1]},
    {"id": 3, "goal": "单独读取 weight_kg", "tool": "get_field",
     "args": {"order_id": "A1001", "field": "weight_kg"}, "depends_on": [1]},
    {"id": 4, "goal": "单独读取 carrier", "tool": "get_field",
     "args": {"order_id": "A1001", "field": "carrier"}, "depends_on": [1]},
    {"id": 5, "goal": "单独读取 tracking", "tool": "get_field",
     "args": {"order_id": "A1001", "field": "tracking"}, "depends_on": [1]},
    {"id": 6, "goal": "用重量算加急运费", "tool": "calc_freight",
     "args": {"order_id": "$1.order_id", "weight_kg": "$3.value", "speed": "加急"},
     "depends_on": [1, 3]},
    {"id": 7, "goal": "生成发货通知文案", "tool": "draft_reply",
     "args": {"order_id": "$1.order_id", "kind": "shipped",
              "detail": "承运商 $4.value，运单号 $5.value"},
     "depends_on": [1, 4, 5, 6]},
    {"id": 8, "goal": "发给客户", "tool": "send_reply",
     "args": {"order_id": "$1.order_id", "text": "$7.text"}, "depends_on": [7]},
]}


class PlanBotLLM(LLM):
    """按提示词里的关键词返回不同计划的假模型（确定性，绝不联网）。

    它模仿的是真模型在三种情形下的典型输出：
        ① 首次规划          → 给出正常粒度的计划
        ② 带着失败去重规划  → 只改必要的步骤（**这是最难的，也是最重要的**）
        ③ 粒度要求          → 粗粒度 / 细粒度
    """

    name = "plan-bot"

    def __init__(self, model: str = "mock-plan") -> None:
        super().__init__(model)
        self.seen: list[list] = []

    def _complete(self, messages, **kwargs):
        prompt = messages[-1].content
        self.seen.append(prompt)

        if "# 重规划" in prompt:
            # 从"当前计划"里读出第一步用的什么工具，据此决定怎么修。
            # （真模型是"读懂"了上下文；这里用正则是为了确定性。）
            tools = _tools_in_plan(prompt)
            plan = PLAN_COARSE_REPAIR if tools[:1] == ["draft_reply"] else PLAN_NORMAL_REPAIR
        elif "# 粒度要求" in prompt:
            hint = prompt.split("# 粒度要求", 1)[1]
            plan = PLAN_COARSE if "粗" in hint else PLAN_FINE
        else:
            plan = PLAN_NORMAL

        return LLMResponse(text=json.dumps(plan, ensure_ascii=False), model=self.model)


def _tools_in_plan(prompt: str) -> list[str]:
    """从渲染出来的计划文本里按顺序抠出工具名（`调用: xxx(...)`）。"""
    return re.findall(r"调用:\s*([A-Za-z_]\w*)\(", prompt)


class MissingArgPlanLLM(LLM):
    """规划器忘了给必填参数（模型经常"以为"工具能猜到）。"""

    name = "missing-arg"

    def _complete(self, messages, **kwargs):
        return LLMResponse(text=json.dumps({"steps": [
            {"id": 1, "goal": "算加急运费（忘了给重量）", "tool": "calc_freight",
             "args": {"order_id": "A1001", "speed": "加急"}, "depends_on": []},
        ]}, ensure_ascii=False), model=self.name)


class BrokenJsonLLM(LLM):
    """规划器输出了一段"人话"而不是 JSON —— 真实世界里很常见。"""

    name = "broken-json"

    def _complete(self, messages, **kwargs):
        return LLMResponse(text="好的，我的计划是：先查订单，再算运费，最后发给客户。", model=self.name)


class PhantomToolLLM(LLM):
    """规划器编了一个不存在的工具（模型的幻觉在规划阶段最常见）。"""

    name = "phantom-tool"

    def _complete(self, messages, **kwargs):
        return LLMResponse(text=json.dumps({"steps": [
            {"id": 1, "goal": "上网搜一下这家快递的口碑", "tool": "search_web",
             "args": {"q": "顺丰 加急"}, "depends_on": []},
            {"id": 2, "goal": "发给客户", "tool": "send_reply",
             "args": {"order_id": "A1001", "text": "已为您加急"}, "depends_on": [1]},
        ]}, ensure_ascii=False), model=self.name)


class CyclicPlanLLM(LLM):
    """规划器写出了循环依赖：第 1 步等第 2 步，第 2 步等第 1 步 —— 永远跑不起来。"""

    name = "cyclic-plan"

    def _complete(self, messages, **kwargs):
        return LLMResponse(text=json.dumps({"steps": [
            {"id": 1, "goal": "算运费", "tool": "calc_freight",
             "args": {"order_id": "A1001", "weight_kg": 2.5, "speed": "加急"}, "depends_on": [2]},
            {"id": 2, "goal": "查订单", "tool": "lookup_order",
             "args": {"order_id": "A1001"}, "depends_on": [1]},
        ]}, ensure_ascii=False), model=self.name)


# ===========================================================================
# 二、"一次想完"的朴素做法：本章的反面教材
# ===========================================================================
# 反面教材有两种死法，第二种比第一种危险得多：
#   ① 硬崩：某一步抛异常，整个任务中断（至少你知道出事了）；
#   ② **假成功**：不检查每步结果，照样往下跑，最后交出一份"任务完成"的报告，
#      而真实世界里什么都没发生（或者更糟：发生了错误的事）。
# 我们演示第 ② 种，因为它是线上事故的主要来源。

NAIVE_PLAN = [
    # 计划是"一次性"想出来的：三件事连在一起，而且运费数字是**当时猜的**
    ("draft_reply", {"order_id": "A1001", "kind": "shipped", "detail": "加急运费 33.75 元"}),
    ("send_reply", {"order_id": "A1001", "text": "您的订单 A1001 已发货，加急运费 33.75 元。"}),
]


def naive_one_shot(world: World) -> tuple[str, list[str]]:
    """一次想完 + 盲执行：不校验、不重规划、不看结果。"""
    tools = world.build_tools()
    errors: list[str] = []
    for tool, args in NAIVE_PLAN:
        result = tools.execute(tool, args)
        if not result.ok:                      # ★ 朴素做法最常见的 bug：这一行被漏掉了
            errors.append(f"{tool}: {result.error}")
    # ★ 更真实的写法：报告是照着**计划**写的，而不是照着**执行结果**写的。
    #   于是报告和现实脱节 —— 这就是线上"任务显示成功、用户什么也没收到"的成因。
    report_text = "任务已完成：已计算加急运费 33.75 元，并已通知客户订单 A1001 已发货。"
    if errors:
        report_text += f"（执行日志里有 {len(errors)} 条 WARN，已忽略）"
    return report_text, errors


# ===========================================================================
# 三、教学小节
# ===========================================================================


def demo_naive_fails() -> None:
    section("反面教材：一次想完 + 盲执行 = 假成功", "①")
    note("任务：")
    code(TASK, indent=4, lang="任务")
    print()
    note("规划时（t=0）订单还是「已发货」，模型据此写出 2 步计划，并把运费 33.75 写死进去：")
    for i, (tool, args) in enumerate(NAIVE_PLAN, 1):
        code(f"{i}. {tool}({json.dumps(args, ensure_ascii=False)})", indent=4)

    print()
    world = World()
    world.cancel("A1001")      # ★ 计划做完之后、执行之前，世界变了
    warn("执行前，订单 A1001 被取消了（环境变了 —— 这在意料之外，但完全在情理之中）。")

    report_text, errors = naive_one_shot(world)
    print()
    kv("Executor 交出的报告", report_text)
    kv("真实发生的错误", errors if errors else "（无）")
    kv("世界里的真实副作用", world.sent if world.sent else "（空 —— 一条通知都没发出去）")
    print()
    warn("报告的措辞是「任务已完成」，但 send_reply 其实失败了，客户什么都没收到。")
    warn("运费 33.75 元也从未被验证过 —— 它是规划时猜出来的数字，却被写进了通知文案。")
    print()
    note("为什么会这样？因为「想」和「做」混在一起：计划里的每一步都是假设，")
    note("但朴素的执行器把假设当成事实 —— 既不校验，也没有「计划已经失效」这个概念。")
    print()
    bullet("死法一：让异常冒出来 → 整条链崩在第二步，前一步的成果也丢了。")
    bullet("死法二（本节的）：吞掉错误继续跑 → 交出假报告，事故要到客户投诉才发现。")
    print()
    ok("修法：把计划做成结构化数据 + 逐步验证 + 失败了重规划。下面三节就是它。")


def demo_plan() -> Plan:
    section("第一步：把任务拆成结构化的有序步骤", "②")
    world = World()
    tools = world.build_tools()
    planner = Planner(PlanBotLLM(), tools)
    plan = planner.make_plan(TASK)

    note("Planner 产出的不是一段话，而是**结构化数据**。下面是它的可读渲染：")
    print()
    code(plan.render(with_result=False), indent=4)
    print()
    kv("步骤数", len(plan.steps))
    kv("依赖关系", {s.id: s.depends_on for s in plan.steps})
    kv("参数引用", {s.id: s.args for s in plan.steps if any("$" in str(v) for v in s.args.values())})
    print()
    note("三个关键设计（缺一个，计划就退化成一段自然语言）：")
    bullet("goal —— 写给人看，也写给重规划时的模型看（失败时它靠这个判断哪条假设破了）")
    bullet("depends_on —— 决定执行顺序，也决定失败时谁会受牵连")
    bullet("args 里的 $1.weight_kg —— 让数据可以**在步骤之间流动**，而不是靠模型猜")
    print()
    problems = validate_plan(plan, tools)
    kv("静态校验", "通过" if not problems else problems)
    note("执行前先校验：副作用不可撤销，能提前拦下的错误绝不拖到执行期。")
    return plan


def demo_execute_step_by_step() -> None:
    section("第二步：确定性执行 —— 每一步都被验证", "③")
    note("这次世界没有变（订单仍是已发货），我们看正常路径长什么样。")
    print()
    world = World()
    tools = world.build_tools()
    executor = Executor(tools, Planner(PlanBotLLM(), tools))
    result = executor.run(TASK)

    print()
    kv("停机原因", result.stop_reason)
    kv("工具调用次数", result.tool_calls)
    kv("实际发出的通知", world.sent[0] if world.sent else "（无）")
    print()
    note("注意第 2 步的参数是 `$1.weight_kg` —— 2.5 这个数字是从第 1 步的**真实结果**里取的，")
    note("不是模型猜的。这就是「结构化计划」比「一段自然语言计划」强的地方：")
    note("模型只负责**编排**，事实必须来自工具。")
    print()
    code(result.final_plan.render(with_result=True), indent=4)


def demo_replan() -> None:
    section("第三步：环境变了 → 失败 → 重规划（本章的核心）", "④")
    note("同样的任务、同样的计划，但这次订单在「计划完成之后、执行之前」被取消了。")
    print()

    world = World()
    tools = world.build_tools()
    planner = Planner(PlanBotLLM(), tools)
    plan_v1 = planner.make_plan(TASK)
    world.cancel("A1001")
    warn("订单 A1001 已取消。计划 v1 里的假设（已发货）此刻已经失效。")

    result = executor_run_with_plan(tools, planner, plan_v1)
    print()
    kv("停机原因", result.stop_reason)
    kv("计划版本数", len(result.plans))
    kv("重规划次数", result.replans)
    kv("被复用的已完成步骤", result.reused_steps)
    kv("工具调用总次数", result.tool_calls)
    print()

    section("重规划改了什么", "")
    print(result.plans[0].diff(result.plans[1]))
    print()
    kv("最终发给客户的文案", world.sent[0] if world.sent else "（无）")
    print()
    note("重规划提示词里必须有三块（见 planner.py 的 replan()）：")
    bullet("① 原始任务 —— 不给它，模型重规划几次就跑偏了")
    bullet("② 已完成步骤的**真实结果** —— 这些是已验证的事实，要保留")
    bullet("③ 失败点 + 原始错误 —— 这是重规划唯一的理由")
    print()
    warn("只给模型一句「失败了，重新规划吧」是没用的：它不知道哪条假设错了，")
    warn("只会把同一份计划再写一遍（这是重规划最常见的失败形态）。")
    print()
    ok("还有一件事同样重要：重规划必须**有预算**（max_replans）。")
    note("模型可能反复给出跑不通的计划，没有预算就是无限烧钱 —— 和 max_steps 一个道理。")


def executor_run_with_plan(tools: ToolRegistry, planner: Planner, plan: Plan):
    """小工具：直接拿一份现成的计划去跑（跳过 make_plan）。"""
    return Executor(tools, planner).run(TASK, plan=plan)


def demo_granularity() -> None:
    section("第四步：计划粒度 —— 越细不等于越好", "⑤")
    note("同一个任务、同一次环境变化（订单被取消），只改计划粒度，看指标怎么变。")
    print()

    rows: list[tuple[str, int, int, int, str]] = []
    for label, hint in (("粗粒度", "尽量粗（能合并的步骤都合并）"),
                        ("中粒度", ""),
                        ("细粒度", "尽量细（每步只读一个字段）")):
        world = World()
        tools = world.build_tools()
        planner = Planner(PlanBotLLM(), tools, verbose=False)
        plan = planner.make_plan(TASK, hint=hint)
        world.cancel("A1001")
        # verbose=False：三种粒度的逐行执行日志会刷屏，这里我们只关心**指标**
        result = Executor(tools, planner, verbose=False).run(TASK, plan=plan)
        rows.append((label, len(plan.steps), result.tool_calls, result.reused_steps, result.stop_reason))

    print(f"  {'粒度':<8}{'计划步数':<10}{'工具调用':<10}{'复用步数':<10}{'结果'}")
    print("  " + "-" * 56)
    for label, steps, calls, reused, stop in rows:
        print(f"  {label:<8}{steps:<12}{calls:<12}{reused:<12}{stop}")
    print()
    bullet("粗粒度：步数少、调用少，但**失败后没有任何东西可以复用** —— ")
    bullet("        唯一的中间产物（通知文案）混入了「已发货」这个错误假设，只能整体作废重做；")
    bullet("        而且运费 33.75 是计划期猜的数字，谁也没验证过。")
    bullet("中粒度：每步一件事 —— 失败时能精确定位到「calc_freight 这一步的假设破了」，")
    bullet("        重规划只改必要的一步，已经验证过的事实（订单全貌）继续复用。")
    bullet("细粒度：调用次数最多，收益却是零 —— 一个字段读一次并没有让重规划更聪明，")
    bullet("        只是把中间结果堆进了上下文（第 05 章会看到这些中间结果有多贵）。")
    print()
    ok("粒度原则：**以「失败时能精确定位、且不必连累已完成的步骤」为标准**，不是越细越好。")
    note("工程上还有个硬约束：每一次工具调用都是延迟和成本，步数直接乘在你的账单上。")


def demo_plan_guardrails() -> None:
    section("第五步：跑不通的计划，一步都不许执行", "⑥")
    note("模型给你的计划里，最常见的三种毛病：幻觉工具、循环依赖、参数不合法。")
    print()

    cases: list[tuple[str, LLM]] = [
        ("幻觉工具（search_web 不存在）", PhantomToolLLM()),
        ("循环依赖（1 等 2，2 等 1）", CyclicPlanLLM()),
        ("参数不合法（calc_freight 少了必填的 weight_kg）", MissingArgPlanLLM()),
    ]
    for label, llm in cases:
        world = World()
        tools = world.build_tools()
        result = Executor(tools, Planner(llm, tools), verbose=False).run(TASK)
        kv(label, f"{result.stop_reason}")
        code(result.failure[:160], indent=4)
        kv("工具调用次数（必须是 0）", world.count())
        print()

    warn("关键点：这些计划**一步都没执行**。因为副作用是不可撤销的 ——")
    warn("宁可拒绝执行并让模型重写，也不要抱着「先跑跑看」的心态。")
    print()

    # 规划器输出根本不是 JSON
    world = World()
    tools = world.build_tools()
    result = Executor(tools, Planner(BrokenJsonLLM(), tools), verbose=False).run(TASK)
    kv("规划器返回一段人话而不是 JSON", result.stop_reason)
    code(result.failure[:200], indent=4)
    print()
    note("规划失败是**预期内的失败模式**，不是意外：")
    bullet("① 重试（让模型重新写一次，提示词里带上解析错误）")
    bullet("② 降级（退化成第 01 章的单步 ReAct 循环，边走边看）")
    bullet("③ 转人工（复杂任务的计划本来就更适合让人确认一眼）")
    warn("唯一不能做的：让异常冒到顶层，把整个任务炸掉。")


def demo_essence() -> None:
    section("收口：一句话本质", "⑦")
    essence(
        "规划 = 先产出步骤列表，再逐步执行 + 按需重规划。\n"
        "计划是假设，执行是验证，偏差就要修计划。\n"
        "\n"
        "三个角色：Planner（说）→ Executor（做）→ Replanner（改）。\n"
        "Planner 与 Replanner 是模型（不确定），Executor 是代码（确定），\n"
        "—— 把不确定的部分和确定的部分分开，是 Agent 工程最核心的手感。\n"
        "\n"
        "记住三句话：\n"
        "  1. 计划一定要是结构化数据，否则你无法校验、执行、对比、统计；\n"
        "  2. 计划里写死的每个值都是假设，能用工具查的就别猜；\n"
        "  3. 重规划必须有预算，而且必须复用已完成的步骤（否则重规划 = 重跑）。"
    )


# ===========================================================================
# 四、验收标准（由 scripts/run_all_checks.py 调用）
# ===========================================================================
# 铁律：run_checks() 必须**快、确定、不打印**。它会被自动验证程序调用，
# 所以这里全部用 verbose=False 的组件，且不依赖任何网络 / 随机 / 时间。


def _run(world: World, hint: str = "", cancel: bool = False, max_replans: int = 2,
         llm: LLM | None = None, plan: Plan | None = None):
    tools = world.build_tools()
    planner = Planner(llm or PlanBotLLM(), tools, max_replans=max_replans, verbose=False)
    plan = plan if plan is not None else planner.make_plan(TASK, hint=hint)
    if cancel:
        world.cancel("A1001")
    result = Executor(tools, planner, verbose=False).run(TASK, plan=plan)
    return plan, result, world


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（对应 ROADMAP.md 第 04 章的三条）。"""
    results: list[tuple[str, bool, str]] = []

    # --- 验收 1：能把多步任务拆成有序步骤并逐步执行 ---------------------
    plan, result, world = _run(World())
    ids = [s.id for s in plan.steps]
    deps_ok = all(d < s.id for s in plan.steps for d in s.depends_on)
    results.append(check_that(
        "能把多步任务拆成有序步骤（≥3 步，编号递增，依赖只指向更小的编号）",
        len(plan.steps) >= 3 and ids == sorted(ids) and deps_ok,
        f"{len(plan.steps)} 步 / 依赖 {[s.depends_on for s in plan.steps]}"))
    results.append(check_that(
        "逐步执行全部成功（stop_reason == completed）",
        result.stop_reason == "completed" and all(s.status == "done" for s in plan.steps),
        f"{result.stop_reason} / {[s.status for s in plan.steps]}"))
    results.append(check_that(
        "步骤之间的数据引用被正确解析（$1.weight_kg → 2.5，算出 33.75 元运费）",
        any("33.75" in s.observation for s in plan.steps),
        next((re.sub(r"\s+", " ", s.observation)[:60]
              for s in plan.steps if "33.75" in s.observation), "没有算出来")))
    results.append(check_that(
        "每一步的调用结果都被记录，可追溯（观测/耗时/工具有痕迹）",
        all(s.observation for s in plan.by_status("done")) and result.tool_calls == len(plan.steps),
        f"tool_calls={result.tool_calls}, steps={len(plan.steps)}"))

    # --- 验收 2：某一步失败时触发重规划，而不是整条链崩掉 ---------------
    plan1, res1, world1 = _run(World(), cancel=True)
    failed = [s for s in plan1.steps if s.status == "failed"]
    results.append(check_that(
        "环境变化导致某一步失败（而不是被静默吞掉）",
        len(failed) == 1 and failed[0].tool == "calc_freight",
        f"失败于第 {failed[0].id} 步 {failed[0].tool}: {failed[0].error[:40]}" if failed else "没有失败步骤"))
    results.append(check_that(
        "失败触发重规划（计划版本 +1，版本号连续）",
        res1.replans == 1 and len(res1.plans) == 2 and res1.plans[1].version == 2,
        f"replans={res1.replans}, versions={[p.version for p in res1.plans]}"))
    results.append(check_that(
        "重规划后的计划改掉了失效的假设（不再算运费，改查退款）",
        any(s.tool == "query_refund" for s in res1.final_plan.steps)
        and all(s.tool != "calc_freight" for s in res1.final_plan.steps),
        f"最终计划工具链：{[s.tool for s in res1.final_plan.steps]}"))
    results.append(check_that(
        "整条链没有崩：重规划后任务完成，且副作用真实发生（客户收到取消通知）",
        res1.stop_reason == "completed" and len(world1.sent) == 1 and "已取消" in world1.sent[0],
        f"{res1.stop_reason} / sent={world1.sent[:1]}"))
    results.append(check_that(
        "重规划复用了已完成的步骤（订单只查了一次，没有重复劳动）",
        res1.reused_steps == 1 and world1.count("lookup_order") == 1,
        f"reused={res1.reused_steps}, lookup_order 调用 {world1.count('lookup_order')} 次"))

    # --- 验收 3：计划不能一次做完（环境会变 / 假设会错） ----------------
    # 一份"规划时想得挺美"的静态计划：把 kind="shipped" 这个假设直接写死在参数里。
    static_plan = Plan(version=1, steps=[
        Step(id=1, goal="拟稿", tool="draft_reply",
             args={"order_id": "A1001", "kind": "shipped"}),
        Step(id=2, goal="发送", tool="send_reply",
             args={"order_id": "A1001", "text": "$1.text"}, depends_on=[1]),
    ])
    w_static = World()
    w_static.cancel("A1001")                     # 计划做完之后环境变了
    t_static = w_static.build_tools()
    # max_replans=0：这份计划"一次想完就不再改"，让它自己暴露问题
    r_static = Executor(t_static, Planner(PlanBotLLM(), t_static, max_replans=0, verbose=False),
                        verbose=False).run(TASK, plan=static_plan)
    results.append(check_that(
        "一次性写死的计划在环境变化后失效（证明计划不能一次做完）",
        r_static.stop_reason != "completed" and static_plan.get(1).status == "failed"
        and "已取消" in static_plan.get(1).error,
        f"{r_static.stop_reason} / 第 1 步 {static_plan.get(1).status}：{static_plan.get(1).error[:40]}"))
    r_exhaust = _run(World(), cancel=True, max_replans=0)[1]
    results.append(check_that(
        "重规划预算用尽时优雅停机（不是无限重规划）",
        r_exhaust.stop_reason == "replan_exhausted",
        r_exhaust.stop_reason))
    results.append(check_that(
        "失败后续的步骤不会被硬跑（依赖未满足的步骤保持未执行）",
        world_no_run_guard(), "第 3/4 步未执行，draft_reply / send_reply 一次都没被调用"))

    # --- 加分项：计划校验（跑不通的计划一步都不执行） -------------------
    w1 = World()
    t1 = w1.build_tools()
    r_phantom = Executor(t1, Planner(PhantomToolLLM(), t1, verbose=False), verbose=False).run(TASK)
    results.append(check_that(
        "幻觉工具被静态校验拦住，且一步都没执行",
        r_phantom.stop_reason == "plan_invalid" and w1.count() == 0 and "search_web" in r_phantom.failure,
        f"{r_phantom.stop_reason} / 调用 {w1.count()} 次"))
    w2 = World()
    t2 = w2.build_tools()
    r_cycle = Executor(t2, Planner(CyclicPlanLLM(), t2, verbose=False), verbose=False).run(TASK)
    results.append(check_that(
        "循环依赖被静态校验拦住",
        r_cycle.stop_reason == "plan_invalid" and "循环" in r_cycle.failure + "依赖",
        r_cycle.failure[:60]))
    w4 = World()
    t4 = w4.build_tools()
    r_args = Executor(t4, Planner(MissingArgPlanLLM(), t4, verbose=False), verbose=False).run(TASK)
    results.append(check_that(
        "缺少必填参数的计划被静态校验拦住（并且一步都没执行）",
        r_args.stop_reason == "plan_invalid" and "必填参数" in r_args.failure and w4.count() == 0,
        r_args.failure[:60]))
    w3 = World()
    t3 = w3.build_tools()
    r_bad = Executor(t3, Planner(BrokenJsonLLM(), t3, verbose=False), verbose=False).run(TASK)
    results.append(check_that(
        "规划器输出坏 JSON 时不崩（plan_failed，可降级）",
        r_bad.stop_reason == "plan_failed" and "JSON" in r_bad.failure,
        r_bad.stop_reason))

    # --- 加分项：粒度权衡 -------------------------------------------------
    coarse = _run(World(), hint="尽量粗（能合并的步骤都合并）", cancel=True)
    normal = _run(World(), hint="", cancel=True)
    fine = _run(World(), hint="尽量细（每步只读一个字段）", cancel=True)
    results.append(check_that(
        "粒度权衡：细粒度的调用次数多于中粒度，但成功率没有提高",
        fine[1].tool_calls > normal[1].tool_calls
        and fine[1].stop_reason == normal[1].stop_reason == "completed",
        f"细 {fine[1].tool_calls} 次 vs 中 {normal[1].tool_calls} 次，结果同为 completed"))
    results.append(check_that(
        "粒度权衡：粗粒度失败后无可复用的中间结果（复用步数为 0）",
        coarse[1].stop_reason == "completed" and coarse[1].reused_steps == 0
        and normal[1].reused_steps == 1,
        f"粗 {coarse[1].reused_steps} / 中 {normal[1].reused_steps}"))

    return results


def world_no_run_guard() -> bool:
    """max_replans=0 时第 2 步失败，后面的步骤必须保持未执行（不能被硬跑）。"""
    world = World()
    tools = world.build_tools()
    planner = Planner(PlanBotLLM(), tools, max_replans=0, verbose=False)
    plan = planner.make_plan(TASK)
    world.cancel("A1001")
    Executor(tools, planner, verbose=False).run(TASK, plan=plan)
    later = plan.get(4)
    return world.count("draft_reply") == 0 and world.count("send_reply") == 0 and later.status == "pending"


# ===========================================================================
# 入口
# ===========================================================================
SECTIONS = {
    "1": ("反面教材：一次想完 + 盲执行", demo_naive_fails),
    "2": ("把任务拆成结构化步骤", demo_plan),
    "3": ("确定性逐步执行", demo_execute_step_by_step),
    "4": ("失败 → 重规划", demo_replan),
    "5": ("计划粒度的取舍", demo_granularity),
    "6": ("跑不通的计划不许执行", demo_plan_guardrails),
    "7": ("一句话本质", demo_essence),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 04 章 · 规划与任务分解")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 04 章 · 规划与任务分解")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 04 章", run_checks()) else 1

    banner("第 04 章 · 规划与任务分解",
           "目标：把「一步一想的 ReAct」升级成「先规划 → 逐步执行 → 按需重规划」")

    for key in ([args.section] if args.section else sorted(SECTIONS)):
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 04 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
