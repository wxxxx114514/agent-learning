# 第 02 章 · 工具系统与 JSON Schema

<!-- 材料定位 -->
> ## 📖 这份文档是**复习手册**，不是第一次学习用的
>
> 同一章有三种材料，**内容一致，用途不同**：
>
> | 材料 | 位置 | 什么时候用 |
> |---|---|---|
> | **① 交互式 Notebook** | `notebooks/02_tools.ipynb` | **第一次学** —— 一步步推导，每个代码单元都能单独运行 |
> | **② 本文件** | `stages/stage02_tools/README.md` | **复习 / 查阅** —— 结构化的原理与工程要点，方便搜索和跳读 |
> | **③ 命令行 demo** | `py -m stages.stage02_tools.demo` | **看完整输出** —— 或者用 `-s N` 只看某一节 |
>
> **建议路径**：先用 ① 学一遍（能看到每一步的真实输出），
> 之后忘了什么回来查 ②，想快速跑一遍用 ③。
>
> 学完的验收命令：`py scripts\run_all_checks.py 02`

---

> **一句话本质**：
> 工具 = `函数签名（给模型看）` + `参数校验（保护自己）` + `结果序列化（给模型读）`。
>
> 三句话记住本章：
> 1. 模型输出是**不可信输入** —— 校验永远放在执行之前。
> 2. 工具失败要变成**可读的观察结果**，而不是异常 —— Agent 才有机会自救。
> 3. `description` 是写给模型的**说明书**，它的质量直接决定调用成功率。

---

## 0. 先看问题

第 01 章里我们是这样调工具的：

```python
result = self.tools[name](**args)     # ← 就这么一行
```

这行代码看起来人畜无害，实际上有三个致命的坑。运行 `py -m stages.stage02_tools.demo -s 1`：

```
  坑 1：模型给错参数名
    │ 工具抛出的原始异常：
    │ TypeError: _bare_calc() missing 1 required positional argument: 'expr'
  ℹ️  这个信息回灌给模型，它基本看不懂。模型需要的是「正确用法：calc(expr='1+1')」。

  坑 2：模型给的参数是恶意输入
    │ 攻击载荷：expr = "__import__('os').getcwd()"
    │ 执行结果：D:\project\agent-learning
  ⚠️  看到了吗？模型输出 = 不可信输入。eval 会老老实实执行它。

  坑 3：工具内部有 Bug
    │ ZeroDivisionError: division by zero
    │ （如果这里不接住，整个 Agent 循环就崩了）
```

三个坑对应三个不同的失败层面：

| 坑 | 触发者 | 后果 | 谁来兜底 |
|---|---|---|---|
| 参数名写错 | 模型幻觉 | 模型看不懂报错，反复试错烧钱 | **schema 校验 + 可读回灌** |
| 恶意参数 | 用户（通过提示词注入） | 执行任意代码/读任意文件 | **参数校验 + 沙箱 + AST 白名单** |
| 工具内部 Bug | 你自己 | 整轮任务崩溃 | **异常兜底 → 结构化结果** |

**核心矛盾**：`self.tools[name](**args)` 把"模型的输出"直接当成了"可信的程序输入"。这是 Agent 安全问题的总根源。

---

## 1. 原理

### 1.1 从"一个函数"升级成"一份带契约的规格"

```
        模型                       你的程序
         │                            │
         │  ① 我要调 calc             │
         │     args={"expr":"1+1"}    │
         ├───────────────────────────►│
         │                            │  ② 这个工具存在吗？        ── ToolSpec.name
         │                            │  ③ 参数符合契约吗？        ── ToolSpec.parameters (JSON Schema)
         │                            │  ④ 执行（在沙箱里）        ── ToolSpec.func
         │                            │  ⑤ 结果序列化 + 截断       ── ToolSpec.max_result_chars
         │  ⑥ <result>...</result>    │
         │◄───────────────────────────┤
         │                            │
```

校验必须发生在 **④ 执行之前**。这不是性能优化，而是安全边界：
**没被执行，就没有副作用**。校验放在执行之后 = 门锁装在门后面。

### 1.2 JSON Schema：给模型的"参数契约"

真实调用的 Schema 长这样：

```json
{
  "type": "object",
  "properties": {
    "expr": { "type": "string", "description": "要计算的表达式", "example": "(12+8)*3/4" }
  },
  "required": ["expr"],
  "additionalProperties": false
}
```

