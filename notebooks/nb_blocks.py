"""nb_blocks —— 课程 Notebook 的共享"积木"，保证 13 章风格一致。

为什么要抽这一层？
    13 个 Notebook 如果各写各的，读者会觉得像 13 个人写的。
    把重复出现的结构（标题、小结、自检、练习）做成函数，
    作者只需要专注**内容**，格式和基调自动统一。

用法：
    from notebooks.nb_blocks import header, objectives, checkpoint, summary

    nb = Notebook("第 01 章 · 最小 Agent 循环")
    header(nb, 1, "最小 Agent 循环", "Agent = 循环 + 工具 + 历史")
    ...
    checkpoint(nb, "01")
    nb.save(...)
"""

from __future__ import annotations

from .notebook_lib import Notebook

# 课程统一的"目标读者"说明。第 0 章会展开讲，后面每章开头简短带一句。
AUDIENCE_NOTE = (
    "> **写给谁看**：本 Notebook 面向**编程能力已具备、但工程经验刚起步**的读者。\n"
    "> 你熟悉写代码、刷算法题，所以这里不解释什么是循环、什么是字典；\n"
    "> 但会详细解释**为什么工程上要这么设计**、以及**踩过哪些坑**。\n"
    "> 类比会尽量贴近你熟悉的东西（数据结构、算法、OJ 评测）。"
)


def resolve_stage_module(chapter: str) -> str:
    """把章号（如 "01"）解析成真实的 stage 包名（如 "stages.stage01_agent_loop"）。

    ★ 为什么需要这一步？
        `stages/` 下的目录名是 `stage01_agent_loop` 这样的
        **章号 + 主题**，而不是纯章号。所以像 `f"stages.stage{chapter}"`
        这样拼出来的模块名（`stages.stage01`）根本不存在 ——
        自检单元会直接报 `ModuleNotFoundError`。

        这个坑很隐蔽：写代码的时候"看起来"完全合理，
        而且只有在**真的运行自检单元**时才会暴露。

    解析顺序：
        1. 精确匹配 `stage{chapter}_*` 目录；
        2. 退一步，只要目录名前缀是 `stage{chapter}`；
        3. 都找不到就返回拼出来的名字（让调用方报出清晰的错误）。
    """
    from pathlib import Path

    root = Path.cwd()
    while not (root / "stages").is_dir() and root.parent != root:
        root = root.parent

    stages_dir = root / "stages"
    ch = chapter.zfill(2) if chapter.isdigit() else chapter
    for pattern in (f"stage{ch}_*", f"stage{ch}"):
        for p in sorted(stages_dir.glob(pattern)):
            if p.is_dir() and (p / "demo.py").exists():
                return f"stages.{p.name}"
    return f"stages.stage{ch}"


def show_checks(title: str, module: str = "", chapter: str = "") -> bool:
    """在 Notebook 里运行某一章的 `run_checks()` 并打印通过情况。

    这个函数被 `checkpoint()` 生成的单元调用。它刻意做成"能用就行、不抛异常"：
    Notebook 里最忌讳因为一个辅助函数报错而打断读者的思路。

    参数
    ----
    title   : 显示用的标题，如 "第 01 章"
    module  : 形如 "stages.stage01_agent_loop"，省略 .demo 后缀
    chapter : 章号（用于自动解析模块名 + 拼命令行提示）
    """
    import importlib
    import io
    from contextlib import redirect_stdout

    # 模块名可以先从章号自动解析，避免调用方写错
    if not module and chapter:
        module = resolve_stage_module(chapter)
    if not module:
        print("（未指定模块）")
        return False

    try:
        mod = importlib.import_module(f"{module}.demo")
        importlib.reload(mod)
    except Exception as exc:
        print(f"❌ 无法导入 {module}.demo：{type(exc).__name__}: {exc}")
        print(f"   提示：请确认 stages/ 下存在对应的章节目录。")
        return False

    fn = getattr(mod, "run_checks", None)
    if not callable(fn):
        print(f"❌ {module}.demo 没有实现 run_checks()")
        return False

    # run_checks() 约定不打印输出，这里吞掉 stdout 以防万一
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            results = fn()
    except Exception as exc:
        print(f"❌ run_checks() 抛异常：{type(exc).__name__}: {exc}")
        return False

    passed = 0
    for item in results:
        name, okflag, detail = item
        passed += bool(okflag)
        mark = "✅" if okflag else "❌"
        suffix = f"   — {detail}" if detail else ""
        print(f"  {mark} {name}{suffix}")

    total = len(results)
    print()
    if passed == total:
        print(f"✅ {title} 自检全部通过（{total} 项）")
    else:
        print(f"❌ {title} 自检 {passed}/{total} 通过")
    if chapter:
        print(f"\n命令行等价形式：  py scripts\\run_all_checks.py {chapter}")
    return passed == total


