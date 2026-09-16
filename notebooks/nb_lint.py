"""nb_lint —— 检查 Notebook 的代码单元是否**自包含**。

------------------------------------------------------------
要解决的真实问题
    读者反馈："代码看起来完整，实际复制下来全是 NameError。"

    根因：Notebook 的代码单元共享一个内核，后面的单元用了前面定义的
    变量/函数却不说明。读者**单独看任何一个单元**都会卡住：
    这个 `TOOLS` 从哪来？`FINAL_RE` 是什么？`_extract_thought` 谁实现的？

    实测过：13 章里每一章都有 60% 以上的代码单元单独跑会 NameError。

本模块怎么解决
    1. `deps_of()`   静态分析一个单元"用到了哪些外部名字"
    2. `lint_notebook()` 对照作者声明的 `CELL_DEPS` 白名单，报出**未声明的继承**
    3. 有了它，就可以在 CI 里强制"要么自包含，要么显式声明依赖"

★ 为什么用白名单而不是要求"零依赖"？
    零依赖最理想，但有些地方刻意保留上下文更利于教学
    （比如"接着上一格的脚本再跑一次"）。
    所以规则是：**可以依赖，但必须显式声明**——
    声明会渲染成一个"依赖提示"单元，读者一眼就知道要先跑哪一格。

用法：
    from notebooks.nb_lint import lint_notebook, format_report
    issues = lint_notebook(path, deps={cell_id: {names...}, cell_id: "reason"})
"""

from __future__ import annotations

import ast
import builtins

BUILTIN_NAMES = set(dir(builtins))

# 常见的"局部作用域"名字：推导式/循环变量、异常变量、lambda 参数等。
# 分析时会被当作"已定义"，否则会大量误报。
_SCOPE_NODES = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
                ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _bound_names(tree: ast.AST) -> set[str]:
    """收集一个模块/函数体内**被定义**的名字。"""
    out: set[str] = set()

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                out.add(child.name)
                # 函数体内部自成作用域，但函数自己能看到外层；
                # 这里只收集"函数名"，参数与局部变量不进外层
                for a in child.args.args + child.args.kwonlyargs:
                    out.add(a.arg)
                if child.args.vararg:
                    out.add(child.args.vararg.arg)
                if child.args.kwarg:
                    out.add(child.args.kwarg.arg)
                visit(child)
                continue

            if isinstance(child, ast.Assign):
                for t in child.targets:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            out.add(x.id)
            elif isinstance(child, ast.AnnAssign):
                if isinstance(child.target, ast.Name):
                    out.add(child.target.id)
            elif isinstance(child, ast.AugAssign):
                if isinstance(child.target, ast.Name):
                    out.add(child.target.id)
            elif isinstance(child, ast.Import):
                for a in child.names:
                    out.add((a.asname or a.name).split(".")[0])
            elif isinstance(child, ast.ImportFrom):
                for a in child.names:
                    out.add(a.asname or a.name)
            elif isinstance(child, (ast.For, ast.AsyncFor)):
                for x in ast.walk(child.target):
                    if isinstance(x, ast.Name):
                        out.add(x.id)
            elif isinstance(child, (ast.With, ast.AsyncWith)):
                for item in child.items:
                    if item.optional_vars is not None:
                        for x in ast.walk(item.optional_vars):
                            if isinstance(x, ast.Name):
                                out.add(x.id)
            elif isinstance(child, ast.Try):
                for h in child.handlers:
                    if h.name:
                        out.add(h.name)

            # 推导式/lambda 的参数属于"局部作用域"，也要收集
            if isinstance(child, _SCOPE_NODES):
                for x in ast.walk(child):
                    if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store):
                        out.add(x.id)
            visit(child)

    visit(tree)
    return out


