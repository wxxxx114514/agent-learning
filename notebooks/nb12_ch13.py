"""第 13 章 · 生产化部署 —— Notebook 内容（逐步推进版）。

遵守 TEACHING_CONTRACT.md：
  · 逐步给：每个知识点在「读者正好需要」时出现
  · 前置知识表保留在 ⓪，定位是索引（可跳过）
  · 每个代码单元自包含（nb_lint 机器校验）
  · 中文引号一律用 「」，不在字符串里嵌 ASCII 双引号

本章特有的两条硬约束（写在最前面，免得后来的人踩）：
  1. **不真的杀进程**：所谓「进程被杀」就是抛 `SimulatedCrash(BaseException)`。
     继承 BaseException 是为了不被任何 `except Exception` 兜底吞掉 ——
     中断和错误必须走不同通道。
  2. **绝不留残留文件**：检查点写进工作区内的临时目录，同一格 try/finally 删掉。
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


def build_13() -> Notebook:
    """第 13 章 · 生产化部署（逐步推进版）。"""
    nb = Notebook("第 13 章 · 生产化部署")

    header(
        nb, "13", "生产化部署",
        "生产化 = `状态持久化` + `幂等重试` + `并发控制` + `超时熔断` + `灰度回滚`。\n"
        "核心矛盾是：**Agent 是有状态的长任务，而 HTTP 是无状态的短连接** ——\n"
        "把长任务塞进短连接，就像把一头大象塞进电话亭。",
    )

    objectives(nb, [
        "说清核心矛盾，并指出本地开发为什么**永远发现不了**这些 bug",
        "亲手复现两种真实的坏结果：崩溃丢工作、重试重复扣款",
        "写出 `RunState` 检查点，并解释为什么必须**原子写**（临时文件 → fsync → `os.replace`）",
        "解释「恢复 = 倒回起点 + 重放」，以及不倒回时那条**工具调用悄悄翻倍**的 bug 链",
        "说清幂等键的作用域为什么要拼 `user_id + 业务意图`，以及为什么用 `sha256` 而非内置 `hash()`",
        "实现并发闸门、熔断器（三态）、超时降级（半成品 + 说明 + 可续跑）",
        "用结构化日志回答「是哪一次运行的哪一步失败了」",
        "说清灰度为什么要按**稳定哈希**分桶、为什么要用**滑动窗口**错误率而不是总错误率",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

前 12 章我们一直在让 Agent **变聪明**：会调工具、会规划、会记忆、会反思、会协作。
但它们全都建立在一个从没写出来的假设上：

```
   进程一直活着   ·   一次只服务一个请求   ·   你不刷新   ·   没有并发
```

真实的线上环境会同时从四个方向打破它：

```
   你的本地机器                        真实的生产环境
 ┌────────────────┐            ┌──────────────────────────────────────┐
 │ 一个进程         │            │ 发布重启 / OOM Killer / Pod 被驱逐    │
 │ 一个请求         │            │ 用户双击 / 客户端自动重试 / 网关重发    │
 │ 你不刷新         │            │ 网关 30 秒就断开，你的任务要跑 90 秒   │
 │ 没有并发         │            │ 200 个并发一起抢模型连接              │
 └────────────────┘            └──────────────────────────────────────┘
         都能跑通                            全部出事
```

本章按顺序拆：

```
① 先看天真做法怎么坏（两种失败，都可运行、可观察）
② 检查点：把状态从进程内存搬到进程之外，而且要「原子写」
③ 恢复 = 倒回起点 + 重放（含一条「工具调用悄悄翻倍」的 bug 链）
④ 幂等：重试时副作用不能发生第二次（键的作用域最容易写错）
⑤ 并发闸门 + 熔断器：过载和下游故障，都要「快速失败」
⑥ 超时降级：给半成品，别挂死（用虚拟时钟让超时确定性可测）
⑦ 结构化日志：回答「是哪一次运行的哪一步失败了」
⑧ 灰度发布与自动回滚：让坏版本只影响 5% 的流量，并且自己退回去
```

一句话记住这一章的定位：

> **前 12 章让 Agent 变聪明，这一章让它敢上线 ——「在坏掉的时候也不出事」。**
""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `dataclass` / `field` | 标准库 `dataclasses` | 声明「一次运行的全部状态」这类数据结构 | `field(default_factory=list)` 给可变默认值 |
| `json.dumps` / `json.loads` | 标准库 `json` | 状态 ↔ 文本（检查点落盘） | `json.dumps(obj, ensure_ascii=False)` |
| `tempfile.mkstemp` | 标准库 `tempfile` | 造一个临时文件并拿到打开的文件描述符 | → `(fd, 绝对路径)` |
| `os.fsync` | 标准库 `os` | 把页缓存真正刷到磁盘（不是「写完就安全」） | `os.fsync(f.fileno())` |
| `os.replace` | 标准库 `os` | **原子**改名（同一文件系统内） | `os.replace(tmp, final)` |
| `hashlib.sha256` | 标准库 `hashlib` | 稳定指纹：幂等键、灰度分桶 | `.hexdigest()[:16]`；**别用内置 `hash()`** |
| `pathlib.Path` | 标准库 `pathlib` | 路径运算与读写 | `Path.cwd() / "x"`、`.read_text(encoding=...)` |
| `shutil.rmtree` | 标准库 `shutil` | 删目录（教学里用完就删，不留垃圾） | `shutil.rmtree(p, ignore_errors=True)` |
| `random.random` | 标准库 `random` | **反面教材**：不稳定，绝不能用来分灰度桶 | 见 ⑧ |

### 本章用到的本项目代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `Agent` / `AgentResult` | `core.agent` | Agent 主循环：`run()` 的第一件事就是追加用户消息 —— 「倒回」的由来 |
| `Conversation` / `Message` | `core.message` | 会话与消息：**Agent 的全部记忆就是这个列表** |
| `BudgetExceeded` | `core.errors` | 「预算耗尽」的语义化异常，它就是超时降级的信号 |
| `RunState` | `stages/stage13_production/journal.py` | 本章核心数据结构：会话 + 起点 + 已完成事实 + 半成品 |
| `FileCheckpointStore` | 同上 | 检查点落盘：**原子写** + 坏文件降级 |
| `EventLog` | 同上 | 结构化日志：一行一个 JSON，按 `run_id` + `step` 定位 |
| `IdempotencyCache` | 同上 | 幂等缓存：`cache_key()` 拼作用域、`fingerprint()` 用 sha256 |
| `FakeClock` / `Budget` | `stages/stage13_production/virtual.py` | 虚拟时钟与预算：让「超时」确定性可测 |
| `SimulatedCrash` / `CheckpointedEngine` | `stages/stage13_production/runtime.py` | 崩溃注入 + 可续跑引擎 |
| `ProductionRuntime` | 同上 | 服务外壳：幂等 → 熔断 → 并发准入 → 执行 → 记录 |
| `CanaryRouter` | `stages/stage13_production/canary.py` | 稳定哈希分桶 + 滑动窗口 + 自动回滚 |

### 随时可查

```python
explain(RunState)          # 字段逐个说明（本项目的生产化状态结构）
explain(FakeClock)         # 虚拟时钟：为什么测试里绝不能 sleep
explain()                  # 列出框架全部公开名字
```

> 本章的每个代码单元都用**普通 dict / 普通类**重写了一遍最小版本，
> 目的是「复制出去就能跑」。要看生产实现，去上面那几张表里的文件。""")

    # ==================================================================
    section(nb, "①", "先看天真做法怎么坏")

    nb.md("""### 现在卡在哪

几乎每个人第一次写 Agent 服务都是这么写的：

```python
agent = build_agent()                    # 状态在进程内存里
store = {}                               # 「检查点」也在内存里

@app.post("/ask")
def ask(q: str):
    result = agent.run(q)                # 一次请求 → 一次完整执行
    return {"answer": result.answer}     # 跑完才返回
```

**它在本地永远是对的**：只有你一个人、一次请求、进程不会重启。

### 所以我需要先亲眼看到两种坏结果

不是讲故事，而是可运行的代码。本节的代码单元会把这两种事故各演一遍：

| 场景 | 触发条件 | 坏结果 |
|---|---|---|
| A：进程被杀 | 发布重启 / OOM / Pod 被驱逐 | 已经跑完的步骤**凭空消失**，用户只能从头再来 |
| B：用户重试 | 网络抖动 / 用户双击 / 网关重发 | **副作用发生两次** —— 重复扣款，P0 事故 |

两者都源自同一个矛盾：

```
┌──────────────────────────────────────────────────────────────────┐
│  Agent 的一次运行 = 有状态 + 长任务                                │
│      · 有状态：几十条消息的会话、已经调过的工具、已经花掉的钱        │
│      · 长任务：几十秒到几分钟、几十步、而且**带副作用**（扣款/发文） │
├──────────────────────────────────────────────────────────────────┤
│  HTTP 的一次请求 = 无状态 + 短连接                                 │
│      · 无状态：服务器不记得你上次请求过什么                          │
│      · 短连接：网关 3~30 秒就断了，断了就什么都没了                  │
└──────────────────────────────────────────────────────────────────┘
```

**本地只有一头象时你能硬塞，上线后象群一来，电话亭就塌了。**

### 它的用法（模拟「进程被杀」）

我们**不真的杀进程**，而是抛一个异常来代表它：

```python
class SimulatedCrash(BaseException):
    ...          # 「进程被 kill」在代码里的等价物
```

对恢复逻辑来说，两者完全一样：都是「`run()` 中途断了，检查点停在半路」。
真实世界里对应的事件是：OOM Killer、Pod 被驱逐、发布重启、机器掉电。""")

    nb.code('''# 单独可运行：天真做法 —— 状态全在进程内存里，进程一死全没


class SimulatedCrash(BaseException):
    """模拟「进程在第 N 步被 kill」（发布重启 / OOM / Pod 被驱逐）。

    ★ 为什么继承 BaseException 而不是 Exception？
        上层几乎总有一句兜底的 `except Exception: pass`
        （本项目 core/agent.py 的观察者派发里就有一句），
        它会把你精心抛出的「中断」翻译成一次普通的错误返回值 ——
        于是演练看起来跑完了，其实根本没崩。
        「中断」（超时 / 取消 / 关机）和「错误」是两类东西，必须走独立通道；
        这也是 Python 自己把 KeyboardInterrupt / SystemExit 放在 BaseException 分支的原因。
    """


# ---- 外部世界：它在进程**之外**，进程重启不会让它归零 -------------------
WORLD = {"lookup_order": 0, "archive_order": 0, "count_words": 0}

# 每一步要调的工具名（后面的假模型也按它推进）
PLAN = ["lookup_order", "archive_order", "count_words"]


def call_tool(name):
    """极简的「工具」：假装一次 RPC 或一次写库，会改外部世界并留下次数。"""
    WORLD[name] += 1                    # ★ 副作用真的发生了，只是没人记下来
    return {"lookup_order": "订单 A1001 已发货",
            "archive_order": "订单 A1001 已归档",
            "count_words": "共 6 个字"}[name]


def run_naive(task, messages, memory):
    """最朴素的一版 Agent 循环：一口气跑完，中途只写进程内存。

    参数 messages：本进程内存里的会话（Agent 的记忆）
         memory  ：本进程内存里的「状态快照」
    """
    messages.append({"role": "user", "content": task})      # 引擎第一步：追加用户消息
    for step, name in enumerate(PLAN, 1):
        result = call_tool(name)                            # ← 副作用在这里发生
        messages.append({"role": "tool", "name": name, "content": result, "ok": True})
        memory["state"] = {"messages": list(messages), "steps_done": step}   # 只写内存
        if step == 2:
            raise SimulatedCrash(f"进程在第 {step} 步之后被 kill")


print("【场景 A】任务跑到第 2 步，进程被 kill：")
memory = {}
try:
    run_naive("查订单 A1001、归档、再统计字数", [], memory)
except SimulatedCrash as exc:
    print("   发生的意外：", exc)
print("   崩溃前，内存里的检查点写着：", memory["state"]["steps_done"], "步已完成")
print()
print("【紧接着进程重启】内存里的东西全部消失（这才是「进程被杀」的真正含义）：")
memory.clear()                          # 重启 = 内存清零，而磁盘上我们什么都没写过
print("   重启后能读到的检查点数量：", len(memory))
print("   可外部世界已经真的变了：", dict(WORLD))
print()
print("★ 坏结果：已经跑完的两步（查订单 + 归档）**凭空消失**。")
print("  用户看到的是「失败」，而系统里其实已经有了一次归档 —— 两边对不上账。")
print("  他只能从头再来一遍，而那意味着再查一次、再归档一次。")''')

    nb.md("""### 结果说明什么

| 观察到的现象 | 根因 |
|---|---|
| 重启后检查点数量为 0 | 状态存在**进程内存**里，进程没了它就没 |
| 外部世界却已经变了 | 副作用发生在进程之外，**它不会跟着回滚** |
| 用户只能从头再来 | 我们没有任何东西可以「接着跑」 |

第一种失败（丢工作）还算「诚实」—— 用户知道失败了。
真正危险的是第二种。""")

    nb.code('''# 单独可运行：第二个坏结果 —— 用户重试一次，钱被扣了两次

# ---- 外部世界（进程之外）：账本 + 接口调用次数 ------------------------
WORLD = {"charge_calls": 0, "charged_cents": 0, "ledger": []}


def charge_user(user_id, cents):
    """扣款接口。**副作用发生在外部世界**，进程重启也不会撤销。"""
    WORLD["charge_calls"] += 1                      # 接口被调用了几次
    WORLD["charged_cents"] += cents                 # 真正扣掉的钱
    WORLD["ledger"].append(f"{user_id} -{cents} 分")
    return {"charged": True, "user_id": user_id, "cents": cents}


def submit_naive(user_id, cents, task):
    """一个「本地永远正确」的提交函数：一次请求 = 一次完整执行。"""
    return charge_user(user_id, cents)              # 每次提交都真的扣一次款


print("用户只提交了**一次**业务意图（给 u_42 续费 350 分）：")
print("   请求 A：", submit_naive("u_42", 350, "会员续费"))
print("   网络抖动，客户端没收到响应 → 它自动重试了一次：")
print("   请求 B：", submit_naive("u_42", 350, "会员续费"))
print()
print("   扣款接口被调用：", WORLD["charge_calls"], "次")
print("   实际扣款      ：", WORLD["charged_cents"], "分")
print("   账本          ：", WORLD["ledger"])
print()
print("★ 坏结果：用户只点了一次支付，钱被扣了两次 —— 这就是 P0 事故。")
print()
print("★ 为什么本地开发永远发现不了？")
print("   你不会点两次、不会断网、不会遇到 30 秒网关超时。")
print("   这些 bug 只在「请求会重复、连接会断」的环境里才浮出水面。")
print()
print("★ 根因：重试安全（幂等）**不是客户端的事**，是服务端必须提供的保证。")
print("  客户端重试的行为是完全合理的：它不知道上次到底成没成功。")''')

    nb.md("""### 结论：这一章要补的五样东西

| 场景 | 需要什么能力 | 本节位置 |
|---|---|---|
| 崩溃丢工作 | **状态持久化**：状态写到进程之外，且写在步骤边界上 | ②③ |
| 重试重复扣款 | **幂等**：同一个业务意图，副作用只发生一次 | ④ |
| 200 并发打进来 | **并发控制**：有上限，满了快速拒绝而不是无限排队 | ⑤ |
| 网关 30 秒就断 | **超时降级**：返回半成品 + 说明 + 可续跑 | ⑥ |
| 下游已经躺了 | **熔断**：别再打它，快速失败，阻断故障扩散 | ⑤ |
| 线上出事要定位 | **结构化日志**：哪一次运行的哪一步失败了 | ⑦ |
| 改了提示词怕变坏 | **灰度 + 自动回滚**：坏版本只影响一部分流量 | ⑧ |

先解决第一个：**把状态从进程内存里搬出来。**""")

    # ==================================================================
    section(nb, "②", "检查点：把状态从进程里搬出来")

    nb.md("""### 现在卡在哪

崩溃丢工作的根因只有一句话：**状态活在进程里。**

而好消息是：Agent 的状态其实**非常少**。第 01 章的第一课就是
「Agent 的记忆就是那个 `messages` 列表」—— 所以持久化要存的东西只有四样：

```
一次运行的全部状态
├─ messages          会话（Agent 的「记忆」，也是恢复的唯一依据）
├─ steps_done        已完成的步数（决定还剩几步预算）
├─ tool_hits         各工具已成功执行的次数（证明「没白跑、没重跑」）
└─ partial_answer    当前能拿得出手的半成品（超时降级时给用户看的东西）
```

### 所以我需要一个「运行状态快照」的结构

用 `dataclass` 把它声明出来。它是本章最重要的数据结构，字段逐个说清：

| 字段 | 含义 | 为什么不能省 |
|---|---|---|
| `run_id` | 这是哪一次运行 | 所有日志、检查点、幂等缓存的关联键 |
| `messages` | 最近一次保存时的完整会话 | 恢复时重建「Agent 的记忆」 |
| `messages_before` | **本条 run 的起点会话**（用户消息之前） | 恢复时要「倒回」到它，见 ③ |
| `start_captured` | 起点到底记过没有（**独立的 bool**） | 不能用「起点是不是空」来判断，见下 |
| `steps_done` | 已跑完几步 | 决定「还剩几步预算」 |
| `tool_hits` | 每个工具成功执行了几次 | 用来自证「没白跑、没重跑」 |
| `partial_answer` | 半成品答案 | 超时降级时用户能看到的东西 |
| `state` | 状态机：pending/running/crashed/done/failed | 说不清「这条记录算不算跑完」就没法运维 |

### 一个必须先讲清的坑：不能用「空值」代表「没设置」

`dataclass` 的写法（`@dataclass` 帮你生成 `__init__`，`field(default_factory=list)`
用来给可变类型一个**每次新建**的默认值 —— 直接写 `= []` 会让所有实例共享同一个列表）：

```python
@dataclass
class RunState:
    messages_before: list = field(default_factory=list)
    start_captured: bool = False        # ★ 独立的标记
```

**为什么不能写 `if not self.messages_before: 记录起点`？**
因为首次运行时，起点**本来就是空会话**（连用户消息都还没追加）。
空值是**合法取值**，不是「没设置」—— 判据直接失效。

### 立刻用一次""")

    nb.code('''# 单独可运行：RunState 的字段，以及「空值当哨兵」这个坑
from dataclasses import dataclass, field


@dataclass
class RunState:
    """一次 Agent 运行的可持久化快照。**这就是本章的核心数据结构。**"""

    run_id: str
    # 会话（Agent 的全部记忆）。恢复时靠它重建「已经做到哪儿了」。
    messages: list = field(default_factory=list)
    # ★ 起点会话：本条 run **用户消息之前**的样子。恢复时从这里重放（见 ③）。
    messages_before: list = field(default_factory=list)
    # ★★ 独立 bool 标记：起点到底记过没有。
    #    绝不能用「messages_before 是不是空」来判断 —— 首次运行的起点本来就是空会话，
    #    空值是**合法取值**，拿空值当哨兵 = 判据在第一次就失效。
    start_captured: bool = False
    steps_done: int = 0
    # 各工具已成功执行的次数：用来证明「没白跑、没重跑」
    tool_hits: dict = field(default_factory=dict)
    # 半成品答案：超时降级时给用户看的东西（有半成品远好过什么都没有）
    partial_answer: str = ""
    # 状态机取值。生产系统里这张状态图必须显式定义，
    # 否则你永远说不清「这条记录到底算不算跑完了」。
    state: str = "pending"

    def snapshot_start(self, conv):
        """记录「本条 run 的起点」—— **一次 run 只写一次，之后永不覆盖**。

        ★ 为什么必须「只写一次」？看这条我们真的踩过的 bug 链：
            ① 起点在 run 开始时正确记为「0 条消息」（首次运行本来就是空会话）；
            ② 崩溃处理里「顺手」又写了一次 `messages_before = 当前会话`，
               把起点覆盖成了「跑了一半的状态」；
            ③ 恢复时按这个起点重放 → 用户消息被追加第二次 →
               模型看到重复的问题、以为什么都没做 → 从头再做一遍；
            ④ 最终答案是对的、检查点也在、日志也正常，
               只有**工具调用次数悄悄翻倍** —— 而这正是幂等要防的事故本身。

        教训：**同一个语义字段只能有一个写入点。**
        多写入点 + 无保护 = 迟早写错，而且错得很难看出来。
        """
        if self.start_captured:             # ★ 已经记过 → 直接返回，绝不覆盖
            return
        self.messages_before = [dict(m) for m in conv]
        self.start_captured = True


# ---- 对照实验：两种判据在「首次运行」下的表现 ----
naive = {"messages_before": []}             # 只有一个列表字段，没有 bool 标记
state = RunState(run_id="run-1")

print("首次运行时，起点本来就是空会话（连用户消息都还没追加）：")
verdict = "空 → 认为「起点还没记过」→ 又记一次（判据失效 ❌）" if not naive["messages_before"] \\
    else "记过了"
print("   朴素判据 `if not messages_before`：", verdict)
state.snapshot_start([])                    # 第一次：起点就是空会话
print("   正确判据 `start_captured`        ：", state.start_captured, "→ 记过了 ✅")
print()

state.snapshot_start([{"role": "user", "content": "跑到一半的状态"}])   # 崩溃处理「顺手」又记一次
print("崩溃处理里再调一次 snapshot_start 之后：")
print("   messages_before =", state.messages_before, " ← 空列表 = 起点没有被覆盖 ✅")
print()
print("★ 如果这里被覆盖成「跑了一半的会话」，恢复时就会多追加一条用户消息；")
print("  这条 bug 链在 ③ 里会完整演示一遍（包括工具调用怎么翻倍）。")''')

    nb.md("""### 现在卡在哪（第二个问题）

`RunState` 有了，接下来要把它**写到进程之外**。最直觉的写法是：

```python
path.write_text(json.dumps(state))          # ❌ 危险
```

**为什么危险？** 因为写入不是一瞬间的事：

```
t0  打开文件（内容立刻被截断成 0 字节）
t1  ← 进程正好在这里被杀（发布重启 / OOM）
t2  新内容才写完

结果：磁盘上留下一个**半截 JSON**。
      「崩溃恢复」于是退化成「崩溃 + 数据损坏」，比没有检查点更糟。
```

### 所以我需要一个「要么全旧、要么全新」的写文件方式

这就是**原子写**，所有数据库的通用套路，只用到三个标准库函数：

| 函数 | 签名 | 干什么 | 返回 |
|---|---|---|---|
| `tempfile.mkstemp` | `mkstemp(dir=..., prefix=..., suffix=...)` | 在同一目录里造一个临时文件 | `(文件描述符 fd, 绝对路径)` |
| `os.fsync` | `os.fsync(fd)` | 把页缓存**真正刷到磁盘**（不是「写完就安全」） | `None` |
| `os.replace` | `os.replace(src, dst)` | 同一文件系统内的**原子**改名 | `None` |

顺序不能变：**写临时文件 → `fsync` → `os.replace`**。
改名的原子性保证：任何时刻读到的要么是完整的旧内容，要么是完整的新内容，没有中间态。

> 为什么临时文件必须和目标是**同一个目录**？因为跨文件系统的 `rename` 不是原子的，
> 有些实现会退化成「复制 + 删除」—— 那又回到半截文件了。

### 立刻用一次""")

    nb.code('''# 单独可运行：检查点落盘 —— 原子写（临时文件 → fsync → os.replace）
import json
import os
import pathlib
import shutil
import tempfile

# ★ 为什么放在工作区内部，而不是系统临时目录？
#   受限环境（沙箱 / CI）下系统临时目录可能不可写；放在工作区里最可靠。
#   而且本格会在 finally 里把它删掉 —— 绝不在仓库里留垃圾。
CKPT = pathlib.Path.cwd() / ".nb13_tmp_ckpt"
shutil.rmtree(CKPT, ignore_errors=True)
CKPT.mkdir(parents=True, exist_ok=True)


def save_atomic(path, payload):
    """原子地写一个 JSON 文件：要么全是旧内容，要么全是新内容，没有中间态。

    参数 path   ：最终文件路径（Path）
         payload：可以被 json 序列化的对象
    返回        ：None；失败时抛异常（并清理临时文件）
    """
    # ① 在**同一个目录**里造临时文件（跨文件系统的改名不是原子的）
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False))
            f.flush()                   # 把 Python 的缓冲区交给操作系统
            os.fsync(f.fileno())        # ★ 再让操作系统真正落盘，而不是留在页缓存里
        os.replace(tmp, path)           # ★ 原子改名：此刻起，读者要么看到旧的全量，要么看到新的全量
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)   # 失败不留半截临时文件
        raise


def load_checkpoint(path):
    """读检查点。**坏文件不能连累主流程**：宁可当成「没有」，也不要抛异常。"""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        # 真实场景：文件被写坏、被人工改坏、版本不兼容……
        # 「恢复」这一步本身绝不该成为新的故障点。
        return None


try:
    # ---- 存一份「跑到第 2 步」的状态 ----
    state = {"run_id": "run-1", "steps_done": 2, "tool_hits": {"lookup_order": 1},
             "partial_answer": "已通过 lookup_order 拿到结果", "messages": []}
    path = CKPT / "run-1.json"
    save_atomic(path, state)
    print("已原子写入：", path.name, "，大小", path.stat().st_size, "字节")
    print("读回来      ：", {k: v for k, v in load_checkpoint(path).items() if k != "messages"})
    print()

    # ---- 对照：非原子写留下的「半截 JSON」长什么样 ----
    broken = CKPT / "run-2.json"
    broken.write_text('{"run_id": "run-2", "steps_do', encoding="utf-8")   # 写到 t1 就被杀了
    print("非原子写留下的半截文件：", repr(broken.read_text(encoding="utf-8")))
    print("load_checkpoint 的返回：", load_checkpoint(broken),
          " ← 当成「没有检查点」，而不是抛异常把恢复流程也带崩")
    print()
    print("目录里现在有：", sorted(p.name for p in CKPT.glob("*.json")))
    print("★ 注意 .tmp-*.json 一个都没剩下 —— os.replace 把临时文件「变成」了正式文件。")
finally:
    # ★ 本格绝不留下残留文件（其他写的格同理）
    shutil.rmtree(CKPT, ignore_errors=True)

print()
print("收尾后临时目录还在吗？", CKPT.exists(), " ← False 表示仓库是干净的")''')

    nb.md("""### 结果说明什么

- **原子写不需要任何第三方库**：`mkstemp` + `fsync` + `os.replace` 就够，
  换成 Redis 时它帮你做的就是这三件事（外加 TTL、并发、集群）。
- **坏文件必须降级成「没有」**，不能抛异常：恢复流程自己崩掉，
  等于把「一次事故」放大成「事故 + 数据不可达」。
- **写在哪里？** 教学用文件；生产用 Redis（快、带 TTL）/ Postgres（要事务、要查询）/
  S3（要归档）—— 接口一模一样（`save` / `load` / `list_run_ids`），
  换的是实现，不是逻辑。

> 反过来说：**不要用本地磁盘存检查点**。K8s 里 Pod 是无状态的，
> 同一台机器的本地文件下次调度根本找不到 —— 这正是 `InMemoryCheckpointStore`
> 那个教训的升级版。

现在状态存下来了。但「怎么用它恢复」才是本章最容易写错的地方。""")

    # ==================================================================
    section(nb, "③", "恢复 = 倒回起点 + 重放")

    nb.md("""### 现在卡在哪

检查点在磁盘上了。但「恢复」有两种做法，差别巨大：

```
 ✗ 做法一：接着中间状态写
     把「崩溃时进程内存里那个半截会话」当成新起点，从第 N 步接着算。
     问题：崩溃可能发生在「一步写了一半」的时候，那个状态**不自洽**；
          而且你**必须假设**模型和工具都是幂等的 —— 它们不是。

 ✗ 做法二：把完整会话原样塞回引擎
     引擎的第一步永远是「追加用户消息」（core/agent.py 的 run() 就是这样）。
     会话里已经有一条用户消息了 → **用户消息出现两次**。

 ✓ 正确做法：倒回起点 + 重放
     起点 = 检查点里的「用户消息之前」的会话；
     重放 = 把「已完成的事实」按顺序装回去。
     于是引擎再追加用户消息时，历史被**精确复原**（不是「大致接上」）。
```

### 为什么「用户消息出现两次」是灾难

看这条完整的 bug 链（每一环都真的会发生）：

```
  ① 恢复时没倒回 → 会话里出现两条一模一样的用户消息
  ② 模型判断「这件事做过没有」，看的是**最近那条用户消息之后**的工具结果
     （真实模型也是这样工作的：它把最近的问题当成当前任务）
  ③ 于是工具结果全被挡在那条重复消息之前 → 模型认为「什么都还没做」
  ④ 它从头再跑一遍：查订单、归档……**副作用又发生了一次**
  ⑤ 最终答案看起来是对的、检查点也在、日志也正常，
     只有**工具调用次数悄悄翻倍**
```

第 ⑤ 条是关键：**静默的错误远比崩溃危险**。崩溃有人报警，翻倍没人发现。

### 它的用法：一个最小的可续跑引擎

引擎的契约只有一句话（对照 `core/agent.py`）：

```python
def run_task(task, start, facts=(), ...):
    conv = list(start)                                  # 起点：用户消息之前
    conv.append({"role": "user", "content": task})      # ★ 引擎的第一步永远是追加用户消息
    conv.extend(facts)                                  # ★ 重放已完成的事实
```

### 立刻用一次：两种恢复方式对照""")

    nb.code('''# 单独可运行：崩溃 → 恢复。「不倒回」和「倒回 + 重放」的对照实验
import json
import os
import pathlib
import shutil
import tempfile


class SimulatedCrash(BaseException):
    """模拟「进程被 kill」。继承 BaseException 的用意见 ① 的说明。"""


# ---- 外部世界（进程之外）：副作用计数 ----------------------------------
WORLD = {"lookup_order": 0, "archive_order": 0, "count_words": 0}


def tool_lookup_order():
    WORLD["lookup_order"] += 1                  # ★ 副作用：真实里是一次 RPC
    return "订单 A1001 已发货"


def tool_archive_order():
    WORLD["archive_order"] += 1                 # ★ 副作用：真实里是一次写库
    return "订单 A1001 已归档"


def tool_count_words():
    WORLD["count_words"] += 1                   # 纯本地计算，不碰外部世界
    return "共 6 个字"


TOOLS = {"lookup_order": tool_lookup_order,
         "archive_order": tool_archive_order,
         "count_words": tool_count_words}
PLAN = ["lookup_order", "archive_order", "count_words"]
TASK = "查订单 A1001、归档、再统计字数"


def fake_model(conv):
    """假模型：看「最后一条用户消息之后」做过哪些工具，决定下一步。

    ★ 为什么按位置判断？因为真实模型也是这样工作的：
      它把**最近的那个问题**当成当前任务，判断「这件事做过没有」，
      依据是那条消息**之后**出现过的工具结果。
      所以「用户消息出现在会话中间」这种脏数据，对模型是真实的灾难。

    另外注意：已完成动作**只能从会话里推断**，不能靠进程内存 ——
    生产里的 Worker 是无状态的，同一个请求可能被负载均衡打到任何一台机器上。
    """
    last_user = max(i for i, m in enumerate(conv) if m["role"] == "user")
    done = {m["name"] for m in conv[last_user:] if m["role"] == "tool"}
    for name in PLAN:
        if name not in done:
            return name
    return None                     # None = 计划里的步骤都做完了，该给最终答案了


def run_task(task, start, facts=(), crash_after=None, on_step=None):
    """最小「可续跑」引擎。

    参数 task ：用户的任务文本
         start：**用户消息之前**的会话（起点）。恢复时要传「倒回之后的起点」。
         facts：已完成的事实（重放用）。首次运行传空。
         crash_after：跑到第几步就注入崩溃（None = 不崩）
         on_step    ：每一步完整做完时回调一次 —— **检查点就写在这里**
    返回：最终的会话（消息列表）
    """
    conv = [dict(m) for m in start]
    conv.append({"role": "user", "content": task})      # ★ 引擎的第一步永远是追加用户消息
    conv.extend(dict(m) for m in facts)                 # ★ 重放：把已完成的事实装回去
    head = len(start) + 1                               # 「用户消息之后」的下标（记账用）
    ran = 0
    for _ in range(len(PLAN) + 2):
        name = fake_model(conv)
        if name is None:
            return conv
        result = TOOLS[name]()                          # ← 副作用在外部世界发生
        conv.append({"role": "assistant", "content": f"Action: {name}"})
        conv.append({"role": "tool", "name": name, "content": result, "ok": True})
        ran += 1
        if on_step is not None:
            on_step(conv, head, name)                   # ← 步骤边界：写完检查点才继续
        if crash_after == ran:
            raise SimulatedCrash(f"进程在第 {ran} 步之后被 kill")
    return conv


# ---- 检查点：写在进程之外（磁盘） --------------------------------------
CKPT = pathlib.Path.cwd() / ".nb13_tmp_ckpt"
shutil.rmtree(CKPT, ignore_errors=True)
CKPT.mkdir(parents=True, exist_ok=True)
PATH = CKPT / "run-1.json"

STATE = {"run_id": "run-1", "start": [], "start_captured": False, "facts": [],
         "steps_done": 0, "tool_hits": {}, "partial_answer": "",
         "messages": []}


def save(state):
    """原子写（②里讲过：临时文件 → fsync → os.replace）。"""
    fd, tmp = tempfile.mkstemp(dir=str(CKPT), prefix=".tmp-", suffix=".json")
    with open(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(state, ensure_ascii=False))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, PATH)


def load():
    """读检查点。真实里这一步是 `GET run:{id}`（Redis）或一条 SELECT。"""
    return json.loads(PATH.read_text(encoding="utf-8"))


def on_step(conv, head, name):
    """观察者：一步**完整做完**之后立刻落盘（检查点必须钉在步骤边界上）。"""
    if not STATE["start_captured"]:
        # ★ 起点只写一次，之后永不覆盖（②里那条 bug 链的第二环）
        STATE["start"] = [dict(m) for m in conv[:head - 1]]
        STATE["start_captured"] = True
    # 事实清单 = 用户消息之后发生的一切（模型结果 + 工具结果，按顺序）
    STATE["facts"] = [dict(m) for m in conv[head:]]
    STATE["steps_done"] = len(STATE["facts"]) // 2
    STATE["tool_hits"][name] = STATE["tool_hits"].get(name, 0) + 1
    STATE["partial_answer"] = f"已完成 {name}"
    # 天真做法会拿这个「崩溃时的完整会话」当新起点 —— 下面就要看到它的后果
    STATE["messages"] = [dict(m) for m in conv]
    save(STATE)


try:
    # ================= 第 1 次提交：跑到第 2 步，进程被杀 =================
    print("【第 1 次提交】跑到第 2 步，进程被 kill：")
    try:
        run_task(TASK, start=[], crash_after=2, on_step=on_step)
    except SimulatedCrash as exc:
        print("   意外：", exc)
    before = dict(WORLD)
    print("   外部世界已发生的副作用：", before)
    print("   检查点：steps_done =", load()["steps_done"], "，tool_hits =", load()["tool_hits"])
    print()

    # ================= 恢复 A：✗ 不「倒回」 ==============================
    saved = load()
    WORLD.update({"lookup_order": 0, "archive_order": 0, "count_words": 0})   # 只看这一次恢复
    print("【恢复 A】✗ 把「崩溃时的完整会话」直接当成起点塞回引擎：")
    conv_a = run_task(TASK, start=saved["messages"])        # ← 会话里已经有一条用户消息了！
    users_a = sum(1 for m in conv_a if m["role"] == "user")
    print("   用户消息出现了", users_a, "次（正常应该是 1 次）")
    print("   这一次「恢复」新增的副作用：", dict(WORLD))
    print("   ^ lookup_order / archive_order 又被各执行了一次 —— 工具调用悄悄翻倍")
    print()

    # ================= 恢复 B：✓ 倒回起点 + 重放 ==========================
    WORLD.update({"lookup_order": 0, "archive_order": 0, "count_words": 0})
    print("【恢复 B】✓ 倒回「用户消息之前」的起点，再重放事实清单：")
    conv_b = run_task(TASK, start=saved["start"], facts=saved["facts"])
    users_b = sum(1 for m in conv_b if m["role"] == "user")
    print("   用户消息出现了", users_b, "次；会话长度", len(conv_b), "条")
    print("   这一次「恢复」新增的副作用：", dict(WORLD))
    print("   ^ lookup_order / archive_order 都是 0 —— 崩溃前做完的两步一步都没重跑")
    print()

    print("【对照表】崩溃前已经发生：lookup_order 1 次 / archive_order 1 次")
    print("   恢复 A 之后累计：lookup_order 2 次 / archive_order 2 次  ← 副作用翻倍 ❌")
    print("   恢复 B 之后累计：lookup_order 1 次 / archive_order 1 次  ← 才是「续跑」✅")
finally:
    shutil.rmtree(CKPT, ignore_errors=True)     # ★ 本格不留残留文件
print()
print("临时目录已清理：", not CKPT.exists())''')

    nb.md("""### 结果说明什么

| 写法 | 用户消息 | 恢复后的副作用 | 结论 |
|---|---|---|---|
| ✗ 把完整会话当起点 | **2 次** | 已完成的工具又各跑一次 | 这不是恢复，是**重跑** |
| ✓ 倒回起点 + 重放事实 | 1 次 | 一步都没重跑 | 这才是续跑 |

三条能带走的结论：

1. **检查点必须钉在「步骤边界」上**（一步要么没开始、要么完整完成）。
   写在「跑完」时等于没写 —— 崩的那一刻恰恰是没跑完的时候。
2. **恢复 = 倒回一个干净的边界 + 重放**，而不是「接着上次的中间状态写」。
   LangGraph 的 Checkpointer 也是这个模型：存 thread state，恢复时重放图。
3. **已完成动作只能从会话里推断**，不能靠进程内存。
   生产里 Worker 是无状态的：同一个请求下一跳可能落到另一台机器上，
   任何「跨请求残留的内存状态」在大规模部署里都会变成一类诡异 bug。

> 顺带一条更一般的工程建议：**状态尽量存「事实清单」，而不是「累计数字」。**
> `steps_done` 这种数字，一旦进程中途死过、续跑过，就极容易算重（1 → 3 → 6 → 10）。
> 而「把每一步追加进一个列表」天然幂等：死多少次都只是补几条。

丢工作的问题解决了。但恢复之后**重跑一遍**同样会造成重复副作用 ——
所以下一节必须解决「重试安全」。""")

    # ==================================================================
    section(nb, "④", "幂等：重试时副作用不能发生第二次")

    nb.md("""### 现在卡在哪

① 里已经看到那个事故：用户点一次支付，钱被扣了两次。

一个自然的想法是「那我在 API 层加个去重」：

```python
if request_id in seen:      # ❌
    return cached
```

**为什么这个不够？** 因为客户端重试时，`request_id` 几乎**总会是新生成的**——
它只是想再发一次同一个业务请求。用它当幂等键，等于没做幂等。

### 所以我需要一个「能代表业务意图」的幂等键

幂等的落点必须在**副作用那一层**（扣款函数里），而不是在 API 层糊一层「看起来没报错」。
而幂等键的生成要遵守两条：

```
① 作用域：幂等键是「命名空间内的唯一」，不是「全局唯一」
     客户端的 Idempotency-Key: "retry-1" 只是它**本地的重试计数器**。
     另一个用户碰巧也用了 "retry-1" → 缓存命中 → 钱记到别人头上。
     → 服务端必须把它和 (user_id, 业务意图) 拼起来才能当全局键。

② 稳定性：跨进程、跨机器都要算出同一个键
     内置 hash() 带随机盐（PYTHONHASHSEED）→ 进程 A 算的键进程 B 认不出来
     → 重启之后幂等失效 → 重复扣款又回来了。
     → 用 sha256。
```

### 它的用法

| 函数 | 签名 | 返回 |
|---|---|---|
| `hashlib.sha256` | `sha256(bytes)` | 一个 hash 对象，用 `.hexdigest()` 拿十六进制字符串 |
| 拼接约定 | `"\\x1f".join(parts)` | 用**不可见分隔符**拼，避免 `("ab","c")` 和 `("a","bc")` 撞车 |

真实系统里客户端和服务的分工是这样的：

| 场景 | 幂等键由谁生成 | 为什么 |
|---|---|---|
| 扣款 / 下单 | **客户端**（HTTP 头 `Idempotency-Key`） | 只有它知道「这次算不算新的一次」 |
| 归档某订单 / 初始化某账号 | **服务端按业务主键推导** | 操作天然唯一（同一个订单归档一万次也只算一次） |

### 立刻用一次""")

    nb.code('''# 单独可运行：幂等键的作用域 —— 为什么不能直接用客户端给的 key
import hashlib


def fingerprint(*parts):
    """把几段文本压成一个稳定的短指纹。

    ★ 为什么用 sha256，而不是内置 hash()？
        内置 hash() 带随机盐（PYTHONHASHSEED），**跨进程不稳定**：
        进程 A 算出来的键，进程 B 认不出来 → 重启后幂等失效 → 重复扣款又回来了。
        这是极隐蔽的一类 bug：单进程测试永远发现不了。
        sha256 跨进程、跨机器都稳定（⑧ 的灰度分桶也要靠它）。
    """
    # 用不可见分隔符拼接：否则 ("ab", "c") 和 ("a", "bc") 会拼成同一个串
    joined = "\\x1f".join(p.strip() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def cache_key_naive(client_key):
    """✗ 直接把客户端给的 key 当全局缓存键。"""
    return client_key


def cache_key(user_id, idempotency_key, task):
    """✓ 把「客户端给的键」和「业务上下文」绑在一起，得到真正的去重键。"""
    if not idempotency_key:
        return ""                       # 没给键 = 不做幂等（调用方自己承担后果）
    return fingerprint("idem", user_id, idempotency_key, task)


LEDGER = {}                              # 幂等账本：真实里是带唯一索引的一张表


def charge(user_id, cents, key):
    """扣款：先查账本，命中就返回第一次的结果（副作用不再发生）。"""
    if key in LEDGER:
        return {**LEDGER[key], "replayed": True}        # ★ 这是重放，不是新执行
    record = {"charged": True, "user_id": user_id, "cents": cents, "seq": len(LEDGER) + 1}
    LEDGER[key] = record
    return {**record, "replayed": False}


print("【事故现场】两个不同的用户，客户端各自用了本地的重试计数器 retry-1：")
print("   u_42 的请求：", charge("u_42", 350, cache_key_naive("retry-1")))
print("   u_9  的请求：", charge("u_9", 900, cache_key_naive("retry-1")))
print("   ^ u_9 的钱根本没扣，系统还告诉他扣了 350 分 —— 钱记到别人头上了")
print("   账本里只有：", LEDGER)
print()

LEDGER.clear()
print("【修好之后】把 user_id + 业务意图拼进键里：")
print("   u_42 的请求：", charge("u_42", 350, cache_key("u_42", "retry-1", "会员续费")))
print("   u_9  的请求：", charge("u_9", 900, cache_key("u_9", "retry-1", "会员续费")))
print("   u_42 真的重试了一次（同一个键）：",
      charge("u_42", 350, cache_key("u_42", "retry-1", "会员续费")))
print("   账本里有", len(LEDGER), "条记录 → 两个用户各扣一次，重试没有多扣")
print()
print("★ 一句话记住：幂等键是「命名空间内的唯一」，不是「全局唯一」。")
print("  设计幂等 API 时一定要问：这个 key 的**作用域**是什么？")
print("★ 换业务呢？键里带上 task（业务意图）就不会和别的业务撞车。")
print("  同一个用户第二天真的想再续费一次 —— 换个新键即可，这正是幂等键的正确语义：")
print("  它区分的是「业务意图」，不是「请求次数」。")''')

    nb.md("""### 现在卡在哪（还差三个细节）

幂等键的算法是对的，但生产上还有三件事必须做对，否则「看起来幂等了」：

```
① 工具必须把 replayed 标记透传给模型
     第二次如果返回一个不一样的结果，模型会对用户说「已为你扣款两次」——
     **副作用没错，叙述错了，用户照样投诉。**
     幂等要幂等到「用户体验」那一层。

② 失败绝不能写幂等缓存
     提前写会把「失败」缓存成「成功」：
     用户重试时拿到一个**假成功**，比重复执行更糟 —— 而且他不会再来。

③ 副作用层要有唯一约束兜底
     三层纵深防御，一层都不能省：
       第 1 层 schema 校验（便宜、在入口）
       第 2 层 函数内断言（拦住「长度够但语义是空」的垃圾键）
       第 3 层 数据库唯一索引 ★ 并发下唯一真正可靠的一层
     （「先 SELECT 再 INSERT」在并发下会双双通过检查，这叫 check-then-act 竞态。）
```

### 立刻用一次""")

    nb.code('''# 单独可运行：幂等落到「副作用那一层」的三个必备细节
from collections import Counter
import hashlib


def fingerprint(*parts):
    """稳定指纹（见上一格的说明：sha256，不用内置 hash）。"""
    joined = "\\x1f".join(p.strip() for p in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


# 两个计数器：分清「接口被调了几次」和「真正生效几次」
WORLD = Counter()
LEDGER = {}


def charge_user(user_id, cents, idem_key):
    """扣款（带幂等）。返回里必须带 `replayed` 标记 —— 那是给**模型**看的。"""
    WORLD["charge_calls"] += 1                       # 接口被调用次数（流量口径）
    record = LEDGER.get(idem_key)
    if record is not None:
        # ★ 第二次返回的是**第一次的原始结果 + replayed 标记**，而不是重算一个新的。
        #   因为调用方会把它写进上下文交给模型：如果第二次返回不一样的东西，
        #   模型就会对用户说「已为你扣款两次」—— 副作用没错、叙述错了，用户照样投诉。
        return {**record, "replayed": True}

    if cents > 100000:
        # ★ 失败路径：直接抛错，**绝不写账本**。
        #   把失败缓存成成功 = 用户重试时拿到一个假成功，比重复扣款更难查：
        #   他以为办成了，其实什么都没发生，而且他不会再来一次。
        raise ValueError(f"单笔金额 {cents} 分超过上限，拒绝执行")

    WORLD["charge_applied"] += 1                     # 真正生效次数（钱的口径）
    WORLD["charged_cents"] += cents
    record = {"ok": True, "seq": WORLD["charge_applied"], "user_id": user_id, "cents": cents}
    LEDGER[idem_key] = record                        # ★ 只有成功才落账本
    return {**record, "replayed": False}


KEY = fingerprint("idem", "u_42", "retry-1", "会员续费")
print("同一个幂等键提交两次（第二次是客户端重试）：")
print("   第 1 次：", charge_user("u_42", 350, KEY))
print("   第 2 次：", charge_user("u_42", 350, KEY))
print("   接口被调用", WORLD["charge_calls"], "次；真正扣款", WORLD["charge_applied"],
      "次；累计", WORLD["charged_cents"], "分")
print("   ^ 调用次数可以很大，**真正生效的次数永远是 1** —— 这就是幂等")
print()

BAD_KEY = fingerprint("idem", "u_42", "retry-2", "会员续费")
print("失败的那一次（金额超限）不会被写进账本：")
try:
    charge_user("u_42", 999999, BAD_KEY)
except ValueError as exc:
    print("   工具抛出的错误：", exc)
print("   这个键在账本里吗？", BAD_KEY in LEDGER, " ← False 才是对的")
print("   真正扣款次数仍然是：", WORLD["charge_applied"], "次（失败没有变成一次「成功」）")
print()
print("★ 幂等的验收标准只有两条，缺一不可：")
print("   1. 调用次数可以很大，而**副作用次数恰好等于业务上应该发生的次数**；")
print("   2. 每一次返回都把 replayed 标记透传出去，让模型说对话。")''')

    nb.md("""### 结果说明什么

| 做法 | 后果 |
|---|---|
| 用 `request_id` 当幂等键 | 客户端重试换了 ID → 幂等直接失效 |
| 用客户端给的 key 当全局键 | 别的用户碰巧同名 → 钱记到别人头上 |
| 用内置 `hash()` | 跨进程不稳定 → 重启后幂等失效 |
| 第二次返回一个「新结果」 | 模型叙述成「扣了两次」→ 用户投诉 |
| 失败也写缓存 | 用户重试拿到**假成功**，比重复执行更糟 |

一句话本质：**幂等不是「重试时不报错」，而是「重试时副作用不发生第二次」。**

到这里，「不丢工作」和「不重复副作用」都解决了。下一类是**容量**问题。""")

    # ==================================================================
    section(nb, "⑤", "过载与下游故障：两种「快速失败」")

    nb.md("""### 现在卡在哪

前面所有讨论都默认「请求能进来」。但生产的第一天你就会遇到：

```
   200 个并发 ──► 模型端 429（限流）──► 全部重试 ──► 更多请求 ──► 雪崩式超时
```

**过载不是「慢」，是「死」。** 每个 Agent run 都占着一条模型连接 + 一份内存，
没有上限时，一次流量尖峰就能把整个服务拖进不可恢复的状态。

### 所以我需要一个「并发闸门」

两种过载策略，必须选第二种：

```
 (A) 无限排队      延迟不可控地涨，用户等到 3 分钟后超时，还白占着连接 ——
                   排队把「过载」变成了「必然超时」

 (B) 快速拒绝 ★    返回 429 + Retry-After，诚实告诉对方「现在不行，0.5 秒后再试」
                   用户重试的成本，远低于挂死
```

生产标准答案：**短队列（吸收抖动）+ 队列满就拒绝（保护自己）**。

而且闸门必须放在**调模型之前** —— 等调完模型再限流，连接池早就被打满了。

### 它的用法

```python
gate = OverloadGuard(limit=5, queue_size=1)     # 同时最多 5 个，外加 1 个短队列位
gate.try_acquire()   # → "admitted" / "queued" / "rejected"
gate.release()       # 跑完释放；短队列里的下一个立刻顶上来
```

`peak` 字段是给我们**自证**用的：不管外面来多少请求，观测到的峰值并发不能超过 `limit`。

### 立刻用一次""")

    nb.code('''# 单独可运行：并发闸门 —— 短队列 + 队列满就快速拒绝
class OverloadGuard:
    """并发闸门（信号量）。真实里它就是连接池 / 服务端的并发上限。

    ★ 为什么是「拒绝」而不是「排队」？
        (A) 无限排队：延迟不可控地涨，用户等到 3 分钟后超时，还白占着连接 ——
            排队把「过载」变成了「必然超时」。
        (B) 快速拒绝：返回 429 + Retry-After，诚实告诉对方「现在不行，0.5 秒后再试」。
        生产的标准答案 = 短队列（吸收抖动）+ 队列满就拒绝（保护自己）。
    """

    def __init__(self, limit=5, queue_size=1, retry_after_s=0.5):
        self.limit = limit                  # 同时最多跑几个
        self.queue_size = queue_size        # 短队列容量：只用来吸收抖动，不是无限缓冲
        self.retry_after_s = retry_after_s  # 告诉被拒的调用方「多久后再来」
        self.in_flight = 0                  # 正在跑的
        self.waiting = 0                    # 在短队列里排队的
        self.peak = 0                       # 观测到的峰值并发（用来自证没超过上限）
        self.rejected = 0                   # 被快速拒绝的次数

    def try_acquire(self):
        """尝试进入。返回 admitted / queued / rejected 三种之一。"""
        if self.in_flight < self.limit:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            return "admitted"
        if self.waiting < self.queue_size:
            self.waiting += 1               # 进短队列（教学里不真的等）
            return "queued"
        self.rejected += 1                  # ★ 队列也满了 → 立刻拒绝，绝不无限排队
        return "rejected"

    def release(self):
        """一个请求跑完 → 释放名额；短队列里的下一个立刻顶上来。"""
        self.in_flight = max(0, self.in_flight - 1)
        if self.waiting > 0:
            self.waiting -= 1
            self.in_flight += 1             # 顶上来的这个依旧受上限约束
            self.peak = max(self.peak, self.in_flight)
            return "promoted"
        return "released"


LIMIT = 5              # ← 试着改这里：2 会拒绝得更多，10 峰值更高
ARRIVALS = 4           # 每个 tick 突发几个请求
JOB_TICKS = 3          # 一次模型调用占几个 tick（= 请求要占用连接多久）

gate = OverloadGuard(limit=LIMIT, queue_size=1)
running = []           # 每个元素 = {"left": 还剩几个 tick}

print(f"并发上限 {LIMIT}，模型调用一次占 {JOB_TICKS} 个 tick，每 tick 突发 {ARRIVALS} 个请求：")
print(f"{'tick':>5}{'在飞':>6}{'排队':>6}{'新接入':>8}{'被拒绝':>8}{'峰值':>6}")
for tick in range(1, 11):
    # ① 这一 tick 到期的请求跑完 → 释放名额（短队列里的下一个会顶上来）
    done = [r for r in running if r["left"] <= 0]
    running = [r for r in running if r["left"] > 0]
    for _ in done:
        if gate.release() == "promoted":
            running.append({"left": JOB_TICKS})     # 从短队列顶上来的开始跑
    # ② 这一 tick 新到的请求过闸门
    admitted = 0
    for _ in range(ARRIVALS):
        if gate.try_acquire() == "admitted":
            running.append({"left": JOB_TICKS})
            admitted += 1
    # ③ 时间前进：所有在飞的请求各消耗一个 tick
    for r in running:
        r["left"] -= 1
    print(f"{tick:>5}{gate.in_flight:>6}{gate.waiting:>6}{admitted:>8}{gate.rejected:>8}{gate.peak:>6}")

print()
print("★ 峰值并发 =", gate.peak, "，从未超过上限", LIMIT, "—— 这就是闸门的全部意义：")
print("  不管外面来多少，「在飞」顶到上限就再也不涨。")
print("★ 被拒绝", gate.rejected, "次：它们拿到的是 429 + Retry-After，而不是被挂死 3 分钟。")
print("★ 注意「排队」那一列始终只有 0~1：短队列只吸收抖动，不做无限缓冲。")
print("★ 闸门必须放在**调模型之前** —— 每个 run 都占着一条模型连接 + 一份内存，")
print("  等模型调完再限流，连接池早就被打满了。")''')

    nb.md("""### 现在卡在哪（第二种：下游已经躺了）

并发控制住了我们打出去的**量**，但还有一种情况：**下游自己坏了**。

```
   下游（模型服务 / 支付网关）已经 100% 失败，
   而你还在每个请求都去敲它一次、等它超时 ——
   结果：上游的线程 / 连接池被这些等待全部占满，故障从下游扩散到整条链路。
```

### 所以我需要一个「连续失败就停止调用下游」的开关

这就是**熔断器**（Circuit Breaker），三个状态是所有实现的标准形状
（Hystrix / Resilience4j 都一样）：

```
    CLOSED   ──连续失败 ≥ 阈值──►  OPEN
      ▲                             │
      │                       冷却时间到
   探测成功                         │
      └──── HALF_OPEN ◄────────────┘

    CLOSED     正常放行，统计失败
    OPEN       一律拒绝，**不再打下游**（快速失败）
    HALF_OPEN  只放**一个**探测请求：成了→恢复；不成→重新计时
```

**为什么 HALF_OPEN 只放一个？** 如果放一批，而下游还是坏的，
你就又把它打死了 —— 这叫**熔断抖动**。

### 它的用法（顺便解决「怎么测 30 秒冷却」）

`cooldown_s=30` 的冷却怎么测？`time.sleep(30)` 显然不行。答案是**注入时钟**：

| 方式 | 问题 |
|---|---|
| `time.sleep(30)` | 测试慢 30 秒、结果不确定、而且根本没法测「冷却结束后恢复」 |
| **`FakeClock` 手动推进** | 瞬间完成、永远稳定、想推进多少就多少 |

生产里这叫 Clock Injection：运行时只问 `clock()` 要「现在几点」，
**从不直接读系统时间**。Java 的 `java.time.Clock`、Go 的 `clockwork`、
Python 的 `freezegun` 都是这个思路 —— 你手写的这十行就是它们的原理。

### 立刻用一次""")

    nb.code('''# 单独可运行：熔断器三态 + 虚拟时钟（冷却 30 秒，真实耗时 0 秒）
class FakeClock:
    """可以手动推进的假时钟 —— 只在教学与测试里用。

    ★ 为什么不用 time.sleep 真等 30 秒？
        1. 自检 / Notebook 会卡 30 秒；
        2. 结果不确定（CI 机器慢一点就变成「没超时」）；
        3. 根本没法演示「冷却结束后恢复」。
    """

    def __init__(self, start=1000.0):
        # 起始值故意不是 0：万一哪里误用「时间戳是否为 0」做判断，会立刻暴露
        self._now = float(start)

    def __call__(self):
        """调一次 = 问「现在几点」。运行时代码只通过它读时间。"""
        return self._now

    def advance(self, seconds):
        """把时间往前推（可以为小数）。测试里用它代替 sleep。"""
        self._now += float(seconds)
        return self._now


class CircuitBreaker:
    """熔断器：连续失败到阈值就停止调用下游，直接快速失败。"""

    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

    def __init__(self, threshold=3, cooldown_s=30.0, clock=None):
        self.threshold = threshold          # 连续失败几次就跳闸
        self.cooldown_s = cooldown_s        # 断开后冷却多久再试探
        self.clock = clock or (lambda: 0.0)
        self.state = self.CLOSED
        self.failures = 0                   # 连续失败次数（成功会清零）
        self.opened_at = 0.0
        self.trips = 0                      # 跳闸次数
        self.short_circuited = 0            # 被「快速失败」挡掉的请求数（越大越省资源）
        self.probe_in_flight = False        # ★ 半开状态下是否已经有一个探测请求在路上

    def allow(self):
        """现在能调用下游吗？"""
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            if self.clock() - self.opened_at >= self.cooldown_s:
                self.state = self.HALF_OPEN         # 冷却结束 → 半开，试探一次
                self.probe_in_flight = False
            else:
                self.short_circuited += 1           # ★ 没有调用下游，直接挡掉
                return False
        # HALF_OPEN：只放一个探测请求，其余一律挡掉（否则就是「熔断抖动」）
        if self.probe_in_flight:
            self.short_circuited += 1
            return False
        self.probe_in_flight = True
        return True

    def record_success(self):
        if self.state == self.HALF_OPEN:
            self.state = self.CLOSED                # 探测成功 → 恢复
        self.failures = 0
        # ★ 无论成功还是失败都必须复位这个标志，否则熔断器会永远卡在半开
        #   （状态机卡死是熔断器最常见的实现 bug）
        self.probe_in_flight = False

    def record_failure(self):
        self.failures += 1
        self.probe_in_flight = False                # 同上：失败路径也要复位
        if self.state == self.HALF_OPEN or self.failures >= self.threshold:
            if self.state != self.OPEN:
                self.trips += 1
            self.state = self.OPEN
            self.opened_at = self.clock()           # 重新开始冷却计时

    def retry_after(self):
        """还要等多久才可能恢复（给用户一个诚实的估计，而不是让他盲等）。"""
        if self.state != self.OPEN:
            return 0.0
        return max(0.0, self.cooldown_s - (self.clock() - self.opened_at))


clock = FakeClock()
breaker = CircuitBreaker(threshold=3, cooldown_s=30.0, clock=clock)


def call_downstream(ok):
    """一次下游调用：先过熔断器，再决定是否真的打过去。"""
    if not breaker.allow():
        return f"circuit_open（{breaker.state}，{breaker.retry_after():.1f}s 后再试）"
    if ok:
        breaker.record_success()
        return "ok"
    breaker.record_failure()
    return "error"


print("【连续 5 次提交，而模型服务一直是坏的】（全程真实耗时 0 秒）")
for i in range(1, 6):
    print(f"   第 {i} 次：{call_downstream(ok=False):<44} 熔断器={breaker.state}")
print("   被快速挡掉：", breaker.short_circuited, "次 —— 这几次**根本没有调用下游**")
print("★ 价值：阻断故障扩散。下游躺了你还每个请求去敲它、等它超时，")
print("  只会把上游的连接池一起拖死，最后整条链路一起挂。")
print()

print("【冷却 30 秒后】只放一个探测请求过去：")
clock.advance(30.0)                             # ← 试着改成 29.9，看它是不是还停在 open
print("   探测 1（下游还是坏的）：", call_downstream(ok=False),
      f"→ 熔断器={breaker.state}，重新计时 {breaker.retry_after():.1f}s")
print("   探测 2（同一时刻又来一个）：", call_downstream(ok=False),
      " ← 半开只放一个，其余立刻挡掉")
clock.advance(30.0)
print("   再等 30 秒，让探测成功一次：", call_downstream(ok=True),
      f"→ 熔断器={breaker.state} ✅ 恢复正常")
print("   恢复之后的请求：", call_downstream(ok=True))
print()
print("★ 熔断器状态：", breaker.state, "；跳闸", breaker.trips, "次；累计挡掉",
      breaker.short_circuited, "个请求")''')

    nb.md("""### 结果说明什么

```
 第 1~3 次：error        （CLOSED，边失败边计数）
 第 4~5 次：circuit_open （OPEN，**一次下游调用都没发生**）
 冷却之后 ：半开只放一个探测，失败就重新计时；成功才恢复 CLOSED
```

- **熔断的价值是「省下注定失败的调用」**，而不是「让错误更快」。
- **`HALF_OPEN` 只放一个探测**，是防止「下游还没好就被二次打死」（熔断抖动）。
- **`probe_in_flight` 必须在成功和失败两条路径上都复位**，
  否则熔断器会永远卡在半开 —— 这类「状态机卡死」是它最常见的实现 bug。

> 注意 `allow()` 被挡住时，我们连一个字节都没有发给下游。
> 这正是「快速失败」与「超时失败」的差别：前者几乎不花时间，后者要白等一整个超时。

下一节处理另一类失败：**任务本身跑得太久。**""")

    # ==================================================================
    section(nb, "⑥", "超时降级：给半成品，而不是挂死")

    nb.md("""### 现在卡在哪

网关 30 秒就断开连接，而你的 Agent 任务可能想跑 90 秒。两种失败方式对比：

```
 ✗ 挂死：连接一直占着 → 网关 30 秒后断开 → 用户看到 504
         而你的进程还在傻跑 —— 算力白烧，用户还不知道进度
 ✓ 降级：2 秒返回半成品 + 「已完成 2/3 步，可续跑」
         用户能决策（要不要等 / 要不要重试），你也没有浪费算力
```

但「超时」这件事有一个非常容易写错的地方：**在哪个时刻收手？**

如果随便在「跑到一半」的地方砍掉，就会出现这种事故：

```
   已经超时了，可工具调用刚刚发出去 → 通知发出去了，但用户看到的是「超时失败」
   → 外部世界变了，用户却以为什么都没发生
```

### 所以我需要把「检查超时」钉在干净的步骤边界上

一圈循环里只有两个时刻是安全的：

| 时刻 | 是什么 | 保证 |
|---|---|---|
| `step_start` | 准备进入下一步 | 别一开始就来不及（省下一次注定无用的模型调用） |
| `llm_output` | ★ **模型刚回来、工具还没执行** | 停在这里，绝不会出现「超时了却又发了一条通知」 |

### 它的用法：预算（Budget）

```python
class Budget:
    def check(self, about_to):          # 超时就 raise，而不是返回 bool
        ...                             # ★ 返回 bool 会被「忘了判断」悄悄吞掉
```

用 `raise` 而不是 `return False` 是刻意的：超时是**必须被处理**的事件，
不是「可以顺手忽略」的返回值。

### 立刻用一次（用虚拟时钟让「超时」确定性可测）""")

    nb.code('''# 单独可运行：超时降级 —— 钉在步骤边界，返回「半成品 + 说明 + 可续跑」
class FakeClock:
    """虚拟时钟：让「超时」变成确定性事件，而不是「碰运气等他 3 秒」。"""

    def __init__(self, start=1000.0):
        self._now = float(start)

    def __call__(self):
        return self._now

    def advance(self, seconds):
        self._now += float(seconds)
        return self._now


class BudgetExceeded(Exception):
    """预算耗尽。它是**设计好的收手**，不是崩溃 —— 但必须被显式处理。"""


class Budget:
    """一次运行的时间预算。

    为什么 Agent 必须带预算？
        一次 run 的耗时不可预测（模型可能想 5 步，也可能想 50 步）。
        没有预算，一个卡住的请求就能占满连接池 → 拖垮整个服务。
        预算把「不可预测」变成「有界」。

    check() 用 raise 而不是返回 bool：这样超时**不能**被「忘了判断」悄悄吞掉。
    """

    def __init__(self, max_seconds, clock):
        self.max_seconds = max_seconds
        self.clock = clock
        self.started_at = clock()

    def elapsed(self):
        return self.clock() - self.started_at

    def check(self, about_to):
        """不够时间做 about_to 这件事就抛 BudgetExceeded。"""
        left = self.max_seconds - self.elapsed()
        if left <= 0:
            raise BudgetExceeded(
                f"预算耗尽（已用 {self.elapsed():.2f}s / 上限 {self.max_seconds:.2f}s），"
                f"来不及{about_to}"
            )


MODEL_COST_S = 0.30      # 每次模型调用的固定耗时 ← 试着改成 0.5 或 0.10
TIME_BUDGET_S = 0.75     # 整轮的时间预算      ← 试着改成 1.5，看它能不能跑完

clock = FakeClock()
budget = Budget(TIME_BUDGET_S, clock)
STATE = {"state": "running", "steps_done": 0, "tool_hits": {}, "partial_answer": ""}


def step(name):
    """跑一步：模型调用前后各检查一次预算（这就是两个步骤边界）。"""
    # ★ 检查点一：step_start —— 别一开始就来不及
    budget.check(f"第 {STATE['steps_done'] + 1} 步的模型调用")
    clock.advance(MODEL_COST_S)      # 模型调用耗时（虚拟时钟推进，绝不 sleep）
    # ★★ 检查点二：llm_output —— 模型刚回来、**工具还没执行**。
    #    停在这里，就绝不会出现「已经超时了，却又发了一条通知」这种事故。
    budget.check(f"第 {STATE['steps_done'] + 1} 步的工具执行")
    # 真正的副作用发生在这一行之后（真实里是写库 / 发通知 / 扣款）
    STATE["tool_hits"][name] = STATE["tool_hits"].get(name, 0) + 1
    STATE["steps_done"] += 1
    STATE["partial_answer"] = f"已完成 {name}"
    return f"{name} 完成"


PLAN = ["lookup_order", "archive_order", "count_words"]
print(f"时间预算 {TIME_BUDGET_S}s，每次模型调用固定耗时 {MODEL_COST_S}s：")
for name in PLAN:
    try:
        print(f"   {name:<14}→ {step(name)}")
    except BudgetExceeded as exc:
        print(f"   {name:<14}→ 收手：{exc}")
        break

print()
print("停机原因  ：timeout")
print("是否降级  ：True")
print("已完成步数：", STATE["steps_done"])
print("工具已发生：", STATE["tool_hits"], " ← 停在了第 3 步的工具执行**之前**")
print("半成品    ：", STATE["partial_answer"])
print("可续跑    ：检查点还在（state=crashed），拿 run_id 就能接着跑")
print()
print("★ 三件套齐了：半成品 + 明确说明 + 可续跑标记。")
print("  缺任何一件，用户都只能干等 —— 而干等的结果是网关先超时。")
print(f"★ 这个「0.75 秒超时」的实验真实耗时 0 秒（虚拟时钟被推进了 {budget.elapsed():.2f}s）。")
print()

# ---- 半成品能接着跑吗？能：换个更大的预算续跑 ----
print("【换个更大的预算续跑】")
budget = Budget(5.0, clock)                     # 新预算；时钟继续往前走
for name in PLAN[STATE["steps_done"]:]:         # 只跑「还没做的那几步」
    print(f"   {name:<14}→ {step(name)}")
print("   续跑后工具累计：", STATE["tool_hits"], " ← lookup_order / archive_order 没有被重跑")
print("★ 超时不是终局：状态还在，预算够了就能跑完 —— 这正是检查点的价值。")''')

    nb.md("""### 结果说明什么

| 观察点 | 含义 |
|---|---|
| 停在第 3 步的**工具执行之前** | 检查点钉在 `llm_output`：模型回来了，但副作用一个都没发生 |
| `tool_hits` 只有前两步 | 「没白跑、没重跑」的硬证据 |
| 返回里带 `partial_answer` + `explain` + `resumable` | 三件套：半成品 + 说明 + 可续跑 |
| 真实耗时 0 秒 | 时间是被**推进**出来的，不是等出来的 |

> 生产里的对应物：`asyncio.wait_for` / gRPC deadline / context deadline ——
> 本质都是「在外层拦截」，因为超时必须能打断任意深的调用栈。

最后一类问题是**排障**：线上出事了，你怎么知道发生了什么？""")

    # ==================================================================
    section(nb, "⑦", "结构化日志：回答「是哪一次运行的哪一步失败了」")

    nb.md("""### 现在卡在哪

生产事故的第一个问题永远是这句话：

> **是哪一次运行的哪一步失败了？**

自由文本日志答不了（只能人肉 grep + 猜）。而 Agent 的失败又特别难复现：
模型有随机性、网络有抖动、上下文每次都不一样。

### 所以我需要「一行一个 JSON」的日志

每条记录固定几个字段，每个字段都对应一个真实排障场景：

```
 字段     回答什么问题
 ──────── ──────────────────────────────────────────────────────
 ts       还原时序：是「先超时」还是「先报错」？顺序不同，根因不同
 run_id   ★ 全链路关联键。所有事件 + 所有下游调用都用它串起来（OTel 的 trace_id）
 step     定位「卡在第几步」—— 降级说明、重试决策都要用它
 event    机器可聚合：error 占比、checkpoint_saved 频率、各步耗时 p99
 ms       性能回归的第一手证据（模型变慢了？工具变慢了？）
 level    告警路由：warn 进周报，error 直接叫人
 （额外字段） 上下文：工具名、错误类型、路由决策、灰度版本……
```

### 它的用法

```python
log.emit("run_failed", run_id="run-777", step=1, level="error", reason="error")
log.by_run("run-777")        # → 这次运行的全部事件，按发生顺序
log.where_failed("run-777")  # → 第一条 error/fatal 记录（那个价值百万的问题的答案）
```

`json.dumps(rec, ensure_ascii=False)` 保证它同时是**人能读**的（中文不转义）
和**机器能解析**的（一行一个 JSON，可以直接喂给 ELK / ClickHouse）。

### 立刻用一次""")

    nb.code('''# 单独可运行：结构化日志 —— 一行一个 JSON，能定位「哪一次运行的哪一步失败了」
import json


class FakeClock:
    """确定性时钟：让日志里的 ts 每次都一样，Notebook 的输出才是可对照的。"""

    def __init__(self, start=31145.0):
        self._now = float(start)

    def __call__(self):
        return self._now

    def advance(self, seconds):
        self._now += float(seconds)
        return self._now


class EventLog:
    """结构化日志：一行一个 JSON 事件。

    为什么不用 `print("出错了")`？
        因为生产事故的第一个问题永远是「**是哪一次运行的哪一步失败了**」。
        自由文本日志答不了这个问题（只能人肉 grep + 猜）；
        结构化日志可以：按 run_id 一过滤，时间线直接出来。
    """

    def __init__(self, clock):
        self.records = []
        self.clock = clock

    def emit(self, event, run_id="", step=0, ms=0.0, level="info", **extra):
        """写一条事件。extra 里的任意键值会一起进 JSON（工具名、错误类型……）。"""
        rec = {
            "ts": round(self.clock(), 4),
            "run_id": run_id,           # ★ 全链路关联键（OTel 里就是 trace_id）
            "step": step,               # 卡在第几步
            "event": event,             # 机器可聚合的事件类型
            "ms": round(float(ms), 2),  # 耗时
            "level": level,             # 告警路由：info / warn / error
            **extra,
        }
        self.records.append(rec)
        return rec

    @staticmethod
    def to_line(rec):
        """渲染成一行紧凑 JSON —— 这就是它会写进日志文件的样子。"""
        return json.dumps(rec, ensure_ascii=False)

    def by_run(self, run_id):
        """★ 排障的核心操作：把一次运行的事件全部捞出来，按发生顺序看。"""
        return [r for r in self.records if r["run_id"] == run_id]

    def where_failed(self, run_id):
        """回答那个价值百万的问题：**run X 是哪一步失败的？**"""
        for rec in self.by_run(run_id):
            if rec["level"] in {"error", "fatal"}:
                return rec
        return None

    def counts_by_event(self):
        """事件类型计数：error 占比、各事件频率（看板上的第一张图）。"""
        out = {}
        for rec in self.records:
            out[rec["event"]] = out.get(rec["event"], 0) + 1
        return out


clock = FakeClock()
log = EventLog(clock)

# ---- 一次失败的 run 的完整时间线 ----------------------------------------
log.emit("run_start", run_id="run-777", messages=1)
clock.advance(0.004)
log.emit("step_start", run_id="run-777", step=1)
clock.advance(0.311)
log.emit("llm_output", run_id="run-777", step=1, ms=311.0, tokens=180)
log.emit("run_failed", run_id="run-777", step=1, level="error",
         reason="error", error="模型服务 503（连续失败 1 次）")

print("一次失败的 run 的完整时间线（每一行都是一个可被机器解析的 JSON）：")
for rec in log.by_run("run-777"):
    print("   ", EventLog.to_line(rec))
print()

bad = log.where_failed("run-777")
print("★ 那个价值百万的问题：「run-777 是哪一步失败的？」")
print(f"   答案：第 {bad['step']} 步，事件 {bad['event']}，原因 {bad['reason']}，"
      f"错误={bad['error']}")
print("   ^ 按 run_id 一过滤，时间线直接出来 —— 不需要猜、不需要爬全量日志")
print()
print("★ 自由文本日志（「出错了」）回答不了这个问题：它没有 run_id，也没有 step。")
print("★ 事件计数（机器聚合的第一手数据）：", log.counts_by_event())
print("★ 真实系统里 run_id 会作为 trace_id 透传到所有下游调用 ——")
print("  第 10 章的可观测性（trace / 指标）在这里闭环。")''')

    nb.md("""### 结果说明什么

- **`run_id` + `step` 是两个不可替代的字段。** 少了 `run_id`，你只能看到一堆
  「某处出错了」；少了 `step`，你知道哪次运行错了却不知道卡在哪。
- **`event` 让日志可以被聚合**：`run_failed` 占比、`checkpoint_saved` 频率、
  各步 `ms` 的 p99 —— 监控看板和告警规则都建立在这一列上。
- **`level` 决定谁来处理**：`warn` 进周报，`error` 直接叫人。

> 一条经验：**能回答「哪一次运行的哪一步」的日志，才叫生产日志。**
> 剩下的都是给人看着安心的。

最后一节：**怎么把新版本安全地放上线** —— 因为 Agent 的输出是概率性的，
单元测试证明不了「它没变坏」。""")

    # ==================================================================
    section(nb, "⑧", "灰度发布与自动回滚")

    nb.md("""### 现在卡在哪

传统服务改代码，单测能覆盖 90%。但 Agent 改了提示词、换了模型、加了工具，
**你没法靠单测证明它没变坏** —— 输出是概率性的。

```
   离线：靠评估集（第 10 章）挡住明显的退化
   在线：靠灰度（本章）用真实流量验证 —— 两者是一对
```

### 所以我需要一个「按比例切流量 + 指标驱动自动回滚」的路由器

```
 流量 ──► 路由器 ──┬── 60% ──► stable 版本
                   └── 40% ──► canary 版本（新提示词 / 新模型 / 新工具）
                                  │
                            实时统计错误率、延迟
                                  │
                     窗口错误率 > 阈值？ ──► ★ 自动回滚（开关级，秒级生效）
```

分桶必须用**稳定哈希**，不能用 `random()`：

| 方式 | 后果 |
|---|---|
| `random()` | 用户刷新一下就被分到另一个版本，**答案突然变了**；同一请求在多台机器上落点不同，灰度比例变成一锅粥 |
| 内置 `hash()` | 带随机盐，**跨进程不稳定** —— 换一个进程就是另一套分桶 |
| **`sha256`** | 跨进程、跨机器都稳定 —— 灰度实验的数据才可信 |

### 它的用法

```python
bucket = int(sha256(request_id).hexdigest()[:8], 16) % 100
version = "canary" if bucket < rollout_percent else "stable"
```

`int(x, 16)` 是「把十六进制字符串当整数读」——`sha256` 的结果是十六进制文本，
取前 8 个字符就够散开了，得到一个 0~99 的桶。

### 立刻用一次""")

    nb.code('''# 单独可运行：灰度分桶必须用「稳定哈希」，不能用 random
import hashlib
import random


def bucket_stable(request_id, salt="agent-v2"):
    """把 request_id 稳定地映射到 0~99 的一个桶。

    参数 request_id：外部给的稳定键（请求 ID / 用户 ID）
         salt      ：换一次 salt 就换一套分桶，可以安全地重启一次实验
    返回          ：0~99 的整数
    """
    digest = hashlib.sha256(f"{salt}:{request_id}".encode("utf-8")).hexdigest()
    # int(x, 16) = 把十六进制字符串按 16 进制读成整数；取前 8 位已经足够散开
    return int(digest[:8], 16) % 100


def pick_stable(request_id, rollout=40):
    """稳定版：同一个 request_id **永远**落进同一个版本。"""
    return "canary" if bucket_stable(request_id) < rollout else "stable"


rng = random.Random(20260101)      # 固定种子只为让本 Notebook 的输出每次一样


def pick_random(request_id, rollout=40):
    """✗ 反面教材：每次调用都重新掷骰子。真实系统里没有种子，行为完全一样。"""
    return "canary" if rng.random() * 100 < rollout else "stable"


REQUESTS = [f"req-{i:03d}" for i in range(1, 13)]
print("同一个 request_id 连续查 3 次（rollout = 40%）：")
print(f"{'request_id':<11}{'桶':>4}   {'稳定哈希':<22}{'random':<22}稳定？")
for rid in REQUESTS[:6]:
    stable = [pick_stable(rid) for _ in range(3)]
    rnd = [pick_random(rid) for _ in range(3)]
    mark = "是 ✅" if len(set(stable)) == 1 else "否 ❌"
    print(f"{rid:<11}{bucket_stable(rid):>4}   {'/'.join(stable):<22}{'/'.join(rnd):<22}{mark}")

canary_n = sum(1 for rid in REQUESTS if pick_stable(rid) == "canary")
wobble = sum(1 for rid in REQUESTS if len({pick_random(rid) for _ in range(3)}) > 1)
print()
print(f"稳定哈希：{len(REQUESTS)} 个请求里 {canary_n} 个走 canary（目标 40% 附近），"
      "同一个请求查几次都落在同一版本")
print(f"random  ：{len(REQUESTS)} 个请求里有 {wobble} 个「刷新一下版本就变了」"
      "（真实系统里连这个数字本身每次都不同）")
print()
print("★ 灰度要的是「同一批用户始终在新版本上」的**粘性**：")
print("  否则你既解释不了指标，也没法把某次出问题的请求「钉」在某个版本上复现。")
print("★ 用 request_id 还是 user_id 分桶？想做「同一个用户体验一致」就用 user_id；")
print("  想快速拿到更多样本就用 request_id —— 这是产品决策，不是技术细节。")''')

    nb.md("""### 现在卡在哪（自动回滚的两个护栏）

有了稳定的分桶，还要决定「什么时候回滚」。两个最容易写错的护栏：

```
 护栏一：min_samples —— 样本太少时比例没有统计意义
        1 个请求失败 = 100% 错误率 → 你会对着一个新版本疯狂回滚

 护栏二：滑动窗口 —— ★ 用「最近 N 次」的错误率，不要用总错误率
        总错误率会被「上线前的健康历史」稀释：
        你会眼睁睁看着它从 0.1% 慢慢爬，等它超过阈值时已经烧了一片。
```

### 它的用法

```python
stats.record(ok, lookback=20)      # 每处理一个请求记一次
stats.error_rate()                 # 总错误率（值班看板上的数字）
stats.window_error_rate(window=20) # ★ 滑动窗口错误率（灰度决策用的数字）
```

### 立刻用一次""")

    nb.code('''# 单独可运行：自动回滚 —— min_samples 护栏 + 滑动窗口错误率
from dataclasses import dataclass, field


@dataclass
class VersionStats:
    """一个版本的在线指标（灰度决策的唯一依据）。"""

    name: str
    total: int = 0                    # 一共处理了多少请求
    errors: int = 0                   # 其中失败了多少
    recent: list = field(default_factory=list)     # 最近 N 次的成败（滑动窗口）

    def record(self, ok, lookback=20):
        self.total += 1
        self.recent.append(bool(ok))
        if len(self.recent) > lookback:
            self.recent = self.recent[-lookback:]  # 滑动：只保留最近 lookback 次
        if not ok:
            self.errors += 1

    def error_rate(self):
        """总错误率（值班看板上的数字）。"""
        return self.errors / self.total if self.total else 0.0

    def window_error_rate(self, window=20):
        """★ 滑动窗口错误率（灰度决策用的数字）。

        为什么不用总错误率做决策？
            新版本刚上线时，总错误率被「上线前的健康历史」稀释了，
            你会看着它从 0.1% 慢慢爬，等它超过阈值时已经烧了一片。
            窗口对**最近**的行为敏感，能让你早 10 分钟发现问题。
        """
        recent = self.recent[-window:]
        return sum(1 for ok in recent if not ok) / len(recent) if recent else 0.0


class CanaryRouter:
    """灰度路由器：决定走哪个版本，并在新版本变坏时**自动回滚**。"""

    def __init__(self, rollout=40, error_threshold=0.25, min_samples=4, lookback=20):
        self.rollout = rollout                    # 先放多少比例给新版本
        self.error_threshold = error_threshold    # 错误率超过多少算「坏了」（通常取基线 2~3 倍）
        self.min_samples = min_samples            # ★ 样本不足就别急着回滚
        self.lookback = lookback                  # 滑动窗口大小
        self.enabled = True                       # 灰度开关（feature flag）
        self.stats = {"stable": VersionStats("stable"), "canary": VersionStats("canary")}
        self.rollback_reason = ""

    def record(self, version, ok):
        """记录一个请求的结果，并检查是否需要回滚。"""
        self.stats[version].record(ok, self.lookback)
        self._maybe_rollback()

    def _maybe_rollback(self):
        """★ 自动回滚：唯一正确的触发方式是「由指标驱动」，而不是「由人盯着」。"""
        if not self.enabled:
            return
        canary = self.stats["canary"]
        if canary.total < self.min_samples:
            return                    # 护栏一：样本不足，比例没有统计意义
        rate = canary.window_error_rate(self.lookback)      # 护栏二：滑动窗口，不是总错误率
        if rate > self.error_threshold:
            self.enabled = False      # ★ 开关级回滚：不用重新发布，秒级生效
            self.rollback_reason = (
                f"新版本窗口错误率 {rate * 100:.1f}% 超过阈值 "
                f"{self.error_threshold * 100:.0f}%（样本 {canary.total}），已自动回滚到 stable"
            )

    def report(self):
        s, c = self.stats["stable"], self.stats["canary"]
        return (f"stable 请求 {s.total:>3} 错误 {s.errors:>2} | "
                f"canary 请求 {c.total:>3} 错误 {c.errors:>2} "
                f"总错误率 {c.error_rate() * 100:>5.1f}% 窗口错误率 {c.window_error_rate() * 100:>5.1f}%")


# ---- 实验一：min_samples 护栏拦住「1 个请求失败就回滚」 -----------------
print("【实验一】样本不足时不要决策")
router = CanaryRouter()
for _ in range(2):
    router.record("canary", ok=False)          # 2 个失败，但样本 < min_samples(4)
print("   2 个失败之后：", router.report())
print("   是否已回滚？", not router.enabled, " ← False 才对（样本不足，比例没有统计意义）")
router.record("canary", ok=False)
router.record("canary", ok=False)              # 累计 4 个样本、100% 失败
print("   4 个失败之后：", router.report())
print("   是否已回滚？", not router.enabled, " ←", router.rollback_reason)
print()

# ---- 实验二：总错误率 vs 滑动窗口错误率 ---------------------------------
print("【实验二】新版本前面已经有 100 个健康样本（模拟上线前的历史）")
router2 = CanaryRouter()
for _ in range(100):
    router2.record("canary", ok=True)          # 历史健康数据
print(f"   {'失败次数':<8}{'总错误率':>10}{'窗口错误率':>12}{'是否回滚':>10}")
for i in range(1, 8):
    router2.record("canary", ok=False)         # 新版本开始连续失败
    c = router2.stats["canary"]
    print(f"   {i:<8}{c.error_rate() * 100:>9.1f}%{c.window_error_rate() * 100:>11.1f}%"
          f"{'是 ✅' if not router2.enabled else '否':>10}")
    if not router2.enabled:
        break
print()
print("   ", router2.rollback_reason)
print("★ 总错误率被 100 个健康样本稀释，只有 5% 上下 —— 用它做决策，你永远等不到回滚；")
print("  滑动窗口在错误率达到 30% 时立刻触发。**这就是为什么必须用窗口。**")
print("★ 回滚是开关级动作：不需要重新发布，流量瞬间全部回到 stable。")''')

    nb.md("""### 结果说明什么

| 实验 | 结论 |
|---|---|
| 2 个失败 → 不回滚 | `min_samples` 护栏有效：样本太少时比例没有统计意义 |
| 4 个失败 → 回滚 | 护栏满足后，错误率一超阈值就动手 |
| 100 个健康 + 6 个失败 | 总错误率只有 5.7%（永远不触发），**窗口错误率 30% 立刻触发** |

三句话记住灰度：

1. **按稳定哈希分桶**（sha256，不用 `random()`）—— 让同一个请求始终落在同一个版本上。
2. **用滑动窗口错误率做决策**，不是总错误率 —— 总错误率会被历史健康数据稀释。
3. **回滚必须是开关级的**（feature flag）—— 需要重新发布的回滚，等它生效时已经烧完了。

---

### 把本章的手写件映射到真实部署

| 本章手写的 | 真实生产里的形态 |
|---|---|
| `FileCheckpointStore` | Redis（`SET run:{id} <json> EX 3600`）/ Postgres `agent_runs` 表 / S3 归档 |
| 同步 `submit()` | **队列 + Worker**：API 只入队并返回 `run_id`，Worker 池消费（Celery / SQS / Kafka） |
| 进程内 `OverloadGuard` | 网关限流（Nginx `limit_req`）+ 服务端并发信号量 + K8s HPA |
| `EventLog` | OpenTelemetry：`run_id` 当 trace_id，每一步是一个 span |
| `IdempotencyCache` | Redis `SETNX` + 数据库唯一索引（两层都要） |
| `CanaryRouter` | Feature Flag 服务 + Ingress 权重路由 + 指标驱动的自动回滚 |
| 幂等键 | HTTP `Idempotency-Key` 头（Stripe / 支付宝的开放 API 都有这个约定） |

**注意最关键的那一次转变**：HTTP 请求不再「跑完才返回」，而是「入队就返回」。

```
  POST /agent/tasks        ──► 入队（返回 202 + run_id）   ← 100ms 内返回，连接立刻释放
  GET  /agent/tasks/{id}   ──► 查状态与结果（长轮询 / SSE / WebSocket 推进度）
  POST /agent/tasks/{id}/resume ──► 手动续跑（补偿任务也调它）
```

于是「长任务 vs 短连接」这个矛盾的根本解法是 ——
**不要让 HTTP 连接去承载任务的生命周期。**""")

    # ==================================================================
    nb.md("---")

    pitfall_table(nb, [
        ("用「空值」表达「未设置」",
         "首次运行的起点本来就是空会话，判据在第一次就失效",
         "用独立的 bool 标记（`start_captured`）"),
        ("同一个语义字段有多个写入点",
         "崩溃处理顺手把「起点」覆盖成「跑了一半的状态」→ 恢复时用户消息追加两次 → 工具调用翻倍",
         "一个语义一个写入点；起点只写一次"),
        ("恢复时「接着中间状态写」",
         "崩溃可能停在「一步写了一半」，状态不自洽；且必须假设模型/工具幂等（它们不是）",
         "恢复 = 倒回起点 + 重放事实清单"),
        ("检查点非原子写",
         "崩溃时留下半截 JSON，「崩溃恢复」变成「崩溃 + 数据损坏」",
         "临时文件 → `fsync` → `os.replace`"),
        ("用「累计数字」表达状态",
         "中途死过再续跑，`steps_done` 极容易算重（1 → 3 → 6 → 10）",
         "存「事实清单」（做了哪几步的列表），天然幂等"),
        ("兜底 `except Exception` 吃掉中断信号",
         "崩溃/超时演练被翻译成普通错误，**看起来跑完了其实没崩**",
         "中断走 `BaseException` 通道（`SimulatedCrash` / `_BudgetSignal`）"),
        ("用 `request_id` 当幂等键",
         "客户端重试时几乎总会生成新的 ID → 幂等直接失效",
         "用 (user_id + 业务意图) 推导出的稳定键"),
        ("直接拿客户端给的 key 当全局缓存键",
         "另一个用户碰巧用了同名 key → 缓存命中 → 钱记到别人头上",
         "拼上 `user_id` + 业务意图，明确 key 的作用域"),
        ("用内置 `hash()` 算键",
         "带随机盐（PYTHONHASHSEED），跨进程不稳定 → 重启后幂等失效",
         "`hashlib.sha256`"),
        ("失败也写幂等缓存",
         "用户重试拿到**假成功**，比重复执行更糟 —— 而且他不会再来",
         "只有成功才 `put`；失败路径直接抛错"),
        ("第二次不返回 `replayed` 标记",
         "模型对用户说「已扣款两次」—— 副作用没错，**叙述错了**照样投诉",
         "工具把 `replayed` 透传给模型，幂等到用户体验那一层"),
        ("无限排队",
         "延迟不可控地涨，排队把「过载」变成了「必然超时」",
         "短队列 + 队列满就拒绝（429 + `Retry-After`）"),
        ("只在「跑完」时检查超时",
         "「已经超时了，却又发了一条通知」→ 外部世界变了，用户以为没发生",
         "钉在 `step_start` 与 `llm_output` 两个步骤边界"),
        ("`HALF_OPEN` 放一批探测请求",
         "下游还没恢复就被二次打死（熔断抖动）；忘了复位标志还会状态机卡死",
         "只放一个探测，且成功/失败两条路径都复位标志"),
        ("用 `time.sleep` 测超时",
         "测试慢、结果不确定、没法测「冷却结束后恢复」",
         "注入 `FakeClock`，手动 `advance()`"),
        ("用总错误率做灰度决策",
         "被上线前的健康历史稀释，等它超阈值时已经烧了一片",
         "滑动窗口错误率 + `min_samples` 护栏"),
        ("用 `random()` 分灰度桶",
         "用户刷新一下答案就变了；跨机器落点不同，比例变成一锅粥",
         "稳定哈希（`sha256(request_id) % 100`）"),
        ("检查点存本地磁盘",
         "Pod 是无状态的，下次调度可能落到另一台机器上，文件根本找不到",
         "存 Redis / Postgres / S3"),
    ])

    summary(nb, [
        "**核心矛盾：Agent 是有状态的长任务，HTTP 是无状态的短连接。**"
        "本章所有机制都在弥合这一个矛盾。",
        "**状态必须落在进程之外，而且写在步骤边界上。**"
        "「跑完再存」等于没存 —— 崩的那一刻恰恰是没跑完的时候。",
        "**原子写 = 临时文件 → `fsync` → `os.replace`。**"
        "少了它，「崩溃恢复」会退化成「崩溃 + 数据损坏」。",
        "**恢复 = 倒回起点 + 重放，不是接着中间状态写。**"
        "不倒回就会出现「用户消息两次 → 模型以为什么都没做 → 工具调用悄悄翻倍」——"
        "**静默的错误远比崩溃危险**。",
        "**幂等的落点在副作用那一层。** 键的作用域必须拼 `user_id + 业务意图`，"
        "算键用 `sha256`（跨进程稳定），失败绝不写缓存，`replayed` 必须透传给模型。",
        "**过载不是慢，是死。** 短队列 + 队列满快速拒绝，闸门放在调模型之前。",
        "**超时降级给三件套：半成品 + 明确说明 + 可续跑标记。**"
        "检查点钉在 `step_start` 与 `llm_output`（工具执行之前）——"
        "这样绝不会「超时了却又发了一条通知」。",
        "**熔断只放一个探测请求**，断了就别再打下游 ——"
        "它的价值是阻断故障扩散，不是让错误来得更快。",
        "**结构化日志的两个字段不可替代：`run_id` 和 `step`。**"
        "它们回答了生产事故的第一个问题：是哪一次运行的哪一步失败了。",
        "**灰度按稳定哈希分桶，回滚按滑动窗口错误率，并且回滚是开关级的。**"
        "Agent 的输出是概率性的，单测证明不了「它没变坏」，只有真实流量能。",
        "**能用确定性代码解决的，绝不用模型**（第 09 章那句）："
        "准入、去重、熔断、超时全是纯确定性代码，一个模型调用都不花。",
    ], """没有了 —— 第 13 章就是最后一章。下面是全课程收口。

```
 第一句（第 01 章）：
      Agent = 一个 while 循环 + 一个会调工具的模型 + 一个能记住历史的列表。

 第二句（第 02~12 章）：
      让它变聪明，靠的不是「更强的模型」，
      而是更好的工具描述、更清晰的提示词契约、更严格的校验、更完整的评估。

 第三句（第 13 章）：
      让它敢上线，靠的不是「更多的功能」，
      而是状态持久化、幂等、并发控制、超时熔断、灰度回滚
      —— 一句话：**在坏掉的时候也不出事。**
```

| 章 | 它对「生产化」的贡献 |
|---|---|
| 01 最小 Agent 循环 | `while` 循环 + 每一步的轨迹 —— 后来所有检查点的**写入时机**都基于它 |
| 02 工具系统 | 工具成了可校验、可注册的对象 —— 幂等键与权限才能挂在「工具」这个边界上 |
| 03 ReAct 提示工程 | 输出格式契约 —— 它让模型输出可解析，「步骤」才能被可靠计数 |
| 04 规划与任务分解 | 计划是假设、执行是验证 —— 续跑时「还剩哪几步」就来自这里 |
| 05 记忆与上下文 | 记忆分层与压缩 —— 检查点里该存什么、能丢什么，由它决定 |
| 06 RAG 检索增强 | 外部知识注入 —— 生产上它是独立服务，同样要熔断、要降级 |
| 07 反思与自我修正 | 失败经验库 —— 它就是「跨 run 的持久状态」，同样需要幂等写入 |
| 08 多智能体协作 | 角色分工与消息传递 —— 多 Agent 把「状态」变成了分布式问题 |
| 09 工作流与状态机 | 显式图 + 节点检查点 —— 本章的 `RunState` 直接沿用它的思想 |
| 10 评估与可观测性 | 评估集 + trace —— 离线管「改动前 vs 改动后」，在线灰度管真实流量 |
| 11 安全护栏 | 输入过滤 + 审批 + 审计 —— 人工审批必须**跨进程持久化**，否则重启即失效 |
| 12 成本与延迟 | 计量、缓存、路由 —— 成本指标要进看板，缓存命中率是容量规划的依据 |
| 13 **生产化部署** | **把前 12 章的全部机制，装进一个「坏了也不出事」的服务外壳里** |

> 成熟的工程不是「不会坏」，而是「坏了以后，用户几乎感觉不到，而你知道发生了什么」。
> 合上这门课之前，请再运行一次下面的自检 —— 那 40 项断言，就是这一章的全部验收标准。""")

    exercises(nb, [
        ("**把检查点换成内存版，观察「假崩溃」为什么没有复现真实故障。**\n\n"
         "把 ③ 里的 `save` / `load` 改成写一个普通 dict（不落盘），"
         "然后重跑整个实验。\n\n"
         "你会看到一个诡异的结果：**恢复居然成功了**。请回答：\n"
         "这个实验为什么没有复现真实故障？真实场景里丢掉的到底是什么？",
         "教学里的「假崩溃」只抛异常，**不销毁对象** —— 那个 dict 还在内存里。\n\n"
         "真实场景丢掉的是**进程本身**：`store`、`agent`、变量全都在那个进程里。\n"
         "想看真实效果，就在恢复前执行 `state.clear()`（或者干脆新建一个空 dict）——"
         "这时你会发现没有任何东西可以恢复。\n\n"
         "这正是 `InMemoryCheckpointStore` 的教训：它一秒都扛不住真实上线。"),

        ("**给幂等缓存加 TTL，并想清楚 TTL 该设多长。**\n\n"
         "1. 给 ④ 的账本加一个 `ttl_s` 参数和基于时钟的惰性过期（读的时候判断）；\n"
         "2. 用 `FakeClock` 写一个自检：**TTL 内命中缓存、TTL 外重新执行**；\n"
         "3. 回答：TTL 设长了会怎样？设短了又会怎样？",
         "惰性过期的写法：把 `stored_at` 一起存进账本，`get` 时判断 `clock() - stored_at > ttl_s`，"
         "过期就当成没有（顺手删掉）。\n\n"
         "设长了：用户第二天真的想再充一次，却被当成重复请求（业务被误伤）。\n"
         "设短了：网络重试在 TTL 之外到达，重复扣款又回来了。\n\n"
         "结论：**TTL 是按业务定的，不是按技术定的。**"
         "支付类通常 24 小时，点赞类可能 5 分钟。"),

        ("**破坏性实验：删掉恢复时的「倒回」，看工具调用怎么翻倍。**\n\n"
         "在 ③ 的恢复 B 里，把 `start=saved[\"start\"], facts=saved[\"facts\"]` 改成"
         "`start=saved[\"messages\"]`（也就是恢复 A 的写法）。\n\n"
         "观察三件事：用户消息几条？`WORLD` 里的副作用计数是多少？最终答案看起来对不对？\n\n"
         "**然后回答：本章所有的破坏性实验里，哪一处的「坏」最不容易被发现？**",
         "最终答案看起来是**对的**，检查点也在，日志也正常 ——"
         "只有工具调用计数悄悄翻倍。\n\n"
         "因为没有东西**崩溃**：用户拿到了正确的答复，监控上也看不到 error，"
         "只有对账的时候（钱、通知、审计记录）才会发现多了一笔。\n\n"
         "**静默的错误远比崩溃危险**：崩溃有人报警，翻倍没人发现。"
         "这也是为什么副作用计数（`tool_hits`）必须进检查点、必须被断言。"),

        ("**把并发闸门的参数改一遍，并回答一个设计问题。**\n\n"
         "把 ⑤ 的 `LIMIT` 从 5 改成 2，再改成 10，各跑一次，比较「峰值」「被拒绝」「新接入」三列。\n\n"
         "然后回答：为什么闸门必须放在**调模型之前**？"
         "如果放在「模型返回之后」再检查，会发生什么？",
         "`LIMIT` 越小，峰值越低、拒绝越多（保护更强、体验更差）；"
         "越大则相反 ——**这个值就是「容量规划」的那根线**，"
         "真实系统里由压测 + 模型端的限流配额共同决定。\n\n"
         "放在调模型之后检查，等于**连接已经占上了、模型调用已经发生了、钱已经花了**，"
         "你再拒绝只是「拒绝把结果给用户」—— 该占的资源一个都没省下。\n\n"
         "准入控制的价值在于「**在花钱之前**就挡住」。"),

        ("**给熔断器补上「半开只放一个探测」的保证性测试（本章代码已经实现，请自证）。**\n\n"
         "写一段代码证明：进入 `HALF_OPEN` 之后连续调用 5 次 `allow()`，"
         "**只有第 1 次返回 True**。\n\n"
         "再想一步：如果把 `probe_in_flight` 的复位删掉，会发生什么？"
         "为什么说这是熔断器最常见的实现 bug？",
         "用 `FakeClock` 推进到冷却结束（`clock.advance(30)`），"
         "然后连续 `allow()` 5 次，统计 `sum(...)` 应该等于 1。\n\n"
         "删掉复位 → 探测请求结束之后标志永远是 True，"
         "熔断器**永远卡在半开**：放不出探测、也就不可能恢复成 CLOSED，"
         "整个下游从此被永久熔断。\n\n"
         "这类「状态机卡死」比「状态机抖动」更危险：抖动有人投诉，卡死没人发现 ——"
         "直到某个下游恢复了，你的流量却再也没有回去。"),
    ])

    checkpoint(nb, "13")

    return nb
