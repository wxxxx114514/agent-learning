"""第 02 章 · 工具系统与 JSON Schema —— Notebook 内容（逐步推进版）。

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


def build_02() -> Notebook:
    """第 02 章 · 工具系统与 JSON Schema（逐步推进版）。"""
    nb = Notebook("第 02 章 · 工具系统与 JSON Schema")

    header(
        nb, "02", "工具系统与 JSON Schema",
        "工具 = `函数签名（给模型看）` + `参数校验（保护自己）` + `结果序列化（给模型读）`。\n"
        "一句话：**模型给的参数是不可信输入** —— 校验必须发生在执行之前。",
    )

    objectives(nb, [
        "说清「裸调工具」的三个致命问题，以及它们各自怎么被兜住",
        "写出一份**工具规格**：名字 + 描述 + JSON Schema + 函数",
        "实现一个 JSON Schema 子集校验器，并解释为什么要「一次给全部错误」",
        "解释 `bool` 是 `int` 子类带来的校验陷阱，并知道怎么修",
        "说明为什么 `eval` 在 Agent 里是致命的，以及 AST 白名单怎么替代它",
        "说明路径穿越怎么防（为什么不能用字符串包含判断）",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

第 01 章结尾留了一个隐患。我们当时是这么调工具的：

```python
obs = f'<result tool="{name}">{self.tools[name](**args)}</result>'
```

这一行看起来人畜无害，实际上有三个坑，而且第三个最阴险。
本章按顺序拆：

```
① 先看三个坑真实发生的样子（可运行，不是讲故事）
② 第一个坑：参数名写错     → 需要「参数校验」
③ 第二个坑：参数是恶意的   → 需要「白名单」而不是黑名单
④ 第三个坑：工具自己崩了   → 需要「把异常变成结果」
⑤ 把上面三件事打包成「工具规格」
⑥ 一个反直觉结论：工具不是越多越好
```

每个知识点都出现在**你正好需要它**的时候。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `json.dumps` | 标准库 `json` | Python 对象 → JSON 字符串 | `json.dumps(obj, ensure_ascii=False)` |
| `json.loads` | 标准库 `json` | JSON 字符串 → Python 对象 | → `dict` / `list` |
| `ast.parse` | 标准库 `ast` | 源码文本 → 语法树 | `ast.parse(表达式, mode="eval")` |
| `ast.walk` | 标准库 `ast` | 遍历语法树所有节点 | 产生节点流 |
| `inspect.signature` | 标准库 `inspect` | 读函数的参数与类型注解 | `sig.parameters` → 参数名到参数的映射 |
| `re.search` | 标准库 `re` | 按正则找第一个匹配 | → `Match` 或 `None` |
| `Path.resolve` | 标准库 `pathlib` | 把路径解析成绝对路径 | → `Path` |
| `math` | 标准库 | `sqrt` / `log` / `floor` / `ceil` | `math.sqrt(16)` → `4.0` |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `ToolSpec` | `core.tool` | 工具的说明书（名字/描述/schema/函数/标签/是否需审批） |
| `ToolResult` | `core.tool` | 工具执行结果（`.ok` / `.content` / `.error` / `.elapsed_ms`） |
| `ToolRegistry` | `core.tool` | 工具注册表：注册、查找、校验、执行 |
| `validate_schema` | `core.tool` | JSON Schema 子集校验器，返回错误信息列表 |
| `build_default_registry` | `core.tool` | 造一套内置工具（calc / count_words / lookup_order / 读写文件） |

### 随时可查

```python
explain(ToolSpec)               # 字段逐个说明
explain(build_default_registry) # 参数含义 + 例子
explain()                       # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "先看三个坑真实发生的样子")

    nb.md("""### 现在卡在哪

第 01 章里我们这样调工具：

```python
self.tools[name](**args)     # args 是模型给的参数字典
```

**这一行把"模型的输出"直接当成了"可信的程序输入"。**
三个坑按严重程度递增：

| 坑 | 谁造成的 | 后果 |
|---|---|---|
| 参数名写错 | 模型幻觉 | 报错信息模型看不懂，反复试错烧钱 |
| 参数是恶意的 | 用户（提示词注入） | 执行任意代码 / 读任意文件 |
| 工具自己崩了 | 你自己的代码有 bug | 整轮任务崩溃，前面全白跑 |

### 先亲眼看一遍

第一和第三个坑下面演示。**第二个坑（恶意参数）留到 ③**，因为它需要先讲清"为什么黑名单不够"。""")

    nb.code('''# 单独可运行：坑 1 和 坑 3 的真实样子
# ---- 坑 1：模型把参数名写错了 ----
def calc(expr: str) -> str:
    """一个正常的工具函数。参数 expr 是表达式字符串。"""
    return f"{expr} = 42"

print("【坑 1】模型给错参数名（它写了 expression，但函数要的是 expr）：")
try:
    calc(expression="1+1")          # 模型幻觉出来的参数名
except TypeError as exc:
    print("   抛出的原始异常：", exc)
print("   ^ 这个信息回灌给模型，它基本看不懂。")
print("     模型需要的是：正确用法 calc(expr='1+1')")
print()

# ---- 坑 3：工具自己崩了 ----
def lookup_order(order_id: str) -> str:
    """查订单。参数 order_id 形如 A1001。"""
    table = {"A1001": "已发货"}
    return table[order_id.upper()]      # 查不到就 KeyError

print("【坑 3】工具内部抛异常（订单不存在）：")
try:
    lookup_order("Z9999")
except KeyError as exc:
    print("   抛出的原始异常：", type(exc).__name__, exc)
print("   ^ 如果这里不接住，整个 Agent 循环就崩了 ——")
print("     用户看到 500，而前面几圈的工作全部白做。")''')

    nb.md("""### 结论：需要三样东西