四个字段各有明确职责：

| 字段 | 作用 | 漏了会怎样 |
|---|---|---|
| `properties` | 每个参数的类型与说明 | 模型不知道要传什么 |
| `required` | 必填清单 | 模型漏填，你只能等工具报 TypeError |
| `additionalProperties: false` | **拒绝一切未定义参数** | 幻觉出的 `unit`、`currency` 会一路传到 `func(**args)` 并抛 `TypeError`（原始 Python 报错，模型看不懂）；只有函数带 `**kwargs` 时才真的被静默吞掉 |
| `example` | 可直接抄的示例（**本项目扩展字段，不是 JSON Schema 标准**；标准里的 `examples` 是数组） | 小模型的调用正确率明显下降 |

> `additionalProperties: false` 是最容易被忽视、又最值钱的一条。
> 模型非常喜欢"多加一个参数显得自己很懂"——比如查订单时顺手传 `format="json"`。
> 不开这个开关，校验**不会**拦住它：参数一路走到 `func(**args)`，运气好被 `**kwargs` 静默吞掉，
> 运气不好抛 `TypeError` —— 而这条报错是写给 Python 程序员看的，模型看不懂（见 4.2 常见坑）。
> 开了这个开关，问题会在**调用之前**变成一条模型能懂的纠正信息。

### 1.3 类型校验的经典陷阱：`bool` 是 `int` 的子类

```python
isinstance(True, int)   # → True
```

所以如果直接写 `isinstance(value, (int, float))`，模型传 `{"expr": true}` 会被判定为**合法的数字**，
然后 `calc(expr=True)` 一路执行下去。必须特判：

```python
ok_type = isinstance(value, tuple(py_types))
if ok_type and bool not in py_types and isinstance(value, bool):
    ok_type = False          # 强制把 bool 从 integer/number 里踢出去
```

这类细节就是"手写一遍"的价值 —— 用现成库你不会知道它替你挡掉了什么。

### 1.4 失败也是一种"结果"

对比两种失败处理方式：

```
❌ 抛异常：
   calc(...) → TypeError → Agent 循环崩溃 → 用户看到 500

✅ 转成结构化 observation：
   calc(...) → {"ok": false, "error": "缺少必填参数 'expr'\n正确用法：calc({\"expr\": ...})"}
             → 回灌给模型 → 模型改对参数 → 任务继续
```

失败信息是**写给模型看的下一条上下文**。所以它必须包含三样东西：

1. **哪里错了**：`$.expr: 期望 string，实际是 bool`
2. **正确姿势**：`正确用法：calc({"expr": "(12+8)*3/4"})`
3. **替代方案**：`可用工具：['calc', 'count_words', 'lookup_order']`

### 1.5 安全三件套

| 手段 | 防的是什么 | 关键实现 |
|---|---|---|
| **AST 白名单** | 表达式注入（`eval` 类工具） | 只解释白名单节点，默认拒绝 |
| **目录归属判断** | 目录穿越（文件类工具） | `resolve()` 后用 `is_relative_to()` 判归属，不做字符串前缀比较 |
| **结果截断** | 上下文被一次调用撑爆 | `max_result_chars` + 截断提示 |

**为什么表达式求值绝不能用 `eval`？**

```
eval("__import__('os').system('rm -rf /')")   ← 真的会执行
```

在 Agent 里，这个字符串的最终来源是**模型输出**，而模型输出可以被用户通过提示词注入间接控制。
用 `eval` 等于把 shell 交给陌生人。

**为什么路径检查不能靠字符串判断？（这其实是两层坑）**

**第一层：不能做"包含 `..`"这类字符串检查。**

因为攻击者可以用 `....//`、URL 编码、Windows 的 `..\`、符号链接、绝对路径绕过 ——
**路径的等价写法是无穷的**。所以必须先解析成唯一的绝对路径：

```python
p = (root / rel).resolve()      # 把 . / .. / 符号链接全部解析掉
```

**第二层：解析之后，也不能用 `str.startswith` 比前缀。**

字符串前缀**不是目录边界**。root 是 `D:\ws\sandbox` 时：

```
D:\ws\sandbox_evil\x.txt        ← 兄弟目录，字符串照样以 "D:\ws\sandbox" 开头
```

所以 `../sandbox_evil/x.txt` 这种路径会被前缀检查**放行** —— 越界成功。
（多级 `..` 逃逸反而挡得住，所以这个洞很容易在测试里漏掉。）

判断"这个路径属不属于这个目录"要用路径语义，不是字符串：

```python
if not p.is_relative_to(root):                  # Python 3.9+，按路径组件判断
    raise ValueError(f"拒绝访问工作目录之外的路径: {rel}")
