r"""第 02 章 · 练习 3 / 5 · 给 AST 白名单加 DoS 防护并验证

【要做什么】
  给 AST 白名单加 DoS 防护并验证。

  现有实现对 `**` 的指数做了限制。试试这些，看白名单是否足够：
  `9**9**9`、`9**999999`、`sqrt(sqrt(sqrt(9**700)))`。

  想一个更通用的防护方案。

【已经给你了】
  · `safe_calc(expr)`         —— AST 白名单计算器，求值部分**已经写好**，
                                 只空中间那道「资源耗尽」防护
  · `TRICKY`                  —— 题目里的三个表达式 + 两个正常表达式
  · `GUARD_ERROR`             —— 资源耗尽的错误里统一带上这个词，验证靠它识别
  · `try_calc(expr)`          —— 帮你接住异常，返回 (是否被拒绝, 错误或结果)
  · `math` / `ast`            —— 已经 import 好

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch02_tools\ex3_dos_guard.py
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
import math                                                   # noqa: E402

GUARD_ERROR = "表达式太复杂"      # ★ 你写的防护被触发时，错误信息里必须包含这个词

NODE_BUDGET = 25                 # 允许经过多少个 AST 节点（正常表达式 10 个以内够用）

TRICKY = [
    # (表达式, 期望结果)
    ("9**9**9", "拒绝"),
    ("9**999999", "拒绝"),
    ("sqrt(sqrt(sqrt(9**700)))", "拒绝"),
    ("1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1", "拒绝"),
    ("2**10", "算得出来"),
    ("sqrt(16) + (12+8)*3/4 - 3", "算得出来"),
]


class Budget:
    """给你数「这次求值已经花掉多少」的小对象。

    · `tick()`  记一次消耗（每经过一个 AST 节点就调一次）
    · `.used`   已经用掉多少
    · `NODE_BUDGET` 是上限

    提示：你可以直接把 `tick()` 写成"超了就 raise"，也可以让它只记数、
    由求值代码自己判断 —— 两种都行，只要错误信息里带 GUARD_ERROR。
    """

    def __init__(self, budget: int = NODE_BUDGET):
        self.used = 0
        self.limit = budget

    def tick(self) -> None:
        """TODO ── 记一次消耗；超过 self.limit 就抛 ValueError（错误信息要含 GUARD_ERROR）。

        两行就够了：
            self.used += 1
            if self.used > self.limit: raise ValueError(f"{GUARD_ERROR}……")
        （只要错误里带 GUARD_ERROR 这个词就能过验证；措辞随你写）

        【这一条拦的是哪一类？】
          像 `1+1+1+…`（几十项）这种表达式：**没有任何幂运算**，
          所以"指数过大"那种逐运算符特判完全抓不到它，
          但它的 AST 节点数会超预算 —— 这正是"限制消耗"比"特判运算符"更通用的地方。

        【那 9**9**9 呢？】
          `9**9**9` 在 Python 里是 `9**(9**9)`：先算 9**9 = 387420489，
          再要算 9**387420489** —— 这一步会把你机器算到天荒地老。
          而它的 AST 只有 4 个节点，光看结构看不出「计算量爆炸」，
          所以它主要还是靠"幂运算规模"那道判断拦下（两重防护一起才稳）：
            ① 限制 AST 节点总数（本练习的做法）
            ② 限制单次幂运算的规模 / 计算耗时
            ③ 真实系统里还要靠超时 + 进程隔离
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 3 · TODO  Budget.tick 还没有写完")
        # ↑↑↑ 你的答案 ↑↑↑


def safe_calc(expr: str) -> str:
    """安全计算数学表达式（AST 白名单 + 资源防护）。不允许的语法抛 ValueError。

    ★ 顺便注意本题的顺序问题：`b.tick()` 只数节点、不做运算，
      所以它必须放在真正运算的**前面**。顺序写反的话，
      `sqrt(9**700)` 会在预算生效之前先去算那个巨大的整数，
      直接抛 `OverflowError: int too large to convert to float`。
    """
    allowed_bin = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
                   ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b,
                   ast.FloorDiv: lambda a, b: a // b, ast.Mod: lambda a, b: a % b,
                   ast.Pow: lambda a, b: a ** b}
    allowed_func = {"sqrt": math.sqrt, "abs": abs, "round": round,
                    "floor": math.floor, "ceil": math.ceil}

    def ev(node, b: Budget):
        if isinstance(node, ast.Expression):
            return ev(node.body, b)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
                b.tick()
                return node.value
            raise ValueError(f"不支持的常量类型: {type(node.value).__name__}")
        if isinstance(node, ast.BinOp):
            op = allowed_bin.get(type(node.op))
            if op is None:
                raise ValueError(f"不支持的运算符: {type(node.op).__name__}")
            left, right = ev(node.left, b), ev(node.right, b)
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
                raise ValueError("除数不能为 0")
            if isinstance(node.op, ast.Pow):
                # 幂是最容易"算力爆炸"的运算符，用两个条件把它卡死：
                #   ① 指数绝对值太大         -> 9**999999
                #   ② 左操作数位数 × 指数太大 -> 9**9**9（先算出 9**9，再拿它当指数）
                if abs(right) > 1000:
                    raise ValueError("指数过大，拒绝计算（防止算力耗尽）")
                if (isinstance(left, int) and isinstance(right, int)
                        and left not in (0, 1, -1)
                        and left.bit_length() * abs(right) > 2000):
                    raise ValueError("幂运算规模过大，拒绝计算（防止算力耗尽）")
            b.tick()                      # ★ 先数节点、再做运算 —— 顺序不能反
            return op(left, right)
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                return -ev(node.operand, b)
            if isinstance(node.op, ast.UAdd):
                return ev(node.operand, b)
            raise ValueError("不支持的一元运算符")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in allowed_func:
                raise ValueError(f"不允许调用 {getattr(node.func, 'id', '?')}")
            if node.keywords:
                raise ValueError("不支持关键字参数")
            b.tick()
            # ★ 生产实现要注意：精度损失会抛 OverflowError。
            #   比如 sqrt(9**700) 转 float 时超出双精度上限 —— 它同样是拒绝理由，
            #   但要翻译成 ValueError，否则调用方按 ValueError 处理会漏接。
            try:
                return allowed_func[node.func.id](*[ev(a, b) for a in node.args])
            except OverflowError:
                raise ValueError("数值超出浮点范围，拒绝计算（防止精度/资源问题）") from None
        raise ValueError(f"表达式里出现不允许的语法: {type(node).__name__}")

    tree = ast.parse(expr, mode="eval")
    # 「先数节点、再动手」：AST 的节点数是**静态**的，算之前就能数出来。
    # 所以预算取「固定上限」和「这棵树的节点数」里更小的那个 ——
    # 表达式一旦大到超过预算，还没开始算就已经注定被拒。
    budget = Budget(budget=min(NODE_BUDGET, sum(1 for _ in ast.walk(tree))))
    value = ev(tree, budget)
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return f"{expr} = {value}"


