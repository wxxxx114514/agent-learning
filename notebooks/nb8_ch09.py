"""第 09 章 · 工作流与状态机 —— Notebook 内容（逐步推进版）。

遵守 TEACHING_CONTRACT.md：
  · 逐步给：每个知识点在"读者正好需要"时出现
  · 前置知识表保留在 ⓪，定位是索引（可跳过）
  · 每个代码单元自包含（nb_lint 机器校验）
  · 中文引号一律用 「」，不在字符串里嵌 ASCII 双引号
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


def build_09() -> Notebook:
    """第 09 章 · 工作流与状态机（逐步推进版）。"""
    nb = Notebook("第 09 章 · 工作流与状态机")

    header(
        nb, "09", "工作流与状态机",
        "**能用确定性代码解决的，绝不用模型。**\n"
        "模型只负责「需要判断」的节点，流程骨架应该是显式的图 / 状态机。\n"
        "给 Agent 多少自由度，是一个**架构决策**，不是模型能力问题。",
    )

    objectives(nb, [
        "说清「把流程交给模型」的三个后果：不可复现、不可中断、不可审计",
        "用「节点 + 边 + 状态」三样东西描述一个流程，并画出它的图",
        "背下那条唯一需要背的判据：**哪个节点该用模型**",
        "从零手写一个状态机引擎（含条件边、循环保护、异常不外泄）",
        "解释为什么 `state` 必须是纯 JSON，而模型客户端 / 人工通道要走 `ctx`",
        "实现「分类 → 路由 → 处理 → 汇总」，并跑通三条不同路径",
        "实现检查点（`Interrupt` + `Checkpoint`）：挂起 → 落盘 → 换进程续跑，且已完成节点不重跑",
        "解释为什么**有环不是 bug，没有上限的环才是 bug**",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

第 08 章我们学会了分工。但只要你还把**流程**交给模型，就永远会遇到同一类事故。

本章的主线只有一句话：

> **流程骨架必须是显式的图，模型只出现在真正需要判断的那几个节点上。**

顺序是：

```
① 先看「让模型自己决定流程」会怎样 —— 它会跳过合规检查
② 状态机只有三样东西（节点 / 边 / 状态），以及那张「哪个节点该用模型」的判据表
③ 图的零件怎么用代码表示 → 就地讲 dataclass 与构建期校验
④ 引擎核心：其实就是一个 while 循环 → 就地讲 state 与 ctx 为什么要分开
⑤ 节点怎么写：规则优先、模型兜底 → 6 行代码替代一个"模型自审"节点
⑥ 把图搭起来，跑通「分类 → 路由 → 处理 → 汇总」三条路径
⑦ 检查点与恢复：挂起 → 落盘成 JSON → 换个进程接着跑
⑧ 人工介入与循环保护：有环不是 bug，没有上限的环才是
```

每个知识点都出现在**你正好需要它**的时候。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `dataclass` | 标准库 `dataclasses` | 自动生成 `__init__` 的类装饰器 | `@dataclass` |
| `json.dumps` | 标准库 `json` | Python 对象 → JSON 字符串 | `json.dumps(obj, ensure_ascii=False, indent=2)` |
| `json.loads` | 标准库 `json` | JSON 字符串 → Python 对象 | → `dict` |
| `re.findall` | 标准库 `re` | 找出所有匹配 | `re.findall(模式, 文本)` → `list[str]` |
| `Callable` | 标准库 `typing` | 类型标注：这是个函数 | `Callable[[State, Ctx], dict]` |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `Message` | `core.message` | 一条消息（`.role` / `.content`） |
| `LLM` / `LLMResponse` | `core.llm` | 模型抽象基类；子类实现 `_complete(messages) -> LLMResponse` |
| `BudgetExceeded` | `core.errors` | 预算耗尽（`AbortAgent` 子类，属于"预期内的策略性停机"） |

> 注意：本章**不用** `core.agent.Agent`。因为这一章的主题正是
> 「把循环从 Agent 手里拿走，换成一张显式的图」—— 我们要自己写引擎。

### 随时可查

```python
explain(Message)     # 字段逐个说明
explain()            # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "先看问题：把流程交给模型")

    nb.md("""### 要做什么

第 08 章结束时，你的团队已经能跑通了。但如果主管问模型一句话：

```python
Agent("你是客服 Agent，请处理这张工单，直接给出给客户的回复。")
```

会得到什么？下面是真实会发生的事（用一个确定性的假模型复现同一类输出）。

### 现在卡在哪

问题不是"模型不听话"，而是：

> **从来没有人告诉它流程里必须有一步叫「合规检查」。**

模型只做你要求它做的事，不会替你想起来还有合规、还有归档、还有超时重试。