```

> 等价写法：`os.path.commonpath([root, p]) == str(root)`。
> 本项目要求 Python 3.10+，直接用 `is_relative_to()` 最清楚。

### 1.6 反直觉结论：工具不是越多越好

```
工具数     场景                                              选择准确率（经验值）
3       本章工具集（3 个，描述清晰，无重叠）                     ~95%
8       加入 5 个功能相近的工具（search_web/search_doc/…）      ~75%
20      典型企业环境（邮件/日历/CRM/Jira/Confluence…）          ~55%
50      不加治理的全量工具挂载                                  ~30%
```

原因：工具说明占用提示词，工具越多，每个描述在注意力里的权重越低；功能重叠时模型无法判断该用哪个；
提示词变长则更贵、更慢、更早撞上上下文上限。

治理手段按性价比排序：

1. **按场景裁剪** —— 客服场景只挂订单/退款/物流工具（框架里的 `ToolRegistry.subset(tags)`）
2. **写清"使用时机"** —— description 说明"什么时候该用我"，而不只是"我能干什么"
3. **工具检索** —— 超过 ~20 个时，先检索出相关的 5 个再注入提示词
4. **合并同类** —— `search_web/search_news/search_blog` 合成一个带 `source` 参数的工具

---

## 2. 动手实现

`demo.py` 手写了一套完整的工具系统（约 200 行），四个核心部件：

### 2.1 `MyToolSpec` —— 说明书

```python
@dataclass
class MyToolSpec:
    name: str
    description: str                              # ← 写给模型看的
    parameters: dict[str, Any]                    # ← JSON Schema 契约
    func: Callable[..., Any] | None = None
    max_result_chars: int = 2000                  # ← 上下文保护
```

它提供两种"渲染"方式，对应模型表达工具调用的两条路线：

```python
def to_prompt_line(self) -> str:
    """纯文本协议：写进系统提示词的一行"""
    # - calc(expr: string): 计算数学表达式
    # 注意可选参数加 `?`，这个约定能显著降低漏填必填参数的概率
```

```python
def to_openai_tool(self) -> dict[str, Any]:
    """原生 Function Calling：OpenAI 兼容协议的结构化描述"""
```

### 2.2 `validate()` —— 校验器

两个设计决定值得单独说：

```python
def validate(value, schema, path="$") -> list[str]:
```

**决定一：一次收集全部错误，而不是遇到第一个就返回。**

```python
errors.append(f"{path}: 缺少必填参数 {key!r}")     # 继续检查，不 return
```

因为每次回灌都要花一次模型调用。一次给全，模型一次改对；一次给一个，模型改完这个又错那个。

**决定二：`path` 参数定位错误位置。**

```python
errors.extend(validate(value[key], sub, f"{path}.{key}"))    # $.order_id: 不匹配 ...
```

嵌套结构里，没有 `path` 的报错（"值不合法"）模型根本不知道该改哪里。

### 2.3 `MyToolRegistry.execute()` —— 安全执行三步走

```python
def execute(self, name: str, args: dict[str, Any]) -> MyToolResult:
    # 第 1 步：工具存在吗？（拦幻觉工具）
    spec = self._tools.get(name)
    if spec is None:
        return MyToolResult(name=name, ok=False,
                           error=f"工具 {name!r} 不存在。可用工具：{self.names()}")

    # 第 2 步：参数合法吗？（拦掉最多的错误，且发生在执行之前）
    errors = validate(args, spec.parameters)
    if errors:
        return MyToolResult(name=name, ok=False,
                           error=("参数校验失败：\n- " + "\n- ".join(errors)
                                  + f"\n\n正确用法：{spec.example_call()}"))

    # 第 3 步：执行 + 序列化（异常兜底）
    try:
        return MyToolResult(name=name, ok=True,
                            content=_serialize(spec.func(**args), spec.max_result_chars))
    except Exception as exc:
        return MyToolResult(name=name, ok=False, error=f"{type(exc).__name__}: {exc}")
