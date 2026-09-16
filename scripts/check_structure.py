"""课程结构校验：检查每个章节是否符合课程契约。

用法：
    py scripts\\check_structure.py           # 检查全部章节
    py scripts\\check_structure.py 04 05     # 只检查指定章

与 run_all_checks.py 的分工：
    check_structure.py  静态检查（文件齐全？能 import？契约方法在不在？）
    run_all_checks.py   动态检查（跑 run_checks()，验证验收标准真的通过）

为什么要分开？
    结构问题会让动态检查整个崩掉，报错信息还埋在 traceback 里。
    先把结构问题单独揪出来，排查成本低得多。
    （这不是理论 —— 本课程开发过程中就出现过语法错误导致整章无法导入。）
"""

from __future__ import annotations

import argparse
import ast
import importlib
import io
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, check, code, fail, kv, note, ok, section, setup_console, warn,
)

# demo.py 必须定义的模块级名字
REQUIRED_NAMES = ["SECTIONS", "run_checks", "main"]
# 每个 stage 目录必须有的文件
REQUIRED_FILES = ["__init__.py", "demo.py", "README.md"]
# README 必须包含的章节标题关键词
README_SECTIONS = [
    ("一句话本质", "一句话本质"),
    ("先看问题", "先看问题"),
    ("原理", "原理"),
    ("动手实现", "动手实现"),
    ("跑起来", "跑起来"),
    ("工程要点", "工程要点"),
    ("练习", "练习"),
    ("验收标准", "验收标准"),
]
# run_checks 返回的检查项数量下限（太少说明验收覆盖不足）
MIN_CHECKS = 8


def discover() -> list[Path]:
    """发现所有章节目录。

    ★ 刻意**不**过滤"是否有 demo.py"。
      过滤会让不完整的章节从检查清单里消失，造成"假绿"——
      自检显示全部通过，但那一章根本没被检查。
      缺什么文件由 check_files() 明确报错，绝不静默跳过。
    """
    return sorted(p for p in (ROOT / "stages").glob("stage*")
                  if p.is_dir() and p.name != "__pycache__")


def check_all_syntax(stage: Path) -> list[tuple[str, bool, str]]:
    """扫描该章**所有** .py 文件，而不是只查 demo.py。

    为什么要扫全部？
        课程开发中最常见的低级错误是"中文引号写错导致 SyntaxError"，
        而 Python 一次只报一个文件。逐个 import 排查很慢 ——
        一次性列出所有语法错误的文件与行号，排查成本立刻降下来。
        （这不是假设：本课程开发过程中有 3 个章节反复踩这个坑。）
    """
    bad: list[str] = []
    checked = 0
    for py in sorted(stage.rglob("*.py")):
        checked += 1
        try:
            ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as exc:
            bad.append(f"{py.name}:{exc.lineno} {exc.msg}")
    return [(f"全部 {checked} 个 .py 文件语法正确", not bad,
             ("；".join(bad[:4]) if bad else ""))]


def check_syntax(path: Path) -> tuple[bool, str]:
    """用 ast 解析，比 import 更快且不执行代码。"""
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        return True, ""
    except SyntaxError as exc:
        # 语法错误是最常见的结构问题，给出精确行号和原文
        line = (exc.text or "").rstrip()
        return False, f"第 {exc.lineno} 行: {exc.msg}\n      {line}"


def check_files(stage: Path) -> list[tuple[str, bool, str]]:
    results = []
    for fname in REQUIRED_FILES:
        p = stage / fname
        results.append((f"存在 {fname}", p.exists(),
                        "" if p.exists() else "缺失"))
    return results


def check_readme(stage: Path) -> list[tuple[str, bool, str]]:
    readme = stage / "README.md"
    if not readme.exists():
        return []
    text = readme.read_text(encoding="utf-8", errors="replace")
    results = []
    for label, keyword in README_SECTIONS:
        results.append((f"README 含「{label}」", keyword in text, ""))
    # 篇幅下限：太短的 README 大概率是敷衍的
    lines = len(text.splitlines())
    results.append((f"README 篇幅充足（{lines} 行）", lines >= 80, f"实际 {lines} 行"))
    return results