def run_all_checks_summary() -> bool:
    """跑一遍全部章节的自检，打印汇总（第 00 章用）。

    刻意不 import scripts/build 之类的重型模块，只跑 run_checks() ——
    这样在 Notebook 里也就几百毫秒，不会让读者等。
    """
    import importlib
    import io
    from contextlib import redirect_stdout
    from pathlib import Path

    root = Path.cwd()
    while not (root / "stages").is_dir() and root.parent != root:
        root = root.parent

    stages = sorted(p.name for p in (root / "stages").glob("stage*")
                    if p.is_dir() and (p / "demo.py").exists())
    total = passed = 0
    rows: list[tuple[str, int, int]] = []

    for name in stages:
        try:
            mod = importlib.import_module(f"stages.{name}.demo")
            importlib.reload(mod)
            fn = getattr(mod, "run_checks", None)
            if not callable(fn):
                continue
            with redirect_stdout(io.StringIO()):
                res = fn()
        except Exception as exc:
            rows.append((name, 0, 1))
            total += 1
            print(f"  ❌ {name}: {type(exc).__name__}: {exc}")
            continue
        p = sum(1 for _, okflag, _ in res if okflag)
        passed += p
        total += len(res)
        rows.append((name, p, len(res)))

    print(f"{'章节':<26}{'通过':>6}{'总数':>6}")
    print("-" * 40)
    for name, p, n in rows:
        mark = "✅" if p == n else "❌"
        print(f"{mark} {name:<24}{p:>6}{n:>6}")
    print("-" * 40)
    print(f"{'合计':<26}{passed:>6}{total:>6}")
    print()
    if total and passed == total:
        print(f"✅ 全部章节验收通过（{total} 项断言）")
    else:
        print(f"⚠️  {passed}/{total} 项通过")
    return passed == total


def header(nb: Notebook, chapter: str, title: str, essence: str) -> Notebook:
    """每章统一的标题区。"""
    nb.md(f"""# 第 {chapter} 章 · {title}

> ### 一句话本质
> {essence}

---

{AUDIENCE_NOTE}

**怎么用这个 Notebook**：从上往下依次运行（`Shift+Enter`）。
每个代码单元都已经跑过一遍，输出是**真实结果**，你可以直接对照。
遇到"你应该看到"的说明，就和你的输出比一比 —— 不一样说明环境或版本有差异。
""")
    return nb


def objectives(nb: Notebook, items: list[str]) -> Notebook:
    """学完这章你能做到什么。"""
    body = "\n".join(f"- {x}" for x in items)
    nb.md(f"""## 学完这一章，你应该能做到

{body}
""")
    return nb


def section(nb: Notebook, index: str, title: str) -> Notebook:
    """小节标题。index 用 ①②③ 之类的序号。"""
    nb.md(f"""---

## {index} {title}
""")
    return nb


