# 第 01 章 · 最小 Agent 循环

<!-- 材料定位 -->
> ## 📖 这份文档是**复习手册**，不是第一次学习用的
>
> 同一章有三种材料，**内容一致，用途不同**：
>
> | 材料 | 位置 | 什么时候用 |
> |---|---|---|
> | **① 交互式 Notebook** | `notebooks/01_agent_loop.ipynb` | **第一次学** —— 一步步推导，每个代码单元都能单独运行 |
> | **② 本文件** | `stages/stage01_agent_loop/README.md` | **复习 / 查阅** —— 结构化的原理与工程要点，方便搜索和跳读 |
> | **③ 命令行 demo** | `py -m stages.stage01_agent_loop.demo` | **看完整输出** —— 或者用 `-s N` 只看某一节 |
>
> **建议路径**：先用 ① 学一遍（能看到每一步的真实输出），
> 之后忘了什么回来查 ②，想快速跑一遍用 ③。
>
> 学完的验收命令：`py scripts\run_all_checks.py 01`

---

> **一句话本质**：
> **Agent = 一个 while 循环 + 一个会调工具的模型 + 一个能记住历史的列表。**
>
> 循环的每一圈只做四件事：**想（LLM）→ 做（Tool）→ 看（Observation）→ 记（History）**。
>
> 把这句话讲清楚，你就已经掌握 Agent 开发 80% 的骨架了；
> 剩下 12 章，都在解决这个骨架在真实世界里会遇到的具体麻烦。

---

## 0. 先看问题

最朴素的"AI 功能"是这样写的：把用户问题发给模型，把回答返回给用户。一次调用，一次回答。

```
用户提问              : 帮我算一下 (12+8)*3/4，然后告诉我订单 A1001 到哪了
模型回答              : 抱歉，我无法进行计算，也无法查询订单信息。
```

模型没有**手**（不能算数）、没有**眼**（看不到你的订单系统）。只靠一次调用，
它只能"凭记忆瞎猜"——而它猜错的概率，在算术和事实类问题上是不可接受的。

更糟的是：猜错了你**无从校验**。它给出的数字看起来很自信，但你不知道它是算出来的还是编出来的。

**突破口**：给模型一个循环，让它能反复"试着做 → 看结果 → 再做"。
这就是 Agent 和"一次问答"的全部差别。

---

## 1. 原理

### 1.1 Agent 循环的形状

```
                 ┌──────────────────────────────────────┐
                 │            messages 列表              │
                 │  （这就是 Agent 的"记忆"）             │
                 └──────────────────────────────────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    ▼                           │
            ┌───────────────┐                   │
            │  ① 想 (LLM)   │  把整个历史发给模型，  │
            │               │  让它写下一段         │
            └───────┬───────┘                   │
                    │                           │
         ┌──────────┴──────────┐                │
         ▼                     ▼                │
  ┌─────────────┐      ┌─────────────┐          │
  │ 给出答案？   │      │ 要调工具？   │          │
  │ Final Answer│      │ Action      │          │
  └──────┬──────┘      └──────┬──────┘          │
         │                    ▼                 │
         │            ┌───────────────┐         │
         │            │  ② 做 (Tool)  │         │
         │            └───────┬───────┘         │
         │                    ▼                 │
         │            ┌───────────────┐         │
         │            │ ③ 看 (Observe)│         │
         │            └───────┬───────┘         │
         │                    ▼                 │
         │            ┌───────────────┐         │
         │            │  ④ 记 (Append)├─────────┘
         │            └───────────────┘
         ▼
     返回答案
```

### 1.2 "记忆"的真相：它根本不存在

这是本章最重要的认知，也是最容易被误解的一点：

> **Agent 没有记忆。它只是每次把整段历史重新发给模型。**

运行第 4 节可以看到：

```
  第 1 次调用           : 2 条消息 / 197 字符
        [system   ] 你可以调用工具。需要工具时输出： Thought: ... Action: 工具名(参数)…
        [user     ] 计算 6*7

  第 2 次调用           : 4 条消息 / 341 字符
        [system   ] 你可以调用工具。…
        [user     ] 计算 6*7
        [assistant] Thought: 需要算一下。 Action: calc(expr="6*7") <tool_call>{"name…
        [tool     ] <result tool="calc"> 6*7 = 42 </result>
```

理解这一点，后面两章的动机就自然浮现了：