| 坑 | 需要什么 |
|---|---|
| 参数名写错 | **参数校验** —— 在执行之前检查参数是否符合约定 |
| 参数恶意 | **白名单** + 沙箱（第 ③ 节） |
| 工具崩了 | **异常兜底** —— 把异常变成一条可读的结果（第 ④ 节） |

这三个东西合起来，就是我们接下来要造的"工具系统"。先解决第一个。

---

### 参数校验需要一个"约定"

要校验，得先说清"合法长什么样"。用自然语言描述（"需要一个字符串表达式"）机器没法检查。

### 所以我需要一个「机器能读的参数契约」

业界通用的那个约定叫 **JSON Schema** —— 用 JSON 描述 JSON 该怎么写。

我们只用到它的一个子集，四个关键字就够：

```python
{
    "type": "object",                    # 整个参数是一个对象（字典）
    "properties": {                      # 每个参数长什么样
        "expr": {"type": "string"}
    },
    "required": ["expr"],                # 哪些参数必须有
    "additionalProperties": False        # ★ 拒绝一切未定义参数
}
```

逐个说清楚：

| 关键字 | 作用 | 漏了会怎样 |
|---|---|---|
| `type` | 参数的类型（`string` / `integer` / `number` / `boolean` / `array` / `object`） | 没法判断类型对不对 |
| `properties` | 每个参数的说明 | 模型不知道要传什么 |
| `required` | 必填清单 | 模型漏填时你只能等函数报 `TypeError` |
| `additionalProperties: False` | **拒绝一切未定义参数** | 模型幻觉出的 `unit`、`currency` 会被静默吞掉，行为不可预测 |

> 最后一条最容易被忽视，也最值钱。模型非常喜欢"多加一个参数显得自己很懂"——
> 比如算数时顺手传 `unit="元"`。不开这个开关，`**args` 会把多余参数静默吃掉；
> 开了，模型会收到明确的纠正信息。

### 立刻写一个校验器

**关键设计：一次给全部错误，而不是遇到第一个就返回。**
因为每次回灌都要花一次模型调用。一次给全，模型一次改对；
一次给一个，模型改完这个又错那个。""")

    nb.code('''# 单独可运行：JSON Schema 子集校验器
def validate_schema(value, schema, path="$"):
    """校验 value 是否符合 schema。

    参数 value ：要被校验的值（通常是参数字典）
         schema：JSON Schema 字典
         path  ：错误信息里的路径前缀，用于定位嵌套结构（默认 $）
    返回      ：错误信息列表（**空列表 = 通过**）
    """
    errors = []
    if not schema:
        return errors

    # ---- 类型检查 ----
    TYPE_MAP = {
        "string": (str,), "integer": (int,), "number": (int, float),
        "boolean": (bool,), "array": (list, tuple), "object": (dict,),
        "null": (type(None),),
    }
    expected = schema.get("type")
    if expected:
        names = expected if isinstance(expected, list) else [expected]
        py_types = []
        for n in names:
            py_types.extend(TYPE_MAP.get(n, ()))
        if py_types:
            ok = isinstance(value, tuple(py_types))
            # ★★ 这一行是整章的隐藏重点，后面单独讲
            if ok and bool not in py_types and isinstance(value, bool):
                ok = False
            if not ok:
                errors.append(
                    f"{path}: 期望 {expected}，实际是 {type(value).__name__}（值={value!r}）"
                )
                return errors      # 类型不对，后面的约束没意义

    # ---- 取值约束 ----
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 必须是 {schema['enum']} 之一，实际 {value!r}")

    # ---- 字符串约束 ----
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度至少 {schema['minLength']}，实际 {len(value)}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: 长度最多 {schema['maxLength']}，实际 {len(value)}")
        if "pattern" in schema:
            import re
            if not re.search(schema["pattern"], value):
                errors.append(f"{path}: 不匹配 {schema['pattern']!r}（值={value!r}）")

    # ---- 数值约束 ----
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 不能小于 {schema['minimum']}，实际 {value}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 不能大于 {schema['maximum']}，实际 {value}")

    # ---- 数组元素 ----
    if isinstance(value, (list, tuple)) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))

    # ---- 对象约束 ----
    if isinstance(value, dict):
        props = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺少必填参数 {key!r}")
        for key, sub in props.items():
            if key in value:
                errors.extend(validate_schema(value[key], sub, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extra = [k for k in value if k not in props]
            if extra:
                errors.append(f"{path}: 出现未定义参数 {extra}，允许的只有 {list(props)}")
    return errors


# ---- 试一下 ----
SCHEMA = {
    "type": "object",
    "properties": {"expr": {"type": "string", "minLength": 1}},
    "required": ["expr"],
    "additionalProperties": False,
}

print("合法参数：", validate_schema({"expr": "1+1"}, SCHEMA), " <- 空列表 = 通过")
print()
print("一次给全部错误（这就是设计目标）：")
for e in validate_schema({"exp": "1+1", "unit": "元"}, SCHEMA):
    print("   -", e)
print()
print("类型错误：", validate_schema({"expr": 2}, SCHEMA))''')

    nb.md("""### 结果说明什么