### 立刻看一遍""")

    nb.code('''# 单独可运行：让模型自己决定流程（对照组）
# 确定性假模型给出的"一步到位"回答（真实项目里这段文字来自模型）
AUTONOMOUS_REPLY = (
    "【工单 T-9002 回复】您好，您的订单已经发货啦，绝对保证明天一定到！"
    "（内部备注：该线路本月已延误 3 次）"
)

# 合规红线：出现这些词，草稿一律不许发给客户（由合规部门定义，不是模型说了算）
FORBIDDEN_WORDS = ("绝对保证", "100%", "内部备注", "私下")


def audit_reply(text: str) -> list:
    """确定性审计：禁用词 + 必填字段。

    参数 text：准备发给客户的回复
    返回    ：问题列表（**空列表 = 通过**）
    """
    issues = []
    for word in FORBIDDEN_WORDS:
        if word in text:
            issues.append(f"禁用词「{word}」")
    if "T-" not in text:
        issues.append("缺少工单号，无法归档")
    return issues


print("模型自己发挥给出的回复：")
print("   ", AUTONOMOUS_REPLY)
print()
issues = audit_reply(AUTONOMOUS_REPLY)
print(f"确定性审计：不通过（{len(issues)} 项）")
for i in issues:
    print("   -", i)
print()
print("★ 没有任何一步叫「合规检查」，所以模型当然不会做 —— 它只做你要求的事。")
print("★ 顺序也不可控：这次先查订单再道歉，下次可能反过来。")
print()
print("顺带一提：这次审计只用了 0 次模型调用、6 行代码。")
print("  第 ⑤ 节会看到同样的 6 行代码，是怎么替代一个「模型自审」节点的。")''')

    nb.md("""### 结果说明什么：三个"不可"

| 问题 | 现象 | 为什么提示词救不了 |
|---|---|---|
| **不可复现** | 这次先查订单再道歉，下次反过来 | 你没法为"随机顺序"写测试 |
| **不可中断** | 跑到一半进程挂了，只能从头再来 | 中间状态在模型脑子里，不在你手里 |
| **不可审计** | 出了事说不清它走了哪条路 | 只有一段最终文本，没有路径记录 |

这三件事，靠"把提示词写得更细"是解决不了的：

- 提示词是**建议**，代码是**约束**；
- 你可以请求模型"记得做合规"，但你无法**保证**它做了；
- 而合规检查这件事，本来就**不需要判断** —— 它是规则。

所以本章要做的是：**把流程从模型手里拿走，写进一张显式的图。**""")

    # ==================================================================
    section(nb, "②", "状态机只有三样东西")

    nb.md("""### 所以我需要一个"流程"的表达方式

任何工作流——不管是客服工单、CI 流水线还是审批系统——都可以拆成三样东西：

```
   节点（做什么）  +  边（下一步去哪）  +  状态（记住什么）
```

把它画出来，本章的流程长这样：

```
   ┌────────┐   条件边: category=="refund"    ┌──────────────┐
   │ intake │───────────────┬────────────────▶│ handle_refund│──┐
   │ 校验    │               │                 └──────────────┘  │
   └────────┘               │ logistics       ┌────────────────┐│
        │                   ├────────────────▶│handle_logistics│├─▶ draft_reply
        │ 内容为空 → END     │                 └────────────────┘│      │
        │                   │ consult         ┌───────────────┐ │      ▼
        │                   └────────────────▶│handle_consult │─┘  compliance
        │                                     └───────────────┘         │
        │                                       条件边: 有无违规          │
        │                                     ┌──────────┴──────────┐    │
        │                                     ▼                     ▼    │
        │                                 finalize            human_review
        │                                     ▲                     │
        │                                     └──── approve ────────┤
        │                                                           │ reject
        │                                                           ▼
        └─────────────────────────────────────────────────  draft_reply（重写）
```

框架（LangGraph / Dify / Coze）多出来的部分，全是围绕这三样的工程包装：
检查点、并发、人工介入、可视化、重试。**所以先手写一遍，你就能看穿它们。**

### 全章唯一需要背下来的判据：哪个节点该用模型？

| 问题 | 答案 | 实现方式 |
|---|---|---|
| 这件事的答案在表里 / 规则里吗？ | 是 | **写代码**（FAQ 查表、订单查询、条款匹配） |
| 这件事每次都必须给出同样的判断吗？ | 是 | **写代码**（合规检查、金额校验、必填字段） |
| 这是流程控制（下一步去哪）吗？ | 是 | **写代码**（路由器是纯函数） |
| 需要把结论翻译成人话 / 理解模糊语义？ | 是 | **交给模型** |
| 需要承担责任（赔付、放行）？ | 是 | **交给人** |

### 立刻用这张判据表量一遍本章的图""")

    nb.code('''# 单独可运行：用判据表给每个节点分类
# 9 个节点，逐个标注「谁来做」和「为什么」
NODES = [
    ("intake", "确定性", "输入校验是规则，错了要能一眼看懂"),
    ("classify", "规则 + 模型兜底", "80% 的工单带关键词；长尾才值得花一次调用"),
    ("handle_refund", "确定性", "答案在订单表和规则里，模型只会读错"),
    ("handle_logistics", "确定性", "同上：查表就有答案"),
    ("handle_consult", "确定性", "FAQ 里有标准答案，永远不要问模型"),
    ("draft_reply", "模型", "把结论写成人话 —— 这才是语言模型的活"),
    ("compliance", "确定性", "合规必须每次判断一致、可审计"),
    ("human_review", "人工", "责任问题，不能交给概率"),
    ("finalize", "确定性", "收口动作没什么可判断的"),
]

print(f"{'节点':<18}{'谁来做':<16}为什么")
print("-" * 72)
for name, kind, why in NODES:
    print(f"{name:<18}{kind:<16}{why}")
print()

llm_nodes = [n for n, kind, _ in NODES if kind == "模型"]
print(f"9 个节点里，真正需要模型的只有 {len(llm_nodes)} 个：{llm_nodes}")
print()
print("★ 这个比例（1/9）不是巧合，而是绝大多数真实业务系统的常态。")
print("  你的第一反应可能是「那模型岂不是很没用」—— 恰恰相反：")
print("  模型的稀缺性，正是它必须被用在「真正需要判断」的地方的原因。")
print()
print("★ 反过来说：如果你发现自己在一张图里标了 6 个模型节点，")
print("  先停下来问一句 —— 那 6 件事里，有几件其实答案在表里？")''')

    # ==================================================================
    section(nb, "③", "图的零件：节点、边、条件边")

    nb.md("""### 现在卡在哪

判据表有了，但"图"还停留在画在纸上的状态。要让它可执行，得先决定**用什么数据结构表示图**。

### 所以我需要三个小结构

| 零件 | 装什么 | 为什么需要 |
|---|---|---|
| `Node` | 名字 + 函数 + 类型 + 标题 | 引擎要知道"这个节点谁来做" |
| `Edge` | 起点 + 终点 | 无条件跳转（"做完 A 就做 B"） |
| `ConditionalEdge` | 起点 + **路由器函数** + 分支表 | 条件跳转（"按类别去哪"） |

用 `dataclass` 是因为这些都是**装数据的容器**：写一次 `@dataclass`，
Python 自动生成 `__init__` / `__repr__` / `__eq__`，你不用手写一堆 `self.x = x`。

### 关键设计：路由器必须是纯函数

```python
ConditionalEdge(src="classify", router=route_by_category,
                targets={"refund": "handle_refund", ...})
```

`router` 的签名是 `(state) -> str`：**看状态，返回一个分支名**，然后查 `targets` 表决定去哪。

**为什么不用模型来路由？** 因为"下一步去哪"是**流程控制**：
它必须可预测、可测试、可审计。把路由交给模型，等于把系统的控制流交给概率。

### 还有一个几乎不要钱、但极其值钱的动作：构建期校验

图是**写死**的，所以它的错误（边指向不存在的节点、孤岛节点、走不到终点）
完全可以在**启动时**就查出来，而不是等跑到半夜才炸。

### 立刻写一遍""")

    nb.code('''# 单独可运行：图的零件 + 构建期校验
from dataclasses import dataclass
from typing import Callable

START = "__start__"     # 入口的虚拟节点名（留着给可视化用）
END = "__end__"         # 终点：走到它就说明流程正常结束


class GraphError(Exception):
    """图本身有问题（连不通、指向不存在的节点）。**在构建期就该炸**，而不是运行到一半才炸。"""


@dataclass
class Node:
    """一个节点 = 一个纯函数（外加它的元信息）。

    参数
      name  ：节点名（边用它来指路）
      fn    ：函数，签名是 fn(state, ctx) -> dict | None，返回「我改了什么」
      kind  ：deterministic / llm / human —— 这个字段就是判据表的落地
      title ：给人看的名字（日志、报错、审批单里都用它）
    """

    name: str
    fn: Callable
    kind: str = "deterministic"
    title: str = ""


@dataclass
class Edge:
    """无条件边：执行完 src 就去 dst。"""

    src: str
    dst: str


@dataclass
class ConditionalEdge:
    """条件边：由 router(state) 返回一个 key，再查 targets 表决定去哪。"""

    src: str
    router: Callable
    targets: dict
    label: str = ""


class StateGraph:
    """图的容器 + 构建期校验（引擎部分在下一节）。"""

    def __init__(self, name: str, max_visits: int = 6) -> None:
        self.name = name
        self.max_visits = max_visits          # 循环保护：同一节点最多被访问几次
        self.nodes: dict = {}
        self.edges: list = []
        self.conditionals: list = []
        self.entry = ""

    def add_node(self, name: str, fn: Callable, kind: str = "deterministic",
                 title: str = "") -> "StateGraph":
        if name in self.nodes:
            raise GraphError(f"节点重名：{name}")     # 重名会让"边指向谁"变得不确定
        self.nodes[name] = Node(name=name, fn=fn, kind=kind, title=title or name)
        return self

    def add_edge(self, src: str, dst: str) -> "StateGraph":
        self.edges.append(Edge(src, dst))
        return self

    def add_conditional(self, src: str, router: Callable, targets: dict,
                        label: str = "") -> "StateGraph":
        self.conditionals.append(ConditionalEdge(src, router, targets, label))
        return self

    def set_entry(self, name: str) -> "StateGraph":
        self.entry = name
        return self

    # ---- 校验：把错误挡在运行之前 ------------------------------------
    def validate(self) -> list:
        """返回图的问题列表（空 = 合法）。生产系统里这一步应该跑在 CI 里。"""
        issues = []
        if self.entry not in self.nodes:
            issues.append(f"入口节点未设置或不存在：{self.entry!r}")
            return issues
        for e in self.edges:
            if e.dst not in self.nodes and e.dst != END:
                issues.append(f"边 {e.src} → {e.dst} 指向不存在的节点")
        for c in self.conditionals:
            if c.src not in self.nodes:
                issues.append(f"条件边的起点不存在：{c.src}")
            for key, dst in c.targets.items():
                if dst not in self.nodes and dst != END:
                    issues.append(f"条件边 {c.src} 的分支 {key!r} 指向不存在的节点 {dst}")
        # 可达性：从入口出发能不能走到每个节点（防死代码）
        reachable = self._reachable(self.entry)
        for name in self.nodes:
            if name not in reachable:
                issues.append(f"节点 {name} 从入口不可达（死代码）")
        # 每个节点都必须能走到 END（否则运行到一半会"卡死在图里"）
        for name in self.nodes:
            if END not in self._reachable(name):
                issues.append(f"节点 {name} 无法到达 END（可能死循环或漏了出边）")
        return issues

    def _reachable(self, start: str) -> set:
        seen, stack = set(), [start]
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in self._next_nodes(cur):
                if nxt not in seen:
                    stack.append(nxt)
        return seen

    def _next_nodes(self, name: str) -> list:
        out = [e.dst for e in self.edges if e.src == name]
        out += [t for c in self.conditionals if c.src == name for t in c.targets.values()]
        return out


# ---- 故意搭一张坏图，看校验能抓到什么 ----
bad = StateGraph("坏图示例")
bad.add_node("a", lambda s, c: None).add_node("orphan", lambda s, c: None)
bad.set_entry("a")
bad.add_conditional("a", lambda s: "go", {"go": "missing_node"}, "指向不存在的节点")

print("坏图的校验结果：")
for i in bad.validate():
    print("   -", i)
print()
print("★ 三个问题全在**构建期**被抓出来了：悬空分支、孤岛节点、到达不了 END。")
print("  如果没有这一步，它们会在某个深夜的请求里变成一次莫名其妙的超时。")''')

    # ==================================================================
    section(nb, "④", "引擎核心：就是一个 while 循环")

    nb.md("""### 现在卡在哪

零件齐了，但图还不会跑。我们需要一个执行器：
"从入口开始，执行节点，按边走到下一个节点，直到 `END`"。

### 它的用法

引擎的核心其实只有这几行：

```python
while cursor != END:
    node = self.nodes[cursor]
    update = node.fn(state, ctx)      # 执行
    if update:
        state.update(update)          # 节点只返回"它改了什么"（增量更新）
    cursor = self._next(cursor, state)  # 按边走到下一步
```

但要做到"能上线"，还要补四件事：

| 补什么 | 为什么 |
|---|---|
| 访问计数 + `max_visits` | 图里**有环是正常的**（人工拒绝要回到草稿），但没有上限的环就是死循环 |
| `try/except` 包住节点 | 任何节点异常都不该让宿主进程崩掉，要变成 `status="error"` 返回 |
| `history` / `visits` | 出事了要能回答"它走了哪条路、每个节点走了几次" |
| `Interrupt` → 检查点 | 需要人拍板时**干净地退出**，而不是阻塞线程（第 ⑦ 节展开） |

### 一个必须现在讲清的纪律：`state` 和 `ctx` 严格分开

```
   ┌───────────────── state（纯 JSON）─────────────────┐
   │  ticket_id / category / decision / draft / ...    │  ← 能落盘、能进 Redis
   └───────────────────────────────────────────────────┘
   ┌───────────────── ctx（运行期资源）────────────────┐
   │  llm 客户端 / 人工通道 / 计数器                    │  ← 绝不进 state
   └───────────────────────────────────────────────────┘
```

**为什么？** 因为检查点要能把 `state` 序列化成 JSON。
模型客户端、回调函数、数据库连接**序列化不了** ——
把模型客户端塞进 state 的代码，是恢复不了的。这是"检查点能不能真正落地"的分水岭。

另外，节点**只返回它改动的字段**（增量），而不是整个 state：
这样并发、回放、审计都容易做，也是 LangGraph 里 `reducer` 的思路。

### 立刻写一个能跑的引擎""")

    nb.code('''# 单独可运行：状态机引擎（含条件边、循环保护、异常兜底）
import json
from dataclasses import dataclass, field
from typing import Callable

END = "__end__"


class GraphError(Exception):
    """图连不通、路由器返回了未定义分支 —— 都属于"程序写错了"，必须显式报出来。"""


class Interrupt(Exception):
    """节点主动"挂起"：我需要人拍板，先把现场存下来，等人回复再继续。

    注意它**不是错误** —— 它是 human-in-the-loop 的**正常控制流**。
    所以它不该被当成 500 错误去告警。
    """

    def __init__(self, question: str, resume_at: str = "") -> None:
        super().__init__(question)
        self.question = question
        self.resume_at = resume_at      # 拿到人工答复后，从哪个节点继续


@dataclass
class Node:
    name: str
    fn: Callable
    kind: str = "deterministic"        # deterministic / llm / human
    title: str = ""


@dataclass
class ConditionalEdge:
    src: str
    router: Callable
    targets: dict
    label: str = ""


@dataclass
class NodeContext:
    """节点运行时的"外部世界"：模型客户端、人工通道、计数器。

    ★ 关键设计：**这些东西绝不放进 state**。
      因为 state 要能被 json.dumps 落盘；而模型客户端、回调函数序列化不了。
    """

    llm: object                      # 任何有 .complete(messages) -> 有 .text 的对象
    human: object                    # 任何有 .try_ask(question) 的对象
    llm_calls: int = 0

    def ask_llm(self, messages: list) -> str:
        """节点里**唯一**允许调模型的方式（顺便记账，方便观察成本）。"""
        self.llm_calls += 1
        return self.llm.complete(messages).text


@dataclass
class Checkpoint:
    """运行现场快照。**必须是纯 JSON**：能落盘、能进 Redis、能被另一个进程接手。"""

    graph: str
    node: str                # 接下来要从哪个节点继续
    state: dict
    visits: dict
    history: list
    llm_calls: int

    def to_json(self, indent=None) -> str:
        return json.dumps({"graph": self.graph, "node": self.node, "state": self.state,
                           "visits": self.visits, "history": self.history,
                           "llm_calls": self.llm_calls},
                          ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "Checkpoint":
        d = json.loads(text)
        return cls(d["graph"], d["node"], d["state"], d["visits"], d["history"], d["llm_calls"])


@dataclass
class RunResult:
    status: str              # completed / interrupted / max_visits / error
    state: dict
    history: list
    visits: dict
    llm_calls: int
    checkpoint: "Checkpoint|None" = None
    error: str = ""

    @property
    def final_reply(self) -> str:
        return str(self.state.get("final_reply", ""))


class StateGraph:
    """状态机引擎：极简，但该有的都有。"""

    def __init__(self, name: str, llm=None, max_visits: int = 6) -> None:
        self.name, self.llm, self.max_visits = name, llm, max_visits
        self.nodes: dict = {}
        self.edges: list = []
        self.conditionals: list = []
        self.entry = ""

    def add_node(self, name, fn, kind="deterministic", title=""):
        self.nodes[name] = Node(name, fn, kind, title or name)
        return self

    def add_edge(self, src, dst):
        self.edges.append((src, dst))
        return self

    def add_conditional(self, src, router, targets, label=""):
        self.conditionals.append(ConditionalEdge(src, router, targets, label))
        return self

    def set_entry(self, name):
        self.entry = name
        return self

    # ---- 运行 ---------------------------------------------------------
    def run(self, state: dict, human=None) -> RunResult:
        return self._execute(self.entry, dict(state), {}, [], human or HumanChannel(), 0)

    def resume(self, checkpoint: Checkpoint, human=None) -> RunResult:
        """从检查点继续 —— 注意这是"另一个进程"也能干的事（前提：state 是纯 JSON）。"""
        if checkpoint.graph != self.name:
            raise GraphError(f"检查点属于图 {checkpoint.graph!r}，不能喂给 {self.name!r}")
        return self._execute(checkpoint.node, dict(checkpoint.state), dict(checkpoint.visits),
                             list(checkpoint.history), human or HumanChannel(), checkpoint.llm_calls)

    # ---- 引擎核心：一个 while 循环，仅此而已 ---------------------------
    def _execute(self, cursor, state, visits, history, human, llm_calls) -> RunResult:
        ctx = NodeContext(llm=self.llm, human=human, llm_calls=llm_calls)

        while cursor != END:
            if cursor not in self.nodes:
                return RunResult("error", state, history, visits, ctx.llm_calls,
                                 error=f"节点不存在：{cursor}")

            visits[cursor] = visits.get(cursor, 0) + 1
            history.append(cursor)

            # 循环保护：同一个节点被访问太多次 = 图里有环且没有出口 → 强制停机。
            # 和 Agent 的 max_steps 是同一个道理，只是这里保护的是"流程"而不是"对话"。
            if visits[cursor] > self.max_visits:
                return RunResult("max_visits", state, history, visits, ctx.llm_calls,
                                 error=f"节点 {cursor} 被访问 {visits[cursor]} 次，超过上限 {self.max_visits}")

            node = self.nodes[cursor]
            # human 节点：先把"人工答复"塞进 state，这样 resume 后节点能直接读到
            if node.kind == "human" and "human_reply" not in state:
                answer = human.try_ask(node.title or "请人工确认")
                if answer is not None:
                    state["human_reply"] = answer

            try:
                update = node.fn(state, ctx)
            except Interrupt as stop:
                # ★ 挂起：保存现场后**干净地退出**（不是崩溃，是可以恢复的暂停）
                state["pending_question"] = stop.question
                cp = Checkpoint(self.name, stop.resume_at or cursor, dict(state),
                                dict(visits), list(history), ctx.llm_calls)
                return RunResult("interrupted", state, history, visits, ctx.llm_calls, checkpoint=cp)
            except Exception as exc:      # 任何节点异常都不该让宿主进程崩掉
                return RunResult("error", state, history, visits, ctx.llm_calls,
                                 error=f"{type(exc).__name__}: {exc}")

            if update:
                state.update(update)      # 节点只返回"它改了什么"
            if node.kind == "human":
                state.pop("human_reply", None)   # 人工答复是一次性的，结算完就清掉
            cursor = self._next(cursor, state)

        return RunResult("completed", state, history, visits, ctx.llm_calls)

    def _next(self, cursor: str, state: dict) -> str:
        for c in self.conditionals:              # 条件边优先
            if c.src == cursor:
                key = c.router(state)
                if key not in c.targets:
                    raise GraphError(f"路由器在 {cursor} 返回了未定义的分支 {key!r}，"
                                     f"已定义：{sorted(c.targets)}")
                return c.targets[key]
        for src, dst in self.edges:
            if src == cursor:
                return dst
        return END                                # 没有出边 = 流程结束


class HumanChannel:
    """人工通道：教学里用**确定性剧本**代替 input()。

    replies 里还有答复 → 直接返回（相当于"值班人在线"）；
    replies 空了       → 返回 None（相当于"没人在线"，引擎会让节点挂起）。
    这样"挂起 → 落盘 → 恢复"这条链路才能被自动化测试反复验证。
    """

    def __init__(self, replies=None) -> None:
        self.replies = list(replies or [])
        self.asked: list = []

    def try_ask(self, question: str):
        self.asked.append(question)
        return self.replies.pop(0) if self.replies else None


# ---- 搭一张最小的图：校验 → 处理 → 收口 ----
def node_intake(state, ctx) -> dict:
    text = str(state.get("text", "")).strip()
    if not text:
        return {"rejected": True, "reject_reason": "工单内容为空"}
    return {"rejected": False, "text": text}


def node_finalize(state, ctx) -> dict:
    return {"final_reply": f"已受理：{state.get('text', '')}", "finished": True}


g = StateGraph("最小示例", max_visits=3)
g.add_node("intake", node_intake, title="输入校验")
g.add_node("finalize", node_finalize, title="交付")
g.set_entry("intake")
g.add_edge("intake", "finalize")          # 无条件边：做完 intake 就去 finalize
g.add_edge("finalize", END)               # 到 END 就结束

r = g.run({"text": "我要退款"})
print("状态：", r.status)
print("路径：", " → ".join(r.history))
print("最终答复：", r.final_reply)
print("模型调用：", r.llm_calls, "次（这一格一个模型节点都没有）")
print()
print("★ 引擎的全部秘密就是那个 while 循环 + state.update(增量)。")
print("★ 注意 history —— 它是排障的第一手资料：出事了先看「它走了哪条路」。")''')

    nb.md("""### 结果说明什么

- 图跑通了，路径是 `intake → finalize`，`history` 把它记了下来
- 这一格**一次模型调用都没有** —— 因为这两个节点都是确定性的
- `state.update(update)` 是"增量更新"：节点不需要看到整个 state，只报自己改了什么

`ctx`（模型客户端 + 人工通道）在这里还没派上用场。下一节我们就来写真正需要模型的节点。""")

    # ==================================================================
    section(nb, "⑤", "节点怎么写：规则优先，模型兜底")

    nb.md("""### 现在卡在哪

有了引擎，接下来是**每个节点内部怎么写**。这里有一条决定性原则：

> ★ **能用确定性代码解决的，绝不用模型。**

### 拿"分类"这件事试一下

假设要判断工单属于 `refund` / `logistics` / `consult` 哪一类。

**第一反应**是让模型分类。但先问自己一句：**真的需要吗？**

真实业务里 80% 的工单都带着明显的关键词："我要退款"、"快递到哪了"、"怎么用"。
这些**根本不需要模型**，一个关键词表就够了，而且：

| 用规则 | 用模型 |
|---|---|
| 0 成本、0 延迟 | 一次调用 + 几百毫秒 |
| 同一句话**永远**分到同一类（可写单元测试） | 今天分对、明天可能分错 |
| 出错时你能一眼看懂为什么 | 出错时你只能猜 |

所以正确做法是**规则优先、模型兜底**：规则命中就用规则，认不出来才轮到模型。

### 第二个例子：合规检查

更极端的是合规：

```python
def node_compliance(state, ctx):
    issues = []
    for word in FORBIDDEN_WORDS:
        if word in state.get("draft", ""):
            issues.append(f"出现禁用词「{word}」")
    ...
    return {"compliance_issues": issues}
```

**6 行代码，0 次模型调用**，替代了一个"让模型自己检查自己"的节点。

为什么不用模型做合规？因为它**不稳**（同样的话这次说有风险、下次说没风险），
而合规要求**每次判断都一样**。

### 立刻对比一次""")

    nb.code('''# 单独可运行：规则优先、模型兜底 + 6 行合规检查
import sys, pathlib, re
from dataclasses import dataclass, field

ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message


# ---- ① 规则优先：关键词命中就返回类别，认不出来返回 None ----
def rule_classify(text: str):
    """关键词规则。

    参数 text：工单正文
    返回    ：类别字符串（refund / logistics / consult）；认不出来返回 None
    """
    rules = (
        ("refund", ("退款", "退货", "不要了", "取消订单")),
        ("logistics", ("快递", "物流", "到哪", "什么时候到", "发货")),
        ("consult", ("怎么用", "怎么开", "有效期", "规则")),
    )
    for label, words in rules:
        if any(w in text for w in words):
            return label
    return None


# ---- ② 模型兜底：只有规则认不出来的长尾才走到这里 ----
class ClassifierLLM(LLM):
    """分类专用假模型（真实项目里这就是一个便宜的小模型）。"""

    name = "classifier"

    def _complete(self, messages, **kwargs):
        text = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if "券" in text:
            label = "consult"
        elif "退" in text:
            label = "refund"
        else:
            label = "logistics"
        return LLMResponse(text=label, model=self.model)


CALLS = {"n": 0}      # 用一个可变字典当计数器，方便在函数里累加


def node_classify(text: str, llm) -> dict:
    """分类节点：**规则优先，模型兜底**。"""
    label = rule_classify(text)
    if label:
        return {"category": label, "classified_by": "规则（0 次模型调用）"}
    CALLS["n"] += 1
    label = llm.complete([Message.system("你是工单分类器。只输出一个类别：refund / logistics / consult。"),
                          Message.user(text)]).text.strip()
    return {"category": label, "classified_by": "模型（规则认不出来才用它）"}


llm = ClassifierLLM()
for text in ("我要退款，订单 A1002 我不想要了",
             "我的订单 A1001 快递到哪了？",
             "请问运费券怎么用？",
             "这个券我不太懂，能解释下吗"):        # ← 最后这条故意不带任何规则关键词
    r = node_classify(text, llm)
    print(f"   {text[:22]:<24} → {r['category']:<10} {r['classified_by']}")
print()
print("模型总共被调用了", CALLS["n"], "次 —— 只有最后那条长尾工单花了钱。")
print()

# ---- ③ 合规检查：6 行代码替代一个"模型自审"节点 ----
FORBIDDEN_WORDS = ("绝对保证", "100%", "内部备注", "私下")
APPROVED_AMOUNTS = {"20"}          # 唯一获批的赔付口径：20 元运费券

DRAFT = "【工单 T-9002 回复】您好，非常抱歉给您带来不便。\\n您的包裹已由顺丰发出。\\n相关补偿绝对保证 24 小时内到账。"


def check_compliance(draft: str, ticket_id: str) -> list:
    """确定性合规检查：每次判断都一样，可审计、可写测试。"""
    issues = []
    for word in FORBIDDEN_WORDS:
        if word in draft:
            issues.append(f"出现禁用词「{word}」")
    for amount in re.findall(r"(\\d+)\\s*元", draft):
        if amount not in APPROVED_AMOUNTS:
            issues.append(f"出现未批准的金额承诺「{amount} 元」")
    if ticket_id not in draft:
        issues.append("回复中缺少工单号，无法归档")
    return issues


issues = check_compliance(DRAFT, "T-9002")
print("模型写出的草稿：")
print("   ", DRAFT.replace("\\n", " ⏎ "))
print()
print("确定性合规检查抓到：", issues)
print("检查用了多少行代码：约 6 行")
print("检查调用了多少次模型：0 次")
print()
print("★ 模型爱用绝对化措辞（绝对保证 / 100%），这是它的真实习惯；")
print("  而这一条恰好是合规红线 —— 所以「模型写、代码查」是个天然的好组合。")''')

    nb.md("""### 结果说明什么

| 做法 | 成本 | 可复现性 | 可测试性 |
|---|---|---|---|
| 全部用模型分类 | 4 次调用 | 差 | 差 |
| **规则优先 + 模型兜底** | **1 次调用** | 好（规则部分 100% 确定） | 好（规则可以写单元测试） |
| 合规交给模型自审 | 1 次调用 | 差 | 差 |
| **合规用 6 行代码** | **0 次调用** | 好 | 好 |

注意最后一列：**"可测试"才是这类改造最值钱的地方。**
一个随机顺序、随机判定的流程，你没法为它写回归测试 —— 也就没法安全地改它。

> 顺带一个判断技巧：如果一个节点你**能用一句话把规则说清楚**，
> 它就大概率该用代码写。只有当你说不清规则（"把这段话写得礼貌一点"），才轮到模型。""")

    # ==================================================================
    section(nb, "⑥", "把图搭起来：分类 → 路由 → 处理 → 汇总")

    nb.md("""### 现在卡在哪

引擎有了、节点写法有了，但散着放的零件不成系统。现在把整张图搭起来。

### 联动：数据怎么流动

```
   用户工单 {ticket_id, text}
        │
        ▼
   ┌─────────────────────────────────────────────────────────┐
   │  state（纯 JSON！）                                       │
   │  {ticket_id, text, category, decision, draft,           │
   │   compliance_issues, human_decision, final_reply, ...}   │
   └───────────────┬─────────────────────────────────────────┘
                   │ 每个节点读 state、返回"我改了什么"
                   ▼
   intake ──条件边──▶ classify ──条件边──▶ handle_refund / _logistics / _consult
                                                │
                                                ▼
                                          draft_reply（唯一的 llm 节点）
                                                │
                                                ▼
                                          compliance（6 行代码）
                                    条件边 ┌────────┴────────┐
                                          ▼                 ▼
                                       finalize       human_review（人工）
                                          ▲                 │ 条件边
                                          └── approve ──────┤
                                                            │ reject
                                                            ▼
                                                   draft_reply（重写，环！）
```

### 三个必须交代的细节

1. **`intake` 用条件边而不是边**：校验不通过的工单**直接出局**，连分类节点都不进 ——
   护栏要在模型之前，这样脏数据连模型都碰不到（0 次调用）。
2. **`handle_*` 是纯查表**：退款规则表、物流表、FAQ 表。答案本来就在表里，模型插不上手。
3. **`draft_reply → compliance → human_review → draft_reply` 是一个环**：
   人工拒绝后回到草稿节点重写。**有环不是 bug**（第 ⑧ 节讲清什么时候才是）。

### 立刻跑通三类工单""")

    nb.code('''# 单独可运行：完整客服工单处理图（引擎 + 节点 + 构图）
import sys, pathlib, re, json
from dataclasses import dataclass
from typing import Callable

ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message

END = "__end__"


class Interrupt(Exception):
    def __init__(self, question, resume_at=""):
        super().__init__(question)
        self.question, self.resume_at = question, resume_at


@dataclass
class Node:
    name: str
    fn: Callable
    kind: str = "deterministic"
    title: str = ""


@dataclass
class NodeContext:
    llm: object
    human: object
    llm_calls: int = 0

    def ask_llm(self, messages) -> str:
        self.llm_calls += 1
        return self.llm.complete(messages).text


class HumanChannel:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.asked = []

    def try_ask(self, question):
        self.asked.append(question)
        return self.replies.pop(0) if self.replies else None


class StateGraph:
    def __init__(self, name, llm=None, max_visits=6):
        self.name, self.llm, self.max_visits = name, llm, max_visits
        self.nodes, self.edges, self.conditionals, self.entry = {}, [], [], ""

    def add_node(self, name, fn, kind="deterministic", title=""):
        self.nodes[name] = Node(name, fn, kind, title or name)
        return self

    def add_edge(self, src, dst):
        self.edges.append((src, dst)); return self

    def add_conditional(self, src, router, targets, label=""):
        self.conditionals.append((src, router, targets)); return self

    def set_entry(self, name):
        self.entry = name; return self

    def run(self, state, human=None):
        return self._execute(self.entry, dict(state), {}, [], human or HumanChannel(), 0)

    def _execute(self, cursor, state, visits, history, human, llm_calls):
        from types import SimpleNamespace
        ctx = NodeContext(llm=self.llm, human=human, llm_calls=llm_calls)
        while cursor != END:
            visits[cursor] = visits.get(cursor, 0) + 1
            history.append(cursor)
            if visits[cursor] > self.max_visits:      # 循环保护
                return SimpleNamespace(status="max_visits", state=state, history=history,
                                       visits=visits, llm_calls=ctx.llm_calls,
                                       error=f"节点 {cursor} 被访问 {visits[cursor]} 次")
            node = self.nodes[cursor]
            if node.kind == "human" and "human_reply" not in state:
                answer = human.try_ask(node.title)
                if answer is not None:
                    state["human_reply"] = answer
            try:
                update = node.fn(state, ctx)
            except Interrupt as stop:                  # 挂起（第 ⑦ 节展开）
                state["pending_question"] = stop.question
                return SimpleNamespace(status="interrupted", state=state, history=history,
                                       visits=visits, llm_calls=ctx.llm_calls,
                                       error="", checkpoint=SimpleNamespace(
                                           graph=self.name, node=stop.resume_at or cursor,
                                           state=dict(state), visits=dict(visits),
                                           history=list(history), llm_calls=ctx.llm_calls))
            except Exception as exc:                   # 节点异常不外泄
                return SimpleNamespace(status="error", state=state, history=history,
                                       visits=visits, llm_calls=ctx.llm_calls,
                                       error=f"{type(exc).__name__}: {exc}")
            if update:
                state.update(update)
            if node.kind == "human":
                state.pop("human_reply", None)
            cursor = self._next(cursor, state)
        return SimpleNamespace(status="completed", state=state, history=history,
                               visits=visits, llm_calls=ctx.llm_calls, error="")

    def _next(self, cursor, state):
        for src, router, targets in self.conditionals:
            if src == cursor:
                key = router(state)
                if key not in targets:
                    raise ValueError(f"路由器在 {cursor} 返回了未定义分支 {key!r}")
                return targets[key]
        for src, dst in self.edges:
            if src == cursor:
                return dst
        return END


# ---------------- 业务数据 ----------------
ORDERS = {
    "A1001": {"status": "已发货", "carrier": "顺丰", "eta": "2025-01-05"},
    "A1002": {"status": "待付款", "carrier": "", "eta": ""},
}
FAQ = {"运费券": "运费券可用于抵扣下一次下单的运费，有效期 90 天，单笔订单限用一张。"}
FORBIDDEN_WORDS = ("绝对保证", "100%", "内部备注", "私下")
APPROVED_AMOUNTS = {"20"}


# ---------------- 假模型 ----------------
class DrafterLLM(LLM):
    """写话术的假模型：唯一一个"必须用模型"的节点。

    它有一个真实的坏习惯：**爱用绝对化措辞**（绝对保证）。
    这正是确定性合规检查存在的意义。
    """

    name = "drafter"

    def _complete(self, messages, **kwargs):
        brief = "\\n".join(m.content for m in messages if m.role == "user")
        tid = re.search(r"工单\\s*(\\S+)", brief)
        tid = tid.group(1) if tid else "T-0000"
        body = re.search(r"结论：(.+)", brief)
        decision = body.group(1).strip() if body else "已为您处理。"
        # 拿到人工修改意见后：删掉绝对化措辞、改成可验证的时限
        wording = "预计 24 小时内到账" if "人工修改意见" in brief else "绝对保证 24 小时内到账"
        return LLMResponse(text=(f"【工单 {tid} 回复】您好，非常抱歉给您带来不便。\\n"
                                 f"{decision}\\n相关补偿{wording}。如有其他问题请随时联系我们。"),
                           model=self.model)


class ClassifierLLM(LLM):
    name = "classifier"

    def _complete(self, messages, **kwargs):
        text = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return LLMResponse(text=("consult" if "券" in text else "logistics"), model=self.model)


# ---------------- 节点 ----------------
def rule_classify(text):
    rules = (("refund", ("退款", "退货", "不要了", "取消订单")),
             ("logistics", ("快递", "物流", "到哪", "什么时候到", "发货")),
             ("consult", ("怎么用", "怎么开", "有效期", "规则")))
    for label, words in rules:
        if any(w in text for w in words):
            return label
    return None


def node_intake(state, ctx):
    """入口：确定性输入校验（护栏在模型之前，脏数据连模型都碰不到）。"""
    text = str(state.get("text", "")).strip()
    if not text:
        return {"rejected": True, "reject_reason": "工单内容为空"}
    if len(text) > 200:
        return {"rejected": True, "reject_reason": "工单内容过长，疑似垃圾信息"}
    return {"rejected": False, "text": text}


def node_classify(state, ctx):
    label = rule_classify(state["text"])
    if label:
        return {"category": label, "classified_by": "规则（0 次模型调用）"}
    label = ctx.ask_llm([Message.system("你是工单分类器。只输出一个类别：refund / logistics / consult。"),
                         Message.user(state["text"])]).strip()
    return {"category": label, "classified_by": "模型（规则认不出来才用它）"}


def node_handle_refund(state, ctx):
    order = ORDERS.get(state.get("order_id", ""), {})
    status = order.get("status", "未知")
    if status == "待付款":
        decision = "您的订单尚未付款，已为您直接取消，不产生任何费用。"
    elif status == "已发货":
        decision = "您的订单已发货，可在签收后 7 天内申请退货，运费由我们承担。"
    else:
        decision = "未查询到该订单，请核对订单号后重试。"
    return {"decision": decision, "handled_by": "退款规则表"}


def node_handle_logistics(state, ctx):
    order = ORDERS.get(state.get("order_id", ""), {})
    if order.get("status") == "已发货":
        decision = f"您的包裹已由{order['carrier']}发出，预计 {order['eta']} 送达。"
    else:
        decision = "该订单还没有发货记录，请确认订单状态。"
    return {"decision": decision, "handled_by": "物流表"}


def node_handle_consult(state, ctx):
    for key, answer in FAQ.items():
        if key in state["text"]:
            return {"decision": answer, "handled_by": "FAQ 表"}
    return {"decision": "这个问题没有标准答案，已为您转接人工。", "handled_by": "转人工"}


def node_draft_reply(state, ctx):
    """写话术：**这才是真正需要模型的节点**（把结论翻译成得体的中文）。"""
    brief = f"工单 {state['ticket_id']}\\n结论：{state['decision']}"
    if state.get("revision_notes"):
        brief += f"\\n人工修改意见：{state['revision_notes']}"
    draft = ctx.ask_llm([Message.system("你是客服文案，把已确认的结论写成给客户的话，不要添加未确认的承诺。"),
                         Message.user(brief)])
    return {"draft": draft.strip()}


def node_compliance(state, ctx):
    """合规检查：**确定性的 6 行代码**，替代一个"模型自审"节点。"""
    draft = state.get("draft", "")
    issues = []
    for word in FORBIDDEN_WORDS:
        if word in draft:
            issues.append(f"出现禁用词「{word}」")
    for amount in re.findall(r"(\\d+)\\s*元", draft):
        if amount not in APPROVED_AMOUNTS:
            issues.append(f"出现未批准的金额承诺「{amount} 元」")
    if state["ticket_id"] not in draft:
        issues.append("回复中缺少工单号，无法归档")
    return {"compliance_issues": issues}


def node_human_review(state, ctx):
    reply = state.get("human_reply")
    if reply is None:
        raise Interrupt(f"草稿未通过合规检查：{state.get('compliance_issues')}，请人工审批",
                        resume_at="human_review")
    if reply.get("decision") == "approved":
        return {"human_decision": "approved", "human_note": reply.get("note", "")}
    return {"human_decision": "rejected", "revision_notes": reply.get("note", "请修改后重新提交")}


def node_finalize(state, ctx):
    return {"final_reply": state.get("draft", ""), "finished": True}


# ---------------- 路由器（纯函数） ----------------
def route_after_intake(state):  return "reject" if state.get("rejected") else "ok"
def route_by_category(state):   return state.get("category", "consult")
def route_after_compliance(state):  return "pass" if not state.get("compliance_issues") else "human"
def route_after_human(state):   return "approve" if state.get("human_decision") == "approved" else "revise"


# ---------------- 构图 ----------------
def build_graph(max_visits: int = 6):
    """客服工单处理图。**读这张图比读一千行 if/else 快得多** —— 这正是它的价值。"""
    g = StateGraph("客服工单处理", llm=DrafterLLM(), max_visits=max_visits)
    g.add_node("intake", node_intake, title="输入校验")
    g.add_node("classify", node_classify, title="分类（规则优先，模型兜底）")
    g.add_node("handle_refund", node_handle_refund, title="退款处理")
    g.add_node("handle_logistics", node_handle_logistics, title="物流处理")
    g.add_node("handle_consult", node_handle_consult, title="咨询处理（FAQ 查表）")
    g.add_node("draft_reply", node_draft_reply, kind="llm", title="撰写回复")
    g.add_node("compliance", node_compliance, title="合规检查")
    g.add_node("human_review", node_human_review, kind="human", title="人工审批")
    g.add_node("finalize", node_finalize, title="交付")
    g.set_entry("intake")
    g.add_conditional("intake", route_after_intake, {"ok": "classify", "reject": END}, "校验结果")
    g.add_conditional("classify", route_by_category,
                      {"refund": "handle_refund", "logistics": "handle_logistics",
                       "consult": "handle_consult"}, "按类别路由")
    for handler in ("handle_refund", "handle_logistics", "handle_consult"):
        g.add_edge(handler, "draft_reply")
    g.add_edge("draft_reply", "compliance")
    g.add_conditional("compliance", route_after_compliance,
                      {"pass": "finalize", "human": "human_review"}, "合规结果")
    g.add_conditional("human_review", route_after_human,
                      {"approve": "finalize", "revise": "draft_reply"}, "人工结论")
    g.add_edge("finalize", END)
    return g


# ---------------- 跑三类工单 ----------------
APPROVE = {"decision": "approved", "note": "合规已确认，可以发送"}
TICKETS = [
    {"ticket_id": "T-9001", "order_id": "A1002", "text": "我要退款，订单 A1002 我不想要了"},
    {"ticket_id": "T-9002", "order_id": "A1001", "text": "我的订单 A1001 快递到哪了？"},
    {"ticket_id": "T-9003", "order_id": "", "text": "请问运费券怎么用？"},
]

for ticket in TICKETS:
    r = build_graph().run(dict(ticket), human=HumanChannel([dict(APPROVE)]))
    print(f"{ticket['ticket_id']}  类别={r.state['category']:<10} 处理={r.state['handled_by']}")
    print(f"   分类方式：{r.state['classified_by']}")
    print(f"   路径    ：{ ' → '.join(r.history) }")
    print(f"   状态 / 模型调用：{r.status} / {r.llm_calls} 次")
    print()
print("★ 三条路径都是图里写死的分支，跑一百次都一样（可复现、可测试、可画给产品看）。")
print("★ 三条工单里，只有「撰写回复」这一步用了模型；分类全部命中关键词规则。")''')

    nb.md("""### 结果说明什么

- 三类工单**分别路由**到了正确的处理节点（`handle_refund` / `handle_logistics` / `handle_consult`）
- 每条路径都能被打印出来 —— 这就是"可审计"的具体形态
- 每条工单只有 1 次模型调用（写话术），分类 0 次（规则命中）

`T-9003` 那条路径值得多看一眼：它走的是 `handle_consult`（FAQ 查表）。
**有标准答案的问题，永远不要问模型。**

现在流程跑通了。但它还缺一样东西：**跑到一半挂了怎么办？**""")

    # ==================================================================
    section(nb, "⑦", "检查点：挂起、落盘、换个进程接着跑")

    nb.md("""### 现在卡在哪

上一节的 `human_review` 节点里有一句 `raise Interrupt(...)`。
它想表达的是"我需要人拍板"。

**但如果代码就地等人工答复，会发生什么？**

```
❌ 阻塞等待： while not answered: sleep(1)
   → 一个 Web 进程被一个请求钉死
   → 线程/连接池被占满 → 整个服务不可用

❌ 抛异常退出： raise RuntimeError
   → 已完成的 3 个节点全白跑，人工答复回来时只能从头再来
```

### 所以我需要「挂起 = 干净地退出 + 把现场存下来」

这就是**检查点（checkpoint）**：

```
   跑到 human_review，没有人工答复
        │
        ▼
   抛 Interrupt ──▶ 引擎保存 Checkpoint ──▶ 干净退出（status="interrupted"）
        │
        │  ……（进程可以重启、可以换机器、可以等 3 天）……
        ▼
   人工答复到达 ──▶ graph.resume(checkpoint, human=...) ──▶ 从断点继续
        │
        ▼
   已完成的节点**不会重跑**，已做过的判断**不会重新调用模型**
```

### 它给我什么

| 产物 | 用处 |
|---|---|
| `RunResult.status == "interrupted"` | 上层知道"这事没完，但在等外部输入" |
| `Checkpoint.to_json()` | **一个纯 JSON**，可以塞进 Redis / 数据库 / 消息队列 |
| `graph.resume(cp, human=...)` | 换一个进程、换一台机器，照样接着跑 |

前提只有一条：**state 必须是纯 JSON**（所以模型客户端走 `ctx`，不走 `state`）。

### 立刻跑一遍""")

    nb.code('''# 单独可运行：检查点与恢复（挂起 → 落盘 → 换进程续跑）
import sys, pathlib, re, json
from dataclasses import dataclass
from typing import Callable

ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message

END = "__end__"


class Interrupt(Exception):
    def __init__(self, question, resume_at=""):
        super().__init__(question)
        self.question, self.resume_at = question, resume_at


@dataclass
class Node:
    name: str
    fn: Callable
    kind: str = "deterministic"
    title: str = ""


@dataclass
class NodeContext:
    llm: object
    human: object
    llm_calls: int = 0

    def ask_llm(self, messages) -> str:
        self.llm_calls += 1
        return self.llm.complete(messages).text


@dataclass
class Checkpoint:
    graph: str
    node: str
    state: dict
    visits: dict
    history: list
    llm_calls: int

    def to_json(self, indent=None) -> str:
        return json.dumps({"graph": self.graph, "node": self.node, "state": self.state,
                           "visits": self.visits, "history": self.history,
                           "llm_calls": self.llm_calls}, ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text):
        d = json.loads(text)
        return cls(d["graph"], d["node"], d["state"], d["visits"], d["history"], d["llm_calls"])


@dataclass
class RunResult:
    status: str
    state: dict
    history: list
    visits: dict
    llm_calls: int
    checkpoint: "Checkpoint|None" = None
    error: str = ""

    @property
    def final_reply(self) -> str:
        return str(self.state.get("final_reply", ""))


class HumanChannel:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.asked = []

    def try_ask(self, question):
        self.asked.append(question)
        return self.replies.pop(0) if self.replies else None


class StateGraph:
    def __init__(self, name, llm=None, max_visits=6):
        self.name, self.llm, self.max_visits = name, llm, max_visits
        self.nodes, self.edges, self.conditionals, self.entry = {}, [], [], ""

    def add_node(self, name, fn, kind="deterministic", title=""):
        self.nodes[name] = Node(name, fn, kind, title or name); return self

    def add_edge(self, src, dst):
        self.edges.append((src, dst)); return self

    def add_conditional(self, src, router, targets, label=""):
        self.conditionals.append((src, router, targets)); return self

    def set_entry(self, name):
        self.entry = name; return self

    def run(self, state, human=None):
        return self._execute(self.entry, dict(state), {}, [], human or HumanChannel(), 0)

    def resume(self, checkpoint, human=None):
        """从检查点继续。★ 这是"另一个进程"也能干的事 —— 前提是 state 是纯 JSON。"""
        if checkpoint.graph != self.name:
            raise ValueError(f"检查点属于图 {checkpoint.graph!r}，不能喂给 {self.name!r}")
        return self._execute(checkpoint.node, dict(checkpoint.state), dict(checkpoint.visits),
                             list(checkpoint.history), human or HumanChannel(), checkpoint.llm_calls)

    def _execute(self, cursor, state, visits, history, human, llm_calls):
        ctx = NodeContext(llm=self.llm, human=human, llm_calls=llm_calls)
        while cursor != END:
            visits[cursor] = visits.get(cursor, 0) + 1
            history.append(cursor)
            if visits[cursor] > self.max_visits:
                return RunResult("max_visits", state, history, visits, ctx.llm_calls,
                                 error=f"节点 {cursor} 被访问 {visits[cursor]} 次")
            node = self.nodes[cursor]
            if node.kind == "human" and "human_reply" not in state:
                answer = human.try_ask(node.title)
                if answer is not None:
                    state["human_reply"] = answer
            try:
                update = node.fn(state, ctx)
            except Interrupt as stop:
                state["pending_question"] = stop.question
                cp = Checkpoint(self.name, stop.resume_at or cursor, dict(state),
                                dict(visits), list(history), ctx.llm_calls)
                return RunResult("interrupted", state, history, visits, ctx.llm_calls, checkpoint=cp)
            except Exception as exc:
                return RunResult("error", state, history, visits, ctx.llm_calls,
                                 error=f"{type(exc).__name__}: {exc}")
            if update:
                state.update(update)
            if node.kind == "human":
                state.pop("human_reply", None)
            cursor = self._next(cursor, state)
        return RunResult("completed", state, history, visits, ctx.llm_calls)

    def _next(self, cursor, state):
        for src, router, targets in self.conditionals:
            if src == cursor:
                return targets[router(state)]
        for src, dst in self.edges:
            if src == cursor:
                return dst
        return END


# ---------------- 节点（与上一节相同的业务逻辑） ----------------
ORDERS = {"A1001": {"status": "已发货", "carrier": "顺丰", "eta": "2025-01-05"}}
FORBIDDEN_WORDS = ("绝对保证", "100%", "内部备注")
APPROVED_AMOUNTS = {"20"}


class DrafterLLM(LLM):
    name = "drafter"

    def _complete(self, messages, **kwargs):
        brief = "\\n".join(m.content for m in messages if m.role == "user")
        tid = re.search(r"工单\\s*(\\S+)", brief)
        tid = tid.group(1) if tid else "T-0000"
        body = re.search(r"结论：(.+)", brief)
        decision = body.group(1).strip() if body else "已为您处理。"
        wording = "预计 24 小时内到账" if "人工修改意见" in brief else "绝对保证 24 小时内到账"
        return LLMResponse(text=(f"【工单 {tid} 回复】您好，非常抱歉给您带来不便。\\n"
                                 f"{decision}\\n相关补偿{wording}。如有其他问题请随时联系我们。"),
                           model=self.model)


def node_intake(state, ctx):
    text = str(state.get("text", "")).strip()
    return {"rejected": not text, "text": text}


def node_classify(state, ctx):
    return {"category": "logistics", "classified_by": "规则（0 次模型调用）"}


def node_handle_logistics(state, ctx):
    o = ORDERS.get(state.get("order_id", ""), {})
    return {"decision": f"您的包裹已由{o.get('carrier', '?')}发出，预计 {o.get('eta', '?')} 送达。",
            "handled_by": "物流表"}


def node_draft_reply(state, ctx):
    brief = f"工单 {state['ticket_id']}\\n结论：{state['decision']}"
    if state.get("revision_notes"):
        brief += f"\\n人工修改意见：{state['revision_notes']}"
    return {"draft": ctx.ask_llm([Message.system("把结论写成给客户的话，不要添加未确认的承诺。"),
                                  Message.user(brief)]).strip()}


def node_compliance(state, ctx):
    draft = state.get("draft", "")
    issues = [f"出现禁用词「{w}」" for w in FORBIDDEN_WORDS if w in draft]
    for amount in re.findall(r"(\\d+)\\s*元", draft):
        if amount not in APPROVED_AMOUNTS:
            issues.append(f"出现未批准的金额承诺「{amount} 元」")
    if state["ticket_id"] not in draft:
        issues.append("回复中缺少工单号，无法归档")
    return {"compliance_issues": issues}


def node_human_review(state, ctx):
    reply = state.get("human_reply")
    if reply is None:
        raise Interrupt(f"草稿未通过合规检查：{state.get('compliance_issues')}，请人工审批",
                        resume_at="human_review")
    if reply.get("decision") == "approved":
        return {"human_decision": "approved", "human_note": reply.get("note", "")}
    return {"human_decision": "rejected", "revision_notes": reply.get("note", "请修改后重新提交")}


def node_finalize(state, ctx):
    return {"final_reply": state.get("draft", ""), "finished": True}


def build_graph(max_visits=6):
    g = StateGraph("客服工单处理", llm=DrafterLLM(), max_visits=max_visits)
    g.add_node("intake", node_intake, title="输入校验")
    g.add_node("classify", node_classify, title="分类")
    g.add_node("handle_logistics", node_handle_logistics, title="物流处理")
    g.add_node("draft_reply", node_draft_reply, kind="llm", title="撰写回复")
    g.add_node("compliance", node_compliance, title="合规检查")
    g.add_node("human_review", node_human_review, kind="human", title="人工审批")
    g.add_node("finalize", node_finalize, title="交付")
    g.set_entry("intake")
    g.add_edge("intake", "classify")
    g.add_edge("classify", "handle_logistics")
    g.add_edge("handle_logistics", "draft_reply")
    g.add_edge("draft_reply", "compliance")
    g.add_conditional("compliance", lambda s: "pass" if not s.get("compliance_issues") else "human",
                      {"pass": "finalize", "human": "human_review"}, "合规结果")
    g.add_conditional("human_review", lambda s: "approve" if s.get("human_decision") == "approved" else "revise",
                      {"approve": "finalize", "revise": "draft_reply"}, "人工结论")
    g.add_edge("finalize", END)
    return g


TICKET = {"ticket_id": "T-9002", "order_id": "A1001", "text": "我的订单 A1001 快递到哪了？"}

# ---- 第一次运行：人工通道是空的（相当于"审批人不在线"） ----
first = build_graph().run(dict(TICKET), human=HumanChannel([]))
print("第一次运行 · 状态：", first.status)
print("第一次运行 · 停在哪：", first.checkpoint.node)
print("第一次运行 · 已走过的路径：", " → ".join(first.history))
print("第一次运行 · 模型调用：", first.llm_calls)
print()
print("挂起时保存的检查点（**这就是一个纯 JSON**，可以塞进 Redis / 数据库）：")
print(first.checkpoint.to_json(indent=2)[:520], "…")
print()

# ---- 模拟"进程重启"：全新的图对象 + 从磁盘读回来的检查点 ----
text = first.checkpoint.to_json()                    # 落盘（这里用字符串代替文件）
graph_b = build_graph()                              # 全新的引擎实例，内存里什么都没有
restored = Checkpoint.from_json(text)                # 从"磁盘"读回来
resumed = graph_b.resume(restored, human=HumanChannel([{"decision": "approved", "note": "合规已确认"}]))

print("恢复后 · 状态：", resumed.status)
print("恢复后 · 完整路径：", " → ".join(resumed.history))
print("恢复后 · 模型调用总数：", resumed.llm_calls, "（恢复过程新增", resumed.llm_calls - first.llm_calls, "次）")
print("恢复后 · classify 被访问次数：", resumed.visits.get("classify"), "次（没有重新分类）")
print()
print("最终对客回复：")
print(resumed.final_reply)
print()
print("★ 恢复过程中**一次模型调用都没发生**：分类结果、订单结论、草稿全都躺在检查点里。")
print("★ 注意这次人工点了「批准」，所以草稿里的「绝对保证」被放行了 ——")
print("  人工审批就是最后的责任关口。它要是选择驳回，就会走 revise 分支（下面就是）。")
print()
print("★ 但如果人工要求修改呢？—— 走 revise 分支回到 draft_reply，多花 1 次调用：")
fixed = build_graph().resume(Checkpoint.from_json(text),
                             human=HumanChannel([{"decision": "rejected",
                                                  "note": "删掉「绝对保证」，改成「预计」，并注明到账时限。"},
                                                 {"decision": "approved", "note": "已修改"}],
                                                ))
print("   完整路径：", " → ".join(fixed.history))
print("   模型调用：", fixed.llm_calls, "次")
print("   最终回复：", fixed.final_reply.replace("\\n", " ⏎ "))''')

    nb.md("""### 结果说明什么

| 观察点 | 说明 |
|---|---|
| `status == "interrupted"` | 挂起**不是崩溃** —— 它是一个可以被上层正常处理的返回 |
| `checkpoint.node == "human_review"` | 断点位置明确：恢复时从这个节点继续 |
| 恢复后 `classify` 只被访问 1 次 | 判断结果在检查点里，**没有重跑、没有重新调模型** |
| 路径里 `human_review` 出现两次 | 一次是抛 `Interrupt` 的那次，一次是恢复后结算的那次 |
| 要求修改后多 1 次模型调用 | 只有"按人工意见重写草稿"这一步是真需要重做的 |

前提再强调一遍：**state 必须是纯 JSON。**
把模型客户端、回调函数塞进 state 的代码，是恢复不了的 —— 因为 `json.dumps` 会当场报错。""")

    # ==================================================================
    section(nb, "⑧", "人工介入与循环保护")

    nb.md("""### 现在卡在哪

上一节我们看到"人工拒绝会回到 `draft_reply` 重写"。这条回边让图里出现了**环**。

于是两个自然的问题：

1. **有环是不是 bug？** —— 不是。人工拒绝 → 修订 → 重新合规，这是**流程本身的一部分**。
2. **那什么才是 bug？** —— **没有上限的环**。

### 所以：有环不是 bug，没有上限的环才是

```
   有点环的正常流程              没有出口的死循环
   draft_reply ──▶ compliance    draft_reply ──▶ compliance
        ▲              │              ▲              │
        └── revise ────┘              └──────────────┘
   （人一旦批准就会出去）          （永远出不去，每圈都在烧模型调用）
```

保护手段就是引擎里那句 `visits[cursor] > self.max_visits` ——
它和第 01 章的 `max_steps` 是同一个道理，只是保护的对象从"对话"变成了"流程"。

### 但上限只是"截断浪费"，真正要治的是病根

本章的演示场景是：**人工一直说"不行"，但不说怎么改**。

这种反馈**不可执行** —— 重写出来的草稿一字不变，流程原地打转。
用一条确定性规则就能从源头消灭它：**在 `human_review` 里强制校验"修改意见必填"**。

### 立刻跑一遍：人工拒绝 + 循环保护""")

    nb.code('''# 单独可运行：人工介入的回环 + 循环保护（max_visits）
import sys, pathlib, re
from dataclasses import dataclass
from typing import Callable

ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message

END = "__end__"
MAX_VISITS = 2          # ← 试着改这里：改成 1 会立刻停机；改成 10 会多烧几次模型调用


class Interrupt(Exception):
    def __init__(self, question, resume_at=""):
        super().__init__(question)
        self.question, self.resume_at = question, resume_at


@dataclass
class Node:
    name: str
    fn: Callable
    kind: str = "deterministic"
    title: str = ""


@dataclass
class NodeContext:
    llm: object
    human: object
    llm_calls: int = 0

    def ask_llm(self, messages) -> str:
        self.llm_calls += 1
        return self.llm.complete(messages).text


class HumanChannel:
    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.asked = []

    def try_ask(self, question):
        self.asked.append(question)
        return self.replies.pop(0) if self.replies else None


class StateGraph:
    def __init__(self, name, llm=None, max_visits=MAX_VISITS):
        self.name, self.llm, self.max_visits = name, llm, max_visits
        self.nodes, self.edges, self.conditionals, self.entry = {}, [], [], ""

    def add_node(self, name, fn, kind="deterministic", title=""):
        self.nodes[name] = Node(name, fn, kind, title or name); return self

    def add_edge(self, src, dst):
        self.edges.append((src, dst)); return self

    def add_conditional(self, src, router, targets, label=""):
        self.conditionals.append((src, router, targets)); return self

    def set_entry(self, name):
        self.entry = name; return self

    def run(self, state, human=None):
        return self._execute(self.entry, dict(state), {}, [], human or HumanChannel(), 0)

    def _execute(self, cursor, state, visits, history, human, llm_calls):
        from types import SimpleNamespace
        ctx = NodeContext(llm=self.llm, human=human, llm_calls=llm_calls)
        while cursor != END:
            visits[cursor] = visits.get(cursor, 0) + 1
            history.append(cursor)
            if visits[cursor] > self.max_visits:        # ★ 循环保护
                return SimpleNamespace(status="max_visits", state=state, history=history,
                                       visits=visits, llm_calls=ctx.llm_calls,
                                       error=f"节点 {cursor} 被访问 {visits[cursor]} 次，"
                                             f"超过上限 {self.max_visits}")
            node = self.nodes[cursor]
            if node.kind == "human" and "human_reply" not in state:
                answer = human.try_ask(node.title)
                if answer is not None:
                    state["human_reply"] = answer
            try:
                update = node.fn(state, ctx)
            except Interrupt as stop:
                return SimpleNamespace(status="interrupted", state=state, history=history,
                                       visits=visits, llm_calls=ctx.llm_calls, error="")
            except Exception as exc:
                return SimpleNamespace(status="error", state=state, history=history,
                                       visits=visits, llm_calls=ctx.llm_calls,
                                       error=f"{type(exc).__name__}: {exc}")
            if update:
                state.update(update)
            if node.kind == "human":
                state.pop("human_reply", None)
            cursor = self._next(cursor, state)
        return SimpleNamespace(status="completed", state=state, history=history,
                               visits=visits, llm_calls=ctx.llm_calls, error="")

    def _next(self, cursor, state):
        for src, router, targets in self.conditionals:
            if src == cursor:
                return targets[router(state)]
        for src, dst in self.edges:
            if src == cursor:
                return dst
        return END


class DrafterLLM(LLM):
    name = "drafter"

    def _complete(self, messages, **kwargs):
        brief = "\\n".join(m.content for m in messages if m.role == "user")
        # ★ 关键：只有拿到「人工修改意见」才改措辞；空意见 → 输出一字不变
        wording = "预计 24 小时内到账" if "人工修改意见：" in brief and brief.split("人工修改意见：")[-1].strip() else "绝对保证 24 小时内到账"
        return LLMResponse(text=(f"【工单 T-9002 回复】您好。\\n相关补偿{wording}。"), model=self.model)


def node_draft_reply(state, ctx):
    brief = f"工单 {state['ticket_id']}\\n结论：{state.get('decision', '已为您处理。')}"
    if state.get("revision_notes"):
        brief += f"\\n人工修改意见：{state['revision_notes']}"
    return {"draft": ctx.ask_llm([Message.system("把结论写成给客户的话。"), Message.user(brief)]).strip()}


def node_compliance(state, ctx):
    return {"compliance_issues": [f"出现禁用词「{w}」" for w in ("绝对保证",) if w in state.get("draft", "")]}


def node_human_review(state, ctx):
    reply = state.get("human_reply")
    if reply is None:
        raise Interrupt("草稿未通过合规检查，请人工审批", resume_at="human_review")
    if reply.get("decision") == "approved":
        return {"human_decision": "approved"}
    return {"human_decision": "rejected", "revision_notes": reply.get("note", "请修改后重新提交")}


def node_finalize(state, ctx):
    return {"final_reply": state.get("draft", ""), "finished": True}


def build_graph(max_visits=MAX_VISITS):
    g = StateGraph("客服工单处理", llm=DrafterLLM(), max_visits=max_visits)
    g.add_node("draft_reply", node_draft_reply, kind="llm", title="撰写回复")
    g.add_node("compliance", node_compliance, title="合规检查")
    g.add_node("human_review", node_human_review, kind="human", title="人工审批")
    g.add_node("finalize", node_finalize, title="交付")
    g.set_entry("draft_reply")
    g.add_edge("draft_reply", "compliance")
    g.add_conditional("compliance", lambda s: "pass" if not s.get("compliance_issues") else "human",
                      {"pass": "finalize", "human": "human_review"})
    g.add_conditional("human_review", lambda s: "approve" if s.get("human_decision") == "approved" else "revise",
                      {"approve": "finalize", "revise": "draft_reply"})
    g.add_edge("finalize", END)
    return g


TICKET = {"ticket_id": "T-9002", "order_id": "A1001", "text": "我的订单 A1001 快递到哪了？"}

# ---- 场景 A：人工给出**可执行**的修改意见 → 一次就改好 ----
good = {"decision": "rejected", "note": "删掉「绝对保证」，改成「预计」，并注明到账时限。"}
r_good = build_graph().run(dict(TICKET), human=HumanChannel([dict(good), {"decision": "approved"}]))
print("A 人工给出可执行意见：")
print("   路径：", " → ".join(r_good.history))
print("   模型调用：", r_good.llm_calls, "次（写草稿 + 按意见重写）")
print("   最终回复：", r_good.state.get("final_reply", "").replace("\\n", " ⏎ "))
print()
print("★ 人工拒绝 → 走 revise 分支回到 draft_reply → 重新合规 → 通过 → 交付。")
print("  这条回环是**图里的边**，不是靠模型「想起来要改」。")
print()

# ---- 场景 B：人工只说"不行"，不说怎么改 → 流程原地打转 ----
vague = {"decision": "rejected", "note": ""}          # ← 注意 note 是空的
r_bad = build_graph().run(dict(TICKET), human=HumanChannel([dict(vague)] * 8))
print("B 人工只说不行、不说怎么改：")
print("   运行状态：", r_bad.status)
print("   停机原因：", r_bad.error)
print("   路径：", " → ".join(r_bad.history))
print("   模型调用：", r_bad.llm_calls, "次（被上限截断了，没有无限放大）")
print()
print("★ max_visits 生效：人工一直拒绝也不会把流程卡死或烧穿账单。")
print("★ 注意最终 status 是 max_visits 而不是 completed ——")
print("  **失败要能被上层看见**，不能假装成功。")
print()
print("★ 但更好的做法是**从源头堵住**：在 human_review 里强制校验「修改意见必填」，")
print("  空的直接打回。用一条确定性规则消灭一整类空转 ——")
print("  又是那句话：能用代码解决的，绝不用模型。")''')

    nb.md("""### 结果说明什么

| 场景 | 人工输入 | 结果 |
|---|---|---|
| A | 「删掉绝对保证，改成预计」 | 一次修订即通过，`status=completed` |
| B | 「不行」（空意见） | 草稿一字未变 → 原地打转 → 被 `max_visits` 强制停机 |

场景 B 是本章最值得记住的一课：

> **不可执行的反馈不产生任何进展。**（第 07 章讲过同一件事）
>
> 而治它的办法不是"把上限调大"，而是**在流程里加一条规则**：
> 修改意见为空就不许提交。这又是一次"用确定性代码解决"。

顺便，把这三节的引擎能力放在一起看：

| 能力 | 靠什么实现 | 它在生产里对应什么 |
|---|---|---|
| 条件路由 | `router(state) -> str` 纯函数 | 业务分支（可画、可测） |
| 循环保护 | `visits` + `max_visits` | 防止流程空转烧钱 |
| 挂起与恢复 | `Interrupt` + `Checkpoint`（纯 JSON） | 断点续跑、人工介入、跨进程 |
| 异常不外泄 | 引擎里的 `except Exception` | 节点崩了不影响宿主进程 |
| 可审计 | `history` / `visits` | 排障第一步："它走了哪条路" |""")

    # ==================================================================
    section(nb, "⑨", "常见坑汇总")

    pitfall_table(nb, [
        ("让模型输出 `next_node`", "流程变成一张随机图，没有测试能覆盖", "路由写成纯函数 `router(state) -> str`"),
        ("把流程藏在提示词里", "不可复现、不可中断、不可审计", "把流程画成显式的图"),
        ("`state` 里塞模型客户端", "`json.dumps` 当场报错，检查点直接失效", "运行期资源走 `ctx`"),
        ("节点返回整个 state", "并发、回放、审计都难做，还会互相覆盖",
         "节点只返回增量 `{改了什么}`"),
        ("把合规/分类全交给模型", "不稳定、不可测、还要花钱", "规则优先，模型兜底"),
        ("有环就当 bug 删掉", "把「人工拒绝 → 修订」这类正常回环删了",
         "有环正常，**没有上限的环**才是 bug"),
        ("人工介入用 `input()`", "把 Web 进程钉死，连接池被占满", "落盘 + 回调（`Interrupt` + `Checkpoint`）"),
        ("人工拒绝没有修改意见", "草稿一字未变，流程空转烧钱",
         "在节点里强制校验「修改意见必填」"),
        ("检查点里没有 `visits`/`history`", "恢复后无法判断「这一步做过没有」",
         "把访问计数与路径一起存"),
        ("图的问题等运行才发现", "半夜炸在某个请求里", "`validate()` 跑在构建期 / CI"),
    ])

    summary(nb, [
        "**能用确定性代码解决的，绝不用模型。** 本章 9 个节点里只有 1 个真的需要模型。",
        "**流程骨架是显式的图**：节点（做什么）+ 边（下一步去哪）+ 状态（记住什么）。",
        "**路由是代码，不是模型输出。** 把控制流交给概率，等于放弃可测试性。",
        "**`state` 与 `ctx` 严格分离。** 这条纪律决定的不是代码好不好看，而是**能不能断点续跑**。",
        "**节点返回增量**，不返回整个 state —— 并发、回放、审计都靠这一条。",
        "**有环不是 bug，没有上限的环才是。** 而比上限更好的，是从源头消灭不可执行的反馈。",
        "**挂起要干净地退出**：`Interrupt` → 纯 JSON 检查点 → 换进程 `resume`，已完成的节点不重跑。",
        "**给 Agent 多少自由度是架构决策**，不是模型能力问题。",
    ], "第 10 章要回答一个更难的问题：**你凭什么说这次改动让系统变好了？**"
       "本章我们写了很多「规则」和「护栏」，但它们到底是提升了效果，"
       "还是只是让你感觉良好？—— 那需要一份评估集和一套可复现的运行。")

    exercises(nb, [
        ("**把护栏拆掉，观察会发生什么（必做）。**\n\n"
         "把第 ⑧ 节的 `MAX_VISITS` 从 2 改成 100，用「只说不行、不说怎么改」的人工重跑场景 B。\n\n"
         "观察 `draft_reply` 被访问了几次、模型调用涨到几次。然后再改回 2。",
         "每一次 `draft_reply` 都是一次真实的模型调用。\n\n"
         "改回 2 之后请回答一句话：`max_visits` 到底在保护什么？\n"
         "（提示：它保护的不是「正确性」，而是「错误发生时的最大代价」。）"),

        ("**在 `human_review` 里强制「修改意见必填」（必做）。**\n\n"
         "拒绝但 `note` 为空时，直接抛 `Interrupt` 或返回一条错误，让流程不进入 `revise` 分支。\n\n"
         "重跑场景 B，确认它不再空转（`draft_reply` 只被访问 1 次）。",
         "在 `node_human_review` 里加：\n\n"
         "```python\n"
         "if reply.get('decision') != 'approved' and not reply.get('note', '').strip():\n"
         "    raise Interrupt('驳回必须写明修改意见', resume_at='human_review')\n"
         "```\n\n"
         "这就是「用一条确定性规则消灭一整类空转」。"),

        ("**把 `handle_consult` 换成模型，量一量代价。**\n\n"
         "现在的咨询处理是 FAQ 查表（0 次调用）。改成调用模型回答同样的问题，\n"
         "对比 `llm_calls` 和两次运行的结果一致性。",
         "跑两次同样的工单，看模型两次的回答是否字字相同。\n\n"
         "合规部门会喜欢哪一个？（提示：一个「每次说法都不一样」的客服系统，"
         "连话术审核都没法做。）"),

        ("**加一个「超时升级」节点。**\n\n"
         "新增节点 `escalate`：当 `visits['human_review'] >= 2`（人工两次没拍板）时，\n"
         "条件边路由到它，把工单交给主管并结束流程。",
         "改 `human_review` 的路由函数，加一条 `escalate` 分支。\n\n"
         "别忘了新节点要能走到 `END`，否则 `validate()` 会报「无法到达 END」——\n"
         "这正是构建期校验的价值。"),

        ("**让检查点真的落盘。**\n\n"
         "把 `Checkpoint.to_json()` 写进文件，再从文件读回来恢复。\n"
         "然后**故意在恢复前改掉图的结构**（比如删掉一个节点），观察 `resume()` 会怎么报错。",
         "生产系统里这叫「版本漂移」：检查点是用旧版图存的，新版图已经不一样了。\n\n"
         "标准做法是在检查点里存一个 `graph_version` 并做兼容校验 ——\n"
         "否则你会得到一个「能恢复、但恢复出来的状态没人认识」的诡异 bug。"),
    ])

    checkpoint(nb, "09")

    return nb
