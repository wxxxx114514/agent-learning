# 第 09 章 · 工作流与状态机

<!-- 材料定位 -->
> ## 📖 这份文档是**复习手册**，不是第一次学习用的
>
> 同一章有三种材料，**内容一致，用途不同**：
>
> | 材料 | 位置 | 什么时候用 |
> |---|---|---|
> | **① 交互式 Notebook** | `notebooks/09_workflow.ipynb` | **第一次学** —— 一步步推导，每个代码单元都能单独运行 |
> | **② 本文件** | `stages/stage09_workflow/README.md` | **复习 / 查阅** —— 结构化的原理与工程要点，方便搜索和跳读 |
> | **③ 命令行 demo** | `py -m stages.stage09_workflow.demo` | **看完整输出** —— 或者用 `-s N` 只看某一节 |
>
> **建议路径**：先用 ① 学一遍（能看到每一步的真实输出），
> 之后忘了什么回来查 ②，想快速跑一遍用 ③。
>
> 学完的验收命令：`py scripts\run_all_checks.py 09`

---

> 一句话本质：**能用确定性代码解决的，绝不用模型。**
> 模型只负责「需要判断」的节点，流程骨架应该是显式的图 / 状态机。
>
> 给 Agent 多少自由度，是一个**架构决策**，不是模型能力问题。

---

## 0. 先看问题

第 08 章我们学会了分工。但只要你还把"流程"交给模型，就永远会遇到同一类事故。

把一张工单丢给一个"你自己看着办"的 Agent：

```python
Agent("你是客服 Agent，请处理这张工单，直接给出给客户的回复。")
```

得到的输出：

```
【工单 T-9002 回复】您好，您的订单已经发货啦，绝对保证明天一定到！（内部备注：该线路本月已延误 3 次）
```

确定性审计（禁用词 / 必填字段）结果：

```
  审计结果              : 不通过（2 项）
    - 禁用词「绝对保证」
    - 禁用词「内部备注」
```

问题不是"模型不听话"，而是**从来没有人告诉它流程里必须有一步叫「合规检查」**。
模型只做你要求它做的事，不会替你想起来还有合规、还有归档、还有超时重试。

更麻烦的是三件事：

1. **不可复现** —— 这次先查订单再道歉，下次可能反过来，你没法写测试；
2. **不可中断** —— 跑到一半进程挂了，只能从头再来；
3. **不可审计** —— 出了事，你说不清它到底走了哪条路。

这三件事，靠"把提示词写得更细"是解决不了的。**要把流程从模型手里拿走。**

---

## 1. 原理

### 1.1 一个状态机只有三样东西

```
   节点（做什么）  +  边（下一步去哪）  +  状态（记住什么）

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
检查点、并发、人工介入、可视化、重试。所以先手写一遍，你就能看穿它们。

### 1.2 哪个节点该用模型？

这是全章唯一需要背下来的判据：

| 问题 | 答案 | 实现方式 |
|---|---|---|
| 这件事的答案在表里 / 规则里吗？ | 是 | **写代码**（FAQ 查表、订单查询、条款匹配）|
| 这件事每次都必须给出同样的判断吗？ | 是 | **写代码**（合规检查、金额校验、必填字段）|
| 这是流程控制（下一步去哪）吗？ | 是 | **写代码**（路由是纯函数）|
| 需要把结论翻译成人话 / 理解模糊语义？ | 是 | **交给模型** |
| 需要承担责任（赔付、放行）？ | 是 | **交给人** |

本章这张图的分工：

| 节点 | 类型 | 理由 |
|---|---|---|
| `intake` | 确定性 | 输入校验是规则，错了要能一眼看懂 |
| `classify` | **规则 + 模型兜底** | 80% 有关键词；长尾才值得花一次调用 |
| `handle_refund` / `handle_logistics` / `handle_consult` | 确定性 | 答案在订单表和 FAQ 里，模型只会读错 |
| `draft_reply` | **模型** | 把结论写成人话 —— 这才是语言模型的活 |
| `compliance` | 确定性 | 合规必须每次判断一致、可审计 |
| `human_review` | **人工** | 责任问题，不能交给概率 |
| `finalize` | 确定性 | 收口动作没什么可判断的 |

**9 个节点，只有 1 个真的需要模型。**

### 1.3 状态必须是纯 JSON

```
   ┌───────────────── state（纯 JSON）─────────────────┐
   │  ticket_id / category / decision / draft / ...    │  ← 能落盘、能进 Redis
   └───────────────────────────────────────────────────┘
   ┌───────────────── ctx（运行期资源）────────────────┐
   │  llm 客户端 / 人工通道 / 计数器                    │  ← 绝不进 state
   └───────────────────────────────────────────────────┘
