"""第 08 章 · 多智能体协作 —— Notebook 内容（逐步推进版）。

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


def build_08() -> Notebook:
    """第 08 章 · 多智能体协作（逐步推进版）。"""
    nb = Notebook("第 08 章 · 多智能体协作")

    header(
        nb, "08", "多智能体协作",
        "多智能体 = `角色分工` + `消息传递` + `结果仲裁`。\n"
        "收益来自**专业化与上下文隔离**，代价是**通信开销与不可控性**。\n"
        "先说结论：**多智能体不是自动更好** —— 一个 Agent 能干的事，别上三个。",
    )

    objectives(nb, [
        "说清「一个 Agent 什么都干」为什么会漏掉条款里的例外，并判断自己的场景该不该分工",
        "画出三种协作形态，说明为什么「共享上下文 + 自由讨论」又贵又脏",
        "亲手写一个消息总线（`Envelope` + `MessageBus`），解释「总线只投递、不做智能」",
        "解释「隔离是结构问题、不是提示词问题」—— 专家的上下文入口为什么只有一个",
        "写一个**确定性**仲裁器（if/else），并说清为什么不能让模型当裁判",
        "说清「传结论、不传上下文」与「结构化汇报 + 挑字段转发」怎么同时省钱和防泄露",
        "说出专家互相踢皮球时，除了轮数上限还需要什么（触顶后的兜底行为）",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

第 07 章结束时，你手上是一个"什么都能干"的 Agent。于是很自然地会想：

> **能不能让懂条款的人专门管条款？**

可以。但这一章的一半篇幅要用来讲**它的账单**。顺序是：

```
① 先看「一个 Agent 什么都干」的真实输出 —— 它有 4 个合规问题
② 想分工，但先看清三种协作形态，以及为什么我们要选「主管 + 隔离专家」
③ 分工要"传话" → 就地讲消息总线（Envelope / MessageBus）
④ 每个专家怎么做到「只看自己该看的」→ 就地讲 Worker 与结构化汇报
⑤ 主管怎么分解、分派、仲裁 → 跑通一支完整的团队，并验收隔离
⑥ 亲手把它搞坏一次：共享上下文 + 自由讨论（污染 / 膨胀 / 泄密）
⑦ 专家互相踢皮球怎么办 → 就地讲轮数上限，以及触顶后的兜底
```

每个知识点都出现在**你正好需要它**的时候，而不是提前堆在开头。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `dataclass` | 标准库 `dataclasses` | 自动生成 `__init__` / `__repr__` 的类装饰器 | `@dataclass` / `@dataclass(frozen=True)` |
| `field` | 标准库 `dataclasses` | 给字段设默认值（尤其是可变默认值） | `facts: dict = field(default_factory=dict)` |
| `re.findall` | 标准库 `re` | 找出**所有**匹配 | `re.findall(模式, 文本, re.M)` → `list[str]` |
| `collections.Counter` | 标准库 `collections` | 数数 | `Counter(["a","a","b"])` → `Counter({'a': 2, 'b': 1})` |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `Message` | `core.message` | 一条消息（`.role` / `.content`）。有 `.system()` / `.user()` 等构造方法 |
| `Agent` | `core` 顶层 | 框架版完整 Agent（本章不用它 —— 我们要自己搭协作层） |

### 随时可查

```python
explain(Message)     # 字段逐个说明
explain()            # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "先看问题：一个 Agent 什么都干")

    nb.md("""### 要做什么

先确认一件事：**"一个 Agent 什么都干"到底会坏在哪。**
不是"感觉它不够聪明"，而是要有可观察、可复现的坏结果。

### 场景：一张真实的客诉工单

```
工单 T-2025-0117：李先生投诉「说好 1 月 5 日送到，现在还没到，我要赔付！」
订单 A1001：已发货 / 顺丰 SF1234567890 / 承诺 2025-01-05
           实际 2025-01-06 到达（延迟 24 小时，轨迹正常）
赔付条款：
  A-1  待付款或已取消                        → 无需赔付
  A-2  已发货且超承诺日 72 小时、无物流轨迹   → 现金赔付 50 元
  B-2  已发货且轨迹正常、延迟 ≤ 48 小时       → 不现金赔付；补偿 20 元运费券
```

正确答案显然是 **B-2：补 20 元运费券**（延迟 24 小时 ≤ 48 小时，且轨迹正常）。

### 现在就跑一遍，看单 Agent 给出什么

下面这一格把"业务事实 + 单 Agent 的典型输出 + 合规检查"放在一起。
**合规检查是确定性代码**（由合规部门定义，不是模型说了算）——
这一点很重要，第 09 章会把它上升成"能用代码解决的绝不用模型"。""")

    nb.code('''# 单独可运行：单 Agent 一把梭（本章的基线）
# ---- 业务事实：一张真实的客诉工单 ----
TICKET = {
    "ticket_id": "T-2025-0117",
    "order_id": "A1001",
    "customer": "李先生",
    "complaint": "说好 1 月 5 日送到，现在还没到，我要赔付！",
}

ORDER = {
    "order_id": "A1001",
    "status": "已发货",
    "carrier": "顺丰",
    "tracking": "SF1234567890",
    "eta": "2025-01-05",          # 承诺送达日
    "trace": "2025-01-06 09:20 到达本市网点（轨迹正常，延迟 24 小时）",
    "delay_hours": 24,            # 实际延迟小时数
    # ★ 这一条是"不该给客户看到"的信息。后面第 ⑥ 节会用它检验隔离有没有生效。
    "internal_note": "内部备注：该承运商本月已有 3 起同类延误（内部数据，勿外传）",
}

# 赔付条款：正确答案是 B-2（延迟 24 小时 ≤ 48 小时，且轨迹正常）
POLICY_RULES = [
    ("A-1", "订单状态为「待付款」或「已取消」", "无需赔付"),
    ("A-2", "状态为「已发货」且超过承诺日 72 小时、物流无轨迹", "现金赔付 50 元"),
    ("B-2", "状态为「已发货」且轨迹正常、仅延迟不超过 48 小时", "不现金赔付；补偿 20 元运费券"),
]

# ---- 单 Agent 的典型输出（真实项目里这段文字来自模型，这里写成常量便于复现）----
# 它记住了"延误赔 50 元"这条最醒目的规则，却漏掉了 B-2 的例外条件。
SINGLE_AGENT_REPLY = (
    f"【工单 {TICKET['ticket_id']} 回复】{TICKET['customer']}您好，非常抱歉。"
    f"经核实订单 {TICKET['order_id']} 存在延误，按赔付规则我们将在 3 个工作日内现金赔付 50 元。"
    f"（{ORDER['internal_note']}）"
)


def verify_reply(text: str) -> list:
    """对客回复的硬性合规检查（确定性代码，0 次模型调用）。

    参数 text：准备发给客户的回复
    返回    ：不合规项列表（**空列表 = 可以发送**）
    """
    issues = []
    if TICKET["ticket_id"] not in text:
        issues.append("缺少工单号，无法归档")
    if "B-2" not in text:
        issues.append("未引用条款编号，处理依据不可溯源")
    if "50 元" in text or "现金" in text:
        issues.append("出现未经批准的现金赔付承诺（应按 B-2 补偿运费券）")
    if "运费券" not in text:
        issues.append("未给出正确的补偿方案（20 元运费券）")
    if "内部" in text or "勿外传" in text:
        issues.append("泄露内部备注（数据外泄事故）")
    return issues


print("单 Agent 的输出：")
print("   ", SINGLE_AGENT_REPLY)
print()
issues = verify_reply(SINGLE_AGENT_REPLY)
print(f"合规检查：不通过（{len(issues)} 项）")
for i in issues:
    print("   -", i)
print()
print("★ 它并不笨：它算对了「有延误」，只是漏掉了 B-2 的例外条件。")
print("★ 更严重的是第 4 条 —— 内部备注被写进了给客户的话术，这是数据外泄事故。")''')

    nb.md("""### 结果说明什么

四个问题，按严重程度排列：

| # | 问题 | 性质 |
|---|---|---|
| 1 | 记错条款 —— 记住了显眼的 A-2，漏掉了 B-2 的例外 | 效果问题 |
| 2 | 没引用条款编号，处理依据不可溯源 | 可审计性问题 |
| 3 | **把内部备注写进了对客话术** | **数据外泄事故** |
| 4 | 顺序不可控：这次先查订单再道歉，下次可能反过来 | 可运维性问题 |

### 根因不是"模型笨"

根因是：**数据、条款、话术全挤在同一个上下文里，注意力被摊薄了。**

这句话很关键，因为它直接指出了解法：**能不能让懂条款的人专门管条款？**
—— 但先别急着上多智能体，我们得先看清楚"分工"这件事有几种做法。""")

    # ==================================================================
    section(nb, "②", "分工之前：三种协作形态，先算账")

    nb.md("""### 现在卡在哪

