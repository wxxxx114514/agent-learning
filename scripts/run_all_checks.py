"""一键自检：跑遍所有章节的验收标准。

用法：
    py scripts\\run_all_checks.py              # 跑全部
    py scripts\\run_all_checks.py 01 02 03     # 只跑指定章
    py scripts\\run_all_checks.py --quiet      # 只打印失败项与总结
    py scripts\\run_all_checks.py --list       # 列出已安装章节

----------------------------------------
契约（每个 stage 的 demo.py 必须满足）：
    run_checks() -> list[tuple[str, bool, str]]
        (检查项名称, 是否通过, 补充说明)

为什么用这个契约？
    因为"验收标准"必须是**可执行**的。写在 README 里的勾选框人人都会打，
    但只有跑得起来的断言才能证明你真的学会了。
----------------------------------------
"""

from __future__ import annotations

import argparse
import importlib
import io
import sys
import time
import traceback
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, code, fail, kv, note, ok, section, setup_console, warn,
)

# 章节显示名（顺序即学习顺序）
CHAPTER_TITLES = {
    "01": "最小 Agent 循环",
    "02": "工具系统与 JSON Schema",
    "03": "ReAct 提示工程",
    "04": "规划与任务分解",
    "05": "记忆与上下文工程",
    "06": "RAG 检索增强",
    "07": "反思与自我修正",
    "08": "多智能体协作",
    "09": "工作流与状态机",
    "10": "评估与可观测性",
    "11": "安全护栏",
    "12": "成本与延迟优化",
    "13": "生产化部署",
}


def discover() -> list[tuple[str, str, Path]]:
    """发现所有已安装章节，返回 [(编号, 模块名, 目录)]。

    ★ 这里有一个必须避免的陷阱：**不能只挑"有 demo.py 的目录"**。

      最初的实现是 `if not (d / "demo.py").exists(): continue`，看起来无害，
      实际会造成"假绿"：一个章节如果漏了 demo.py，它不会被报错，
      而是**从检查清单里彻底消失** —— 整套自检显示"全部通过"，
      但那一章其实根本不存在。

      生产环境里这类"静默跳过"是最危险的失败模式：
      覆盖率看着是 100%，实际漏检的东西你永远不知道。

      所以现在的规则是：**只要目录叫 stageNN_xxx，就必须被检查**。
      缺文件 → 明确报错（见 run_one 里的存在性检查），绝不静默跳过。
    """
    found: list[tuple[str, str, Path]] = []
    for d in sorted((ROOT / "stages").glob("stage*")):
        if not d.is_dir() or d.name == "__pycache__":
            continue
        # 目录名形如 stageNN_xxx；不符合命名的目录会被报告为"命名不规范"
        prefix = d.name[len("stage"):][:2]
        found.append((prefix, f"stages.{d.name}.demo", d))
    return found


def run_one(prefix: str, module_name: str, quiet: bool) -> tuple[int, int]:
    """跑一个章节的自检，返回 (通过数, 总数)。"""
    title = CHAPTER_TITLES.get(prefix, "")
    if not quiet:
        section(f"第 {prefix} 章 · {title}", f"[{prefix}]")

    # ★ 先做存在性检查：缺文件必须报错，不能静默跳过（否则就是"假绿"）
    stage_dir = ROOT / "stages" / module_name.split(".")[1]
    missing = [f for f in ("__init__.py", "demo.py", "README.md")
               if not (stage_dir / f).exists()]
    if missing:
        fail(f"第 {prefix} 章材料不完整，缺少：{missing}")
        note(f"目录：{stage_dir}")
        return (0, 1)

    # demo 里可能有大量讲解输出（print）。检查阶段我们把它们吞掉，
    # 只保留我们自己的报告，输出才干净。
    buf = io.StringIO()
    try:
        mod = importlib.import_module(module_name)
        importlib.reload(mod)  # 保证每次都是干净状态
    except Exception:
        fail(f"导入 {module_name} 失败")
        code(traceback.format_exc(limit=4).strip(), indent=4)
        return (0, 1)

    fn = getattr(mod, "run_checks", None)
    if fn is None:
        fail(f"{module_name} 没有实现 run_checks()（违反课程契约）")
        return (0, 1)

    t0 = time.perf_counter()
    try:
        with redirect_stdout(buf):
            results = fn()
    except Exception:
        fail(f"{module_name}.run_checks() 抛异常")
        code(traceback.format_exc(limit=6).strip(), indent=4)
        return (0, 1)
    elapsed = (time.perf_counter() - t0) * 1000

    passed = 0
    if not results:
        fail("run_checks() 返回空列表")
        return (0, 1)

    for item in results:
        try:
            name, okflag, detail = item
        except Exception:
            fail(f"检查项格式错误（应为 3 元组）: {item!r}")
            continue
        okflag = bool(okflag)
        passed += okflag
        if quiet and okflag:
            continue
        mark = "  ✅" if okflag else "  ❌"
        suffix = f"   — {detail}" if detail else ""
        print(f"{mark} {name}{suffix}")

    if not quiet:
        kv("耗时", f"{elapsed:.0f}ms")
        kv("结果", f"{passed}/{len(results)} 通过")
    return (passed, len(results))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跑遍所有章节的验收标准")
    parser.add_argument("chapters", nargs="*", help="只跑指定章号，如 01 02")
    parser.add_argument("--quiet", "-q", action="store_true", help="只打印失败项与总结")
    parser.add_argument("--list", "-l", action="store_true", help="列出已安装章节")
    args = parser.parse_args(argv)

    setup_console()
    stages = discover()

    if args.list:
        banner("已安装章节")
        for prefix, module, _ in stages:
            print(f"  [{prefix}] {CHAPTER_TITLES.get(prefix, '?'):<20} {module}")
        missing = [k for k in CHAPTER_TITLES if k not in {p for p, _, _ in stages}]
        if missing:
            warn(f"未安装章节：{missing}")
        return 0

    if not stages:
        fail("没有发现任何章节。请确认 stages/ 目录下有 stageNN_*/demo.py")
        return 1

    wanted = [c.zfill(2) for c in args.chapters] if args.chapters else None
    todo = [s for s in stages if wanted is None or s[0] in wanted]
    if not todo:
        fail(f"没有匹配的章节：{args.chapters}")
        return 1

    banner("Agent 开发课程 · 一键自检",
           f"共 {len(todo)} 个章节 | 契约：run_checks() -> list[(name, passed, detail)]")

    total_passed = total = 0
    failed_chapters: list[str] = []
    t0 = time.perf_counter()

    for prefix, module, _ in todo:
        p, n = run_one(prefix, module, args.quiet)
        total_passed += p
        total += n
        if p < n:
            failed_chapters.append(prefix)

    elapsed = time.perf_counter() - t0
    print()
    print("=" * 68)
    kv("检查项总数", total)
    kv("通过", total_passed)
    kv("失败", total - total_passed)
    kv("总耗时", f"{elapsed:.1f}s")
    print("=" * 68)

    if total == total_passed:
        ok("全部章节验收通过 🎉")
        note("下一步：打开 stages/ 里任意一章的 README.md 做练习，或读 NOTES.md 记笔记。")
        return 0

    fail(f"以下章节未通过：{failed_chapters}")
    note("单独跑某一章看详细输出：  py -m stages.stageNN_xxx.demo")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