```

这是"检查点能不能真正落地"的分水岭。**把模型客户端、回调函数塞进 state 的代码，是恢复不了的。**

### 1.4 检查点与人工介入

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

---

## 2. 动手实现

代码在 `stages/stage09_workflow/demo.py`，全部离线可跑，人工答复由确定性剧本提供。

### 2.1 图的基本零件

```python
@dataclass
class Node:
    name: str
    fn: Callable[[State, "NodeContext"], dict | None]
    kind: str = "deterministic"             # deterministic / llm / human
    title: str = ""

@dataclass
class ConditionalEdge:
    """条件边：由 router(state) 返回一个 key，再查表决定去哪。

    为什么路由器是**纯函数**而不是模型调用？
        因为"下一步去哪"是流程控制，必须可预测、可测试、可审计。
        把路由交给模型，等于把系统的控制流交给概率。
    """
    src: str
    router: Callable[[State], str]
    targets: dict[str, str]
```

### 2.2 引擎核心：一个 while 循环

```python
while cursor != END:
    visits[cursor] = visits.get(cursor, 0) + 1
    history.append(cursor)
    if visits[cursor] > self.max_visits:                     # 循环保护
        return RunResult("max_visits", ..., error=f"节点 {cursor} 被访问 {visits[cursor]} 次")
    node = self.nodes[cursor]
    try:
        update = node.fn(state, ctx)
    except Interrupt as stop:                                # ★ 挂起（不是崩溃）
        cp = Checkpoint(self.name, stop.resume_at or cursor, dict(state),
                        dict(visits), list(history), ctx.llm_calls)
        return RunResult("interrupted", state, history, visits, ctx.llm_calls, checkpoint=cp)
    except Exception as exc:
        return RunResult("error", ..., error=f"{type(exc).__name__}: {exc}")
    if update:
        state.update(update)          # 节点只返回"它改了什么"（增量更新）
    cursor = self._next(cursor, state)
```

三个设计决定：

1. **节点返回增量**而不是整个 state —— 并发、回放、审计都容易做（LangGraph 的 reducer 思路）；
2. **`Interrupt` 是控制流，不是异常** —— 它会被转换成"可恢复的暂停"；
3. **`max_visits` 保护流程**（对应第 01 章的 `max_steps` 保护对话）。

### 2.3 Ctrl 与 state 分离

```python
@dataclass
class NodeContext:
    """★ 这些东西绝不放进 state：state 要能 json.dumps，模型客户端序列化不了。"""
    llm: LLM
    human: HumanChannel
    models: dict[str, LLM] = field(default_factory=dict)   # 按角色选模型（分类用小的）
    llm_calls: int = 0

    def ask_llm(self, messages: list[Message], role: str = "") -> str:
        self.llm_calls += 1
        client = self.models.get(role, self.llm)
        return client.complete(messages).text
```

### 2.4 规则优先，模型兜底

```python
def rule_classify(text: str) -> str | None:
    """关键词规则：命中就返回类别，认不出来返回 None。

    ★ 全章的题眼：能用确定性代码解决的，绝不用模型。
      真实业务里，80% 的工单都带着明显的关键词。
    """
    rules = (("refund", ("退款", "退货", "不要了", "取消订单")),
             ("logistics", ("快递", "物流", "到哪", "什么时候到", "发货")),
             ("consult", ("怎么用", "怎么开", "有效期", "规则")))
    for label, words in rules:
        if any(w in text for w in words):
            return label
    return None