| 现象 | 后果 | 在哪一章解决 |
|---|---|---|
| 历史无限增长 | 上下文窗口会爆 | 第 05 章 记忆与上下文工程 |
| 每次都重发全部历史 | token 成本呈平方级增长 | 第 12 章 成本与延迟优化 |

### 1.3 为什么 `max_steps` 是必需品

看看没有它会怎样。第 5 节用 `AlwaysToolLLM`（永远请求调用同一个工具）模拟"模型卡住"：

```
  死循环实验 · 圈数        : 3
  死循环实验 · 停机原因      : max_steps
  ✅ max_steps 生效：模型卡住时，我们只损失 3 次调用，而不是无限次。
```

`max_steps` 是**唯一能兜住"模型犯傻"的机制**。没有它，一个提示词的 bug
就能让你烧掉一整天的 API 额度（真事，不是危言耸听）。

### 1.4 四道保险：Agent 为什么会停下来

| 停机原因 | 触发条件 | 性质 |
|---|---|---|
| `final_answer` | 模型给出了 `Final Answer` | ✅ 正常结束 |
| `max_steps` | 步数用完 | 🛡 保护 |
| `loop_detected` | 同样的动作反复出现 | 🛡 保护 |
| `parse_failed` | 模型输出连续无法解析 | 🛡 保护 |
| `error` | LLM 调用连续失败 | ❌ 故障 |

**新手只关心第一种。老手知道后四种才是能不能上线的分水岭。**

### 1.5 工具失败要变成"观察结果"，不是异常

这是第 01 章就要建立的第二个关键设计：

```
❌ 抛异常：
   calc(...) → TypeError → Agent 循环崩溃 → 用户看到 500

✅ 转成结构化 observation：
   calc(...) → "错误：参数不对。工具 calc 需要参数：['expr']"
             → 回灌给模型 → 模型改对参数 → 任务继续
```

理由：Agent 是"永不放弃"的系统。工具失败只是一次不成功的尝试，
应该给模型机会自救（换工具、改参数、或者如实告诉用户）。

---

## 2. 动手实现

本章刻意**不用** `core/agent.py`，而是从零手写一个 `MiniAgent`。
因为你要先看懂循环本身，再看框架在它之上加了什么。

### 2.1 主循环（这才是 Agent 的本质，约 30 行）

```python
def run(self, question: str) -> tuple[str, list[Step], str]:
    # ① 历史列表 —— 这就是 Agent 的"记忆"，也是它唯一的上下文
    messages: list[Message] = [
        Message.system("...格式契约 + 工具说明..."),
        Message.user(question),
    ]
    steps: list[Step] = []

    # ② 主循环：想 → 做 → 看 → 记，一圈一圈直到给出答案
    for i in range(1, self.max_steps + 1):
        step = Step(index=i)
        steps.append(step)

        # --- 想：把历史交给模型，让它写下一段 ---
        reply = self.llm.complete(messages).text
        step.thought = _extract_thought(reply)

        # --- 它是想回答问题，还是想调工具？ ---
        answer_match = FINAL_RE.search(reply)
        call = _extract_tool_call(reply)

        if answer_match and not call:
            step.answer = answer_match.group(1).strip()
            messages.append(Message.assistant(reply))
            stop_reason = "final_answer"
            break

        if not call:
            # 既没答案也没动作 → 把错误回灌，让它重写
            messages.append(Message.assistant(reply))
            messages.append(Message.user("你的输出无法解析。请严格用 ... 格式。"))
            continue

        # --- 做：真正执行工具（这是模型做不到的事） ---
        name, args = call
        messages.append(Message.assistant(reply))
        step.observation = self._execute(name, args)

        # --- 看 + 记：结果进入历史 ---
        messages.append(Message.tool_result(name, step.observation))
    return _last_answer(steps), steps, stop_reason
```

注意这里**没有**任何"思考框架"、"链式推理引擎"之类的复杂东西。
骨架就这么简单。后面 12 章加的，全是工程细节。

### 2.2 安全执行工具（任何失败都不抛异常）

```python
def _execute(self, name: str, args: dict) -> str:
    if name not in self.tools:
        return (f"错误：工具 {name!r} 不存在。"
                f"可用工具：{list(self.tools)}。请换一个工具，或直接给出 Final Answer。")
    try:
        # ★ 注意 **args：模型给的是参数字典，工具是普通 Python 函数
        result = self.tools[name](**args)
        return f'<result tool="{name}">\n{result}\n</result>'
    except TypeError as exc:
        return f"错误：参数不对（{exc}）。工具 {name} 需要参数：{_tool_params(...)}"
    except Exception as exc:
        return f"错误：{type(exc).__name__}: {exc}"
```