```

**这个方法在任何情况下都不抛异常。** 这是刻意的：
Agent 是"永不放弃"的系统，工具失败应该变成一条观察结果，让模型有机会自救。

### 2.4 `from_function()` —— 函数即工具

```python
def count_words(text: str) -> dict[str, Any]:
    """统计文本长度。"""
    ...

reg.from_function(count_words, description="统计一段文本的总字符数与中文字数。")
```

靠 `inspect.signature()` 内省参数名、类型注解和默认值，自动生成 Schema：

- `str → "string"`、`int → "integer"`、`float → "number"`、`bool → "boolean"`
- 没有默认值的参数 → 进 `required`
- 有默认值的参数 → 写进 `default`

**写业务函数的人不需要手写 JSON Schema**，少写样板代码 = 少犯错。

---

## 3. 跑起来

```powershell
py -m stages.stage02_tools.demo              # 全部小节 + 自检
py -m stages.stage02_tools.demo --list       # 列出小节
py -m stages.stage02_tools.demo -s 3         # 只看"八种犯错场景"
py -m stages.stage02_tools.demo --check      # 只跑自检
```

### 第 3 节：八种犯错场景的真实输出（节选）

```
  ✅ ① 正常调用
  调用                : calc({"(12+8)*3/4"})
  (12+8)*3/4 = 15

  ❌ ② 幻觉工具（模型编了一个不存在的工具）
  调用                : search_google({"q": "天气"})
  工具 'search_google' 不存在。可用工具：['calc', 'count_words', 'lookup_order']

  ❌ ③ 参数名写错（exp 而不是 expr）
  调用                : calc({"exp": "1+1"})
  参数校验失败：
  - $: 缺少必填参数 'expr'
  - $: 出现未定义参数 ['exp']，允许的只有 ['expr']

  正确用法：calc({"expr": "(12+8)*3/4"})

  ❌ ⑤ 类型错误（把表达式写成数字）
  参数校验失败：
  - $.expr: 期望 string，实际是 int（值=2）
```

观察这几点：

1. 没有任何一种情况抛异常 —— Agent 循环永远不会被工具炸掉。
2. 失败信息是**写给模型看**的：包含原因 + 正确用法，模型据此就能改对。
3. ③④⑤⑥⑦ 都在**执行之前**被拦下 —— 没被执行就没副作用。
4. ② 幻觉工具时返回可用工具清单 —— 这是纠正幻觉最有效的一招。
5. ⑧ 是唯一进入函数体才发现的问题，属于正常业务分支，不是 Bug。

### 第 4 节：安全三件套的真实输出（节选）

```
  ① AST 白名单：拒绝一切非数学语法

  calc('(12+8)*3/4')                       : ✅ (12+8)*3/4 = 15
  calc('sqrt(16)+1')                       : ✅ sqrt(16)+1 = 5
  calc("__import__('os').system('echo pwned')") : ⛔ 已拒绝：不允许调用 __import__；可用：['abs', 'ceil', ...]
  calc("open('/etc/passwd').read()")       : ⛔ 已拒绝：不允许调用 open；可用：[...]
  calc('(1).__class__.__bases__')          : ⛔ 已拒绝：表达式里出现不允许的语法: Attribute

  ② 路径穿越防护：沙箱边界

  路径 'notes.md'                                    : ✅ 允许 → notes.md
  路径 '../stage01_agent_loop/demo.py'               : ⛔ 已拒绝：拒绝访问工作目录之外的路径: ...
  路径 '../../../Windows/System32/drivers/etc/hosts' : ⛔ 已拒绝：...
  路径 '/etc/passwd'                                 : ⛔ 已拒绝：...

  ③ 结果截断：防止一次工具调用撑爆上下文

  原始长度            : 20000 字符
  截断后长度           : 231 字符
```

### 自检结果

```
py -m stages.stage02_tools.demo --check
  ✅ 全部通过（24 项）
