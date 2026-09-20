r"""第 11 章 · 练习 4 / 5 · 给脱敏加一条规则

【要做什么】
  中文姓名是最难脱敏的一类（没有固定格式）。试着加一条：
  把「客户张伟」这类 `客户[\u4e00-\u9fa5]{1,3}` 打成 `客户张*`。

  提示：在 `REDACTION_RULES` 里加一条，然后跑第 ⑥ 节看效果。

【已经给你了】
  install_name_rule()  把「客户+中文姓名」这条脱敏规则插进 REDACTION_RULES —— ★ 你要写的
  apply_rules(text)    对一段文本跑一遍全部脱敏规则，返回 (脱敏后文本, 命中的规则名)
  show_rules()         打印当前生效的规则表（看看你的规则排在第几条、为什么）
  SAMPLES              四条样本：手机号 / 密钥 / 姓名+身份证 / 银行卡
  redact()             课程原版的脱敏入口（用的是同一份 REDACTION_RULES）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch11_guardrails\ex4_redaction_rule.py
  3. 验收本章：py scripts\run_all_checks.py 11
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import re                                                      # noqa: E402

from core.console import bullet, kv, note, warn                # noqa: E402
from stages.stage11_guardrails.demo import REDACTION_RULES, redact  # noqa: E402

RULE_NAME = "中文姓名（客户XXX）"
NAME_PATTERN = r"客户[\u4e00-\u9fa5]{1,3}"      # 客户 + 1~3 个汉字
NAME_REPL = "客户*"                              # 只留姓？—— 题目要求打成 客户张*

SAMPLES = (
    ("客服回答", "您的订单已发往 13800138000，如有问题请联系客服。"),
    ("调试信息", "调用失败：api_key=sk-abc1234567890xyz，请检查配额。"),
    ("用户资料", "客户张伟，身份证 11010119900307123X，邮箱 zhangwei@example.com。"),
    ("对账信息", "打款卡号 6222021234567890123 已确认。"),
)

# 误伤检查用的样本：这些词里也带「客户」，但它们**不是姓名**
INNOCENT = ("客户服务", "客户经理", "客户反馈")


def show_rules() -> None:
    """打印当前生效的脱敏规则表。"""
    print("    当前 REDACTION_RULES（顺序就是执行顺序）：")
    for i, (name, pattern, repl) in enumerate(REDACTION_RULES, 1):
        print(f"      {i}. {name:<16} {pattern.pattern[:44]:<46} → {repl}")
    print()


def apply_rules(text: str) -> tuple[str, list[str]]:
    """对一段文本跑一遍全部脱敏规则，返回 (脱敏后文本, 命中的规则名)。"""
    out, hits = text, []
    for name, pattern, repl in REDACTION_RULES:
        out, n = pattern.subn(repl, out)
        if n:
            hits.append(f"{name}×{n}")
    return out, hits


def assert_masking_style(text: str) -> tuple[str, str]:
    """辅助：把「客户张伟」按题目要求打成「客户张*」，返回 (要求的样子, 你的规则给出的样子)。

    题目原话是「把「客户张伟」这类打成 `客户张*`」——**保留姓氏、打码名字**。
    """
    m = re.search(NAME_PATTERN, text)
    expected = (m.group(0)[:3] + "*") if m else ""           # 「客户张伟」→「客户张*」
    got, _ = apply_rules(text)
    got_name = re.search(r"客户[^\s，。]*", got)
    return expected, (got_name.group(0) if got_name else "")


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def install_name_rule() -> str:
    """TODO ── 加一条脱敏规则：把「客户张伟」打成「客户张*」。

    要做三件事：
      ① 造正则：pattern = re.compile(r"客户([\u4e00-\u9fa5])[\u4e00-\u9fa5]{0,2}")
         解释：`客户` + 捕获组里的**第一个汉字**（姓）+ 后面 0~2 个汉字（名）
              —— `{1,3}` 写成 `([\u4e00-\u9fa5])[\u4e00-\u9fa5]{0,2}` 才能把「姓」captured 出来
      ② 造替换串：repl = r"客户\1*"
         （`\1` 就是捕获到的姓；这样「客户张伟」→「客户张*」，「客户欧阳娜」→「客户欧*」）
      ③ 插进规则表，并返回你观察到的结论（见下面第 ③ 问）

    ★ 插在哪里很重要：脱敏规则是**顺序执行**的，前一条的输出是后一条的输入。
      排在前面 = 先看见原文。这里插在**最前面**最直观：
          REDACTION_RULES.insert(0, (RULE_NAME, pattern, repl))
      （用 insert 而不是重新赋值 REDACTION_RULES = [...]：模块级列表被别处引用着，
        重新绑定只会改你自己模块里的名字，redact() 那边看不见。）

    第 ③ 问（写在返回的字符串里）：这条规则会**误伤**什么？
        提示：`客户服务`、`客户经理`、`客户反馈` 都会被误伤 ——
        这就是为什么姓名脱敏通常要靠**名单匹配**或**模型判定**，而不是纯正则。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO  install_name_rule")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_4() -> None:
    pii = "客户张伟，身份证 11010119900307123X，邮箱 zhangwei@example.com。"
    before, _ = apply_rules(pii)
    if "客户张*" in before:
        raise AssertionError("动手之前不该已经有姓名脱敏规则，先检查环境")

    conclusion = install_name_rule()
    if len(str(conclusion).strip()) < 10:
        raise AssertionError("第 ③ 问还没写：这条规则会误伤什么？")

    names = [name for name, _, _ in REDACTION_RULES]
    if RULE_NAME not in names:
        raise AssertionError(f"规则表里没有 {RULE_NAME!r}，实际有：{names}")

    # ① 姓名必须被打码，而且格式是「客户张*」（保留姓）
    expected, got = assert_masking_style(pii)
    if got != expected:
        raise AssertionError(f"「客户张伟」应该打成 {expected!r}，你的规则给出的是 {got!r}")
    after, hits = apply_rules(pii)
    if "客户张*" not in after:
        raise AssertionError(f"脱敏后没看到「客户张*」：{after!r}")
    if "张伟" in after:
        raise AssertionError("名字没被打掉，规则等于没生效")

    # ② 原有的脱敏能力不能被弄坏（身份证 / 邮箱仍然要被打码）
    if "11010119900307123X" in after:
        raise AssertionError("身份证没有被脱敏 —— 你的规则插错位置，把后面的规则挡住了")
    if "zhangwei@example.com" in after:
        raise AssertionError("邮箱没有被脱敏 —— 同上")

    print("    脱敏规则表：")
    show_rules()
    print("    样本对照：")
    print(f"      {'场景':<10}{'原始输出':<40}{'脱敏后':<40}命中")
    print("      " + "-" * 104)
    for label, text in SAMPLES:
        clean, found = apply_rules(text)
        print(f"      {label:<10}{text[:38]:<40}{clean[:38]:<40}{','.join(found)}")
    print()
    kv("姓名规则", f"「客户张伟」→「{got}」（保留姓氏，打码名字）")
    kv("规则条数", f"{len(REDACTION_RULES)} 条（原来 5 条 + 你加的 1 条）")

    # ③ 误伤是这一题的"另一半答案"：让你的规则自己证明它会误伤
    print()
    print("    你的规则的副作用（误伤检查）：")
    hurt: list[tuple[str, str]] = []
    for word in INNOCENT:
        clean, _ = apply_rules(word)
        if clean != word:
            hurt.append((word, clean))
        print(f"      {word} → {clean}" + ("   ← 误伤" if clean != word else ""))
    print()
    if hurt:
        kv("误伤", f"{len(hurt)} 个词：{[w for w, _ in hurt]}")
        note("★ 这就是「纯正则脱中文姓名」的代价 —— 题目让你亲手看见它。")
    else:
        note("★ 你的规则居然没误伤这些词 —— 说明你用了比题目更精细的做法")
        note("  （名单匹配 / 上下文判定）。这正是工业做法，值得表扬。")
    kv("你的结论", str(conclusion).strip()[:56])
    print()
    warn("★ 中文姓名是最难脱敏的一类：没有固定格式，纯正则必然误伤正常词汇。")
    note("  所以工业做法是「名单匹配」（有确切客户名单时精确替换）或「模型判定」")
    note("  （让它认出「这是一个人名」而不是「这是一个以客户开头的词」）。")
    bullet("脱敏不是「删掉就算」：打码要保留足够的排障信息（客户张* 比 *** 有用）")
    bullet("规则顺序 = 执行顺序：前一条的输出是后一条的输入，插错位置会挡住别的规则")
    bullet("PII 有三个泄露面：输入侧、输出侧、**日志侧** —— 最后一个最容易被忽略")


def main() -> int:
    try:
        check_4()
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