**`**args` 这个展开是最容易写错的地方。** 新手常写成 `self.tools[name](args)`，
那样 `expr` 收到的是整个字典，工具会在内部莫名报错，而且报错信息看不出真正原因。

### 2.3 极简解析

```python
TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)
FINAL_RE = re.compile(r"Final Answer\s*[:：]\s*(.*)", re.S)
```

只认 `<tool_call>{...}</tool_call>`。**故意做得笨**——
第 03 章你会看到工业级解析器要处理多少种畸形输出。

---

## 3. 跑起来

```powershell
py -m stages.stage01_agent_loop.demo             # 全部小节 + 自检
py -m stages.stage01_agent_loop.demo --list      # 列出小节
py -m stages.stage01_agent_loop.demo -s 2        # 只看主循环那次运行
py -m stages.stage01_agent_loop.demo --check     # 只跑自检
```

### 第 3 节：真跑一次，观察每一圈

```
  ┌─ 第 1 圈 ────────────────────────────────────────
  │ 💭 想 : 先解决算术部分。
  │ 🔧 做 : calc(expr='(12+8)*3/4')
  │ 👁  看 : (12+8)*3/4 = 15
  └────────────────────────────────────────────────

  ┌─ 第 2 圈 ────────────────────────────────────────
  │ 💭 想 : 算术完成，现在查订单。
  │ 🔧 做 : lookup_order(order_id='A1001')
  │ 👁  看 : 订单 A1001：已发货，顺丰 SF1234567890，预计 2025-01-05 送达
  └────────────────────────────────────────────────

  ┌─ 第 3 圈 ────────────────────────────────────────
  │ 💭 想 : 两个信息都有了，可以回答了。
  │ ✅ 答 : (12+8)*3/4 = 15；订单 A1001 已发货，顺丰 SF1234567890，预计 2025-01-05 送达。
  └────────────────────────────────────────────────

  最终答案              : (12+8)*3/4 = 15；订单 A1001 已发货…
  循环圈数              : 3
  停机原因              : final_answer
```

**这就是 Agent 最核心的一幕**：一个它单独做不到的任务，被拆成"算数"和"查订单"
两次工具调用，然后组合成一个完整答案。

### 第 5 节：四道保险

```
  死循环实验 · 圈数        : 3
  死循环实验 · 停机原因      : max_steps
  ✅ max_steps 生效：模型卡住时，我们只损失 3 次调用，而不是无限次。

  格式崩坏实验 · 圈数       : 4
  格式崩坏实验 · 停机原因     : max_steps
  ℹ️  模型不会写协议 → 每圈都白跑 → max_steps 兜底停机。
```

### 自检结果

```
py -m stages.stage01_agent_loop.demo --check
  ✅ 全部通过（13 项）
```

---

## 4. 工程要点

### 4.1 手写版 vs 框架版：框架多做了什么

`core/agent.py` 和我们手写的 `MiniAgent` 结构**完全一样**，只是多了这些工程能力：

| # | 能力 | 为什么必须有 |
|---|---|---|
| 1 | 解析器容忍 5 种畸形格式 | 真实模型输出很脏 |
| 2 | 解析失败有预算（`max_parse_retries`） | 否则模型写不对时无限烧钱 |
| 3 | LLM 调用带重试（指数退避） | 网络抖动不该让整轮任务失败 |
| 4 | 重复动作检测 | 发现复读主动提醒模型，而不是干等 |
| 5 | 上下文保护（超长历史折叠） | 防止撑爆上下文窗口 |
| 6 | 完整 `StepRecord` 轨迹 | 出错时你唯一能依赖的东西 |
| 7 | 工具审批钩子 | 高危操作先问人（第 11 章） |
| 8 | 事件回调 `observer` | 接日志/监控/UI 的入口 |

**框架的价值在于这些工程细节，不在于"循环"本身。** 学会循环，剩下的都是可查的。

### 4.2 轨迹（trace）：第一天就要做

`core/agent.py` 的 `AgentResult.trace()` 输出：

```
[第 1 步]  (llm 0ms / tool 0ms / 814 tok)
  💭 Thought: 我需要用 calc 工具来获取信息，参数已经准备好。
  🔧 Action : calc({"expr": "(12+8)*3/4"})
  👁  Obs    : <result tool="calc">  …(+2 行)
[第 2 步]  (llm 0ms / tool 0ms / 847 tok)
  💭 Thought: calc 返回了结果，我可以据此回答了。
  ✅ Answer : 根据 calc 的结果：(12+8)*3/4 = 15
```