- 校验器返回**错误列表**，空列表表示通过 —— 调用方不用处理异常
- 一次返回全部错误：`缺少必填参数 expr` 和 `出现未定义参数 ['exp']` 同时给出
- 每个错误都带 `path`（`$` 是根，嵌套会拼成 `$.order_id`）——
  嵌套结构里没有这个定位，模型不知道该改哪里

现在进入本章最值得单独讲的一个陷阱。""")

    # ==================================================================
    section(nb, "②", "一个 `bool` 引发的血案")

    nb.md("""### 现在卡在哪

上面的校验器里有一行写得很奇怪：

```python
if ok and bool not in py_types and isinstance(value, bool):
    ok = False
```

**为什么要对 `bool` 特殊处理？** 因为 Python 里有一个反直觉的事实：""")

    nb.code('''# 单独可运行：bool 是 int 的子类
print("Python 里最反直觉的继承关系之一：")
print()
print("   isinstance(True, int)   =", isinstance(True, int))
print("   isinstance(False, int)  =", isinstance(False, int))
print("   isinstance(True, float) =", isinstance(True, float))
print("   issubclass(bool, int)   =", issubclass(bool, int))
print()
print("意思就是：True 在类型检查眼里「是一个整数」。")
print()

# 演示它会造成的真实问题
TYPE_MAP = {"integer": (int,), "string": (str,)}

def naive_check(value, expected_type):
    """不做 bool 特判的校验 —— 看看会漏掉什么。"""
    return isinstance(value, TYPE_MAP[expected_type])

def correct_check(value, expected_type):
    """做了 bool 特判的校验。"""
    py_types = TYPE_MAP[expected_type]
    ok = isinstance(value, py_types)
    if ok and bool not in py_types and isinstance(value, bool):
        ok = False
    return ok

print("如果有人给 integer 参数传了 True：")
print(f"   {'朴素校验':<10}: {'通过（漏了！）' if naive_check(True, 'integer') else '拦住'}")
print(f"   {'正确校验':<10}: {'通过' if correct_check(True, 'integer') else '拦住 ✅'}")
print()
print("★ 后果：模型写 <call>{\\"name\\": \\"calc\\", \\"args\\": {\\"expr\\": true}}</call>，")
print("  朴素校验会放行，然后 calc(expr=True) 一路执行下去 ——")
print("  校验形同虚设。")''')

    nb.md("""### 结果说明什么

| 写法 | `{"expr": true}` 会被放行吗 |
|---|---|
| 直接 `isinstance(value, (int, float))` | **会**（因为 `bool` 是 `int` 的子类） |
| 加上 `bool not in py_types and isinstance(value, bool)` 特判 | 不会 ✅ |

这一行如果不写，你的校验器就有了一个洞。
**这种细节就是"手写一遍"的价值** —— 用现成的库你不会知道它替你挡了什么。

> 顺便：这个坑不只出现在校验器里。任何时候你写"是不是数字"的判断，
> 都要想一下"如果传进来是 `True` 呢"。

现在第一个坑（参数写错）解决了。下一个：**如果参数不是写错，而是故意的呢？**""")

    # ==================================================================
    section(nb, "③", "为什么黑名单没用：从 eval 说起")

    nb.md("""### 现在卡在哪

校验器能拦住"类型不对"、"缺参数"。但如果模型给了一个**类型完全正确、
内容却恶意**的参数呢？

```
<call>{"name": "calc", "args": {"expr": "__import__('os').system('删库')"}}</call>
```

`expr` 确实是字符串，校验通过。然后我们的计算工具要拿它去算 —— 怎么算？

### 一个看似方便的答案，和一个致命的后果

Python 有个内置函数 `eval(字符串)`，能把字符串当表达式求值。
用它实现计算器只要一行。

**但模型输出是不可信输入。** 用户可以通过提示词注入，让模型输出这样的"表达式"。

