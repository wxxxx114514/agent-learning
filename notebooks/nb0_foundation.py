"""第 00 章 · 从零理解：模型和代码之间到底传什么（Notebook 内容）。

------------------------------------------------------------
这一章是整个课程的地基。

为什么它必须排在所有章节前面
    读者最容易卡住的地方，不是「Agent 怎么写」，而是**根本不知道
    模型和程序之间怎么通信**：

        · 模型会执行我写的函数吗？
        · 它返回给我的到底是什么？一个对象？还是一段文字？
        · 所谓「工具调用」是谁在调用？

    这些不搞清楚，后面所有代码都是悬空的 —— 读者只能死记硬背语法。

本章遵守 notebooks/nb_lint.py 的自包含规矩：
    每个代码单元都能单独运行，不依赖前面的单元。

★ 写作约定（踩过坑）：代码单元里凡是需要中文引号的地方，
  一律用 「」，绝不在字符串内部再嵌 ASCII 双引号 —— 那会导致 SyntaxError。
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


def build_00() -> Notebook:
    """第 00 章 · 模型和代码之间传什么（自包含重写版）。"""
    nb = Notebook("第 00 章 · 模型和代码之间传什么")

    header(
        nb, "00", "模型和代码之间传什么",
        "模型和程序之间**只传文本**。\n"
        "所谓「让模型调用工具」，本质是：约定一套文本格式 + 写一个解析器 + 我们自己执行函数。",
    )

    objectives(nb, [
        "说清模型和你的程序之间**到底传了什么**（一条一条列出来）",
        "解释为什么模型**不能**执行你的函数，以及「工具调用」到底是谁在调用",
        "亲手写一个 20 行的最小闭环：发消息 → 收文本 → 解析 → 执行函数 → 再发回去",
        "看懂 `llm.complete(messages) -> LLMResponse` 这个接口，以及 `.text` 是什么",
        "知道本项目 `core/` 里有哪些现成的零件，各自负责什么",
    ])

    setup_cell(nb)

    nb.md("""---

## 读这一章之前，先丢开一个误解

很多人第一次接触 Agent 时，心里默认的模型是这样的：

```
   我的程序  ──[ 调用 ]──►  模型  ──[ 它自己去调用我的函数 ]──►  数据库/计算器
```

**这是错的。** 实际是这样的：

```
   我的程序  ──[ 一段文本 ]──►  模型
             ◄──[ 一段文本 ]──

   然后：我的程序自己看这段文本，自己决定要不要执行函数。
```

模型**从头到尾只做一件事**：看着你给的文本，续写下一段文本。

> 它没有手，不能执行任何东西；没有记忆，不记得上次说了什么；
> 也不能主动找你 —— 只有你问它，它才答。

这一章就是把这四句话讲透，并且让你**亲眼看到**。
""")

    # ==================================================================
    section(nb, "①", "先看最小的一步：我们发什么、收什么")

    nb.md("""### 要做什么

写一段程序，问模型一个问题，把它的回答打印出来。就这一件事。

### 需要什么功能

只有一个能力：**把一段文本发给模型，拿回一段文本。**

不需要工具、不需要循环、不需要记忆。先把这一件事搞明白。

### 用什么实现

**真实情况**：模型在别人的服务器上，要用 HTTP 请求调用它 —— 这需要 API Key、网络、还要处理各种错误。

**但我们现在只想理解「传什么」**，这些和网络无关。
所以我们自己写一个**假的模型**：它不做任何智能的事，只是按你给它的规则返回一段文本。

