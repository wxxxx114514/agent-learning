r"""第 00 章 · 练习 2 / 4 · 故意把 JSON 写坏，看程序怎么反应

【要做什么】
  故意把 JSON 写坏，看程序怎么反应。

  把 `CalcLLM` 的输出改成 `1+1` 不加引号的非法 JSON。

  观察：`json.loads` 抛什么异常？`parse_tool_call` 返回什么？循环还能继续吗？

【已经给你了】
  · `CALL_RE`            —— 从模型输出里抠出 `<call>…</call>` 的正则
  · `parse_tool_call(text)` —— 解析器，中间的 `json.loads` 那段留给你写
  · `BrokenJsonLLM`      —— 输出非法 JSON 的假模型（全局变量 `LLM` 就是它）
  · `GoodJsonLLM`        —— 输出合法 JSON 的对照模型（`LLM = GoodJsonLLM()` 即可切换）
  · `make_llm()`         —— 只返回模型输出，方便你单独观察解析结果

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch00_setup\ex2_broken_json.py
  3. 验收本章：py scripts\run_all_checks.py 00
     （第 00 章 没有 stages/stage00_* 目录，这个脚本会提示它，不影响你做题）
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                                                   # noqa: E402
import re                                                     # noqa: E402

from core.llm import LLM, LLMResponse                         # noqa: E402
from core.message import Message                              # noqa: E402

CALL_RE = re.compile(r"<call>(\{.*?\})</call>", re.S)

MAX_ROUNDS = 3          # 循环最多跑几圈（这个循环里没人给它答案，只能靠它兜底）


class GoodJsonLLM(LLM):
    """对照组：输出合法的 JSON，解析器能正常解析出来。"""

    name = "good-json"

    def _complete(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(
            text='Thought: 申请计算。\n'
                 '<call>{"name": "calc", "args": {"expr": "1+1"}}</call>'
        )


class BrokenJsonLLM(LLM):
    """捣乱组：输出 `1+1` 不加引号的非法 JSON —— json.loads 会抛异常。"""

    name = "broken-json"

    def _complete(self, messages, **kwargs) -> LLMResponse:
        return LLMResponse(
            text="Thought: 申请计算。\n"
                 '<call>{"name": "calc", "args": {"expr": 1+1}}</call>'   # ← 非法 JSON
        )


LLM = BrokenJsonLLM()        # ← 想看正常情况：把这行改成 LLM = GoodJsonLLM()


def make_llm():
    """只调一次模型，把它输出的一段文本给你。"""
    return LLM.complete([Message.user("帮我算 1+1")]).text


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def parse_tool_call(text: str):
    """从模型输出里抠出工具调用。

    参数 text：模型的原始输出（一整段字符串）
    返回    ：(工具名, 参数字典)；**解析不出来时必须返回 None，不许抛异常**

    三步：
      1. m = CALL_RE.search(text)；`if not m: return None`
         （search 找不到时返回 None 而不是报错 —— 忘了判空，下一行 .group() 就抛 AttributeError）
      2. `try: obj = json.loads(m.group(1))`
         `except json.JSONDecodeError: return None`
         （模型经常把 JSON 写坏，这是**必然会发生**的，不是意外）
      3. 检查 obj 是 dict 且有 "name"，返回 (obj["name"], obj.get("args", {}))
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 2 · TODO  parse_tool_call 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 00 章 · 练习 2 · 把 JSON 写坏会怎样")
    print("=" * 68)

    # ① 先单独看解析器：坏 JSON 和好 JSON 各返回什么
    bad = '<call>{"name": "calc", "args": {"expr": 1+1}}</call>'
    good = '<call>{"name": "calc", "args": {"expr": "1+1"}}</call>'
    try:
        print("\n  解析器对坏 JSON 的返回：", repr(parse_tool_call(bad)))
        print("  解析器对好 JSON 的返回：", repr(parse_tool_call(good)))
        print("  解析器对普通闲聊：      ", repr(parse_tool_call("我今天心情不错")))
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    if parse_tool_call(bad) is not None:
        print("\n❌ 坏 JSON 应该返回 None，现在却解析出了东西")
        return 1
    if parse_tool_call(good) != ("calc", {"expr": "1+1"}):
        print("\n❌ 好 JSON 应该解析成 ('calc', {'expr': '1+1'})，现在不是")
        return 1
    print("  ★ json.loads 抛的是 json.JSONDecodeError，被 except 接住后返回 None")

    # ② 再看循环：解析不出来时会不会崩、会不会继续
    print(f"\n  让循环跑 {MAX_ROUNDS} 圈（模型永远写坏 JSON）：")
    messages = [Message.user("帮我算 1+1")]
    rounds = 0
    for i in range(1, MAX_ROUNDS + 1):
        rounds = i
        reply = make_llm()
        call = parse_tool_call(reply)
        messages.append(Message.assistant(reply))
        if call is None:
            print(f"    第 {i} 圈：没解析出工具调用 -> 打印一句提示，继续下一圈")
            continue
        name, args = call
        messages.append(Message.tool_result(name, "（真的执行了工具）"))
        print(f"    第 {i} 圈：解析出 {name}{args}")

    print(f"\n  循环正常跑完 {rounds} 圈，一次异常都没抛。")
    print("\n✅ 跑通了")
    print("   ★ 问题也在此：模型永远写不对，循环就永远空转 ——")
    print("     所以「解析失败要回灌纠错 + 重试上限」，这是第 03 章的题目。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
