"""第 01 章 · 最小 Agent 循环 —— Notebook 内容（逐步推进版）。

------------------------------------------------------------
本书遵守 TEACHING_CONTRACT.md 的两条规矩：

  ① **逐步给**：每个知识点在"读者正好需要它"的那一刻出现，
     而不是开头集中讲完。
  ② **前置知识表**：开头仍保留一张速查表，职责是"读到一半忘了回头查"，
     明确标注初次阅读可跳过。

另外每个代码单元都能单独运行（notebooks/nb_lint.py 机器校验）。

★ 代码单元里的中文引号一律用 「」，绝不在字符串内部嵌 ASCII 双引号。
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


def build_01() -> Notebook:
    """第 01 章 · 最小 Agent 循环（逐步推进版）。"""
    nb = Notebook("第 01 章 · 最小 Agent 循环")

    header(
        nb, "01", "最小 Agent 循环",
        "Agent = 一个 while 循环 + 一个会调工具的模型 + 一个能记住历史的列表。\n"
        "循环的每一圈只做四件事：想（LLM）→ 解析 → 做（Tool）→ 记（History）。",
    )

    objectives(nb, [
        "说清 Agent 和「一次问答」的差别，并画出循环的四个动作",
        "**手写**一个能跑的最小 Agent（不用框架）",
        "解释为什么「模型没有记忆」，以及 Agent 的记忆到底是什么",
        "说出 4 种停机原因，并解释为什么 `max_steps` 是必需品",
        "解释为什么工具失败必须变成「观察结果」而不是异常",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

**从零推导，一步一步来。** 顺序是：

```
① 先写最朴素的版本（问一次、答一次），看它为什么不够
② 遇到第一个问题：模型怎么"申请"用工具？ → 就地讲正则
③ 遇到第二个问题：算出来的东西不能信   → 就地讲 ast 白名单
④ 遇到第三个问题：工具怎么被找到？      → 就地讲工具表
⑤ 遇到第四个问题：谁记住对话？          → 就地讲消息列表
⑥ 把上面拼成循环，跑通
⑦ 循环停不下来怎么办                    → 就地讲四道保险
⑧ 工具报错怎么办
```

每个知识点都出现在**你正好需要它**的时候，而不是提前堆在开头。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这不是教学部分，是**索引**。读到一半忘了某个名字是什么，回这里查。
> 正文会在需要的地方就地讲清每个东西 —— 不需要提前记住这张表。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `re.compile` | 标准库 `re` | 编译正则 | `re.compile(正则, 标志)` → `Pattern` 对象 |
| `Pattern.search` | 上面返回的对象 | 在文本里找第一个匹配 | → `Match` 对象，**找不到返回 `None`** |
| `Match.group(n)` | 上面返回的对象 | 取捕获内容 | `.group(0)` 是整个匹配，`.group(1)` 是第 1 个括号 |
| `re.S` | 标准库 `re` | 标志位 | 让 `.` 也能匹配换行符 |
| `json.loads` | 标准库 `json` | JSON 文本 → Python 对象 | → `dict` / `list`，非法 JSON 抛 `JSONDecodeError` |
| `ast.parse` | 标准库 `ast` | 源码文本 → 语法树 | `ast.parse(表达式, mode="eval")` → AST 节点 |
| `math.sqrt` | 标准库 `math` | 平方根 | `math.sqrt(16)` → `4.0` |

### 本章用到的本项目 `core/` 代码（不是 pip 包，是本仓库的文件夹）

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `Message` | `core.message` | 一条消息（`.role` / `.content`）。有 `.system()` / `.user()` / `.assistant()` / `.tool_result()` 四个构造方法 |
| `ToolCall` | `core.message` | 一次工具调用请求（`.name` / `.args`） |
| `LLM` | `core.llm` | 模型抽象基类。子类实现 `_complete(messages) -> LLMResponse` |
| `LLMResponse` | `core.llm` | 一次回复。**`.text` 是模型的正文** |
| `ScriptedLLM` | `core.mock_llm` | 按剧本念台词的假模型 |
| `LoopingLLM` | `core.mock_llm` | 永远重复同一动作的假模型（用来演示死循环） |
| `Agent` | `core`（顶层） | 框架版完整 Agent |

### 随时可查

```python
explain(run_once)        # 查函数：参数含义 + 返回什么 + 例子
explain(AgentResult)     # 查数据结构：字段逐个说明
explain()                # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "最朴素的版本：问一次，答一次")

    nb.md("""### 要做什么

先写一个"能回答问题"的程序。这是绝大多数 AI 功能的第一版。

### 想法

给模型一段文本，它回一段文本。完事。

### 会出现什么问题

我们直接试一个需要**算数**的问题，看它行不行。

> 也许你会觉得"模型算 `(12+8)*3/4` 怎么可能错"。
> 事实是：**长表达式它经常算错**，而且你无法校验 ——
> 它给出的数字看起来很自信，你不知道那是算出来的还是编出来的。
> 这是后面所有设计的起点。""")

    nb.code('''# 单独可运行：最朴素的版本 —— 没有工具，没有循环
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.llm import LLM, LLMResponse
from core.message import Message

class NaiveLLM(LLM):
    """一个"只会聊天"的模型：它没有工具可用，只能凭记忆回答。

    真实模型在这种情况下的行为就是这样 —— 它会尝试自己心算，
    或者干脆说做不到。
    """

    def _complete(self, messages, **kwargs):
        user = [m for m in messages if m.role == "user"][-1].content
        # 假装它在心算（真实模型也是"假装"—— 它没有计算器）
        return LLMResponse(text=f"根据我的计算，{user} 的结果大约是 15。")


question = "帮我算一下 (12+8)*3/4，再告诉我订单 A1001 到哪了"
reply = NaiveLLM().complete([Message.user(question)]).text

print("用户问：", question)
print("模型答：", reply)
print()
print("问题在哪：")
print("  1. 它算了个数，但我们没有校验手段 —— 对错只能靠人肉看")
print("  2. 订单信息它根本不知道，只能编")
print("  3. 就算它想用工具，它也没有「申请调用工具」这个动作")''')

    nb.md("""### 结论：需要两样东西

