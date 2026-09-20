r"""第 03 章 · 练习 5 / 5 · 实现提示词的差异对比工具

【要做什么】
  写一个函数，用 `difflib.unified_diff` 对比 `PromptBuilder` 在不同配置下生成的系统提示词，
  输出人类可读的 diff。

  用途：code review 提示词改动 —— 提示词也是代码，改它必须能看清「到底改了哪几行」。

【已经给你了】
  · OLD_SYSTEM / NEW_SYSTEM  两份只差一条业务规则的提示词（同一套工具说明书）
  · OTHER_SYSTEM             换了协议风格（react -> function_calling）的第三份
  · REG                      工具注册表（PromptBuilder.build_system 要用）
  · difflib.unified_diff(a.splitlines(), b.splitlines(), lineterm="")  —— 现成的 diff 生成器

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch03_react_prompt\ex5_prompt_diff.py
  3. 验收本章：py scripts\run_all_checks.py 03
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import difflib                             # noqa: E402

from core.prompts import PromptBuilder     # noqa: E402
from core.tool import build_default_registry  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
REG = build_default_registry(ROOT)

PERSONA = "你是「小助手」，一个严谨的电商客服助理。"
NEW_RULE = "涉及金额计算一律用 calc，禁止心算。"

# v1：基线
OLD_SYSTEM = PromptBuilder(style="react", persona=PERSONA).build_system(REG)
# v2：只多加了一条业务规则
NEW_SYSTEM = PromptBuilder(style="react", persona=PERSONA, rules=[NEW_RULE]).build_system(REG)
# v3：换了工具调用协议
OTHER_SYSTEM = PromptBuilder(style="function_calling", persona=PERSONA).build_system(REG)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def diff_prompts(old: str, new: str, name_old: str = "旧提示词", name_new: str = "新提示词") -> list[str]:
    """对比两份系统提示词，返回**可打印的 diff 行**（list[str]）。

    TODO ① ── 三行就够：
        difflib.unified_diff(old.splitlines(), new.splitlines(),
                             fromfile=name_old, tofile=name_new, lineterm="")
      然后用 list(...) 收集成列表返回。

    提示：`lineterm=""` 不能省 —— 否则每行后面会多挂一个换行符，print 出来会多空一行。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 5 · TODO ①  diff_prompts：用 difflib.unified_diff 生成 diff")
    # ↑↑↑ 你的答案 ↑↑↑


def added_rules(diff_lines: list[str]) -> list[str]:
    """从 diff 行里挑出**新增的业务规则**。

    业务规则在提示词里长这样：      - 涉及金额计算一律用 calc，禁止心算。
    被 diff 标记成新增之后长这样：  +- 涉及金额计算一律用 calc，禁止心算。

    TODO ② ── 挑出以 "+-" 开头的行，把前缀去掉、去掉首尾空白后返回。
              提示：一行列表推导 + `line[2:].strip()`
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 5 · TODO ②  added_rules：挑出新增的规则行")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        lines = diff_prompts(OLD_SYSTEM, NEW_SYSTEM, "prompt_v1", "prompt_v2")
        style_lines = diff_prompts(OLD_SYSTEM, OTHER_SYSTEM, "react", "function_calling")

        if not isinstance(lines, list) or not lines:
            raise AssertionError("两份不一样的提示词，diff 不该是空的")
        if not all(isinstance(x, str) for x in lines):
            raise AssertionError("diff 行必须是字符串列表")
        text = "\n".join(lines)
        if NEW_RULE not in text:
            raise AssertionError(f"diff 里应该能看到新增的那条规则：{NEW_RULE!r}")
        if not any(x.startswith(("+", "-")) for x in lines):
            raise AssertionError("diff 行应该带 +/- 前缀（unified_diff 的输出）")

        rules = added_rules(lines)
        if rules != [NEW_RULE]:
            raise AssertionError(f"added_rules 应该正好挑出新增的那条规则，实际拿到 {rules}")
        style_added = added_rules(style_lines)
        if not style_lines:
            raise AssertionError("换成 function_calling 协议之后，提示词变了很多，diff 不该是空的")
        if diff_prompts(OLD_SYSTEM, OLD_SYSTEM, "a", "b"):
            raise AssertionError("两份完全一样的提示词，diff 应该是空的")

        report.append("【v1 -> v2】只加了一条业务规则，diff 长这样：")
        for line in lines:
            report.append("      " + line)
        report.append("")
        report.append(f"    程序挑出来的新规则：{rules}")
        report.append("      ^ 这就是「提示词回归测试」（第 10 章）的雏形：")
        report.append("        能 diff，才能 review；能 review，才敢改线上提示词。")
        report.append("")
        report.append("【v1 -> v3】换成 function_calling 协议，diff 前 6 行：")
        for line in style_lines[:6]:
            report.append("      " + line)
        report.append("      ...（工具说明书整块消失、格式契约整块换掉 —— 一眼可见）")
        report.append("")
        report.append(f"    ⚠️ 但 added_rules 在这组 diff 上挑出了 {len(style_added)} 条「规则」：")
        for r in style_added:
            report.append(f"        - {r}")
        report.append("      ^ 全是误报！function_calling 模板里的普通条目也是 `- ` 开头的。")
        report.append("      这就是「靠前缀猜语义」的极限 —— 想稳，就得靠**结构**：")
        report.append("      只在 `# 业务规则` 这个标题之后的行才算规则（这就是分块的好处）。")
        report.append("")
        report.append("★ 提示词也是代码：揉成一大坨字符串就没法做这种 diff，")
        report.append("  更没法 `assert \"Action:\" in system` 这样的分块断言。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    for line in report:
        print(line)
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
