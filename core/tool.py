"""工具系统：Agent 的"手和脚"。

本模块解决四个工程问题：
  1. 描述：怎么把 Python 函数变成模型能看懂的说明书？ → ToolSpec + JSON Schema
  2. 校验：模型给的参数不合法怎么办？             → 轻量 JSON Schema 校验器
  3. 管理：工具多了怎么组织？                     → ToolRegistry（注册表模式）
  4. 容错：工具崩了会不会拖垮 Agent？             → 异常 → 结构化 observation

一句话本质：
    **工具 = 函数签名（给模型看） + 参数校验（保护自己） + 结果序列化（给模型读）**
"""

from __future__ import annotations

import inspect
import json
import math
import re
import time
import typing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .errors import ToolError, ToolNotFound, ToolValidationError

# ===========================================================================
# 一、JSON Schema 子集校验器
# ===========================================================================
# 为什么自己写？因为学习阶段要"看得见每一行逻辑"，且避免第三方依赖。
# 生产环境请用 jsonschema / pydantic —— 但原理完全一样。
#
# 支持的约束：type / properties / required / enum / const / minimum / maximum
#            / minLength / maxLength / pattern / items / additionalProperties

_TYPE_MAP: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
    "null": (type(None),),
}


def validate_schema(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """校验 value 是否符合 schema，返回错误信息列表（空列表 = 通过）。

    设计要点：**一次收集全部错误**，而不是遇到第一个就返回。
    因为我们要把完整错误一次性回灌给模型，减少来回次数。
    """
    errors: list[str] = []
    if not schema:
        return errors

    expected = schema.get("type")
    if expected:
        types = expected if isinstance(expected, list) else [expected]
        py_types: list[type] = []
        for t in types:
            py_types.extend(_TYPE_MAP.get(t, ()))
        if py_types:
            # 注意：bool 是 int 的子类，需要特殊处理，否则 True 会被判为 integer
            ok = isinstance(value, tuple(py_types))
            if ok and bool not in py_types and isinstance(value, bool):
                ok = False
            if not ok:
                errors.append(
                    f"{path}: 期望类型 {expected}，实际是 {type(value).__name__}（值={_short(value)}）"
                )
                return errors  # 类型都不对，后面约束没有意义

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 取值必须是 {schema['enum']} 之一，实际是 {_short(value)}")
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 取值必须是 {schema['const']!r}，实际是 {_short(value)}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度至少 {schema['minLength']}，实际 {len(value)}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: 长度最多 {schema['maxLength']}，实际 {len(value)}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: 不匹配正则 {schema['pattern']!r}（值={_short(value)}）")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 不能小于 {schema['minimum']}，实际 {value}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 不能大于 {schema['maximum']}，实际 {value}")

    if isinstance(value, (list, tuple)) and "items" in schema:
        for i, item in enumerate(value):
            errors.extend(validate_schema(item, schema["items"], f"{path}[{i}]"))

    if isinstance(value, dict):
        props: dict[str, Any] = schema.get("properties", {})
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺少必填参数 {key!r}")
        for key, sub in props.items():
            if key in value:
                errors.extend(validate_schema(value[key], sub, f"{path}.{key}"))
        if schema.get("additionalProperties") is False:
            extra = [k for k in value if k not in props]
            if extra:
                errors.append(f"{path}: 出现未定义参数 {extra}，允许的参数只有 {list(props)}")
    return errors


def _short(v: Any, n: int = 40) -> str:
    s = json.dumps(v, ensure_ascii=False, default=str) if not isinstance(v, str) else v
    return s if len(s) <= n else s[:n] + "…"