> 这个做法后面会一直用。原因不只是省钱：
> 真实的模型每次回答都不一样，你没法用它验证自己的代码逻辑对不对。
> 换成一个行为完全确定的假模型，才能做到同一个输入永远同一个输出。
""")

    nb.code('''# 单独可运行：最小的模型，看清它收什么、回什么
# ---- 先准备环境（每个单元自带这几行，保证能单独跑）----
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---- 本单元要用到的东西，逐个说明 ----
# core.llm.LLM          本项目的抽象基类：所有「模型」的父类
# core.llm.LLMResponse  本项目的类：装模型的一次回复
# core.message.Message  本项目的类：装一条消息
from core.llm import LLM, LLMResponse
from core.message import Message


class ToyLLM(LLM):
    """一个什么都不做的模型：无论你发什么，它都回同一句话。

    它只实现了一个方法 _complete(messages)：
        messages         —— 一个 Message 列表（我们发给它的历史）
        返回 LLMResponse —— 装着它的回复
    """

    def _complete(self, messages, **kwargs):
        # 它「看到」的输入就是这些消息。先打印出来，让你亲眼看到。
        print("  【模型收到】", len(messages), "条消息：")
        for m in messages:
            print(f"      role={m.role!r:12} content={m.content!r}")

        # 它的回复就是一段写死的文本
        return LLMResponse(text="你好，我收到了你的消息。")


# ---- 用它：构造消息 → 调用 → 看返回 ----
print("【我们发出】一条 user 消息")
reply = ToyLLM().complete([Message.user("你好")])
print()
print("【我们收到】一个对象，类型是：", type(reply).__name__)
print("    .text       =", repr(reply.text), "   <-- 模型说的话，就是这段文本")
print("    .model      =", repr(reply.model))
print("    .latency_ms =", reply.latency_ms, "毫秒（complete() 自动填的）")''')

    nb.md("""### 这个例子里，你需要记住三件事

**① 我们发过去的是一个 `Message` 列表**，不是一句话。

为什么要用列表？因为要带上历史（后面会看到）。每条 `Message` 有：

| 字段 | 类型 | 含义 |
|---|---|---|
| `.role` | str | 这条消息是谁说的：`'system'` / `'user'` / `'assistant'` / `'tool'` |
| `.content` | str | 消息正文 |
| `.tool_calls` | list | 这条 assistant 消息想调用的工具（暂时用不到，先知道有它） |

`Message` **不是任何库里的东西** —— 它是本项目 `core/message.py` 里我们自己定义的类。
它提供四个构造快捷方法：

```python
Message.system("你是助手")                    # 系统提示词：我是谁、有哪些工具、什么格式
Message.user("帮我算 1+1")                    # 用户说的话
Message.assistant("Thought: ...")             # 模型的回复（我们把它存回历史）
Message.tool_result("calc", "1+1 = 2")        # 工具返回的结果
```

**② 我们收回来的是一个对象 `LLMResponse`**，不是一个字符串。

| 字段 | 类型 | 含义 | 重要程度 |
|---|---|---|---|
| `.text` | str | **模型回复的正文** | ★★★ 你 90% 的时间只用这个 |
| `.model` | str | 模型名 | ★ |
| `.prompt_tokens` / `.completion_tokens` / `.total_tokens` | int | token 用量（算钱用） | ★★ |
| `.latency_ms` | float | 这次调用花了多久 | ★ |

想知道每个字段的完整说明，随时：

```python
explain(LLMResponse)
```

**③ 接口只有 `complete()` 一个方法**

```
   你调用       llm.complete(messages)
   子类实现     llm._complete(messages)
```

`complete()` 是框架写好的外壳，负责计时、统计 token、统一包装异常；
你写假模型时只需要实现 `_complete()`。真实模型也一样 ——
`core/real_llm.py` 里的 `OpenAICompatLLM._complete()` 就是发一个 HTTP 请求。

> **这就是不需要 API Key 也能学的原因**：Agent 内核只认 `complete()` 这个接口，
> 至于它背后是 HTTP 请求还是一句 `return`，内核不关心。""")

    # ==================================================================
    section(nb, "②", "关键问题：模型能执行我的函数吗？")

    nb.md("""### 不能。这是初学 Agent 最容易误解的一点。