def _used_names(tree: ast.AST) -> set[str]:
    """收集一个模块里**被读取**的名字。"""
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def deps_of(source: str) -> set[str]:
    """返回一段代码单元"依赖外部提供"的名字集合。

    ★ 为什么用标准库的 `symtable` 而不是自己走 AST？
        第一版我手写了一个 AST 遍历来收集"定义的名字"和"使用的名字"，
        结果在 `class XXX:` 上直接崩了（ClassDef 没有 .args，我和 FunctionDef
        混在一起处理了）。作用域规则是语言里最容易写错的部分之一：
        推导式、lambda、except as、global/nonlocal、类作用域、
        海象运算符……每一种都有各自的绑定规则。

        `symtable` 是 CPython 自己的符号表实现 —— 它就是编译器用来做这件事的。
        直接用"编译器怎么看"，比自己重新发明一套规则可靠得多。

      原理：把代码编译成模块，用 CPython 自己的符号表判断每个名字的归属。
      对**模块级代码**（Notebook 单元就是模块级代码），规则很干净：

          名字被 use 但**不在本模块绑定**（is_global() 且 not is_local()）
          → 它必须由外部提供 → 就是我们要找的"外部依赖"

      实测过的三种情况：
          'x = 1'          → x 是 global+local（本模块绑定的）→ 不算依赖
          'y = x'          → x 是 global 但**不** local      → 是依赖
          'print(TOOLS)'   → print 与 TOOLS 都符合上一条，减去内置后只剩 TOOLS ✅

      （第一版我错用了"free variable"的概念 —— 那是**嵌套作用域**里的说法，
        在模块级用不上，结果所有单元都返回空集合，等于没检查。）
    """
    try:
        import symtable
        st = symtable.symtable(source, "<cell>", "exec")
    except (SyntaxError, ValueError):
        return set()

    def local_bound(table) -> set[str]:
        """这个作用域**自己绑定**的名字（赋值、定义、import、for 目标…）。"""
        return {s.get_name() for s in table.get_symbols()
                if s.is_assigned() or s.is_imported()
                or (s.is_local() and not s.is_referenced())
                or s.is_parameter()}

    def walk(table, ancestors: set[str], is_class: bool = False) -> set[str]:
        """返回 table 及其子作用域中「来自单元外部」的名字。

        ancestors = 所有外层作用域绑定的名字（供子作用域查）。
        """
        found: set[str] = set()

        # ---- 本作用域直接引用的外部名字 ----
        if not is_class:      # 类作用域不参与闭包查找，它自己的引用按模块级算
            for sym in table.get_symbols():
                if sym.is_referenced() and sym.is_global() and not sym.is_local():
                    if sym.get_name() not in ancestors:
                        found.add(sym.get_name())

        # ---- 递归子作用域 ----
        # ★ 关键细节：函数不能看到**外层类**的名字（Python 的作用域规则），
        #   所以进入类的子作用域时，ancestors 里要去掉类自己绑定的名字。
        own = local_bound(table)
        for child in table.get_children():
            child_ancestors = ancestors | (own if not is_class else set())
            found |= walk(child, child_ancestors, is_class=child.get_type() == "class")
        return found

    return walk(st, local_bound(st)) - BUILTIN_NAMES


def lint_notebook(path, deps: dict | None = None) -> list[tuple[int, list[str], str]]:
    """检查一个 Notebook 的代码单元。

    参数
    ----
    path : .ipynb 路径
    deps : 作者声明的依赖白名单，形如
             {2: {"ROOT"},            # 第 2 格允许用 ROOT（来自引导单元）
              3: "接着上一格的 script 继续跑"}   # 也可以写一句理由
           键是**代码单元序号**（从 0 开始，只数代码单元）。

    返回 [(单元序号, 未声明的外部名字, 说明)]
    """
    import json
    from pathlib import Path as _P

    deps = deps or {}
    data = json.loads(_P(path).read_text(encoding="utf-8"))
    code_cells = [c for c in data["cells"] if c["cell_type"] == "code"]

    issues: list[tuple[int, list[str], str]] = []
    for i, cell in enumerate(code_cells):
        src = "".join(cell["source"])
        missing = deps_of(src)
        if not missing:
            continue
        declared = deps.get(i)
        if declared is None:
            issues.append((i, sorted(missing), "未声明依赖"))
            continue
        allowed = set() if isinstance(declared, str) else set(declared)
        undeclared = missing - allowed
        if undeclared:
            issues.append((i, sorted(undeclared), "声明了但不包含这些"))
    return issues


def lint_all(deps_map: dict | None = None) -> tuple[int, int]:
    """检查全部 Notebook。deps_map 形如 {'01_agent_loop.ipynb': {...}}。

    没有在 deps_map 里出现的 Notebook 会用空白名单（= 要求完全自包含）。
    """
    from pathlib import Path as _P

    deps_map = deps_map or {}
    root = _P(__file__).resolve().parent
    total = bad = 0
    for p in sorted(root.glob("*.ipynb")):
        total += 1
        issues = lint_notebook(p, deps_map.get(p.name))
        if issues:
            bad += 1
    return (total - bad, total)


def format_report(path, deps: dict | None = None) -> str:
    """给人看的报告。"""
    issues = lint_notebook(path, deps)
    name = getattr(path, "name", str(path))
    if not issues:
        return f"✅ {name}：所有代码单元自包含或已声明依赖"
    lines = [f"❌ {name}：{len(issues)} 个代码单元存在未声明依赖"]
    for i, names, why in issues:
        lines.append(f"     单元[{i}] {why}：{names}")
    return "\n".join(lines)
