r"""第 03 章 · 练习 2 / 5 · 故意制造静默错误：把「协议违规」检测拆掉

【要做什么】
  把 `looks_like_broken_protocol()` 改成永远返回 `False`，
  然后重新跑第 ⑤ 节的对比。

  观察：坏掉的工具调用会变成什么？
  思考：这种 bug 在真实项目里为什么特别难发现？

【已经给你了】
  · BROKEN / CHAT             一条「写崩的工具调用」+ 一条「真正的聊天内容」
  · parse_output(text)        课程自带解析器（护栏完好）—— 用它做正确行为的对照
  · simulate_parse(text, ...) 复刻第 ⑤ 节那段兜底逻辑的骨架（循环和返回都写好了）
  · looks_like_broken_protocol_off(text)  你要拆掉的那个判定函数

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch03_react_prompt\ex2_silent_error.py
  3. 验收本章：py scripts\run_all_checks.py 03
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.parser import parse_output   # noqa: E402

# ① 写崩的工具调用：括号没闭合，也没有 Final Answer
BROKEN = 'Thought: 我要算一下\nAction: calc(expr="1+1"'
# ② 真正的聊天内容：没有任何协议标记
CHAT = "你好呀，今天天气不错。"


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def looks_like_broken_protocol_off(text: str) -> bool:
    """把护栏拆掉：对**任何**输入都回答「这不是坏掉的协议」。

    TODO ① ── 写一行就够：永远返回 False。
    （对照：core/parser.py 里的 _looks_like_broken_protocol 会去查
      Action:/Thought:/<tool_call>/Final Answer 这些关键词，还有 "name":/"args": 这类字段名。）
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 2 · TODO ①  looks_like_broken_protocol_off 永远返回 False")
    # ↑↑↑ 你的答案 ↑↑↑


def simulate_parse(text: str) -> dict:
    """复刻第 ⑤ 节那段兜底逻辑，用来对比「护栏在 / 护栏拆了」。

    前后都写好了：先用真正的解析器拿到 thought / tool_calls / errors，
    再决定「什么都没提取到时」要不要把整段文本退化成答案。你只写中间那段兜底。

    返回的 dict 里有四个键：thought / calls / errors / answer
    """
    p = parse_output(text)
    info = {
        "thought": p.thought,
        "calls": [c.signature() for c in p.tool_calls],
        "errors": list(p.errors),
        "answer": p.answer,
    }

    # TODO ② ── 写出「危险兜底」：把护栏拆掉之后，解析器会怎么做？
    #   三种情况，按顺序判断：
    #     ① 已经拿到 tool_calls 或有 answer  → 不用兜底，直接返回 info（原样）
    #     ② 既没调用也没答案，且 looks_like_broken_protocol_off(text) 为真
    #        → 判定为协议违规：answer 保持空串（交给上层回灌纠错）
    #     ③ 其余情况（真正的聊天内容）→ answer = text.strip()
    #   提示：这里不需要 try/except，就是 if / elif / else 三段。
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 2 · TODO ②  simulate_parse 里的兜底分支")
    # ↑↑↑ 你的答案 ↑↑↑

    # 兜底的直接后果：有答案 -> Agent 立刻停机；没答案 -> 上层还能回灌纠错
    info["stop_reason"] = "final_answer" if info["answer"].strip() else "parse_failed"
    return info

# TODO ③ ── 纯思考题：写下你的结论（一两句话就行，不用写代码）
#   提示：想想「程序不报错」+「监控指标全绿」+「只有答案内容是错的」这三件事叠在一起，
#         再想想如果没有第 ⑤ 节那套判定，这个 bug 会在哪一步、被谁发现？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        # ---- 先确认护栏真的被拆掉了（TODO ①）----
        if looks_like_broken_protocol_off(BROKEN):
            raise AssertionError(
                "TODO ① 要把它改成永远返回 False；现在它对协议标记仍然返回 True")

        # ---- 先看课程自带解析器（护栏完好）怎么处理这两条输入 ----
        real_broken = parse_output(BROKEN)
        real_chat = parse_output(CHAT)
        report.append("【护栏完好】core.parser.parse_output（第 ⑤ 节的「安全兜底」）：")
        report.append(f"    坏掉的调用 -> answer={real_broken.answer!r}  "
                      f"errors={real_broken.errors[:1]}")
        report.append(f"    真聊天内容 -> answer={real_chat.answer!r}")
        report.append("")

        # ---- 再看你拆掉护栏之后的版本 ----
        off_broken = simulate_parse(BROKEN)
        off_chat = simulate_parse(CHAT)

        if not isinstance(off_broken, dict) or "answer" not in off_broken:
            raise AssertionError("simulate_parse 必须返回 dict（含 answer 键）")
        if off_broken["answer"].strip() == "":
            raise AssertionError(
                "护栏好像还在：坏掉的调用没有退化成答案。"
                "检查 TODO ① 是不是没拆掉（应永远返回 False），"
                "以及 TODO ② 里的分支是不是写反了")
        if off_chat["answer"] != CHAT:
            raise AssertionError(f"真正的聊天内容应该照常当答案，实际拿到 {off_chat['answer']!r}")

        report.append("【护栏拆掉】你的 simulate_parse（判定函数永远返回 False）：")
        report.append(f"    坏掉的调用 -> answer={off_broken['answer']!r}")
        report.append("      ^ 半截坏 JSON 被当成最终答案交给了用户！")
        report.append(f"    真聊天内容 -> answer={off_chat['answer']!r}   <- 这条两种兜底一样")
        report.append("")
        report.append("    于是这个 Agent 会这样收场：")
        report.append(f"      用户看到的答案 = {off_broken['answer'].splitlines()[-1]!r}")
        report.append(f"      stop_reason    = {off_broken['stop_reason']}   "
                      f"（看起来一切正常）")
        report.append(f"    而「护栏完好」那一版是 stop_reason = "
                      f"{'final_answer' if real_broken.answer.strip() else 'parse_failed'}"
                      f"，answer 留空 -> 上层才能回灌纠错（第 ⑥ 节）")
        report.append("")
        report.append("★ 这就是静默错误：不报错、不崩溃、监控指标全绿，只有答案是错的。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 2 · TODO ③  写下你的结论：这种 bug 为什么特别难发现？")
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
