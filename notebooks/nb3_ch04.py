"""第 04 章 · 规划与任务分解 —— Notebook 内容（逐步推进版）。

遵守 TEACHING_CONTRACT.md：
  · 逐步给：每个知识点在「读者正好需要」时出现
  · 前置知识表保留在 ⓪，定位是索引（可跳过）
  · 每个代码单元自包含（nb_lint 机器校验）
  · 中文引号一律用 「」，不在代码单元里嵌 ASCII 双引号
  · 代码单元里只用 GBK 也能编码的符号（读者在 GBK 控制台复制单格跑不会崩）
"""

from __future__ import annotations

from notebooks.nb_blocks import (
    checkpoint,
    exercises,
    header,
    objectives,
    pitfall_table,
    section,
    setup_cell,
    summary,
)
from notebooks.notebook_lib import Notebook


def build_04() -> Notebook:
    """第 04 章 · 规划与任务分解（逐步推进版）。"""
    nb = Notebook("第 04 章 · 规划与任务分解")

    header(
        nb, "04", "规划与任务分解",
        "规划 = 先产出**步骤列表**，再逐步执行 + 按需重规划。\n"
        "计划是**假设**，执行是**验证** —— 偏差就要修计划。",
    )

    objectives(nb, [
        "说清「走一步看一步」的 Agent 在复杂任务上会怎么死，尤其是**假成功**那一种",
        "把计划写成结构化数据（`Step` / `Plan`），并解释为什么散文计划不能要",
        "写出**执行前静态校验**：幻觉工具 / 循环依赖 / 缺参数，一步都不许执行",
        "用 `$1.weight_kg` 这种**引用**让数据在步骤之间流动，而不是让模型猜数字",
        "解释「计划为什么不能一次做完」，并实现 失败 → 重规划 → 复用 的闭环",
        "用**工具调用次数**量化计划粒度：粗 / 中 / 细到底差多少",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

第 01~03 章的 Agent 是「走一步看一步」的：想一下 → 调个工具 → 看结果 → 再想。
任务一复杂，它就露出两个毛病：

- **走错方向很晚才发现**：做到第 5 步才发现前提是错的，前 4 步的钱和时间全白花；
- **没法提前检查**：等它真的动手（发短信、扣款、写文件）时，你才知道计划跑不通。

那「先一次性想好全部步骤」行不行？也不行 —— 因为**环境会在计划之后变化**，
而计划里的每一步都是**假设**。

本章按这个顺序拆：

```
① 先看盲执行的两种死法（可运行，不是讲故事）—— 第二种叫「假成功」
② 计划必须是结构化数据            -> 就地讲 dataclass 与步骤指纹
③ 执行前静态校验                  -> 幻觉工具 / 循环依赖 / 缺参数，一步都不跑
④ 参数引用 $1.weight_kg           -> 数据在步骤间流动，而不是让模型猜数字
⑤ 环境变了 -> 失败 -> 重规划       -> 本章的核心闭环
⑥ 重规划要复用，不要重跑           -> 不然客户会收到两条短信
⑦ 计划粒度：不是越细越好           -> 用调用次数把这件事量化
⑧ 常见坑
```

每个知识点都出现在**你正好需要它**的时候，而不是提前堆在开头。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `dataclass` | 标准库 `dataclasses` | 自动生成 `__init__` / `__repr__` 的类装饰器 | `@dataclass` 修饰类；字段写成 `名字: 类型 = 默认值` |
| `field` | 标准库 `dataclasses` | 给字段配默认值（尤其是 list/dict 这种可变默认值） | `field(default_factory=list)` |
| `json.dumps` | 标准库 `json` | Python 对象 → JSON 字符串 | `json.dumps(obj, sort_keys=True)` → `str` |
| `json.loads` | 标准库 `json` | JSON 字符串 → Python 对象 | → `dict` / `list` |
| `re.compile` | 标准库 `re` | 编译正则 | `re.compile(正则)` → `Pattern`；`.match()` 从开头匹配 |
| `re.sub` | 标准库 `re` | 按正则替换 | `re.sub(正则, 替换, 文本)` → `str` |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `ToolRegistry` | `core.tool` | 工具注册表：注册、查找、校验、**安全执行**（内部异常一律转成结果） |
| `ToolResult` | `core.tool` | 工具执行结果：`.ok` / `.content` / `.error` / `.elapsed_ms` |
| `ToolSpec` | `core.tool` | 工具规格：名字 / 描述 / JSON Schema / 函数 / 标签 |

> 本章**故意不用** `core/agent.py`，而是自己写一套最小的 Planner-Executor。
> 理由和刷题一样：自己推一遍，才知道框架替你做了什么。
> 完整版在 `stages/stage04_planning/planner.py`（约 800 行，含全部容错），
> 你可以对照着看"教学版"和"工程版"的差别。

### 随时可查

```python
explain(ToolRegistry)   # 注册表：有哪些方法、怎么用
explain(ToolResult)     # 结果结构：字段逐个说明
explain()               # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "先看盲执行会交出什么报告")

    nb.md("""### 现在卡在哪

第 01~03 章的循环是这样的：模型说一步，我们做一步。
每一步都基于**刚刚看到的结果**，看起来很安全。

问题出在「多步任务」上。举个真实场景：

```
t=0   订单 A1001 状态 = 已发货，重量 2.5kg
      模型据此写出计划：① 算加急运费  ② 拟发货通知  ③ 发给客户

t=1   执行计划 —— 但在这中间，订单被取消了（意料之外，但完全在情理之中）
```

订单被取消不是 bug，是**环境变了**。而计划是 t=0 的产物，它假设订单还是已发货。

### 所以我需要先看清「不做任何保护」会发生什么

执行计划有两种写法，对应两种死法。下面直接跑给你看。""")

    nb.code('''# 单独可运行：盲执行的两种死法 —— 亲眼看到「假成功」
# 场景：给订单 A1001 算加急运费，然后通知客户。
#       计划是在「订单还是已发货」时做的，执行时订单已经被取消了。

# ---- 一个会变的世界：订单系统 ----
ORDER = {"order_id": "A1001", "status": "已取消", "carrier": None,
         "tracking": None, "weight_kg": 2.5, "amount": 328.0}
SENT = []            # 真正发出去的客户通知（副作用账本）


def calc_freight(order_id, weight_kg, speed):
    """算运费。订单已取消时报错 —— 这是业务规则，不是程序 bug。"""
    if ORDER["status"] == "已取消":
        raise ValueError(f"订单 {order_id} 已取消，无法计算运费")
    base = 12.0 if speed == "标准" else 25.0
    return {"freight": round(base + 3.5 * float(weight_kg), 2)}


def draft_reply(order_id, kind, detail=""):
    """生成给客户的通知文案。kind 必须与订单的**真实状态**一致。"""
    want = {"已发货": "shipped", "已取消": "cancelled"}.get(ORDER["status"])
    if kind != want:
        raise ValueError(f"通知类型 {kind!r} 与订单真实状态不符（应该用 {want!r}）")
    return {"text": f"您的订单 {order_id} 已取消。{detail}"}


def send_reply(order_id, text):
    """把文案真正发给客户 —— 副作用，不可撤销。"""
    if ORDER["status"] == "已取消" and "已发货" in text:
        raise ValueError(f"拒绝发送：订单 {order_id} 已取消，但文案声称已发货")
    SENT.append(text)
    return {"sent": True}


TOOLS = {"calc_freight": calc_freight, "draft_reply": draft_reply, "send_reply": send_reply}

# ---- 这份计划是 t=0 做出来的（那时订单还写着「已发货」）----
PLAN = [
    {"id": 1, "goal": "算出加急运费", "tool": "calc_freight",
     "args": {"order_id": "A1001", "weight_kg": 2.5, "speed": "加急"}},
    {"id": 2, "goal": "拟发货通知", "tool": "draft_reply",
     "args": {"order_id": "A1001", "kind": "shipped", "detail": "加急运费 33.75 元"}},
    {"id": 3, "goal": "把通知发给客户", "tool": "send_reply",
     "args": {"order_id": "A1001", "text": "您的订单 A1001 已发货，加急运费 33.75 元。"}},
]

print("【死法 1】异常直接往上抛（最朴素的做法）：")
for step in PLAN:
    try:
        TOOLS[step["tool"]](**step["args"])
    except Exception as exc:
        print(f"   第 {step['id']} 步抛异常，任务中断：{type(exc).__name__}: {exc}")
        break
print("   后果：任务没做完，但**你知道出事了**。")
print()


# ---- 死法 2：每一步都 try/except，出错记一条警告接着跑 ----
def naive_execute(plan):
    """天真执行器：吞掉所有异常，只把警告记在日志里。"""
    warnings = []
    for step in plan:
        try:
            TOOLS[step["tool"]](**step["args"])
        except Exception as exc:
            warnings.append(f"第 {step['id']} 步 {type(exc).__name__}: {exc}")
    return warnings


warnings = naive_execute(PLAN)

print("【死法 2】吞掉异常继续跑（线上更常见）：")
print("   执行器交出的报告 : 任务已完成：已计算加急运费 33.75 元，并已通知客户订单 A1001 已发货。")
print(f"   执行日志里的 WARN : {len(warnings)} 条（没人看，被忽略了）")
for w in warnings:
    print("        -", w)
print(f"   世界里的真实副作用: {SENT}   <- 空列表，一条通知都没发出去")
print()
print("★ 这就叫**假成功**：报告说通知了，客户什么都没收到。")
print("  死法 1 你至少知道出事了；死法 2 会一路骗到线上，且没人发现。")''')

    nb.md("""### 结果说明什么

| 死法 | 表现 | 危害 |
|---|---|---|
| ① 让异常冒出来 | 第二步报错，任务中断 | 至少你知道出事了，前一步的成果也还在 |
| ② **吞掉错误继续跑** | 交出「任务已完成」的报告 | **假成功**：报告说通知了，客户什么都没收到 |

第二种是线上事故的主要来源。**根因只有一个：
计划里的每一步都是假设，而朴素执行器把假设当成了事实。**

### 所以要补上三件事

| 缺什么 | 补什么 | 本章位置 |
|---|---|---|
| 计划是散文，机器没法检查 | 把计划变成**结构化数据** | ② |
| 跑不通的计划照样开跑 | **执行前静态校验** | ③ |
| 环境变了没人管 | **失败 → 重规划** | ⑤ |

先解决第一件：让计划变成机器能读的东西。""")

    # ==================================================================
    section(nb, "②", "计划不是散文：把它变成结构化数据")

    nb.md("""### 现在卡在哪

模型的计划天然是一段自然语言：

```
先查一下订单，然后用订单里的重量算出加急运费，最后发个通知给客户。
```

这段话人能懂，但**程序没法用**：工具名是哪个？参数从哪来？先做哪一步？
想校验「它说的工具存在吗」，只能去猜。

### 所以我需要一个「能装下一步」的结构

| 形态 | 能校验 | 能执行 | 能 diff | 能统计 |
|---|---|---|---|---|
| 一段自然语言 | ✗ | ✗ | ✗ | ✗ |
| 结构化 Step 列表 | ✓ | ✓ | ✓ | ✓ |

一个步骤至少要有四个字段（先记住这四行，够用了）：

```python
Step(id=2, goal="用订单里的重量算出加急运费",
     tool="calc_freight",
     args={"weight_kg": "$1.weight_kg", "speed": "加急"},
     depends_on=[1])
```

| 字段 | 作用 | 少了它会怎样 |
|---|---|---|
| `id` | 步骤编号，后面的步骤靠它引用 | 没法表达「第 2 步依赖第 1 步」 |
| `goal` | 这一步要达成什么 | 重规划时模型不知道哪条假设破了 |
| `tool` + `args` | 用什么工具、传什么参数 | 没法校验，也没法执行 |
| `depends_on` | 依赖哪些步骤 | 执行顺序不确定，失败时不知道谁会受牵连 |

### 它的用法

Python 里装「一组固定字段」最顺手的工具是 `dataclasses`：

```python
from dataclasses import dataclass, field

@dataclass                 # 装饰器：自动帮你生成 __init__ / __repr__
class Step:
    id: int                # 带类型注解的类属性 = 字段
    args: dict = field(default_factory=dict)   # 可变默认值必须用 field(...)
```

★ `field(default_factory=dict)` 这个写法看起来罗嗦，但它是**必须的**：
写成 `args: dict = {}` 会让所有实例共用同一个字典 —— 改一个步骤的参数，
其它步骤跟着一起变。这是 Python 最经典的坑之一。

### 立刻用一次""")

    nb.code('''# 单独可运行：把计划变成结构化数据 —— Step / Plan
from dataclasses import dataclass, field
import json


@dataclass
class Step:
    """计划里的一步。字段就是「执行器需要知道的全部信息」。

    id          : 步骤编号，从 1 开始；后面的步骤靠它引用
    goal        : 这一步要达成什么（写给人看，也写给重规划的模型看）
    tool        : 用哪个工具
    args        : 工具参数；值可以写成 "$1.weight_kg" 这种引用
    depends_on  : 依赖哪些步骤（决定顺序，也决定失败时谁会受牵连）
    status      : pending / done / failed / blocked
    result      : 工具返回的**结构化**结果（供后续步骤引用）
    observation : 工具返回的文本（喂给人和模型）
    error       : 失败原因
    """
    id: int
    goal: str
    tool: str = ""
    args: dict = field(default_factory=dict)          # <- 必须用 field()，见正文
    depends_on: list = field(default_factory=list)    # <- 同上
    status: str = "pending"
    result: object = None
    observation: str = ""
    error: str = ""

    @property
    def signature(self) -> str:
        """步骤指纹 = 工具名 + 参数的规范 JSON。

        sort_keys=True 很关键：参数的字典顺序不影响指纹，
        所以「同样的调用」不管模型怎么排版都得到同一个指纹 ——
        重规划时靠它判断某一步是不是已经做过了。
        """
        args = json.dumps(self.args, sort_keys=True, ensure_ascii=False, default=str)
        return f"{self.tool}({args})"

    def line(self) -> str:
        """渲染成一行（教学用；线上应该输出 JSON，方便日志系统解析）。"""
        mark = {"pending": "待办", "done": "完成", "failed": "失败", "blocked": "阻塞"}[self.status]
        dep = f"  <- 依赖 {self.depends_on}" if self.depends_on else ""
        head = f"[{mark}] {self.id}. {self.goal}{dep}"
        if self.observation:
            head += f"\\n         结果: {self.observation[:56]}"
        if self.error:
            head += f"\\n         错误: {self.error[:56]}"
        return head


@dataclass
class Plan:
    """一版计划。version 从 1 开始，每重规划一次 +1 —— 有版本号才能 diff。"""
    version: int
    steps: list
    reason: str = ""

    def get(self, sid: int):
        """按 id 找某一步（找不到返回 None，而不是抛异常）。"""
        return next((s for s in self.steps if s.id == sid), None)

    @property
    def done_signatures(self) -> dict:
        """已成功步骤的「指纹 -> 步骤」表 —— 重规划时用它避免重复执行。"""
        return {s.signature: s for s in self.steps if s.status == "done"}

    def render(self) -> str:
        head = f"计划 v{self.version}" + (f"（{self.reason}）" if self.reason else "")
        return "\\n".join([head] + [s.line() for s in self.steps])


# ---- 立刻用一次：写一份 3 步计划并渲染出来 ----
plan = Plan(version=1, reason="初始计划", steps=[
    Step(1, "查询订单 A1001 的真实状态与重量", "lookup_order",
         {"order_id": "A1001"}),
    Step(2, "用订单里的重量算出加急运费", "calc_freight",
         {"order_id": "$1.order_id", "weight_kg": "$1.weight_kg", "speed": "加急"},
         depends_on=[1]),
    Step(3, "把通知真正发给客户", "send_reply",
         {"order_id": "$1.order_id", "text": "$2.text"},
         depends_on=[2]),
])

print(plan.render())
print()
print("第 2 步的指纹 :", plan.steps[1].signature)
print("第 2 步依赖谁 :", plan.steps[1].depends_on)
print()
print("★ 注意 args 里的 $1.order_id：参数不是模型猜的，")
print("  而是从第 1 步的**真实结果**里取的。这一行设计 ④ 节单独讲。")''')

    nb.md("""### 结果说明什么

- 计划现在是一个**对象**：`plan.steps` 可以遍历，`plan.get(2)` 可以查，
  `plan.done_signatures` 可以统计 —— 这些能力自然语言计划一个都没有。
- `signature`（指纹）现在是「工具名 + 参数」的规范字符串。
  它后面要干两件大事：**判重**（⑥ 节）和**复用**（⑥ 节）。
- `version` 让「重规划改了什么」变成可 diff 的：v1 → v2 到底改了哪几步，一眼可见。

现在计划能被程序读了。下一个问题：**它跑得通吗？**""")

    # ==================================================================
    section(nb, "③", "执行前静态校验：跑不通的计划一步都不执行")

    nb.md("""### 现在卡在哪

模型写计划时**还没看到任何真实反馈**（这正是规划与 ReAct 的区别），
所以它在规划期编造工具名的概率**比执行期更高**。三种典型毛病：

| 毛病 | 例子 | 如果不拦 |
|---|---|---|
| 幻觉工具 | `tool: "search_web"`，而你没这个工具 | 跑到那一步才发现，前面的步骤白做 |
| 循环依赖 | 第 1 步依赖第 2 步，第 2 步依赖第 1 步 | 执行顺序无法确定，两边互相等 |
| 参数不全 / 多余 | 缺 `weight_kg`；多传一个 `unit` | 工具报 `TypeError`，模型看不懂 |

**关键认识：执行计划的代价是真实副作用。** 发出去的短信、扣掉的钱，
你是没法 ctrl+Z 的。所以检查必须**前移**：

```
   计划期（便宜，能提前发现问题）        执行期（昂贵，副作用不可撤销）
   ----------------------------        ------------------------------
   工具名是否存在                        参数值是否合法（weight_kg 真是数字吗）
   依赖是否成环                          业务规则是否满足（订单取消了吗）
   必填参数是否齐全                      环境是否变化（假设还成立吗）
   查不出「值对不对」
```

一句话：**能静态拦下的，绝不拖到执行期。**

### 所以我需要一个「只查结构、不碰副作用」的函数

### 它的用法

```python
validate_plan(steps, tools) -> list[str]
    steps : list[Step]，要检查的计划
    tools : ToolRegistry，可用工具（第 02 章的注册表，能告诉你 schema）
    返回   : 问题描述列表 —— **空列表 = 计划合法**
```

三个设计决定值得单独说：

1. **一次收集全部问题**，而不是遇到第一个就返回 —— 每轮反馈都花一次模型调用，
   一次给全，模型一次改对；
2. **依赖只允许指向更小的编号**：这一条一石二鸟，既挡住「依赖不存在的步骤」，
   也天然挡住循环依赖（A 等 B、B 等 A 时，必然有一个依赖指向更大的编号）；
3. 返回**问题列表**而不是抛异常 —— 调用方不需要写 try。

### 立刻用一次""")

    nb.code('''# 单独可运行：执行前静态校验 —— 跑不通的计划一步都不执行
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.tool import ToolRegistry


@dataclass
class Step:
    """和上一格同一个结构（这里只留校验需要的字段，便于聚焦）。"""
    id: int
    goal: str
    tool: str = ""
    args: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)


def build_tools() -> ToolRegistry:
    """造一套工具。schema 就是「参数契约」（第 02 章讲过），校验全靠它。"""
    reg = ToolRegistry()

    @reg.tool(
        "lookup_order",
        "查询订单的当前状态、承运商、重量。任何涉及订单的任务都应该先调用它。",
        {"type": "object",
         "properties": {"order_id": {"type": "string", "description": "订单号，例如 A1001"}},
         "required": ["order_id"], "additionalProperties": False},
        tags=["read"],
    )
    def lookup_order(order_id: str) -> dict:
        return {"order_id": order_id.upper(), "status": "已发货", "weight_kg": 2.5}

    @reg.tool(
        "calc_freight",
        "计算运费。需要订单号、重量与时效；订单已取消时无法计算。",
        {"type": "object",
         "properties": {"order_id": {"type": "string"},
                        "weight_kg": {"type": "number", "minimum": 0},
                        "speed": {"type": "string", "enum": ["标准", "加急"]}},
         "required": ["order_id", "weight_kg", "speed"], "additionalProperties": False},
        tags=["compute"],
    )
    def calc_freight(order_id: str, weight_kg: float, speed: str) -> dict:
        return {"freight": round((12.0 if speed == "标准" else 25.0) + 3.5 * float(weight_kg), 2)}

    return reg


def validate_plan(steps, tools) -> list:
    """返回问题列表（空列表 = 计划合法）。**一次收集全部问题**，减少来回次数。

    参数 steps：list[Step]，要检查的计划
         tools：ToolRegistry，可用工具
    返回      ：list[str]，每条是一句人能读懂、模型也能照做的问题描述
    """
    problems = []
    ids = [s.id for s in steps]

    if not steps:
        problems.append("计划为空：至少要有一步")

    # names() 返回排序后的工具名列表；get(name) 返回 ToolSpec（含 parameters）
    known = set(tools.names())

    for s in steps:
        # ① 工具必须真实存在（模型很爱编工具名，规划期尤其常见）
        if not s.tool:
            problems.append(f"第 {s.id} 步没有指定工具")
        elif s.tool not in known:
            problems.append(f"第 {s.id} 步用了不存在的工具 {s.tool!r}，可用工具：{sorted(known)}")
        else:
            # ② 参数必须符合 schema —— 只查「齐不齐 / 多不多」，不查值对不对
            schema = tools.get(s.tool).parameters
            props = set(schema.get("properties", {}))
            required = set(schema.get("required", []))
            missing = sorted(required - set(s.args))
            extra = sorted(set(s.args) - props)
            if missing:
                problems.append(f"第 {s.id} 步缺少必填参数 {missing}（工具 {s.tool}）")
            if extra:
                problems.append(f"第 {s.id} 步出现未定义参数 {extra}（工具 {s.tool} 只接受 {sorted(props)}）")

        # ③ 依赖只能指向**本计划里更小的编号**：
        #    既挡住「依赖不存在的步骤」，也天然挡住循环依赖
        for d in s.depends_on:
            if d == s.id:
                problems.append(f"第 {s.id} 步依赖了自己")
            elif d not in ids:
                problems.append(f"第 {s.id} 步依赖了不存在的步骤 {d}")
            elif d > s.id:
                problems.append(f"第 {s.id} 步依赖了后面的第 {d} 步 —— 依赖只能指向更小的编号")

    return problems


reg = build_tools()
print("可用工具：", reg.names())
print()

BAD_PLANS = {
    "幻觉工具": [Step(1, "上网搜一下订单", "search_web", {"q": "订单 A1001"})],
    "循环依赖": [
        Step(1, "先做第二步", "lookup_order", {"order_id": "A1001"}, depends_on=[2]),
        Step(2, "再做第一步", "calc_freight",
             {"order_id": "A1001", "weight_kg": 2.5, "speed": "加急"}, depends_on=[1]),
    ],
    "缺必填参数": [Step(1, "算运费", "calc_freight", {"order_id": "A1001", "speed": "加急"})],
    "多个幻觉参数": [Step(1, "算运费", "calc_freight",
                     {"order_id": "A1001", "weight_kg": 2.5, "speed": "加急", "unit": "元"})],
}

for label, steps in BAD_PLANS.items():
    problems = validate_plan(steps, reg)
    print(f"[{label}] 发现 {len(problems)} 个问题 -> 拒绝执行（执行步数 0）")
    for p in problems:
        print("      -", p)

print()
print("★ 上面四份坏计划**一步都没有进入执行阶段**，所以一个副作用都没产生。")
print("  对比 ① 节的盲执行：那里是跑到一半才发现，这里是压根不让它跑。")''')

    nb.md("""### 结果说明什么

- 四种毛病全部在**执行之前**被拦下，副作用为零；
- 每条错误信息都写了「第几步 + 哪里错 + 正确用法」，这是**写给模型看的**，
  它看到就能改（第 02 章的同一条原则）；
- 「循环依赖」是被 ③ 号规则**顺带**拦住的 —— 我们没有专门写环检测代码。
  **一条更严格的规则，往往比一个专门的检查器更省事。**

### 但静态校验有个明确的能力边界

它查不出「值对不对」。举例：模型把重量单位搞错，写成 `weight_kg=250`
（其实是 250 克），静态校验完全合法，只有业务规则和范围校验拦得住
（`"minimum": 0` 也拦不住 250）。

**所以执行期仍然需要兜底**：有副作用的步骤，执行前必须再校验一次前置条件。
⑤ 节会看到这个兜底怎么救场。

现在计划能被执行了。但还有个更隐蔽的问题：**参数里的值从哪来？**""")

    # ==================================================================
    section(nb, "④", "让数据在步骤之间流动：引用语法")

    nb.md("""### 现在卡在哪

看第 2 步的参数：

```python
{"weight_kg": ???}     # 重量是多少？模型并不知道，它只在计划里"见过"第 1 步的目标
```

真实模型在这里只有两条路：

1. **猜一个数字**写进去（`weight_kg: 2.5`）—— 这就是**幻觉的发源地**。
   等执行时订单重量变成 3.8，这个数字就是错的，而且没人发现；
2. 或者写一句「用第 1 步的重量」，但那是自然语言，程序没法执行。

### 所以我需要一种「在参数里引用上游结果」的语法

约定很简单：

```
$<步骤号>.<字段名>        例如  $1.weight_kg
```

它有两种用法，**用途不同**：

| 写法 | 输入 | 输出 | 什么时候用 |
|---|---|---|---|
| 整个参数就是一个引用 | `"$1.weight_kg"` | `2.5`（**保留原始类型**，数字还是数字） | 把上游的数字/对象直接传给下一步 |
| 字符串内插值 | `"运单号 $1.tracking，请查收"` | `"运单号 SF1234567890，请查收"` | 拼一句话 |

### 它的用法

用两个正则区分这两种情况：

```python
_REF_EXACT_RE = re.compile(r"^\\$(\\d+)\\.([\\w\\.]+)$")   # 整串就是一个引用
_REF_ANY_RE   = re.compile(r"\\$(\\d+)\\.([\\w\\.]+)")     # 字符串里出现引用
```

逐个部分说清：

| 部分 | 含义 |
|---|---|
| `\\$` | 转义：`$` 在正则里是「字符串结尾」的元字符，加 `\\` 才是普通字符 |
| `(\\d+)` | 第 1 个捕获组：步骤号（一个或多个数字） |
| `\\.` | 字面的那个点（`.` 在正则里是「任意字符」，必须转义） |
| `([\\w\\.]+)` | 第 2 个捕获组：字段路径，允许 `a.b` 这种嵌套 |
| `^...$` | 首尾锚定：**整串必须完全匹配**才是「纯引用」 |
| `re.sub` | 把匹配到的每一处替换掉（内插值用） |

### 立刻用一次""")

    nb.code('''# 单独可运行：参数引用 —— 让数据在步骤之间流动
import re

# 整串就是一个引用（首尾有 ^ 和 $）
_REF_EXACT_RE = re.compile(r"^\\$(\\d+)\\.([\\w\\.]+)$")
# 字符串里任意位置出现的引用（用于内插值）
_REF_ANY_RE = re.compile(r"\\$(\\d+)\\.([\\w\\.]+)")


class RefError(Exception):
    """引用解析失败。

    它的真实含义不是「参数错了」，而是：**上游结果和计划的假设不一致**。
    所以它应该触发重规划，而不是让执行器崩掉 —— 这个区别 ⑤ 节会用到。
    """


def _lookup_ref(done: dict, sid: int, path: str, key: str, raw: str):
    """从第 sid 步的结果里，按 path 取出值。

    参数 done：{步骤号: 结构化结果}，只包含**已成功完成**的步骤
         sid ：要引用的步骤号
         path：字段路径，支持 "a.b" 这种嵌套
         key ：出错信息里显示「哪个参数」出了问题（便于模型定位）
         raw ：原始引用字符串（便于模型看懂自己写了什么）
    返回    ：取到的值（类型原样保留）
    """
    if sid not in done:
        raise RefError(f"参数 {key}={raw!r} 引用了还没成功完成的第 {sid} 步")
    data = done[sid]
    for part in path.split("."):
        if isinstance(data, dict) and part in data:
            data = data[part]                      # 往里走一层
        else:
            avail = sorted(data) if isinstance(data, dict) else type(data).__name__
            raise RefError(f"参数 {key}={raw!r} 无法解析：第 {sid} 步的结果里没有 {path!r}"
                           f"（可用的键：{avail}）")
    return data


def resolve_args(args: dict, done: dict) -> dict:
    """把参数里的引用换成真实值。

    参数 args：步骤的参数字典，值可能是 "$1.weight_kg" 这种字符串
         done：{步骤号: 结构化结果}
    返回    ：新字典（不改原字典）；解析失败抛 RefError
    """
    out = {}
    for key, value in args.items():
        if not isinstance(value, str):        # 数字/布尔等原样透传
            out[key] = value
            continue

        m = _REF_EXACT_RE.match(value.strip())    # ① 整串就是一个引用
        if m:
            out[key] = _lookup_ref(done, int(m.group(1)), m.group(2), key, value)
            continue

        if "$" in value:                          # ② 字符串内插值
            out[key] = _REF_ANY_RE.sub(
                lambda mm: str(_lookup_ref(done, int(mm.group(1)), mm.group(2), key, value)),
                value,
            )
            continue

        out[key] = value                          # ③ 普通字符串（例如 "加急"），原样透传
    return out


# ---- 第 1 步的真实结果（执行完之后才知道）----
DONE = {1: {"order_id": "A1001", "weight_kg": 2.5, "tracking": "SF1234567890"}}

print("① 整串是引用（注意类型被完整保留）：")
got = resolve_args({"order_id": "$1.order_id", "weight_kg": "$1.weight_kg", "speed": "加急"}, DONE)
print("   ", got)
print(f"    weight_kg 的类型 = {type(got['weight_kg']).__name__}  <- 还是数字，不是字符串")
print()

print("② 字符串内插值：")
print("   ", resolve_args({"text": "运单号 $1.tracking，请查收"}, DONE))
print()

print("③ 失败模式（引用解析不了 -> 抛 RefError，交给重规划）：")
for bad in [{"weight_kg": "$2.weight_kg"},        # 第 2 步还没跑完
            {"weight_kg": "$1.color"},            # 字段不存在
            {"text": "重量 $1.color 公斤"}]:       # 内插值里的引用同样会被检查
    try:
        print("   没拦住:", resolve_args(bad, DONE))
    except RefError as exc:
        print("   RefError:", exc)
print()
print("★ 为什么值得为它设计一套语法？")
print("  没有它，模型只能把 weight_kg **猜**出来写死进计划 —— 那就是幻觉的发源地。")
print("  有了它，计划只描述「从哪取」，真实值永远来自真实结果。")''')

    nb.md("""### 结果说明什么

- 纯引用保留了**原始类型**：`weight_kg` 是 `float` 而不是字符串 `\"2.5\"`。
  如果这里退化成字符串，工具的参数校验会立刻报类型错误 —— 一个很容易踩的坑；
- 内插值适合拼文本（文案、日志、邮件正文）；
- 失败时抛的是 `RefError`，而且信息里带上了**可用的键** ——
  模型看到 `可用的键：['order_id', 'status', 'weight_kg', ...]` 就知道该改成什么。

现在零件齐了：结构化计划 + 静态校验 + 引用解析。
**把它们串起来，就能对付「环境变了」。**""")

    # ==================================================================
    section(nb, "⑤", "环境变了：失败 → 重规划")

    nb.md("""### 现在卡在哪

回到 ① 节的场景：计划是 t=0 做的，执行时订单已经被取消。
现在我们知道第 2 步会失败 —— 然后呢？

有三种处理方式，只有一种是及格的：

| 做法 | 结果 |
|---|---|
| 抛异常，整个任务崩掉 | 前 1 步白做，用户看到 500 |
| 吞掉异常继续跑 | **假成功**（① 节的死法 2） |
| **带着失败原因重新规划** | 任务继续，而且改走正确的路 |

### 所以我需要一个「确定性执行器 + 会改计划的规划器」

这里有一个容易被忽略的分工原则：

```
   Planner    模型，不确定   ->  产出步骤列表（假设）
   Executor   **纯代码，确定性** ->  逐步执行，交出真实结果（验证）
   Replanner  模型，不确定   ->  带着真实结果和失败原因改写计划
```

**为什么 Executor 必须是确定性代码？** 因为可归因。
计划可以错，但「按计划执行」这件事不允许有随机性 ——
否则你永远分不清失败是**计划的锅**还是**执行的锅**。

### 它的用法

执行器每一步都要问三个问题：

```
   ① 依赖满足了吗？   -> 不满足：标 blocked，触发重规划（而不是硬跑出错误结果）
   ② 引用能解析吗？   -> 解析不了：说明上游结果和计划假设不一致，触发重规划
   ③ 工具成功了吗？   -> 失败：带着**原始错误**触发重规划
```

而重规划的提示词必须有**三块**，缺一不可：

```
   # 任务        <- 原始任务（不带它，模型会忘记最初要干什么）
   # 现状        <- 上一版计划 + 每步的真实结果（这些是已验证的事实）
   # 失败点      <- 第几步失败、原因是什么（这是重规划的唯一理由）
```

> 只给模型一句「失败了，重新规划吧」是没用的：它不知道**哪条假设错了**，
> 只会把同一份计划再写一遍 —— 这是重规划最常见的失败形态。

### 立刻用一次""")

    nb.code('''# 单独可运行：确定性执行器 —— 失败变成「带原因的结果」，不是崩溃
import sys, pathlib, json
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.tool import ToolRegistry

# ---------------- 会变的世界 ----------------
ORDER = {"order_id": "A1001", "status": "已取消", "carrier": None,
         "tracking": None, "weight_kg": 2.5, "amount": 328.0}
CALLS = []          # 每次工具调用记一笔（**这里的工具调用次数就是钱**）

def make_tools() -> ToolRegistry:
    """把订单系统包装成工具。异常由注册表兜住（第 02 章的能力，白拿）。"""
    reg = ToolRegistry()

    @reg.tool("lookup_order", "查询订单状态、承运商、运单号、重量。",
              {"type": "object",
               "properties": {"order_id": {"type": "string"}},
               "required": ["order_id"], "additionalProperties": False}, tags=["read"])
    def lookup_order(order_id: str) -> dict:
        CALLS.append("lookup_order")
        return dict(ORDER)

    @reg.tool("calc_freight", "计算运费。订单已取消时无法计算。",
              {"type": "object",
               "properties": {"order_id": {"type": "string"},
                              "weight_kg": {"type": "number"},
                              "speed": {"type": "string", "enum": ["标准", "加急"]}},
               "required": ["order_id", "weight_kg", "speed"],
               "additionalProperties": False}, tags=["compute"])
    def calc_freight(order_id: str, weight_kg: float, speed: str) -> dict:
        CALLS.append("calc_freight")
        if ORDER["status"] == "已取消":
            raise ValueError(f"订单 {order_id} 已取消，无法计算运费")
        return {"freight": round(25.0 + 3.5 * float(weight_kg), 2)}

    return reg


# ---------------- 计划的数据结构（与 ② 节同一套，精简版）----------------
@dataclass
class Step:
    id: int
    goal: str
    tool: str = ""
    args: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    status: str = "pending"
    result: object = None
    observation: str = ""
    error: str = ""

    @property
    def signature(self) -> str:
        return f"{self.tool}({json.dumps(self.args, sort_keys=True, ensure_ascii=False, default=str)})"


# ---------------- 参数引用（与 ④ 节同一套）----------------
import re
_REF_EXACT_RE = re.compile(r"^\\$(\\d+)\\.([\\w\\.]+)$")
_REF_ANY_RE = re.compile(r"\\$(\\d+)\\.([\\w\\.]+)")

class RefError(Exception):
    """引用解析失败 = 上游结果与计划假设不一致 -> 触发重规划。"""

def resolve_args(args, done):
    out = {}
    for key, value in args.items():
        if not isinstance(value, str):
            out[key] = value
            continue
        m = _REF_EXACT_RE.match(value.strip())
        if m:
            sid, path = int(m.group(1)), m.group(2)
            if sid not in done:
                raise RefError(f"参数 {key}={value!r} 引用了未成功的第 {sid} 步")
            data = done[sid]
            for part in path.split("."):
                if isinstance(data, dict) and part in data:
                    data = data[part]
                else:
                    raise RefError(f"参数 {key}={value!r} 无法解析：第 {sid} 步结果里没有 {path!r}")
            out[key] = data
            continue
        if "$" in value:
            def _sub(mm):
                sid, path = int(mm.group(1)), mm.group(2)
                if sid not in done:
                    raise RefError(f"参数 {key}={value!r} 引用了未成功的第 {sid} 步")
                data = done[sid]
                for part in path.split("."):
                    data = data[part] if isinstance(data, dict) and part in data else None
                return str(data)
            out[key] = _REF_ANY_RE.sub(_sub, value)
            continue
        out[key] = value
    return out


# ---------------- 执行器：三个检查点，一步都不马虎 ----------------
def execute(steps, tools, verbose=True):
    """逐步执行。返回 None = 全部成功；否则返回 (失败的步骤, 原因)。"""
    for step in steps:
        if step.status == "done":
            if verbose:
                print(f"   [跳过] 第 {step.id} 步已完成，复用上一版的结果")
            continue

        # ① 依赖检查：不满足就 blocked（而不是硬跑出错误的中间结果）
        unmet = [d for d in step.depends_on
                 if (dep := next((s for s in steps if s.id == d), None)) is None
                 or dep.status != "done"]
        if unmet:
            step.status, step.error = "blocked", f"依赖未满足：第 {unmet} 步没有成功完成"
            if verbose:
                print(f"   [阻塞] 第 {step.id} 步：{step.error}")
            return step, step.error

        # ② 引用解析：解析不了说明上游结果和计划假设不一致
        done = {s.id: s.result for s in steps if s.status == "done"}
        try:
            args = resolve_args(step.args, done)
        except RefError as exc:
            step.status, step.error = "failed", str(exc)
            if verbose:
                print(f"   [失败] 第 {step.id} 步参数无法解析：{exc}")
            return step, f"计划里的参数引用与真实结果不一致：{exc}"

        # ③ 执行工具：注册表保证「工具内部异常也变成结果」，绝不会抛出来
        r = tools.execute(step.tool, args)
        if r.ok:
            step.status, step.observation = "done", r.content
            # 结果能反序列化成结构体就反序列化 —— 后续步骤要靠字段引用取数据
            step.result = json.loads(r.content) if r.content.startswith("{") else r.content
            if verbose:
                print(f"   [完成] 第 {step.id} 步：{step.goal}")
                print(f"          {step.tool} -> {r.content[:60]}")
        else:
            step.status, step.error = "failed", (r.error or r.content)
            if verbose:
                print(f"   [失败] 第 {step.id} 步：{step.goal}")
                print(f"          {step.tool} -> {step.error[:70]}")
            return step, step.error
    return None


# ---------------- 跑一次：看失败是怎么被「交出来」的 ----------------
tools = make_tools()
steps = [
    Step(1, "查询订单 A1001 的真实状态与重量", "lookup_order", {"order_id": "A1001"}),
    Step(2, "用订单里的重量算出加急运费", "calc_freight",
         {"order_id": "$1.order_id", "weight_kg": "$1.weight_kg", "speed": "加急"}, [1]),
    Step(3, "把通知真正发给客户", "send_reply", {"text": "$2.货运单"}),   # 故意引用一个不存在的字段
]

print("执行计划 v1：")
outcome = execute(steps, tools)
print()
if outcome is None:
    print("全部成功")
else:
    failed, reason = outcome
    print(f"执行器交回的是：第 {failed.id} 步失败，原因 = {reason}")
print()
print("★ 注意它没有抛异常，而是把「哪一步失败 + 为什么」原样交回给调用方。")
print("  调用方拿着这两样东西，就能去找 Replanner 了。")
print(f"★ 真实发生的工具调用：{CALLS}（{len(CALLS)} 次）")
print("  第 3 步因为引用不存在的字段，**根本没有执行** —— 所以没产生任何副作用。")''')

    nb.md("""### 结果说明什么

- 失败被**结构化**地交了出来：`(哪一步, 为什么)`。调用方不需要解析字符串；
- 第 2 步失败之后，第 3 步**没有再执行** —— 这就是「不检查就继续跑」和
  「检查后停下」的差别；
- 工具内部的 `ValueError` 被注册表转成了 `r.ok = False`，
  执行器拿到的是一个**结果**而不是异常（第 02 章的能力，这里直接白拿）。

现在把 Replanner 接上，闭环就完成了。""")

    nb.code('''# 单独可运行：失败 -> 重规划 -> 复用 -> 完成（本章的核心闭环）
import sys, pathlib, json, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.tool import ToolRegistry

REPLAN_BUDGET = 2        # ← 试着改这里：改成 0，看停机原因会变成什么


# ======================= 1. 会变的世界 =======================
class World:
    """订单系统 + 几个有副作用的动作。所有调用都被记账（调用次数 = 钱）。"""

    def __init__(self, cancel: bool = False) -> None:
        self.order = {"order_id": "A1001",
                      "status": "已取消" if cancel else "已发货",
                      "carrier": None if cancel else "顺丰",
                      "tracking": None if cancel else "SF1234567890",
                      "weight_kg": 2.5, "amount": 328.0}
        self.calls = []        # 每次工具调用记一笔（含失败）
        self.sent = []         # 真正发出去的客户通知
        self.refunds = {}

    def build_tools(self) -> ToolRegistry:
        reg, w = ToolRegistry(), self

        @reg.tool("lookup_order", "查询订单状态、承运商、运单号、重量。任何涉及订单的任务都先调它。",
                  {"type": "object", "properties": {"order_id": {"type": "string"}},
                   "required": ["order_id"], "additionalProperties": False}, tags=["read"])
        def lookup_order(order_id: str) -> dict:
            w.calls.append("lookup_order")
            return dict(w.order)

        @reg.tool("calc_freight", "计算运费。订单已取消时无法计算。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"},
                                  "weight_kg": {"type": "number", "minimum": 0},
                                  "speed": {"type": "string", "enum": ["标准", "加急"]}},
                   "required": ["order_id", "weight_kg", "speed"],
                   "additionalProperties": False}, tags=["compute"])
        def calc_freight(order_id: str, weight_kg: float, speed: str) -> dict:
            w.calls.append("calc_freight")
            if w.order["status"] == "已取消":
                raise ValueError(f"订单 {order_id} 已取消，无法计算运费")
            base = 12.0 if speed == "标准" else 25.0
            return {"order_id": order_id.upper(), "speed": speed,
                    "freight": round(base + 3.5 * float(weight_kg), 2)}

        @reg.tool("query_refund", "查询订单的退款状态与金额（订单取消后用它）。",
                  {"type": "object", "properties": {"order_id": {"type": "string"}},
                   "required": ["order_id"], "additionalProperties": False}, tags=["read"])
        def query_refund(order_id: str) -> dict:
            w.calls.append("query_refund")
            if w.order["status"] != "已取消":
                raise ValueError(f"订单 {order_id} 未取消，没有退款记录")
            info = w.refunds.setdefault(order_id.upper(),
                                        {"status": "退款处理中", "amount": w.order["amount"]})
            return dict(info)

        @reg.tool("draft_reply", "按订单**真实状态**生成通知文案：已发货->shipped，已取消->cancelled。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"},
                                  "kind": {"type": "string", "enum": ["shipped", "cancelled"]},
                                  "detail": {"type": "string"}},
                   "required": ["order_id", "kind"],
                   "additionalProperties": False}, tags=["write"])
        def draft_reply(order_id: str, kind: str, detail: str = "") -> dict:
            w.calls.append("draft_reply")
            want = {"已发货": "shipped", "已取消": "cancelled"}.get(w.order["status"])
            if kind != want:
                # 这条错误就是「计划里的假设已经过期」的信号，必须原样回灌给 Replanner
                raise ValueError(f"通知类型 {kind!r} 与订单真实状态不符（应该用 {want!r}）")
            if kind == "shipped":
                text = f"您的订单 {order_id} 已发货，运单号 {w.order['tracking']}。{detail}"
            else:
                text = f"您的订单 {order_id} 已取消。{detail}"
            return {"kind": kind, "text": text.strip()}

        @reg.tool("send_reply", "把通知真正发给客户（**有副作用，不可撤销**）。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"},
                                  "text": {"type": "string", "minLength": 1}},
                   "required": ["order_id", "text"],
                   "additionalProperties": False}, tags=["write"])
        def send_reply(order_id: str, text: str) -> dict:
            w.calls.append("send_reply")
            # ★ 兜底护栏：即使上游的计划全错，也不允许把错误信息发给客户。
            #   这就是 ③ 节说的「有副作用的步骤，执行前再校验一次前置条件」。
            if w.order["status"] == "已取消" and "已发货" in text:
                raise ValueError(f"拒绝发送：订单 {order_id} 已取消，但文案声称已发货")
            w.sent.append(text)
            return {"sent": True, "chars": len(text)}

        return reg


# ======================= 2. 计划与执行（与 ②③④ 节同一套）=======================
@dataclass
class Step:
    id: int
    goal: str
    tool: str = ""
    args: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    status: str = "pending"
    result: object = None
    observation: str = ""
    error: str = ""

    @property
    def signature(self) -> str:
        return f"{self.tool}({json.dumps(self.args, sort_keys=True, ensure_ascii=False, default=str)})"

    def line(self) -> str:
        mark = {"pending": "待办", "done": "完成", "failed": "失败", "blocked": "阻塞"}[self.status]
        dep = f"  <- 依赖 {self.depends_on}" if self.depends_on else ""
        body = f"[{mark}] {self.id}. {self.goal}{dep}"
        if self.observation:
            body += f"\\n         结果: {self.observation[:52]}"
        if self.error:
            body += f"\\n         错误: {self.error[:52]}"
        return body


@dataclass
class Plan:
    version: int
    steps: list
    reason: str = ""

    def render(self) -> str:
        head = f"计划 v{self.version}" + (f"（{self.reason}）" if self.reason else "")
        return "\\n".join([head] + [s.line() for s in self.steps])

    @property
    def done_signatures(self) -> dict:
        return {s.signature: s for s in self.steps if s.status == "done"}


_REF_EXACT_RE = re.compile(r"^\\$(\\d+)\\.([\\w\\.]+)$")
_REF_ANY_RE = re.compile(r"\\$(\\d+)\\.([\\w\\.]+)")


class RefError(Exception):
    pass


def resolve_args(args, done):
    out = {}
    for key, value in args.items():
        if not isinstance(value, str):
            out[key] = value
            continue
        m = _REF_EXACT_RE.match(value.strip())
        if m:
            sid, path = int(m.group(1)), m.group(2)
            if sid not in done:
                raise RefError(f"参数 {key}={value!r} 引用了未成功的第 {sid} 步")
            data = done[sid]
            for part in path.split("."):
                if isinstance(data, dict) and part in data:
                    data = data[part]
                else:
                    raise RefError(f"参数 {key}={value!r} 无法解析：没有 {path!r}")
            out[key] = data
            continue
        if "$" in value:
            def _sub(mm):
                sid, path = int(mm.group(1)), mm.group(2)
                if sid not in done:
                    raise RefError(f"参数 {key}={value!r} 引用了未成功的第 {sid} 步")
                data = done[sid]
                for part in path.split("."):
                    data = data[part] if isinstance(data, dict) and part in data else None
                return str(data)
            out[key] = _REF_ANY_RE.sub(_sub, value)
            continue
        out[key] = value
    return out


def validate_plan(steps, tools) -> list:
    """执行前的静态校验（③ 节的精简版）。跑不通的计划一步都不执行。"""
    problems, ids = [], [s.id for s in steps]
    known = set(tools.names())
    for s in steps:
        if s.tool not in known:
            problems.append(f"第 {s.id} 步用了不存在的工具 {s.tool!r}，可用工具：{sorted(known)}")
            continue
        schema = tools.get(s.tool).parameters
        missing = sorted(set(schema.get("required", [])) - set(s.args))
        extra = sorted(set(s.args) - set(schema.get("properties", {})))
        if missing:
            problems.append(f"第 {s.id} 步缺少必填参数 {missing}（工具 {s.tool}）")
        if extra:
            problems.append(f"第 {s.id} 步出现未定义参数 {extra}（工具 {s.tool}）")
        for d in s.depends_on:
            if d not in ids:
                problems.append(f"第 {s.id} 步依赖了不存在的步骤 {d}")
            elif d > s.id:
                problems.append(f"第 {s.id} 步依赖了后面的第 {d} 步")
    return problems


def execute_steps(steps, tools, verbose=True):
    """逐步执行。返回 None 表示全部成功；否则返回 (失败的步骤, 原因)。"""
    for step in steps:
        if step.status == "done":
            if verbose:
                print(f"   [跳过] 第 {step.id} 步已完成，复用上一版的结果")
            continue
        unmet = [d for d in step.depends_on
                 if (dep := next((s for s in steps if s.id == d), None)) is None
                 or dep.status != "done"]
        if unmet:
            step.status, step.error = "blocked", f"依赖未满足：第 {unmet} 步没有成功完成"
            return step, step.error
        done = {s.id: s.result for s in steps if s.status == "done"}
        try:
            args = resolve_args(step.args, done)
        except RefError as exc:
            step.status, step.error = "failed", str(exc)
            return step, f"参数引用与真实结果不一致：{exc}"
        r = tools.execute(step.tool, args)
        if r.ok:
            step.status, step.observation = "done", r.content
            step.result = json.loads(r.content) if r.content.startswith("{") else r.content
            if verbose:
                print(f"   [完成] 第 {step.id} 步：{step.goal}  -> {r.content[:56]}")
        else:
            step.status, step.error = "failed", (r.error or r.content)
            if verbose:
                print(f"   [失败] 第 {step.id} 步：{step.goal}  -> {step.error[:64]}")
            return step, step.error
    return None


# ======================= 3. 重规划 =======================
def initial_plan() -> Plan:
    """t=0 时模型写出的计划（那时订单还是「已发货」）。"""
    return Plan(version=1, reason="初始计划", steps=[
        Step(1, "查询订单 A1001 的真实状态与重量", "lookup_order", {"order_id": "A1001"}),
        Step(2, "用订单里的重量算出加急运费", "calc_freight",
             {"order_id": "$1.order_id", "weight_kg": "$1.weight_kg", "speed": "加急"}, [1]),
        Step(3, "拟发货通知", "draft_reply",
             {"order_id": "$1.order_id", "kind": "shipped", "detail": "加急运费 $2.freight 元"}, [1, 2]),
        Step(4, "把通知真正发给客户", "send_reply",
             {"order_id": "$1.order_id", "text": "$3.text"}, [3]),
    ])


def replan(task: str, plan: Plan, failed: Step, reason: str) -> Plan:
    """真实的 Replanner 是一次模型调用；这里用确定性函数替代，让结论可复现。

    它收到的信息就是真实提示词里的那三块：原始任务 + 上一版计划的真实状态 + 失败点。
    """
    if "已取消" in reason:
        return Plan(
            version=plan.version + 1,
            reason=f"第 {failed.id} 步失败：{reason[:44]}",
            steps=[
                Step(1, "查询订单 A1001 的真实状态与重量", "lookup_order", {"order_id": "A1001"}),
                Step(2, "订单已取消 -> 改查退款进度", "query_refund",
                     {"order_id": "$1.order_id"}, [1]),
                Step(3, "改拟取消通知（附退款进度）", "draft_reply",
                     {"order_id": "$1.order_id", "kind": "cancelled",
                      "detail": "退款进度：$2.status"}, [1, 2]),
                Step(4, "把通知真正发给客户", "send_reply",
                     {"order_id": "$1.order_id", "text": "$3.text"}, [3]),
            ])
    raise RuntimeError("这个教学用的假规划器只会处理「订单已取消」这一种失败")


def carry_over(old: Plan, new: Plan) -> int:
    """把上一版**已成功**的步骤继承过来（指纹相同才算数）。返回复用了几步。"""
    reusable, reused = old.done_signatures, 0
    for step in new.steps:
        prior = reusable.get(step.signature)
        if prior is not None:
            step.status, step.result, step.observation = "done", prior.result, prior.observation
            reused += 1
    return reused


# ======================= 4. 主循环：三道刹车写进结构里 =======================
def run(task: str, world: World, max_replans: int = REPLAN_BUDGET) -> dict:
    tools = world.build_tools()
    plan = initial_plan()
    plans, replans, reused = [plan], 0, 0
    stop_reason = "completed"
    print(plan.render())
    print()

    while True:
        # 刹车 ①：执行前静态校验 —— 跑不通的计划一步都不执行
        problems = validate_plan(plan.steps, tools)
        if problems:
            stop_reason = "plan_invalid"
            print("   静态校验不通过，拒绝执行：", problems)
            break

        outcome = execute_steps(plan.steps, tools)
        if outcome is None:                     # 全部成功
            stop_reason = "completed"
            break

        failed, reason = outcome
        # 刹车 ②：重规划预算 —— 模型可能反复给出跑不通的计划
        if replans >= max_replans:
            stop_reason = "replan_exhausted"
            print(f"   重规划次数已达上限 {max_replans}，停止重试")
            break

        print(f"   [重规划] 第 {replans + 1} 次")
        new_plan = replan(task, plan, failed, reason)
        reused += carry_over(plan, new_plan)
        replans += 1
        plans.append(new_plan)
        plan = new_plan
        print()
        print(plan.render())
        print()

    return {"stop_reason": stop_reason, "plans": plans, "replans": replans,
            "reused": reused, "calls": list(world.calls), "sent": list(world.sent)}


# ======================= 5. 跑一次：订单在计划之后被取消 =======================
world = World(cancel=True)
print("任务：告诉客户订单 A1001 的当前状态")
print("（注意：计划是订单还写着「已发货」时做的，执行时它已经被取消了）")
print()
result = run("告诉客户订单 A1001 的当前状态", world)
print()
print("停机原因        :", result["stop_reason"])
print("计划版本数      :", len(result["plans"]))
print("重规划次数      :", result["replans"])
print("被复用的已完成步骤:", result["reused"])
print("工具调用        :", result["calls"], f"（{len(result['calls'])} 次）")
print("真实发给客户的通知:", result["sent"])
print()
print("★ 任务完成了，而且**客户收到的是一条正确的新通知**（订单已取消 + 退款进度）。")
print("  如果当初吞掉异常继续跑（① 节的死法 2），没人会知道出过问题。")''')

    nb.md("""### 结果说明什么

把这次运行的轨迹摊平看：

| 阶段 | 发生了什么 | 关键点 |
|---|---|---|
| 计划 v1 | 4 步，假设订单已发货 | 计划是**假设** |
| 第 1 步 | 查订单 → 真实状态是「已取消」 | 执行是**验证** |
| 第 2 步 | `calc_freight` 失败，原因原样保留 | 失败是**信号**，不是崩溃 |
| 重规划 | 第 2 步改成查退款，第 3 步改成取消通知 | 改计划，不是改目标 |
| 第 1 步 | **直接复用**（跳过） | 已验证的事实不重跑 |
| 第 3/4 步 | 完成，客户收到正确通知 | 闭环 |

三个细节值得记住：

1. **`send_reply` 里的兜底护栏救了一次场**。即使重规划也写错了文案，
   那句「订单已取消但文案声称已发货 → 拒绝发送」都会拦住它。
   **有副作用的步骤，执行前必须再校验一次前置条件** —— 静态校验管不到这里。
2. **停机原因是 `completed`**，而且它和 `plan_invalid` / `replan_exhausted`
   是三种不同的东西。**停机原因必须分类**，否则你永远定位不到问题。
3. `REPLAN_BUDGET` 是必需品，和 `max_steps` 是同一条道理：
   **每个循环都必须能证明自己会停。**（改它的那一格在代码里标了 `<- 试着改这里`。）

现在闭环能跑了。但还有一个「省钱 / 保命」的细节没讲：**重规划之后，那些已经成功的步骤怎么办？**""")

    # ==================================================================
    section(nb, "⑥", "重规划要复用，不要重跑")

    nb.md("""### 现在卡在哪

重规划会产出一份**全新的计划**。如果执行器老老实实从第 1 步开始跑：

- 已经成功的**读操作**会被重复执行 —— 浪费钱和时间；
- 已经成功的**写操作**会被重复执行 —— 这是**事故**：
  客户收到两条短信、账户被扣两次钱、仓库发两次货。

### 所以我需要一个「按指纹复用已成功步骤」的机制

判据只有一条：**指纹相同（工具 + 参数完全一致）且上一版里已经成功**。

```python
reusable = old.done_signatures              # {指纹: 已成功的步骤}
for step in new.steps:
    prior = reusable.get(step.signature)
    if prior is not None:                   # 完全一样的调用，且已经成功过
        step.status, step.result, step.observation = "done", prior.result, prior.observation
```

这段代码只有 10 行，但它是「重规划能不能省錢」的分水岭。
为什么用**指纹**而不是用「第几步」？因为重规划会重新编号 ——
第 1 步可能变成第 2 步，靠编号对不上，靠「工具 + 参数」才稳。

### 立刻用一次

下面这个场景会让「不复用」的后果**直接变成事故**：

```
   计划 v1：① 查订单  ② 拟通知  ③ 发给客户  ④ 写入内部备注（失败）
   重规划 v2：① ② ③ 一样，④ 改用另一个工具
```

第 ③ 步是**真的发短信**。如果 v2 从头跑一遍，客户就会收到**两条**短信。""")

    nb.code('''# 单独可运行：重规划要不要复用已完成的步骤？
CARRY_OVER = True        # ← 试着改这里：改成 False，看客户收到几条通知

import sys, pathlib, json, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.tool import ToolRegistry


# ---------- 世界：多了一个"失败的备注服务" ----------
class World:
    def __init__(self):
        self.order = {"order_id": "A1001", "status": "已发货",
                      "carrier": "顺丰", "tracking": "SF1234567890"}
        self.calls = []       # 工具调用记录
        self.sent = []        # 真正发出去的短信（客户看得见的东西）
        self.notes = []       # 内部备注

    def build_tools(self):
        reg, w = ToolRegistry(), self

        @reg.tool("lookup_order", "查询订单状态、承运商、运单号。",
                  {"type": "object", "properties": {"order_id": {"type": "string"}},
                   "required": ["order_id"], "additionalProperties": False})
        def lookup_order(order_id: str) -> dict:
            w.calls.append("lookup_order")
            return dict(w.order)

        @reg.tool("draft_reply", "生成发货通知文案。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"},
                                  "tracking": {"type": "string"}},
                   "required": ["order_id", "tracking"],
                   "additionalProperties": False})
        def draft_reply(order_id: str, tracking: str) -> dict:
            w.calls.append("draft_reply")
            return {"text": f"您的订单 {order_id} 已发货，运单号 {tracking}。"}

        @reg.tool("send_reply", "把短信发给客户（**有副作用**）。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"}, "text": {"type": "string"}},
                   "required": ["order_id", "text"], "additionalProperties": False})
        def send_reply(order_id: str, text: str) -> dict:
            w.calls.append("send_reply")
            w.sent.append(text)                       # <- 真发了，撤不回来
            return {"sent": True, "cumulative": len(w.sent)}

        @reg.tool("write_note", "把备注写进内部系统（**本次故意不可用**）。",
                  {"type": "object", "properties": {"text": {"type": "string"}},
                   "required": ["text"], "additionalProperties": False})
        def write_note(text: str) -> str:
            w.calls.append("write_note")
            raise RuntimeError("备注服务暂时不可用，请改用 write_audit")

        @reg.tool("write_audit", "把记录写进审计流水（write_note 的替代方案）。",
                  {"type": "object", "properties": {"text": {"type": "string"}},
                   "required": ["text"], "additionalProperties": False})
        def write_audit(text: str) -> dict:
            w.calls.append("write_audit")
            w.notes.append(text)
            return {"audited": True}

        return reg


@dataclass
class Step:
    id: int
    goal: str
    tool: str = ""
    args: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    status: str = "pending"
    result: object = None
    observation: str = ""
    error: str = ""

    @property
    def signature(self) -> str:
        return f"{self.tool}({json.dumps(self.args, sort_keys=True, ensure_ascii=False, default=str)})"


_REF_EXACT_RE = re.compile(r"^\\$(\\d+)\\.([\\w\\.]+)$")
_REF_ANY_RE = re.compile(r"\\$(\\d+)\\.([\\w\\.]+)")

class RefError(Exception):
    pass

def resolve_args(args, done):
    """引用解析（④ 节那套，这里只保留够用的部分）。"""
    out = {}
    for key, value in args.items():
        if not isinstance(value, str):
            out[key] = value
            continue
        m = _REF_EXACT_RE.match(value.strip())
        if m:
            sid, path = int(m.group(1)), m.group(2)
            if sid not in done:
                raise RefError(f"参数 {key}={value!r} 引用了未成功的第 {sid} 步")
            data = done[sid]
            for part in path.split("."):
                if isinstance(data, dict) and part in data:
                    data = data[part]
                else:
                    raise RefError(f"参数 {key}={value!r} 无法解析：没有 {path!r}")
            out[key] = data
            continue
        if "$" in value:
            def _sub(mm):
                sid, path = int(mm.group(1)), mm.group(2)
                if sid not in done:
                    raise RefError(f"参数 {key}={value!r} 引用了未成功的第 {sid} 步")
                data = done[sid]
                for part in path.split("."):
                    data = data[part] if isinstance(data, dict) and part in data else None
                return str(data)
            out[key] = _REF_ANY_RE.sub(_sub, value)
            continue
        out[key] = value
    return out


def execute_steps(steps, tools, verbose=True):
    """逐步执行；返回 None 或 (失败步骤, 原因)。"""
    for step in steps:
        if step.status == "done":
            if verbose:
                print(f"   [跳过] 第 {step.id} 步（已完成，复用结果）")
            continue
        done = {s.id: s.result for s in steps if s.status == "done"}
        try:
            args = resolve_args(step.args, done)
        except RefError as exc:
            step.status, step.error = "failed", str(exc)
            return step, str(exc)
        r = tools.execute(step.tool, args)
        if r.ok:
            step.status, step.observation = "done", r.content
            step.result = json.loads(r.content) if r.content.startswith("{") else r.content
            if verbose:
                print(f"   [完成] 第 {step.id} 步：{step.goal}")
        else:
            step.status, step.error = "failed", (r.error or r.content)
            if verbose:
                print(f"   [失败] 第 {step.id} 步：{step.goal}  -> {step.error[:56]}")
            return step, step.error
    return None


def plan_v1():
    """t=0 的计划：查订单 -> 拟文案 -> 发短信 -> 写内部备注。"""
    return [
        Step(1, "查询订单状态与运单号", "lookup_order", {"order_id": "A1001"}),
        Step(2, "拟发货通知文案", "draft_reply",
             {"order_id": "$1.order_id", "tracking": "$1.tracking"}, [1]),
        Step(3, "把短信发给客户", "send_reply",
             {"order_id": "$1.order_id", "text": "$2.text"}, [2]),
        Step(4, "把这次通知写进内部备注", "write_note", {"text": "$2.text"}, [2]),
    ]


def plan_v2(old):
    """重规划的产物：前三步一字不改，第 4 步改用 write_audit。

    ★ 注意：**模型并不知道**第 1~3 步已经成功执行过了 ——
      它只看到「第 4 步失败」，于是原样保留前三步。
      所以"要不要跳过它们"这件事，必须由执行器自己判断。
    """
    return [
        Step(1, "查询订单状态与运单号", "lookup_order", {"order_id": "A1001"}),
        Step(2, "拟发货通知文案", "draft_reply",
             {"order_id": "$1.order_id", "tracking": "$1.tracking"}, [1]),
        Step(3, "把短信发给客户", "send_reply",
             {"order_id": "$1.order_id", "text": "$2.text"}, [2]),
        Step(4, "改用审计流水记录这次通知", "write_audit", {"text": "$2.text"}, [2]),
    ]


def carry_over(old_steps, new_steps):
    """★ 本章最值钱的 10 行：按指纹复用上一版**已成功**的步骤。"""
    reusable = {s.signature: s for s in old_steps if s.status == "done"}
    reused = 0
    for step in new_steps:
        prior = reusable.get(step.signature)
        if prior is not None:
            step.status, step.result, step.observation = "done", prior.result, prior.observation
            reused += 1
    return reused


# ---------- 跑一次（CARRY_OVER 就是那个开关）----------
world = World()
tools = world.build_tools()

print("=== 计划 v1 ===")
v1 = plan_v1()
outcome = execute_steps(v1, tools)
print()

print("=== 重规划得到 v2 ===")
v2 = plan_v2(v1)
if CARRY_OVER:
    n = carry_over(v1, v2)
    print(f"   复用了 {n} 个已成功步骤（状态直接标成 done）")
else:
    print("   不复用（每一版都从头跑）—— 看看会发生什么")
print()
outcome = execute_steps(v2, tools)
print()
print(f"CARRY_OVER        = {CARRY_OVER}")
print(f"工具调用          = {world.calls}")
print(f"其中 send_reply   = {world.calls.count('send_reply')} 次")
print(f"客户实际收到的短信 : {len(world.sent)} 条")
for s in world.sent:
    print("      -", s)
print(f"内部备注          = {world.notes}")
print()
if CARRY_OVER:
    print("★ 客户收到 1 条短信。已完成的步骤被跳过，只有第 4 步真正重跑。")
else:
    print("★ 客户收到 2 条**一模一样**的短信 —— 这就是线上事故。")
    print("  读操作重跑只是浪费钱；写操作重跑是事故。")
    print("  没有幂等保证的时候，「复用已完成步骤」不是优化，而是**必需**。")''')

    nb.md("""### 结果说明什么

| `CARRY_OVER` | 工具调用次数 | 客户收到的短信 | 结论 |
|---|---|---|---|
| `True` | 5 次 | **1 条** | 只重跑真正需要重跑的那一步 |
| `False` | 6 次 | **2 条**（重复） | 重复副作用 = 事故 |

两件事值得单独记住：

1. **模型不知道哪些步骤已经执行过。** 它只看到「第 4 步失败」，于是原样保留前三步。
   「跳过已成功的步骤」这件事必须由**执行器**负责 —— 不能指望模型自觉。
2. **幂等性决定重规划的安全边界。** 读操作可以随便重跑；写操作必须有幂等键
   （第 13 章）才能安全重试。**没有幂等保证时，复用是必需品，不是优化。**

最后看一下「计划该拆多细」这件事 —— 它是成本表上的乘数。""")

    # ==================================================================
    section(nb, "⑦", "计划粒度：不是越细越好")

    nb.md("""### 现在卡在哪

既然「失败时能精确定位」很重要，那是不是把计划拆得越细越好？比如：

```
   ❌ 太细：① 查订单号  ② 查状态  ③ 查重量  ④ 算运费  ⑤ 拟文案  ⑥ 发短信
   ❌ 太粗：① 一步搞定（查订单 + 算运费 + 拟文案 + 发短信）
   ✓ 合适：① 查订单  ② 算运费  ③ 拟文案  ④ 发短信
```

三个档次的真实差别：

| 粒度 | 步数 | 工具调用 | 失败后可复用 | 问题 |
|---|---|---|---|---|
| 太粗 | 少 | 少 | **0** | 失败时不知道是哪件事破了 |
| 合适 | 中 | 中 | 有 | —— |
| 太细 | 多 | **多** | 有（但没多） | 调用成本翻倍，中间结果撑爆上下文 |

判据不是「越细越严谨」，而是：**失败时能精确定位，且不必连累已完成的步骤。**

### 立刻用一次：把这件事量化

同一份任务、同一个「订单被取消」的变化，只改粒度，看指标怎么变。""")

    nb.code('''# 单独可运行：计划粒度实验 —— 用调用次数把「细粒度更严谨」这个错觉打掉
GRANULARITY = "mid"      # ← 试着改这里："coarse" / "mid" / "fine"

import sys, pathlib, json, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.tool import ToolRegistry


class World:
    """订单系统。cancelled=True 表示「计划做完之后订单被取消了」。"""

    def __init__(self, cancelled: bool = True) -> None:
        self.cancelled = cancelled
        self.order = {"order_id": "A1001",
                      "status": "已取消" if cancelled else "已发货",
                      "weight_kg": 2.5, "amount": 328.0, "tracking": "SF1234567890"}
        self.calls = []

    def build_tools(self) -> ToolRegistry:
        reg, w = ToolRegistry(), self

        @reg.tool("lookup_order", "查询订单的全部字段。",
                  {"type": "object", "properties": {"order_id": {"type": "string"}},
                   "required": ["order_id"], "additionalProperties": False})
        def lookup_order(order_id: str) -> dict:
            w.calls.append("lookup_order")
            return dict(w.order)

        @reg.tool("get_field", "只读一个字段。字段粒度会让步骤变多，请谨慎使用。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"},
                                  "field": {"type": "string",
                                            "enum": ["status", "weight_kg", "amount", "tracking"]}},
                   "required": ["order_id", "field"], "additionalProperties": False})
        def get_field(order_id: str, field: str) -> dict:
            w.calls.append("get_field")
            return {"field": field, "value": w.order.get(field)}

        @reg.tool("calc_freight", "计算运费。订单已取消时无法计算。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"}, "weight_kg": {"type": "number"},
                                  "speed": {"type": "string", "enum": ["标准", "加急"]}},
                   "required": ["order_id", "weight_kg", "speed"],
                   "additionalProperties": False})
        def calc_freight(order_id: str, weight_kg: float, speed: str) -> dict:
            w.calls.append("calc_freight")
            if w.cancelled:
                raise ValueError(f"订单 {order_id} 已取消，无法计算运费")
            return {"freight": round(25.0 + 3.5 * float(weight_kg), 2)}

        @reg.tool("draft_reply", "生成通知文案（kind 必须与真实状态一致）。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"}, "kind": {"type": "string"}},
                   "required": ["order_id", "kind"], "additionalProperties": False})
        def draft_reply(order_id: str, kind: str) -> dict:
            w.calls.append("draft_reply")
            want = "cancelled" if w.cancelled else "shipped"
            if kind != want:
                raise ValueError(f"通知类型 {kind!r} 与真实状态不符（应该用 {want!r}）")
            return {"text": f"订单 {order_id} 的通知（{kind}）"}

        @reg.tool("send_reply", "把通知发给客户（有副作用）。",
                  {"type": "object",
                   "properties": {"order_id": {"type": "string"}, "text": {"type": "string"}},
                   "required": ["order_id", "text"], "additionalProperties": False})
        def send_reply(order_id: str, text: str) -> dict:
            w.calls.append("send_reply")
            return {"sent": True}

        return reg


@dataclass
class Step:
    id: int
    goal: str
    tool: str = ""
    args: dict = field(default_factory=dict)
    depends_on: list = field(default_factory=list)
    status: str = "pending"
    result: object = None
    observation: str = ""
    error: str = ""

    @property
    def signature(self) -> str:
        return f"{self.tool}({json.dumps(self.args, sort_keys=True, ensure_ascii=False, default=str)})"


_REF_EXACT_RE = re.compile(r"^\\$(\\d+)\\.([\\w\\.]+)$")

class RefError(Exception):
    pass

def resolve_args(args, done):
    """只处理「整串是引用」这一种（教学版够用）。"""
    out = {}
    for key, value in args.items():
        if not isinstance(value, str):
            out[key] = value
            continue
        m = _REF_EXACT_RE.match(value.strip())
        if not m:
            out[key] = value
            continue
        sid, path = int(m.group(1)), m.group(2)
        if sid not in done:
            raise RefError(f"参数 {key}={value!r} 引用了未成功的第 {sid} 步")
        data = done[sid]
        for part in path.split("."):
            if isinstance(data, dict) and part in data:
                data = data[part]
            else:
                raise RefError(f"参数 {key}={value!r} 无法解析：没有 {path!r}")
        out[key] = data
    return out


def execute_steps(steps, tools, calls, verbose=False):
    """执行到失败为止。

    参数 steps：计划
         tools：工具注册表
         calls：世界的调用记录列表（**调用次数就是钱**，所以要单独统计出来）
    返回      ：(停机原因, 工具调用次数, 已成功完成的步骤数)
    """
    for step in steps:
        done = {s.id: s.result for s in steps if s.status == "done"}
        try:
            args = resolve_args(step.args, done)
        except RefError as exc:
            step.status, step.error = "failed", str(exc)
            return "failed（引用解析失败）", len(calls), len([s for s in steps if s.status == "done"])
        r = tools.execute(step.tool, args)
        if verbose:
            print(f"      {step.tool} -> {(r.content if r.ok else r.error)[:48]}")
        if r.ok:
            step.status, step.observation = "done", r.content
            step.result = json.loads(r.content) if r.content.startswith("{") else r.content
        else:
            step.status, step.error = "failed", (r.error or r.content)
            return "failed", len(calls), len([s for s in steps if s.status == "done"])
    return "completed", len(calls), len(steps)


def make_plan(kind: str):
    """三种粒度下，模型会写出的三种计划（都是"能完成同一个任务"的写法）。"""
    if kind == "coarse":
        # 粗：一步干四件事。省调用，但失败时什么都保不住
        return [
            Step(1, "查订单并算运费、拟文案、发通知", "draft_reply",
                 {"order_id": "A1001", "kind": "shipped"}),
        ]
    if kind == "fine":
        # 细：一个字段一步。看着严谨，实际把调用次数翻倍
        return [
            Step(1, "查状态", "get_field", {"order_id": "A1001", "field": "status"}),
            Step(2, "查重量", "get_field", {"order_id": "A1001", "field": "weight_kg"}),
            Step(3, "查运单号", "get_field", {"order_id": "A1001", "field": "tracking"}),
            Step(4, "算运费", "calc_freight",
                 {"order_id": "A1001", "weight_kg": "$2.value", "speed": "加急"}, [2]),
            Step(5, "拟文案", "draft_reply", {"order_id": "A1001", "kind": "shipped"}, [1]),
            Step(6, "发通知", "send_reply", {"order_id": "A1001", "text": "$5.text"}, [5]),
        ]
    # mid：一件事一步 —— 失败时能精确定位，且前面成功的步骤都能复用
    return [
        Step(1, "查订单状态、重量、运单号", "lookup_order", {"order_id": "A1001"}),
        Step(2, "算加急运费", "calc_freight",
             {"order_id": "$1.order_id", "weight_kg": "$1.weight_kg", "speed": "加急"}, [1]),
        Step(3, "拟通知文案", "draft_reply", {"order_id": "$1.order_id", "kind": "shipped"}, [1]),
        Step(4, "发通知", "send_reply", {"order_id": "$1.order_id", "text": "$3.text"}, [3]),
    ]


print("表格：三个粒度 x 两种世界（订单取消 / 没取消）")
print()
print(f"{'粒度':<8}{'步数':>4}{'世界':>8}{'调用次数':>10}{'可复用步骤':>12}  停机原因")
print("-" * 66)
rows = {}
for kind, label in (("coarse", "粗"), ("mid", "中"), ("fine", "细")):
    for cancelled in (False, True):
        # 每种组合都用一个全新的世界和执行环境，免得互相污染
        world = World(cancelled=cancelled)
        tools = world.build_tools()
        steps = make_plan(kind)
        stop, calls, reusable = execute_steps(steps, tools, world.calls)
        rows[(kind, cancelled)] = (stop, calls, reusable)
        w = "已取消" if cancelled else "正常"
        print(f"{label:<8}{len(steps):>4}{w:>10}{calls:>10}{reusable:>12}  {stop}")

print()
sel = rows[(GRANULARITY, True)]
print(f"当前选中的粒度 GRANULARITY = {GRANULARITY!r}（订单被取消的那一行）")
print(f"   步数 = {len(make_plan(GRANULARITY))}，调用次数 = {sel[1]}，可复用步骤 = {sel[2]}，停机原因 = {sel[0]}")
print()
print("★ 读表要点：")
print("  · 粗粒度在「订单取消」时**一步都复用不了**：唯一那一步混入了错误假设，只能整体重做；")
print("  · 细粒度调用次数最多（一个字段一次调用），但**成功率并没有变高** —— 多花的钱没换来东西；")
print("  · 中粒度是那个平衡点：失败时能精确定位，前面成功的步骤都能保住。")
print("  · 一句话：粒度以「失败时能精确定位、且不必连累已完成步骤」为准，不是越细越好。")''')

    nb.md("""### 结果说明什么

- **粗粒度**：调用最少，但唯一那一步混进了错误假设（`kind=shipped`），
  一失败就**全部重做**，可复用步骤 = 0，而且运费那种数字是计划期猜的；
- **中粒度**：失败点精确到「算运费这一步的假设破了」，重规划只改必要的一步；
- **细粒度**：调用次数翻倍，成功率并没有变高 ——
  多花的钱和把中间结果堆进上下文的代价（第 05 章）都没换来收益。

> 注意 `GRANULARITY` 那一行是可以改的：改成 `"coarse"` 或 `"fine"` 再跑一次，
> 看下面那三行详细输出怎么变。表格本身永远打印三档，方便你对照。

粒度这件事的判据只有一条：**失败时能精确定位，且不必连累已完成的步骤。**""")

    # ==================================================================
    section(nb, "⑧", "常见坑汇总")

    pitfall_table(nb, [
        ("吞掉错误继续跑", "交出「任务已完成」的报告 → **假成功**",
         "失败必须变成「带原因的结果」，并触发重规划"),
        ("计划里的每一步都当事实", "环境变了之后，计划还在按旧假设执行",
         "有副作用的步骤执行前**再校验一次前置条件**"),
        ("重规划时不带原始任务", "重规划两三次后模型忘记最初要干什么，开始优化自己发明的目标",
         "提示词三块：任务 + 已完成的真实结果 + 失败原因"),
        ("重规划没有预算", "模型反复给出跑不通的计划 → 无限烧钱", "`max_replans`，理由同 `max_steps`"),
        ("重规划不复用已完成步骤", "重复读浪费钱；重复写是**事故**（客户收到两条短信）",
         "按「工具 + 参数」指纹复用已成功的步骤"),
        ("依赖不限制方向", "循环依赖（A 等 B、B 等 A）导致执行顺序无法确定",
         "依赖只能指向**更小的编号**（一条规则同时挡住两种毛病）"),
        ("规划期不校验工具名", "幻觉工具在规划期比执行期更常见（模型还没看到任何反馈）",
         "`validate_plan` 在执行前查工具名 + 参数齐不齐"),
        ("以为静态校验能查「值对不对」", "`weight_kg=250`（把克当千克）静态完全合法",
         "范围校验（`minimum`/`maximum`）+ 业务规则兜底"),
        ("校验放在执行之后", "副作用已经产生才报错，撤不回来", "校验必须在执行**之前**"),
        ("参数让模型「猜」一个值", "幻觉的发源地，而且没人能发现",
         "用 `$1.field` 引用上游结果，真实值只来自真实结果"),
        ("粒度越细越好", "调用次数翻倍，成功率不变，上下文被中间结果撑爆",
         "以「失败时能精确定位」为准，不是越细越好"),
    ])

    summary(nb, [
        "**规划 = 先产出步骤列表，再逐步执行 + 按需重规划。**"
        "计划是假设，执行是验证，偏差就要修计划。",
        "**最大的危险不是崩溃，而是假成功** —— 吞掉错误的执行器会交出一份"
        "「任务已完成」的报告，而客户什么都没收到。",
        "**计划必须是结构化数据**：`id` / `goal` / `tool` / `args` / `depends_on`。"
        "散文计划没法校验、没法执行、没法 diff。",
        "**能静态拦下的，绝不拖到执行期。** 幻觉工具、循环依赖、缺参数 —— 一步都不许跑。",
        "**用引用（`$1.weight_kg`）让数据在步骤间流动**，而不是让模型猜数字。"
        "猜出来的数字就是幻觉。",
        "**Executor 必须是确定性代码**，否则你分不清失败是计划的锅还是执行的锅。",
        "**重规划要带三块信息**：原始任务 + 已完成的真实结果 + 失败原因。"
        "只说「失败了重来吧」，模型会把同一份计划再写一遍。",
        "**重规划要复用已成功的步骤**（按指纹）。"
        "没有幂等保证时，这不是优化，而是**必需** —— 否则客户会收到两条短信。",
        "**粒度以「失败时能精确定位」为准**，不是越细越好。"
        "每一步都是一次调用，是账单上的乘数。",
    ], "第 05 章会解决规划带出来的新问题："
       "每一版计划、每一步的观测、每一次重规划的原因，全都堆在上下文里 ——"
       "一个 50 轮的任务会轻松把上下文窗口撑爆。"
       "那一章讲**记忆与上下文工程**：在有限预算里保留最高价值的信息。")

    exercises(nb, [
        ("**给 `Step` 加一个 `optional: bool` 字段。**\n\n"
         "可选步骤失败时**不触发重规划**，只记一条警告继续跑。\n\n"
         "改完之后，自己构造一个「第 3 步是可选的、且必然失败」的计划，"
         "验证任务仍然能走到 `completed`。",
         "改动点在执行器的失败分支：`if step.optional: 记警告 + continue`。\n\n"
         "想清楚一个问题：**哪些步骤适合标成可选？**"
         "提示：读操作基本都可以；写操作几乎都不行（写失败往往意味着状态不确定）。"),

        ("**拆掉护栏：注释掉依赖方向的校验。**\n\n"
         "把 `validate_plan` 里最后那个 `elif d > s.id:` 分支删掉，"
         "再用 ③ 节的「循环依赖」坏计划跑一次。\n\n"
         "观察：静态校验还拦得住吗？拦不住的话，执行时会发生什么？",
         "删掉之后静态校验会放行，执行器会把第 1 步标成 `blocked`（依赖未满足），"
         "然后触发重规划 —— 如果重规划又给出同一份计划，就会一直循环，"
         "直到 `max_replans` 兜底。\n\n"
         "结论：**没有静态校验时，你只能靠预算兜底。** 预算是最后一道防线，不是第一道。"),

        ("**让重规划的提示词更省 token。**\n\n"
         "现在的实现把「上一版计划的**全部**结果」都塞进提示词。"
         "改成只传「被后续步骤引用到的字段」。\n\n"
         "统计一下：一个 4 步计划能省掉多少字符？步数变成 20 步时呢？",
         "思路：遍历 `new_steps` 的参数，把 `$N.path` 里的 `(N, path)` 收集起来，"
         "只有这些字段才进提示词。\n\n"
         "这一步的收益随步数线性增长 —— 这就是「上下文工程」在规划场景里的第一次应用。"),

        ("**并行执行互不依赖的步骤。**\n\n"
         "找出计划里 `depends_on` 互不相交、且都无副作用的步骤，"
         "用 `concurrent.futures.ThreadPoolExecutor` 并行跑，打印串行 / 并行的耗时对比。",
         "并行的前提有两条：**无依赖** + **无副作用冲突**。\n\n"
         "两个都写同一个订单的步骤绝对不能并行。"
         "真实系统里还要考虑「同一个工具被限流」这种情况。"),

        ("**给 `Plan` 加一个 `to_mermaid()` 方法。**\n\n"
         "把步骤和依赖渲染成 Mermaid 流程图，贴进任意 Markdown 编辑器就能看到图。",
         "形如：`1[\"查询订单\"] --> 2[\"算运费\"]`。\n\n"
         "为什么值得做？因为「计划长什么样」是给人看的 —— "
         "线上排障时，一张图比 200 行 JSON 有用得多。"),
    ])

    checkpoint(nb, "04")

    return nb
