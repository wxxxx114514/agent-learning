r"""第 02 章 · 练习 4 / 5 · 给 `count_words` 写一份好的 description

【要做什么】
  给 `count_words` 写一份好的 description。

  现在它写的是「统计一段文本的总字符数与中文字数」。
  按四要素（功能 + 参数格式 + 使用时机 + 边界）重写一版。

  然后对比：什么样的 description 会让模型更不容易用错？

【已经给你了】
  · `count_words(text)`      —— 工具函数本身（返回字符数 / 中文字数 / 英文单词数 / 行数）
  · `WEAK_DESCRIPTION`       —— 现在这句"只说了功能"的差描述
  · `BETTER_DESCRIPTION`     —— 你要写的地方（TODO ①）
  · `describe_score(text)`   —— 把描述里出现的四要素逐条列出来（不评分，只列事实）
  · `pick_tool(question)`    —— 一个玩具版"工具选择器"：模拟模型只根据系统提示词
                                里的工具说明来选择工具（选择依据全部可见，不用猜）
  · `QUESTIONS`              —— 四个测试问题（前两个该用 count_words，后两个不该）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch02_tools\ex4_write_description.py
  3. 验收本章：py scripts\run_all_checks.py 02
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.tool import ToolSpec                               # noqa: E402

CJK = ("\u4e00", "\u9fff")


def count_words(text: str) -> dict:
    """统计文本长度：字符数 / 中文字数 / 英文单词数 / 行数。"""
    import re
    cjk = sum(1 for ch in text if CJK[0] <= ch <= CJK[1])
    return {
        "总字符数": len(text),
        "中文字数": cjk,
        "英文单词数": len(re.findall(r"[A-Za-z]+", text)),
        "行数": text.count("\n") + 1,
    }


# 现在这份描述：只说了"功能"，没说"什么时候用 / 什么时候别用"
WEAK_DESCRIPTION = "统计一段文本的总字符数与中文字数。"

# TODO ① ── 在这里写你的版本（四要素：功能 + 参数格式 + 使用时机 + 边界）
#   提示：可以写成几行拼接的字符串，方便读：
#       BETTER_DESCRIPTION = (
#           "统计……"
#           "……"
#       )
#   ★ 别改函数、别改函数名，只写这段文字 —— 模型看到的就只是这段文字。
BETTER_DESCRIPTION = ""

# 四要素的判定关键词（只用来"列出事实"，不是评分标准）
ELEMENTS = {
    "功能":   ("统计", "字符数", "字数", "行数"),
    "参数格式": ("text", "原文", "内容", "直接传"),
    "使用时机": ("必须", "当用户", "如果用户问", "需要"),
    "边界":   ("不要", "改用", "不适合", "其它工具", "其他工具", "而不是"),
}

QUESTIONS = [
    ("这段有多少字？", True),         # 该用 count_words
    ("帮我数一下这句话的字数", True),   # 该用 count_words（有"句"字，但问的确实是"多少个字"）
    ("这段有几句话？", False),         # 不该用（那是分句统计，中文句号怎么切是另一回事）
    ("这句话语法对不对？", False),      # 不该用（那是语法检查）
]

# 每个问题"真正"该调哪个工具（这是标准答案，与 description 无关）
TOOL_KEYWORDS = {
    "count_words": ("多少字", "字数", "数一下", "统计"),      # 需要"使用时机"这句才会被选中
    "sentence_split": ("几句",),                             # 需要"边界"这句才会被改选到这里
    "grammar_check": ("语法",),                              # 同上
}


def describe_score(text: str) -> dict:
    """列出这段描述里出现了哪几个要素（不评分，只列事实）。"""
    return {name: [k for k in kws if k in text] for name, kws in ELEMENTS.items()}


def pick_tool(question: str, description: str):
    """玩具版工具选择器：只看两个工具的说明，决定该调哪个。

    这不是真模型，而是把"模型依据说明做选择"这件事**变成可复现的规则**：

      · 先按 `TOOL_KEYWORDS` 判断"这个问题**真正**该用哪个工具"（标准答案）
      · 再看 description 里有没有写清「什么时候该用我」和「什么情况别用我」：
          - 该用、但没写"使用时机" -> 模型犹豫，干脆不用 -> 记一次"漏用"
          - 不该用、但没写"边界"   -> 模型看名字像就用了 -> 记一次"用错"
          - 两句都写清 -> 与标准答案一致 ✅

    返回 (选中的工具名, 依据说明)。工具名后面带 "(……)" 表示选错了。
    """
    # ① 标准答案（与 description 无关）
    correct = "final_answer"
    for want, keywords in TOOL_KEYWORDS.items():
        if any(k in question for k in keywords):
            correct = want
            break

    # ② 模型能从这段 description 里读到什么
    says_when = ("必须" in description) or ("当用户" in description)
    says_boundary = ("改用" in description) and (
        "其它工具" in description or "其他工具" in description)

    if correct == "count_words":
        if says_when:
            return "count_words", "命中「什么时候该用我」"
        return "count_words(漏用)", "描述没写清使用时机，模型没敢用"

    # 不该用 count_words 的问题：只有写了边界，模型才会改选别的工具
    if says_boundary:
        return "other_tool", "命中「边界：这种情况别用我」"
    return "count_words(用错了)", "描述没写清边界，模型看名字像就用了"


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def why_better(weak: dict, better: dict) -> str:
    """TODO ② ── 对比两份描述的四要素覆盖情况，写下你的结论。

    参数 weak / better 是 `describe_score()` 对两份描述的输出，形如
        {"功能": ["统计", ...], "参数格式": [...], "使用时机": [...], "边界": [...]}

    写清：多出来的那几项**具体**改变了什么（模型在什么情况下会因此少犯错）。
    返回你的一段结论（写 30 个字以上，不许返回空串）。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 4 · TODO ②  why_better 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 02 章 · 练习 4 · 工具说明是写给模型看的")
    print("=" * 68)

    if not BETTER_DESCRIPTION.strip():
        print("\n⬜ 还没写：练习 4 · TODO ①  BETTER_DESCRIPTION 还没有写")
        return 0
    if BETTER_DESCRIPTION.strip() == WEAK_DESCRIPTION.strip():
        print("\n❌ 这跟原来那句一模一样，要重写一版")
        return 1
    if len(BETTER_DESCRIPTION.strip()) < 40:
        print(f"\n❌ 太短了（{len(BETTER_DESCRIPTION.strip())} 字）—— 四要素塞不进一句话")
        return 1

    print(f"\n  【差描述】{WEAK_DESCRIPTION}")
    weak = describe_score(WEAK_DESCRIPTION)
    for name, hits in weak.items():
        print(f"      {name:<6}: {'命中 ' + str(hits) if hits else '—— 没提'}")

    print(f"\n  【你的描述】{BETTER_DESCRIPTION}")
    better = describe_score(BETTER_DESCRIPTION)
    for name, hits in better.items():
        print(f"      {name:<6}: {'命中 ' + str(hits) if hits else '—— 没提'}")

    missing = [name for name, hits in better.items() if not hits]
    if missing:
        print(f"\n❌ 四要素里还缺：{missing}")
        print("   提示：功能（统计什么）+ 参数格式（text 直接传原文）+")
        print("         使用时机（当用户问「多少字」时必须用它）+")
        print("         边界（问「几句」「语法对不对」请改用其它工具）")
        return 1

    print("\n  把两份说明分别拿去选工具（同样的四个问题）：")
    wrong_weak = wrong_better = 0
    for question, should_use in QUESTIONS:
        tool_w, _ = pick_tool(question, WEAK_DESCRIPTION)
        tool_b, why = pick_tool(question, BETTER_DESCRIPTION)
        want = "count_words" if should_use else "其它"
        bad_w = ("count_words" in tool_w) != should_use or tool_w.endswith("(用错了)")
        bad_b = ("count_words" in tool_b) != should_use or tool_b.endswith("(用错了)")
        wrong_weak += bool(bad_w)
        wrong_better += bool(bad_b)
        print(f"    {question:<20} 期望 {want:<12} 差描述->{tool_w:<18} 你的->{tool_b:<12} ({why})")

    print(f"\n  选错次数：差描述 {wrong_weak} 次 / 你的描述 {wrong_better} 次")
    if wrong_better >= wrong_weak:
        print("\n❌ 你的描述没能让选择器变准 —— 多半是「边界」那句没写到点子上")
        print("   试试明确写出：问「有几句」「语法对不对」时请改用其它工具")
        print("   （「使用时机」那句会让该用的场景真的被选上，也别漏）")
        return 1

    try:
        conclusion = why_better(weak, better)
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print(f"\n  你的结论（{len(str(conclusion))} 字）：")
    for line in str(conclusion).splitlines():
        print("      " + line)
    if len(str(conclusion).strip()) < 30:
        print("\n❌ 结论太短 —— 要说清多出来的要素**具体**减少了哪种错")
        return 1

    print("\n  顺手看看框架版渲染出来的说明（ToolSpec.to_prompt_line）：")
    spec = ToolSpec(name="count_words", description=BETTER_DESCRIPTION,
                    parameters={"type": "object",
                                "properties": {"text": {"type": "string"}},
                                "required": ["text"]})
    print("      " + spec.to_prompt_line()[:150])
    print("      " + spec.example_call())

    print("\n✅ 跑通了")
    print("   ★ 要点：description 是**写给模型看的说明书**，不是写给人看的注释。")
    print("     四要素 = 功能 + 参数格式 + 使用时机 + 边界（什么情况别用我）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