下面这个例子把 Python 函数的说明**真的交给模型**，看它怎么回应。""")

    nb.code('''# 单独可运行：模型能执行函数吗？
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message

# 假设我们有这么一个函数，希望模型能用它
def add(a: int, b: int) -> int:
    """把两个整数相加。"""
    return a + b

print("我们把函数说明写进系统提示词，交给模型：")
print()
system_text = (
    "你可以使用下面的函数：\\n"
    "  add(a: integer, b: integer) -> integer   // 把两个整数相加\\n"
    "需要用它时，输出：\\n"
    '  <call>{"name": "add", "args": {"a": ..., "b": ...}}</call>'
)
print(system_text)
print()

class EchoToolLLM(LLM):
    """假模型：它看懂了要求，于是输出一段描述它想调用什么的文本。

    重点：它输出的只是一段文本，不是真的调用。
         函数 add() 从头到尾没有被执行过。
    """

    def _complete(self, messages, **kwargs):
        return LLMResponse(
            text='我需要计算，所以想调用 add。\\n'
                 '<call>{"name": "add", "args": {"a": 1, "b": 2}}</call>'
        )

reply = EchoToolLLM().complete([
    Message.system(system_text),
    Message.user("帮我算 1+2"),
])

print("模型返回的 .text 是：")
print("   ", reply.text.replace("\\n", "\\n    "))
print()
print("它只是一段文本。add() 有没有被执行？")
print("   add(1, 2) 的真实结果 =", add(1, 2), "  <-- 这是我们自己调用才有结果的")
print()
print("结论：")
print("   1. 模型不能执行任何函数 —— 它只会说出它想调什么")
print("   2. 真正执行函数的是我们的程序")
print("   3. 所以「工具调用」这个名字有误导性，准确说是：")
print("      模型输出一段特定格式的文本，我们的程序解析后自己执行")''')

    nb.md("""### 那「原生 Function Calling」又是什么？

你以后会看到 OpenAI / DeepSeek 等厂商提供 `tools` 参数和 `tool_calls` 字段，
看起来像是模型直接调用了函数。**本质没变**：

| 你以为发生的 | 实际发生的 |
|---|---|
| 模型执行了我的函数 | 模型输出了一段结构化文本，**厂商的服务器**帮你解析成了 JSON |
| 模型知道函数的结果 | 不知道。函数结果要你再发一次给它 |

厂商做的那层解析，好处是格式更可靠（不容易写崩），
但流程一字未变：**你发文本 → 它回文本 → 你执行 → 你再发**。

> 第 03 章会详细比较「纯文本协议」（我们自己写正则解析）和
> 「原生 Function Calling」（厂商帮我们解析）的取舍。
> 现在只需要记住：**两者本质相同，都是文本进、文本出。**

### 小结：模型和代码之间传的东西

```
   我们发过去 ────────────────────────────────► 模型
     · 系统提示词（Message.system）：我是谁、有哪些工具、要什么格式
     · 用户问题  （Message.user）  ：用户说了什么
     · 历史      （Message.assistant / Message.tool_result）
                                    ：之前它说过什么、工具返回过什么

   模型回给我们 ◄────────────────────────────────
     · LLMResponse.text：一段文本。
       可能是「我要调工具」（我们自己解析），
       也可能是「这是我的答案」（我们直接用）。
```""")

    # ==================================================================
    section(nb, "③", "把闭环接上：解析 → 执行 → 再发回去")

    nb.md("""### 要做什么

把前面的零件串成一个**能真正干活**的闭环。目标：让模型算出 `(12+8)*3/4`。

（模型自己算这种长表达式经常出错，所以我们要让它申请调用计算器，
由我们的代码去算 —— 这就是「工具」存在的意义。）

### 需要哪些功能

| # | 我需要一个能……的东西 | 对应实现 |
|---|---|---|
| 1 | 从模型输出的一段文本里，抠出它想调什么函数、参数是什么 | `re` 模块的正则 |
| 2 | 把抠出来的 JSON 文本变成 Python 字典 | `json.loads` |
| 3 | 真的执行那个函数 | 就是普通 Python 函数调用 |
| 4 | 把结果变成一条消息，追加到历史里 | `Message.tool_result` |
| 5 | 重复以上过程，直到它给出答案 | `while` 循环 |

### 用什么实现（逐个说明）

**功能 1 + 2：正则 + JSON**

```python
import re, json
CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>")
#          ^ re.compile(正则字符串) 返回一个 Pattern 对象
#            Pattern.search(文本) 返回 Match 对象；找不到返回 None（不报错）
#            Match.group(1) 拿到第 1 个括号里捕获的内容
```