def node_classify(state, ctx) -> dict:
    label = rule_classify(state["text"])
    if label:
        return {"category": label, "classified_by": "规则（0 次模型调用）"}
    label = ctx.ask_llm([...], role="classifier").strip()     # 长尾才轮到模型
    return {"category": label, "classified_by": "模型（规则认不出来才用它）"}
```

### 2.5 合规检查：6 行代码替代一个模型节点

```python
def node_compliance(state: State, ctx: NodeContext) -> dict:
    draft = state.get("draft", "")
    issues: list[str] = []
    for word in FORBIDDEN_WORDS:
        if word in draft:
            issues.append(f"出现禁用词「{word}」")
    for amount in re.findall(r"(\d+)\s*元", draft):
        if amount not in APPROVED_AMOUNTS:
            issues.append(f"出现未批准的金额承诺「{amount} 元」")
    if state["ticket_id"] not in draft:
        issues.append("回复中缺少工单号，无法归档")
    return {"compliance_issues": issues}
```

**为什么不用模型做合规？** 因为它不稳（同样的话这次说有风险、下次说没有），
而合规要求**每次判断都一样**。

### 2.6 人工介入节点

```python
def node_human_review(state: State, ctx: NodeContext) -> dict:
    reply = state.get("human_reply")
    if reply is None:
        raise Interrupt(f"草稿未通过合规检查：{state.get('compliance_issues')}，请人工审批",
                        resume_at="human_review")        # ← 挂起，等人工
    if reply.get("decision") == "approved":
        return {"human_decision": "approved", "human_note": reply.get("note", "")}
    return {"human_decision": "rejected", "revision_notes": reply.get("note", "请修改后重新提交")}
```

教学里人工答复来自 `HumanChannel` 的**确定性剧本**（绝不调用 `input()`）：

```python
class HumanChannel:
    def try_ask(self, question: str) -> dict | None:
        self.asked.append(question)
        return self.replies.pop(0) if self.replies else None    # 空 = 没人在线 → 引擎挂起
```

---

## 3. 跑起来

```powershell
cd D:\project\agent-learning

py -m stages.stage09_workflow.demo --list
py -m stages.stage09_workflow.demo -s 4        # 只看检查点与恢复
py -m stages.stage09_workflow.demo --check
py -m stages.stage09_workflow.demo
```

以下是 `py -m stages.stage09_workflow.demo` 的**真实输出**（节选）。

第 ① 节：让模型自己决定流程。

```
    │ 【工单 T-9002 回复】您好，您的订单已经发货啦，绝对保证明天一定到！（内部备注：该线路本月已延误 3 次）

  模型调用次数            : 1
  审计结果              : 不通过（2 项）
    - 禁用词「绝对保证」
    - 禁用词「内部备注」
```

第 ② 节：三类工单各自路由（每条路径都能画出来给产品看）。

```
  T-9001 类别         : refund
    分类方式            : 规则（0 次模型调用）
    处理节点            : 退款规则表
    路径              : intake → classify → handle_refund → draft_reply → compliance → human_review → finalize
    状态 / 模型调用       : completed / 1 次
```

第 ③ 节：确定性优先。

```
  明确工单 · 分类方式       : 规则（0 次模型调用）
  明确工单 · 总模型调用      : 1
  模糊工单 · 分类方式       : 模型（规则认不出来才用它）
  模糊工单 · 总模型调用      : 2

  模型写出的第一版草稿        : 相关补偿绝对保证 24 小时内到账。如有其他问题请随时联系我们。
  确定性合规检查抓到         : 1 项：['禁用词「绝对保证」']
  检查用了多少行代码         : 6 行（见 node_compliance）
  检查调用了多少次模型        : 0 次