```

---

## 4. 工程要点

### 4.1 生产环境该用什么

| 教学实现 | 生产替代 | 为什么 |
|---|---|---|
| 手写 `validate()` | `pydantic` / `jsonschema` | 需要 `$ref`、`oneOf`、自定义格式（email/date-time） |
| 手写 AST 白名单 | `simpleeval` + 进程级沙箱 | 语言级白名单防不住资源耗尽攻击 |
| 目录归属判断 | 容器 / chroot / 独立服务账号 | 同进程内的路径检查总有绕过风险 |
| 字符串截断 | 结构化摘要 + 分页读取 | 截断会丢关键信息，摘要不会 |

**但是原理完全一样。** 用库的时候你必须知道它替你做了什么，否则出事时你连往哪查都不知道。

### 4.2 常见坑

| 坑 | 症状 | 解法 |
|---|---|---|
| 用 `eval` 实现计算器 | 被注入执行任意代码 | AST 白名单，或换 `ast.literal_eval` |
| 忘记 `additionalProperties: false` | 幻觉参数一路传到函数调用才炸（TypeError 或静默吞掉） | 显式关闭 |
| `bool` 被判为 `integer` | `{"expr": true}` 通过校验 | 特判 `isinstance(value, bool)` |
| 错误信息直接抛给模型 | 模型看不懂 `TypeError: missing 1 required positional argument` | 转写成"缺哪个参数 + 正确用法" |
| 工具异常向上抛 | 整轮任务崩溃 | 兜底 `except Exception` → 结构化结果 |
| 不限制结果长度 | 一次调用返回 10MB 日志，上下文爆掉 | `max_result_chars` + 截断提示 |
| 参数校验放在执行之后 | 副作用已经产生才报错 | 校验必须在执行之前 |
| 工具重名 | 模型随机选一个，行为不可预测 | 注册期就抛 `ValueError` |
| description 写成给人看的注释 | 模型调用成功率低 | 写清"什么时候用我 + 参数含义 + 示例" |
| 功能重叠的工具都挂上去 | 模型选错工具 | `subset(tags)` 按场景裁剪 |

### 4.3 工具描述怎么写（这是提示词工程的一部分）

```
❌ 差：
   "query"  —  查询数据

✅ 好：
   lookup_order — 根据订单号查询订单状态、承运商和预计送达时间。
                  订单号形如 A1001（1-2 个字母 + 至少 3 位数字）。
                  需要退款、物流轨迹等其它信息时请改用其它工具。
```

好描述包含四要素：**功能 + 参数格式 + 使用时机 + 边界（什么情况不该用我）**。

---

## 5. 练习

1. **给工具加超时**：现在的 `execute()` 没有超时保护。一个卡死 30 秒的工具会拖垮整轮任务。
   用 `signal.alarm`（Unix）或线程 + `join(timeout)`（跨平台）实现，超时后返回
   `ok=False, error="工具执行超时"`。
   *提示*：注意线程超时后无法真正杀死线程，生产环境要用子进程或异步任务。

2. **实现 `enum` 校验并观察效果**：给 `lookup_order` 加一个可选参数
   `format: {"type": "string", "enum": ["text", "json"]}`，然后分别传 `"json"`、`"xml"`、`"JSON"`，
   看校验器返回什么。思考：为什么 `"JSON"` 应该被拒绝？

3. **故意拆掉护栏**：把 `validate()` 里 `additionalProperties` 那段注释掉，重跑第 3 节的场景④。
   观察：错误的参数现在会被静默接受，模型永远不知道自己错了。
   **这就是"护栏拆掉后问题反而更难查"的典型例子。**

4. **给 `calc` 增加 DoS 防护并验证**：现有实现限制了 `**` 的指数。试试
   `9**9**9`、`sqrt(sqrt(sqrt(9**700)))`，看白名单是否足够。想一个更通用的防护方案。
   *提示*：参考 AST 节点数预算，而不是逐个运算符特判。

5. **工具检索的最小实现**：注册 20 个工具（描述随机写），然后实现 `select_tools(query, k=5)`：
   用 `difflib.SequenceMatcher` 或关键词重叠度给工具描述打分，只把 Top-K 注入提示词。
   对比"全量注入"与"Top-5 注入"的提示词长度。

---

## 6. 验收标准

- [x] 工具报错时 Agent **不崩**，错误变成 observation 回灌给模型
- [x] 参数校验失败时，模型能看到"正确用法"提示
- [x] 能解释为什么 `eval()` 在 Agent 里是致命的（并看到 AST 白名单实现）
- [x] 路径穿越（`../../etc/passwd`）被拒绝

```powershell
py scripts\run_all_checks.py 02      # → 0 failures
```

---

**上一章**：[第 01 章 最小 Agent 循环](../stage01_agent_loop/README.md)
**下一章**：[第 03 章 ReAct 提示工程](../stage03_react_prompt/README.md) —— 工具有了，
但模型开始乱调工具、不思考、格式写崩。下一章解决"怎么跟模型说话"。