`json.loads(字符串)` 把 JSON 文本变成 Python 字典；
如果文本不是合法 JSON 会抛 `JSONDecodeError`，所以要 `try` 包住。

**功能 5：`while` 循环**

这就是 Agent 的全部骨架。下一章会展开写，这里先用最朴素的形式。

### 数据结构：东西存哪

| 存什么 | 用什么结构 | 为什么 |
|---|---|---|
| 对话历史 | `list[Message]` | 要按顺序整段发过去，列表天然有序 |
| 工具表 | `dict[str, 函数]` | 要用名字查到函数 —— 这正是字典的用途 |
| 解析结果 | 元组 `(名字, 参数字典)` 或 `None` | 只有两种可能：解析出来了 / 没解析出来 |

### 联动：数据怎么流动

```
    messages: list[Message]      <-- 历史（Agent 的记忆）
            │
            │ ① 整段发过去
            ▼
      llm.complete(messages) ──► LLMResponse
            │                        │
            │                        ▼ .text 是一段文本
            │              '...<call>{"name":"calc","args":{...}}</call>'
            │                        │
            │                        ▼ ② 用正则解析
            │                 Match.group(1) = '{"name":...}'
            │                        │
            │                        ▼ ③ json.loads
            │                 {"name": "calc", "args": {...}}
            │                        │
            │                        ▼ ④ 查工具表并执行
            │                 TOOLS["calc"](expr="(12+8)*3/4") = "= 15"
            │                        │
            │                        ▼ ⑤ 包装成一条消息
            └──── messages.append(Message.tool_result("calc", "= 15"))
                                     │
                                     └─► 回到 ①，再来一圈
```

