r"""第 02 章 · 练习 2 / 5 · 故意拆掉 `additionalProperties` 防护

【要做什么】
  故意拆掉 `additionalProperties` 防护。

  把 `calc` 的 schema 里 `"additionalProperties": False` 删掉，
  然后传 `{"expr": "1+1", "unit": "元"}`。

  观察：错误还会被报出来吗？模型还能知道参数错了吗？

【已经给你了】
  · `GUARDED_SCHEMA`      —— **开着** `additionalProperties: False` 的 schema
  · `UNGUARDED_SCHEMA`    —— 拆掉防护的版本（把这一行删掉就是题目要求，已经替你删好了）
  · `validate_schema`     —— 校验器
  · `calc_strict(expr)`   —— 签名严格的工具函数（多余参数会抛 TypeError）
  · `calc_lenient(**kwargs)` —— 带 **kwargs 的版本（多余参数被**静默吞掉**）
  · `reg`                 —— 注册了 `calc_strict` 的工具注册表

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch02_tools\ex2_drop_additional.py
  3. 验收本章：py scripts\run_all_checks.py 02
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import ast                                                    # noqa: E402

from core.tool import ToolRegistry, ToolSpec, validate_schema # noqa: E402

GUARDED_SCHEMA = {
    "type": "object",
    "properties": {"expr": {"type": "string"}},
    "required": ["expr"],
    "additionalProperties": False,          # ★ 就是这一行在防"幻觉参数"
}

# 题目要求的那次拆除：把上面那一行删掉之后的 schema 长这样
UNGUARDED_SCHEMA = {
    "type": "object",
    "properties": {"expr": {"type": "string"}},
    "required": ["expr"],
}

BAD_ARGS = {"expr": "1+1", "unit": "元"}     # 模型"顺手多加一个参数"的典型样子


def _safe_expr(expr: str) -> str:
    BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
           ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.BinOp):
            return BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp):
            return -ev(n.operand)
        raise ValueError(f"不支持的语法: {type(n).__name__}")

    v = ev(ast.parse(expr, mode="eval"))
    return f"{expr} = {int(v) if isinstance(v, float) and v.is_integer() else v}"


def calc_strict(expr: str) -> str:
    """签名严格的工具：多传一个 unit 就会抛 TypeError。"""
    return _safe_expr(expr)


def calc_lenient(expr: str, **kwargs) -> str:
    """带 **kwargs 的版本：多传的参数被收进 kwargs，连异常都没有。"""
    extra = "".join(f" [额外参数 {k}={v!r} 被静默收下]" for k, v in kwargs.items())
    return _safe_expr(expr) + extra


reg = ToolRegistry()
reg.register(ToolSpec(name="calc", description="计算数学表达式。",
                      parameters=GUARDED_SCHEMA, func=calc_strict))


def strict_result():
    """走一遍开防护的路径：校验 -> 执行，返回注册表给出的结果对象。"""
    return reg.execute("calc", BAD_ARGS)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def check_after_removal() -> dict:
    """TODO ── 拆掉防护之后，亲手验证三件事，并把观察结果填进字典返回。

    返回的字典必须包含这 4 个键：

      "errors"       : 用 UNGUARDED_SCHEMA 校验 BAD_ARGS，返回的错误列表
                       —— 提示：errors = validate_schema(BAD_ARGS, UNGUARDED_SCHEMA)
      "type_error"   : calc_strict(**BAD_ARGS) 抛出的 TypeError 文本；
                       没抛异常就填空字符串 ""
      "extra_seen"   : calc_lenient(**BAD_ARGS) 的返回值里，**有没有出现 unit**？
                       填一个 `bool`：多余的参数被 **kwargs 收下 -> True
      "lenient_out"  : calc_lenient(**BAD_ARGS) 的完整返回值

    ★ 这一格要你亲手跑出来，而不是"读"出来 —— 重点在于体会
      "错误在调用之后才炸、而且炸得看不懂" 有多难查。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 2 · TODO  check_after_removal 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 02 章 · 练习 2 · 拆掉 additionalProperties 之后")
    print("=" * 68)
    print(f"\n  模型的参数 = {BAD_ARGS}   （expr 是对的，多了一个 unit）")

    print("\n  【开着防护】additionalProperties: False")
    guarded = strict_result()
    print(f"    校验拦截 : {not guarded.ok}")
    for line in (guarded.error or guarded.content).splitlines()[:4]:
        print("      " + line)

    try:
        out = check_after_removal()
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print("\n  【拆掉防护】只留 type / properties / required")
    print(f"    校验错误列表 = {out['errors']}   ← 空列表 = 放行")
    print(f"    严格版抛的异常: {out['type_error'] or '(没抛)'}")
    print(f"    带 **kwargs 版的返回: {out['lenient_out']}")
    print(f"    ^ 参数真的传进函数了吗？ {out['extra_seen']}   ← 期望 True")

    problems = []
    if out["errors"] != []:
        problems.append("拆掉防护后校验就该放行了，errors 应该是空列表")
    if "unit" not in (out["type_error"] or "") and "unexpected keyword" not in (out["type_error"] or ""):
        problems.append("严格版会抛 TypeError，文本里应带 'unit' / 'unexpected keyword'")
    if not out["extra_seen"]:
        problems.append("带 **kwargs 的函数会照单全收，lenient_out 里应该出现 'unit'")
    if "1+1 = 2" not in str(out["lenient_out"]):
        problems.append("带 **kwargs 的版本会把 unit 静默吞掉，正常算出 1+1 = 2")

    if problems:
        print("\n❌ 还不对：")
        for p in problems:
            print(f"      - {p}")
        return 1

    print("\n✅ 跑通了")
    print("   ★ 这是「护栏拆掉后问题反而更难查」的典型例子：")
    print("     · 开着防护    -> 执行**之前**拦住，错误信息含「未定义参数 + 允许的参数」")
    print("     · 拆掉+严格签名 -> 错误在调用**之后**才炸（TypeError 模型看不懂）")
    print("     · 拆掉+**kwargs -> 连炸都不炸，参数被静默收下，模型永远不知道自己错了")
    print("     第 ③ 种最危险：没有任何反馈，错误会一路漂到业务逻辑里。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
