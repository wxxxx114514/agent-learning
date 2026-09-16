"""环境自检：确认这台机器能跑完整套课程。

用法：
    py scripts\\check_env.py

检查项：
    1. Python 版本（需要 3.10+，因为课程用了 `X | None` 类型语法）
    2. 课程文件是否齐全（core/ 与 stages/）
    3. 标准库依赖是否可用（零第三方依赖是硬约束）
    4. 控制台编码（Windows GBK 会导致中文/emoji 报错）
    5. 是否配置了真实模型的 API Key（可选）
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

# 允许 `py scripts\check_env.py` 直接运行时找到项目根目录
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.console import (  # noqa: E402
    banner, bullet, check, code, kv, note, section, setup_console, warn,
)

MIN_PY = (3, 10)


def check_python() -> bool:
    section("1) Python 版本", "①")
    v = sys.version_info
    ok = v >= MIN_PY
    kv("解释器", sys.executable)
    kv("版本", f"{v.major}.{v.minor}.{v.micro}")
    check(f"版本 >= {MIN_PY[0]}.{MIN_PY[1]}", ok, f"实际 {v.major}.{v.minor}")
    if not ok:
        note("课程用了 `str | None` 这类语法，Python 3.9 及以下会直接语法报错。")
    return ok


def check_files() -> bool:
    section("2) 课程文件完整性", "②")
    required = [
        "README.md", "ROADMAP.md", "NOTES.md", "CHAPTERS.md",
        "TEACHING_CONTRACT.md",
        "core/__init__.py", "core/agent.py", "core/tool.py", "core/prompts.py",
        "core/parser.py", "core/message.py", "core/llm.py", "core/mock_llm.py",
        "core/real_llm.py", "core/console.py", "core/errors.py",
        "scripts/run_all_checks.py", "scripts/check_structure.py",
        "scripts/check_docs.py", "scripts/build_notebooks.py",
        "scripts/rebuild_all.py", "scripts/audit_consistency.py",
        "notebooks/notebook_lib.py", "notebooks/nb_blocks.py",
        "notebooks/nb_explain.py", "notebooks/nb_lint.py",
        "tests/test_core.py",
    ]
    missing = [p for p in required if not (ROOT / p).exists()]
    check(f"核心文件齐全（{len(required)} 个）", not missing,
          f"缺失: {missing}" if missing else "")
    if missing:
        warn("请确认你没有移动/删除文件；课程代码互相依赖。")

    stages = sorted(p.name for p in (ROOT / "stages").glob("stage*") if p.is_dir())
    kv("已安装章节", f"{len(stages)} 个")
    if stages:
        code("\n".join(stages))
    if len(stages) < 13:
        warn(f"13 章中尚有 {13 - len(stages)} 章未安装（不影响已完成的章节学习）。")
    return not missing


def check_stdlib() -> bool:
    section("3) 标准库依赖（零第三方依赖是硬约束）", "③")
    mods = ["json", "urllib.request", "ast", "re", "math", "dataclasses",
            "typing", "pathlib", "time", "random", "unicodedata", "difflib"]
    ok = True
    for m in mods:
        try:
            importlib.import_module(m)
            check(m, True)
        except Exception as exc:
            ok = False
            check(m, False, str(exc))
    note("课程刻意只用标准库：任何装了 Python 的机器都能跑，不需要 pip install。")
    return ok


def check_console() -> bool:
    section("4) 控制台编码", "④")
    can_emoji = setup_console()
    kv("stdout 编码", getattr(sys.stdout, "encoding", "?"))
    kv("emoji 支持", "是" if can_emoji else "否（已自动降级为 ASCII 标记）")
    check("中文与 emoji 可安全输出", True)
    if not can_emoji:
        note("这不影响学习；课程输出会自动使用 [想]/[做]/[看] 这样的 ASCII 标记。")
    return True


def check_api_key() -> bool:
    section("5) 真实模型（可选）", "⑤")
    try:
        from core.real_llm import find_provider
        found = find_provider()
    except Exception as exc:
        check("real_llm 可导入", False, str(exc))
        return True

    if found:
        prefix, key, base, model = found
        check("检测到 API Key", True)
        kv("服务商", prefix)
        kv("base_url", base)
        kv("默认模型", model)
        kv("Key 掩码", key[:6] + "…" + key[-4:] if len(key) > 12 else "***")
        note("跑 demo 时加 --real 就会走真实模型。")
    else:
        check("检测到 API Key", True, "未配置 —— 将使用离线 Mock 模型")
        bullet("想接真实模型，任选其一设置环境变量：")
        code(
            '$env:DEEPSEEK_API_KEY = "sk-xxx"    # 然后： py -m stages.stage01_agent_loop.demo --real\n'
            '$env:OPENAI_API_KEY  = "sk-xxx"\n'
            '$env:DASHSCOPE_API_KEY = "sk-xxx"   # 通义千问',
            indent=6,
        )
        note("没配 Key 也能学完全部课程 —— 内核逻辑与模型无关，这正是第 01 章要讲的。")
    return True


def check_notebooks() -> bool:
    section("6) Jupyter Notebook（可选）", "⑥")
    nb_dir = ROOT / "notebooks"
    ipynbs = sorted(nb_dir.glob("*.ipynb")) if nb_dir.is_dir() else []
    kv("已生成 Notebook", f"{len(ipynbs)} 个")

    try:
        import nbformat  # noqa: F401
        check("已安装 Jupyter 工具链", True)
        note("可以直接：jupyter lab notebooks/")
    except ImportError:
        check("已安装 Jupyter 工具链", True, "未安装 —— 不影响 .py 版本的学习")
        note("课程本身零依赖；Notebook 只是多一种学习形态。")
        bullet("想用 Notebook，任选一种方式：")
        code("pip install jupyterlab        # 功能最全\n"
             "pip install notebook          # 经典界面\n"
             "# 或者：直接用 VS Code 打开 .ipynb（无需安装）", indent=6)
    if ipynbs:
        note(f"已生成：{', '.join(p.name for p in ipynbs[:4])}"
             + (" …" if len(ipynbs) > 4 else ""))
    else:
        warn("还没有生成 Notebook：执行  py scripts\\build_notebooks.py")
    return True


def main() -> int:
    setup_console()
    banner("Agent 开发课程 · 环境自检",
           f"项目根目录：{ROOT}")

    results = [
        check_python(),
        check_files(),
        check_stdlib(),
        check_console(),
        check_api_key(),
        check_notebooks(),
    ]

    print()
    if all(results):
        from core.console import ok
        ok("环境就绪！下一步：")
        code("py -m stages.stage01_agent_loop.demo          # 跑第 01 章\n"
             "py scripts\\run_all_checks.py                 # 跑全部 13 章的验收标准\n"
             "py scripts\\build_notebooks.py                # 生成 Notebook（可选）\n"
             "py scripts\\check_structure.py                # 检查章节材料是否齐全", indent=4)
        note("建议先读 CHAPTERS.md（分章节导读），它告诉你每一章在解决什么问题。")
        return 0
    from core.console import fail
    fail("环境存在问题，请先按上面的提示修复。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