### 完整代码（下面这一整格可以直接单独运行）""")

    nb.code('''# 单独可运行：接上完整闭环，让模型算出 (12+8)*3/4
import sys, pathlib, re, json, ast
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message

# ---------- 零件 1：一个真的能算数的工具（普通 Python 函数，没有魔法）----------
def calc(expr: str) -> str:
    """计算数学表达式。

    参数 expr：表达式字符串，例如 (12+8)*3/4
    返回    ：结果字符串，例如 (12+8)*3/4 = 15
    """
    # 用 ast 而不是 eval：expr 来自模型输出，是不可信输入。
    # ast.parse 只把字符串解析成语法树（一个数据结构），不执行任何东西。
    BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}

    def ev(node):
        if isinstance(node, ast.Expression):          # 顶层容器
            return ev(node.body)
        if isinstance(node, ast.Constant):            # 数字字面量
            return node.value
        if isinstance(node, ast.BinOp):               # 二元运算 a+b
            return BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp):             # 一元运算 -a
            return -ev(node.operand)
        raise ValueError(f"不支持的语法: {type(node).__name__}")

    value = ev(ast.parse(expr, mode="eval"))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{expr} = {value}"


# ---------- 零件 2：工具表（名字 -> 函数）----------
TOOLS = {"calc": calc}


# ---------- 零件 3：解析器（文本 -> 结构）----------
CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>", re.S)
# re.S 让 . 也能匹配换行符；模型输出常常跨行，不加就匹配不到

def parse_tool_call(text: str):
    """从模型输出里抠出工具调用。

    参数 text：模型的原始输出（一整段字符串）
    返回    ：(工具名, 参数字典)；解析不出来时返回 None
    """
    m = CALL_RE.search(text)          # 返回 Match 或 None
    if not m:
        return None                   # 找不到要判空，否则 .group() 会报错
    try:
        obj = json.loads(m.group(1))  # 第 1 个括号里的 JSON 文本 -> 字典
    except json.JSONDecodeError:
        return None                   # 模型把 JSON 写坏了
    return obj.get("name"), obj.get("args", {})


# ---------- 零件 4：一个会申请调工具的假模型 ----------
class CalcLLM(LLM):
    """两拍假模型：第一拍申请调 calc，第二拍看到结果后给出答案。"""

    def _complete(self, messages, **kwargs):
        # 判断依据：这一轮里有没有出现过 tool 角色的消息
        has_tool_result = any(m.role == "tool" for m in messages)
        if not has_tool_result:
            return LLMResponse(          # 第一拍：申请调用工具
                text='我需要计算，申请调用 calc。\\n'
                     '<call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</call>'
            )
        last = [m for m in messages if m.role == "tool"][-1]
        return LLMResponse(text=f"Final Answer: 算出来是 {last.content}")   # 第二拍：给答案


# ---------- 零件 5：把上面串成闭环 ----------
SYSTEM = (
    "你可以调用这些工具：" + ", ".join(TOOLS) + "\\n"
    '需要工具时输出：<call>{"name": "工具名", "args": {...}}</call>\\n'
    "可以回答时输出：Final Answer: ..."
)

messages = [Message.system(SYSTEM), Message.user("帮我算 (12+8)*3/4")]
llm = CalcLLM()

for round_no in range(1, 6):                       # ⑤ 循环，最多 5 圈
    print(f"=== 第 {round_no} 圈 ===")
    print(f"  发给模型的历史：{len(messages)} 条消息")

    reply = llm.complete(messages).text             # ① 发过去，收文本
    print(f"  模型输出：{reply.splitlines()[0][:52]}")

    if "Final Answer:" in reply:                    # 它答完了
        print()
        print("最终答案：", reply.split("Final Answer:")[1].strip())
        break

    call = parse_tool_call(reply)                   # ② 解析
    if call is None:
        print("  （没解析出工具调用，这轮跳过）")
        continue

    name, args = call                               # ③ 查表 + 执行
    print(f"  解析出：调用 {name}，参数 {args}")
    result = TOOLS[name](**args)
    print(f"  我们执行它，得到：{result}")

    messages.append(Message.assistant(reply))       # ④ 把它的输出存进历史
    messages.append(Message.tool_result(name, result))   # ⑤ 把结果也存进去
    print(f"  -> 历史变成 {len(messages)} 条，回到开头")''')

    nb.md("""### 你刚刚亲眼看到的事

| 你看到的 | 含义 |
|---|---|
| 模型输出 `<call>{...}</call>` | 它只是在**说**它想调用什么，用我们约定的格式 |
| `TOOLS[name](**args)` 是我们执行的 | **执行权在我们手里**，不在模型手里 |
| 结果被 `Message.tool_result` 包装后追加 | 模型下次看到结果，靠的就是这条新消息 |
| 循环的终止条件是 `Final Answer:` | 这是我们在提示词里和它约定的「我答完了」信号 |

**这一章讲的所有东西，13 章再也不会变**：

```
    发：Message 列表（系统提示词 + 历史）
    收：LLMResponse，重点是 .text
    然后：我们解析、我们执行、我们追加、再来一圈
```

后面 12 章都在解决这个朴素闭环在真实世界里会遇到什么麻烦：
模型输出格式崩了怎么办（03）、参数是恶意输入怎么办（02）、
历史太长怎么办（05）、一次任务要几十圈怎么办（04）……
""")

    # ==================================================================
    section(nb, "④", "本项目的零件清单：core/ 里都有什么")

    nb.md("""现在你已经理解了原理，可以看看本项目提供了哪些现成零件。
**这些不是 pip 包，是本仓库 `core/` 文件夹里的代码** —— 你可以直接打开读。

| 层 | 名字 | 从哪 import | 负责什么 |
|---|---|---|---|
| **模型** | `LLM` | `core.llm` | 抽象基类。子类实现 `_complete(messages) -> LLMResponse` |
| | `LLMResponse` | `core.llm` | 一次回复：`.text` 最重要 |
| | `ScriptedLLM` | `core.mock_llm` | 按剧本念台词的假模型（本章用的那种） |
| | `RuleBasedLLM` | `core.mock_llm` | 默认假模型：真的会规划多步工具调用 |
| | `OpenAICompatLLM` | `core.real_llm` | 真实模型（HTTP，需要 API Key） |
| **消息** | `Message` | `core.message` | 一条消息（`.role` / `.content`） |
| | `ToolCall` | `core.message` | 一次工具调用请求（`.name` / `.args`） |
| | `Conversation` | `core.message` | 消息列表的薄封装 |
| **工具** | `ToolRegistry` | `core.tool` | 工具注册表：注册、校验参数、安全执行 |
| | `ToolSpec` | `core.tool` | 工具的说明书 |
| | `build_default_registry` | `core.tool` | 造一套内置工具（calc / count_words / 订单查询…） |
| **提示词** | `PromptBuilder` | `core.prompts` | 拼系统提示词（ReAct 格式） |
| **解析** | `parse_output` | `core.parser` | 从模型文本解析出工具调用（比本章的正则强得多） |
| **Agent** | `Agent` | `core`（顶层） | 框架版完整 Agent（第 01 章会拆开讲） |

**查询工具**：记不住这些没关系，随时敲

```python
explain()               # 列出全部（按层分组）
explain(LLMResponse)    # 查一个类的字段
explain(count_words)    # 查一个工具怎么用
```""")

    nb.code('''# 单独可运行：看看 core 里到底有哪些东西
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import core
print("core 暴露给我们的全部名字（", len(core.__all__), "个）：")
print()
for name in sorted(core.__all__):
    print("   ", name)''')

    nb.code('''# 单独可运行：core/ 文件夹里有哪些文件（这些就是零件的源码）
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent

print("core/ 目录：")
for f in sorted((ROOT / "core").glob("*.py")):
    n = len(f.read_text(encoding="utf-8").splitlines())
    print(f"   {f.name:<16} {n:>4} 行")
print()
print("建议：等第 01 章学完，回来挑一个文件读一遍 ——")
print("      你会发现它比你想象的简单，而且注释里写了为什么这么设计。")''')

    # ==================================================================
    section(nb, "⑤", "接真实模型（可选）")

    nb.md("""本章一直用假模型。想试试真的，需要两样东西：

1. **一个 API Key**（DeepSeek / OpenAI / 通义千问 等任选）；
2. **网络**。

设置方式（PowerShell）：

```powershell
$env:DEEPSEEK_API_KEY = "sk-xxx"
```

然后 `core.real_llm.get_llm(prefer_real=True)` 就会返回真实模型的适配器；
**没有配 Key 时会自动回退到假模型并告诉你原因**。

> **建议：先用假模型把 13 章学完，再用真实模型跑一遍做对照。**
> 反过来做的话，你会把大量时间花在调不通上（超时、限流、格式不对），
> 而不是学不会上。

为什么假模型能替代真模型来学原理？因为按本章讲的：
**模型对外的接口只有一个 `complete(messages) -> LLMResponse`**。
内核只依赖这个接口，背后是 HTTP 还是一句 `return`，它不关心。""")

    nb.code('''# 单独可运行：看看当前环境有没有配 Key
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.real_llm import get_llm

llm, desc = get_llm(prefer_real=False)   # 改成 True 就会尝试真实模型
print("当前使用：", desc)
print("模型类型：", type(llm).__name__)
print()
print("支持的厂商（设好环境变量即可）：")
print("   DEEPSEEK_API_KEY / OPENAI_API_KEY / MOONSHOT_API_KEY")
print("   DASHSCOPE_API_KEY / ZHIPU_API_KEY / SILICONFLOW_API_KEY")
print("   或自定义 *_BASE_URL（含 Ollama 本地服务）")''')

    # ==================================================================
    section(nb, "⑥", "收口")

    nb.md("""### 一句话本质

> **模型和程序之间只传文本。**
> 所谓让模型调用工具，本质是三件事：
> **约定一套文本格式 + 写一个解析器 + 我们自己执行函数。**

### 这一章建立的四个认知

1. **模型只会续写文本。** 它不能执行任何东西、没有记忆、不能主动找你。
2. **接口只有一个**：`llm.complete(messages) -> LLMResponse`，你几乎只用 `.text`。
3. **执行权在你的程序手里。** 模型说想调用 calc，真正调用的是你。
4. **记忆是你自己维护的 `messages` 列表**，每圈整段重发 —— 这就是第 05 章的主题。

### 一个可以立刻做的观察

本章的闭环里，每次循环都把**完整的 `messages`** 发给了模型。
你可以在第 ③ 节的代码里加一行打印，看看历史是怎么一圈圈变长的：

```python
print(f"  历史 {len(messages)} 条，共 {sum(len(m.content) for m in messages)} 字符")
```

看到它每圈都在涨，你就理解了为什么后面需要上下文工程（第 05 章）
和成本优化（第 12 章）。""")

    pitfall_table(nb, [
        ("以为模型会执行我的函数", "写出「模型帮我调了数据库」这种错误设计",
         "模型只输出文本，执行权在自己手里"),
        ("以为 `.complete()` 返回字符串", "对返回值做字符串操作，报 AttributeError",
         "返回的是 `LLMResponse` 对象，文本在 `.text` 里"),
        ("`re.search` 结果不判空", "没匹配上返回 `None`，`.group()` 抛 AttributeError",
         "先 `if not m: return None`"),
        ("用 `eval` 执行模型给的表达式", "提示词注入可执行任意代码",
         "`ast` 白名单（本章 `calc` 的写法）"),
        ("忘了加 `re.S`", "跨行的模型输出匹配不到", "Agent 场景几乎必加"),
        ("`json.loads` 不用 try 包住", "模型把 JSON 写坏时整个程序崩掉",
         "`try/except json.JSONDecodeError`"),
    ])

    summary(nb, [
        "**模型和程序之间只传文本** —— 发 `Message` 列表，收 `LLMResponse`。",
        "**模型不能执行任何东西。** 工具是你的程序执行的，它只负责说想调什么。",
        "**接口只有一个**：`llm.complete(messages)`，重点看返回的 `.text`。",
        "**Agent 的骨架接下来不会变**：发历史 → 收文本 → 解析 → 执行 → 追加 → 再来一圈。",
        "**`core/` 是本仓库的代码，不是 pip 包。** `import core` 能成功只因为项目根在 `sys.path` 里。",
    ], "第 01 章会把这个朴素闭环写成正式的 `MiniAgent` 类，"
       "并讲清四道停机保护（为什么 `max_steps` 是必需品）。")

    exercises(nb, [
        ("**让 `CalcLLM` 一次申请两个工具调用。**\n\n"
         "现在的解析器只处理一个 `<call>`。改成用 `CALL_RE.findall(text)` 找出全部调用，"
         "逐个执行，并把每个结果都追加成一条 `tool_result` 消息。\n\n"
         "验证：让模型一次申请算两个表达式。",
         "`findall` 返回的是**字符串列表**（每个括号捕获的内容），不是 Match 对象。\n"
         "每个结果都要 `messages.append(Message.tool_result(name, result))`。"),

        ("**故意把 JSON 写坏，看程序怎么反应。**\n\n"
         "把 `CalcLLM` 的输出改成 `1+1` 不加引号的非法 JSON。\n\n"
         "观察：`json.loads` 抛什么异常？`parse_tool_call` 返回什么？循环还能继续吗？",
         "会抛 `json.JSONDecodeError`，被 `except` 接住后返回 `None`，"
         "循环打印没解析出工具调用然后继续下一圈。\n\n"
         "**但这暴露一个问题**：模型永远写不对，循环就永远空转 —— "
         "这正是第 03 章要解决的（解析失败要回灌纠错，且要有重试上限）。"),

        ("**加一条总耗时保护。**\n\n"
         "在循环里记录开始时间，如果超过 0.5 秒就停机，并说明因超时未完成。",
         "`import time`，循环前 `t0 = time.perf_counter()`，"
         "每圈检查 `time.perf_counter() - t0 > 0.5`。\n\n"
         "这是生产系统的基本要求：宁可给部分结果 + 说明，也不能无限等。"),

        ("**去掉 `Final Answer:` 的判断，观察后果。**\n\n"
         "把判断 `Final Answer:` 的那一段删掉，改成永远尝试解析工具调用。\n\n"
         "跑一次，看它会不会停下来。",
         "会一直跑到 `range(1, 6)` 的上限 —— 这就是 `max_steps` 的作用。\n\n"
         "**这个实验的目的**：让你对没有终止条件这件事有体感。"
         "第 01 章会详细讲四道停机保护。"),
    ])

    checkpoint(nb, "00")

    return nb
