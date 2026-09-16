"""生成全部 13 章的 Jupyter Notebook。

用法：
    py scripts\\build_notebooks.py                 # 生成全部
    py scripts\\build_notebooks.py --chapters 01 02
    py scripts\\build_notebooks.py --list          # 列出章节与生成状态
    py scripts\\build_notebooks.py --no-exec       # 只生成不执行（快速草稿）
    py scripts\\build_notebooks.py --check         # 只校验已生成的 .ipynb

------------------------------------------------------------
为什么用"生成器"而不是手写 .ipynb？
    1. `.ipynb` 是 JSON，手写 13 个文件根本没法维护（改一处要改 13 处）；
    2. 生成器可以**顺便执行每个单元并把真实输出嵌进去** ——
       读者不用运行就能看到结果，也不会出现"示例输出是编的"这种问题；
    3. Notebook 与 `.py` 版本的 demo 共享同一个 `core/` 框架，
       内容一旦不一致，`run_checks()` 的自检会立刻暴露。

章节内容一章一个文件：`nb0_foundation.py`（第 00 章）、`nb1_ch01.py` …
`nb12_ch13.py`（第 13 章）。文件名的数字只是区分用，**以每个文件里定义的
`build_NN()` 为准** —— 注册表就是这么映射的。
------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, code, fail, kv, note, ok, section, setup_console, warn,
)
from notebooks.notebook_lib import Notebook, summarize, validate_ipynb  # noqa: E402

NB_DIR = ROOT / "notebooks"

# 章号 -> (标题, 文件名, 内容模块, 工厂函数名)
# 文件名前缀决定排序，所以用两位数。
#
# 注：**13 章全部**已按 TEACHING_CONTRACT.md 重写：
#     · 逐步给（每个知识点在读者正好需要时出现）
#     · 开头保留 ⓪ 速查表当索引用
#     · 每个代码单元自包含，能单独运行（notebooks/nb_lint.py 机器校验）
#     · 代码单元高注释密度（几乎每行都说明"为什么"）
#
#     生成器源码一章一个文件（nbN_chNN.py），便于单独维护和并行编写。
REGISTRY: dict[str, tuple[str, str, str, str]] = {
    "00": ("模型和代码之间传什么", "00_setup.ipynb", "nb0_foundation", "build_00"),
    "01": ("最小 Agent 循环", "01_agent_loop.ipynb", "nb1_ch01", "build_01"),
    "02": ("工具系统与 JSON Schema", "02_tools.ipynb", "nb2_ch02", "build_02"),
    "03": ("ReAct 提示工程", "03_react_prompt.ipynb", "nb3_ch03", "build_03"),
    "04": ("规划与任务分解", "04_planning.ipynb", "nb3_ch04", "build_04"),
    "05": ("记忆与上下文工程", "05_memory.ipynb", "nb4_ch05", "build_05"),
    "06": ("RAG 检索增强", "06_rag.ipynb", "nb5_ch06", "build_06"),
    "07": ("反思与自我修正", "07_reflection.ipynb", "nb6_ch07", "build_07"),
    "08": ("多智能体协作", "08_multi_agent.ipynb", "nb7_ch08", "build_08"),
    "09": ("工作流与状态机", "09_workflow.ipynb", "nb8_ch09", "build_09"),
    "10": ("评估与可观测性", "10_evaluation.ipynb", "nb9_ch10", "build_10"),
    "11": ("安全护栏", "11_guardrails.ipynb", "nb10_ch11", "build_11"),
    "12": ("成本与延迟优化", "12_cost_latency.ipynb", "nb11_ch12", "build_12"),
    "13": ("生产化部署", "13_production.ipynb", "nb12_ch13", "build_13"),
}

# 生成顺序（按章号）
ORDER: list[str] = [f"{i:02d}" for i in range(0, 14)]


def build_one(chapter: str, execute: bool = True) -> tuple[bool, str]:
    """生成单个章节的 Notebook。返回 (是否成功, 说明)。"""
    if chapter not in REGISTRY:
        return False, f"未知章号 {chapter}"
    title, filename, module_name, factory = REGISTRY[chapter]

    try:
        mod = importlib.import_module(f"notebooks.{module_name}")
    except ImportError as exc:
        return False, f"内容模块 notebooks.{module_name} 尚未提供（{exc}）"

    fn = getattr(mod, factory, None)
    if not callable(fn):
        return False, f"notebooks.{module_name} 缺少工厂函数 {factory}()"

    nb = fn()
    if not isinstance(nb, Notebook):
        return False, f"{factory}() 必须返回 Notebook 对象，实际是 {type(nb).__name__}"

    if execute:
        good, msg = nb.verify(workdir=ROOT)
        if not good:
            return False, f"执行失败：{msg}"

    path = nb.save(NB_DIR / filename)
    good, msg = validate_ipynb(path)
    if not good:
        return False, f"生成的文件不合法：{msg}"
    return True, msg


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成课程 Jupyter Notebook")
    parser.add_argument("chapters", nargs="*", help="只生成指定章号，如 01 02")
    parser.add_argument("--chapters", dest="chapters_opt", nargs="*", default=None,
                        help="只生成指定章号（显式写法）")
    parser.add_argument("--list", "-l", action="store_true", help="列出章节与生成状态")
    parser.add_argument("--no-exec", action="store_true", help="只生成不执行代码单元")
    parser.add_argument("--check", action="store_true", help="只校验已生成的 .ipynb")
    args = parser.parse_args(argv)

    setup_console()

    wanted = args.chapters_opt if args.chapters_opt is not None else args.chapters
    todo = [c.zfill(2) for c in wanted] if wanted else list(ORDER)

    if args.list:
        banner("课程 Jupyter Notebook", f"共 {len(REGISTRY)} 章")
        for ch in ORDER:
            title, filename, _, _ = REGISTRY[ch]
            p = NB_DIR / filename
            if p.exists():
                info = summarize(p)
                status = (f"✅ {info['markdown']} 讲解 / {info['code']} 代码 "
                          f"（已执行 {info['executed']}）")
            else:
                status = "— 未生成"
            print(f"  [{ch}] {title:<26} {filename:<26} {status}")
        return 0

    if args.check:
        banner("校验已生成的 Notebook", f"共 {len(REGISTRY)} 章")
        n_ok = n_bad = 0
        for ch in ORDER:
            _, filename, _, _ = REGISTRY[ch]
            p = NB_DIR / filename
            if not p.exists():
                warn(f"[{ch}] {filename} 未生成")
                n_bad += 1
                continue
            good, msg = validate_ipynb(p)
            if good:
                ok(f"[{ch}] {filename} — {msg}")
                n_ok += 1
            else:
                fail(f"[{ch}] {filename} — {msg}")
                n_bad += 1
        print()
        return 0 if n_bad == 0 else 1

    banner("生成课程 Jupyter Notebook",
           f"共 {len(todo)} 章 | 执行代码单元：{'否' if args.no_exec else '是'}")

    n_ok = n_bad = 0
    for ch in todo:
        title = REGISTRY.get(ch, ("?",))[0]
        good, msg = build_one(ch, execute=not args.no_exec)
        if good:
            ok(f"[{ch}] {title} — {msg}")
            n_ok += 1
        else:
            fail(f"[{ch}] {title} — {msg}")
            n_bad += 1

    print()
    print("=" * 68)
    kv("成功", n_ok)
    kv("失败", n_bad)
    print("=" * 68)
    if n_bad == 0:
        ok("全部 Notebook 生成完毕，且每个代码单元都真的跑通了 ✅")
        note("打开方式：jupyter lab / VS Code 直接打开 notebooks/*.ipynb")
        return 0
    fail("有 Notebook 生成失败，请看上面的报错。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