"让懂条款的专门管条款"这个念头是对的，但它可以落成**三种完全不同的结构**，
成本和风险差得非常远：

```
① 单 Agent 一把梭（上一节的基线）
   ┌────────────────────────────────┐
   │  订单数据 + 条款 + 话术规范     │──▶ 1 次调用 ──▶ 回复
   └────────────────────────────────┘
   便宜，但注意力摊薄 → 专业判断容易错

② 共享上下文 + 自由讨论（反面教材）
   ┌──────────────────────────────────────────────┐
   │  一块共享草稿纸：所有人往上写，所有人读全部    │
   │  数据专家 ↔ 政策专家 ↔ 文案专家 ↔ ……          │
   └──────────────────────────────────────────────┘
   贵（上下文随轮次膨胀），而且会**互相污染**

③ 主管 + 隔离专家（本章的正解）
              ┌────────────┐
              │  Supervisor │  只做：分解 / 分派 / 仲裁
              └──┬───┬───┬──┘
        ┌────────┘   │   └────────┐
        ▼            ▼            ▼
   ┌─────────┐  ┌─────────┐  ┌─────────┐
   │ 数据专家 │  │ 政策专家 │  │ 文案专家 │   各自独立的上下文
   │ 订单数据 │  │ 条款表   │  │ 话术规范 │   互不可见
   └─────────┘  └─────────┘  └─────────┘
        └────────────┴────────────┘
              只传「结论」，不传「上下文」
```

### 为什么②一定更贵

因为它违反了"Agent 每次调用都要重发全部历史"这条铁律（第 01 章讲过）。
共享讨论里，**第 i 个发言人要重读前面所有人的发言**，所以：

```
第 1 次调用：读 1 份材料
第 2 次调用：读 1 份材料 + 第 1 个人的发言
第 3 次调用：读 1 份材料 + 前 2 个人的发言
……
总 token ≈ O(轮数²)
```

### 立刻算一遍这笔账

先算账再动手，是这一章的第一个工程习惯。下面这一格是**估算模型**（不是精确测量），
但它给出的量级关系是真的：""")

    nb.code('''# 单独可运行：分工的账，先算清楚再动手
EXPERT_COUNT = 3        # ← 试着改成 5、8：专家越多，下面两个数字怎么变？
SHARED_ROUNDS = 2       # ← 试着改成 3、5：共享讨论多一轮，成本涨多少？

# 各段文本的典型长度（字符）。真实项目里这些数字来自你的提示词，量一下就知道。
SYSTEM_CHARS = 60       # 每个专家的岗位说明书
TASK_CHARS = 40         # 主管给的子任务
FACT_CHARS = 120        # 主管随附的结构化事实
SPEECH_CHARS = 90       # 每个专家一次发言的长度

# ---- 形态③：主管 + 隔离专家 ----
# 每个专家只被调用一次，每次只读「自己的说明书 + 主管给的子任务」
isolated_calls = EXPERT_COUNT
isolated_chars = EXPERT_COUNT * (SYSTEM_CHARS + TASK_CHARS + FACT_CHARS)

# ---- 形态②：共享上下文 + 自由讨论 ----
# 第 i 次调用要重读此前所有人的发言 → 上下文随调用序号线性增长
shared_calls = EXPERT_COUNT * SHARED_ROUNDS
base = SYSTEM_CHARS + TASK_CHARS          # 共享草稿纸的初始内容
sizes = [base + i * SPEECH_CHARS for i in range(shared_calls)]
shared_chars = sum(sizes)

print(f"形态③ 主管 + 隔离专家：{isolated_calls} 次调用，合计 {isolated_chars} 字符")
print(f"形态② 共享上下文讨论：{shared_calls} 次调用，合计 {shared_chars} 字符")
print()
print("共享讨论里，每次调用要重读的历史：")
for i, s in enumerate(sizes, 1):
    print(f"   第 {i} 次调用：{s} 字符")
print()
print(f"成本倍数：{shared_chars / isolated_chars:.2f} 倍")
print()
print("★ 先说清楚：上面是**估算模型**（各段长度取的是典型值），不是精确测量。")
print("  重点不是绝对值，而是增长方式：")
print("  隔离版随专家数**线性**增长；共享版随轮数**平方级**增长。")
print("  团队一大、讨论一久，共享上下文就会先撞上下文窗口，再撞你的预算。")
print("  （第 ⑤ 节你会看到一份真实的账：3 次调用 / 每个专家只读自己那两块。）")''')

    nb.md("""### 结论：三种形态的取舍

| | 单 Agent | 共享讨论 | 主管 + 隔离专家 |
|---|---|---|---|
| 模型调用 | 1 | 3 × 轮数 | 专家数 |
| 上下文增长 | 常数 | **平方级** | 线性 |
| 结论正确性 | 漏条款例外 | 容易被先发言的人锚定 | 可溯源（引用条款编号） |
| 数据外泄风险 | 高（全都在一个上下文里） | 高 | 低（结构化字段可控） |
| 可替换性 | 牵一发动全身 | 无边界 | 换掉政策专家即可 |

**还有一个更根本的问题**：形态②里，谁先说话谁就定义了讨论的起点。
一条早期的错误草稿会变成所有人的"共识"—— 第 ⑥ 节会现场演示这件事。

所以本章要做的是**形态③**。它需要两个零件：一个负责"传话"，一个负责"干活"。""")

    # ==================================================================
    section(nb, "③", "分工要传话：消息总线")

    nb.md("""### 现在卡在哪

一旦有了多个角色，就冒出一个新问题：**谁把什么告诉了谁？**

这不是"随手 `print` 一下"能解决的。多智能体最难查的 bug 就是这类：
主管明明拿到了干净的数据，但转发的时候把不该给的东西也一起转发了 ——
而且**最终答案看起来还是对的**，你根本不知道泄露发生在哪一步。

### 所以我需要一个「只投递、只记账」的东西

它就是**消息总线**（message bus）。关键在于它的定位：

> **总线不做任何智能。** 它不总结、不筛选、不改写 —— 只负责"投递 + 留痕"。
> 一旦总线开始"智能地"改内容，你就再也说不清到底传了什么。

### 它的用法

我们要两个数据结构：

| 名字 | 是什么 | 关键字段 |
|---|---|---|
| `Envelope` | 一个"信封"：一条消息 | `sender` / `recipient` / `topic` / `payload` / `round` |
| `MessageBus` | 信封的账本 | `.log`（全部消息）/ `.send(env)` / `.to(收件人)` |

用 `dataclass` 而不是裸 `dict`，是因为字段名会被写错 ——
`env.recipient` 写错立刻报错，`env["recipiant"]` 只会在运行时悄悄给你一个 KeyError。
（`frozen=True` 表示"发出去的信封不可改"，防止有人事后篡改留痕。）

