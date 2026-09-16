"""教学输出工具：让每一课的输出都**稳定、对齐、可读**。

------------------------------------------------------------
一句话本质：
    教学代码的 print 不是"打印"，而是**可视化内部状态**。
    读者要靠这些输出"看见" Agent 的脑袋里发生了什么。
------------------------------------------------------------

本模块解决三个很实际的坑：

1. **Windows 控制台默认是 GBK**，而我们的课程里全是中文 + emoji（💭🔧👁）。
   直接 print 会抛 UnicodeEncodeError 把整个 demo 炸掉。
   → setup_console() 在进程启动时把 stdout/stderr 切到 UTF-8。

2. **教学输出需要"分步骤"的视觉层次**：标题 / 小节 / 键值 / 成功失败。
   全部裸 print 的话，读者分不清哪段是哪段。
   → 提供了一套极简的排版原语（不引入任何第三方库）。

3. **emoji 在部分终端（老 cmd、CI 日志）显示成方块或乱码**。
   → 自动探测：编码不支持就降级成 ASCII 标记，绝不因为"画不出花"而崩掉。

设计原则：**这里的任何函数都不能抛异常**。教学工具挂了会掩盖真正的知识点。
"""

from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------------------
# 一、编码与终端能力探测
# ---------------------------------------------------------------------------
_ASCII_MODE = False


def setup_console(force_ascii: bool | None = None) -> bool:
    """把标准输出切到 UTF-8，并探测能否安全输出 emoji。

    返回：True 表示可以使用 emoji；False 表示已降级为 ASCII 模式。

    参数 force_ascii：
        None（默认）→ 自动探测
        True        → 强制 ASCII（用于把输出重定向到老式日志系统）
        False       → 强制尝试 emoji
    """
    global _ASCII_MODE

    if force_ascii is None:
        force_ascii = os.environ.get("AGENT_COURSE_ASCII", "").strip() in {"1", "true", "yes"}

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:
            # 有些环境（IDLE、被重定向的管道）不支持 reconfigure，忽略即可。
            pass

    if force_ascii:
        _ASCII_MODE = True
        return False

    # 探测：真的写一个 emoji 出去，看会不会炸。用 errors='replace' 时不会抛异常，
    # 所以我们额外看编码名判断。
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    _ASCII_MODE = not (enc.startswith("utf") or enc.startswith("cp65001"))
    return not _ASCII_MODE


def ascii_mode() -> bool:
    return _ASCII_MODE


def _icon(rich: str, plain: str) -> str:
    return plain if _ASCII_MODE else rich


# 图标字典（ASCII 模式下自动降级）
I = {
    "thought": lambda: _icon("💭", "[想]"),
    "action": lambda: _icon("🔧", "[做]"),
    "obs": lambda: _icon("👁 ", "[看]"),
    "answer": lambda: _icon("✅", "[答]"),
    "warn": lambda: _icon("⚠️ ", "[!]"),
    "info": lambda: _icon("ℹ️ ", "[i]"),
    "fail": lambda: _icon("❌", "[x]"),
    "step": lambda: _icon("▶", ">"),
    "key": lambda: _icon("🔑", "[key]"),
}

WIDTH = 68


# ---------------------------------------------------------------------------
# 二、排版原语
# ---------------------------------------------------------------------------
def banner(title: str, subtitle: str = "") -> None:
    """整课的开场大标题。"""
    try:
        print("=" * WIDTH)
        print(f"  {title}")
        if subtitle:
            print(f"  {subtitle}")
        print("=" * WIDTH)
    except Exception:
        pass


def section(title: str, index: str = "") -> None:
    """小节标题（一节课里会有好几个小节）。"""
    try:
        head = f"{index} {title}".strip() if index else title
        print(f"\n{'-' * WIDTH}")
        print(f"▌{head}" if not _ASCII_MODE else f"| {head}")
        print("-" * WIDTH)
    except Exception:
        pass


def note(text: str) -> None:
    try:
        print(f"  {I['info']()} {text}")
    except Exception:
        pass


def warn(text: str) -> None:
    try:
        print(f"  {I['warn']()} {text}")
    except Exception:
        pass


