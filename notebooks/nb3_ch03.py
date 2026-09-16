"""第 03 章 · ReAct 提示工程 —— Notebook 内容（逐步推进版）。

遵守 TEACHING_CONTRACT.md：
  · 逐步给：每个知识点在"读者正好需要"时出现
  · 前置知识表保留在 ⓪，定位是索引（可跳过）
  · 每个代码单元自包含（nb_lint 机器校验）
  · 高注释密度：几乎每行代码都有中文说明，讲"为什么"
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


def build_03() -> Notebook:
    """第 03 章 · ReAct 提示工程（逐步推进版）。"""
    nb = Notebook("第 03 章 · ReAct 提示工程")

    header(
        nb, "03", "ReAct 提示工程",
        "**Agent 的可靠性 = 模型的指令遵循能力 × 你的格式契约清晰度 × 解析器的健壮性。**\n"
        "三者中只有后两个是你完全可控的 —— 所以先把它们做到极致。",
    )

    objectives(nb, [
        "说清「模型说得对但程序读不懂」这个问题的本质",
        "写出四块结构的提示词，并解释「输出格式契约」为什么是 Agent 特有的",
        "用受控实验证明：格式契约才是可解析率的开关，不是业务规则",
        "让解析器能容忍 6 种畸形输出，并说清每一级的降级策略",
        "识别并避免「静默错误」—— 把半截坏 JSON 当成最终答案",
        "实现解析失败回灌纠错，并解释为什么必须有重试上限",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

第 02 章我们把工具系统做扎实了：参数校验、AST 白名单、路径沙箱、
结果截断、失败转结果。**但这一切都建立在一个前提上：模型愿意按你的格式说话。**

这一章要拆的就是这个前提。顺序：

```
① 先看问题：模型答对了，但程序一个字段都提取不到
② 为什么加了业务规则还是不行？     → 需要「输出格式契约」
③ 提示词该怎么组织？               → 就地讲四块结构
④ 模型的真实输出有多脏？           → 用 6 种畸形输出实测
⑤ 最危险的一种：静默错误           → 就地讲协议违规判定
⑥ 写崩了怎么办？                   → 就地讲回灌纠错 + 重试上限
⑦ 三种工具调用协议怎么选
```

每个知识点都出现在**你正好需要它**的时候。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `re.compile` | 标准库 `re` | 编译正则 | `re.compile(正则, 标志)` → `Pattern` 对象 |
| `Pattern.search` | 上面返回的对象 | 找第一个匹配 | → `Match`，**找不到返回 `None`** |
| `Pattern.finditer` | 上面返回的对象 | 找全部匹配（可迭代） | 产生 `Match` 对象 |
| `Match.group(n)` | 上面返回的对象 | 取捕获内容 | `.group(0)` 整个匹配，`.group(1)` 第 1 个括号 |
| `re.S` | 标准库 `re` | 标志位 | 让 `.` 匹配换行符（跨行输出必加） |
| `json.loads` | 标准库 `json` | JSON 文本 → Python 对象 | 非法 JSON 抛 `JSONDecodeError` |
| `ast.literal_eval` | 标准库 `ast` | 安全解析字面量 | 单引号字典等 Python 风格字面量 |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `PromptBuilder` | `core.prompts` | 提示词构建器。参数：`style` / `persona` / `rules` / `extra_context` |
| `parse_output` | `core.parser` | 把模型文本解析成 `ParsedOutput`（分级降级，容忍 6 种畸形格式） |
| `ParsedOutput` | `core.parser` | 解析结果。字段：`.thought` / `.answer` / `.tool_calls` / `.errors` / `.raw` |
| `parse_tool_calls` | `core.parser` | 只要工具调用的便捷函数，返回 `list[ToolCall]` |
| `SpyLLM` | `core.mock_llm` | 包装任意模型，记录它每次收到的完整提示词 |
| `ScriptedLLM` | `core.mock_llm` | 按剧本念台词的假模型（用来喂畸形输出） |
| `default_mock` | `core.mock_llm` | 默认假模型（`RuleBasedLLM`） |

### `ParsedOutput` 的字段（解析器给你什么）

| 字段 | 类型 | 含义 |
|---|---|---|
| `.thought` | str | 提取到的 Thought（没有则空串） |
| `.answer` | str | 提取到的 Final Answer（没有则空串） |
| `.tool_calls` | list | 解析出的工具调用 |
| `.errors` | list[str] | 解析遇到的问题（**空列表 = 一切正常**） |
| `.raw` | str | 模型的原始输出（排查问题时看它） |
| `.is_final` | bool | 有答案且没有待执行工具 → 可以结束 |
| `.has_tool_call` | bool | 有没有解析出工具调用 |

### 随时可查

```python
explain(PromptBuilder)   # 参数含义 + 返回 + 例子
explain(parse_output)    # 分级降级策略
explain(ParsedOutput)    # 字段逐个说明
```""")

    # ==================================================================
    section(nb, "①", "先看问题：模型答对了，程序却读不懂")

    nb.md("""### 现在卡在哪

假设我们把工具和提示词都准备好了，问模型一个算术问题。**它答对了。**

但我们的程序需要知道的是"它要调用哪个工具、参数是什么"。看它给了什么。""")

    nb.code('''# 单独可运行：模型说得对，但程序提取不到任何结构化信息
import re

# 模拟一个"很热情但没按格式输出"的模型回复
CHATTY_REPLY = (
    "当然可以！我来帮你算一下。"
    "你给的表达式是 (12+8)*3/4，"
    "按照先乘除后加减的顺序计算，结果是 15。"
)

print("模型回复：")
print("  ", CHATTY_REPLY)
print()

# ---- 我们期望的格式是 <call>{"name": ..., "args": {...}}</call> ----
CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>", re.S)
FINAL_RE = re.compile(r"Final Answer\\s*[:：]\\s*(.*)", re.S)

print("用我们的解析器去提取：")
print("  找工具调用 :", CALL_RE.search(CHATTY_REPLY), " <- None")
print("  找最终答案 :", FINAL_RE.search(CHATTY_REPLY), " <- None")
print()
print("★ 结论：模型答对了，但程序**一个字段都提取不到**。")
print()
print("这带来三个具体后果：")
print("  1. 无法校验 —— 它给的 15 是对的还是编的？我们没法验证")
print("  2. 无法复现 —— 没有结构化的执行记录，下次同样的问题不知道会不会一样")
print("  3. 无法审计 —— 生产系统需要知道'它调了什么工具、拿什么参数'")
print()
print("★ 更糟的情况：它这次算对了，下次算错了，我们**根本不知道**。")''')

    nb.md("""### 结论：我需要模型稳定地按我的格式说话

这是 Agent 特有的问题。普通程序里，函数的输入格式由**代码**保证；
Agent 里，输入格式要靠**和模型约定**，而模型不一定遵守。

### 一个自然的想法：加业务规则

"在提示词里写清楚：需要计算时必须调用 calc 工具，禁止心算。"

这看起来应该有用。**我们实测一下。**""")

    # ==================================================================
    section(nb, "②", "为什么加了业务规则还是不行？")

    nb.md("""### 现在卡在哪

我们要验证"加一条业务规则"到底有没有用。
但真实模型每次输出都不一样，没法做对照实验。

### 所以我需要一个「行为完全固定、由我控制」的模型

项目里有两个现成的假模型（`core/mock_llm.py`）：

| 名字 | 行为 | 本章用它干什么 |
|---|---|---|
| `ScriptedLLM` | 你给它一串回复，它照顺序吐出来 | 喂特定格式的输出，测解析器 |
| `RuleBasedLLM` | 关键词匹配，模仿 ReAct 两拍 | 看"正常模型"的行为 |

但做对照实验还需要一个"**性格固定但会随提示词改变行为**"的模型。
所以我们自己写一个：它会检查系统提示词里**有没有格式契约**，据此决定输出什么。

### 立刻做这个对照实验""")

    nb.code('''# 单独可运行：受控实验 —— 提示词里有什么，决定模型输出什么
import sys, pathlib, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message


class FixedPersonalityLLM(LLM):
    """一个"性格固定"的假模型，用来做对照实验。

    它唯一的开关是：**系统提示词里有没有「输出格式契约」**
    （判定标准：同时出现 Action: 和 <tool_call>）。

    有契约   -> 输出结构化文本（Thought + Action + <tool_call>）
    没契约   -> 像普通聊天助手一样输出自然语言

    为什么这么设计？因为要做**受控实验**：
    只改变"提示词"这一个变量，看输出格式怎么变。
    真实模型做不到这一点（它每次输出都不一样，还无法按需失败）。
    """

    def _complete(self, messages, **kwargs):
        # 取出系统提示词 —— 这是它唯一的判断依据
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")

        # ★ 它的"唯一开关"：系统提示词里有没有格式契约
        has_contract = ("Action:" in system) and ("<tool_call>" in system)

        if not has_contract:
            # 没有契约 -> 输出自然语言（程序提取不到任何字段）
            return LLMResponse(
                text=f"好的，我来算一下。你给的表达式是 {user}，结果是 15。"
            )

        # 有契约 -> 按约定输出结构化文本
        return LLMResponse(
            text="Thought: 这是算术问题，我应该用 calc 工具，而不是自己心算。\\n"
                 'Action: calc(expr="(12+8)*3/4")\\n'
                 '<tool_call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</tool_call>'
        )


# ---- 三种提示词配置，逐个测试 ----
QUESTION = "计算 (12+8)*3/4"
CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>|<tool_call>(\\{.*?\\})</tool_call>", re.S)

CONFIGS = [
    ("A. 纯聊天（什么规则都没有）", "你是一个乐于助人的 AI 助手。"),
    ("B. 加业务规则（要求用工具）",
     "你是一个乐于助人的 AI 助手。\\n"
     "# 业务规则\\n- 需要计算时必须使用 calc 工具，禁止心算。"),
    ("C. 加输出格式契约",
     "你是一个乐于助人的 AI 助手。\\n"
     "# 输出格式（严格遵守）\\n"
     "需要工具时输出：\\n"
     "Thought: <推理>\\n"
     'Action: <工具名>(<参数>)\\n'
     '<tool_call>{"name": "<工具名>", "args": {...}}</tool_call>'),
]

print(f"{'提示词配置':<30}{'模型输出前 40 字':<44}{'可解析'}")
print("-" * 86)
for label, system in CONFIGS:
    reply = FixedPersonalityLLM().complete(
        [Message.system(system), Message.user(QUESTION)]
    ).text
    parsable = bool(CALL_RE.search(reply))
    first = reply.splitlines()[0][:40]
    print(f"{label:<30}{first:<44}{'✅ 是' if parsable else '❌ 否'}")''')

    nb.md("""### 结果说明什么

| 配置 | 有没有格式契约 | 可解析 |
|---|---|---|
| A. 纯聊天 | 没有 | ❌ |
| B. 加业务规则 | **没有** | ❌ |
| C. 加输出格式契约 | **有** | ✅ |

**关键发现：加业务规则（B）没有用。**

为什么？因为业务规则约束的是**行为**（"你该用工具"），
而程序需要的是**格式**（"你要用这种写法告诉我"）。
这两件事是分开的。

> **所以我需要的东西叫「输出格式契约」** ——
> 它不是写给用户看的，是**写给解析器看的**。

现在的问题是：提示词该怎么组织，才能让格式契约清晰、可维护？""")

    # ==================================================================
    section(nb, "③", "提示词该怎么组织：四块结构")

    nb.md("""### 现在卡在哪

新手很容易把提示词写成一大坨字符串。后果：

- 改一处影响全局，没法做回归测试
- 想注入 RAG 片段时，不知道该插在哪
- 工具变了要手改提示词正文，容易漏改导致格式不一致

### 所以我需要一个「分块、每块职责单一」的组织方式

观察下来，一个 Agent 的系统提示词由**四块**组成：

| 块 | 读者 | 职责 | 变了会怎样 |
|---|---|---|---|
| ① 身份与规则 | 模型 | 我是谁、遵守什么业务规则 | 行为风格变化 |
| ② 工具说明书 | 模型 | 我能用什么、参数什么格式 | 影响工具选择准确率 |
| ③ **输出格式契约** | **解析器** | 我必须怎么说话 | **影响能不能跑起来** |
| ④ 参考资料 | 模型 | RAG 片段、长期记忆、当前时间 | 影响事实准确性 |

第 ③ 块是 Agent 特有的，也是最容易被忽略的。

### 分块的好处：每一块都能单独断言

```
assert "Action:" in system          # 格式契约在
assert "calc" in system             # 工具说明在
assert "禁止心算" in system          # 业务规则在
assert "2025-01-01" in system       # 动态上下文在
```

这就是第 10 章「提示词回归测试」的基础设施。揉成一大坨字符串，你就没法做这种断言。

### 立刻用 `PromptBuilder` 生成一次

本项目提供了成品 `core.prompts.PromptBuilder`。它的构造参数：

| 参数 | 类型 | 含义 | 默认 |
|---|---|---|---|
| `style` | str | `"react"` / `"function_calling"` / `"plain"` | `"react"` |
| `persona` | str | 追加的身份描述 | `""` |
| `rules` | list[str] | 业务规则列表 | `[]` |
| `extra_context` | str | 动态上下文（RAG 片段、当前时间…） | `""` |
| `max_tools` | int | 工具数超过它会附一句提醒 | `20` |

方法是 `build_system(tools)`，参数是 `ToolRegistry`，返回拼好的系统提示词字符串。""")

    nb.code('''# 单独可运行：用 PromptBuilder 生成四块结构的提示词
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.prompts import PromptBuilder
from core.tool import build_default_registry

# 工具注册表：里面有 calc / count_words / lookup_order 等
reg = build_default_registry(ROOT)

# 构造提示词构建器：每一块对应一个参数
pb = PromptBuilder(
    style="react",                                  # 用纯文本 ReAct 协议
    persona="你是「小助手」，一个严谨的电商客服助理。",   # ① 身份
    rules=[                                         # ① 业务规则
        "涉及金额计算一律用 calc，禁止心算。",
        "不要猜测订单状态，一律用 lookup_order 查询。",
    ],
    extra_context="当前时间：2025-01-01 09:00（北京时间）",   # ④ 参考资料
)

system = pb.build_system(reg)      # ② 工具说明 + ③ 格式契约 由它自动注入

print("生成的系统提示词总长度：", len(system), "字符")
print()
print("=" * 66)
print(system)
print("=" * 66)
print()
print("分段断言（这就是分块的好处）：")
for label, token in [
    ("③ 格式契约", "Action:"),
    ("③ 格式契约", "<tool_call>"),
    ("② 工具说明", "calc"),
    ("① 业务规则", "禁止心算"),
    ("④ 参考上下文", "2025-01-01"),
    ("① 身份", "电商客服"),
]:
    print(f"   {label:<12} {'✅' if token in system else '❌'}  {token!r}")''')

    nb.md("""### 顺便注意一个实现细节

`PromptBuilder` 注入工具说明时用的是 **`str.replace` 而不是 `str.format`**：

```python
base = REACT_SYSTEM.replace("{tools}", tool_desc)
```

**为什么？** 因为 ReAct 提示词里含大量 JSON 花括号
（`<tool_call>{"name": ..., "args": {...}}</tool_call>`）。
用 `str.format` 会把它们当成占位符，直接报 `KeyError`。

这个坑非常常见。自己写提示词模板时记住：**花括号多的时候别用 `format`。**

现在提示词能给模型了。但**真实模型会老老实实按格式输出吗？**""")

    # ==================================================================
    section(nb, "④", "模型的真实输出有多脏")

    nb.md("""### 现在卡在哪

我们写好格式契约了。但真实模型（尤其是小模型、本地模型）经常写出各种"差不多但不合法"的格式。

**如果解析器只认一种标准格式，换个模型就全崩。**

### 所以我需要一个「分级降级」的解析器

思路：把解析策略按可靠性**从高到低**排成几级，任何一级成功就停止。

| 级别 | 匹配什么 | 可靠性 |
|---|---|---|
| 1 | `<tool_call>{...}</tool_call>` | 最可靠（模型专门学过） |
| 2 | ` ```json {...}``` ` 代码块 | 次可靠 |
| 3 | `Action: name({...})` 内联 JSON | 常见 |
| 4 | `Action: name(k=v)` 键值对 | JSON 全崩了也能救 |
| 5 | 整段里第一个像 JSON 的片段 | 最后手段 |

本项目已经实现了这套：`core.parser.parse_output(text, known_tools=...)`。

它的参数和返回：

| 参数 | 类型 | 含义 |
|---|---|---|
| `text` | str | 模型的原始输出 |
| `known_tools` | list[str] 或 None | 已知工具名（**只作参考，不拦截幻觉工具**） |

返回一个 `ParsedOutput` 对象（字段见 ⓪ 节的表）。

### 立刻用 6 种畸形输出实测""")

    nb.code('''# 单独可运行：6 种真实会遇到的畸形输出，解析器全都要接住
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.parser import parse_output

CASES = [
    ("① 标准 ReAct",
     'Thought: 用 calc 算。\\n'
     'Action: calc(expr="1+1")\\n'
     '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>',
     "最理想：Thought + Action + 结构化标签"),

    ("② 只有 Markdown 代码块",
     'Thought: 我来算。\\n```json\\n{"name": "calc", "args": {"expr": "1+1"}}\\n```',
     "很多模型默认输出 ```json 围栏"),

    ("③ 单引号 JSON",
     "Thought: 算一下。\\n<tool_call>{'name': 'calc', 'args': {'expr': '1+1'}}</tool_call>",
     "Python 风格的引号，不是合法 JSON"),

    ("④ 尾逗号",
     'Thought: 算一下。\\n<tool_call>{"name": "calc", "args": {"expr": "1+1",},}</tool_call>',
     "JSON 不允许尾逗号，但模型很爱写"),

    ("⑤ 参数值缺引号（KV 兜底）",
     "Thought: 算一下。\\nAction: calc(expr=1+1)",
     "连 JSON 都没有，靠 Action: name(k=v) 兜底"),

    ("⑥ 括号没闭合 / 彻底崩坏",
     'Thought: 我要算一下\\nAction: calc(expr="1+1"',
     "★ 最危险的一种（下一节专门讲）"),
]

for title, raw, why in CASES:
    # parse_output 把文本解析成结构化的 ParsedOutput
    p = parse_output(raw)

    print(f"{title}")
    print(f"   模型输出   : {raw.replace(chr(10), ' ')[:58]}")
    print(f"   为什么出现 : {why}")
    print(f"   解析结果   : thought={'有' if p.thought else '无'}  "
          f"calls={[c.signature()[:34] for c in p.tool_calls]}  "
          f"answer={p.answer[:16]!r}")
    if p.errors:
        # errors 非空说明解析过程中遇到了问题（这是给开发者看的信息）
        print(f"   ⚠️  解析错误 : {p.errors[0][:58]}")
    print()''')

    nb.md("""### 结果说明什么

- ①②③④⑤ 全部解析成功 —— 分级降级起作用了
- 第 ⑥ 种：`calls=[]`，`answer=''`，但 `errors` 里有一条
- **注意第 ⑥ 种的 `answer` 是空的** —— 这一点非常重要，下一节专门讲

前五种解决了。但第六种如果不小心处理，会造成一个**比崩溃更危险**的问题。""")

    # ==================================================================
    section(nb, "⑤", "最危险的一种：静默错误")

    nb.md("""### 现在卡在哪

第 ⑥ 种输出是：`Thought: 我要算一下\\nAction: calc(expr="1+1"` —— 括号没闭合。

它**既没有工具调用，也没有 Final Answer**。那解析器该拿它怎么办？

### 一个看起来合理的兜底逻辑，和一个灾难性的后果

新手很容易这么写：

```python
if not tool_calls and not answer:
    answer = 整段文本          # ← 都没提取到，那就当聊天回复吧
```

于是那半截坏 JSON 被当成**最终答案**返回给用户。
**而且 Agent 完全不知道出过错** —— 它会 `stop_reason="final_answer"` 正常结束。

这就是**静默错误**：不报错、不崩溃，只是答案错了。
**比崩溃危险得多**，因为崩溃你至少知道出问题了。

### 所以我需要「区分聊天内容 vs 坏掉的工具调用」

判据不能看结构（结构已经崩了），要看**关键词**：

- 出现 `Action:` / `Thought:` / `<tool_call>` / `Final Answer:` → 说明模型**试图**走协议
- 或者出现 `"name":` / `"args":` 这类字段名 → 说明它想写 JSON 工具调用

满足任一条却解析不出调用 → 判定为**协议违规**，**不**退化成答案，而是报错交给上层处理。

### 立刻对比两种兜底逻辑""")

    nb.code('''# 单独可运行：静默错误是怎么发生的（对比两种兜底逻辑）
import re

# 这段是"坏掉的工具调用"：括号没闭合，也拿不到 Final Answer
BROKEN = 'Thought: 我要算一下\\nAction: calc(expr="1+1"'
CHAT = "你好呀，今天天气不错。"       # 这段是真正的聊天内容

# 协议关键词：出现任何一个，说明模型"试图"走协议
PROTOCOL_HINT = re.compile(r"(Action\\s*[:：]|Thought\\s*[:：]|<tool_call>|Final\\s*Answer)", re.I)
# JSON 字段名：出现它说明模型想写 JSON 工具调用，只是写坏了
JSON_HINT = re.compile(r'"(?:name|args|arguments|tool)"\\s*:', re.I)

def looks_like_broken_protocol(text):
    """判断一段文本是不是「试图调用工具但写崩了」。

    参数 text：模型的原始输出
    返回    ：bool
    """
    return bool(PROTOCOL_HINT.search(text)) or bool(JSON_HINT.search(text))

def fallback_naive(text):
    """❌ 危险的兜底：什么都没提取到，就整段当答案。"""
    return text.strip()

def fallback_safe(text):
    """✅ 安全的兜底：协议违规不退化答案，而是报错。"""
    if looks_like_broken_protocol(text):
        return None      # None = 判定为协议违规，交给上层回灌纠错
    return text.strip()  # 真正的聊天内容才当答案

print("对「坏掉的工具调用」：")
print(f"   ❌ 危险兜底 -> 返回 {fallback_naive(BROKEN.splitlines()[1])!r}")
print("      ^ 这半截坏 JSON 会被当成最终答案交给用户！")
print(f"   ✅ 安全兜底 -> 返回 {fallback_safe(BROKEN.splitlines()[1])!r}（判定为协议违规）")
print()
print("对「真正的聊天内容」：")
print(f"   ✅ 安全兜底 -> 返回 {fallback_safe(CHAT)!r}（正常当答案）")
print()
print("★ 核心区别：安全兜底会区分「聊天」和「坏掉的协议」，危险兜底不会。")
print()
print("用项目的解析器验证（它就是这么做的）：")
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.parser import parse_output

p_broken = parse_output(BROKEN)
p_chat = parse_output(CHAT)
print(f"   parse_output(坏掉的调用).answer = {p_broken.answer!r}  <- 空！没退化成答案")
print(f"   parse_output(坏掉的调用).errors = {p_broken.errors}")
print(f"   parse_output(聊天).answer       = {p_chat.answer!r}  <- 正常当答案")''')

    nb.md("""### 对照表

| 输入 | 危险兜底 | 安全兜底 |
|---|---|---|
| 坏掉的工具调用 | 当成答案 → **静默错误** ❌ | 判定协议违规 → 回灌纠错 ✅ |
| 真正的聊天内容 | 当成答案 ✅ | 当成答案 ✅ |

**这一节是本章最重要的工程教训**：
> 错误处理里最危险的不是"崩溃"，而是"悄悄用错误的方式继续"。

现在解析器能识别问题了。下一个问题：**识别出来之后怎么办？**""")

    # ==================================================================
    section(nb, "⑥", "解析失败怎么办：回灌纠错")

    nb.md("""### 现在卡在哪

模型写崩了格式。我们的选择有：

| 做法 | 后果 |
|---|---|
| 直接放弃，报错给用户 | 用户体验差，明明模型有能力改对 |
| 无限重试 | 模型永远写不对时无限烧钱 |
| **把错误告诉它，让它重写，但限制次数** | ✅ 正确做法 |

### 所以我需要一个「把解析错误变成提示再发回去」的机制

关键：回灌的信息必须**具体** —— 不能只说"你写错了"，
要告诉它"哪里错了 + 正确的格式长什么样"。

本项目 `core/prompts.py` 提供了 `PromptBuilder.parse_error_feedback(error)`，
返回的就是这么一段纠错提示。

### 立刻看它长什么样 + 跑一遍完整链路""")

    nb.code('''# 单独可运行：把解析错误变成给模型的纠错提示
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.prompts import PromptBuilder
from core.parser import parse_output

# 模拟一次解析失败，拿到错误原因
BROKEN = 'Thought: 我要算一下\\nAction: calc(expr="1+1"'
parsed = parse_output(BROKEN)
error_text = "; ".join(parsed.errors) or "没有找到 Action 或 Final Answer"

# 把错误转成写给模型看的提示
feedback = PromptBuilder.parse_error_feedback(error_text)

print("解析器报出的错误：")
print("  ", error_text)
print()
print("转成给模型的纠错提示（这一段会被追加到对话历史里）：")
print("=" * 66)
print(feedback)
print("=" * 66)
print()
print("★ 注意它包含三样东西：")
print("   1. 哪里错了（原文引用解析器的报错）")
print("   2. 正确的格式是什么（格式 A 或格式 B）")
print("   3. 一个保底建议（如果真的知道答案，直接用 Final Answer）")''')

    nb.md("""### 完整链路：第一次写崩 → 回灌 → 第二次写对

下面这一格把整个纠错链路跑通。注意 `ScriptedLLM` 的剧本：
第一条是坏输出，第二条是被纠正后的好输出，第三条是最终答案。""")

    nb.code('''# 单独可运行：解析失败 -> 回灌 -> 重写 -> 成功（含重试上限）
import sys, pathlib, json
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message
from core.mock_llm import ScriptedLLM
from core.parser import parse_output
from core.prompts import PromptBuilder

# 剧本：三步走 —— 写崩 / 被纠正后写对 / 给出最终答案
SCRIPT = [
    # 第一次：括号没闭合（典型的格式崩坏）
    'Thought: 我要算一下\\nAction: calc(expr="1+1"',

    # 第二次：收到纠错提示后，写对了
    'Thought: 抱歉，刚才格式写错了。\\n'
    'Action: calc(expr="1+1")\\n'
    '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>',

    # 第三次：看到工具结果，给出答案
    'Thought: 算出来了。\\nFinal Answer: 1+1 = 2',
]

MAX_PARSE_RETRIES = 2        # ★ 连续解析失败几次就放弃（必须有上限）

llm = ScriptedLLM(SCRIPT)
messages = [
    Message.system("需要工具时用 Action: + <tool_call>，可以回答时用 Final Answer:"),
    Message.user("计算 1+1"),
]

fail_streak = 0              # 连续解析失败次数
for round_no in range(1, 6):
    reply = llm.complete(messages).text
    parsed = parse_output(reply)

    print(f"--- 第 {round_no} 圈 ---")
    print(f"  模型输出 : {reply.replace(chr(10), ' ')[:56]}")

    # 情况 1：它给出了最终答案 -> 结束
    if parsed.is_final:
        print(f"  ✅ 最终答案：{parsed.answer}")
        break

    # 情况 2：解析出工具调用 -> 执行（这里简化成直接返回结果）
    if parsed.has_tool_call:
        call = parsed.tool_calls[0]
        print(f"  🔧 调用工具：{call.signature()}")
        messages.append(Message.assistant(parsed.thought, parsed.tool_calls))
        messages.append(Message.tool_result(call.name, "1+1 = 2"))
        fail_streak = 0                       # 成功一次就把失败计数清零
        continue

    # 情况 3：解析失败 -> 回灌纠错提示
    fail_streak += 1
    print(f"  ⚠️  解析失败（连续第 {fail_streak} 次），回灌纠错提示")
    messages.append(Message.assistant(reply))
    messages.append(Message.user(
        PromptBuilder.parse_error_feedback("; ".join(parsed.errors))
    ))

    # ★ 连续失败超过上限 -> 停机，不再无限重试
    if fail_streak > MAX_PARSE_RETRIES:
        print(f"  ❌ 连续失败 {fail_streak} 次，停机（stop_reason=parse_failed）")
        break
    print()

print()
print("★ 纠错成功的原因：回灌的信息里说清了「哪里错了 + 正确格式」。")
print("★ 上限的意义：如果模型连续 N 次都写不对，说明它没能力遵守这个协议，")
print("  继续重试只是烧钱 —— 这时候应该如实报告，而不是死磕。")''')

    nb.md("""### 还要注意一件事：回灌会让上下文变长

每次回灌都往历史里加两条消息（模型的坏输出 + 我们的纠错提示）。
用 `SpyLLM` 可以看清上下文是怎么一轮轮涨起来的 ——
它是"包装任意模型、记录每次收到的完整提示词"的假模型。""")

    nb.code('''# 单独可运行：用 SpyLLM 看上下文怎么一轮轮变长
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import Agent
from core.mock_llm import SpyLLM, default_mock

# SpyLLM 包在真实模型外面，记录它每次收到的完整 messages
spy = SpyLLM(default_mock())

# 用框架版 Agent 跑一次任务（它会调用 spy 里的假模型）
Agent(llm=spy, max_steps=6, verbose=False).run("计算 (12+8)*3/4")

print("SpyLLM 记录了每次调用的上下文：")
print(spy.diff_summary())
print()
print("第 1 次调用时模型看到的消息：")
for m in spy.seen[0]:
    print(f"   [{m.role:<9}] {m.content.replace(chr(10), ' ')[:56]}")
print()
print("第 2 次调用时多了什么：")
for m in spy.seen[1]:
    print(f"   [{m.role:<9}] {m.content.replace(chr(10), ' ')[:56]}")
print()
print("★ 历史每圈都在涨 —— 因为每次都要把**整段历史**重新发给模型。")
print("  这引出两个后续章节：")
print("    · 历史无限增长 -> 上下文窗口会爆     -> 第 05 章 记忆与上下文工程")
print("    · 每次都重发全部历史 -> 成本平方增长 -> 第 12 章 成本优化")''')

    # ==================================================================
    section(nb, "⑦", "三种工具调用协议怎么选")

    nb.md("""### 现在卡在哪

我们一直在用"纯文本协议"（自己写正则解析）。但厂商还提供了另一种方式：
**原生 Function Calling**。该选哪个？

### 三种协议对比

| 协议 | 实现方式 | 优点 | 代价 |
|---|---|---|---|
| **纯文本 ReAct** | 自己写正则/分级解析 | 任何模型都能用、完全可解释、易调试 | 可靠性最低、格式说明耗 token、易解析失败 |
| **原生 Function Calling** | 解析 API 返回的 `tool_calls` 字段 | 可靠性最高、格式由厂商保证 | 绑定厂商、模型受限、调试时看不到黑盒决策 |
| **约束解码 / JSON Mode** | 强制模型只能输出合法 JSON | 格式 100% 合法 | 表达力受限、部分服务商不提供 |

### 项目怎么做的：两条路线共用同一个解析器

`core/real_llm.py` 里，拿到厂商的原生 `tool_calls` 后**把它还原成文本协议**：

```python
# 原生 tool_calls -> 我们自己的 <tool_call> 标签
blocks.append(f'<tool_call>{"id": "...", "name": "...", "args": {...}}</tool_call>')
text = text + "\\n" + "\\n".join(blocks)
```

这样上层的解析逻辑**完全不用改** —— 这就是适配器模式的价值。

### 立刻验证这一点""")

    nb.code('''# 单独可运行：原生 tool_calls 还原成文本协议后，同一个解析器照样能处理
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.parser import parse_tool_calls

# 这行文本模拟"厂商返回的原生 tool_calls 被适配器还原后的样子"
NATIVE_AS_TEXT = (
    '<tool_call>{"id": "call_abc123", "name": "calc", '
    '"args": {"expr": "6*7"}}</tool_call>'
)

calls = parse_tool_calls(NATIVE_AS_TEXT)

print("输入（原生协议还原后的文本）：")
print("  ", NATIVE_AS_TEXT)
print()
print("用同一个解析器处理：")
for c in calls:
    print(f"   工具名 : {c.name}")
    print(f"   参数   : {c.args}")
    print(f"   调用 id: {c.id}      <- 原生协议会带 id，用来把结果和请求配对")
print()
print("★ 结论：原生 Function Calling 和纯文本 ReAct **共用同一个解析器**，")
print("  所以换模型对上层完全透明 —— 这就是适配器模式的价值。")
print()
print("工程上的务实选择：")
print("  · 生产环境优先用原生 Function Calling（可靠性 > 厂商绑定成本）")
print("  · 要兼容本地开源模型/多厂商时用纯文本 ReAct，但必须写足分级降级")
print("  · 两者可以同时开（项目就是这么做的）")''')

    # ==================================================================
    section(nb, "⑧", "常见坑汇总")

    pitfall_table(nb, [
        ("只用业务规则，不写格式契约", "模型知道该用工具，但仍输出自然语言",
         "规则和格式契约分开写，两块都要"),
        ("用 `str.format` 注入工具说明", "提示词里的 JSON 花括号被当占位符，报 `KeyError`",
         "用 `str.replace` 或双写 `{{ }}`"),
        ("兜底逻辑把坏输出当答案", "半截 JSON 变成用户看到的答案（静默错误）",
         "协议关键词检测，判为协议违规"),
        ("解析器只认一种格式", "换个模型就全崩", "分级降级 + 宽松 JSON + 参数名兼容"),
        ("无限制回灌纠错", "模型写不对时无限烧钱", "`max_parse_retries`"),
        ("提示词写成一大坨", "无法回归测试，改一处影响全局", "四块结构，每块可断言"),
        ("不记录模型原始输出", "解析出问题时无从排查", "原始输出必须落日志"),
        ("`re.compile` 忘加 `re.S`", "跨行的模型输出匹配不到", "Agent 场景几乎必加"),
        ("以为原生 Function Calling 是模型在调用函数", "理解错整条链路",
         "本质仍是文本进文本出（第 00 章讲过）"),
    ])

    summary(nb, [
        "**ReAct = 把「思考」显式写出来**，让推理可观察、可干预、可回灌纠错。",
        "**提示词 = 身份规则 + 工具说明书 + 输出格式契约 + 参考资料。**",
        "**格式契约的读者是解析器，不是用户** —— 这是 Agent 提示词最特别的一块。",
        "**业务规则约束行为，格式契约约束格式** —— 加了业务规则不等于能解析。",
        "**解析失败要用分级降级，并且绝不退化成答案**（静默错误比崩溃危险）。",
        "**回灌纠错必须有限额**，连错 N 次就停机，不要死磕。",
        "**原生 Function Calling 和纯文本协议本质相同**，项目让它们共用解析器。",
    ], "第 04 章会遇到一个新问题：**复杂任务一步做不完**。"
       "现在的循环是「走一步看一步」，遇到「调研三家竞品并写报告」这种任务会崩 ——"
       "因为单次模型调用承载不了那么长的因果链。那需要「规划」。")

    exercises(nb, [
        ("**给解析器加一种新格式。**\n\n"
         "现在不支持 `TOOL: calc | ARGS: {\"expr\":\"1+1\"}` 这种自定义分隔符。\n"
         "自己写一个正则，把它也解析出来。\n\n"
         "思考：应该加在分级降级的哪一级？为什么？",
         "加在 `Action: name(...)` 那一级**之后**（优先级更低）——"
         "因为它的格式更不规范，可靠性更低。\n\n"
         "分级的原则：越靠前 = 模型越可能专门学过 = 越可靠。"),

        ("**故意制造静默错误，观察后果。**\n\n"
         "把 `looks_like_broken_protocol()` 改成永远返回 `False`，"
         "然后重新跑第 ⑤ 节的对比单元。\n\n"
         "观察：坏掉的工具调用会变成什么？\n\n"
         "思考：这种 bug 在真实项目里为什么特别难发现？",
         "它会退化成 `answer`，被当成最终答案。\n\n"
         "难发现的原因：**程序不报错、不崩溃、`stop_reason` 还是 `final_answer`**，"
         "所有监控指标看起来都正常，只有答案内容是错的。\n\n"
         "这就是为什么要有「轨迹可观测性」（第 10 章）："
         "光看结果不够，要看过程。"),

        ("**测一测不同模型的指令遵循能力。**\n\n"
         "如果能配 API Key，用**同一个提示词**跑 2-3 个不同模型，"
         "记录「格式正确率」。\n\n"
         "这是选模型时最该看的指标之一。",
         "先把同一段系统提示词和问题发给不同模型，"
         "然后用 `parse_output()` 看能不能解析出工具调用。\n\n"
         "统计：跑 10 次，成功几次？这个比例比「跑分」更能预测它在你的 Agent 里好不好用。"),

        ("**给提示词加「思维预算」。**\n\n"
         "现在的格式契约要求 Thought 简短，但没有强制。\n"
         "试试明确限制长度（比如「Thought 最多 30 字」），\n"
         "观察对解析成功率和 token 消耗的影响。",
         "改 `REACT_SYSTEM` 里关于 Thought 的那一句，或者在自己的提示词里加一条规则。\n\n"
         "理论上：Thought 越短 -> 格式越简单 -> 解析成功率越高，token 也越省。"
         "但太短可能让模型「想不清楚」。这是一个真实的取舍。"),

        ("**实现提示词的差异对比工具。**\n\n"
         "写一个函数，用 `difflib.unified_diff` 对比 `PromptBuilder` "
         "在不同配置下生成的系统提示词，输出人类可读的 diff。\n\n"
         "用途：code review 提示词改动。",
         "`PromptBuilder(style=\"react\")` vs `PromptBuilder(style=\"react\", rules=[\"X\"])`，"
         "两次 `build_system(reg)` 的结果做 diff。\n\n"
         "`difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm=\"\")` "
         "返回的就是可打印的 diff 行。"),
    ])

    checkpoint(nb, "03")

    return nb