def check_demo(stage: Path, prefix: str) -> list[tuple[str, bool, str]]:
    """静态解析 demo.py，确认契约名字都在。"""
    results: list[tuple[str, bool, str]] = []
    tree = ast.parse((stage / "demo.py").read_text(encoding="utf-8"))

    assigned = set()
    funcs = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    assigned.add(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assigned.add(node.target.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.add(node.name)

    for name in REQUIRED_NAMES:
        present = name in assigned or name in funcs
        results.append((f"定义了 {name}", present, "" if present else "缺失"))

    # main 必须有 argv 参数，否则无法被测试/程序化调用
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            has_argv = any(a.arg == "argv" for a in node.args.args)
            results.append(("main(argv=None) 签名正确", has_argv,
                            "" if has_argv else "缺少 argv 参数"))

    # 必须调用 setup_console，否则 Windows GBK 下中文/emoji 会崩
    src = (stage / "demo.py").read_text(encoding="utf-8")
    results.append(("调用了 setup_console()", "setup_console" in src,
                    "" if "setup_console" in src else "Windows 下会因 GBK 编码报错"))
    return results


def check_contract(stage: Path) -> list[tuple[str, bool, str]]:
    """真正 import 并调用 run_checks()，验证契约与速度。"""
    results: list[tuple[str, bool, str]] = []
    module_name = f"stages.{stage.name}.demo"

    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            mod = importlib.import_module(module_name)
            importlib.reload(mod)
    except Exception:
        return [("demo.py 可导入", False, traceback.format_exc(limit=3).strip()
                 .splitlines()[-1])]

    results.append(("demo.py 可导入", True, ""))

    fn = getattr(mod, "run_checks", None)
    if not callable(fn):
        return results + [("run_checks 可调用", False, "不存在或不可调用")]
    results.append(("run_checks 可调用", True, ""))

    import time
    t0 = time.perf_counter()
    try:
        with redirect_stdout(buf):
            res = fn()
    except Exception:
        return results + [("run_checks() 执行不抛异常", False,
                           traceback.format_exc(limit=4).strip().splitlines()[-1])]
    elapsed = time.perf_counter() - t0

    results.append(("run_checks() 执行不抛异常", True, ""))
    results.append((f"耗时 < 1s（实际 {elapsed * 1000:.0f}ms）", elapsed < 1.0,
                    "" if elapsed < 1.0 else "太慢，会影响整体自检体验"))

    # 返回格式：list[(str, bool, str)]
    shape_ok = isinstance(res, list) and len(res) > 0
    if shape_ok:
        for item in res:
            if not (isinstance(item, tuple) and len(item) == 3
                    and isinstance(item[0], str) and isinstance(item[1], bool)):
                shape_ok = False
                break
    results.append(("run_checks() 返回 list[(str, bool, str)]", shape_ok,
                    f"收到 {type(res).__name__}，{len(res) if isinstance(res, list) else '?'} 项"))
    results.append((f"检查项 >= {MIN_CHECKS} 项",
                    isinstance(res, list) and len(res) >= MIN_CHECKS,
                    f"实际 {len(res) if isinstance(res, list) else '?'} 项"))

    # run_checks 不应该往 stdout 打印（会被自检器捕获，污染输出）
    leaked = buf.getvalue().strip()
    results.append(("run_checks() 不打印输出", not leaked,
                    (f"泄漏 {len(leaked)} 字符" if leaked else "")))
    return results


def check_one(stage: Path, quiet: bool) -> tuple[int, int]:
    prefix = stage.name[len("stage"):][:2]
    print(f"\n  ── [{prefix}] {stage.name} " + "─" * max(0, 40 - len(stage.name)))

    results: list[tuple[str, bool, str]] = []

    # 1) 语法（最先做，因为语法错会让后面全部失败）
    demo_path = stage / "demo.py"
    if not demo_path.exists():
        # 材料不完整：明确报错，不再往下走（但必须出现在结果里，不能静默跳过）
        results.append(("存在 demo.py", False, "缺失 —— 该章无法被验收"))
        for name, passed, detail in results:
            check(name, passed, detail)
        return (0, 1)

    syntax_ok, msg = check_syntax(demo_path)
    results.append(("demo.py 语法正确", syntax_ok, "" if syntax_ok else msg))
    if not syntax_ok:
        for name, passed, detail in results:
            check(name, passed, detail)
        return (0, 1)

    # 2) 全文件语法扫描（一次列出该章所有语法错误）
    results += check_all_syntax(stage)

    results += check_files(stage)
    results += check_demo(stage, prefix)
    results += check_readme(stage)
    results += check_contract(stage)

    passed = 0
    for name, okflag, detail in results:
        passed += okflag
        if quiet and okflag:
            continue
        check(name, okflag, detail)
    return (passed, len(results))


def check_notebook_freshness() -> tuple[int, int]:
    """检查 Notebook 产物是不是比生成源码旧（= 被编辑器旧内容覆盖了）。

    ★ 真实场景：
        我在改生成器源码并重新生成 Notebook，而你同时用 VS Code 开着那个
        .ipynb。你一切换窗口 / 一保存，编辑器缓冲区里的**旧内容**就会写回磁盘，
        静默覆盖掉新版。文件看起来正常，内容却退回去了。

        这条检查专门抓这种情况：源码比产物新 → 立刻报出来。
        修复办法永远是同一条：重新跑 build_notebooks.py。
    """
    import sys as _sys
    if str(ROOT) not in _sys.path:
        _sys.path.insert(0, str(ROOT))
    from notebooks.notebook_lib import stale_notebooks

    stale = stale_notebooks(ROOT)
    if not stale:
        ok("所有 Notebook 产物都是最新的")
        return 1, 1

    for filename, why in stale:
        fail(f"{filename} 已过期：{why}")
    note("修复：py scripts\\build_notebooks.py")
    note("预防：看 Notebook 时关掉 VS Code 的自动保存，或把文件设为只读")
    return 0, len(stale)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验章节结构是否符合课程契约")
    parser.add_argument("chapters", nargs="*", help="只检查指定章号，如 04 05")
    parser.add_argument("--quiet", "-q", action="store_true", help="只显示失败项")
    args = parser.parse_args(argv)

    setup_console()
    stages = discover()
    wanted = [c.zfill(2) for c in args.chapters] if args.chapters else None
    todo = [s for s in stages
            if wanted is None or s.name[len("stage"):][:2] in wanted]

    banner("课程结构校验", f"共 {len(todo)} 个章节 | 契约：SECTIONS / run_checks() / main(argv)")

    total_passed = total = 0
    bad: list[str] = []
    for stage in todo:
        p, n = check_one(stage, args.quiet)
        total_passed += p
        total += n
        if p < n:
            bad.append(stage.name[len("stage"):][:2])

    # 额外一层：Notebook 产物是不是比生成源码旧（被编辑器旧内容覆盖过）
    if wanted is None:
        section("Notebook 产物新鲜度", "★")
        np_, nt = check_notebook_freshness()
        total_passed += np_
        total += nt
        if np_ < nt:
            bad.append("Notebook-过期")

    print()
    print("=" * 68)
    kv("检查项总数", total)
    kv("通过", total_passed)
    kv("失败", total - total_passed)
    print("=" * 68)

    if total == total_passed:
        ok("全部章节结构合规 ✅")
        note("下一步：py scripts\\run_all_checks.py  （跑真正的验收标准）")
        return 0
    fail(f"结构不合规：{bad}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