def fail(text: str) -> None:
    try:
        print(f"  {I['fail']()} {text}")
    except Exception:
        pass


def ok(text: str) -> None:
    try:
        print(f"  {I['answer']()} {text}")
    except Exception:
        pass


def kv(key: str, value: object, indent: int = 2) -> None:
    """对齐的键值输出，用于展示指标。"""
    try:
        print(f"{' ' * indent}{key:<18}: {value}")
    except Exception:
        pass


def bullet(text: str, indent: int = 2) -> None:
    try:
        print(f"{' ' * indent}- {text}")
    except Exception:
        pass


def code(text: str, indent: int = 4, lang: str = "") -> None:
    """代码/数据块，带左边框，便于和讲解文字区分。"""
    try:
        pad = " " * indent
        if lang:
            print(f"{pad}[{lang}]")
        for line in str(text).rstrip("\n").splitlines():
            print(f"{pad}│ {line}" if not _ASCII_MODE else f"{pad}| {line}")
    except Exception:
        pass


def boxed(text: str, title: str = "") -> None:
    """把一段结论框起来（用于"一句话本质"）。"""
    try:
        print("  ┌" + "─" * (WIDTH - 4) + ("┐" if not _ASCII_MODE else "+"))
        if title:
            print(f"  │ {title}")
        for line in str(text).rstrip("\n").splitlines():
            print(f"  │ {line}")
        print("  └" + "─" * (WIDTH - 4) + ("┘" if not _ASCII_MODE else "+"))
    except Exception:
        pass


def essence(text: str) -> None:
    """「一句话本质」的统一呈现方式 —— 每节课的收口。"""
    boxed(text, title="一句话本质")


def check(name: str, passed: bool, detail: str = "") -> bool:
    """打印一条自检结果，返回 passed（方便累计）。"""
    try:
        mark = _icon("✅", "[PASS]") if passed else _icon("❌", "[FAIL]")
        tail = f"  ({detail})" if detail else ""
        print(f"  {mark} {name}{tail}")
    except Exception:
        pass
    return passed


def progress(i: int, total: int, label: str = "") -> None:
    """阶段进度条：`[###-------] 3/10 主题`。"""
    try:
        filled = int(round(WIDTH * 0.4 * i / max(total, 1)))
        bar = "#" * filled + "-" * (int(WIDTH * 0.4) - filled)
        print(f"  [{bar}] {i}/{total} {label}")
    except Exception:
        pass


def pause(prompt: str = "按回车继续…", auto: bool = True) -> None:
    """交互式停顿。auto=True 时（非 TTY / 设置 NO_PAUSE）直接跳过，避免卡住自动化脚本。"""
    try:
        if auto and (os.environ.get("AGENT_COURSE_NO_PAUSE") or not sys.stdin.isatty()):
            return
        input(prompt)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 三、阶段性自检收集器
# ---------------------------------------------------------------------------
# 每个 stage 的 demo.py 都实现 `run_checks() -> list[tuple[str, bool, str]]`，
# 由 scripts/run_all_checks.py 统一调用。契约必须统一，否则一键自检做不出来。
def check_that(name: str, condition: object, detail: str = "") -> tuple[str, bool, str]:
    """构造一条检查结果（不打印），供 run_checks() 返回。"""
    return (name, bool(condition), detail)


def report(title: str, results: list[tuple[str, bool, str]]) -> bool:
    """打印一组检查结果并返回是否全部通过。"""
    section(f"自检：{title}")
    all_ok = True
    for name, passed, detail in results:
        all_ok &= check(name, passed, detail)
    print()
    if all_ok:
        ok(f"全部通过（{len(results)} 项）")
    else:
        failed = [n for n, p, _ in results if not p]
        fail(f"{len(failed)}/{len(results)} 项未通过：{failed}")
    return all_ok


__all__ = [
    "setup_console", "ascii_mode", "I", "WIDTH",
    "banner", "section", "note", "warn", "fail", "ok", "kv", "bullet",
    "code", "boxed", "essence", "check", "progress", "pause",
    "check_that", "report",
]