### 先亲眼看看 `eval` 有多危险""")

    nb.code('''# 单独可运行：eval 的危险（只做无害演示，不执行破坏性命令）
payload = "__import__('os').getcwd()"

print("如果用 eval 实现计算器：")
print("   代码：eval(payload)")
print("   payload：", repr(payload))
print()
result = eval(payload)          # 只读当前目录，无害
print("   执行结果：", result)
print()
print("★ 看到了吗 —— 我们只是想「算个数」，结果它执行了系统调用。")
print()
print("真实攻击长这样（这里**故意不执行**）：")
for evil in ["__import__('os').system('del /f /q *')",
             "open('C:/Users/xxx/.ssh/id_rsa').read()",
             "__import__('subprocess').run(['rm', '-rf', '/'])"]:
    print("   ", evil)
print()
print("★ 为什么这是 Agent 特有的严重问题？")
print("   普通程序里，eval 的输入来自你自己的代码；")
print("   而 Agent 里，eval 的输入来自**模型输出**，")
print("   模型输出又能被用户通过提示词注入间接控制 ——")
print("   等于把 shell 交给了陌生人。")''')

    nb.md("""### 结论：不能用黑名单，要用白名单

一个自然的想法是"把危险的关键字过滤掉"（黑名单）：

```python
# ❌ 黑名单：永远堵不完
if any(bad in expr for bad in ["import", "eval", "exec", "open", "__", "os"]):
    raise ValueError("危险表达式")
```

**为什么黑名单一定失败？** 因为绕过方式无穷多：
大小写变形、Unicode 同形字、字符串拼接、编码……你堵一个他换一个。

正确思路是**白名单**：**默认拒绝，只显式允许我认识的东西。**

### 所以我需要一个「能把表达式拆成结构」的工具

标准库 `ast`（抽象语法树）正好干这个：

| 函数 | 作用 | 关键性质 |
|---|---|---|
| `ast.parse(表达式, mode="eval")` | 把字符串**解析**成语法树 | **纯数据结构，不执行任何东西** |
| 节点类型 | 树的每个节点代表一种语法 | `ast.BinOp` 是二元运算、`ast.Call` 是函数调用、`ast.Attribute` 是属性访问…… |

拿到树之后，**我们自己遍历**：只允许白名单里的节点类型，遇到不认识的直接拒绝。

### 立刻用一次""")

    nb.code('''# 单独可运行：AST 白名单（默认拒绝，显式允许）
import ast, math

def safe_calc(expr: str) -> str:
    """安全计算数学表达式。

    参数 expr：表达式字符串，例如 (12+8)*3/4
    返回    ：结果字符串，例如 (12+8)*3/4 = 15
    不允许的语法会抛 ValueError
    """
    # ── 白名单之一：允许的二元运算符 ──
    BIN_OPS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a ** b,
    }
    # ── 白名单之二：允许调用的函数 ──
    FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round,
             "floor": math.floor, "ceil": math.ceil}

    def ev(node):
        """递归求值。只有白名单里的节点类型能通过。"""
        if isinstance(node, ast.Expression):        # 顶层容器，剥掉
            return ev(node.body)

        if isinstance(node, ast.Constant):          # 数字字面量
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")

        if isinstance(node, ast.BinOp):             # a + b
            op = BIN_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
                raise ValueError("除数不能为 0")
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("指数过大，拒绝计算（防算力耗尽）")
            return op(left, right)

        if isinstance(node, ast.UnaryOp):           #  -a  /  +a
            if isinstance(node.op, ast.USub):
                return -ev(node.operand)
            if isinstance(node.op, ast.UAdd):
                return ev(node.operand)
            raise ValueError("不支持的一元运算符")

        if isinstance(node, ast.Call):              # sqrt(16)
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
                raise ValueError(f"不允许调用 {getattr(node.func, 'id', '?')}")
            if node.keywords:
                raise ValueError("不支持关键字参数")
            return FUNCS[node.func.id](*[ev(a) for a in node.args])

        # ★ 兜底：其余一切语法都拒绝（属性访问、下标、import、lambda……）
        raise ValueError(f"表达式里出现不允许的语法: {type(node).__name__}")

    value = ev(ast.parse(expr, mode="eval"))        # 只解析，不执行
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{expr} = {value}"


print("正常表达式（白名单内的）：")
for e in ["(12+8)*3/4", "sqrt(16)+1", "2**10", "17 % 5", "-3 + 1"]:
    print(f"   {e:<14} -> {safe_calc(e)}")

print()
print("攻击载荷（全部被拒绝）：")
for bad in ["__import__('os').system('echo 危险')",
            "open('/etc/passwd').read()",
            "(1).__class__.__bases__",
            "[x for x in range(3)]"]:
    try:
        safe_calc(bad)
        print(f"   没拦住: {bad}")
    except ValueError as exc:
        print(f"   已拒绝: {bad[:32]:<34} ({exc})")''')

    nb.md("""### 对照表：白名单 vs `eval`

| 输入 | `eval` | AST 白名单 |
|---|---|---|
| `(12+8)*3/4` | 15 ✅ | 15 ✅ |
| `__import__('os').system(...)` | **真的执行** ❌ | 抛 `ValueError` ✅ |
| `open('/etc/passwd').read()` | **真的读文件** ❌ | 抛 `ValueError` ✅ |
| `(1).__class__.__bases__` | 返回类型元组 ❌ | 抛 `ValueError` ✅ |

现在"表达式注入"解决了。但工具不止算数这一种 —— **文件类工具还有另一个坑**。""")

    # ==================================================================
    section(nb, "④", "文件工具的坑：路径穿越")

    nb.md("""### 现在卡在哪

如果工具有读写文件的能力，模型可以给出这样的参数：

```
<call>{"name": "read_file", "args": {"path": "../../../../etc/passwd"}}</call>
```

这就是**路径穿越**：用 `..` 逃出你划定的工作目录，去读系统的任意文件。

### 一个看起来很对的写法，和一个致命的漏洞

```python
# ❌ 用字符串包含判断
if ".." in path:
    raise ValueError("禁止 ..")
```

**为什么这个一定被绕过？**

| 绕过方式 | 例子 |
|---|---|
| 多加几个点 | `....//` |
| 反斜杠（Windows） | `..\\..\\Windows\\System32` |
| URL 编码 | `%2e%2e%2f` |
| 符号链接 | 一个指向 `/etc` 的软链接 |
| 绝对路径 | 直接写 `C:/Windows/System32/drivers/etc/hosts` |

字符串检查永远输，因为**路径的等价写法是无穷的**。

### 所以我需要一个「把路径解析成唯一形式」的工具

`pathlib.Path.resolve()` —— 它把路径里的 `.`、`..`、符号链接全部解析掉，
得到一个**唯一的绝对路径**。然后我们只做一件事：**比较前缀**。

```python
p = (root / rel).resolve()      # 解析成绝对路径
if not str(p).startswith(str(root.resolve())):
    raise ValueError("拒绝访问工作目录之外的路径")
```

这个判断是**可靠**的，因为它比较的是解析后的规范形式，
不管攻击者用多少个点、什么斜杠、怎么编码，最终都会落到某个绝对路径上。

### 立刻用一次""")

    nb.code('''# 单独可运行：路径穿越防护
import pathlib, shutil

# 造一个临时的"工作目录"来演示。
# ★ 为什么不放在系统临时目录？因为受限环境（沙箱）下那里可能不可写，
#   所以放在当前工作区内部，用完删掉，不留垃圾。
workspace = pathlib.Path.cwd() / ".nb02_sandbox"
shutil.rmtree(workspace, ignore_errors=True)
workspace.mkdir(parents=True, exist_ok=True)
(workspace / "notes.md").write_text("这是工作目录内的合法文件", encoding="utf-8")

def safe_path(rel: str) -> pathlib.Path:
    """把相对路径解析到工作目录内。

    参数 rel：用户/模型给的相对路径字符串
    返回    ：解析后的绝对 Path
    越界时抛 ValueError
    """
    root = workspace.resolve()
    p = (root / rel).resolve()          # ★ 关键：解析成规范绝对路径
    if not str(p).startswith(str(root)):
        raise ValueError(f"拒绝访问工作目录之外的路径: {rel}")
    return p


print("工作目录：", workspace)
print()
print("非法路径（全部被拒绝）：")
for bad in ["../outside.txt",
            "../../../../etc/passwd",
            "....//....//etc/passwd",
            "subdir/../../escape.txt"]:
    try:
        p = safe_path(bad)
        print(f"   没拦住: {bad} -> {p}")
    except ValueError as exc:
        print(f"   已拒绝: {bad:<28} ({exc})")

print()
print("合法路径（正常放行）：")
p = safe_path("notes.md")
print(f"   notes.md -> {p}")
print(f"   内容是：{p.read_text(encoding='utf-8')}")

# 清理演示目录
shutil.rmtree(workspace, ignore_errors=True)
print()
print("★ 注意那条可靠的判断：resolve() 之后比前缀。")
print("  绝不用「字符串包含」判断路径安全性。")''')

    nb.md("""### 还有一个容易忽略的保护：结果截断

工具返回值会被塞进上下文。如果一个工具返回 10MB 日志，**一次调用就能把上下文窗口撑爆**，
后面所有对话都废了。

所以要给每个工具设一个 `max_result_chars`：""")

    nb.code('''# 单独可运行：结果截断
def serialize(raw, max_chars=200):
    """把工具的返回值变成给模型读的字符串，并做长度保护。

    参数 raw      ：工具返回的任意对象
         max_chars：最多保留多少字符
    返回         ：字符串（超长会截断并附提示）
    """
    import json
    if raw is None:
        text = "(空结果)"
    elif isinstance(raw, str):
        text = raw
    elif isinstance(raw, (dict, list, tuple)):
        text = json.dumps(raw, ensure_ascii=False, indent=2, default=str)
    else:
        text = str(raw)

    if len(text) > max_chars:
        text = (text[:max_chars]
                + f"\\n...（结果被截断，原始长度 {len(text)} 字符；请缩小查询范围）")
    return text


huge = "日志行内容\\n" * 3000
out = serialize(huge, max_chars=200)
print("原始长度  :", len(huge), "字符")
print("截断后长度:", len(out), "字符")
print()
print("截断后的尾巴：")
print(out[-90:])
print()
print("★ 截断提示本身也是给模型的信息：它知道结果不完整，可以缩小范围重试。")''')

    nb.md("""现在三个坑都有解法了：

| 坑 | 解法 |
|---|---|
| 参数写错 | JSON Schema 校验（②） |
| 参数恶意（表达式注入） | AST 白名单（③） |
| 参数恶意（路径穿越） | `resolve()` 后比前缀（④） |
| 结果撑爆上下文 | `max_result_chars` 截断（④） |
| 工具自己崩了 | 还没做 —— 下一节 |

但还有一个问题：**这些零件现在散落各处。** 怎么把它们组织起来？""")

    # ==================================================================
    section(nb, "⑤", "打包：把「一个函数」升级成「工具规格」")

    nb.md("""### 现在卡在哪

现在我们有：一个校验器、一个白名单、一个路径检查、一个截断函数，
还有模型需要的"说明书"（名字 + 描述 + schema）。

**散着放的话，每加一个工具都要重新串一遍这些逻辑**，很快就会乱。

### 所以我需要一个「把工具的所有信息装在一起」的结构

用 `dataclass`。一个工具需要装这些东西：

| 要装什么 | 为什么需要 |
|---|---|
| `name` | 模型用它来指定调哪个 |
| `description` | **写给模型看的说明书** —— 决定它会不会选对工具 |
| `parameters` | JSON Schema，给校验器用 |
| `func` | 真正执行的 Python 函数 |
| `tags` | 标签，用于按场景裁剪工具集（⑥ 会讲） |
| `requires_approval` | 高危工具标记（第 11 章会讲） |
| `max_result_chars` | 结果截断长度 |

本项目已经提供了成品：`core.tool.ToolSpec`。先看它长什么样、有哪些字段。""")

    nb.code('''# 单独可运行：看清 ToolSpec 的字段（这就是"工具规格"）
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tool import ToolSpec

print("ToolSpec 的字段（来自 core/tool.py）：")
print()
import dataclasses
for f in dataclasses.fields(ToolSpec):
    default = "" if f.default is dataclasses.MISSING else f"  （默认 {f.default!r}）"
    print(f"   .{f.name:<20}{default}")
print()
print("想查每个字段的详细含义：explain(ToolSpec)")''')

    nb.md("""### 现在写一个完整的工具

下面这一格把前面的所有零件串成一个**完整可用**的工具规格，
并用 `ToolRegistry` 注册、校验、执行。""")

    nb.code('''# 单独可运行：一个完整工具的诞生（规格 + 注册 + 校验 + 执行）
import sys, pathlib, ast, math, json, time
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tool import ToolRegistry, ToolSpec, validate_schema


# ---------- 第一步：写工具函数（就是普通 Python 函数）----------
def calc(expr: str) -> str:
    """计算数学表达式。

    参数 expr：表达式字符串，例如 (12+8)*3/4
    返回    ：结果字符串
    """
    BIN_OPS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
               ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
    FUNCS = {"sqrt": math.sqrt, "abs": abs, "round": round}

    def ev(n):
        if isinstance(n, ast.Expression): return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) \\
                and not isinstance(n.value, bool):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in BIN_OPS:
            return BIN_OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \\
                and n.func.id in FUNCS:
            return FUNCS[n.func.id](*[ev(a) for a in n.args])
        raise ValueError(f"不支持的语法: {type(n).__name__}")

    v = ev(ast.parse(expr, mode="eval"))
    return f"{expr} = {int(v) if isinstance(v, float) and v.is_integer() else v}"


# ---------- 第二步：写说明书（规格）----------
CALC_SPEC = ToolSpec(
    name="calc",
    # ★★ 这一行是**写给模型看的**，不是给人看的注释。
    #    它直接决定模型会不会、以及会不会选对工具。
    description=(
        "计算数学表达式，支持 + - * / 和 sqrt/abs/round。"
        "任何算术问题都必须用它，不要自己心算 —— 心算长表达式容易出错。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "expr": {
                "type": "string",
                "description": "要计算的表达式，例如 (12+8)*3/4",
                "minLength": 1,
            }
        },
        "required": ["expr"],
        "additionalProperties": False,     # ★ 拒绝一切未定义参数
    },
    func=calc,
    tags=["math"],
    max_result_chars=400,                  # 结果截断
)


# ---------- 第三步：注册进注册表 ----------
reg = ToolRegistry()
reg.register(CALC_SPEC)

print("注册成功。注册表里的工具：", reg.names())
print()
print("模型看到的说明书（这段文字就是模型判断「该不该用、怎么用」的全部依据）：")
print()
print(CALC_SPEC.to_prompt_line())
print()
print("可以抄的调用示例：", CALC_SPEC.example_call())''')

    nb.md("""### 注册表怎么安全执行

`ToolRegistry.execute(name, args)` 把前面所有保护串在一起，**任何情况下都不抛异常**：

```
execute(name, args)
   │
   ├─ 工具存在吗？        → 不存在：返回"工具不存在 + 可用清单"
   ├─ 参数符合 schema 吗？ → 不符合：返回"参数校验失败 + 正确用法"
   ├─ 执行函数（沙箱里）   → 抛异常：返回"错误类型 + 信息"
   └─ 序列化 + 截断       → 返回 ToolResult(ok=True, content=...)
```

### 立刻用它试各种输入""")

    nb.code('''# 单独可运行：注册表把各种错误都接住（一个都不抛出来）
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tool import build_default_registry

reg = build_default_registry(ROOT)     # 用框架内置的那套工具
print("内置工具：", reg.names())
print()

CASES = [
    ("正常调用",                 "calc",         {"expr": "(12+8)*3/4"}),
    ("幻觉工具（不存在）",         "search_web",   {"q": "天气"}),
    ("参数名写错",               "calc",         {"exp": "1+1"}),
    ("幻觉参数（多传一个）",       "calc",         {"expr": "1+1", "unit": "元"}),
    ("类型错误（传了 True）",      "calc",         {"expr": True}),
    ("必填参数缺失",             "lookup_order", {}),
    ("格式不合法（订单号）",       "lookup_order", {"order_id": "abc"}),
    ("工具内部业务异常",          "lookup_order", {"order_id": "Z9999"}),
    ("表达式注入",               "calc",         {"expr": "__import__('os').system('x')"}),
    ("路径穿越",                 "read_file",    {"path": "../../../etc/passwd"}),
]

for label, name, args in CASES:
    r = reg.execute(name, args)
    mark = "OK  " if r.ok else "拦住"
    body = (r.content if r.ok else r.error).replace("\\n", " ")
    print(f"  [{mark}] {label:<22} {body[:66]}")

print()
print("★ 十种情况，没有一种抛异常。")
print("★ 而且每条失败信息都是**写给模型看的**：")
print("   「哪里错了 + 正确用法 + 可用替代」三件套齐全，模型看到就能自救。")''')

    nb.md("""### 最后一块拼图：工具崩了怎么办

上面的 `execute()` 已经包含这层保护了：**函数内部抛任何异常，都被转成 `ok=False` 的结果**。

对比一下"包"与"不包"的区别：

| 做法 | 工具内部 `KeyError` 时 |
|---|---|
| 直接 `func(**args)` | 异常冒到 Agent 循环 → 整轮任务崩溃 |
| 包在 `execute()` 里 | 变成 `ToolResult(ok=False, error="KeyError: ...")` → 回灌给模型 → 它自己想办法 |

**关键设计：错误信息必须包含「哪里错了 + 正确用法」。**
Python 原始的 `TypeError: missing 1 required positional argument` 模型基本看不懂；
`缺少必填参数 expr。正确用法：calc(expr="1+1")` 它就能照着改对。""")

    # ==================================================================
    section(nb, "⑥", "反直觉结论：工具不是越多越好")

    nb.md("""### 现在卡在哪

工具系统好用了，自然会想"那我多挂点工具，能力不就更强了？"

**恰恰相反。** 工具说明要占提示词，工具越多：

1. 每个描述在注意力里的权重越低（都变"模糊"了）
2. 功能重叠时模型无法判断该用哪个（`search_web` 还是 `search_doc`？）
3. 提示词变长 → 更贵、更慢、更早撞上上下文上限

### 立刻量一下：多一个工具，代价是多少

关键洞察：工具说明会被**每一圈循环重复发送**，所以成本是**乘出来的**。""")

    nb.code('''# 单独可运行：工具数量 vs 提示词长度（改数字看变化）
FAKE_TOOL_COUNT = 3        # ← 试着改成 20、50，看下面怎么变

BASE_TOOLS = [
    "- calc(expr: string): 计算数学表达式。",
    "- lookup_order(order_id: string): 查订单状态。",
    "- count_words(text: string): 统计字数。",
]
FILLER = [
    f"- tool_{i}(q: string): 查询第 {i} 类数据，返回相关记录。"
    for i in range(FAKE_TOOL_COUNT)
]
lines = BASE_TOOLS + FILLER
prompt = "可用工具：\\n" + "\\n".join(lines)

def estimate_tokens(text):
    """极简 token 估算：中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token。"""
    cjk = sum(1 for ch in text if "\\u4e00" <= ch <= "\\u9fff")
    return cjk + max(1, (len(text) - cjk) // 4)

print(f"工具数量      : {len(lines)}")
print(f"提示词字符数  : {len(prompt)}")
print(f"估算 token    : {estimate_tokens(prompt)}")
print()
print("★ 关键：这段说明会在**每一圈循环里重发一次**。")
print("  假设一个任务要跑 5 圈：")
for n in (3, 10, 20, 50):
    extra = len(BASE_TOOLS) + n
    chars = len("可用工具：\\n" + "\\n".join(
        BASE_TOOLS + [f"- tool_{i}(q: string): 查询第 {i} 类数据，返回相关记录。"
                      for i in range(n)]))
    print(f"     {extra:>2} 个工具 -> 每圈 {chars:>5} 字符 -> 5 圈共 {chars * 5:>6} 字符")
print()
print("真实系统因此在工具超过 ~20 个时先做「工具检索」，只注入相关的 5 个。")''')

    nb.md("""### 工程解法（按性价比排序）

| 手段 | 怎么做 | 框架里对应 |
|---|---|---|
| **按场景裁剪** | 客服场景只挂订单/退款/物流工具 | `ToolRegistry.subset(tags)` |
| **写清使用时机** | description 说明"什么时候该用我"，不只是"我能干什么" | 写 description 时 |
| **工具检索** | 超过 ~20 个时，先检索出相关的 5 个再注入 | 第 12 章会讲 |
| **合并同类** | `search_web` / `search_news` / `search_blog` 合成一个带 `source` 参数的工具 | 设计工具时 |

### description 到底该怎么写

这是最容易低估的一件事。对比：

```
❌ 差： "query"  ——  查询数据

✅ 好： lookup_order —— 根据订单号查询订单状态、承运商和预计送达时间。
                      订单号形如 A1001（1-2 个字母 + 至少 3 位数字）。
                      需要退款、物流轨迹等其它信息时请改用其它工具。
```

好的 description 包含四要素：**功能 + 参数格式 + 使用时机 + 边界（什么情况不该用我）**。""")

    nb.code('''# 单独可运行：subset() 按标签裁剪工具集
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.tool import build_default_registry

full = build_default_registry(ROOT)
print("全部工具        :", full.names())
print()
print("只要 math 标签的 :", full.subset(["math"]).names())
print("只要 file 标签的 :", full.subset(["file"]).names())
print()
print("★ 给模型看的工具越少，它选错的概率越低。")
print("  这就是「按场景给最小工具集」的具体做法。")''')

    # ==================================================================
    section(nb, "⑦", "常见坑汇总")

    pitfall_table(nb, [
        ("用 `eval` 实现计算器", "提示词注入可执行任意代码", "AST 白名单，或 `ast.literal_eval`"),
        ("忘记 `additionalProperties: false`", "模型的幻觉参数被静默吞掉，行为不可预测",
         "显式关闭"),
        ("`bool` 被判为合法 `integer`", "`{\"expr\": true}` 通过校验并执行",
         "特判 `isinstance(value, bool)`"),
        ("参数校验放在执行之后", "副作用已经产生才报错", "校验必须在执行**之前**"),
        ("用字符串包含判断路径安全", "`....//`、符号链接、绝对路径都能绕过",
         "`resolve()` 后比前缀"),
        ("把原始异常回灌给模型", "模型看不懂 `missing 1 required positional argument`",
         "转写成「缺哪个参数 + 正确用法」"),
        ("工具异常向上抛", "整轮任务崩溃", "兜底 `except Exception` -> 结构化结果"),
        ("不限制结果长度", "一次返回 10MB 日志，上下文爆掉", "`max_result_chars` + 截断提示"),
        ("工具重名", "模型随机选一个，行为不可预测", "注册期就抛 `ValueError`"),
        ("description 写成给人看的注释", "模型调用成功率低",
         "写清「什么时候用我 + 参数含义 + 示例」"),
        ("工具无脑全挂上去", "模型选错工具", "`subset(tags)` 按场景裁剪"),
    ])

    summary(nb, [
        "**工具 = 函数签名（给模型看）+ 参数校验（保护自己）+ 结果序列化（给模型读）。**",
        "**模型输出是不可信输入。** 校验必须在执行之前 —— 没被执行，就没有副作用。",
        "**白名单，不是黑名单。** 黑名单永远堵不完（等价写法无穷多）；白名单默认拒绝。",
        "**`bool` 是 `int` 的子类** —— 不特判的话 `{\"expr\": true}` 会通过类型校验。",
        "**路径安全靠 `resolve()` 后比前缀**，不是字符串包含判断。",
        "**失败也是一种结果。** 错误信息要含「哪里错了 + 正确用法 + 可用替代」，"
        "它是写给模型的下一条上下文。",
        "**工具不是越多越好。** 超过 ~20 个就该做工具检索或按场景裁剪。",
    ], "第 03 章会解决一个新问题：模型输出格式会崩。"
       "我们的校验器再好，也拦不住「模型根本没按格式说话」——"
       "那需要提示词工程 + 健壮解析器 + 失败回灌。")

    exercises(nb, [
        ("**给校验器加 `enum` 约束并观察效果。**\n\n"
         "给 `lookup_order` 加一个可选参数 `format`，取值只能是 `text` 或 `json`。\n\n"
         "然后分别传 `json`、`xml`、`JSON`，看校验器返回什么。\n\n"
         "思考：为什么 `JSON`（大写）应该被拒绝？",
         "schema 里写 `{\"type\": \"string\", \"enum\": [\"text\", \"json\"]}`。\n\n"
         "`enum` 是**精确匹配**。如果要允许大小写，可以在校验前统一转小写，"
         "或者把两种写法都列进 enum —— 但要想清楚哪种更安全。"),

        ("**故意拆掉 `additionalProperties` 防护。**\n\n"
         "把 `calc` 的 schema 里 `\"additionalProperties\": False` 删掉，"
         "然后传 `{\"expr\": \"1+1\", \"unit\": \"元\"}`。\n\n"
         "观察：错误还会被报出来吗？模型还能知道参数错了吗？",
         "删掉之后校验会通过，多余的 `unit` 会被 `**args` 静默接受，"
         "模型**永远不知道自己错了**。\n\n"
         "这就是「护栏拆掉后问题反而更难查」的典型例子 —— "
         "错误被静默吞掉比报错更危险。"),

        ("**给 AST 白名单加 DoS 防护并验证。**\n\n"
         "现有实现对 `**` 的指数做了限制。试试这些，看白名单是否足够：\n"
         "`9**9**9`、`9**999999`、`sqrt(sqrt(sqrt(9**700)))`。\n\n"
         "想一个更通用的防护方案。",
         "逐个运算符特判是补不完的。更通用的做法是**限制 AST 节点总数**"
         "（比如超过 100 个节点就拒绝），或者限制计算耗时。\n\n"
         "真实系统里这类「资源耗尽」攻击要靠超时 + 进程隔离来防，"
         "不是靠表达式层面的检查。"),

        ("**给 `count_words` 写一份好的 description。**\n\n"
         "现在它写的是「统计一段文本的总字符数与中文字数」。\n"
         "按四要素（功能 + 参数格式 + 使用时机 + 边界）重写一版。\n\n"
         "然后对比：什么样的 description 会让模型更不容易用错？",
         "好的版本大概长这样：\n\n"
         "「统计一段文本的字符数和中文字数。`text` 是要统计的原文，"
         "直接传内容本身，不要加引号。**当用户问「这段有多少字」时必须用它**；"
         "如果用户问的是「有几句」或「语法对不对」，请改用其它工具。」"),

        ("**模拟一次完整的注入攻击链。**\n\n"
         "写一个假模型，让它输出这样的工具调用：\n"
         "`<call>{\"name\": \"calc\", \"args\": {\"expr\": \"__import__('os').system('echo 被入侵')\"}}</call>`\n\n"
         "然后走一遍 `reg.execute('calc', ...)`，"
         "确认 AST 白名单把它拦住了，并且返回的错误信息是可读的。",
         "直接用 `build_default_registry(ROOT).execute('calc', {...})`。\n\n"
         "重点看：`r.ok` 是不是 `False`、`r.error` 里有没有说清"
         "「不允许调用 __import__」以及可用函数清单。"),
    ])

    checkpoint(nb, "02")

    return nb