# ===========================================================================
# 二、工具规格与结果
# ===========================================================================
@dataclass
class ToolSpec:
    """一个工具的"说明书"。

    description 是**写给模型看的**，不是写给人看的注释 ——
    这是新手最容易忽视的一点：工具描述的质量直接决定调用成功率。
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    func: Callable[..., Any] | None = None
    tags: list[str] = field(default_factory=list)
    requires_approval: bool = False   # 高危工具：执行前需人类确认（阶段 11 会用）
    max_result_chars: int = 4000      # 结果截断，防止一次工具调用把上下文撑爆

    def to_openai_tool(self) -> dict[str, Any]:
        """转成 OpenAI Function Calling 的 tools 参数格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_prompt_line(self) -> str:
        """转成写进系统提示词的一行说明（纯文本协议的模型用）。"""
        params = self.parameters.get("properties", {})
        required = set(self.parameters.get("required", []))
        parts = []
        for pname, pspec in params.items():
            mark = "" if pname in required else "?"
            ptype = pspec.get("type", "any")
            pdesc = pspec.get("description", "")
            parts.append(f"{pname}{mark}: {ptype}" + (f"  // {pdesc}" if pdesc else ""))
        sig = ", ".join(parts)
        return f"- {self.name}({sig}): {self.description}"

    def example_call(self) -> str:
        """生成一个可直接抄的调用示例 —— 大幅提高小模型的调用正确率。"""
        params = self.parameters.get("properties", {})
        demo = {}
        for pname, pspec in params.items():
            t = pspec.get("type", "string")
            if "example" in pspec:
                demo[pname] = pspec["example"]
            elif pname in self.parameters.get("required", []):
                demo[pname] = {"string": "示例文本", "integer": 1, "number": 1.0,
                               "boolean": True, "array": [], "object": {}}.get(t, "…")
        return f'{self.name}({json.dumps(demo, ensure_ascii=False)})'


@dataclass
class ToolResult:
    """工具执行结果。**永远不要在这里抛异常给 Agent 循环**。"""

    name: str
    ok: bool
    content: str
    elapsed_ms: float = 0.0
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_observation(self) -> str:
        """转成喂给模型的 observation 文本（成功/失败格式统一，便于模型学习）。"""
        if self.ok:
            return f"<result tool=\"{self.name}\">\n{self.content}\n</result>"
        return (
            f"<result tool=\"{self.name}\" status=\"error\">\n"
            f"工具执行失败：{self.error or self.content}\n"
            f"提示：请检查参数是否正确，或改用其他工具。\n</result>"
        )