def try_calc(expr: str):
    """跑一次 safe_calc，返回 (是否被拒绝, 错误信息 或 结果)。"""
    try:
        return False, safe_calc(expr)
    except ValueError as exc:
        return True, str(exc)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def other_idea() -> str:
    """TODO ── 想一个**比逐运算符特判更通用**的防护方案，写下来。

    提示：逐个运算符特判是补不完的（这个练习就是证据：
      `9**999999` 被指数限制挡住了，但 `9**9**9` 的算力爆炸藏在
      「先算一次幂、再拿它当指数」里；换一种写法还能绕过别的特判）。
    写清：① 你打算限制什么（节点数 / 耗时 / 结果规模 / …）
          ② 为什么它比"再补一个 if"更通用
          ③ 它的代价是什么（误伤？需要额外机制？）

    返回你的一段结论（写 30 个字以上，不许返回空串）。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 3 · TODO  other_idea 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 02 章 · 练习 3 · 表达式也会 DoS")
    print("=" * 68)
    print(f"\n  AST 节点预算 = {NODE_BUDGET}")

    print("\n  逐个试（超预算的会打印被拒绝的原因）：")
    results = {}
    for expr, expect in TRICKY:
        try:
            blocked, detail = try_calc(expr)
        except NotImplementedError as exc:
            print(f"\n⬜ 还没写：{exc}")
            return 0
        results[expr] = (blocked, detail)
        mark = "拒绝" if blocked else "算出"
        print(f"    {expr:<28} [{mark}] {detail[:60]}")

    # 先分清"还没写"和"写错了"：两种典型现象都是"正常表达式被拦/怪表达式被放行"
    blocked_simple = results["2**10"][0]
    traps = [e for e, want in TRICKY if want == "拒绝"]
    fired = [e for e in traps if results[e][0] and GUARD_ERROR in results[e][1]]
    if blocked_simple and not fired:
        print(f"\n⬜ 还没写：练习 3 · TODO  Budget.tick 还没有写完")
        print("   （所有表达式都被拦住了 —— tick() 还是那句 raise NotImplementedError）")
        return 0

    for expr, expect in TRICKY:
        blocked, _ = results[expr]
        if blocked != (expect == "拒绝"):
            print(f"\n❌ {expr} 期望「{expect}」，实际「{'拒绝' if blocked else '算出'}」")
            print("   预算内的正常表达式要算得出来，超预算的必须抛带 GUARD_ERROR 的 ValueError")
            return 1

    if not fired:
        print(f"\n❌ 三个陷阱表达式里，至少要有**一个**是被你写的节点预算拦下的"
              f"（错误信息里含 {GUARD_ERROR!r}）")
        print("   现在它们都是被原有的『指数过大』拦下的 —— 说明 Budget.tick() 还没生效。")
        return 1
    print(f"\n  被你的节点预算拦下：{fired}")
    print(f"  （另外 {len(traps) - len(fired)} 个是原有的『指数过大 / 幂运算规模过大』先拦的 ——")
    print("    两重防护一起在起作用，这是有意的：单靠一层都可能被绕过）")

    try:
        idea = other_idea()
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print(f"\n  你的通用方案（{len(str(idea))} 字）：")
    for line in str(idea).splitlines():
        print("      " + line)
    if len(str(idea).strip()) < 30:
        print("\n❌ 写得太短 —— 要说清「限制什么 + 为什么通用 + 代价」")
        return 1

    print("\n✅ 跑通了")
    print("   ★ 结论：逐运算符特判补不完。真正通用的是**限制消耗**：")
    print("     AST 节点数 / 计算耗时 / 结果规模 —— 真实系统还要外加超时 + 进程隔离。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