**为什么第一天就要做？** 因为 Agent 出错时，你唯一能依赖的就是"它到底经历了什么"。
没有 trace 的 Agent 就是黑盒，调试等于猜谜。这也是第 10 章评估体系的基础设施。

### 4.3 常见坑

| 坑 | 症状 | 解法 |
|---|---|---|
| 没有 `max_steps` | 一个 bug 烧掉一天额度 | 永远设上限，默认 6~10 |
| 工具异常向上抛 | 整轮任务崩溃 | 兜底 `except` → 结构化 observation |
| 工具调用忘了 `**args` | 工具内部莫名报错 | 参数字典要展开 |
| 每圈都重建 messages | 历史丢失，模型反复问同样的问题 | 历史列表在循环外创建 |
| 只看最终答案 | 出错了不知道错在哪一步 | 记录每一步的 StepRecord |
| 把工具结果原样塞回去 | 一次长结果撑爆上下文 | 结果截断（第 02 章） |
| 死循环不检测 | 模型复读时白烧钱 | 动作指纹去重（框架版有） |
| 单一模型写死 | 换模型要改一堆代码 | LLM 抽象层（依赖倒置） |

### 4.4 为什么内核不能依赖厂商 SDK

`core/llm.py` 把模型抽象成一个方法：**把消息列表变成一段文本**。

```python
class LLM:
    def complete(self, messages: Sequence[Message], **kwargs) -> LLMResponse:
        ...
    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        raise NotImplementedError      # 子类只实现这个
```

收益：

1. 学习时用 Mock 模型离线跑 —— 不烧钱、不联网、**结果可复现**；
2. 换模型（GPT / Claude / DeepSeek / 本地模型）不改 Agent 代码；
3. 测试时注入"故意犯错"的假模型，专门验证错误处理路径。

这是软件工程的**依赖倒置原则**在 Agent 开发中的第一次应用。

---

## 5. 练习

1. **给 MiniAgent 加"重复动作检测"**：记录每次工具调用的指纹（`name + args` 的 JSON），
   同一个指纹出现超过 2 次时，往历史里插入一条提醒：
   "你已经重复调用 X 三次了，请换个方法或直接给出 Final Answer。"
   *提示*：参考 `core/agent.py` 的 `_call_history` 和 `repeat_limit`。

2. **把 `max_steps` 去掉，观察后果**：注释掉 `for i in range(1, self.max_steps + 1)`
   的上限，改成 `while True`，用 `AlwaysToolLLM` 跑一次。
   **记得设个计时器或准备好 `Ctrl+C`。** 这个实验的目的是让你对"没有护栏"有体感。

3. **加一个"总耗时"护栏**：除了限制步数，再限制整轮任务的总耗时（比如 5 秒）。
   超时后停机，并在答案里说明"因超时未能完成，已完成的部分是……"。
   *提示*：在循环里检查 `time.perf_counter() - t0`。这是第 13 章"超时降级"的雏形。

4. **让 Agent 支持多轮对话**：现在的 `run()` 每次都重置 `messages`（`reset=True`）。
   改成保留历史，让用户可以接着上一轮继续问。然后观察：
   第二轮时模型看到了多少条消息？这会在什么情况下出问题？

5. **注入一个会撒谎的模型**：写一个 `LyingLLM`，让它**不调用工具**，直接编一个
   订单状态返回。观察 Agent 会不会发现。然后修改系统提示词，加入
   "订单状态必须来自 lookup_order 的真实返回，禁止编造"，看能否拦住它。
   *提示*：这是第 11 章"幻觉防护"和第 07 章"反思"的引子。

---

## 6. 验收标准

- [x] 能跑通"计算 (12+8)*3/4"，`stop_reason == "final_answer"`
- [x] 能说出 4 种停机原因（final_answer / max_steps / loop_detected / parse_failed）
- [x] 能解释：为什么 `max_steps` 不是"可选项"而是"必需品"
- [x] 能画出消息列表在一次 run 中如何增长

```powershell
py scripts\run_all_checks.py 01      # → 0 failures
```

---

**下一章**：[第 02 章 工具系统与 JSON Schema](../stage02_tools/README.md) —— 循环跑通了，
但我们调工具的方式（`self.tools[name](**args)`）有三个致命的坑。下一章逐个拆掉。