```

第 ④ 节：检查点（这是本章最值钱的一段输出）。

```
  第一次运行 · 状态        : interrupted
  第一次运行 · 停在哪       : human_review
  第一次运行 · 已走过的路径    : intake → classify → handle_logistics → draft_reply → compliance → human_review
  第一次运行 · 模型调用      : 1

  ℹ️  挂起时保存的检查点（**这就是一个纯 JSON**，可以塞进 Redis / 数据库 / 消息队列）：
    │ {
    │   "graph": "客服工单处理",
    │   "node": "human_review",
    │   "state": {
    │     "ticket_id": "T-9002",
    │     "category": "logistics",
    │     "decision": "您的包裹已由顺丰发出，预计 2025-01-05 送达。",
    │     "draft": "【工单 T-9002 回复】…相关补偿绝对保证 24 小时内到账。…",
    │     "compliance_issues": [ "出现禁用词「绝对保证」" ]
    │   },
    │   "visits": { "intake": 1, "classify": 1, "handle_logistics": 1, "draft_reply": 1, "compliance": 1, "human_review": 1 },
    │   "history": [ "intake", "classify", "handle_logistics", "draft_reply", "compliance", "human_review" ],
    │   "llm_calls": 1
    │ }

    （为了排版，上面 state 里的 order_id / text / classified_by / handled_by /
      pending_question 等字段用 … 省略了；实际输出是完整的 699 字符 JSON。）

  恢复后 · 状态          : completed
  恢复后 · 模型调用总数      : 1（恢复过程新增 0 次）
  恢复后 · classify 被访问次数: 1 次（没有重新分类）

  要求修改后 · 完整路径      : intake → classify → handle_logistics → draft_reply → compliance → human_review → human_review → draft_reply → compliance → finalize
  要求修改后 · 模型调用      : 2 次（多了 1 次：按人工意见重写草稿）
```

注意 `classify 被访问 1 次` 且 `恢复过程新增 0 次模型调用` —— **判断结果全都躺在检查点里**，
恢复时不会重新问模型。（路径里 `human_review` 出现两次：一次是抛 `Interrupt` 的那次，一次是恢复后结算的那次。）

第 ⑥ 节：图校验与循环保护。

```
  坏图 · 校验发现         : 4 个问题
    - 条件边 a 的分支 'go' 指向不存在的节点 missing_node
    - 节点 orphan 从入口不可达（死代码）
    - 节点 a 无法到达 END（可能死循环或漏了出边）
    - 节点 orphan 无法到达 END（可能死循环或漏了出边）

  循环保护 · 运行状态       : max_visits
  循环保护 · 停机原因       : 节点 draft_reply 被访问 3 次，超过上限 2
  循环保护 · 路径         : intake → classify → handle_logistics → draft_reply → compliance → human_review → draft_reply → compliance → human_review → draft_reply