模型只会生成文本。要让它做实事，我们需要：

| 缺什么 | 需要补上什么 |
|---|---|
| 它不能算数、查不了订单 | 给它**工具** —— 我们自己写的函数 |
| 它不知道"该怎么告诉我们要调工具" | 和它**约定一套输出格式**，然后我们解析 |

这两件事就是整个 Agent 的全部秘密。下面一步一步来。

---

### 先解决"约定格式"这一半

我们从最简单的开始：**让模型用一段特定格式的文本告诉我们它想干什么。**

约定成：

```
<call>{"name": "工具名", "args": {"参数名": 值}}</call>
```

现在冒出一个具体的技术问题。""")

    # ==================================================================
    section(nb, "②", "怎么从一段文本里挖出我们要的东西")

    nb.md("""### 现在卡在哪

模型会输出一整段文本，比如：

```
我需要计算。
<call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</call>
```

我们要从中取出 `<call>` 和 `</call>` 中间那段 JSON。
**这是"从文本里按模式找子串"的问题 —— 手写 `find` + 切片也能做，
但一旦模式稍微复杂（比如要处理中间可能有空格、换行），就很容易写错。**

### 所以我需要一个「按模式匹配文本」的工具

Python 里这就是**正则表达式**，在标准库 `re` 模块里。

### 它的用法

```python
import re
CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>", re.S)
```

逐个参数说清楚：

| 部分 | 含义 |
|---|---|
| `re.compile(...)` | **把正则字符串编译成一个对象**（不匹配任何东西，只是准备） |
| 第 1 个参数：正则字符串 | `<call>` 字面匹配；`(\\{.*?\\})` 是一个**捕获组**，负责圈出我们要的内容 |
| `\\{` 和 `\\}` | 转义的大括号（正则里 `{` 有特殊含义，加 `\\` 表示它就是普通字符） |
| `.*?` | 任意字符（`.`）、重复任意次（`*`）、**非贪婪**（`?` 表示尽量少匹配） |
| 第 2 个参数：`re.S` | 标志位，让 `.` 也能匹配换行符。**不加它，跨行的输出就匹配不到** |

### 它给我什么

返回一个 **`Pattern` 对象**。用它的 `.search(文本)` 方法：

| 表达式 | 返回 |
|---|---|
| `CALL_RE.search(文本)` | 找到 → `Match` 对象；**找不到 → `None`**（注意：不报错！） |
| `m.group(0)` | 整个匹配到的内容 |
| `m.group(1)` | **第 1 个括号里**捕获的内容 ← 我们要的就是它 |

