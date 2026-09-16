"""第 04 章 · Planner-Executor：把"一次想完"改成"先规划、再执行、按需重规划"。

--------------------------------------------------------------------------
一句话本质：
    规划 = 先产出步骤列表，再逐步执行 + 按需重规划。
    计划是**假设**，执行是**验证**，偏差就要修计划。
--------------------------------------------------------------------------

为什么把规划器单独放一个文件？
    因为真实工程里这三个角色的**寿命完全不同**：
      - Planner（模型，不确定）
      - Executor（确定性代码，可测试）
      - Replanner（模型，不确定）
    把它们混在一个 800 行的文件里，你就没法单独给 Executor 写测试了。
    本文件刻意保持"可以被 run_checks() 在 1 秒内跑完"的规模。

三个角色各自的职责（记住这张表，后面所有 Agent 框架都是它的变体）：

    ┌───────────┬────────────────────────┬──────────────────────────┐
    │ 角色      │ 输入                    │ 输出                     │
    ├───────────┼────────────────────────┼──────────────────────────┤
    │ Planner   │ 任务 + 工具清单         │ 步骤列表（假设）          │
    │ Executor  │ 步骤列表                │ 每步的真实结果（验证）    │
    │ Replanner │ 任务 + 计划 + 失败原因  │ 修正后的步骤列表          │
    └───────────┴────────────────────────┴──────────────────────────┘

为什么 Executor 必须是确定性代码、而不是让模型"边做边想"？
    因为可测试。计划可以错，但"按计划执行"这件事不允许有随机性 ——
    否则你永远不知道失败是计划的锅还是执行的锅。
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.console import bullet, kv, note, warn
from core.llm import LLM, estimate_tokens
from core.message import Message
from core.tool import ToolRegistry, ToolResult

# ===========================================================================
# 一、计划的数据结构：Step 与 Plan
# ===========================================================================
# 为什么计划要写成结构化数据（而不是一段自然语言）？
#   1. 可以**校验**：工具存不存在、依赖有没有环、参数全不全；
#   2. 可以**执行**：Executor 不需要理解自然语言，只认数据结构；
#   3. 可以**对比**：重规划前后能 diff 出"到底改了哪几步"；
#   4. 可以**评估**：步数、调用次数、失败率都是可统计的指标（第 10 章要用）。
# 一句话：自然语言的计划只能给人看，结构化的计划才能给机器跑。


@dataclass
class Step:
    """计划中的一步。

    注意 `args` 里可以写**引用**（形如 "$1.status"），表示"用第 1 步结果的 status 字段"。
    这是计划能表达"依赖关系"的关键 —— 否则只能写死参数，那就不是计划而是脚本了。
    """

    id: int
    goal: str                                   # 这一步要达成什么（写给人看，也写给模型看）
    tool: str = ""                              # 用哪个工具
    args: dict[str, Any] = field(default_factory=dict)
    depends_on: list[int] = field(default_factory=list)
    status: str = "pending"                     # pending / done / failed / blocked
    result: Any = None                          # 结构化结果（供后续步骤引用）
    observation: str = ""                       # 文本结果（喂给人和模型）
    error: str = ""
    elapsed_ms: float = 0.0

    @property
    def signature(self) -> str:
        """步骤指纹：工具 + 参数。用于判断"这一步是否已经做过、可否复用"。"""
        return f"{self.tool}({json.dumps(self.args, sort_keys=True, ensure_ascii=False, default=str)})"

    def line(self, with_result: bool = True) -> str:
        mark = {"pending": "·", "done": "✓", "failed": "✗", "blocked": "⊘"}.get(self.status, "?")
        dep = f"  ←依赖 {self.depends_on}" if self.depends_on else ""
        head = f"{mark} {self.id}. [{self.status:<7}] {self.goal}{dep}"
        if not with_result:
            return head
        detail = f"\n       调用: {self.signature}"
        if self.observation:
            detail += f"\n       结果: {_one_line(self.observation, 88)}"
        if self.error:
            detail += f"\n       错误: {_one_line(self.error, 88)}"
        return head + detail


@dataclass
class Plan:
    """一版计划。`version` 从 1 开始，每次重规划 +1。"""

    version: int
    steps: list[Step] = field(default_factory=list)
    reason: str = ""            # 这一版为什么存在（初始计划 / 重规划的原因）
    replan_from: int = 0        # 由哪一版重规划而来

    def get(self, step_id: int) -> Step | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    def by_status(self, status: str) -> list[Step]:
        return [s for s in self.steps if s.status == status]

    @property
    def done_signatures(self) -> dict[str, Step]:
        """已成功步骤的指纹表 —— 重规划时用它避免重复执行（尤其是重复副作用）。"""
        return {s.signature: s for s in self.steps if s.status == "done"}

    def render(self, with_result: bool = True) -> str:
        head = f"计划 v{self.version}"
        if self.reason:
            head += f"（{self.reason}）"
        return head + "\n" + "\n".join(s.line(with_result) for s in self.steps)

    def diff(self, other: "Plan") -> str:
        """对比两版计划的差异 —— 重规划到底改了什么，一眼看出来。"""
        old = {s.id: s for s in self.steps}
        new = {s.id: s for s in other.steps}
        lines: list[str] = []
        for sid in sorted(set(old) | set(new)):
            a, b = old.get(sid), new.get(sid)
            if a and not b:
                lines.append(f"  - 删除第 {sid} 步：{a.goal}")
            elif b and not a:
                lines.append(f"  + 新增第 {sid} 步：{b.goal}（{b.tool}）")
            elif a and b and a.signature != b.signature:
                if a.tool != b.tool:
                    lines.append(f"  ~ 修改第 {sid} 步：工具 {a.tool} → {b.tool}")
                else:
                    lines.append(f"  ~ 修改第 {sid} 步：工具仍是 {a.tool}，但参数/目标变了")
                lines.append(f"      旧目标：{a.goal}")
                lines.append(f"      新目标：{b.goal}")
            elif a and b:
                lines.append(f"  = 保留第 {sid} 步：{b.goal}")
        return "\n".join(lines) or "  （两版计划完全一致）"


# ===========================================================================
# 二、计划校验：在执行之前把"跑不通的计划"拦下来
# ===========================================================================
# 为什么必须在执行前校验？因为执行计划的代价是**真实副作用**：
# 发了一条错误的短信、写坏了一个文件、扣了一笔钱，你是没法 ctrl+z 的。
# 计划期的静态检查很便宜，执行期的错误很贵 —— 所以能提前发现的就别拖到执行。
#
# 但也要清楚**静态检查的能力边界**：它只能查"结构问题"（工具名、依赖、参数是否齐），
# 查不出"值对不对"（weight_kg 到底是 2.5 还是 25，只有执行时才知道）。
# 这个边界很重要：它决定了计划期该做什么、执行期该兜什么。

def validate_plan(plan: Plan, tools: ToolRegistry) -> list[str]:
    """返回问题列表（空列表 = 计划合法）。收集**全部**问题一次性反馈给模型。"""
    problems: list[str] = []
    ids = [s.id for s in plan.steps]

    if not plan.steps:
        problems.append("计划为空：至少要有一步")
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        problems.append(f"步骤 id 重复：{dup}")

    known = set(tools.names())
    for s in plan.steps:
        # ① 工具必须真实存在（模型很爱编工具名）
        if not s.tool:
            problems.append(f"第 {s.id} 步没有指定工具")
        elif s.tool not in known:
            problems.append(f"第 {s.id} 步用了不存在的工具 {s.tool!r}，可用工具：{sorted(known)}")
        else:
            # ② 参数必须符合工具的 schema（这里只查"齐不齐/多不多"，不查值）
            spec = tools.get(s.tool)
            props = set(spec.parameters.get("properties", {}))
            required = set(spec.parameters.get("required", []))
            missing = sorted(required - set(s.args))
            extra = sorted(set(s.args) - props)
            if missing:
                problems.append(f"第 {s.id} 步缺少必填参数 {missing}（工具 {s.tool}）")
            if extra:
                problems.append(f"第 {s.id} 步出现未定义参数 {extra}（工具 {s.tool} 只接受 {sorted(props)}）")

        # ③ 依赖必须指向**本计划里已经出现过的更小 id**。
        #    这条规则一石二鸟：既挡住了"依赖不存在的步骤"，也天然挡住了循环依赖
        #    （A 依赖 B、B 依赖 A 时，必然有一个依赖指向更大的 id）。
        for d in s.depends_on:
            if d == s.id:
                problems.append(f"第 {s.id} 步依赖了自己")
            elif d not in ids:
                problems.append(f"第 {s.id} 步依赖了不存在的步骤 {d}")
            elif d > s.id:
                problems.append(
                    f"第 {s.id} 步依赖了后面的第 {d} 步 —— 依赖只能指向更小的步骤编号"
                    f"（否则可能出现循环依赖，且执行顺序无法确定）"
                )
    return problems


# ===========================================================================
# 三、Planner：让模型产出计划（本文件里它是"结构化输出"的消费者）
# ===========================================================================
PLANNER_SYSTEM = """你是一个任务规划器。你的工作是把用户的复杂任务拆解成**有序的、可执行的**步骤。

