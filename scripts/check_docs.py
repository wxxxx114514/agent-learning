"""校验课程文档里的链接与命令是否真实存在。

用法：
    py scripts\\check_docs.py

为什么需要这个？
    课程文档里有大量「📂 stages/stageNN/README.md」这样的链接和
    `py -m stages.stageNN.demo` 这样的命令。章节重构时（改名、拆分目录）
    很容易留下死链 —— 而读者点到 404 就断了学习节奏。
    这个脚本把这类问题变成一条可自动执行的检查。

检查三件事：
    1. 四个顶层文档里的 markdown 链接是否指向真实文件
    2. 各章 README 里的 `py -m stages.xxx` 命令是否对应真实模块
    3. 各章目录是否满足课程契约（三件套齐全）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, code, fail, kv, note, ok, section, setup_console, warn,
)

TOP_DOCS = ["README.md", "CHAPTERS.md", "ROADMAP.md", "NOTES.md", "notebooks/README.md"]
REQUIRED_FILES = ["__init__.py", "demo.py", "README.md"]


def strip_code(text: str) -> str:
    """去掉围栏代码块与行内代码。

    ★ 为什么必须去掉？
        文档里会写 `self.tools[name](**args)` 这种**行内代码**，
        朴素的 `\\]\\(([^)]+)\\)` 正则会把它误判成 markdown 链接
        （因为 `name](**args)` 长得就像链接）。
        同理，代码块里也可能出现 `](...)`。
    """
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`\n]*`", "", text)
    return text


def markdown_links(text: str) -> list[str]:
    return re.findall(r"\]\(([^)\s]+)\)", strip_code(text))


def check_doc_links() -> tuple[int, int]:
    section("① 顶层文档的链接", "1")
    passed = total = 0
    for name in TOP_DOCS:
        p = ROOT / name
        if not p.exists():
            warn(f"{name} 不存在，跳过")
            continue
        broken = []
        for target in markdown_links(p.read_text(encoding="utf-8")):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            if not (ROOT / target.split("#")[0]).exists():
                broken.append(target)
        total += 1
        passed += not broken
        if broken:
            fail(f"{name} 有 {len(broken)} 个死链")
            for b in broken[:6]:
                print(f"       → {b}")
        else:
            ok(f"{name} 链接全部有效")
    return passed, total


def check_readme_commands() -> tuple[int, int]:
    section("② 各章 README 里的命令", "2")
    passed = total = 0
    for stage in sorted((ROOT / "stages").glob("stage*")):
        readme = stage / "README.md"
        if not readme.exists():
            continue
        text = readme.read_text(encoding="utf-8")
        mods = sorted(set(re.findall(r"py -m ((?:stages|scripts|tests)[\w.]*)", text)))
        bad = []
        for mod in mods:
            if not ROOT.joinpath(*mod.split(".")).with_suffix(".py").exists():
                bad.append(mod)
        total += 1
        passed += not bad
        if bad:
            fail(f"{stage.name}/README.md 里的命令指向不存在的模块：{bad}")
        else:
            ok(f"{stage.name} 的 {len(mods)} 条命令有效")
    return passed, total


def check_stage_contract() -> tuple[int, int]:
    section("③ 各章目录的材料完整性", "3")
    passed = total = 0
    for stage in sorted((ROOT / "stages").glob("stage*")):
        if stage.name == "__pycache__":
            continue
        missing = [f for f in REQUIRED_FILES if not (stage / f).exists()]
        total += 1
        passed += not missing
        if missing:
            fail(f"{stage.name} 缺少 {missing}")
        else:
            ok(f"{stage.name} 三件套齐全")
    return passed, total


def check_notebooks() -> tuple[int, int]:
    """检查 notebooks/ 下的 .ipynb 是否符合 nbformat v4。

    这一层单独查，因为 Notebook 是**生成产物**：
    改了 `nb_part*.py` 却忘了重新生成，就会出现"内容与代码不一致"。
    这里的校验能立刻发现产物损坏或缺失。
    """
    section("④ Notebook 产物", "4")
    nb_dir = ROOT / "notebooks"
    if not nb_dir.is_dir():
        warn("notebooks/ 目录不存在，跳过")
        return 1, 1

    sys.path.insert(0, str(ROOT))
    try:
        from notebooks.notebook_lib import validate_ipynb
    except ImportError as exc:
        fail(f"无法导入 notebooks.notebook_lib: {exc}")
        return 0, 1

    passed = total = 0
    for ipynb in sorted(nb_dir.glob("*.ipynb")):
        total += 1
        good, msg = validate_ipynb(ipynb)
        passed += good
        (ok if good else fail)(f"{ipynb.name} — {msg}")

    if total == 0:
        warn("还没有生成任何 .ipynb（运行 py scripts\\build_notebooks.py）")
        return 1, 1
    return passed, total


def main() -> int:
    setup_console()
    banner("课程文档校验", "检查链接、命令、材料完整性与 Notebook 产物")

    p1, t1 = check_doc_links()
    p2, t2 = check_readme_commands()
    p3, t3 = check_stage_contract()
    p4, t4 = check_notebooks()

    print()
    print("=" * 68)
    kv("检查组总数", t1 + t2 + t3 + t4)
    kv("通过", p1 + p2 + p3 + p4)
    kv("失败", (t1 + t2 + t3 + t4) - (p1 + p2 + p3 + p4))
    print("=" * 68)

    if p1 + p2 + p3 + p4 == t1 + t2 + t3 + t4:
        ok("文档全部有效 ✅")
        return 0
    fail("文档存在问题，请修复上面的死链 / 失效命令 / 缺失材料。")
    note("提示：正在编写的章节会暂时缺少 README.md；Notebook 需要先跑 build_notebooks.py。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