# ===========================================================================
# 三、注册表：工具的"户口本"
# ===========================================================================
class ToolRegistry:
    """管理所有工具：注册、查找、生成说明书、安全执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ---- 注册 ---------------------------------------------------------
    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"工具重名: {spec.name}（Agent 会分不清该调哪个）")
        if not spec.name.isidentifier():
            raise ValueError(f"工具名必须是合法标识符: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def tool(
        self,
        name: str = "",
        description: str = "",
        parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """装饰器写法：@registry.tool("calc", "计算表达式", {...})"""

        def deco(fn: Callable[..., Any]) -> Callable[..., Any]:
            spec = ToolSpec(
                name=name or fn.__name__,
                description=description or (inspect.getdoc(fn) or "").split("\n")[0],
                parameters=parameters or {"type": "object", "properties": {}},
                func=fn,
                **kwargs,
            )
            self.register(spec)
            return fn

        return deco

    def from_function(self, fn: Callable[..., Any], description: str = "", name: str = "") -> ToolSpec:
        """从一个普通 Python 函数**自动生成** schema（内省函数签名 + 类型注解）。

        这是"少写样板代码"的关键：函数即工具。
        """
        sig = inspect.signature(fn)
        type_map = {str: "string", int: "integer", float: "number", bool: "boolean",
                    list: "array", dict: "object"}
        # ★ 处理 `from __future__ import annotations`（PEP 563 延迟注解）
        #
        # 这是极易踩的坑：一旦模块顶部写了 `from __future__ import annotations`，
        # 所有注解在运行时都是**字符串**而不是类型对象。
        # 于是 `type_map.get("int")` 查不到，静默退化成 "string" ——
        # 校验器就会允许模型给 int 参数传字符串，直到函数执行时才炸。
        # 用 get_type_hints() 把字符串注解还原成真正的类型对象。
        try:
            hints = typing.get_type_hints(fn)
        except Exception:
            # 前向引用、循环引用等情况下解析可能失败，退回原始注解
            hints = dict(getattr(fn, "__annotations__", {}) or {})

        props: dict[str, Any] = {}
        required: list[str] = []
        for pname, p in sig.parameters.items():
            if pname in ("self", "cls") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                continue
            # 类型来源优先级：注解 > 默认值的类型 > 兜底 string
            #
            # 为什么要看默认值？因为常见写法是
            #     def read_file(path: str, max_chars=4000): ...
            # 这里 max_chars 没有注解。如果直接兜底成 "string"，模型会传
            # `{"max_chars": "4000"}`（字符串），而 Python 函数期望 int ——
            # 校验通过了，执行时才炸。用默认值的类型推断能避免这一类问题。
            anno = hints.get(pname, p.annotation)
            if anno is inspect.Parameter.empty:
                anno = None
            if isinstance(anno, str):
                # get_type_hints 也失败时的最后兜底：直接按名字匹配
                anno = {"str": str, "int": int, "float": float, "bool": bool,
                        "list": list, "dict": dict}.get(anno.strip())
            if anno is not None:
                ptype = type_map.get(anno, "string")
            elif p.default is not inspect.Parameter.empty and p.default is not None:
                ptype = type_map.get(type(p.default), "string")
            else:
                ptype = "string"
            props[pname] = {"type": ptype}
            if p.default is inspect.Parameter.empty:
                required.append(pname)
            else:
                props[pname]["default"] = p.default
            doc = _parse_param_doc(fn, pname)
            if doc:
                props[pname]["description"] = doc
        spec = ToolSpec(
            name=name or fn.__name__,
            description=description or (inspect.getdoc(fn) or "").split("\n")[0],
            parameters={"type": "object", "properties": props, "required": required},
            func=fn,
        )
        return self.register(spec)

    # ---- 查询 ---------------------------------------------------------
    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise ToolNotFound(
                f"工具 {name!r} 不存在。可用工具：{sorted(self._tools)}"
            )
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    def subset(self, tags: list[str]) -> "ToolRegistry":
        """按标签裁剪工具集 —— 工具越多模型越容易选错，按场景给最小集合。"""
        sub = ToolRegistry()
        for spec in self.specs():
            if set(tags) & set(spec.tags):
                sub.register(spec)
        return sub

    # ---- 说明书 -------------------------------------------------------
    def describe(self, style: str = "prompt") -> str:
        if style == "openai":
            return json.dumps([s.to_openai_tool() for s in self.specs()], ensure_ascii=False, indent=2)
        lines = [s.to_prompt_line() for s in self.specs()]
        examples = "\n".join(s.example_call() for s in self.specs())
        return "可用工具：\n" + "\n".join(lines) + "\n\n调用示例：\n" + examples

    def openai_tools(self) -> list[dict[str, Any]]:
        return [s.to_openai_tool() for s in self.specs()]

    # ---- 执行 ---------------------------------------------------------
    def execute(self, name: str, args: dict[str, Any], dry_run: bool = False) -> ToolResult:
        """执行工具。**任何异常都被转成 ToolResult(ok=False)**，绝不向上抛。

        dry_run=True 只校验参数不真正执行（预演），用于高危工具的人工确认流程。
        """
        start = time.perf_counter()
        try:
            spec = self.get(name)
        except ToolNotFound as exc:
            return ToolResult(name=name, ok=False, content="", error=str(exc),
                              elapsed_ms=(time.perf_counter() - start) * 1000)

        errors = validate_schema(args, spec.parameters)
        if errors:
            hint = self._param_hint(spec)
            return ToolResult(
                name=name, ok=False, content="", error="参数校验失败：\n- " + "\n- ".join(errors) + hint,
                elapsed_ms=(time.perf_counter() - start) * 1000,
            )

        if dry_run:
            return ToolResult(name=name, ok=True, content=f"[dry-run] 参数校验通过：{args}",
                              elapsed_ms=(time.perf_counter() - start) * 1000)

        if spec.func is None:
            return ToolResult(name=name, ok=False, content="", error=f"工具 {name} 没有实现",
                              elapsed_ms=(time.perf_counter() - start) * 1000)

        try:
            raw = spec.func(**args)
            content = _serialize_result(raw, spec.max_result_chars)
            return ToolResult(name=name, ok=True, content=content,
                              elapsed_ms=(time.perf_counter() - start) * 1000)
        except ToolError as exc:
            return ToolResult(name=name, ok=False, content="", error=str(exc),
                              elapsed_ms=(time.perf_counter() - start) * 1000)
        except Exception as exc:  # 兜底：连 Bug 也不能让 Agent 崩
            return ToolResult(
                name=name, ok=False, content="",
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=(time.perf_counter() - start) * 1000,
                meta={"traceback_hint": "工具内部异常，属于代码缺陷，应修工具而不是重试"},
            )

    def _param_hint(self, spec: ToolSpec) -> str:
        props = spec.parameters.get("properties", {})
        required = spec.parameters.get("required", [])
        lines = [f"\n正确用法：{spec.example_call()}"]
        if required:
            lines.append(f"必填参数：{required}")
        lines.append("参数说明：" + "; ".join(f"{k}({v.get('type')})" for k, v in props.items()))
        return "\n".join(lines)


def _parse_param_doc(fn: Callable[..., Any], param: str) -> str:
    """从 docstring 的 Args: 段落里抠出参数说明（Google 风格）。"""
    doc = inspect.getdoc(fn) or ""
    m = re.search(rf"^\s*{re.escape(param)}\s*[\(:：]\s*(.+)$", doc, re.M)
    if not m:
        m = re.search(rf"^\s*:param\s+{re.escape(param)}:\s*(.+)$", doc, re.M)
    return m.group(1).strip() if m else ""


def _serialize_result(raw: Any, max_chars: int = 4000) -> str:
    """把任意返回值变成模型能读的字符串，并做长度保护。"""
    if raw is None:
        return "(空结果)"
    if isinstance(raw, str):
        text = raw
    elif isinstance(raw, (dict, list, tuple)):
        try:
            text = json.dumps(raw, ensure_ascii=False, indent=2, default=str)
        except TypeError:
            text = str(raw)
    else:
        text = str(raw)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n…（结果被截断，原始长度 {len(text)} 字符；如需完整内容请缩小查询范围）"
    return text


# ===========================================================================
# 四、内置工具集（覆盖"计算 / 文本 / 文件 / 数据查询"四类典型场景）
# ===========================================================================
def build_default_registry(workspace: str | Path = ".") -> ToolRegistry:
    """构建教学用的默认工具集。"""
    reg = ToolRegistry()
    root = Path(workspace).resolve()

    # ---- 工具 1：安全计算器（重点讲！） -------------------------------
    @reg.tool(
        "calc",
        "计算一个数学表达式，支持 + - * / // % ** 和 sqrt/abs/round/min/max。用于任何算术问题。",
        {
            "type": "object",
            "properties": {
                "expr": {"type": "string", "description": "要计算的表达式，例如 (12+8)*3/4", "example": "(12+8)*3/4"},
            },
            "required": ["expr"],
            "additionalProperties": False,
        },
        tags=["math"],
    )
    def calc(expr: str) -> str:
        """安全求值：用 AST 白名单，绝不使用 eval()。

        为什么不能直接用 eval？
            模型输出 = 不可信输入。eval("__import__('os').system('rm -rf /')") 是真的会执行。
            这是 Agent 安全的第一课：**永远不要相信模型给的字符串**。
        """
        import ast

        allowed_bin = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/",
                       ast.FloorDiv: "//", ast.Mod: "%", ast.Pow: "**"}
        allowed_unary = {ast.UAdd: "+", ast.USub: "-"}
        allowed_func = {"sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max,
                        "int": int, "float": float, "pow": pow, "log": math.log, "floor": math.floor,
                        "ceil": math.ceil}

        def ev(node: ast.AST) -> Any:
            if isinstance(node, ast.Expression):
                return ev(node.body)
            if isinstance(node, ast.Constant):
                if isinstance(node.value, (int, float)):
                    return node.value
                raise ToolError(f"不支持的常量类型: {type(node.value).__name__}")
            if isinstance(node, ast.BinOp):
                op = allowed_bin.get(type(node.op))
                if op is None:
                    raise ToolError(f"不支持的运算符: {type(node.op).__name__}")
                left, right = ev(node.left), ev(node.right)
                if op == "**" and abs(right) > 1000:
                    raise ToolError("指数过大，拒绝计算（防止算力耗尽）")
                if op in ("/", "//", "%") and right == 0:
                    raise ToolError("除数不能为 0")
                return {"+": lambda: left + right, "-": lambda: left - right,
                        "*": lambda: left * right, "/": lambda: left / right,
                        "//": lambda: left // right, "%": lambda: left % right,
                        "**": lambda: left ** right}[op]()
            if isinstance(node, ast.UnaryOp):
                if type(node.op) not in allowed_unary:
                    raise ToolError("不支持的一元运算符")
                val = ev(node.operand)
                return val if isinstance(node.op, ast.UAdd) else -val
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in allowed_func:
                    raise ToolError(f"不允许调用函数 {getattr(node.func, 'id', '?')}；"
                                    f"可用：{sorted(allowed_func)}")
                if node.keywords:
                    raise ToolError("不支持关键字参数")
                return allowed_func[node.func.id](*[ev(a) for a in node.args])
            if isinstance(node, ast.Tuple):
                return tuple(ev(e) for e in node.elts)
            raise ToolError(f"表达式里出现不允许的语法: {type(node).__name__}")

        tree = ast.parse(expr, mode="eval")
        value = ev(tree)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return f"{expr} = {value}"

    # ---- 工具 2：字数统计 ---------------------------------------------
    @reg.tool(
        "count_words",
        "统计一段文本的字符数、中文字数、英文单词数。",
        {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要统计的文本", "minLength": 1},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
        tags=["text"],
    )
    def count_words(text: str) -> dict[str, Any]:
        """统计文本长度。"""
        cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
        words = len(re.findall(r"[A-Za-z]+", text))
        return {
            "总字符数": len(text),
            "中文字数": cjk,
            "英文单词数": words,
            "行数": text.count("\n") + 1,
        }

    # ---- 工具 3：订单查询（模拟内部系统 API） -------------------------
    FAKE_ORDERS = {
        "A1001": {"status": "已发货", "carrier": "顺丰", "tracking": "SF1234567890", "eta": "2025-01-05"},
        "A1002": {"status": "待付款", "carrier": None, "tracking": None, "eta": None},
        "B2043": {"status": "运输中", "carrier": "中通", "tracking": "ZT9988776655", "eta": "2025-01-03"},
    }

    @reg.tool(
        "lookup_order",
        "根据订单号查询订单状态、承运商和预计送达时间。订单号形如 A1001。",
        {
            "type": "object",
            "properties": {
                "order_id": {"type": "string", "description": "订单号，例如 A1001",
                             "pattern": "(?i)^[a-z]{0,2}\\d{3,}$"},
            },
            "required": ["order_id"],
            "additionalProperties": False,
        },
        tags=["data"],
    )
    def lookup_order(order_id: str) -> dict[str, Any]:
        """查询订单（教学用假数据）。"""
        key = order_id.upper()
        if key not in FAKE_ORDERS:
            raise ToolError(f"订单 {key} 不存在。已知示例订单：{sorted(FAKE_ORDERS)}")
        return {"order_id": key, **FAKE_ORDERS[key]}

    # ---- 工具 4/5：受限文件读写（沙箱） -------------------------------
    def _safe_path(path: str) -> Path:
        """路径穿越防护：只允许访问 workspace 内部。"""
        p = (root / path).resolve()
        if not str(p).startswith(str(root)):
            raise ToolError(f"拒绝访问工作目录之外的路径: {path}")
        return p

    @reg.tool(
        "read_file",
        "读取工作目录内的文本文件内容（相对路径）。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对路径，例如 notes.md"},
                "max_chars": {"type": "integer", "description": "最多读取多少字符", "minimum": 1, "maximum": 20000},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        tags=["file"],
    )
    def read_file(path: str, max_chars: int = 4000) -> str:
        """读取文件。"""
        p = _safe_path(path)
        if not p.exists():
            raise ToolError(f"文件不存在: {path}")
        if p.is_dir():
            raise ToolError(f"{path} 是目录，不是文件。可用 list_dir 查看目录内容")
        text = p.read_text(encoding="utf-8", errors="replace")
        return text[:max_chars]

    @reg.tool(
        "list_dir",
        "列出工作目录内某个目录下的文件与子目录（相对路径，默认根目录）。",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "相对路径，默认 ."}},
            "required": [],
            "additionalProperties": False,
        },
        tags=["file"],
    )
    def list_dir(path: str = ".") -> list[str]:
        """列目录。"""
        p = _safe_path(path)
        if not p.exists():
            raise ToolError(f"目录不存在: {path}")
        return sorted(f"{'[目录] ' if c.is_dir() else '      '}{c.name}" for c in p.iterdir())

    @reg.tool(
        "write_note",
        "把一段文字追加写入工作目录内的笔记文件（用于记录中间结论）。",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "相对路径，例如 scratch/notes.md"},
                "text": {"type": "string", "description": "要写入的内容", "minLength": 1},
            },
            "required": ["path", "text"],
            "additionalProperties": False,
        },
        tags=["file"],
        requires_approval=True,   # 会改磁盘 → 高危，阶段 11 讲审批流程
    )
    def write_note(path: str, text: str) -> str:
        """写笔记。"""
        p = _safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
        return f"已写入 {len(text)} 字符到 {path}"

    return reg