# 输出格式（严格遵守，只输出 JSON，不要任何解释文字）
{
  "steps": [
    {"id": 1, "goal": "这一步要达成什么（中文，简短）",
     "tool": "工具名", "args": {"参数名": "值或引用"}, "depends_on": []}
  ]
}

# 规则
1. 步骤编号从 1 开始并**严格递增**；depends_on 只能引用编号更小的步骤。
2. 参数值可以用 "$<步骤号>.<字段名>" 的形式引用前面步骤的结果，例如 "$1.order_id"。
3. 不要臆造工具；只能使用给定清单里的工具。
4. 每一步只做一件事，粒度以"失败时能精确定位"为准。
5. 步骤越少越好，但**不允许把需要判断的事情藏进一步里**。
"""


def _extract_json(text: str) -> Any:
    """从模型输出里抠出 JSON。

    真实模型会给你加一堆 ```json 围栏和"好的，这是我的计划："之类的客套话，
    所以必须有这层容错。core/parser.py 里有更完整的版本（处理单引号/尾逗号/裸键名），
    这里只保留最必要的三种：去围栏 → 取最外层花括号 → 修尾逗号。
    """
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    try:
        return json.loads(text)
    except Exception:
        pass
    try:  # 尾逗号是模型最常见的 JSON 错误，值得单独救一次
        return json.loads(re.sub(r",\s*([}\]])", r"\1", text))
    except Exception as exc:
        raise ValueError(f"计划不是合法 JSON：{exc}；原始输出前 120 字：{text[:120]!r}") from exc


def _parse_steps(payload: Any) -> list[Step]:
    """把模型给的 JSON 变成 Step 列表。字段缺失一律给默认值，绝不因为小毛病整单丢弃。"""
    if isinstance(payload, dict):
        raw_steps = payload.get("steps") or payload.get("plan") or []
    elif isinstance(payload, list):
        raw_steps = payload
    else:
        raw_steps = []
    steps: list[Step] = []
    for i, item in enumerate(raw_steps, 1):
        if not isinstance(item, dict):
            continue
        try:
            sid = int(item.get("id", i))
        except (TypeError, ValueError):
            sid = i
        deps = item.get("depends_on") or item.get("deps") or []
        if isinstance(deps, (int, str)):
            deps = [deps]
        clean_deps: list[int] = []
        for d in deps:
            try:
                clean_deps.append(int(d))
            except (TypeError, ValueError):
                pass
        args = item.get("args") or item.get("arguments") or {}
        steps.append(Step(
            id=sid,
            goal=str(item.get("goal") or item.get("description") or "").strip() or f"步骤 {sid}",
            tool=str(item.get("tool") or item.get("action") or "").strip(),
            args=args if isinstance(args, dict) else {},
            depends_on=clean_deps,
        ))
    return steps


class Planner:
    """调用模型产出计划 / 重规划。

    关键设计：**Planner 不碰工具**。它只负责"说"，执行是 Executor 的事。
    这样你才能用一个假模型专门测试规划逻辑（本课程的 run_checks 就是这么做的）。
    """

    def __init__(self, llm: LLM, tools: ToolRegistry, max_replans: int = 2, verbose: bool = True) -> None:
        self.llm = llm
        self.tools = tools
        self.max_replans = max_replans     # ★ 重规划预算是必需品，理由同 max_steps
        self.verbose = verbose
        self.prompts: list[list[Message]] = []   # 记录每次送给模型的提示词（教学观察用）

    # ---- 内部：一次"让模型写计划"的调用 ---------------------------------
    def _ask(self, user_prompt: str) -> list[Step]:
        messages = [Message.system(PLANNER_SYSTEM), Message.user(user_prompt)]
        self.prompts.append(messages)
        resp = self.llm.complete(messages)
        return _parse_steps(_extract_json(resp.text))

    def _tool_manual(self) -> str:
        """把工具说明书塞进提示词 —— 计划里能用的工具必须在清单内。"""
        return self.tools.describe("prompt")

    # ---- 初始计划 -------------------------------------------------------
    def make_plan(self, task: str, hint: str = "") -> Plan:
        prompt = (
            f"# 任务\n{task}\n\n"
            f"# 可用工具\n{self._tool_manual()}\n\n"
            + (f"# 粒度要求\n{hint}\n\n" if hint else "")
            + "# 请输出这一任务的执行计划（JSON）。"
        )
        steps = self._ask(prompt)
        return Plan(version=1, steps=steps, reason="初始计划")

    # ---- 重规划 ---------------------------------------------------------
    def replan(self, task: str, plan: Plan, failed: Step, reason: str) -> Plan:
        """带着"上一版计划 + 真实执行结果 + 失败原因"重新规划。

        注意这里的提示词包含三块，缺一不可：
          ① 原始任务   —— 防止模型跑偏（重规划最容易丢掉初始目标）
          ② 已完成的步骤及其**真实结果** —— 这些是已验证的事实，要保留
          ③ 失败点及其原因 —— 这是重规划的唯一理由
        只给"失败了，重新规划吧"是没用的：模型不知道哪条假设错了，只会重写一遍同样的计划。
        """
        history = plan.render(with_result=True)
        prompt = (
            f"# 任务\n{task}\n\n"
            f"# 可用工具\n{self._tool_manual()}\n\n"
            "# 重规划\n"
            f"上一版计划在执行中失败了，这是它现在的真实状态（含已完成步骤的真实结果）：\n"
            f"{history}\n\n"
            f"# 失败点\n"
            f"第 {failed.id} 步「{failed.goal}」（{failed.tool}）失败。\n"
            f"原因：{reason}\n\n"
            "# 要求\n"
            "1. 不要重复执行已经成功的步骤（除非它的前提假设已经不成立）；\n"
            "2. 只修改必要的步骤，尽量复用已验证的结果；\n"
            "3. 如果原目标已经不可能达成（例如订单被取消，就不能再通知发货），\n"
            "   请调整后续步骤去达成**修正后的目标**，并在 goal 里写清楚；\n"
            "4. 输出完整的新计划（JSON），编号从 1 开始。"
        )
        steps = self._ask(prompt)
        return Plan(version=plan.version + 1, steps=steps,
                    reason=f"第 {failed.id} 步失败后重规划：{reason[:60]}",
                    replan_from=plan.version)


# ===========================================================================
# 四、参数引用解析：$1.status 到底怎么变成真值
# ===========================================================================
class RefError(Exception):
    """引用解析失败。**必须触发重规划**，而不是让 Executor 崩掉。"""


_REF_EXACT_RE = re.compile(r"^\$(\d+)\.([\w\.]+)$")
_REF_ANY_RE = re.compile(r"\$(\d+)\.([\w\.]+)")


def _lookup_ref(plan: Plan, sid: int, path: str, key: str, raw: str) -> Any:
    src = plan.get(sid)
    if src is None or src.status != "done":
        raise RefError(f"参数 {key}={raw!r} 引用了未成功完成的第 {sid} 步")
    data: Any = src.result
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]
        else:
            raise RefError(
                f"参数 {key}={raw!r} 无法解析：第 {sid} 步的结果里没有 {path!r}"
                f"（可用的键：{sorted(data) if isinstance(data, dict) else type(data).__name__}）"
            )
    return data


def resolve_args(args: dict[str, Any], plan: Plan) -> dict[str, Any]:
    """把参数里的 "$1.weight_kg" 替换成第 1 步结果里的真实值。

    为什么要设计引用语法？
        因为"依赖"必须能**传递数据**而不只是"排个先后顺序"。
        没有它，模型就得把 weight_kg 的值猜出来写死 —— 那就是幻觉的发源地。

    两种写法，用途不同：
        "$1.weight_kg"                → 整个参数就是引用，返回**原始类型**（数字还是数字）
        "运单号 $1.tracking，请查收"   → 字符串内插值，返回拼接后的字符串
    """
    out: dict[str, Any] = {}
    for key, value in args.items():
        if not isinstance(value, str):
            out[key] = value
            continue
        m = _REF_EXACT_RE.match(value.strip())
        if m:
            out[key] = _lookup_ref(plan, int(m.group(1)), m.group(2), key, value)
            continue
        if "$" in value:              # 内插值：把每个 $N.path 就地替换成文本
            out[key] = _REF_ANY_RE.sub(
                lambda mm: str(_lookup_ref(plan, int(mm.group(1)), mm.group(2), key, value)),
                value,
            )
            continue
        out[key] = value              # 普通字符串（例如 "加急"），原样透传
    return out


# ===========================================================================
# 五、Executor：确定性地把计划跑完，失败了就喊 Replanner
# ===========================================================================
@dataclass
class RunResult:
    """一次 Planner-Executor 运行的完整记录。"""

    task: str
    plans: list[Plan]
    stop_reason: str            # completed / replan_exhausted / plan_invalid / plan_failed
    answer: str = ""
    failure: str = ""
    tool_calls: int = 0
    replans: int = 0
    reused_steps: int = 0       # 重规划时被直接复用的已完成步骤数（省下的重复劳动）
    tokens: int = 0
    elapsed_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.stop_reason == "completed"

    @property
    def final_plan(self) -> Plan:
        return self.plans[-1]

    def trace(self) -> str:
        lines = [f"任务：{self.task}"]
        for p in self.plans:
            lines.append("")
            lines.append(p.render(with_result=True))
        lines.append("")
        lines.append(f"停机原因：{self.stop_reason} | 计划版本数：{len(self.plans)} "
                     f"| 重规划次数：{self.replans} | 工具调用：{self.tool_calls}")
        return "\n".join(lines)


class Executor:
    """逐步执行计划。**确定性代码，不含任何模型调用** —— 这是能写测试的前提。

    执行策略（每一步都问三个问题）：
        ① 依赖满足了吗？  —— 不满足就 blocked，触发重规划（而不是硬跑出错误结果）
        ② 引用能解析吗？  —— 解析不了说明上游结果和计划假设不一致，触发重规划
        ③ 工具成功了吗？  —— 失败就带着**原始错误**触发重规划
    所有分支都不抛异常给调用方：Agent 的哲学是"失败要变成信息"，不是"失败要变成崩溃"。
    """

    def __init__(self, tools: ToolRegistry, planner: Planner, verbose: bool = True) -> None:
        self.tools = tools
        self.planner = planner
        self.verbose = verbose
        self._tool_calls = 0     # 真实发生的工具调用次数（被复用的步骤不算，它没调用工具）

    # ---- 主入口 ---------------------------------------------------------
    def run(self, task: str, plan: Plan | None = None) -> RunResult:
        t0 = time.perf_counter()
        self._tool_calls = 0
        plans: list[Plan] = []
        replans = 0
        reused = 0
        stop_reason = "completed"
        failure = ""

        if plan is None:
            # 规划失败（模型没给出合法 JSON）也不能崩：这是**预期内的失败模式**，
            # 真实系统里应该降级（例如退化成第 01 章的单步 ReAct 循环）而不是报错退出。
            try:
                plan = self.planner.make_plan(task)
            except Exception as exc:
                return RunResult(task=task, plans=[], stop_reason="plan_failed",
                                 failure=f"规划器输出无法解析：{exc}",
                                 elapsed_ms=(time.perf_counter() - t0) * 1000)
        plans.append(plan)

        while True:
            # ① 执行前校验：跑不通的计划绝不执行（副作用是不可撤销的）
            problems = validate_plan(plan, self.tools)
            if problems:
                stop_reason = "plan_invalid"
                failure = "；".join(problems)
                if self.verbose:
                    warn(f"计划 v{plan.version} 未通过静态校验，拒绝执行：")
                    for p in problems:
                        bullet(p)
                break

            # ② 逐步执行
            outcome = self._execute(plan)
            if outcome is None:                      # 全部步骤成功
                stop_reason = "completed"
                break

            failed_step, reason = outcome
            failure = reason
            if replans >= self.planner.max_replans:
                # ③ 重规划预算用尽：优雅停机 + 如实报告，而不是无限重规划
                stop_reason = "replan_exhausted"
                if self.verbose:
                    warn(f"重规划次数已达上限 {self.planner.max_replans}，停止重试。")
                break

            # ④ 带着失败去重规划
            try:
                new_plan = self.planner.replan(task, plan, failed_step, reason)
            except Exception as exc:
                stop_reason = "plan_failed"
                failure = f"重规划输出无法解析：{exc}"
                break
            reused += self._carry_over(plan, new_plan)   # 复用已成功步骤，避免重复副作用
            replans += 1
            if self.verbose:
                print(f"\n  ⟳ 触发重规划（第 {replans} 次）")
            plans.append(new_plan)
            plan = new_plan

        result = RunResult(
            task=task, plans=plans, stop_reason=stop_reason,
            answer=self._answer(plans[-1]), failure=failure,
            tool_calls=self._tool_calls,
            replans=replans,
            reused_steps=reused,
            tokens=estimate_tokens("\n".join(p.render() for p in plans)),
            elapsed_ms=(time.perf_counter() - t0) * 1000,
        )
        return result

    # ---- 执行一版计划 ---------------------------------------------------
    def _execute(self, plan: Plan) -> tuple[Step, str] | None:
        """返回 None 表示全部成功；否则返回 (失败的步骤, 原因)。"""
        for step in plan.steps:
            if step.status == "done":
                if self.verbose:
                    print(f"  ↺ 第 {step.id} 步已完成，跳过（复用上一版的结果）")
                continue

            # ① 依赖检查
            unmet = [d for d in step.depends_on
                     if (dep := plan.get(d)) is None or dep.status != "done"]
            if unmet:
                step.status = "blocked"
                step.error = f"依赖未满足：第 {unmet} 步没有成功完成"
                if self.verbose:
                    print(f"  ⊘ 第 {step.id} 步被阻塞：{step.error}")
                return step, step.error

            # ② 参数引用解析
            try:
                args = resolve_args(step.args, plan)
            except RefError as exc:
                step.status = "failed"
                step.error = str(exc)
                if self.verbose:
                    print(f"  ✗ 第 {step.id} 步参数无法解析：{exc}")
                return step, f"计划里的参数引用与真实结果不一致：{exc}"

            # ③ 执行（工具层永远不会抛异常，失败会变成 ok=False）
            result: ToolResult = self.tools.execute(step.tool, args)
            self._tool_calls += 1
            step.elapsed_ms = result.elapsed_ms
            if result.ok:
                step.status = "done"
                step.observation = result.content
                step.result = _maybe_json(result.content)
                if self.verbose:
                    print(f"  ✓ 第 {step.id} 步完成：{step.goal}")
                    print(f"      {step.tool}({_fmt(args)}) → {_one_line(result.content)}")
            else:
                step.status = "failed"
                step.error = result.error or result.content
                if self.verbose:
                    print(f"  ✗ 第 {step.id} 步失败：{step.goal}")
                    print(f"      {step.tool}({_fmt(args)}) → {_one_line(step.error)}")
                return step, step.error
        return None

    # ---- 重规划后：把上一版已成功的步骤继承过来 -------------------------
    def _carry_over(self, old: Plan, new: Plan) -> int:
        """**这一小段代码是重规划能否省钱的关键。**

        没有它，重规划 = 从头再跑一遍：重复的读操作浪费钱，重复的写操作是事故
        （客户会收到两条短信、账户会被扣两次钱）。
        有它，只有"指纹相同且已成功"的步骤会被沿用。返回被复用的步骤数。
        """
        reusable = old.done_signatures
        reused = 0
        for step in new.steps:
            prior = reusable.get(step.signature)
            if prior is not None:
                step.status = "done"
                step.result = prior.result
                step.observation = prior.observation
                reused += 1
        return reused

    # ---- 汇总答案 -------------------------------------------------------
    @staticmethod
    def _answer(plan: Plan) -> str:
        done = plan.by_status("done")
        if not done:
            return "（没有任何步骤成功完成）"
        return done[-1].observation.strip()


def _maybe_json(text: str) -> Any:
    """工具结果能反序列化成结构体就反序列化 —— 后续步骤要靠字段引用取数据。"""
    text = (text or "").strip()
    if not text.startswith(("{", "[")):
        return text
    try:
        return json.loads(text)
    except Exception:
        return text


def _one_line(text: str, width: int = 96) -> str:
    """把多行结果压成一行预览：**必须折叠连续的空白**，否则 JSON 的缩进会把输出撑爆。"""
    return re.sub(r"\s+", " ", text or "").strip()[:width]


def _fmt(args: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items())


# ===========================================================================
# 六、教学用的"外部世界"：一个会变的订单系统
# ===========================================================================
# 为什么第 04 章要造一个"会变的世界"？
#   因为"计划不能一次做完"这个结论，只有当你**亲眼看到环境在计划之后变了**，
#   才会真的相信。静态的例子里，一次想完的计划和逐步执行看起来没区别。
#
#   真实世界的变化来源：用户改了需求、库存被抢光、订单被取消、接口改了字段名、
#   另一个同事先提交了同样的改动…… 计划做得越早、执行得越晚，偏差就越大。

DEFAULT_ORDER = {
    "order_id": "A1001",
    "status": "已发货",
    "carrier": "顺丰",
    "tracking": "SF1234567890",
    "weight_kg": 2.5,
    "amount": 328.0,
}


class World:
    """订单系统 + 几个有副作用的动作。所有工具调用都被计数，便于课堂统计。"""

    def __init__(self, orders: dict[str, dict[str, Any]] | None = None) -> None:
        self.orders: dict[str, dict[str, Any]] = orders or {"A1001": dict(DEFAULT_ORDER)}
        self.calls: list[str] = []       # 每次工具调用记一笔（含失败），用于统计调用成本
        self.sent: list[str] = []        # 真正发出去的客户通知（副作用记录）
        self.refunds: dict[str, dict[str, Any]] = {}

    # ---- 世界的变化 -----------------------------------------------------
    def cancel(self, order_id: str) -> None:
        """模拟"计划做完之后，订单被取消了"。"""
        self.orders[order_id]["status"] = "已取消"
        self.orders[order_id]["carrier"] = None
        self.orders[order_id]["tracking"] = None

    def count(self, tool: str = "") -> int:
        return len(self.calls) if not tool else self.calls.count(tool)

    def calls_after(self, index: int, tool: str = "") -> int:
        """统计"第 index 次调用之后"发生的调用次数 —— 用于度量重做的工作量。"""
        tail = self.calls[index:]
        return len(tail) if not tool else tail.count(tool)

    # ---- 工具集 ---------------------------------------------------------
    def build_tools(self) -> ToolRegistry:
        """用 core/tool.py 的注册表注册工具 —— 参数校验、异常兜底全部白拿。"""
        reg = ToolRegistry()
        world = self

        def _order(order_id: str) -> dict[str, Any]:
            key = order_id.upper()
            if key not in world.orders:
                raise ValueError(f"订单 {key} 不存在。已知订单：{sorted(world.orders)}")
            return world.orders[key]

        @reg.tool(
            "lookup_order",
            "查询订单的当前状态、承运商、运单号、重量和金额。任何涉及订单的任务都应该先调用它。",
            {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号，例如 A1001",
                                 "pattern": "(?i)^[a-z]{0,2}\\d{3,}$"},
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
            tags=["read"],
        )
        def lookup_order(order_id: str) -> dict[str, Any]:
            world.calls.append("lookup_order")
            return dict(_order(order_id))

        @reg.tool(
            "get_field",
            "只读取订单的某一个字段（status/carrier/tracking/weight_kg/amount）。"
            "字段粒度读取会让步骤变多，请谨慎使用。",
            {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "field": {"type": "string", "description": "字段名",
                              "enum": ["status", "carrier", "tracking", "weight_kg", "amount"]},
                },
                "required": ["order_id", "field"],
                "additionalProperties": False,
            },
            tags=["read"],
        )
        def get_field(order_id: str, field: str) -> dict[str, Any]:
            world.calls.append("get_field")
            return {"field": field, "value": _order(order_id).get(field)}

        @reg.tool(
            "calc_freight",
            "计算运费。必须先知道订单状态和重量；订单已取消时无法计算运费。",
            {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "weight_kg": {"type": "number", "description": "重量（千克）", "minimum": 0},
                    "speed": {"type": "string", "description": "时效", "enum": ["标准", "加急"]},
                },
                "required": ["order_id", "weight_kg", "speed"],
                "additionalProperties": False,
            },
            tags=["compute"],
        )
        def calc_freight(order_id: str, weight_kg: float, speed: str) -> dict[str, Any]:
            world.calls.append("calc_freight")
            order = _order(order_id)
            if order["status"] == "已取消":
                raise ValueError(f"订单 {order_id} 已取消，无法计算运费")
            base = 12.0 if speed == "标准" else 25.0
            return {"order_id": order_id.upper(), "speed": speed,
                    "freight": round(base + 3.5 * float(weight_kg), 2),
                    "eta_days": 2 if speed == "加急" else 5}

        @reg.tool(
            "query_refund",
            "查询订单的退款状态与金额（订单取消后用它）。",
            {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "订单号"}},
                "required": ["order_id"],
                "additionalProperties": False,
            },
            tags=["read"],
        )
        def query_refund(order_id: str) -> dict[str, Any]:
            world.calls.append("query_refund")
            order = _order(order_id)
            if order["status"] != "已取消":
                raise ValueError(f"订单 {order_id} 未取消，没有退款记录")
            info = world.refunds.setdefault(order_id.upper(),
                                            {"status": "退款处理中", "amount": order["amount"],
                                             "eta_days": 3})
            return dict(info)

        @reg.tool(
            "draft_reply",
            "按订单的**真实状态**生成给客户的通知文案。kind 必须与订单当前状态一致："
            "已发货→shipped，运输中→delay，已取消→cancelled。",
            {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "kind": {"type": "string", "description": "通知类型",
                             "enum": ["shipped", "delay", "cancelled"]},
                    "detail": {"type": "string", "description": "要写进文案的补充信息（如运费、退款进度）"},
                },
                "required": ["order_id", "kind"],
                "additionalProperties": False,
            },
            tags=["write"],
        )
        def draft_reply(order_id: str, kind: str, detail: str = "") -> dict[str, Any]:
            world.calls.append("draft_reply")
            order = _order(order_id)
            expect = {"已发货": "shipped", "运输中": "delay", "已取消": "cancelled"}
            want = expect.get(order["status"])
            if kind != want:
                # 这条错误就是"计划里的假设已经过期"的信号，必须原样回灌给 Replanner
                raise ValueError(
                    f"通知类型 {kind!r} 与订单 {order_id} 的真实状态「{order['status']}」不符"
                    f"（应该用 {want!r}）"
                )
            texts = {
                "shipped": f"您的订单 {order_id} 已发货，承运商 {order['carrier']}，"
                           f"运单号 {order['tracking']}。{detail}",
                "delay": f"您的订单 {order_id} 仍在运输途中。{detail}",
                "cancelled": f"您的订单 {order_id} 已取消。{detail}",
            }
            return {"kind": kind, "text": texts[kind].strip()}

        @reg.tool(
            "send_reply",
            "把通知文案真正发送给客户（**有副作用，不可撤销**）。发送前会校验文案与订单状态一致。",
            {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "订单号"},
                    "text": {"type": "string", "description": "要发送的正文", "minLength": 1},
                },
                "required": ["order_id", "text"],
                "additionalProperties": False,
            },
            tags=["write"],
        )
        def send_reply(order_id: str, text: str) -> dict[str, Any]:
            world.calls.append("send_reply")
            order = _order(order_id)
            if order["status"] == "已取消" and "已发货" in text:
                # 兜底护栏：即使上游的计划全错，也不允许把错误信息发给客户
                raise ValueError(f"拒绝发送：订单 {order_id} 已取消，但文案声称已发货")
            world.sent.append(text)
            return {"sent": True, "to": f"客户({order_id})", "chars": len(text)}

        return reg


__all__ = [
    "Step", "Plan", "Planner", "Executor", "RunResult", "World",
    "validate_plan", "resolve_args", "RefError", "PLANNER_SYSTEM",
]
