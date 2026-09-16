"""一键恢复：把被编辑器覆盖掉的 Notebook 重新生成出来。

用法：
    py scripts\\rebuild_all.py

什么时候用它？
    我在改 Notebook 内容时，如果你同时用 VS Code 开着那个 .ipynb，
    你一切换窗口 / 一保存，编辑器缓冲区里的**旧内容**就可能写回磁盘，
    静默覆盖掉我刚生成的新版。

    症状：某个 Notebook 的内容"退回旧版"、检查报
          「XX.ipynb 已过期：源码比产物新 N 秒」。

    修复：跑一次这个脚本。它会把所有过期/丢失的 Notebook 重新生成，
          并且**真的执行每个代码单元**，把真实输出嵌进去。

它做的事（按顺序）：
    1. 找出所有"产物比源码旧"或缺失的 Notebook
    2. 逐个重新生成（含执行）
    3. 校验产物是合法 nbformat v4
    4. 报告结果；顺便提示怎么预防下次再被覆盖
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, code, fail, kv, note, ok, section, setup_console, warn,
)


def main() -> int:
    setup_console()
    banner("一键恢复 Notebook", "重新生成所有被覆盖 / 过期的产物")

    from notebooks.notebook_lib import is_stale, stale_notebooks
    from scripts.build_notebooks import REGISTRY, build_one

    # ---- 1. 找出需要重建的 ----
    section("① 检查哪些需要重建", "1")
    stale = dict(stale_notebooks(ROOT))
    if not stale:
        ok("所有 Notebook 都是最新的 —— 没有东西需要恢复")
        note("如果你觉得内容不对，可能是 VS Code 还没重新加载文件：")
        code("在 VS Code 里关掉该文件再打开（Ctrl+W 然后重新点开）", indent=6)
        return 0

    for filename, why in sorted(stale.items()):
        warn(f"{filename}：{why}")

    # ---- 2. 重新生成 ----
    section("② 重新生成", "2")
    todo = [(ch, meta) for ch, meta in REGISTRY.items()
            if meta[1] in stale]

    n_ok = n_bad = 0
    for ch, (title, filename, _mod, _factory) in todo:
        good, msg = build_one(ch, execute=True)
        if good:
            ok(f"[{ch}] {filename} — {msg}")
            n_ok += 1
        else:
            fail(f"[{ch}] {filename} — {msg}")
            n_bad += 1

    # ---- 3. 复查 ----
    section("③ 复查", "3")
    still = dict(stale_notebooks(ROOT))
    if still:
        for filename, why in sorted(still.items()):
            fail(f"{filename} 仍然过期：{why}")
    else:
        ok("全部产物已是最新")

    print()
    print("=" * 68)
    kv("重建成功", n_ok)
    kv("重建失败", n_bad)
    kv("仍然过期", len(still))
    print("=" * 68)

    if n_bad == 0 and not still:
        ok("恢复完成 ✅")
        note("在 VS Code 里关掉该文件再重新打开，就能看到新内容")
        return 0

    fail("有产物没能恢复，请看上面的报错。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
