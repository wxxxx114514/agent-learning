r"""第 03 章 · 练习 3 / 5 · 测一测不同模型的「指令遵循能力」

【要做什么】
  用**同一个提示词**跑几个「模型」，记录各自的「格式正确率」。
  这是选模型时最该看的指标之一 —— 它比跑分更能预测这个模型在你的 Agent 里好不好用。

  （题目原版是接真实 API 跑 2~3 个厂商的模型。这里用三个行为固定的假模型把实验做完，
    结论完全一样；有 API Key 的话，把 FakeModel 换成 core.real_llm 里的适配器即可。）

【已经给你了】
  · SYSTEM / MESSAGES     同一段系统提示词（PromptBuilder 生成）+ 同一个问题
  · StrictLLM / FenceLLM / ChattyLLM
                          三个行为固定的假模型：一个严格守约、一个时好时坏、一个完全不守约
  · REG                   课程默认工具注册表（parse_output 的 known_tools 用它）
  · parse_output(text, known_tools=...).has_tool_call   —— 判断「这次输出能不能解析出调用」

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch03_react_prompt\ex3_model_compliance.py
  3. 验收本章：py scripts\run_all_checks.py 03
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.llm import LLM, LLMResponse      # noqa: E402
from core.message import Message           # noqa: E402
from core.parser import parse_output       # noqa: E402
from core.prompts import PromptBuilder     # noqa: E402
from core.tool import build_default_registry  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
REG = build_default_registry(ROOT)

# ★ 三个模型收到的提示词**一模一样** —— 这是受控实验的关键
SYSTEM = PromptBuilder(
    style="react",
    persona="你是「小助手」，一个严谨的电商客服助理。",
    rules=["涉及金额计算一律用 calc，禁止心算。"],
).build_system(REG)
QUESTION = "计算 (12+8)*3/4"
MESSAGES = [Message.system(SYSTEM), Message.user(QUESTION)]
RUNS = 10        # 每个模型跑几次


class StrictLLM(LLM):
    """每次都严格按格式契约输出（Thought + Action + <tool_call>）。"""

    name = "strict"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        return LLMResponse(
            text='Thought: 这是算术问题，用 calc。\n'
                 'Action: calc(expr="(12+8)*3/4")\n'
                 '<tool_call>{"name": "calc", "args": {"expr": "(12+8)*3/4"}}</tool_call>',
            model=self.name,
        )


class FenceLLM(LLM):
    """一半时间用 Markdown 代码块（能救回来），一半时间把 JSON 写崩（救不回来）。"""

    name = "fence"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        if self.total_calls % 2 == 0:
            text = ('Thought: 我用 calc。\n```json\n'
                    '{"name": "calc", "args": {"expr": "(12+8)*3/4"}}\n```')
        else:
            # 参数值没加引号 —— 非法 JSON，而且没有 Action: 行可以兜底
            text = 'Thought: 我用 calc。\n{"name": "calc", "args": {"expr": (12+8)*3/4}}'
        return LLMResponse(text=text, model=self.name)


class ChattyLLM(LLM):
    """完全不按格式契约说话（自然语言里说着答案，程序一个字段都提不到）。"""

    name = "chatty"

    def _complete(self, messages: list[Message], **kwargs) -> LLMResponse:
        return LLMResponse(
            text="当然可以！我来帮你算一下。(12+8)*3/4 按照先乘除后加减，结果是 15。",
            model=self.name,
        )


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def compliance_rate(llm: LLM, runs: int = RUNS) -> float:
    """用同一段提示词（MESSAGES）跑 runs 次，返回「格式正确率」。

    前后都写好了（循环、计数、返回比例），你只写中间那一句判定。

    参数 llm ：要测的模型
         runs：跑几次
    返回     ：float，能解析出工具调用的次数 / 总次数
    """
    hits = 0
    for _ in range(runs):
        reply = llm.complete(MESSAGES).text

        # TODO ① ── 判断这一次输出能不能解析出工具调用，能就让 hits 加 1
        #   提示：p = parse_output(reply, known_tools=REG.names())，然后看 p.has_tool_call
        #        （不要用 `"calc" in reply` 这种土办法 —— 那会把自然语言里提到 calc
        #          也算成成功，测出来的正确率是虚高的）
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 3 · TODO ①  compliance_rate 里判断「这次输出可解析吗」")
        # ↑↑↑ 你的答案 ↑↑↑

    return hits / runs


# TODO ② ── 纯思考题：写下你的结论（一两句话就行）
#   提示：把「格式正确率」换算成业务后果 —— 50% 意味着每两次工具调用就有一次失败，
#         而失败的那次在用户看来是什么？监控里又能看到什么？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        models = (("严格守约 StrictLLM", StrictLLM),
                  ("时好时坏 FenceLLM", FenceLLM),
                  ("完全不理 ChattyLLM", ChattyLLM))
        rates: dict[str, float] = {}
        for label, factory in models:
            rate = compliance_rate(factory(), RUNS)
            if not isinstance(rate, float) or not 0.0 <= rate <= 1.0:
                raise AssertionError(f"compliance_rate 应返回 0~1 的比例，实际是 {rate!r}")
            rates[label] = rate

        if rates["严格守约 StrictLLM"] != 1.0:
            raise AssertionError(f"严格守约的模型应该 100% 可解析，实测 {rates['严格守约 StrictLLM']:.0%}")
        if rates["完全不理 ChattyLLM"] != 0.0:
            raise AssertionError(f"完全不理契约的模型应该 0%，实测 {rates['完全不理 ChattyLLM']:.0%}")
        if not 0.0 < rates["时好时坏 FenceLLM"] < 1.0:
            raise AssertionError(
                f"「时好时坏」那个模型应该落在 0 和 1 之间，实测 {rates['时好时坏 FenceLLM']:.0%}"
                "（想想：Markdown 代码块那一次为什么还能救回来？）")

        # 取一次「写崩」的样本给学生看（第 2 次调用才是崩的那次）
        fence = FenceLLM()
        fence.complete(MESSAGES)
        broken_sample = fence.complete(MESSAGES).text.splitlines()[-1]

        report.append(f"同一段提示词，每个模型跑 {RUNS} 次：")
        report.append("")
        for label, _ in models:
            rate = rates[label]
            bar = "#" * int(round(rate * 20)) + "." * (20 - int(round(rate * 20)))
            report.append(f"    {label:<20} 格式正确率 {rate:>4.0%}  [{bar}]")
        report.append("")
        report.append("    失败样本长什么样（FenceLLM 写崩的那一次）：")
        report.append(f"      {broken_sample[:72]}")
        report.append("      -> parse_output 拿不到调用，只会记一条协议违规")
        report.append("")
        report.append("    这三条正确率说明的事：")
        report.append("      · 同一段提示词下，模型的「指令遵循能力」差别是数量级的；")
        report.append("      · 提示词写得再好，也只能把「愿意守约」的模型拉满，")
        report.append("        拉不动一个根本不看格式契约的模型；")
        report.append("      · 所以选模型时，格式正确率要单独测 —— 它和跑分不是一回事。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 3 · TODO ②  写下你的结论：哪个数字最危险，为什么？")
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
