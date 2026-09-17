"""一致性审计：找出仓库里所有"和现状不符"的地方。

为什么要专门写这个？
    课程同时存在于 4 种材料里（Notebook / README / demo / 顶层文档），
    又有一堆脚本和测试。改了一处，别处很容易留下过期描述：

        · 文档里写的文件名已经删了
        · 统计数字对不上（"73 个测试"其实有 92 个）
        · 读者拿到的指示是旧流程（"先读 README"）
        · 新加的文件没在任何地方介绍

    靠眼睛翻一定会漏。这个脚本按**类别**逐项验证，把"需要同步的地方"
    一次性列出来。每一条都是可验证的事实，不是主观判断。

用法：
    py scripts/audit_consistency.py
    py scripts/audit_consistency.py --fix-hints    # 附带修复建议
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, check, code, fail, kv, note, ok, section, setup_console, warn,
)

# 顶层文档 + 各章 README（审计范围）
TOP_DOCS = ["README.md", "CHAPTERS.md", "ROADMAP.md", "NOTES.md",
            "TEACHING_CONTRACT.md", "notebooks/README.md"]
ALL_DOCS = TOP_DOCS + [
    f"stages/{d.name}/README.md"
    for d in sorted((ROOT / "stages").glob("stage*"))
    if (d / "README.md").exists()
]

ISSUES: list[tuple[str, str, str]] = []      # (类别, 位置, 问题)


def issue(cat: str, where: str, what: str) -> None:
    ISSUES.append((cat, where, what))


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def strip_code(text: str) -> str:
    """剥掉代码块与行内代码，避免把示例代码里的东西当成正文引用。"""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


# ===========================================================================
# ① 文档提到的文件路径是否真实存在
# ===========================================================================
def audit_file_references() -> None:
    # 形如 stages/stageNN_xxx/xxx 或 notebooks/xxx 或 scripts/xxx.py 的引用
    pat = re.compile(r"(?<![\w/])((?:core|stages|notebooks|scripts|tests)/[\w./\-]+)")

    for rel in ALL_DOCS:
        text = read(rel)
        if not text:
            continue
        for m in pat.finditer(strip_code(text)):
            ref = m.group(1).rstrip(".,;:)）】")
            # 允许引用目录、允许带通配（stageNN_xxx 这种占位）
            if "NN" in ref or "xxx" in ref or ref.endswith("/"):
                continue
            if not (ROOT / ref).exists():
                # 可能是带锚点的、或是 glob 模式
                if not list(ROOT.glob(ref)):
                    issue("① 引用不存在的路径", rel, ref)


# ===========================================================================
# ② 统计数字是否和实际一致
# ===========================================================================
def audit_stats() -> None:
    # --- 单元测试数量 ---
    out = subprocess.run([sys.executable, "-m", "unittest", "discover",
                          "-s", "tests", "-t", "."],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", cwd=str(ROOT))
    m = re.search(r"Ran (\d+) tests", (out.stderr or "") + (out.stdout or ""))
    real_tests = int(m.group(1)) if m else None

    # --- 课程验收项数 ---
    out2 = subprocess.run([sys.executable, "scripts/run_all_checks.py", "--quiet"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=str(ROOT))
    m2 = re.search(r"检查项总数\s*:\s*(\d+)", out2.stdout or "")
    real_checks = int(m2.group(1)) if m2 else None

    # --- Notebook 数 ---
    real_nb = len(list((ROOT / "notebooks").glob("*.ipynb")))

    # 文档里出现过的数字声明
    for rel in ALL_DOCS:
        text = strip_code(read(rel))
        if real_tests:
            for m in re.finditer(r"(\d+)\s*(?:个)?\s*(?:框架)?(?:单元)?测试", text):
                if int(m.group(1)) != real_tests:
                    issue("② 测试数对不上", rel,
                          f"文档写 {m.group(1)}，实际 {real_tests}")
        # ★ 只检查**总数**声明，不碰"每章多少项"。
        #   判据：数字后面跟的如果是"项检查/项断言"，且上下文里有「全部/共/合计」，
        #   才当成总数。否则可能是在说某一章（例如"第 01 章 13 项"）。
        for m in re.finditer(r"(全部|共|合计)[^\n]{0,24}?(\d+)\s*项(?:检查|断言|验收)", text):
            if int(m.group(2)) != real_checks:
                issue("② 验收项总数对不上", rel,
                      f"文档写 {m.group(2)}，实际 {real_checks}")
        for m in re.finditer(r"(\d+)\s*个\s*Notebook", text):
            if int(m.group(1)) not in (real_nb, real_nb - 1):
                issue("② Notebook 数对不上", rel,
                      f"文档写 {m.group(1)}，实际 {real_nb}")

    # --- 逐章核对 CHAPTERS.md 进度表里的"检查项"列 ---
    audit_per_chapter_counts()


def audit_per_chapter_counts() -> None:
    """核对 CHAPTERS.md 进度表里每章的检查项数是否和实际一致。

    ★ 这一列很容易过期：改了某章的教学内容，`run_checks()` 的项数就变了，
      而文档里的数字没人会想起来同步。所以单独查。
    """
    doc = read("CHAPTERS.md")
    if not doc:
        return

    # 逐章跑一次 run_checks，拿到真实项数
    real: dict[str, int] = {}
    for d in sorted((ROOT / "stages").glob("stage*")):
        demo = d / "demo.py"
        if not demo.exists():
            continue
        ch = d.name[len("stage"):][:2]
        out = subprocess.run(
            [sys.executable, "scripts/run_all_checks.py", ch, "--quiet"],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", cwd=str(ROOT))
        m = re.search(r"检查项总数\s*:\s*(\d+)", out.stdout or "")
        if m:
            real[ch] = int(m.group(1))

    # 从表格里抠出 "| 01 | 主题 | ... | 13 |" 这种行
    for line in doc.split("\n"):
        if not line.startswith("| "):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 6 or not cells[0].isdigit():
            continue
        ch, claimed = cells[0].zfill(2), cells[-1]
        if not claimed.isdigit():
            continue          # 写的是"见自检"之类，跳过
        if ch in real and int(claimed) != real[ch]:
            issue("② 某章检查项数过期", "CHAPTERS.md",
                  f"第 {ch} 章写 {claimed}，实际 {real[ch]}")


# ===========================================================================
# ③ 已删除文件是否仍被提及
# ===========================================================================
def audit_deleted_files() -> None:
    deleted = ["nb_part0.py", "nb_part1.py", "nb_part2.py",
               "00_START_HERE.ipynb", "nb_start.py", "START_HERE.md"]
    for rel in ALL_DOCS:
        text = read(rel)
        for name in deleted:
            if name in text:
                # 允许"已删除"这类说明性提及
                for line in text.split("\n"):
                    if name in line and "已" not in line and "删" not in line \
                            and "旧" not in line:
                        issue("③ 提到已删除的文件", rel, f"{name}  → {line.strip()[:64]}")
                        break


# ===========================================================================
# ④ 顶层脚本 / 模块是否都被介绍过
# ===========================================================================
def audit_script_coverage() -> None:
    doc_all = "\n".join(read(r) for r in TOP_DOCS)

    for p in sorted((ROOT / "scripts").glob("*.py")):
        if p.name == "__init__.py":
            continue
        if p.name not in doc_all:
            issue("④ 脚本未在文档中介绍", "README.md", f"scripts/{p.name}")

    for p in sorted((ROOT / "notebooks").glob("nb_*.py")):
        if p.name not in doc_all:
            issue("④ 模块未在文档中介绍", "notebooks/README.md", f"notebooks/{p.name}")


# ===========================================================================
# ⑤ 文档里写的命令是否真能跑
# ===========================================================================
def audit_commands() -> None:
    pat = re.compile(r"py (?:-m )?((?:scripts|stages|tests)[\w.\\/]*)")
    for rel in ALL_DOCS:
        text = read(rel)
        for m in pat.finditer(strip_code(text)):
            cmd = m.group(1).replace("\\", "/")
            if "NN" in cmd or "xxx" in cmd:
                continue
            # scripts/foo.py → 文件；stages.foo.demo → modules
            if cmd.endswith(".py"):
                if not (ROOT / cmd).exists():
                    issue("⑤ 命令指向不存在的脚本", rel, f"py {cmd}")
            else:
                parts = cmd.split(".")
                cand = ROOT.joinpath(*parts).with_suffix(".py")
                pkg = ROOT.joinpath(*parts) / "__init__.py"
                if not cand.exists() and not pkg.exists():
                    issue("⑤ 命令指向不存在的模块", rel, f"py -m {cmd}")


# ===========================================================================
# ⑥ 学习流程指示是否统一（不该再出现"先读 README"）
# ===========================================================================
def audit_workflow_wording() -> None:
    bad_patterns = [
        (r"第一步\s*读\s*`?stages/", "仍是「先读 README」的旧流程"),
        (r"按章节学习\s*←\s*打开对应\s*stageNN\s*目录的\s*README", "旧流程指示"),
        (r"先读「0\. 先看问题」", "旧流程指示"),
    ]
    for rel in TOP_DOCS:
        text = read(rel)
        for pat, why in bad_patterns:
            if re.search(pat, text):
                issue("⑥ 流程指示未同步", rel, why)


# ===========================================================================
# ⑦ 各章 README 是否有"复习手册"定位说明，以及是否提到 Notebook
# ===========================================================================
def audit_stage_readme_banner() -> None:
    for d in sorted((ROOT / "stages").glob("stage*")):
        p = d / "README.md"
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = f"stages/{d.name}/README.md"
        if "材料定位" not in text:
            issue("⑦ README 缺定位说明", rel, "没有「复习手册」定位段落")
        if "notebooks/" not in text:
            issue("⑦ README 没指向 Notebook", rel, "定位段落里没提对应的 .ipynb")


# ===========================================================================
# ⑧ Notebook 与 demo 的章节数是否一致
# ===========================================================================
def audit_chapter_parity() -> None:
    """Notebook 与 stages/ 下的 demo 是否一一对应。

    有一个**已知的合理例外**：第 00 章（模型和代码之间传什么）只有 Notebook，
    没有 `stages/stage00_*` 目录。原因：它讲的是"模型和代码怎么通信"这个地基，
    内容是一整条可运行的推导链，拆成 `demo.py` + `README.md` 反而割裂，
    而且它没有需要单独验收的工程实现。
    """
    KNOWN_EXCEPTIONS = {"00"}      # 有 Notebook、故意没有 demo

    nbs = {p.name.split("_")[0] for p in (ROOT / "notebooks").glob("*.ipynb")}
    demos = {d.name[len("stage"):][:2]
             for d in (ROOT / "stages").glob("stage*")
             if (d / "demo.py").exists()}

    only_nb = nbs - demos - KNOWN_EXCEPTIONS
    only_demo = demos - nbs
    if only_nb:
        issue("⑧ 章号不齐", "notebooks/", f"只有 Notebook 没有 demo：{sorted(only_nb)}")
    if only_demo:
        issue("⑧ 章号不齐", "stages/", f"只有 demo 没有 Notebook：{sorted(only_demo)}")


# ===========================================================================
def main() -> int:
    parser = argparse.ArgumentParser(description="一致性审计")
    parser.add_argument("--fix-hints", action="store_true", help="附带修复建议")
    args = parser.parse_args()

    setup_console()
    banner("一致性审计", "找出所有和现状不符的文档描述")

    checks = [
        ("① 文档引用的路径", audit_file_references),
        ("② 统计数字", audit_stats),
        ("③ 已删除的文件", audit_deleted_files),
        ("④ 脚本/模块覆盖", audit_script_coverage),
        ("⑤ 文档里的命令", audit_commands),
        ("⑥ 学习流程指示", audit_workflow_wording),
        ("⑦ README 定位说明", audit_stage_readme_banner),
        ("⑧ 章节齐整性", audit_chapter_parity),
    ]
    for name, fn in checks:
        section(name, "◆")
        before = len(ISSUES)
        try:
            fn()
        except Exception as exc:
            fail(f"该检查本身出错：{type(exc).__name__}: {exc}")
            continue
        found = len(ISSUES) - before
        if found == 0:
            ok("没有发现问题")
        else:
            warn(f"发现 {found} 处需要同步")

    print()
    print("=" * 72)
    if not ISSUES:
        ok("全部一致，没有需要同步的地方 ✅")
        return 0

    kv("需要同步的总数", len(ISSUES))
    print("=" * 72)
    print()
    by_cat: dict[str, list[tuple[str, str]]] = {}
    for cat, where, what in ISSUES:
        by_cat.setdefault(cat, []).append((where, what))
    for cat, items in by_cat.items():
        print(f"  【{cat}】{len(items)} 处")
        for where, what in items[:12]:
            print(f"      {where}")
            print(f"        → {what}")
        if len(items) > 12:
            print(f"      …还有 {len(items) - 12} 处")
        print()

    if args.fix_hints:
        note("修复建议：逐类处理")
        code("① 把过期路径改成现存的\n"
             "② 更新统计数字（测试数 / 验收项数 / Notebook 数）\n"
             "③ 删掉或标注「已删除」\n"
             "④ 在 README 的目录树里补上\n"
             "⑤ 修正命令\n"
             "⑥ 改成「学新章节用 Notebook」\n"
             "⑦ 跑 py scripts\\add_readme_banner.py\n"
             "⑧ 补齐缺失的一侧", indent=6)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