def checkpoint(nb: Notebook, chapter: str, notes: str = "", stage_module: str = "") -> Notebook:
    """每章末尾的自检单元。

    它做两件事：
      1. 真的去调用这一章的 `run_checks()`，让你看到验收标准的实时结果；
      2. 打印出等价的命令行，方便你离开 Notebook 后复现。

    参数
    ----
    chapter      : 两位章号，如 "01"
    notes        : 追加在说明里的补充内容
    stage_module : 可选，显式指定 stage 包名。省略时由
                   `resolve_stage_module()` 从章号自动解析 ——
                   **不要手写 `stages.stage01` 这种名字，它并不存在**。
    """
    extra = f"\n{notes}\n" if notes else ""
    module = stage_module or resolve_stage_module(chapter)
    nb.md(f"""---

## ✅ 自检：这一章我真的学会了吗？

下面这段代码会调用这一章的 `run_checks()` —— 也就是
`py scripts\\run_all_checks.py {chapter}` 背后的同一套断言。
{extra}
> 看到 `全部通过` 就说明**教学材料本身是好的**。
> 但注意：**它验的是材料，不是你**。你学会与否，取决于能不能独立做完下面的练习。
""")
    nb.code(f"""from notebooks.nb_blocks import show_checks
show_checks("第 {chapter} 章", "{module}", "{chapter}")""")
    return nb


def exercises(nb: Notebook, items: list[tuple[str, str]]) -> Notebook:
    """练习题区。items 是 [(题目 markdown, 可选提示 markdown)]。"""
    nb.md("""---

## 🏋️ 练习

> **说明**：练习不提供完整答案，但给了思路和验证方法。
> 做完之后建议跑一次 `py scripts\\run_all_checks.py <章号>`，
> 确认你没有把原来通过的东西改坏（这就是回归测试的意识）。
""")
    for i, (task, hint) in enumerate(items, 1):
        nb.md(f"### 练习 {i}\n\n{task}\n")
        if hint:
            nb.md(f"<details>\n<summary>点开看提示</summary>\n\n{hint}\n\n</details>\n")
    return nb


def summary(nb: Notebook, points: list[str], next_hint: str = "") -> Notebook:
    """收口：本章要点 + 下一章的引子。"""
    body = "\n".join(f"{i}. {p}" for i, p in enumerate(points, 1))
    tail = f"\n---\n\n**下一章**：{next_hint}\n" if next_hint else ""
    nb.md(f"""---

## 📌 本章要点

{body}
{tail}""")
    return nb


def pitfall_table(nb: Notebook, rows: list[tuple[str, str, str]]) -> Notebook:
    """坑位表：现象 / 根因 / 解法。工程经验主要靠这个传递。"""
    head = "| 现象 | 根本原因 | 解法 |\n|---|---|---|\n"
    body = "\n".join(f"| {a} | {b} | {c} |" for a, b, c in rows)
    nb.md(f"""### 常见坑（工程经验集中在这里）

{head}{body}
""")
    return nb


def setup_cell(nb: Notebook) -> Notebook:
    """统一的初始化单元：修好控制台编码 + 把项目根加进 sys.path + 装好 explain()。

    ★ 这个单元必须放在最前面、且必须执行 —— 否则 Windows 下 GBK 控制台
      打印中文/emoji 会直接抛 UnicodeEncodeError，把整个 Notebook 打断。
      （`.py` 版本里对应的是每个 demo 开头调用的 setup_console()。）

    ★ 顺便把 `explain()` 装进来：读者在任意一章看到不认识的函数/参数/返回值时，
      就地 `explain(那个东西)` 就能查，不用回头翻文档。
      这是"看到不认识的 API 怎么办"的标准答案。
    """
    nb.code("""# 初始化：把项目根目录加入 import 路径，修好控制台编码，并装好 explain() 查询工具
# （Windows 默认 GBK 控制台打印 emoji 会报 UnicodeEncodeError）
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import setup_console
setup_console()

# ★ 遇到看不懂的函数/参数/返回值，随时查：
#     explain(Agent)         解释 Agent 这个类（参数含义 + 返回 + 例子）
#     explain(StepRecord)    解释数据结构（字段逐个说明）
#     explain(run_once)      解释函数
#     explain()              列出框架全部公开 API（按层分组）
from notebooks.nb_explain import explain

print("项目根目录：", ROOT)
print("提示：遇到不认识的 API，随时 explain(名字) —— 例如 explain(run_once)")""")
    return nb