### 立刻用一次""")

    nb.code('''# 单独可运行：正则到底返回什么（先验证，再拿去用）
import re

CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>", re.S)

# 模拟一段模型的真实输出
MODEL_TEXT = (
    "我需要计算。\\n"
    '<call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</call>'
)

print("输入文本：")
print(MODEL_TEXT)
print()

m = CALL_RE.search(MODEL_TEXT)
print("search 返回的类型 :", type(m).__name__)
print("m.group(0)        :", repr(m.group(0)))
print("m.group(1)        :", repr(m.group(1)), "  <-- 第 1 个括号里的内容")
print()

print("如果文本里没有这个东西：")
print("   CALL_RE.search('随便一段话') =", CALL_RE.search("随便一段话"))
print("   ^ 返回 None，而且不报错 —— 所以拿到结果必须先判空")
print()

print("跨行的情况（这就是 re.S 的作用）：")
multiline = '思考中……\\n<call>{"name": "calc",\\n         "args": {}}</call>'
print("   不加 re.S :", re.compile(r"<call>(\\{.*?\\})</call>").search(multiline))
print("   加了 re.S :", "匹配成功" if re.compile(r"<call>(\\{.*?\\})</call>", re.S).search(multiline) else "没匹配到")''')

    nb.md("""### 结果说明什么

- 返回的是 `Match` 对象，不是一个字符串 —— 要调 `.group(1)` 才拿到内容
- **找不到时返回 `None`，不抛异常** —— 所以代码里必须 `if not m: return None`
- `re.S` 不是可有可无的：模型输出几乎总是跨行

现在把这段正则封装成一个函数，方便复用。""")

    nb.code('''# 单独可运行：封成函数，附"该怎么处理异常"
import re, json

CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>", re.S)

def extract_call(text: str):
    """从模型输出里取出工具调用。

    参数 text：模型的原始输出（一整段字符串）
    返回    ：(工具名, 参数字典) 这个元组；取不到时返回 None

    三种失败情况都会返回 None，而不是抛异常：
        1. 文本里没有 <call>...</call>
        2. 括号里不是合法 JSON
        3. JSON 里没有 name 字段
    """
    m = CALL_RE.search(text)
    if not m:                                  # 情况 1
        return None
    try:
        obj = json.loads(m.group(1))           # 字符串 → dict
    except json.JSONDecodeError:               # 情况 2
        return None
    if not isinstance(obj, dict) or "name" not in obj:   # 情况 3
        return None
    args = obj.get("args", {})
    if not isinstance(args, dict):
        return None
    return obj["name"], args


# 逐个测：正常 / 没有调用 / JSON 坏了 / 缺字段
cases = [
    '<call>{"name": "calc", "args": {"expr": "1+1"}}</call>',
    "我今天心情不错",
    '<call>{"name": "calc", "args": {"expr": 1+1}}</call>',
    '<call>{"args": {}}</call>',
]
for t in cases:
    print(f"  输入 {t[:44]!r:48} -> {extract_call(t)}")''')

    nb.md("""### 为什么失败要 `return None` 而不是抛异常？

因为**模型输出是不可信输入**。它经常写错格式，如果每错一次程序就崩，
这个 Agent 根本没法用。后面（第 03 章）会讲怎么把"解析失败"变成
一条提示回灌给模型，让它重写。

现在"取出工具调用"这件事解决了。下一个问题：**取出来的参数能直接信吗？**""")

    # ==================================================================
    section(nb, "③", "算数这件事：为什么不能用 eval")

    nb.md("""### 现在卡在哪

模型给的参数是 `{"expr": "(12+8)*3/4"}` —— 一个**表达式字符串**，我们要算出结果。

最直接的想法是 Python 内置的 `eval()`：它能把字符串当代码执行。

**但绝对不能这么做。** 原因：

```
模型输出 = 不可信输入
用户可以通过提示词注入，让模型输出这样的"表达式"：

    __import__('os').system('删掉你的文件')

如果我们用 eval 执行它 —— 就真的执行了。
```

### 所以我需要一个「能算数学、但不能执行任意代码」的东西

标准库 `ast`（抽象语法树）正好能解决：

- `ast.parse(表达式, mode="eval")` 把字符串**解析成语法树** ——
  一个纯数据结构，**不执行任何东西**
- 然后我们**自己遍历这棵树**，只允许白名单里的节点类型（加减乘除、几个数学函数）
- 出现任何其它语法（属性访问、函数调用、import…）→ 直接拒绝

这叫**白名单**：默认拒绝，显式允许。""")

    nb.code('''# 单独可运行：用 ast 白名单安全求值
import ast, math

def safe_calc(expr: str) -> str:
    """计算数学表达式。用 ast 白名单，绝不 eval。

    参数 expr：表达式字符串，例如 (12+8)*3/4
    返回    ：结果字符串，例如 (12+8)*3/4 = 15
    不支持的语法会抛 ValueError（调用方负责接住）
    """
    # 允许的二元运算符：AST 节点类型 -> 对应的计算函数
    BIN_OPS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a ** b,
    }
    # 允许调用的函数
    FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round,
             "floor": math.floor, "ceil": math.ceil}

    def ev(node):
        if isinstance(node, ast.Expression):       # 顶层容器，剥掉它
            return ev(node.body)
        if isinstance(node, ast.Constant):         # 数字字面量
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
        if isinstance(node, ast.BinOp):            # 二元运算：a + b
            op = BIN_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
            return op(ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp):          # 一元运算：-a
            if isinstance(node.op, ast.USub):
                return -ev(node.operand)
            raise ValueError("不支持的一元运算符")
        if isinstance(node, ast.Call):             # 函数调用：sqrt(16)
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
                raise ValueError(f"不允许调用 {getattr(node.func, 'id', '?')}")
            return FUNCS[node.func.id](*[ev(a) for a in node.args])
        # 其它一切语法都拒绝（属性访问、下标、import、lambda……）
        raise ValueError(f"表达式里出现不允许的语法: {type(node).__name__}")

    value = ev(ast.parse(expr, mode="eval"))       # 只解析，不执行
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{expr} = {value}"


print("正常表达式：")
for e in ["(12+8)*3/4", "sqrt(16)+1", "2**10", "17 % 5"]:
    print(f"   {e:<14} -> {safe_calc(e)}")

print()
print("攻击载荷（这就是为什么不能用 eval）：")
for bad in ["__import__('os').system('echo 危险')",
            "open('/etc/passwd').read()",
            "(1).__class__"]:
    try:
        safe_calc(bad)
        print(f"   没拦住: {bad}")
    except ValueError as exc:
        print(f"   已拒绝: {bad[:34]:<36} ({exc})")''')

    nb.md("""### 关键对比

| 做法 | `safe_calc("(12+8)*3/4")` | `safe_calc("__import__('os').system(...)")` |
|---|---|---|
| 用 `eval` | 算出 15 ✅ | **真的执行系统命令** ❌ |
| 用 `ast` 白名单 | 算出 15 ✅ | 抛 `ValueError`，拒绝执行 ✅ |

这就是"模型输出是不可信输入"的第一个具体后果。
第 02 章会把这件事系统化（参数校验、路径沙箱、结果截断）。

现在我们有了解析器、有了计算工具。下一个问题：**模型怎么知道有哪些工具可用？**""")

    # ==================================================================
    section(nb, "④", "模型怎么知道有哪些工具？—— 工具表")

    nb.md("""### 现在卡在哪

模型输出了 `{"name": "calc", "args": {...}}`。我们的程序拿到 `"calc"` 这个字符串，
得**根据名字找到对应的函数**去执行。

### 所以我需要一个「用名字查东西」的结构

这就是**字典**（`dict`）。`{"名字": 函数}`，查起来是 O(1)。

### 先写两个工具

工具**就是普通的 Python 函数**，没有任何魔法。""")

    nb.code('''# 单独可运行：写两个工具（普通 Python 函数）
import ast, math

def safe_calc(expr: str) -> str:
    """计算数学表达式（ast 白名单实现，见上一节）。

    参数 expr：表达式字符串，例如 (12+8)*3/4
    返回    ：结果字符串
    """
    BIN_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
               ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in BIN_OPS:
            return BIN_OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -ev(node.operand)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ("sqrt", "abs"):
                return {"sqrt": math.sqrt, "abs": abs}[node.func.id](
                    *[ev(a) for a in node.args])
        raise ValueError(f"不支持的语法: {type(node).__name__}")

    v = ev(ast.parse(expr, mode="eval"))
    return f"{expr} = {int(v) if isinstance(v, float) and v.is_integer() else v}"


# ---- 工具 2：查订单 ----
# 用假数据模拟"查内部系统"。真实场景这里是查数据库或调 API。
FAKE_ORDERS = {
    "A1001": {"status": "已发货", "carrier": "顺丰", "tracking": "SF1234567890"},
    "B2043": {"status": "运输中", "carrier": "中通", "tracking": "ZT9988776655"},
}

def lookup_order(order_id: str) -> dict:
    """查订单状态。

    参数 order_id：订单号字符串，例如 A1001（大小写都行）
    返回    ：dict，例如 {"order_id": "A1001", "status": "已发货", ...}
    查不到时抛 ValueError
    """
    key = order_id.upper()
    if key not in FAKE_ORDERS:
        raise ValueError(f"订单 {key} 不存在。已知示例：{sorted(FAKE_ORDERS)}")
    return {"order_id": key, **FAKE_ORDERS[key]}


print("safe_calc('(12+8)*3/4')  ->", safe_calc("(12+8)*3/4"))
print("lookup_order('A1001')   ->", lookup_order("A1001"))
print()
try:
    lookup_order("Z9999")
except ValueError as exc:
    print("lookup_order('Z9999')   -> 抛 ValueError:", exc)''')

    nb.md("""### 现在登记成表

模型只能调用我们**登记过**的名字 —— 这就是安全边界之一。""")

    nb.code('''# 单独可运行：工具表（名字 -> 函数）
# 为了让这一格能单独跑，把两个工具再定义一遍（内容与上一格相同）
def calc(expr: str) -> str:
    """极简版计算（只支持四则运算），签名与上一格一致。"""
    import ast
    BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant): return n.value
        if isinstance(n, ast.BinOp): return BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp): return -ev(n.operand)
        raise ValueError(f"不支持的语法: {type(n).__name__}")
    v = ev(ast.parse(expr, mode="eval"))
    return f"{expr} = {int(v) if isinstance(v, float) and v.is_integer() else v}"

def lookup_order(order_id: str) -> str:
    """查订单。参数 order_id 形如 A1001，返回描述字符串。"""
    t = {"A1001": "订单 A1001：已发货，顺丰 SF1234567890"}
    k = order_id.upper()
    if k not in t:
        raise ValueError(f"订单 {k} 不存在。已知：{sorted(t)}")
    return t[k]


# ★ 这就是"工具表"：模型只能调用这里登记过的名字
TOOLS = {
    "calc": calc,
    "lookup_order": lookup_order,
}

print("工具表 :", list(TOOLS))
print()
print("用名字查到函数并执行：")
name, args = "calc", {"expr": "6*7"}
print(f"   TOOLS[{name!r}](**{args}) = {TOOLS[name](**args)}")
print()
print("★ 注意 `**args`：模型给的是参数字典 {'expr': '6*7'}，")
print("  要用 ** 展开成关键字参数 expr='6*7'。")
print("  写成 TOOLS[name](args) 的话，expr 收到的会是整个字典 —— 这是常见错误。")''')

    nb.md("""### 顺便要交代的一件事：系统提示词

模型怎么知道有 `calc` 和 `lookup_order` 可用？**我们写在提示词里告诉它。**

这就是 `Message.system` 的用途 —— 它是给模型的"说明书"：

```python
SYSTEM = (
    "你可以调用这些工具：calc, lookup_order\\n"
    '需要工具时输出：<call>{"name": "工具名", "args": {...}}</call>\\n'
    "可以回答时输出：Final Answer: ..."
)
```

现在零件齐了。下一个问题：**对话历史存哪？**""")

    # ==================================================================
    section(nb, "⑤", "谁记住对话？—— 消息列表")

    nb.md("""### 现在卡在哪

循环第二圈的时候，模型需要知道"上一圈调用了什么工具、结果是什么"。
但模型**自己没有记忆** —— 每次调用它都是全新的。

### 所以我需要一个「按顺序攒消息」的结构

`list`。每发生一件事就往里加一条，每次调用模型时把**整个列表**发过去。

### 消息长什么样

本项目 `core/message.py` 里的 `Message` 类。它有四个构造快捷方法：

| 方法 | 什么时候用 |
|---|---|
| `Message.system(文本)` | 系统提示词：我是谁、有哪些工具、什么格式 |
| `Message.user(文本)` | 用户说的话 |
| `Message.assistant(文本)` | 模型的回复（我们要存回历史） |
| `Message.tool_result(工具名, 结果)` | 工具返回的结果 |

每条消息的字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `.role` | str | `'system'` / `'user'` / `'assistant'` / `'tool'` |
| `.content` | str | 正文 |

### 立刻验证「模型没有记忆」这件事""")

    nb.code('''# 单独可运行：亲眼看到"记忆"是怎么来的
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message
from core.mock_llm import ScriptedLLM

llm = ScriptedLLM([
    '<call>{"name": "calc", "args": {"expr": "6*7"}}</call>',
    "Final Answer: 6*7 = 42",
])

# 模拟 Agent 循环：每圈都把整段历史重发给模型
messages = [Message.system("你是助手"), Message.user("计算 6*7")]

for round_no in range(1, 3):
    print(f"=== 第 {round_no} 次调用模型 ===")
    print(f"    这次发过去 {len(messages)} 条消息，共 "
          f"{sum(len(m.content) for m in messages)} 字符：")
    for m in messages:
        print(f"      [{m.role:<9}] {m.content[:46]}")
    print()

    reply = llm.complete(messages).text          # 模型看到的 = 整个 messages
    messages.append(Message.assistant(reply))    # 它的回复存进历史
    messages.append(Message.tool_result("calc", "6*7 = 42"))

print("★ 结论：模型没有记忆。")
print("  它每次看到的都是我们重新发过去的整段历史。")
print("  所以「Agent 的记忆」= 一个我们自己维护的列表。")
print()
print("这直接引出后面两章：")
print("  · 历史无限增长 -> 上下文窗口会爆     -> 第 05 章 记忆与上下文工程")
print("  · 每次都重发全部历史 -> 成本平方增长 -> 第 12 章 成本优化")''')

    nb.md("""现在所有零件都齐了：

| 零件 | 是什么 |
|---|---|
| 解析器 `extract_call` | 从模型输出里取出 (工具名, 参数) |
| 工具表 `TOOLS` | 名字 → 函数 |
| 消息列表 `messages` | 按顺序攒对话历史 |

**把它们串起来就是一个 Agent。**""")

    # ==================================================================
    section(nb, "⑥", "串起来：完整的 MiniAgent")

    nb.md("""### 联动：数据怎么流动

```
    messages: list[Message]        <-- 历史（Agent 的记忆）
            │
            │ ① 整段发给模型
            ▼
      llm.complete(messages) ──► LLMResponse
            │                         │
            │                         ▼ .text = 模型输出的一段文本
            │              '我要算。 <call>{"name":"calc","args":{...}}</call>'
            │                         │
            │                         ▼ ② extract_call() 正则解析
            │                 ("calc", {"expr": "(12+8)*3/4"})
            │                         │
            │                         ▼ ③ 查 TOOLS 并执行
            │                 TOOLS["calc"](expr="(12+8)*3/4") = "= 15"
            │                         │
            │                         ▼ ④ 包装成消息
            └── messages.append(Message.tool_result("calc", "= 15"))
                                      │
                                      └─► 回到 ①，再来一圈
```

### 完整代码（下面这一整格可以直接单独运行）""")

    nb.code('''# 单独可运行：完整的 MiniAgent（所有零件都在这一格里）
import sys, pathlib, re, json, ast, math
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message
from core.mock_llm import ScriptedLLM


# ---------- 零件 1：解析器 ----------
CALL_RE = re.compile(r"<call>(\\{.*?\\})</call>", re.S)
FINAL_RE = re.compile(r"Final Answer\\s*[:：]\\s*(.*)", re.S)
THOUGHT_RE = re.compile(r"Thought\\s*[:：]\\s*(.*?)(?=\\n|$)", re.S)

def extract_thought(text):
    """取出 Thought 那一段。参数 text 是模型输出，返回 str（找不到返回空串）。"""
    m = THOUGHT_RE.search(text)
    return m.group(1).strip() if m else ""

def extract_answer(text):
    """取出 Final Answer。参数 text 是模型输出，返回 str（没有则空串）。"""
    m = FINAL_RE.search(text)
    return m.group(1).strip() if m else ""

def extract_call(text):
    """取出工具调用。返回 (工具名, 参数字典)；取不到返回 None。"""
    m = CALL_RE.search(text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict) or "name" not in obj:
        return None
    return obj["name"], obj.get("args", {})


# ---------- 零件 2：工具（普通函数）----------
def calc(expr):
    """计算数学表达式。参数 expr 是表达式字符串，返回结果字符串。"""
    BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant): return n.value
        if isinstance(n, ast.BinOp): return BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp): return -ev(n.operand)
        raise ValueError(f"不支持的语法: {type(n).__name__}")
    v = ev(ast.parse(expr, mode="eval"))
    return f"{expr} = {int(v) if isinstance(v, float) and v.is_integer() else v}"

def lookup_order(order_id):
    """查订单。参数 order_id 形如 A1001，返回描述字符串，查不到抛 ValueError。"""
    t = {"A1001": "订单 A1001：已发货，顺丰 SF1234567890"}
    k = order_id.upper()
    if k not in t:
        raise ValueError(f"订单 {k} 不存在。已知：{sorted(t)}")
    return t[k]

# ---------- 零件 3：工具表 ----------
TOOLS = {"calc": calc, "lookup_order": lookup_order}

# ---------- 零件 4：系统提示词 ----------
SYSTEM = (
    "你可以调用这些工具：" + ", ".join(TOOLS) + "\\n"
    "需要工具时严格输出：\\n"
    "Thought: <简短推理>\\n"
    '  <call>{"name": "工具名", "args": {...}}</call>\\n'
    "可以回答时输出：\\n"
    "Thought: <简短推理>\\n"
    "Final Answer: <答案>"
)


# ---------- 零件 5：Agent 本体 ----------
class MiniAgent:
    """最小可用 Agent。

    参数
      llm       : 任何有 .complete(messages) -> LLMResponse 的东西
      tools     : dict，工具名 -> 普通 Python 函数
      max_steps : int，循环圈数上限。必须设，否则模型卡住时无限循环
    """

    def __init__(self, llm, tools, max_steps=6):
        self.llm, self.tools, self.max_steps = llm, tools, max_steps

    def run(self, question):
        """跑一轮对话。参数 question 是用户问题，返回 (答案, 轨迹, 停机原因)。"""
        messages = [Message.system(SYSTEM), Message.user(question)]
        trace, stop_reason = [], "max_steps"

        for i in range(1, self.max_steps + 1):
            reply = self.llm.complete(messages).text      # ① 想
            thought = extract_thought(reply)
            answer = extract_answer(reply)
            call = extract_call(reply)
            rec = {"step": i, "thought": thought, "action": call, "answer": answer}
            trace.append(rec)

            if answer and not call:                       # 它答完了
                messages.append(Message.assistant(reply))
                stop_reason = "final_answer"
                break

            if not call:                                  # 既没动作也没答案
                messages.append(Message.assistant(reply))
                messages.append(Message.user(
                    "你的输出无法解析。请严格用 "
                    '<call>{"name":...,"args":{...}}</call> 或 Final Answer: ...'
                ))
                continue

            name, args = call                             # ② 做
            messages.append(Message.assistant(reply))
            if name not in self.tools:                    # 幻觉工具
                obs = f"错误：工具 {name!r} 不存在。可用工具：{list(self.tools)}"
            else:
                try:
                    obs = f'<result tool="{name}">{self.tools[name](**args)}</result>'
                except Exception as exc:                  # 工具失败也是结果
                    obs = f"错误：{type(exc).__name__}: {exc}"
            rec["observation"] = obs

            messages.append(Message.tool_result(name, obs))   # ③ 记

        final = next((t["answer"] for t in reversed(trace) if t.get("answer")), "")
        return final, trace, stop_reason


# ---------- 跑一次 ----------
SCRIPT = [
    'Thought: 先算数。\\n<call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</call>',
    'Thought: 再查订单。\\n<call>{"name": "lookup_order", "args": {"order_id": "A1001"}}</call>',
    'Thought: 信息齐了。\\nFinal Answer: (12+8)*3/4 = 15；订单 A1001 已发货，SF1234567890。',
]

answer, trace, why = MiniAgent(ScriptedLLM(SCRIPT), TOOLS, max_steps=6).run(
    "算一下 (12+8)*3/4，并告诉我订单 A1001 到哪了"
)

for rec in trace:
    print(f"--- 第 {rec['step']} 圈 ---")
    print(f"  想   : {rec['thought']}")
    if rec.get("action"):
        print(f"  做   : 调用 {rec['action'][0]}，参数 {rec['action'][1]}")
    if rec.get("observation"):
        print(f"  看   : {str(rec['observation'])[:60]}")
    if rec.get("answer"):
        print(f"  答   : {rec['answer']}")
print()
print("最终答案 :", answer)
print("停机原因 :", why)''')

    nb.md("""**这就是 Agent 最核心的一幕。** 模型单独做不到的任务，被拆成两次工具调用，
然后合成一个答案。机制朴素到令人失望：一个 `while` 循环 + 一个记录历史的列表。

现在跑通了。但还有两件事必须处理 —— 否则它不能用于真实场景。""")

    # ==================================================================
    section(nb, "⑦", "循环停不下来怎么办？—— 四道保险")

    nb.md("""### 现在卡在哪

上面的循环靠 `max_steps` 硬性截断。如果模型陷入"复读"（一直想调同一个工具），
它会白白跑完 6 圈，烧 6 次模型调用的钱。

如果 `max_steps` 设成 1000 呢？那就烧 1000 次。**没有上限就更糟 —— 无限循环。**

### 所以我需要「识别异常循环并主动打断」的机制

一共四道保险：

| 停机原因 | 触发条件 | 性质 |
|---|---|---|
| `final_answer` | 模型给出了 `Final Answer` | ✅ 正常结束 |
| `max_steps` | 步数用完 | 🛡 保护 |
| `loop_detected` | 同样的动作反复出现 | 🛡 保护 |
| `parse_failed` | 模型输出连续解析不了 | 🛡 保护 |
| `error` | 模型调用连续失败 | ❌ 故障 |

**新手只关心第一种。老手知道后四种才是能不能上线的分水岭。**

### 先亲眼看看"停不下来"是什么样

`core/mock_llm.py` 里提供了一个 `LoopingLLM`：它永远返回同一个工具调用。""")

    nb.code('''# 单独可运行：死循环演示
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message
from core.mock_llm import LoopingLLM

# LoopingLLM 是什么：永远返回同一个工具调用的假模型
probe = LoopingLLM(action="calc", args={"expr": "1+1"})
print("LoopingLLM 每次都说：")
print("   ", probe.complete([Message.user("随便问")]).text.replace("\\n", " ")[:64])
print()

def run_with_limit(max_steps):
    """跑一个循环，返回实际跑了几圈。用来对比不同上限。"""
    llm = LoopingLLM()
    messages = [Message.system("用 <call>{...}</call> 调工具"), Message.user("问")]
    for i in range(1, max_steps + 1):
        messages.append(Message.assistant(llm.complete(messages).text))
        messages.append(Message.tool_result("calc", "1+1 = 2"))
    return max_steps

for limit in (3, 5, 8):
    print(f"  max_steps={limit} -> 跑了 {run_with_limit(limit)} 圈才停")

print()
print("★ 如果没有 max_steps，这段代码会一直跑到你没钱为止。")
print("  一个提示词的 bug 就足以烧掉一整天的 API 额度 —— 真实发生过。")
print()
print("★ 但只看步数上限不够：5 圈全白跑也是浪费。")
print("  更好的做法是识别「重复动作」，主动打断并提醒模型。")''')

    nb.md("""### 框架版怎么做的：动作指纹去重

思路很简单：**把每次工具调用变成一个字符串指纹，数它出现了几次。**

```python
# 指纹 = 工具名 + 参数的规范 JSON（sort_keys 保证顺序无关）
sig = f'{name}({json.dumps(args, sort_keys=True)})'
# 例如 'calc({"expr": "1+1"})'

# 同一个指纹出现超过 repeat_limit 次 → 往历史里插一条提醒
messages.append(Message.user(
    f"检测到重复动作 {sig} 已出现 {n} 次。"
    "请停止重复调用，改用其他方法或直接给出 Final Answer。"
))
```

关键点：**不是直接停机，而是先提醒模型。** 因为模型可能只是没意识到自己在复读；
提醒之后它往往会换方法。只有提醒了还继续重复，才真正停机。

`core/agent.py` 里的 `Agent` 就是这么做的（`_call_history` + `repeat_limit`）。""")

    # ==================================================================
    section(nb, "⑧", "工具报错了怎么办？")

    nb.md("""### 现在卡在哪

工具会失败。三种典型情况：

| 失败 | 例子 |
|---|---|
| 模型梦游，编了一个不存在的工具 | 它输出 `name: "search_web"`，但我们没有这个工具 |
| 参数不对 | 它传了 `{"exp": "1+1"}`，但函数要的是 `expr` |
| 工具内部业务异常 | 订单 `Z9999` 不存在，`lookup_order` 抛 `ValueError` |

### 所以我需要「让失败变成结果，而不是异常」

理由：**Agent 是永不放弃的系统。** 工具失败只是一次不成功的尝试，
应该给模型机会自救（换工具、改参数、或者如实告诉用户）。

### 两种做法的对比

```
❌ 抛异常：  calc 参数错 -> 程序崩 -> 用户看到 500，前面全白跑
✅ 转成结果：calc 参数错 -> "错误：缺参数 expr，正确用法 calc(expr='1+1')"
             -> 塞回历史 -> 模型看到错误 -> 自己改对 -> 任务继续
```

### 关键设计：失败信息是**写给模型看的**

所以它必须包含三样东西：

1. **哪里错了** —— 不是 `TypeError`，而是"缺少必填参数 expr"
2. **正确用法** —— 让模型能照着改
3. **替代方案** —— 可用工具清单

### 立刻验证""")

    nb.code('''# 单独可运行：四种失败，一个都不许冒出来
def calc(expr):
    """计算表达式（只支持四则）。参数 expr 是字符串，返回结果字符串。"""
    if not isinstance(expr, str):
        raise ValueError(f"expr 必须是字符串，收到 {type(expr).__name__}")
    try:
        return f"{expr} = {eval(expr, {'__builtins__': {}}, {})}"   # 仅演示用
    except ZeroDivisionError:
        raise ValueError("除数不能为 0")
    except Exception as exc:
        raise ValueError(f"表达式无法计算: {exc}")

def lookup_order(order_id):
    """查订单。参数 order_id 形如 A1001，返回描述字符串。"""
    t = {"A1001": "已发货"}
    k = str(order_id).upper()
    if k not in t:
        raise ValueError(f"订单 {k} 不存在。已知：{sorted(t)}")
    return t[k]

TOOLS = {"calc": calc, "lookup_order": lookup_order}


def call_tool(name, args):
    """安全执行工具。**任何情况下都不抛异常**，失败变成一句可读的错误。

    参数 name：工具名字符串
         args：参数字典
    返回    ：str，工具结果或错误说明
    """
    if name not in TOOLS:                     # ① 幻觉工具
        return (f"错误：工具 {name!r} 不存在。"
                f"可用工具：{list(TOOLS)}。请换一个，或直接给出 Final Answer。")
    try:
        return str(TOOLS[name](**args))
    except TypeError as exc:                  # ② 参数写错（名字错/缺参数）
        import inspect
        params = list(inspect.signature(TOOLS[name]).parameters)
        return f"错误：参数不对（{exc}）。该工具需要参数：{params}"
    except Exception as exc:                  # ③ 工具内部业务异常
        return f"错误：{type(exc).__name__}: {exc}"


print("四种情况，逐个看它返回什么：")
for name, args in [
    ("calc",         {"expr": "1+1"}),          # 正常
    ("search_web",   {"q": "天气"}),             # 幻觉工具
    ("calc",         {"exp": "1+1"}),            # 参数名写错
    ("lookup_order", {"order_id": "Z9999"}),     # 业务异常（订单不存在）
]:
    print(f"  调用 {name}({args})")
    print(f"    -> {call_tool(name, args)}")

print()
print("★ 四种情况都没有抛异常。")
print("  而且每条错误信息都包含「哪里错了 + 该怎么办」—— 模型看到就能自救。")''')

    nb.md("""### 现在和框架版对比一下

我们手写的 `MiniAgent` 和 `core/agent.py` 里的 `Agent` **结构完全一样**，
只是框架版补上了那些"让它别崩"的工程细节。""")

    nb.code('''# 单独可运行：框架版 Agent
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import Agent
from core.mock_llm import RuleBasedLLM

result = Agent(llm=RuleBasedLLM(), max_steps=6, verbose=False).run("计算 (12+8)*3/4")

print("框架版返回的对象（AgentResult）字段：")
print("  .answer       :", result.answer)
print("  .stop_reason  :", result.stop_reason)
print("  .llm_calls    :", result.llm_calls)
print("  .total_tokens :", result.total_tokens)
print("  .elapsed_ms   :", round(result.elapsed_ms, 1))
print("  .steps        :", len(result.steps), "圈")
print()
print("第一圈的记录（StepRecord）字段：")
s = result.steps[0]
for field in ("index", "thought", "tool_calls", "observations", "llm_ms", "tokens"):
    val = getattr(s, field)
    if isinstance(val, list):
        val = [str(v)[:34] for v in val]
    print(f"  .{field:<14}: {str(val)[:56]}")
print()
print("想查每个字段什么意思：explain(AgentResult)  /  explain(StepRecord)")''')

    nb.md("""### 框架版比手写版多了什么

| # | 能力 | 为什么必须有 |
|---|---|---|
| 1 | 解析器容忍 5 种畸形格式 | 真实模型输出很脏（第 03 章展开） |
| 2 | 解析失败有重试上限 | 否则模型写不对时无限烧钱 |
| 3 | 模型调用带指数退避重试 | 网络抖动不该让整轮任务失败 |
| 4 | 重复动作检测 | 发现复读主动提醒，而不是干等 |
| 5 | 上下文保护（超长历史折叠） | 防止撑爆上下文窗口 |
| 6 | 完整轨迹记录 | 出错时你唯一能依赖的东西 |
| 7 | 工具审批钩子 | 高危操作先问人（第 11 章） |

**框架的价值在这些工程细节，不在循环本身。** 循环你现在已经会写了。""")

    # ==================================================================
    section(nb, "⑨", "常见坑汇总")

    pitfall_table(nb, [
        ("没有 `max_steps`", "模型卡住时无限循环，烧钱烧时间", "永远设上限，默认 6~10"),
        ("用 `eval` 算表达式", "提示词注入可执行任意代码", "`ast` 白名单"),
        ("工具调用忘写 `**args`", "`TOOLS[name](args)` 传进去的是整个字典",
         "必须 `TOOLS[name](**args)`"),
        ("工具异常向上抛", "整轮任务崩溃，前面全白跑", "兜底 `except` -> 结构化结果"),
        ("每圈重新创建 `messages`", "历史丢失，模型反复问同样的问题", "历史列表在循环**外**创建"),
        ("`re.search` 结果不判空", "没匹配上返回 `None`，`.group()` 抛 AttributeError",
         "先 `if not m: return None`"),
        ("`re.compile` 忘了 `re.S`", "跨行的模型输出匹配不到", "Agent 场景几乎必加 `re.S`"),
        ("`json.loads` 不包 try", "模型把 JSON 写坏时整个程序崩", "捕获 `JSONDecodeError`"),
        ("只看最终答案", "出错了不知道错在哪一步", "记录每一步的轨迹"),
    ])

    summary(nb, [
        "**Agent = 一个 while 循环 + 一个会调工具的模型 + 一个能记住历史的列表。**",
        "**模型没有记忆** —— 它每次看到的都是我们重新发过去的整段历史。",
        "**`max_steps` 不是可选项。** 它是唯一能兜住模型犯傻的机制。",
        "**工具失败要变成观察结果，不是异常。** 错误信息是写给模型看的下一条上下文。",
        "**执行权在我们手里。** 模型只负责「说」它想调什么（第 00 章讲过）。",
        "**模型给的参数是不可信输入** —— 所以用 `ast` 而不是 `eval`（第 02 章会系统化这件事）。",
    ], "第 02 章会把「工具」从「一个普通函数」升级成「带契约的规格」："
       "参数校验、路径沙箱、结果截断 —— 因为模型给的参数既可能写错，也可能恶意。")

    exercises(nb, [
        ("**给 `MiniAgent.run()` 加重复动作检测。**\n\n"
         "记录每次工具调用的指纹（`name + json.dumps(args, sort_keys=True)`），"
         "同一个指纹出现超过 2 次时，往历史里插一条提醒。\n\n"
         "然后跑 `LoopingLLM` 验证：提醒有没有出现在它的上下文里？",
         "指纹就是 `f\"{name}({json.dumps(args, sort_keys=True)})\"`。\n\n"
         "插提醒的方法：`messages.append(Message.user(\"提醒内容\"))`。\n"
         "参考 `core/agent.py` 里的 `_call_history` 和 `repeat_limit`。"),

        ("**去掉 `max_steps`，观察后果。**\n\n"
         "把 `for i in range(1, self.max_steps + 1)` 改成 `while True`，"
         "用 `LoopingLLM` 跑一次。\n\n"
         "⚠️ 记得先设个计数器保护自己（比如跑到 200 圈就 break）。",
         "目的是让你对「没有护栏」有体感，不是真把机器跑挂。\n\n"
         "打印一下：如果不是上限保护，它本来会跑多少圈。"),

        ("**加一道「总耗时」护栏。**\n\n"
         "除了限制步数，再限制整轮任务的总耗时（比如 0.5 秒）。"
         "超时后停机，并在答案里说明「因超时未完成，已完成的部分是……」。",
         "`import time`；循环前 `t0 = time.perf_counter()`；每圈检查"
         "`time.perf_counter() - t0 > 0.5`。\n\n"
         "这是第 13 章「超时降级」的雏形：宁可给部分结果 + 说明，也不能无限等。"),

        ("**让工具报错信息更像「写给模型看的」。**\n\n"
         "现在 `call_tool` 在参数名写错时返回的是 Python 原始报错。"
         "改成包含三样：哪里错了 + 正确用法 + 可用替代。\n\n"
         "验证：故意传错参数名，看返回的字符串能不能照着改对。",
         "`inspect.signature(TOOLS[name])` 能拿到正确参数名列表。\n\n"
         "对比：`TypeError: calc() got an unexpected keyword argument`"
         "和「缺少必填参数 expr。正确用法：calc(expr='1+1')」—— 哪个模型能看懂？"),

        ("**注入一个会撒谎的模型。**\n\n"
         "写一个假模型，让它**不调用工具**，直接编一个订单状态返回。"
         "观察 Agent 会不会发现。\n\n"
         "然后修改系统提示词，加入「订单状态必须来自 lookup_order 的真实返回」，"
         "再看能否拦住它。",
         "假模型只要继承 `LLM` 并实现 `_complete()`：\n"
         "```python\n"
         "class LyingLLM(LLM):\n"
         "    def _complete(self, messages, **kwargs):\n"
         "        return LLMResponse(text='Final Answer: 订单 A1001 已发货')\n"
         "```\n\n"
         "你会发现问题：光靠提示词很难 100% 拦住它 —— 这正是第 07 章（反思/验证器）"
         "和第 11 章（护栏）要解决的。"),
    ])

    checkpoint(nb, "01")

    return nb