### 立刻用一次""")

    nb.code('''# 单独可运行：消息总线 —— 只投递、只记账，不做任何智能
from dataclasses import dataclass


@dataclass(frozen=True)
class Envelope:
    """一条消息。生产系统里它还必须带：唯一 id、时间戳、trace_id、重试次数。"""

    sender: str
    recipient: str
    topic: str        # task / result / question / arbitration
    payload: str
    round: int = 1    # 第几轮（踢皮球时用来判断"该喊停了"）

    def render(self) -> str:
        """给人看的一行摘要 —— 日志、报错、演示都用它。"""
        return f"[R{self.round}] {self.sender} → {self.recipient} ({self.topic}) {self.payload}"


class MessageBus:
    """消息总线：只负责投递与记账。

    两个设计要点：
      1. 消息是**显式**的：谁发给谁、什么主题、第几轮，全都留痕（可审计、可回放）；
      2. 总线**不共享上下文**：投递的是"结论"，不是"对方的完整思考过程"。
         这一条是多智能体能不能省钱、能不能不互相污染的**分水岭**。
    """

    def __init__(self) -> None:
        self.log: list = []          # 全部信封，按发生顺序

    def send(self, env: Envelope) -> Envelope:
        """投递一条消息（这里就是"追加到账本"，真实系统里才是走网络）。"""
        self.log.append(env)
        return env

    def to(self, recipient: str) -> list:
        """按收件人过滤 —— 排障时最常用的一句话：「发给政策专家的到底是哪几条？」"""
        return [e for e in self.log if e.recipient == recipient]

    def topics(self) -> list:
        return [e.topic for e in self.log]

    def __len__(self) -> int:
        return len(self.log)


# ---- 试一下：手工发几条消息 ----
bus = MessageBus()
bus.send(Envelope("supervisor", "data", "task", "请核实订单 A1001 的物流事实。"))
bus.send(Envelope("data", "supervisor", "result", "订单数据已核实：状态已发货、延迟 24 小时。"))
bus.send(Envelope("supervisor", "policy", "task", "请依据条款判断本单处理方案。（随附事实 6 项）"))
bus.send(Envelope("policy", "supervisor", "result", "结论：不现金赔付；补偿 20 元运费券（依据条款 B-2）"))

print("总线上的完整记录：")
for env in bus.log:
    print("   ", env.render())
print()
print("发给 data 的消息条数：", len(bus.to("data")))
print("全部消息条数：", len(bus), "（实现了 __len__，所以 len(bus) 直接可用）")
print()
print("★ 现在「主管有没有把内部备注转发给政策专家」是一行代码就能回答的问题：")
print("   ", any("内部备注" in e.payload for e in bus.to("policy")))''')

    nb.md("""### 结果说明什么

- 总线上跑的是**结论**（"状态已发货、延迟 24 小时"），不是某个专家的完整输出
- 每条消息都带 `sender` / `recipient` / `topic` / `round` —— 出事的顺序、方向、轮次一目了然
- `any("内部备注" in e.payload for e in bus.to("policy"))` 这一行就是**隔离的断言**。
  第 ⑧ 节（练习）会让你故意把它变成 `True`，看会发生什么

现在总线和"传话"都有了。下一个问题：专家拿到消息之后，**怎么保证它只看得到自己该看的？**""")

    # ==================================================================
    section(nb, "④", "专家：上下文入口只有一个")

    nb.md("""### 现在卡在哪

一个自然的做法是：给每个专家一个系统提示词，然后**把整段对话历史都发给它**，
再在提示词里叮嘱一句"你只负责条款，别管别的"。

**这是新手最容易犯的错。** 因为：

```
系统提示词 ┐
完整历史   ├─→ 拼成同一个字符串 → 模型
别人的发言 ┘
```

模型没有任何物理手段区分"这句是给我的岗位说明"和"这句是别人随口说的"。
你在提示词里写"别管别的"，只是在**请求**它，不是在**限制**它。

### 所以我需要一个「结构上就拿不到」的设计

关键词是**结构**：不是「叮嘱它别看」，而是**根本不给它**。

具体做法：专家的执行入口只接受两块内容 ——

```python
messages = [Message.system(self.system_prompt),   # ① 我的岗位说明书
            Message.user(instruction)]            # ② 主管给我的子任务
```

就这两块。它拿不到总线上的历史、拿不到别的专家说过的话、
也拿不到用户的原始长对话。

### 还有一个零件：结构化汇报

如果专家交回来的是一段自由文本，主管就没法"只转发该转发的部分"——
一段话里什么都有（包括不该外传的内部备注）。

所以要让它交回一个**带字段的对象**。我们用一个 `dataclass` 装：

| 字段 | 含义 | 为什么需要 |
|---|---|---|
| `conclusion` | 一句话结论 | 给总线 / 给人看的摘要 |
| `facts` | 结构化事实字典 | ★ 主管可以**只挑需要的字段**转发给下一个专家 |
| `evidence` | 依据（例如条款编号 `B-2`） | 让结论**可溯源**；缺失就不许下结论 |
| `needs_help` | 我干不了，需要别人补材料 | 踢皮球信号（第 ⑦ 节用它触发轮数上限） |
| `prompt_chars` | 这次它看了多少字 | 成本可观测（第 12 章的地基） |

### 立刻用一次""")

    nb.code('''# 单独可运行：专家（Worker）—— 上下文入口只有一个
import sys, pathlib
from dataclasses import dataclass, field

ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message      # 本项目的统一消息类型（.role / .content）


@dataclass
class WorkerReport:
    """专家交回来的**结构化**汇报。

    为什么要结构化而不是"返回一段话"？
        因为主管要能把它**安全地转发给下一个专家**。
        一段自由文本里什么都有（包括不该外传的内部备注），
        而结构化字段让我们可以只挑需要的传下去 —— 这就是隔离的落地方式。
    """

    worker: str                                  # 谁汇报的
    conclusion: str                              # 一句话结论
    facts: dict = field(default_factory=dict)    # ★ 可以被"挑字段"转发的结构化事实
    evidence: str = ""                           # 依据（例如条款编号 B-2）
    needs_help: bool = False                     # 踢皮球信号
    prompt_chars: int = 0                        # 这次它看了多少字（成本可观测）


class Worker:
    """专家：**自己的系统提示词 + 自己的上下文 + 自己的结论**。

    注意 handle() 里的 messages 是怎么构造的 —— 只有两块：
        自己的岗位说明书 + 主管给的子任务。
    """

    def __init__(self, title, system_prompt, reply_fn, parse_fn) -> None:
        self.title = title                       # 显示名，例如「数据专家」
        self.system_prompt = system_prompt       # 岗位说明书（只有它自己看得到）
        self.reply_fn = reply_fn                 # 它的"大脑"（教学里是确定性假模型）
        self.parse_fn = parse_fn                 # 把它的输出解析成 WorkerReport
        self.contexts: list = []                 # 记录"我到底看到了什么"（用于验收隔离）
        self.outputs: list = []                  # 记录"我说了什么"（用于验收信息流向）
        self.calls = 0                           # 被调用了几次（= 花了多少钱）

    def handle(self, instruction: str) -> WorkerReport:
        """★ 整章的支点就是这个函数（只有 6 行）。"""
        messages = [Message.system(self.system_prompt),   # ① 我的岗位说明书
                    Message.user(instruction)]            # ② 主管给我的子任务
        self.contexts.append("\\n".join(m.content for m in messages))   # 留痕：我看到了什么
        self.calls += 1                                                # 记账：一次调用
        text = self.reply_fn(instruction)                              # 干活
        self.outputs.append(text)                                      # 留痕：我说了什么
        report = self.parse_fn(text)
        report.prompt_chars = sum(len(m.content) for m in messages)     # 成本可观测
        return report

    @property
    def seen_chars(self) -> int:
        return sum(len(c) for c in self.contexts)


# ---- 一个数据专家：它只查事实、不做判断 ----
ORDER = {
    "order_id": "A1001", "status": "已发货", "carrier": "顺丰",
    "tracking": "SF1234567890", "eta": "2025-01-05",
    "trace": "2025-01-06 09:20 到达本市网点（轨迹正常，延迟 24 小时）",
    "delay_hours": 24,
    "internal_note": "内部备注：该承运商本月已有 3 起同类延误（内部数据，勿外传）",
}


def data_reply(instruction: str) -> str:
    """数据专家的确定性假模型：它一定会把查到的原始内容原样说出来。"""
    return ("已核实订单数据：\\n"
            f"- 订单号：{ORDER['order_id']}，状态：{ORDER['status']}\\n"
            f"- 承运商：{ORDER['carrier']}（运单号 {ORDER['tracking']}）\\n"
            f"- 承诺送达：{ORDER['eta']}\\n"
            f"- 实际轨迹：{ORDER['trace']}\\n"
            f"{ORDER['internal_note']}")


def parse_data(text: str) -> WorkerReport:
    """★ 关键：结构化汇报时**只挑该下游知道的字段**，内部备注故意不放进去。"""
    return WorkerReport(
        worker="数据专家",
        conclusion="订单数据已核实：状态已发货、延迟 24 小时、轨迹正常。",
        facts={
            "订单号": ORDER["order_id"],
            "状态": ORDER["status"],
            "承运商": ORDER["carrier"],
            "承诺送达": ORDER["eta"],
            "延迟小时数": str(ORDER["delay_hours"]),
            "轨迹": "正常",                 # ← 内部备注在这里被"挡掉"了
        },
    )


data = Worker("数据专家", "你是数据专家，只负责查证订单与物流事实，不做任何判断。",
              data_reply, parse_data)
report = data.handle("工单 T-2025-0117：客户投诉订单 A1001 未按时送达。请给出该订单的客观事实。")

print("数据专家这次看到了什么（它的全部上下文）：")
print("   ", data.contexts[0].replace("\\n", " ⏎ ")[:150], "…")
print()
print("它的原始输出里**确实有**内部备注：", "内部备注" in data.outputs[0])
print("但它交给主管的结构化 facts 里**没有**：", "内部备注" not in str(report.facts))
print()
print("结构化 facts：")
for k, v in report.facts.items():
    print(f"    - {k}：{v}")
print()
print("它这次看了多少字：", report.prompt_chars)
print("★ 结论：内部备注死在数据专家自己的上下文里，**根本没有进入主管的手里**。")
print("  这就是「隔离」在代码里的样子 —— 不是提示词，是数据结构。")''')

    nb.md("""### 结果说明什么

- `handle()` 只有 6 行，但它是整章的支点：**专家的输入只有两块，拿不到别的**
- 数据专家的原始输出里**有**内部备注（它确实查到了），但 `facts` 里**没有**——
  因为 `parse_data()` 明确只挑了 6 个字段
- 于是"隔离"变成了一个**可以断言的代码事实**，而不是一句提示词里的请求

> 注意一个反直觉的点：**隔离不是"省 token 的小技巧"，而是可靠性的结构性保证。**
> 省 token 只是它的副产品。

现在"干活的人"和"传话的通道"都有了。缺一个管事的。""")

    # ==================================================================
    section(nb, "⑤", "主管：分解 → 分派 → 仲裁")

    nb.md("""### 现在卡在哪

有了三个专家和一条总线，还需要一个角色回答三件事：

1. **谁来决定下一个发言人？**（集中式调度，还是谁都能 @ 谁？）
2. **专家之间怎么不互相污染？**（上一节解决了 —— 但现在要把它用起来）
3. **讨论什么时候停？**（谁说了算？）

### 所以我需要一个「只做三件事」的角色

**主管（Supervisor）只做：分解、分派、仲裁。**

它**不参与专业推理**（那是专家的事），也**不把自己的上下文借给专家**。
它的上下文里只有短小的结构化汇报（`WorkerReport`），不放专家们的原始长文本。

### 联动：数据怎么流动

```
                  ┌──────────────────────────────┐
                  │  MessageBus（只投递、只记账）  │
                  └──────────────────────────────┘
                     ▲        ▲        ▲
    ① task          │        │        │
   ┌─────────────────┴──┐     │        │
   │    Supervisor       │     │        │
   │  分解 / 分派 / 仲裁   │     │        │
   └──┬────────┬────────┬─┘     │        │
      │        │        │       │        │
      ▼        ▼        ▼       │        │
 ┌────────┐┌────────┐┌────────┐ │        │
 │数据专家 ││政策专家 ││文案专家 │ │        │
 │订单数据 ││ 条款表  ││ 话术规范 │ │        │
 └───┬────┘└───┬────┘└───┬────┘ │        │
     │②result │③只传facts│④只传结论│       │
     └────────┴────────┴────────┘        │
              WorkerReport（结构化）        │
                                          │
   ⑤ 仲裁：确定性 if/else（0 次模型调用）◄──┘
        │
        ├─ 有可溯源依据 → 交给文案专家写话术 → 对客回复
        └─ 拿不到依据   → 转人工 + 保守话术（绝不猜结论）
```

### 两条硬规矩

| 规矩 | 为什么 |
|---|---|
| **只传结论，不传上下文** | 传原文 = 把上游的上下文整个搬过去 = 又贵又容易泄密 |
| **仲裁必须是确定性的 if/else** | "谁权威、冲突听谁的、缺依据怎么办"是**流程规则**，不是判断题。交给模型 = 把系统控制流交给概率 |

### 立刻把整支团队跑起来""")

    nb.code('''# 单独可运行：主管 + 三个专家（一支完整的团队）
import sys, pathlib, re
from dataclasses import dataclass, field

ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message

# ---------------- 业务事实 ----------------
TICKET = {"ticket_id": "T-2025-0117", "order_id": "A1001", "customer": "李先生"}
ORDER = {
    "order_id": "A1001", "status": "已发货", "carrier": "顺丰",
    "tracking": "SF1234567890", "eta": "2025-01-05",
    "trace": "2025-01-06 09:20 到达本市网点（轨迹正常，延迟 24 小时）",
    "delay_hours": 24,
    "internal_note": "内部备注：该承运商本月已有 3 起同类延误（内部数据，勿外传）",
}
POLICY_RULES = {
    "A-1": ("待付款或已取消", "无需赔付"),
    "A-2": ("已发货且超承诺日 72 小时、无物流轨迹", "现金赔付 50 元"),
    "B-2": ("已发货且轨迹正常、延迟 ≤ 48 小时", "不现金赔付；补偿 20 元运费券"),
}
HOLD_REPLY = (f"【工单 {TICKET['ticket_id']} 回复】{TICKET['customer']}您好，我们已收到您的反馈，"
              "正在为您核实处理，将在 24 小时内由专人回复您。")


# ---------------- 消息总线 ----------------
@dataclass(frozen=True)
class Envelope:
    sender: str
    recipient: str
    topic: str          # task / result / question / arbitration
    payload: str
    round: int = 1

    def render(self) -> str:
        return f"[R{self.round}] {self.sender} → {self.recipient} ({self.topic}) {self.payload}"


class MessageBus:
    def __init__(self) -> None:
        self.log: list = []

    def send(self, env: Envelope) -> Envelope:
        self.log.append(env)
        return env


# ---------------- 结构化汇报 ----------------
@dataclass
class WorkerReport:
    worker: str
    conclusion: str
    facts: dict = field(default_factory=dict)
    evidence: str = ""
    needs_help: bool = False
    prompt_chars: int = 0


# ---------------- 三个专家的"大脑"（确定性假模型） ----------------
def data_reply(task: str) -> str:
    return ("已核实订单数据：\\n"
            f"- 订单号：{ORDER['order_id']}，状态：{ORDER['status']}\\n"
            f"- 承运商：{ORDER['carrier']}（运单号 {ORDER['tracking']}）\\n"
            f"- 实际轨迹：{ORDER['trace']}\\n"
            f"{ORDER['internal_note']}")


def policy_reply(task: str) -> str:
    """政策专家只做一件事：从**结构化事实**里读出条件，然后查条款表。"""
    # 主管给它是 `- 键：值` 的格式，所以这里能用一行正则解析回字典
    facts = dict(re.findall(r"^- ([^：\\n]+)：([^\\n]+)$", task, re.M))
    status, trace, delay = facts.get("状态", "?"), facts.get("轨迹", "?"), facts.get("延迟小时数", "-1")
    delay = int(delay) if delay.isdigit() else -1
    if status == "已发货" and trace == "正常" and 0 <= delay <= 48:
        code = "B-2"
    elif status == "已发货" and delay > 72:
        code = "A-2"
    else:
        code = "A-1"
    match, action = POLICY_RULES[code]
    return f"依据条款 {code}（{match}）：{action}"


def reply_reply(task: str) -> str:
    """文案专家只把已经定好的结论翻译成对客户说的话。"""
    if "现金赔付 50 元" in task:      # 被上下文里的既有结论锚定（第 ⑥ 节会用到这条路径）
        return (f"【工单 {TICKET['ticket_id']} 回复】{TICKET['customer']}您好，非常抱歉。"
                f"经核实订单 {TICKET['order_id']} 延误，我们将在 3 个工作日内现金赔付 50 元。"
                f"{ORDER['internal_note']}")
    code = re.search(r"([AB]-\\d)", task)
    return (f"【工单 {TICKET['ticket_id']} 回复】{TICKET['customer']}您好，非常抱歉给您带来不便。\\n"
            f"经核实：订单 {TICKET['order_id']} 已于 2025-01-06 到达本市网点（较承诺时间晚 24 小时），物流轨迹正常。\\n"
            f"依据服务条款 {code.group(1) if code else 'B-2'}，我们将为您补偿 20 元运费券，将于 24 小时内到账。\\n"
            "感谢您的耐心等待，如有其他问题请随时联系我们。")


# ---------------- 三个专家的"汇报解析" ----------------
def parse_data(text: str) -> WorkerReport:
    if "我还需要" in text:
        return WorkerReport("数据专家", text, needs_help=True)
    # ★ 只把**该下游知道**的字段放进 facts（内部备注故意不放进去）
    return WorkerReport("数据专家", "订单数据已核实：状态已发货、延迟 24 小时、轨迹正常。",
                        facts={"订单号": ORDER["order_id"], "状态": ORDER["status"],
                               "承运商": ORDER["carrier"], "承诺送达": ORDER["eta"],
                               "延迟小时数": str(ORDER["delay_hours"]), "轨迹": "正常"})


def parse_policy(text: str) -> WorkerReport:
    if "我需要" in text:
        return WorkerReport("政策专家", text, needs_help=True)
    code = re.search(r"([AB]-\\d)", text)
    code = code.group(1) if code else ""
    action = POLICY_RULES.get(code, ("", "无法判定"))[1]
    return WorkerReport("政策专家", f"结论：{action}（依据条款 {code or '缺失'}）",
                        facts={"条款": code, "处理方案": action}, evidence=code)


def parse_reply(text: str) -> WorkerReport:
    return WorkerReport("文案专家", text.strip())


# ---------------- 专家 ----------------
class Worker:
    def __init__(self, title, system_prompt, reply_fn, parse_fn) -> None:
        self.title, self.system_prompt = title, system_prompt
        self.reply_fn, self.parse_fn = reply_fn, parse_fn
        self.contexts: list = []
        self.outputs: list = []
        self.calls = 0

    def handle(self, instruction: str) -> WorkerReport:
        # ★★ 支点：只有两块内容 —— 我的说明书 + 主管给的子任务
        messages = [Message.system(self.system_prompt), Message.user(instruction)]
        self.contexts.append("\\n".join(m.content for m in messages))
        self.calls += 1
        text = self.reply_fn(instruction)
        self.outputs.append(text)
        report = self.parse_fn(text)
        report.prompt_chars = sum(len(m.content) for m in messages)
        return report

    @property
    def seen_chars(self) -> int:
        return sum(len(c) for c in self.contexts)


# ---------------- 主管 ----------------
@dataclass
class TeamResult:
    final_reply: str
    decision: str
    stop_reason: str        # completed / round_limit
    rounds: int


class Supervisor:
    """主管：只做三件事 —— 分解、分派、仲裁。"""

    def __init__(self, bus: MessageBus, max_rounds: int = 3, stubborn: bool = False) -> None:
        self.bus = bus
        self.max_rounds = max_rounds
        self.workers = {
            "data": Worker("数据专家", "你是数据专家，只负责查证订单与物流事实，不做判断。",
                           (lambda t: "我还需要政策专家先给出赔付口径，否则不知道该查哪些字段。")
                           if stubborn else data_reply, parse_data),
            "policy": Worker("政策专家",
                             "你是赔付政策专家，只负责条款匹配。条款：\\n"
                             + "\\n".join(f"{c}｜{m}｜{a}" for c, (m, a) in POLICY_RULES.items()),
                             (lambda t: "我需要数据专家提供物流轨迹的逐条时间戳，否则无法判断条款。")
                             if stubborn else policy_reply, parse_policy),
            "reply": Worker("文案专家",
                            "你是客服文案专家，只负责把已确认的结论写成对客户的话术。"
                            "严禁添加未确认的承诺，严禁提及任何内部信息。",
                            reply_reply, parse_reply),
        }

    # ---- 只把「事实字典」挑出来交给政策专家（不传上游原文）----
    def _ask_policy(self, data_report: WorkerReport, rounds: int) -> WorkerReport:
        facts_text = "\\n".join(f"- {k}：{v}" for k, v in data_report.facts.items())
        self.bus.send(Envelope("supervisor", "policy", "task",
                               f"请依据条款判断本单处理方案。（随附事实 {len(data_report.facts)} 项）", rounds))
        report = self.workers["policy"].handle(
            f"请判断订单 {TICKET['order_id']} 是否应赔付。\\n已知事实：\\n{facts_text}")
        self.bus.send(Envelope("policy", "supervisor", "result", report.conclusion, rounds))
        return report

    # ---- 仲裁：确定性 if/else，0 次模型调用 ----
    def arbitrate(self, reports: dict) -> tuple:
        data, policy = reports.get("data"), reports.get("policy")
        if data is None or data.needs_help:
            return "转人工：事实缺失", HOLD_REPLY
        if policy is None or policy.needs_help or not policy.evidence:
            return "转人工：条款依据缺失（专家未达成一致）", HOLD_REPLY
        if policy.evidence not in POLICY_RULES:
            return f"转人工：依据 {policy.evidence} 不可溯源", HOLD_REPLY
        _, action = POLICY_RULES[policy.evidence]
        return f"依据条款 {policy.evidence}：{action}", ""

    def run(self) -> TeamResult:
        reports: dict = {}
        rounds, stop_reason = 1, "completed"

        # ① 分派给数据专家（无依赖，可以先跑）
        self.bus.send(Envelope("supervisor", "data", "task",
                               f"请核实工单 {TICKET['ticket_id']}（订单 {TICKET['order_id']}）的物流事实。", rounds))
        reports["data"] = self.workers["data"].handle(
            f"工单 {TICKET['ticket_id']}：客户投诉订单 {TICKET['order_id']} 未按时送达。请给出客观事实。")
        self.bus.send(Envelope("data", "supervisor", "result", reports["data"].conclusion, rounds))

        # ② 分派给政策专家：**只传它需要的事实**
        reports["policy"] = self._ask_policy(reports["data"], rounds)

        # ③ 踢皮球保护：互相要材料时主管在中间转达，但**有轮数上限**
        while reports["policy"].needs_help or reports["data"].needs_help:
            if rounds >= self.max_rounds:
                stop_reason = "round_limit"
                self.bus.send(Envelope("supervisor", "arbiter", "arbitration",
                                       f"达到轮数上限 {self.max_rounds}，强制结束讨论。", rounds))
                break
            rounds += 1
            if reports["policy"].needs_help:
                question, target = reports["policy"], "data"
            else:
                question, target = reports["data"], "policy"
            self.bus.send(Envelope("supervisor", target, "question",
                                   f"转达对方诉求：{question.conclusion}", rounds))
            reports[target] = self.workers[target].handle(question.conclusion)
            self.bus.send(Envelope(target, "supervisor", "result", reports[target].conclusion, rounds))
            if target == "data":
                reports["policy"] = self._ask_policy(reports["data"], rounds)

        # ④ 仲裁（确定性规则，不是模型调用）
        decision, final_reply = self.arbitrate(reports)
        if decision.startswith("转人工"):
            final_reply = HOLD_REPLY          # 宁可给客户一句"正在核实"，也不猜一个赔付结论
        else:
            # ⑤ 分派给文案专家：**只给结论**
            self.bus.send(Envelope("supervisor", "reply", "task",
                                   f"请依据仲裁结论撰写对客回复。{decision}", rounds))
            reports["reply"] = self.workers["reply"].handle(
                f"请为工单 {TICKET['ticket_id']} 撰写对客回复。\\n"
                f"已确认事实：订单 {TICKET['order_id']} 延迟 24 小时，轨迹正常。\\n"
                f"仲裁结论：{decision}\\n"
                "（只写对客话术，不要添加任何未确认的承诺，不要提及内部信息。）")
            self.bus.send(Envelope("reply", "supervisor", "result", "对客回复已生成", rounds))
            final_reply = reports["reply"].conclusion

        return TeamResult(final_reply, decision, stop_reason, rounds)


# ---------------- 一句话的合规检查（确定性，0 次模型调用）----------------
def verify_issues(text: str) -> list:
    """对客回复的硬性合规检查。

    参数 text：准备发给客户的回复
    返回    ：不合规项列表（**空列表 = 可以发送**）
    """
    issues = []
    if TICKET["ticket_id"] not in text:
        issues.append("缺少工单号")
    if "B-2" not in text:
        issues.append("未引用条款编号，处理依据不可溯源")
    if "50 元" in text or "现金" in text:
        issues.append("出现未经批准的现金赔付承诺")
    if "运费券" not in text:
        issues.append("未给出正确的补偿方案")
    if "内部" in text or "勿外传" in text:
        issues.append("泄露内部备注（数据外泄事故）")
    return issues


# ---------------- 跑一次完整团队 ----------------
bus = MessageBus()
supervisor = Supervisor(bus, max_rounds=3)
result = supervisor.run()

print("消息总线上的完整通信记录（谁在什么时候把什么告诉了谁）：")
for env in bus.log:
    print("   ", env.render()[:100])
print()
print("最终对客回复：")
print(result.final_reply)
print()
print("主管的仲裁结论：", result.decision)
print("轮数 / 停机原因：", result.rounds, "/", result.stop_reason)
print("消息条数：", len(bus.log))
print("模型调用次数：", sum(w.calls for w in supervisor.workers.values()))
print("专家上下文合计字符：", sum(w.seen_chars for w in supervisor.workers.values()))
issues = verify_issues(result.final_reply)
print("合规检查：", "通过 ✅" if not issues else f"不通过：{issues}")''')

    nb.md("""### 结果说明什么

同一张工单，多了两次调用，换来了三件东西：

1. **正确的条款引用**（`B-2`，而不是"延误就赔 50 元"）
2. **干净的对外话术**（内部备注没有出现在回复里）
3. **可审计的通信记录**（每条消息都有发送方、接收方、主题、轮次）

而且请留意主管**没有**做的一件事：

> 它**没有**把数据专家的原文转发给政策专家 —— 只转发了 `facts` 里的 6 个字段。

`facts_text` 那一行就是"传结论、不传上下文"的落地。""")

    # ==================================================================
    section(nb, "⑥", "验收隔离：每个专家到底看到了什么")

    nb.md("""### 现在卡在哪

"我们做了隔离"是一句**主张**，不是证据。
工程上必须能在任何时候回答：**这次运行里，每个专家到底看到了多少字、看到了什么？**

### 所以我需要「上下文留痕 + 可断言」

上一节的 `Worker.contexts` 就是留痕：每次 `handle()` 都把"我看到的全部内容"存下来。
有了它，隔离检查就变成几条**一行断言**：

```python
"内部备注" not in policy_ctx      # 政策专家没看到内部备注
"运单号"   not in reply_ctx       # 文案专家没看到订单原文
```

### 立刻验收

下面这一格把"每个专家看了多少字"和四条隔离断言一次跑出来。""")

    nb.code('''# 单独可运行：隔离验收 —— 每个专家只看自己该看的
import sys, pathlib, re
from dataclasses import dataclass, field

ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message

TICKET = {"ticket_id": "T-2025-0117", "order_id": "A1001", "customer": "李先生"}
ORDER = {
    "order_id": "A1001", "status": "已发货", "carrier": "顺丰",
    "tracking": "SF1234567890", "eta": "2025-01-05",
    "trace": "2025-01-06 09:20 到达本市网点（轨迹正常，延迟 24 小时）",
    "delay_hours": 24,
    "internal_note": "内部备注：该承运商本月已有 3 起同类延误（内部数据，勿外传）",
}


@dataclass
class WorkerReport:
    worker: str
    conclusion: str
    facts: dict = field(default_factory=dict)
    evidence: str = ""
    needs_help: bool = False
    prompt_chars: int = 0


class Worker:
    """和上一节完全一样的 Worker：输入只有两块。"""

    def __init__(self, title, system_prompt, reply_fn, parse_fn) -> None:
        self.title, self.system_prompt = title, system_prompt
        self.reply_fn, self.parse_fn = reply_fn, parse_fn
        self.contexts: list = []
        self.outputs: list = []
        self.calls = 0

    def handle(self, instruction: str) -> WorkerReport:
        messages = [Message.system(self.system_prompt), Message.user(instruction)]
        self.contexts.append("\\n".join(m.content for m in messages))
        self.calls += 1
        text = self.reply_fn(instruction)
        self.outputs.append(text)
        report = self.parse_fn(text)
        report.prompt_chars = sum(len(m.content) for m in messages)
        return report

    @property
    def seen_chars(self) -> int:
        return sum(len(c) for c in self.contexts)


# ---- 三个专家各自的"岗位说明书"（这就是它们看到的全部背景知识）----
SYSTEM_DATA = "你是数据专家，只负责查证订单与物流事实，不做判断。"
SYSTEM_POLICY = ("你是赔付政策专家，只负责条款匹配。条款：\\n"
                 "A-1｜待付款或已取消｜无需赔付\\n"
                 "A-2｜已发货且超承诺日 72 小时、无物流轨迹｜现金赔付 50 元\\n"
                 "B-2｜已发货且轨迹正常、延迟 ≤ 48 小时｜不现金赔付；补偿 20 元运费券")
SYSTEM_REPLY = ("你是客服文案专家，只负责把已确认的结论写成对客户的话术。"
                "严禁添加未确认的承诺，严禁提及任何内部信息。")

# ---- 主管给三个专家的三段"子任务"（注意它们各自带了什么、没带什么）----
TASK_DATA = f"工单 {TICKET['ticket_id']}：客户投诉订单 {TICKET['order_id']} 未按时送达。请给出客观事实。"
FACTS = {"订单号": "A1001", "状态": "已发货", "承运商": "顺丰",
         "承诺送达": "2025-01-05", "延迟小时数": "24", "轨迹": "正常"}
TASK_POLICY = ("请判断订单 A1001 是否应赔付。\\n已知事实：\\n"
               + "\\n".join(f"- {k}：{v}" for k, v in FACTS.items()))
TASK_REPLY = (f"请为工单 {TICKET['ticket_id']} 撰写对客回复。\\n"
              "已确认事实：订单 A1001 延迟 24 小时，轨迹正常。\\n"
              "仲裁结论：依据条款 B-2：不现金赔付；补偿 20 元运费券\\n"
              "（只写对客话术，不要添加任何未确认的承诺，不要提及内部信息。）")

workers = {
    "数据专家": Worker("数据专家", SYSTEM_DATA, lambda t: "已核实订单数据。\\n" + ORDER["internal_note"],
                       lambda t: WorkerReport("数据专家", "订单数据已核实。", FACTS)),
    "政策专家": Worker("政策专家", SYSTEM_POLICY, lambda t: "依据条款 B-2：不现金赔付；补偿 20 元运费券",
                       lambda t: WorkerReport("政策专家", "结论：不现金赔付；补偿 20 元运费券",
                                              {"条款": "B-2"}, evidence="B-2")),
    "文案专家": Worker("文案专家", SYSTEM_REPLY, lambda t: "对客回复已生成",
                       lambda t: WorkerReport("文案专家", "对客回复已生成")),
}
reports = {name: w.handle(task) for (name, w), task in
           zip(workers.items(), (TASK_DATA, TASK_POLICY, TASK_REPLY))}

print("每个专家这次看了多少字：")
for name, w in workers.items():
    print(f"   {name} · 看了 {w.seen_chars} 字")
print()
print("它们各自看到的全文（前 60 字）：")
for name, w in workers.items():
    print(f"   [{name}] {w.contexts[0].replace(chr(10), ' ⏎ ')[:60]}…")
print()

policy_ctx = "\\n".join(workers["政策专家"].contexts)
reply_ctx = "\\n".join(workers["文案专家"].contexts)
data_out = "\\n".join(workers["数据专家"].outputs)      # 数据专家**说了什么**（含内部备注）

final_reply = "【工单 T-2025-0117 回复】李先生您好，依据服务条款 B-2，我们将为您补偿 20 元运费券。"

checks = [
    ("政策专家没看到内部备注", "内部备注" not in policy_ctx),
    ("政策专家拿到了结构化事实（延迟小时数）", "延迟小时数" in policy_ctx),
    ("文案专家没看到内部备注与订单原文", "内部备注" not in reply_ctx and "运单号" not in reply_ctx),
    ("数据专家的原始长文本（含内部备注）留在它自己那里，没有广播给全队",
     "内部备注" in data_out and "内部备注" not in policy_ctx and "内部备注" not in reply_ctx),
    ("最终回复不泄露内部信息", "内部" not in final_reply and "勿外传" not in final_reply),
]
for label, passed in checks:
    print(f"   {'✅' if passed else '❌'} {label}")
print()
print("★ 隔离 = 每个专家只拿到「完成自己那一小块」所需的最小信息。")
print("★ 它不是提示词里的一句叮嘱，而是 handle() 的调用签名决定的。")''')

    nb.md("""### 结果说明什么

| 谁 | 知道什么 | 不知道什么 |
|---|---|---|
| 数据专家 | 订单原始数据（含内部备注） | 条款表、话术规范 |
| 政策专家 | 条款表 + 结构化事实 | 内部备注、订单原文 |
| 文案专家 | 仲裁结论 + 该说的事实 | 条款表、内部备注、订单原文 |

**内部备注死在数据专家自己的上下文里** —— 这才叫隔离。

顺带记一笔：隔离同时是成本控制手段。上下文越小，每次调用越便宜（第 12 章会量化它）。

现在团队能跑、隔离也有证据了。但我们还没证明**为什么需要这么麻烦** ——
下面把它搞坏一次，你就知道代价了。""")

    # ==================================================================
    section(nb, "⑦", "亲手搞坏一次：共享上下文 + 自由讨论")

    nb.md("""### 现在卡在哪

"隔离"听起来像洁癖。所以必须把反面教材真的跑一遍，看清楚两件事：

1. **一条早期的错误草稿会变成所有人的"共识"**（污染）；
2. **每次调用都要重读全部历史**（成本平方级增长）。

### 所以要构造一个"共享草稿纸"

做法很朴素：所有人共用一份 `transcript` 列表，
每个人发言前**把整份记录发给它**，发完再把它的发言追加回去。

关键是那张草稿纸上**先躺着一条早期草稿**：

```
[早期草稿] 结论：按 A-2 现金赔付 50 元。（待确认）
```

——这是真实团队里最常见的信息污染源。""")

    nb.code('''# 单独可运行：反面教材 —— 共享上下文 + 自由讨论
# 业务事实（与前面几节相同）
TICKET = {"ticket_id": "T-2025-0117", "order_id": "A1001", "customer": "李先生"}
INTERNAL_NOTE = "内部备注：该承运商本月已有 3 起同类延误（内部数据，勿外传）"

# 共享草稿纸的初始内容：系统说明 + 用户工单 + ★ 一条"早期草稿"
TRANSCRIPT_SEED = [
    "[系统] 你们是一个客服团队，共用一个对话记录。请各自发言，自由讨论如何处理工单。",
    f"[用户] 工单 {TICKET['ticket_id']}：说好 1 月 5 日送到，现在还没到，我要赔付！",
    "[助手-早期草稿] 结论：按 A-2 现金赔付 50 元。（待确认）",
]


def shared_reply(speaker: str, transcript: list) -> str:
    """共享上下文里的专家：它的行为规律是「顺着上下文里已有的结论说」。"""
    seen = "\\n".join(transcript)
    if speaker == "数据专家":
        return f"[数据专家] 订单 A1001 状态已发货，延迟 24 小时，轨迹正常。{INTERNAL_NOTE}"
    if speaker == "政策专家":
        # ★ 锚定效应：草稿里已经写了"现金赔付 50 元"，它就不再回去查条款了
        return "[政策专家] 同意草稿的判断，本单应现金赔付 50 元。"
    return (f"[文案专家] 【工单 {TICKET['ticket_id']} 回复】{TICKET['customer']}您好，"
            f"我们将现金赔付 50 元。{INTERNAL_NOTE}")


transcript = list(TRANSCRIPT_SEED)     # 大家共用这一块草稿纸
sizes = []                             # 每次调用时，发言者要读多少字符
final = ""
for r in range(1, 3):                  # 两轮讨论
    for speaker in ("数据专家", "政策专家", "文案专家"):
        transcript.append(f"[用户] 第 {r} 轮，请 {speaker} 发言。")
        sizes.append(sum(len(x) for x in transcript))     # ★ 它这次读了多少字
        text = shared_reply(speaker, transcript)
        transcript.append(f"[助手] {text}")
        if speaker == "文案专家":
            final = text

print("共享上下文版：每次调用要重读的历史")
for i, s in enumerate(sizes, 1):
    print(f"   第 {i} 次调用：{s} 字符")
print()
print("最终对客回复：")
print("   ", final)
print()
print("污染检查：")
print("   结论被早期草稿锚定（应该是 B-2，实际写成了 50 元）：", "B-2" not in final)
print("   内部信息外泄：", "内部" in final or "勿外传" in final)
print()
print("成本对比（隔离版每个专家只看两块内容：说明书 + 子任务）：")
# ★ 这就是第 ⑤ 节里真正发给三个专家的三段内容（原样抄过来，所以数字能对上）
ISOLATED_PROMPTS = [
    ("你是数据专家，只负责查证订单与物流事实，不做判断。",
     "工单 T-2025-0117：客户投诉订单 A1001 未按时送达。请给出客观事实。"),
    ("你是赔付政策专家，只负责条款匹配。条款：\\n"
     "A-1｜待付款或已取消｜无需赔付\\n"
     "A-2｜已发货且超承诺日 72 小时、无物流轨迹｜现金赔付 50 元\\n"
     "B-2｜已发货且轨迹正常、延迟 ≤ 48 小时｜不现金赔付；补偿 20 元运费券",
     "请判断订单 A1001 是否应赔付。\\n已知事实：\\n"
     "- 订单号：A1001\\n- 状态：已发货\\n- 承运商：顺丰\\n- 承诺送达：2025-01-05\\n"
     "- 延迟小时数：24\\n- 轨迹：正常"),
    ("你是客服文案专家，只负责把已确认的结论写成对客户的话术。"
     "严禁添加未确认的承诺，严禁提及任何内部信息。",
     "请为工单 T-2025-0117 撰写对客回复。\\n"
     "已确认事实：订单 A1001 延迟 24 小时，轨迹正常。\\n"
     "仲裁结论：依据条款 B-2：不现金赔付；补偿 20 元运费券\\n"
     "（只写对客话术，不要添加任何未确认的承诺，不要提及内部信息。）"),
]
isolated_chars = sum(len(a) + len(b) for a, b in ISOLATED_PROMPTS)
print(f"   共享版：{len(sizes)} 次调用 / 合计 {sum(sizes)} 字符")
print(f"   隔离版：{len(ISOLATED_PROMPTS)} 次调用 / 合计 {isolated_chars} 字符")
print(f"   成本倍数：{sum(sizes) / isolated_chars:.2f} 倍")
print()
print("★ 共享的不是「记忆」，是「偏见」：谁先说话，谁就定义了讨论的起点。")
print("★ 而且内部备注被文案专家照抄进了对客回复 —— 这已经不是效果问题，是事故。")''')

    nb.md("""### 结果说明什么

| | 共享上下文讨论 | 主管 + 隔离专家 |
|---|---|---|
| 结论 | 顺着草稿写"现金赔付 50 元"（错） | 引用条款 `B-2`（对） |
| 内部备注 | 被文案专家照抄进对客回复 | 没有离开数据专家的上下文 |
| 上下文 | 每次调用都重读全部历史 | 每个专家只读两块 |
| 可追责 | 你只能说"大家讨论了一下" | 每条消息可溯源 |

这一节最重要的不是数字，而是一句话：

> **共享的不是「记忆」，是「偏见」。**

一旦所有人读同一份记录，最先说话的那个人（或者最早那条草稿）就成了整场讨论的锚。
而"多放几个专家"并不会让这件事变好，只会让它更贵。

### 那什么时候才真的需要多智能体？

这是本章最容易被误读的地方。判断标准只有两条：

| 问题 | 如果答案是"否" |
|---|---|
| 子任务**需要不同的知识**吗？ | 两个专家看同一份资料 = 同一个 Agent 的两次调用，纯浪费钱 |
| 这些知识**能被切干净**吗？ | 切不干净就没有隔离，只会得到一份更贵的共享草稿纸 |

两条都满足，才轮到形态③。否则先回去把单 Agent 的提示词和工具写好。""")

    # ==================================================================
    section(nb, "⑧", "踢皮球：讨论什么时候停？")

    nb.md("""### 现在卡在哪

还有一种比"讨论被污染"更隐蔽的坏结果：**专家互相要材料，谁都不干活。**

```
主管 → 数据专家：请核实物流事实
数据专家 → 主管：我还需要政策专家先给出赔付口径，否则不知道该查哪些字段
主管 → 政策专家：……
政策专家 → 主管：我需要数据专家提供逐条时间戳，否则无法判断条款
主管 → 数据专家：……
（无限循环）
```

这不是 bug，这是**真实的组织病**。而且它不报错、不崩溃 ——
它只是**一直花你的钱**。

### 所以我需要「轮数上限」，以及上限之后的行为

| 保护 | 做法 | 为什么 |
|---|---|---|
| `max_rounds` | 讨论轮数上限，到点强制结束 | 没有它，多智能体就是一张会自动续费的账单 |
| 触顶后的**兜底行为** | 返回"转人工 + 保守话术" | 宁可给客户一句"正在核实"，也不猜一个赔付结论 |
| 停机原因要显式 | `stop_reason = "round_limit"` | 上层要能一眼看出"没完成"，而不是被包装成"已完成" |

> 把失败包装成"已完成"，是多智能体系统里最贵的 bug ——
> 因为没人会去修一个"看起来成功"的东西。

### 立刻跑一次""")

    nb.code('''# 单独可运行：踢皮球与轮数上限
# ★ 这一格把"两个专家互相要材料"抽象成一个最小的循环，方便你把参数改来改去。
MAX_ROUNDS = 3        # ← 试着改这里：改成 10、50，看消息条数和成本怎么变

# 两个"固执"的专家：永远说"我干不了，需要对方先给我材料"
def stubborn_data(task: str) -> str:
    return "我还需要政策专家先给出赔付口径，否则不知道该查哪些字段。"


def stubborn_policy(task: str) -> str:
    return "我需要数据专家提供物流轨迹的逐条时间戳，否则无法判断条款。"


# 一个最小的"传话"记录（真实系统里就是消息总线上的信封）
log: list = []


def send(sender: str, recipient: str, topic: str, payload: str, rnd: int) -> None:
    log.append(f"[R{rnd}] {sender} → {recipient} ({topic}) {payload}")


rounds = 1
stop_reason = "completed"

# 开场：主管把活派给数据专家，数据专家却说自己缺材料 —— 踢皮球从这里开始
send("supervisor", "data", "task", "请核实工单 T-2025-0117（订单 A1001）的物流事实。", rounds)
send("data", "supervisor", "result", stubborn_data(""), rounds)
needs_help = {"data": True, "policy": False}     # 数据专家在等政策专家给口径

while needs_help["policy"] or needs_help["data"]:
    if rounds >= MAX_ROUNDS:
        stop_reason = "round_limit"
        send("supervisor", "arbiter", "arbitration", f"达到轮数上限 {MAX_ROUNDS}，强制结束讨论。", rounds)
        break
    rounds += 1
    target = "data" if needs_help["policy"] else "policy"
    send("supervisor", target, "question", "转达对方诉求：我还需要对方先给材料。", rounds)
    answer = stubborn_data("") if target == "data" else stubborn_policy("")
    needs_help[target] = True                    # 对方也要求补材料 → 继续踢
    send(target, "supervisor", "result", answer, rounds)

print("总线上的记录：")
for line in log:
    print("   ", line)
print()
print("轮数：", rounds, "（上限", MAX_ROUNDS, "）")
print("停机原因：", stop_reason)
print("消息条数：", len(log))
print("★ 注意 stop_reason = round_limit，而不是 completed —— 失败要能被上层看见。")
print()
print("触顶后的兜底行为（这才是关键）：")
HOLD_REPLY = "【工单 T-2025-0117 回复】李先生您好，我们已收到您的反馈，正在为您核实处理，将在 24 小时内由专人回复您。"
print("   ", HOLD_REPLY)
print()
print("★ 如果 MAX_ROUNDS 设成 50 会怎样？改一下重跑这一格：")
print("   消息条数会一路涨到 50 轮 —— 每一轮都是真金白银，而且它什么也没解决。")
print()
print("★ 更根本的解法不是「把上限调小」，而是**从源头消灭这类空转**：")
print("   让主管在转达时就要求「必须附带具体字段名」（一条确定性规则，第 09 章的做法）。")''')

    nb.md("""### 结果说明什么

- `max_rounds` 生效：讨论在第 3 轮被强制结束，消息条数有界，没有无限踢皮球
- 触顶后**如实交付**一个保守结果（转人工），而不是硬编一个结论
- `stop_reason = round_limit` 让上层能区分"做完了"和"没做完"

### 三个方案放在一起看（数字都是前面几节的**实测输出**）

| 方案 | 模型调用 | 提示词字符 | 结论 / 合规 |
|---|---|---|---|
| 单 Agent 一把梭 | 1 | 约 360 | 漏条款例外 → ❌ 4 项不合规 |
| 共享上下文讨论 | 6 | 约 2070（第 ⑦ 节实测） | 结论被污染 + 泄密 → ❌ 4 项不合规 |
| 主管 + 隔离专家 | 3 | 约 440（第 ⑤ 节实测） | 引用条款 B-2 → ✅ 通过 |

**三个方案的取舍，一句话**：

> 多智能体买到的：专业化（各管一摊）+ 隔离（各看一份）+ 可审计（消息留痕）。
> 多智能体付出的：N 倍调用 + 一个新的失败模式（踢皮球 / 死锁 / 谁说了算）。
>
> 所以选型原则是：**先单 Agent；只有当子任务需要不同知识、且上下文能切干净时，才分工。**""")

    # ==================================================================
    section(nb, "⑨", "常见坑汇总")

    pitfall_table(nb, [
        ("在提示词里叮嘱专家「别看别的」", "提示词和别人的发言拼成同一个字符串，模型区分不了",
         "隔离要在**结构**上做：`handle()` 只接两块内容"),
        ("把上游专家的原文直接转发给下游", "又贵又容易泄露内部信息（一段自由文本里什么都有）",
         "转发 `WorkerReport.facts` 的**选定字段**"),
        ("让模型来当裁判（仲裁）", "每个工单结论都不一样，控制流变成概率",
         "仲裁写成确定性 if/else，0 次模型调用"),
        ("没有 `max_rounds`", "专家互相要材料，无限踢皮球，一直烧钱", "设上限，并定义**触顶后的兜底行为**"),
        ("触顶后随便编一个结论", "把失败包装成成功，是最贵的 bug", "转人工 + 保守话术 + 显式 `stop_reason`"),
        ("所有角色共用一份上下文", "早期草稿变成全员共识（锚定效应），成本平方级增长",
         "一个专家一个上下文，只交换结论"),
        ("专家数量无脑加", "每多一个角色 = 多一份调用 + 多一个失败点",
         "先问：子任务需要不同知识吗？能切干净吗？"),
        ("结论没有 `evidence`", "无法溯源，出了事故说不清依据", "把条款编号/来源写进汇报，缺失就转人工"),
        ("只看最终答案", "出事了不知道是谁把什么告诉了谁",
         "从第一天就有消息总线（可审计、可回放）"),
        ("不做隔离断言", "「我们隔离了」只是主张，不是证据",
         "用 `contexts` 留痕，写成一行断言进 CI"),
    ])

    summary(nb, [
        "**多智能体 = 角色分工 + 消息传递 + 结果仲裁。** 三样缺一不可。",
        "**先试单 Agent。** 只有当子任务需要不同知识、且上下文能切干净时，分工才划算。",
        "**隔离是结构问题，不是提示词问题。** 专家的输入入口只有一个："
        "`自己的岗位说明书 + 主管给的子任务`。",
        "**传「结论」，不传「上下文」。** 这是省钱和防泄露的同一个动作。",
        "**汇报要结构化，转发要挑字段。** `facts` 字典让你能只传需要的部分。",
        "**仲裁必须是确定性的。** 把仲裁交给模型，等于把系统的控制流交给概率。",
        "**上限不是可选项。** 没有 `max_rounds`，多智能体就是一张自动续费的账单；"
        "而且上限之外还要有触顶后的行为（转人工，不是编结论）。",
        "**共享的不是记忆，是偏见。** 谁先说话，谁就定义了讨论的起点。",
    ], "第 09 章会接着问一个更狠的问题：**这些「流程」本身，为什么要交给模型？**"
       "本章的主管已经用 if/else 做了仲裁 —— 第 09 章会把整个流程画成一张显式的图，"
       "并且给出判据：能用确定性代码解决的，绝不用模型。")

    exercises(nb, [
        ("**拆掉轮数上限，看账单怎么涨（必做）。**\n\n"
         "把第 ⑧ 节的 `MAX_ROUNDS` 从 3 改成 50，重跑那一格。\n\n"
         "观察：消息条数、`rounds`、以及「如果每轮都要调一次模型」的调用次数。\n\n"
         "再想一步：如果这是一个每天 1 万单的客服系统，这个 bug 一天要花多少钱？",
         "每一轮「转达 + 回答」至少是两条消息、两次模型调用。\n\n"
         "50 轮 × 3 个专家 ≈ 150 次调用 —— 而它**什么问题都没解决**。\n\n"
         "这就是为什么上限之外还要有「触顶后的兜底」：光有上限只是把浪费截断，"
         "没有上限才是灾难。"),

        ("**让隔离「漏一点」，看哪几条断言变红（必做）。**\n\n"
         "把第 ⑤ 节 `_ask_policy()` 里的 `facts_text` 换成数据专家的**原始输出**"
         "（也就是把内部备注一起转发给政策专家），重跑第 ⑥ 节的隔离验收。\n\n"
         "观察：哪几条 ✅ 变成了 ❌？",
         "`政策专家没看到内部备注` 会立刻变红。\n\n"
         "顺手想一想：如果代码里没有这条断言，这个改动会在什么时候被发现？\n"
         "——大概率是客户投诉的时候。**这就是回归测试的价值。**"),

        ("**加第四个专家（合规专家）。**\n\n"
         "让它在文案专家之后跑，检查禁用词和金额，把结论用 `topic=\"result\"` 回给主管。\n\n"
         "然后回答：这一步真的需要模型吗？还是 6 行 if/else 更合适？",
         "参考第 09 章的 `node_compliance`：6 行确定性代码就能替代一个「模型自审」节点。\n\n"
         "原因：合规要求**每次判断都一样**，而模型给不了这个保证。\n\n"
         "别忘了在 `arbitrate()` 里加上「合规不通过 → 转人工」的分支。"),

        ("**给 `Envelope` 加 `trace_id` 和 `elapsed_ms`。**\n\n"
         "然后写一句话回答：为什么这两个字段必须从第一天就有？",
         "`trace_id` 是把一次运行的**所有**消息串起来的关联键 —— "
         "真实系统里它就是 OpenTelemetry 的 trace_id（第 10、13 章会反复用它）。\n\n"
         "事后补是补不上的：你不可能回头给已经跑过的消息补一个 id。\n\n"
         "`elapsed_ms` 则是性能回归的第一手证据：是模型慢了，还是某个专家慢了？"),

        ("**设计一个「真的需要多智能体」的任务。**\n\n"
         "从下面三个候选人里挑，并写出理由：\n"
         "① 把这段中文翻译成英文并检查语法；\n"
         "② 读三份不同格式的财报，各自抽取关键指标，再合成一张对比表；\n"
         "③ 帮我写一首诗。",
         "问自己两个问题：**子任务需要不同的知识吗？上下文能切干净吗？**\n\n"
         "②最像正确答案：三份财报的解析互不依赖，格式各自独立，"
         "最后合成一张表需要的是一个**确定性**的汇总步骤。\n\n"
         "①和③更像是「同一个 Agent 调两次」，分出去只会多花两次调用的钱。"),
    ])

    checkpoint(nb, "08")

    return nb
