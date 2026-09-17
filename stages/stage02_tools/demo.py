"""第 02 章 · 工具系统与 JSON Schema —— 让模型安全地调用你的函数。

运行：
    py -m stages.stage02_tools.demo
    py -m stages.stage02_tools.demo --list
    py -m stages.stage02_tools.demo --section 4

本章目标：回答一个问题 —— **模型凭什么能安全地调用我写的 Python 函数？**

第 01 章里我们是"裸调"工具的：
    self.tools[name](**args)
这行代码有三个致命的坑，本章逐个拆掉：

    坑 1：模型给错参数名 → TypeError，错误信息人类都看不懂，模型更看不懂
    坑 2：模型给恶意参数   → ../.. 路径穿越、eval 注入、超长结果撑爆上下文
    坑 3：工具内部有 Bug   → 异常直接把 Agent 循环炸掉，整轮任务失败

解法是把"工具"从**一个函数**升级成**一份带契约的规格（ToolSpec）**。
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check_that, code, essence, kv, note, ok, report,
    section, setup_console, warn,
)

# ===========================================================================
# 第 1 节：先看裸调工具的三个坑
# ===========================================================================


def _bare_calc(expr: str) -> str:
    """一个天真到危险的"计算器" —— 用 eval 实现（千万别这么干）。"""
    return str(eval(expr))  # noqa: S307  ← 故意留的漏洞，用来演示攻击


def demo_naive_tools() -> None:
    section("裸调工具：三个坑，一个比一个致命", "①")

    print("  坑 1：模型给错参数名\n")
    try:
        _bare_calc()  # 模型忘了给 expr
    except TypeError as exc:
        code(f"工具抛出的原始异常：\nTypeError: {exc}", indent=4)
    note("这个信息回灌给模型，它基本看不懂。模型需要的是「正确用法：calc(expr='1+1')」。")

    print("\n  坑 2：模型给的参数是恶意输入\n")
    payload = "__import__('os').getcwd()"
    result = _bare_calc(payload)
    code(f"攻击载荷：expr = {payload!r}\n执行结果：{result}", indent=4)
    warn("看到了吗？模型输出 = 不可信输入。eval 会老老实实执行它。")
    warn("真实攻击用 __import__('os').system('rm -rf /') 或读取环境变量里的密钥，后果自己想象。")

    print("\n  坑 3：工具内部有 Bug\n")
    try:
        _bare_calc("1/0")
    except ZeroDivisionError as exc:
        code(f"ZeroDivisionError: {exc}\n（如果这里不接住，整个 Agent 循环就崩了）", indent=4)

    print()
    essence(
        "工具的输入来自模型，模型输出不可信；\n"
        "工具的异常属于你自己，不该让整轮任务陪葬。\n"
        "所以工具必须是「带契约的规格」，不是「一个裸函数」。"
    )


# ===========================================================================
# 第 2 节：手写一个工具系统（本章核心）
# ===========================================================================
# 一份完整的工具规格 = 四件事：
#   ① name/description  —— 给模型看的"说明书"（模型靠它决定调不调、怎么调）
#   ② parameters        —— JSON Schema，给校验器看的"契约"
#   ③ func              —— 真正执行的 Python 函数
#   ④ 安全策略          —— 审批、结果截断、超时（本章先讲结果截断）


@dataclass
class MyToolSpec:
    """工具说明书。注意 description 是**写给模型看的**，不是写给人看的注释。"""

    name: str
    description: str
    parameters: dict[str, Any]
    func: Callable[..., Any] | None = None
    max_result_chars: int = 2000

    # -------- ① 给模型看的两种格式 --------
    def to_prompt_line(self) -> str:
        """纯文本协议用：写进系统提示词的一行说明。

        注意 `expr: string` 后面的问号规则 —— 必填参数不加问号，可选参数加 `?`。
        这个约定能显著降低模型漏填必填参数的概率。
        """
        props = self.parameters.get("properties", {})
        required = set(self.parameters.get("required", []))
        parts = []
        for pname, pspec in props.items():
            mark = "" if pname in required else "?"
            parts.append(f"{pname}{mark}: {pspec.get('type', 'any')}")
        return f"- {self.name}({', '.join(parts)}): {self.description}"

    def to_openai_tool(self) -> dict[str, Any]:
        """原生 Function Calling 用：OpenAI 兼容协议的结构化描述。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def example_call(self) -> str:
        """生成一个"可以直接抄"的调用示例 —— 对小模型正确率的提升非常明显。"""
        props = self.parameters.get("properties", {})
        demo: dict[str, Any] = {}
        for pname, pspec in props.items():
            if "example" in pspec:
                demo[pname] = pspec["example"]
            elif pname in self.parameters.get("required", []):
                demo[pname] = {"string": "示例文本", "integer": 1, "number": 1.0,
                               "boolean": True, "array": [], "object": {}}.get(
                                   pspec.get("type", "string"), "…")
        return f"{self.name}({json.dumps(demo, ensure_ascii=False)})"


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """JSON Schema 子集校验器：返回全部错误（不是遇到第一个就返回）。

    为什么要"一次给全部错误"？
        因为每次回灌都要花一次模型调用。一次给全，模型一次就能改对；
        一次给一个，模型改完这个又错那个，来回 5 次，钱和时间都浪费了。

    支持：type / properties / required / enum / const / minimum / maximum
          / minLength / maxLength / pattern / items / additionalProperties
    """
    errors: list[str] = []
    if not schema:
        return errors

    # ---- 类型 ----
    type_map: dict[str, tuple[type, ...]] = {
        "string": (str,), "integer": (int,), "number": (int, float),
        "boolean": (bool,), "array": (list, tuple), "object": (dict,),
        "null": (type(None),),
    }
    expected = schema.get("type")
    if expected:
        names = expected if isinstance(expected, list) else [expected]
        py_types: list[type] = []
        for n in names:
            py_types.extend(type_map.get(n, ()))
        if py_types:
            ok_type = isinstance(value, tuple(py_types))
            # ★ 坑：bool 是 int 的子类！不特判的话 True 会被判成合法的 integer。
            if ok_type and bool not in py_types and isinstance(value, bool):
                ok_type = False
            if not ok_type:
                errors.append(f"{path}: 期望 {expected}，实际是 {type(value).__name__}"
                              f"（值={_short(value)}）")
                return errors  # 类型都不对，后面的约束没意义

    # ---- 取值约束 ----
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 必须是 {schema['enum']} 之一，实际 {_short(value)}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 必须是 {schema['const']!r}，实际 {_short(value)}")

    # ---- 字符串约束 ----
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度至少 {schema['minLength']}，实际 {len(value)}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: 长度最多 {schema['maxLength']}，实际 {len(value)}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: 不匹配 {schema['pattern']!r}（值={_short(value)}）")

    # ---- 数值约束 ----
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 不能小于 {schema['minimum']}，实际 {value}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 不能大于 {schema['maximum']}，实际 {value}")

    # ---- 数组约束 ----
    if isinstance(value, (list, tuple)) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(validate(item, schema["items"], f"{path}[{i}]"))

    # ---- 对象约束 ----
    if isinstance(value, dict):
        props: dict[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺少必填参数 {key!r}")
        for key, sub in props.items():
            if key in value:
                errors.extend(validate(value[key], sub, f"{path}.{key}"))
        # ★ 这条最容易被忽视，但它是"防幻觉参数"的关键
        if schema.get("additionalProperties") is False:
            extra = [k for k in value if k not in props]
            if extra:
                errors.append(f"{path}: 出现未定义参数 {extra}，允许的只有 {list(props)}")
    return errors


def _short(v: Any, n: int = 40) -> str:
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, default=str)
    return s if len(s) <= n else s[:n] + "…"