```

最后自检会打印 `✅ 全部通过（20 项）`。

---

## 4. 工程要点

**① 先画图，再写提示词。**
把流程画出来，你会立刻发现两件事：哪些节点其实不需要模型；哪些"模型行为"其实是流程缺失。
本章的图有 9 个节点，只有 1 个是 `kind="llm"`。

**② 路由是代码，不是模型输出。**
"下一步去哪"必须可预测。让模型输出 `next_node` 是初学者最常见的架构错误：
它会把你的流程变成一张随机图，而且没有任何测试能覆盖。

**③ state 与 ctx 严格分离。**
state 只放 JSON；模型客户端、人工通道、数据库连接全部走 ctx。
这条纪律决定的不是代码好不好看，而是**你能不能断点续跑**。

**④ 挂起要"干净地退出"，不要阻塞线程。**
本章的 `Interrupt` + `Checkpoint` 是标准做法。真实系统里 `input()` / `while not answered: sleep()`
会把一个 Web 进程钉死 —— 正确姿势是落盘 + 回调（第 13 章细讲）。

**⑤ 人工节点必须有回环，也要有上限。**
人工拒绝 → 回到 `draft_reply` 修订（图里的边），这是流程的一部分；
但"只说不行、不说怎么改"的人工会让流程空转 —— 本章第 ⑥ 节用 `max_visits` 兜住了它，
更好的做法是在节点里**强制校验"修改意见必填"**（用一条确定性规则消灭一整类空转）。

**⑥ 图要在 CI 里校验。**
`validate()` 检查三件事：边指向的节点存在、所有节点从入口可达、所有节点都能走到 END。
这三条能拦住绝大多数"上线才发现"的流程 bug。

**⑦ 状态变更要留痕。**
`history`（走过哪些节点）和 `visits`（每个节点走了几次）是排障的第一手资料。
真实项目里还应该记录每个节点的输入 / 输出 / 耗时（第 10 章）。

**⑧ 常见误区**

| 误区 | 现实 |
|---|---|
| "让 Agent 自主决定流程更灵活" | 灵活 = 不可复现 = 不可运维；流程该写死 |
| "分类这么简单，让模型做就行了" | 规则命中率 80%，且 0 成本、0 延迟、可测试 |
| "合规检查也用一个模型节点吧" | 合规要的是"每次判断一样"，模型给不了 |
| "检查点就是存个 state" | state 里混进不可序列化对象，检查点直接失效 |
| "人工介入就是 `input()`" | 那会把进程钉死；正确做法是落盘 + 回调 |
| "有环就是 bug" | 有环是正常的（修订回环），**没有上限的环**才是 bug |

---

## 5. 练习

**练习 1（必做）：把护栏拆掉，观察会发生什么。**
把 `build_graph(max_visits=2)` 改成 `max_visits=100`，用"只说不行、不说怎么改"的人工跑第 ⑥ 节。
*提示*：你会看到 `draft_reply` 被反复访问，每次访问都是一次模型调用。
再把它改回 2 —— 体会一下 `max_visits` 到底在保护什么。

**练习 2：把 `handle_consult` 换成模型，量一量代价。**
现在的咨询处理是 FAQ 查表（0 次调用）。改成调用模型来回答同样的问题，
对比 `llm_calls` 和结果的一致性。
*提示*：跑两次同样的工单，看模型两次的回答是否字字相同。合规部门会喜欢哪一个？

**练习 3：加一个"超时升级"节点。**
新增节点 `escalate`：当 `visits["human_review"] >= 2`（人工两次没拍板）时，
条件边路由到 `escalate`，把工单交给主管并结束流程。
*提示*：改 `route_after_human`，加一条新分支。别忘了 `validate()` 要能通过（新节点要能到 END），
并在 `run_checks()` 里补一条断言。

**练习 4：让检查点真的落盘。**
把 `Checkpoint.to_json()` 写进文件（`Path("checkpoint.json").write_text(...)`），
再从文件读回来恢复。然后**故意在恢复前修改 graph 的结构**（比如删掉一个节点），
观察 `resume()` 会怎么报错。
*提示*：生产系统里这叫"版本漂移"，通常需要在检查点里存一个 `graph_version` 并做兼容校验。

**练习 5：把这张图和第 08 章的主管对比。**
第 08 章的主管用自然语言分派任务，第 09 章用条件边路由。
写下三个判断标准，说明什么情况下该用哪一种。
*提示*：想想"分派规则是不是稳定的"、"子任务数量是不是固定的"、
"失败之后要不要从头再来"。

---

## 6. 验收标准

来自 `ROADMAP.md` 第 09 章：

- [x] 能用状态机表达"分类→路由→处理→汇总"流程
- [x] 支持在任意节点中断并可恢复（检查点）
- [x] 能说清"给 Agent 多少自由度"的取舍原则

自动验证（20 项检查，另外覆盖了条件边、确定性护栏、规则优先、图校验、循环保护、可复现性）：

```powershell
py scripts\run_all_checks.py 09
```

预期结果：`20/20 通过`，耗时 1ms 量级。

> 关于第三条验收标准（"说清取舍原则"）：它的书面答案在本文件 `## 1.2 哪个节点该用模型？`
> 的判据表里，而它的**可执行版本**在 `demo.py` 的这条断言里：
>
> ```python
> results.append(check_that(
>     "只有 draft_reply 被标记为 llm 节点（其余节点确定性）",
>     llm_nodes == {"draft_reply"},
>     f"llm 节点 = {sorted(llm_nodes)}，共 {len(build_graph().nodes)} 个节点"))
> ```
>
> 能跑通的取舍原则，才是真的想清楚了。