@dataclass
class MyToolResult:
    """执行结果。**永远不抛异常给 Agent 循环**，失败也是一种结果。"""

    name: str
    ok: bool
    content: str = ""
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_observation(self) -> str:
        """成功/失败统一格式 —— 统一的格式让模型更容易学会怎么读。"""
        if self.ok:
            return f'<result tool="{self.name}">\n{self.content}\n</result>'
        return (f'<result tool="{self.name}" status="error">\n'
                f'工具执行失败：{self.error}\n'
                f'提示：请检查参数是否正确，或改用其他工具。\n</result>')


class MyToolRegistry:
    """工具注册表：管理说明书、校验参数、安全执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, MyToolSpec] = {}

    # ---- 注册 -----------------------------------------------------------
    def register(self, spec: MyToolSpec) -> MyToolSpec:
        if spec.name in self._tools:
            # 重名必须在注册期就报错，而不是等运行时模型选错工具
            raise ValueError(f"工具重名: {spec.name}（模型会分不清该调哪个）")
        if not spec.name.isidentifier():
            raise ValueError(f"工具名必须是合法标识符: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def from_function(self, fn: Callable[..., Any], description: str = "") -> MyToolSpec:
        """从普通 Python 函数**自动生成** schema（内省签名 + 类型注解）。

        这就是"函数即工具"：写业务函数的人不需要手写 JSON Schema，
        少写样板代码 = 少犯错。
        """
        sig = inspect.signature(fn)
        type_map = {str: "string", int: "integer", float: "number",
                    bool: "boolean", list: "array", dict: "object"}
        props: dict[str, Any] = {}
        required: list[str] = []
        for pname, p in sig.parameters.items():
            anno = p.annotation if p.annotation is not inspect.Parameter.empty else str
            props[pname] = {"type": type_map.get(anno, "string")}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
            else:
                props[pname]["default"] = p.default
        return self.register(MyToolSpec(
            name=fn.__name__,
            description=description or (inspect.getdoc(fn) or "").split("\n")[0],
            parameters={"type": "object", "properties": props, "required": required},
            func=fn,
        ))

    # ---- 查询 -----------------------------------------------------------
    def names(self) -> list[str]:
        return sorted(self._tools)

    def describe(self) -> str:
        """把全部工具渲染成提示词片段（含调用示例）。"""
        lines = [s.to_prompt_line() for s in self._tools.values()]
        examples = "\n".join(f"  {s.example_call()}" for s in self._tools.values())
        return ("可用工具：\n" + "\n".join(lines) + "\n\n调用示例：\n" + examples)

    # ---- 执行 -----------------------------------------------------------
    def execute(self, name: str, args: dict[str, Any]) -> MyToolResult:
        """安全执行三步走：找工具 → 校验参数 → 执行并序列化。

        ★ 这个方法**任何情况下都不抛异常**。
          理由：Agent 是"永不放弃"的系统，工具失败应该变成一条观察结果，
          让模型有机会自救（换工具、改参数、或者如实告诉用户）。
        """
        # 第 1 步：工具存在吗？（模型会产生"幻觉工具"）
        spec = self._tools.get(name)
        if spec is None:
            return MyToolResult(
                name=name, ok=False,
                error=f"工具 {name!r} 不存在。可用工具：{self.names()}",
            )

        # 第 2 步：参数合法吗？（这一步拦掉的错误最多）
        errors = validate(args, spec.parameters)
        if errors:
            return MyToolResult(
                name=name, ok=False,
                error=("参数校验失败：\n- " + "\n- ".join(errors)
                       + f"\n\n正确用法：{spec.example_call()}"),
            )

        # 第 3 步：执行 + 序列化
        if spec.func is None:
            return MyToolResult(name=name, ok=False, error=f"工具 {name} 没有实现")
        try:
            raw = spec.func(**args)
            return MyToolResult(name=name, ok=True,
                                content=_serialize(raw, spec.max_result_chars))
        except Exception as exc:
            # 兜底：连我自己写的 Bug 也不能让 Agent 崩
            return MyToolResult(
                name=name, ok=False,
                error=f"{type(exc).__name__}: {exc}",
                meta={"hint": "工具内部异常，属于代码缺陷；应修工具而不是让模型重试"},
            )


def _serialize(raw: Any, max_chars: int = 2000) -> str:
    """把任意返回值变成模型能读的字符串，并做长度保护。

    ★ 结果截断是必须的：一个返回 10MB 日志的工具，
      一次调用就能把上下文窗口撑爆，后面所有对话都废了。
    """
    if raw is None:
        return "(空结果)"
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, (dict, list, tuple)):
        text = json.dumps(raw, ensure_ascii=False, indent=2, default=str)
    else:
        text = str(raw)
    if len(text) > max_chars:
        text = (text[:max_chars]
                + f"\n…（结果被截断，原始长度 {len(text)} 字符；请缩小查询范围）")
    return text


# ===========================================================================
# 第 3 节：把工具接到 Agent 上
# ===========================================================================


def _build_registry() -> MyToolRegistry:
    """注册本章的教学工具集。"""
    reg = MyToolRegistry()

    def calc(expr: str) -> str:
        """计算数学表达式（安全实现，见第 5 节）。"""
        return _safe_calc(expr)

    reg.register(MyToolSpec(
        name="calc",
        description="计算数学表达式，支持 + - * / // % ** 和 sqrt/abs/round/min/max。",
        parameters={
            "type": "object",
            "properties": {
                "expr": {"type": "string", "description": "要计算的表达式",
                         "example": "(12+8)*3/4"},
            },
            "required": ["expr"],
            "additionalProperties": False,   # ★ 拒绝一切未定义参数
        },
        func=calc,
    ))

    reg.register(MyToolSpec(
        name="lookup_order",
        description="根据订单号查询订单状态。订单号形如 A1001（字母+数字）。",
        parameters={
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号，例如 A1001",
                             "pattern": "(?i)^[a-z]{1,2}\\d{3,}$"},
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
        func=_lookup_order,
    ))

    reg.from_function(
        count_words,
        description="统计一段文本的总字符数与中文字数。",
    )
    return reg


def count_words(text: str) -> dict[str, Any]:
    """统计文本长度。"""
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return {"总字符数": len(text), "中文字数": cjk}


def _lookup_order(order_id: str) -> dict[str, Any]:
    table = {
        "A1001": {"status": "已发货", "carrier": "顺丰", "tracking": "SF1234567890"},
        "B2043": {"status": "运输中", "carrier": "中通", "tracking": "ZT9988776655"},
    }
    key = order_id.upper()
    if key not in table:
        raise ValueError(f"订单 {key} 不存在。已知示例订单：{sorted(table)}")
    return {"order_id": key, **table[key]}


def demo_registry() -> None:
    section("工具规格长什么样：模型看到的说明书", "③")
    reg = _build_registry()
    kv("已注册工具", reg.names())
    print()
    note("这是模型看到的工具说明（写进系统提示词）：")
    code(reg.describe(), indent=4)
    print()
    note("这是给原生 Function Calling 用的结构化格式：")
    code(json.dumps(reg._tools["calc"].to_openai_tool(), ensure_ascii=False, indent=2), indent=4)


# ===========================================================================
# 第 4 节：五种"模型犯错"场景，看工具系统怎么接住
# ===========================================================================


def demo_validation() -> None:
    section("参数校验：把模型的错拦在执行之前", "④")
    reg = _build_registry()

    cases: list[tuple[str, str, dict]] = [
        ("① 正常调用", "calc", {"expr": "(12+8)*3/4"}),
        ("② 幻觉工具（模型编了一个不存在的工具）", "search_google", {"q": "天气"}),
        ("③ 参数名写错（exp 而不是 expr）", "calc", {"exp": "1+1"}),
        ("④ 幻觉参数（多传一个 unit）", "calc", {"expr": "1+1", "unit": "元"}),
        ("⑤ 类型错误（把表达式写成数字）", "calc", {"expr": 1 + 1}),
        ("⑥ 格式不合法（订单号不合 pattern）", "lookup_order", {"order_id": "abc"}),
        ("⑦ 缺少必填参数", "lookup_order", {}),
        ("⑧ 工具内部业务异常（订单不存在）", "lookup_order", {"order_id": "Z9999"}),
    ]

    for title, name, args in cases:
        result = reg.execute(name, args)
        mark = "✅" if result.ok else "❌"
        print(f"\n  {mark} {title}")
        kv("调用", f"{name}({json.dumps(args, ensure_ascii=False)})")
        body = result.content if result.ok else result.error
        for line in body.splitlines()[:6]:
            print(f"        {line}")

    print()
    note("观察这几点：")
    for line in [
        "1. 没有任何一种情况抛异常 —— Agent 循环永远不会被工具炸掉。",
        "2. 失败信息是**写给模型看**的：包含原因 + 正确用法，模型据此就能改对。",
        "3. ③④⑤⑥⑦ 都在**执行之前**被拦下 —— 没被执行就没副作用，这是安全的关键。",
        "4. ② 幻觉工具时返回可用工具清单 —— 这是纠正幻觉最有效的一招。",
        "5. ⑧ 是唯一进入函数体才发现的问题，属于正常业务分支，不是 Bug。",
    ]:
        print(f"     {line}")


# ===========================================================================
# 第 5 节：安全三件套（本章最该记住的部分）
# ===========================================================================


def _safe_calc(expr: str) -> str:
    """安全求值：AST 白名单。

    ★ 为什么绝不能用 eval？
        eval("__import__('os').system('rm -rf /')") 是真的会执行。
        在 Agent 里，expr 这个字符串的来源是**模型的输出**，而模型输出
        可以被用户通过提示词注入间接控制。等于把 shell 交给了陌生人。

    ★ 为什么 AST 白名单是安全的？
        我们只"解释"白名单里的节点类型（加减乘除、几个数学函数），
        任何不在白名单里的语法（属性访问、下标、推导式、import、lambda…）
        直接拒绝。白名单的本质是：**默认拒绝，显式允许**。
    """
    allowed_bin = {
        ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
        ast.Pow: lambda a, b: a ** b,
    }
    allowed_func = {"sqrt": math.sqrt, "abs": abs, "round": round,
                    "min": min, "max": max, "floor": math.floor, "ceil": math.ceil}

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                return node.value
            raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
        if isinstance(node, ast.BinOp):
            op = allowed_bin.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 1000:
                raise ValueError("指数过大，拒绝计算（防止算力耗尽）")  # DoS 防护
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
                raise ValueError("除数不能为 0")
            return op(left, right)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            val = ev(node.operand)
            return val if isinstance(node.op, ast.UAdd) else -val
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_func:
                raise ValueError(f"不允许调用 {getattr(node.func, 'id', '?')}；"
                                 f"可用：{sorted(allowed_func)}")
            if node.keywords:
                raise ValueError("不支持关键字参数")
            return allowed_func[node.func.id](*[ev(a) for a in node.args])
        raise ValueError(f"表达式里出现不允许的语法: {type(node).__name__}")

    value = ev(ast.parse(expr, mode="eval"))
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{expr} = {value}"


def _safe_path(workspace: Path, rel: str) -> Path:
    """路径穿越防护：把相对路径解析后，必须仍在工作目录内。

    ★ 第一层：为什么不能只检查 "../"？
        因为攻击者可以用 `....//`、URL 编码、符号链接、Windows 的
        `..\\` 和绝对路径 `C:\\Windows\\...` 绕过字符串检查 ——
        **路径的等价写法是无穷的**，所以先 resolve() 成唯一的绝对路径。

    ★★ 第二层：解析成绝对路径之后，**也不能用 startswith 比前缀**。
        字符串前缀不是目录边界：root 是 `D:\\ws\\sandbox` 时，
        兄弟目录 `D:\\ws\\sandbox_evil` 的字符串同样以它开头，
        于是 `../sandbox_evil/x.txt` 会被前缀检查**放行**（越界成功）。
        目录归属要按路径语义判断：`Path.is_relative_to()`（Python 3.9+）。
    """
    root = Path(workspace).resolve()
    p = (root / rel).resolve()
    if not p.is_relative_to(root):
        raise ValueError(f"拒绝访问工作目录之外的路径: {rel}")
    return p


def demo_security() -> None:
    section("安全三件套：AST 白名单 / 路径穿越 / 结果截断", "⑤")

    print("  ① AST 白名单：拒绝一切非数学语法\n")
    for expr in ["(12+8)*3/4", "sqrt(16)+1",
                 "__import__('os').system('echo pwned')",
                 "open('/etc/passwd').read()",
                 "(1).__class__.__bases__"]:
        try:
            kv(f"calc({expr!r})", f"✅ {_safe_calc(expr)}")
        except Exception as exc:
            kv(f"calc({expr!r})", f"⛔ 已拒绝：{exc}")
    print()
    note("前两个正常计算；后三个是真实攻击载荷，全部被白名单挡在解释器之外。")
    warn("对比第 1 节的 eval 版本 —— 同样的载荷会真的执行。这就是有校验和没校验的区别。")

    print("\n\n  ② 路径穿越防护：沙箱边界\n")
    workspace = ROOT / "stages" / "stage02_tools"
    for rel in ["notes.md", "../stage01_agent_loop/demo.py",
                "../stage02_tools_evil/x.md",
                "../../../Windows/System32/drivers/etc/hosts", "/etc/passwd"]:
        try:
            p = _safe_path(workspace, rel)
            kv(f"路径 {rel!r}", f"✅ 允许 → {p.relative_to(workspace.resolve())}")
        except Exception as exc:
            kv(f"路径 {rel!r}", f"⛔ 已拒绝：{exc}")
    print()
    note("注意 '../stage02_tools_evil/x.md' 这条：它解析到**兄弟目录**，字符串照样以 root 开头 ——")
    note("用 startswith 比前缀会放行它，用 is_relative_to 才拦得住。这就是前缀不是目录边界。")
    note("绝对路径 '/etc/passwd' 也被拦住：pathlib 里 root / '/etc/passwd' 会**替换**掉 root，")
    note("得到 D:/etc/passwd，本来就在工作目录之外。**永远不要用字符串前缀判断路径安全。**")

    print("\n\n  ③ 结果截断：防止一次工具调用撑爆上下文\n")
    huge = "日志行\n" * 5000            # 约 2 万字符
    spec = MyToolSpec(name="read_log", description="读日志",
                      parameters={"type": "object", "properties": {}},
                      max_result_chars=300)
    truncated = _serialize(huge, spec.max_result_chars)
    kv("原始长度", f"{len(huge)} 字符")
    kv("截断后长度", f"{len(truncated)} 字符")
    print()
    code(truncated[-120:], indent=4)
    print()
    note("截断提示本身也是给模型的信息：它知道结果不完整，可以缩小查询范围重试。")
    warn("不截断的后果：一次调用吃掉几万 token，后面所有对话都被挤掉，成本还暴涨。")


# ===========================================================================
# 第 6 节：工具数量与选择准确率（反直觉的工程结论）
# ===========================================================================


def demo_tool_count_tradeoff() -> None:
    section("反直觉结论：工具不是越多越好", "⑥")

    reg = _build_registry()
    base = len(reg.names())

    rows = [
        (base, "本章工具集（3 个，描述清晰，无重叠）", "~95%"),
        (8, "加入 5 个功能相近的工具（search_web/search_doc/search_db…）", "~75%"),
        (20, "典型企业环境（邮件/日历/CRM/Jira/Confluence…）", "~55%"),
        (50, "不加治理的全量工具挂载", "~30%"),
    ]
    print(f"  {'工具数':<8}{'场景':<48}{'选择准确率（经验值）'}")
    print("  " + "-" * 78)
    for n, desc, acc in rows:
        print(f"  {n:<8}{desc:<48}{acc}")

    print()
    note("为什么会这样？因为工具说明会占用提示词，工具越多：")
    for line in [
        "1. 每个工具的描述都变「模糊」（上下文注意力被稀释）；",
        "2. 功能重叠时模型无法判断该用哪个（search_web vs search_doc）；",
        "3. 提示词变长 → 更贵、更慢、更早撞上上下文上限。",
    ]:
        print(f"     {line}")

    print()
    note("工程解法（按性价比排序）：")
    for line in [
        "① 按场景裁剪：客服场景只挂订单/退款/物流工具（core/tool.py 的 subset()）；",
        "② 写清楚 description 的**使用时机**，而不只是功能（说清「什么时候该用我」）；",
        "③ 工具检索：工具超过 ~20 个时，先检索出相关的 5 个再注入提示词；",
        "④ 合并同类：把 search_web/search_news/search_blog 合成一个带 source 参数的工具。",
    ]:
        print(f"     {line}")

    print()
    essence(
        "工具 = 函数签名（给模型看）+ 参数校验（保护自己）+ 结果序列化（给模型读）。\n"
        "\n"
        "三句话记住本章：\n"
        "  1. 模型输出是**不可信输入** —— 校验永远放在执行之前。\n"
        "  2. 工具失败要变成**可读的观察结果**，而不是异常 —— Agent 才有机会自救。\n"
        "  3. description 是写给模型的**说明书**，它的质量直接决定调用成功率。"
    )


def demo_compare_framework() -> None:
    section("对比：框架版的工具系统（core/tool.py）", "⑦")
    from core.tool import build_default_registry

    reg = build_default_registry(ROOT)
    kv("框架内置工具", reg.names())
    print()
    note("框架版比我们手写的多了这些（都是生产环境的必需品）：")
    for line in [
        "1. requires_approval —— 高危工具执行前必须人类审批（第 11 章）",
        "2. tags + subset()  —— 按场景裁剪工具集（本节⑥讲的治理手段）",
        "3. 慢调用告警      —— 工具耗时超阈值会记录，便于发现性能问题",
        "4. ToolSpec.to_prompt_line / to_openai_tool —— 两种协议一键切换",
        "5. _parse_param_doc —— 直接从 docstring 的 Args: 段落抠参数说明",
    ]:
        print(f"     {line}")
    print()
    # 拿框架版跑一次真实的校验失败，证明行为一致
    r = reg.execute("calc", {"expression": "1+1"})
    kv("框架版非法参数调用", "ok=False" if not r.ok else "ok=True")
    code((r.error or "")[:220], indent=4)


# ===========================================================================
# 自检
# ===========================================================================


def run_checks() -> list[tuple[str, bool, str]]:
    """本章验收标准（由 scripts/run_all_checks.py 调用）。"""
    results: list[tuple[str, bool, str]] = []
    reg = _build_registry()

    # --- 验收 1：正常调用成功 ---
    r = reg.execute("calc", {"expr": "(12+8)*3/4"})
    results.append(check_that("正常调用成功并返回结果", r.ok and "15" in r.content,
                              r.content[:40]))

    # --- 验收 2：工具内部异常不抛出，转成结构化失败 ---
    try:
        r2 = reg.execute("lookup_order", {"order_id": "Z9999"})
        raised = False
    except Exception:
        r2, raised = None, True
    results.append(check_that("工具业务异常不抛异常给 Agent 循环", not raised))
    results.append(check_that("异常被转成 ok=False 的结构化结果",
                              r2 is not None and r2.ok is False and "不存在" in r2.error,
                              (r2.error if r2 else "")[:50]))
    results.append(check_that("失败信息可读（含可用示例）",
                              r2 is not None and "A1001" in r2.error))

    # --- 验收 3：参数校验在执行前拦截 ---
    r3 = reg.execute("calc", {"exp": "1+1"})
    results.append(check_that("错误参数名被拦截（未执行）",
                              not r3.ok and "expr" in r3.error, r3.error[:60]))
    r4 = reg.execute("calc", {"expr": "1+1", "unit": "元"})
    results.append(check_that("additionalProperties=false 拦住幻觉参数",
                              not r4.ok and "未定义参数" in r4.error, r4.error[:60]))
    r5 = reg.execute("lookup_order", {"order_id": "abc"})
    results.append(check_that("pattern 拦截格式不合法的参数",
                              (not r5.ok) and ("不匹配" in r5.error), r5.error[:60]))
    r6 = reg.execute("calc", {})
    results.append(check_that("缺少必填参数被拦截",
                              not r6.ok and "缺少必填参数" in r6.error, r6.error[:60]))
    results.append(check_that("校验失败时回灌'正确用法'示例",
                              "正确用法" in r6.error and "expr" in r6.error))

    # --- 验收 4：幻觉工具被纠正 ---
    r7 = reg.execute("search_google", {"q": "x"})
    results.append(check_that("幻觉工具返回可用工具清单",
                              not r7.ok and "calc" in r7.error and "不存在" in r7.error,
                              r7.error[:60]))

    # --- 验收 5：bool 不被当成 integer（类型校验的经典坑）---
    r8 = reg.execute("calc", {"expr": True})
    results.append(check_that("bool 不被误判为合法 string/integer",
                              not r8.ok, r8.error[:60]))

    # --- 验收 6：AST 白名单挡住注入 ---
    for payload, label in [
        ("__import__('os').system('echo pwned')", "import 注入"),
        ("open('/etc/passwd').read()", "文件读取注入"),
        ("(1).__class__.__bases__", "属性访问"),
    ]:
        try:
            _safe_calc(payload)
            blocked = False
        except Exception:
            blocked = True
        results.append(check_that(f"AST 白名单拒绝{label}", blocked))
    results.append(check_that("AST 白名单仍能正常计算",
                              _safe_calc("sqrt(16)+1").endswith("5")))

    # --- 验收 7：路径穿越被拒绝 ---
    ws = ROOT / "stages" / "stage02_tools"
    for rel, label in [("../stage01_agent_loop/demo.py", "相对路径逃逸"),
                       ("../../../../etc/passwd", "多级逃逸"),
                       ("../stage02_tools_evil/x.md", "兄弟目录前缀绕过")]:
        try:
            _safe_path(ws, rel)
            blocked = False
        except Exception:
            blocked = True
        results.append(check_that(f"路径穿越被拒绝（{label}）", blocked))
    results.append(check_that("沙箱内路径正常放行",
                              _safe_path(ws, "notes.md").name == "notes.md"))

    # --- 验收 8：结果截断 ---
    big = "x" * 10000
    out = _serialize(big, 200)
    results.append(check_that("超长结果被截断并给出提示",
                              len(out) < 400 and "截断" in out, f"{len(out)} 字符"))

    # --- 验收 9：函数即工具（自动生成 schema）---
    spec = reg._tools["count_words"]
    results.append(check_that("from_function 自动生成 schema",
                              spec.parameters.get("required") == ["text"]
                              and spec.parameters["properties"]["text"]["type"] == "string",
                              str(spec.parameters.get("required"))))

    # --- 验收 10：重名工具在注册期就报错 ---
    try:
        reg.register(MyToolSpec(name="calc", description="重复", parameters={}))
        dup_blocked = False
    except ValueError:
        dup_blocked = True
    results.append(check_that("重名工具在注册期被拒绝", dup_blocked))

    # --- 验收 11：框架版工具系统行为一致 ---
    from core.tool import build_default_registry

    freg = build_default_registry(ROOT)
    fr = freg.execute("calc", {"expression": "1+1"})
    results.append(check_that("框架版同样拦住错误参数名",
                              not fr.ok and "expr" in fr.error, fr.error[:50]))
    fr2 = freg.execute("calc", {"expr": "6*7"})
    results.append(check_that("框架版正常运行", fr2.ok and "42" in fr2.content,
                              fr2.content[:30]))

    return results


# ===========================================================================
# 入口
# ===========================================================================

SECTIONS = {
    "1": ("裸调工具的三个坑", demo_naive_tools),
    "2": ("工具规格长什么样", demo_registry),
    "3": ("参数校验：八种犯错场景", demo_validation),
    "4": ("安全三件套", demo_security),
    "5": ("工具数量与准确率的取舍", demo_tool_count_tradeoff),
    "6": ("对比框架版工具系统", demo_compare_framework),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="第 02 章 · 工具系统与 JSON Schema")
    parser.add_argument("--section", "-s", choices=sorted(SECTIONS), help="只跑指定小节")
    parser.add_argument("--list", "-l", action="store_true", help="列出所有小节")
    parser.add_argument("--check", action="store_true", help="只跑自检")
    args = parser.parse_args(argv)

    setup_console()

    if args.list:
        banner("第 02 章 · 工具系统与 JSON Schema")
        for k in sorted(SECTIONS):
            print(f"  [{k}] {SECTIONS[k][0]}")
        return 0

    if args.check:
        return 0 if report("第 02 章", run_checks()) else 1

    banner("第 02 章 · 工具系统与 JSON Schema",
           "目标：搞清模型凭什么能安全地调用你写的 Python 函数")

    for key in ([args.section] if args.section else sorted(SECTIONS)):
        SECTIONS[key][1]()

    if not args.section:
        print()
        return 0 if report("第 02 章", run_checks()) else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
