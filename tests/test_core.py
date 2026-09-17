"""框架级单元测试（不依赖网络、不依赖 API Key）。

用法：
    py -m unittest discover -s tests -v
    py tests\\test_core.py            # 也可以直接运行

与 scripts/run_all_checks.py 的分工：
    run_all_checks.py   验证**课程章节**的验收标准（教学视角）
    tests/test_core.py  验证**框架本身**的正确性（工程视角）

为什么两者都要？
    章节自检回答"学员学会了吗"，框架测试回答"内核有没有坏"。
    改动 core/ 之后，先跑框架测试确认没破坏内核，再跑章节自检确认没破坏课程。
"""

from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.agent import Agent  # noqa: E402
from core.errors import (  # noqa: E402
    BudgetExceeded, GuardrailTripped, LLMError as _CanonicalLLMError, ToolNotFound,
)
from core.llm import LLM, LLMError, LLMResponse, estimate_tokens  # noqa: E402
from core.message import Conversation, Message, ToolCall  # noqa: E402
from core.mock_llm import (  # noqa: E402
    FlakyLLM, HallucinatingLLM, LoopingLLM, MalformedLLM, RuleBasedLLM,
    ScriptedLLM, SpyLLM, default_mock,
)
from core.parser import parse_output, parse_tool_calls  # noqa: E402
from core.prompts import PromptBuilder  # noqa: E402
from core.real_llm import OpenAICompatLLM  # noqa: E402
from core.tool import ToolRegistry, ToolSpec, build_default_registry, validate_schema  # noqa: E402


# ===========================================================================
# 解析器
# ===========================================================================
class TestParser(unittest.TestCase):
    def test_tool_call_tag(self):
        calls = parse_tool_calls('<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "calc")
        self.assertEqual(calls[0].args, {"expr": "1+1"})

    def test_markdown_fence(self):
        calls = parse_tool_calls('```json\n{"name": "calc", "args": {"expr": "1+1"}}\n```')
        self.assertEqual(len(calls), 1)

    def test_single_quotes(self):
        calls = parse_tool_calls("<tool_call>{'name': 'calc', 'args': {'expr': '1+1'}}</tool_call>")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args["expr"], "1+1")

    def test_trailing_comma(self):
        calls = parse_tool_calls('<tool_call>{"name": "calc", "args": {"expr": "1+1",},}</tool_call>')
        self.assertEqual(len(calls), 1)

    def test_action_kv_fallback(self):
        calls = parse_tool_calls("Action: calc(expr=1+1)")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].args["expr"], "1+1")

    def test_thought_and_final_answer(self):
        p = parse_output("Thought: 我需要算一下\nFinal Answer: 结果是 15")
        self.assertEqual(p.thought, "我需要算一下")
        self.assertEqual(p.answer, "结果是 15")
        self.assertTrue(p.is_final)

    def test_openai_native_shape(self):
        p = parse_output('{"function": {"name": "calc", "arguments": "{\\"expr\\": \\"1+1\\"}"}}')
        self.assertEqual(len(p.tool_calls), 1)
        self.assertEqual(p.tool_calls[0].args["expr"], "1+1")

    # --- 关键回归：畸形输出不能退化成"最终答案" ---
    def test_broken_protocol_is_not_answer(self):
        """括号没闭合的调用不能被当成答案（否则是静默错误）。"""
        p = parse_output('Thought: 我要算一下\nAction: calc(expr="1+1"')
        self.assertEqual(p.answer, "")
        self.assertEqual(p.tool_calls, [])
        self.assertTrue(p.errors, "应当报出可读的协议违规错误")

    def test_illegal_json_is_not_answer(self):
        p = parse_output('{"name": "calc", "args": {"expr": 1+1}}   <-- 非法 JSON')
        self.assertEqual(p.answer, "")

    def test_plain_chat_is_answer(self):
        p = parse_output("你好呀，今天天气不错。")
        self.assertEqual(p.answer, "你好呀，今天天气不错。")

    def test_no_spurious_errors_on_standard_output(self):
        """标准 ReAct 输出（含 Action 行 + tool_call 标签）不应产生假错误。"""
        text = ('Thought: 用 calc 算。\n'
                'Action: calc(expr="1+1")\n'
                '<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>')
        p = parse_output(text)
        self.assertEqual(p.errors, [], f"出现了假错误: {p.errors}")
        self.assertEqual(len(p.tool_calls), 1)

    def test_empty_output(self):
        p = parse_output("")
        self.assertTrue(p.errors)
        self.assertFalse(p.tool_calls)


# ===========================================================================
# Schema 校验
# ===========================================================================
class TestSchema(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "properties": {"expr": {"type": "string", "minLength": 1}},
        "required": ["expr"],
        "additionalProperties": False,
    }

    def test_valid(self):
        self.assertEqual(validate_schema({"expr": "1+1"}, self.SCHEMA), [])

    def test_missing_required(self):
        errs = validate_schema({}, self.SCHEMA)
        self.assertTrue(any("缺少必填参数" in e for e in errs))

    def test_additional_properties_rejected(self):
        errs = validate_schema({"expr": "1+1", "unit": "元"}, self.SCHEMA)
        self.assertTrue(any("未定义参数" in e for e in errs))

    def test_bool_is_not_integer(self):
        """bool 是 int 的子类，必须特判，否则 True 会被当成合法 number。"""
        schema = {"type": "object", "properties": {"n": {"type": "integer"}}}
        self.assertTrue(validate_schema({"n": True}, schema))

    def test_int_is_valid_number(self):
        schema = {"type": "object", "properties": {"n": {"type": "number"}}}
        self.assertEqual(validate_schema({"n": 3}, schema), [])

    def test_pattern(self):
        schema = {"type": "string", "pattern": r"^[A-Z]\d{4}$"}
        self.assertTrue(validate_schema("abc", schema))
        self.assertEqual(validate_schema("A1001", schema), [])

    def test_all_errors_collected_at_once(self):
        """一次返回全部错误，而不是遇到第一个就返回。"""
        errs = validate_schema({"a": 1, "b": "x"}, {
            "type": "object",
            "properties": {"a": {"type": "string"}, "b": {"type": "integer"}},
        })
        self.assertEqual(len(errs), 2, f"应当一次报出两个错误，实际 {errs}")


# ===========================================================================
# 工具注册表（辅助函数定义在模块层，避免嵌套函数内省的不确定性）
# ===========================================================================
def _greet_for_schema(name: str, times: int = 1) -> str:
    """打招呼。"""
    return name * times


def _no_annotation(text, count=1, rate=1.5, flag=True):
    """没有类型注解的函数，用于测试"从默认值推断类型"。"""
    return text


class TestToolRegistry(unittest.TestCase):
    def setUp(self):
        self.reg = build_default_registry(ROOT)

    def test_calc_ok(self):
        r = self.reg.execute("calc", {"expr": "6*7"})
        self.assertTrue(r.ok)
        self.assertIn("42", r.content)

    def test_unknown_tool_lists_available(self):
        r = self.reg.execute("no_such_tool", {})
        self.assertFalse(r.ok)
        self.assertIn("calc", r.error)

    def test_wrong_param_name(self):
        r = self.reg.execute("calc", {"expression": "1+1"})
        self.assertFalse(r.ok)
        self.assertIn("expr", r.error)

    def test_execute_never_raises(self):
        """任何输入都不能让 execute 抛异常。"""
        for name, args in [
            ("calc", {}), ("calc", {"expr": None}), ("calc", {"expr": "1/0"}),
            ("calc", {"expr": "import os"}), ("lookup_order", {"order_id": "xx"}),
            ("read_file", {"path": "../../../etc/passwd"}),
            ("count_words", {"text": ""}),
        ]:
            try:
                r = self.reg.execute(name, args)
            except Exception as exc:
                self.fail(f"execute({name}, {args}) 抛出了 {type(exc).__name__}: {exc}")
            self.assertIsInstance(r.ok, bool)

    def test_calc_rejects_injection(self):
        for payload in ["__import__('os').system('echo x')",
                        "open('/etc/passwd').read()",
                        "(1).__class__"]:
            r = self.reg.execute("calc", {"expr": payload})
            self.assertFalse(r.ok, f"{payload} 应当被拒绝")

    def test_path_traversal_blocked(self):
        """越界路径必须被拒绝 —— 含"兄弟目录前缀绕过"这条回归用例。

        ★ 为什么必须有第二条：早期版本用 `str.startswith(str(root))` 判前缀。
          root 是 `.../agent-learning` 时，兄弟目录 `.../agent-learning_evil`
          的字符串同样以它开头，前缀检查会**放行** —— 多级 `..` 逃逸挡得住，
          这一条挡不住。改成 `Path.is_relative_to()` 后才真正拦住。
        """
        sibling = f"../{ROOT.name}_evil/x.txt"          # 解析后是 root 的兄弟目录
        for bad in ["../../../../etc/passwd", sibling]:
            r = self.reg.execute("read_file", {"path": bad})
            self.assertFalse(r.ok, f"{bad} 应当被拒绝")
            self.assertIn("拒绝", r.error, f"{bad} 应当报'拒绝访问'，而不是别的原因")

    def test_result_truncation(self):
        spec = ToolSpec(name="big", description="x",
                        parameters={"type": "object", "properties": {}},
                        func=lambda: "y" * 10000, max_result_chars=100)
        reg = ToolRegistry()
        reg.register(spec)
        r = reg.execute("big", {})
        self.assertTrue(r.ok)
        self.assertLess(len(r.content), 400)
        self.assertIn("截断", r.content)

    def test_duplicate_name_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.register(ToolSpec(name="calc", description="dup", parameters={}))

    def test_subset_by_tag(self):
        sub = self.reg.subset(["math"])
        self.assertIn("calc", sub.names())
        self.assertNotIn("read_file", sub.names())

    def test_from_function_autoschema(self):
        """函数即工具：内省签名自动生成 schema。

        注意：被测函数定义在模块层（`_greet_for_schema`），而不是嵌在测试方法里。
        嵌套函数在 unittest 上下文里内省行为不稳定，测试应该只考察被测逻辑本身。
        """
        reg = ToolRegistry()
        spec = reg.from_function(_greet_for_schema)
        self.assertEqual(spec.parameters["required"], ["name"])
        self.assertEqual(spec.parameters["properties"]["name"]["type"], "string")
        self.assertEqual(spec.parameters["properties"]["times"]["type"], "integer")
        self.assertEqual(spec.parameters["properties"]["times"]["default"], 1)

    def test_from_function_infers_type_from_default(self):
        """没有类型注解时，用默认值的类型推断 —— 否则模型会传字符串给 int 参数。"""
        reg = ToolRegistry()
        spec = reg.from_function(_no_annotation)
        self.assertEqual(spec.parameters["properties"]["count"]["type"], "integer")
        self.assertEqual(spec.parameters["properties"]["rate"]["type"], "number")
        self.assertEqual(spec.parameters["properties"]["flag"]["type"], "boolean")
        self.assertEqual(spec.parameters["required"], ["text"])

    def test_from_function_handles_postponed_annotations(self):
        """PEP 563 延迟注解（`from __future__ import annotations`）必须也能正确处理。

        这是一个真实的坑：开启延迟注解后，参数注解在运行时是**字符串**，
        `type_map.get("int")` 查不到，会静默退化成 "string" ——
        校验器就会放行字符串参数，直到函数执行时才炸。
        本测试文件顶部正好开了延迟注解，所以它天然覆盖了这个场景。
        """
        reg = ToolRegistry()
        spec = reg.from_function(_greet_for_schema)
        self.assertEqual(spec.parameters["properties"]["times"]["type"], "integer",
                         "延迟注解未被解析，说明退化成了 string")


# ===========================================================================
# 提示词
# ===========================================================================
class TestPrompts(unittest.TestCase):
    def test_react_has_all_four_blocks(self):
        reg = build_default_registry(ROOT)
        system = PromptBuilder(style="react", persona="客服", rules=["R1"],
                               extra_context="CTX").build_system(reg)
        for token in ["Action:", "<tool_call>", "Final Answer", "calc", "客服", "R1", "CTX"]:
            self.assertIn(token, system)

    def test_plain_has_no_tools(self):
        reg = build_default_registry(ROOT)
        system = PromptBuilder(style="plain").build_system(reg)
        self.assertNotIn("Action:", system)
        self.assertNotIn("calc", system)

    def test_format_braces_do_not_break(self):
        """ReAct 提示词含大量花括号，绝不能用 str.format 注入（会 KeyError）。"""
        reg = build_default_registry(ROOT)
        system = PromptBuilder(style="react").build_system(reg)
        self.assertIn("{", system)   # 花括号原样保留

    def test_parse_error_feedback_mentions_reason(self):
        fb = PromptBuilder.parse_error_feedback("JSON 没闭合")
        self.assertIn("JSON 没闭合", fb)
        self.assertIn("Final Answer", fb)

    def test_render_scratchpad(self):
        msgs = [Message.system("S"), Message.user("U"),
                Message.assistant("A", [ToolCall("calc", {"expr": "1"})]),
                Message.tool_result("calc", "R")]
        text = PromptBuilder.render_scratchpad(msgs)
        self.assertNotIn("S", text.split("\n")[0])   # 默认不含 system
        self.assertIn("用户: U", text)
        self.assertIn("Observation[calc]: R", text)

    def test_inject_retrieved(self):
        out = PromptBuilder.inject_retrieved(["片段A", "片段B"])
        self.assertIn("[片段 1]", out)
        self.assertIn("片段B", out)
        self.assertEqual(PromptBuilder.inject_retrieved([]), "")


# ===========================================================================
# 消息数据结构
# ===========================================================================
class TestMessage(unittest.TestCase):
    def test_roles(self):
        self.assertEqual(Message.system("x").role, "system")
        self.assertEqual(Message.user("x").role, "user")
        self.assertEqual(Message.assistant("x").role, "assistant")
        self.assertEqual(Message.tool_result("t", "x").role, "tool")

    def test_tool_call_stable_id(self):
        a = ToolCall("calc", {"expr": "1+1"})
        b = ToolCall("calc", {"expr": "1+1"})
        self.assertEqual(a.id, b.id, "相同调用应有相同 id（便于去重）")

    def test_tool_call_signature_order_insensitive(self):
        a = ToolCall("t", {"x": 1, "y": 2})
        b = ToolCall("t", {"y": 2, "x": 1})
        self.assertEqual(a.signature(), b.signature())

    def test_to_openai_tool_message(self):
        m = Message.tool_result("calc", "R", "call_1")
        d = m.to_openai()
        self.assertEqual(d["role"], "tool")
        self.assertEqual(d["tool_call_id"], "call_1")

    def test_to_openai_assistant_with_calls(self):
        m = Message.assistant("thinking", [ToolCall("calc", {"expr": "1"}, "call_1")])
        d = m.to_openai()
        self.assertEqual(d["tool_calls"][0]["function"]["name"], "calc")

    def test_conversation_helpers(self):
        c = Conversation()
        c.add(Message.system("s"))
        c.add(Message.user("u"))
        self.assertEqual(len(c), 2)
        self.assertEqual(c.last.content, "u")
        self.assertEqual(len(c.by_role("user")), 1)
        self.assertGreater(c.total_chars(), 0)

    def test_estimate_tokens(self):
        self.assertEqual(estimate_tokens(""), 0)
        self.assertGreater(estimate_tokens("你好世界"), 0)


# ===========================================================================
# Agent 主循环
# ===========================================================================
class TestAgentLoop(unittest.TestCase):
    def test_happy_path(self):
        r = Agent(llm=RuleBasedLLM(), max_steps=6, verbose=False).run("计算 (12+8)*3/4")
        self.assertEqual(r.stop_reason, "final_answer")
        self.assertIn("15", r.answer)
        self.assertTrue(r.ok)

    def test_max_steps_protection(self):
        """模型卡住时必须被 max_steps 拦住。"""
        r = Agent(llm=LoopingLLM(), max_steps=4, verbose=False).run("x")
        self.assertIn(r.stop_reason, {"max_steps", "loop_detected"})
        self.assertLessEqual(len(r.steps), 4)

    def test_looping_detected(self):
        r = Agent(llm=LoopingLLM(), max_steps=12, verbose=False).run("x")
        self.assertEqual(r.stop_reason, "loop_detected")

    def test_hallucinated_tool_recovered(self):
        r = Agent(llm=HallucinatingLLM(), max_steps=6, verbose=False).run("x")
        self.assertEqual(r.stop_reason, "final_answer")
        self.assertIn("42", r.answer)

    def test_malformed_then_recovers(self):
        r = Agent(llm=MalformedLLM(), max_steps=8, verbose=False).run("计算 1+1")
        self.assertEqual(r.stop_reason, "final_answer")

    def test_parse_failure_stops(self):
        """永远写不对的模型必须停机，而不是无限重试。"""
        r = Agent(llm=ScriptedLLM(['Thought: x\nAction: calc(expr="1+1"'], repeat_last=True),
                  max_steps=20, max_parse_retries=2, verbose=False).run("计算 1+1")
        self.assertEqual(r.stop_reason, "parse_failed")
        self.assertLessEqual(len(r.steps), 4)

    def test_llm_retry_eventually_fails_gracefully(self):
        r = Agent(llm=FlakyLLM(fail_times=99), max_steps=3, max_llm_retries=1,
                  verbose=False).run("x")
        self.assertEqual(r.stop_reason, "error")
        self.assertTrue(r.error)

    def test_llm_retry_actually_recovers(self):
        """回归测试：模型抖动后重试必须能成功。

        这条测试守着一个很隐蔽的 Bug —— 曾经存在两个互不相干的 LLMError
        （core.errors.LLMError 与 core.llm.LLMError），导致 Agent 的重试分支
        永远不执行：代码看着有重试，实际表现是"一抖动就失败"。
        """
        r = Agent(llm=FlakyLLM(fail_times=2), max_steps=3, max_llm_retries=3,
                  verbose=False).run("x")
        self.assertEqual(r.stop_reason, "final_answer", f"重试没有生效: {r.error}")
        self.assertIn("重试成功", r.answer)
        self.assertIn("尝试成功", r.steps[0].note)

    def test_llm_error_classes_are_unified(self):
        """core.errors.LLMError 与 core.llm.LLMError 必须兼容（同一个异常族）。"""
        self.assertTrue(issubclass(LLMError, _CanonicalLLMError),
                        "core.llm.LLMError 必须继承 core.errors.LLMError，"
                        "否则 Agent 的 except 抓不到适配器抛的异常")

    def test_trace_is_readable(self):
        r = Agent(llm=RuleBasedLLM(), max_steps=6, verbose=False).run("计算 1+1")
        trace = r.trace()
        self.assertIn("Agent 推理轨迹", trace)
        self.assertIn("停止原因", trace)

    def test_observer_receives_events(self):
        events: list[str] = []
        Agent(llm=RuleBasedLLM(), max_steps=6, verbose=False,
              observer=lambda e, p: events.append(e)).run("计算 1+1")
        for expected in ["user_input", "step_start", "llm_output", "run_end"]:
            self.assertIn(expected, events, f"缺少事件 {expected}")

    def test_observer_exception_does_not_break_run(self):
        """观察者抛异常不能影响 Agent 运行（监控代码不该拖垮业务）。"""
        def bad_observer(event, payload):
            raise RuntimeError("监控系统挂了")
        r = Agent(llm=RuleBasedLLM(), max_steps=6, verbose=False,
                  observer=bad_observer).run("计算 1+1")
        self.assertEqual(r.stop_reason, "final_answer")

    def test_approval_hook_blocks_high_risk_tool(self):
        """高危工具被拒绝后，Agent 不能重试，而应向用户说明。"""
        calls: list[str] = []
        r = Agent(llm=ScriptedLLM([
            'Thought: 我要写文件。\n'
            '<tool_call>{"name": "write_note", "args": {"path": "x.md", "text": "hi"}}</tool_call>',
            'Thought: 被拒绝了，我向用户说明。\nFinal Answer: 无法写入，需要授权。',
        ]), max_steps=4, verbose=False, workspace=str(ROOT),
            approval_hook=lambda call: (calls.append(call.name), False)[1]).run("写个笔记")
        self.assertEqual(calls, ["write_note"], "审批钩子应当被调用")
        self.assertEqual(r.stop_reason, "final_answer")
        self.assertNotIn("hi", r.answer)

    def test_conversation_reset_by_default(self):
        a = Agent(llm=RuleBasedLLM(), max_steps=4, verbose=False)
        a.run("计算 1+1")
        n1 = len(a.conversation)
        a.run("计算 2+2")
        self.assertLess(len(a.conversation), n1 * 2, "默认应当重置历史")

    def test_context_guard_folds_long_history(self):
        """超长上下文必须被折叠，避免撑爆窗口。"""
        big = "x" * 5000
        llm = ScriptedLLM([
            f'Thought: 存一下。\n<tool_call>{{"name": "count_words", "args": {{"text": "{big}"}}}}</tool_call>',
            'Thought: 好了。\nFinal Answer: ok',
        ])
        r = Agent(llm=llm, max_steps=4, verbose=False, context_char_limit=1200).run("统计")
        self.assertEqual(r.stop_reason, "final_answer")

    def test_function_calling_style_passes_tools_to_llm(self):
        """style="function_calling" 时，工具规格必须作为 API 参数下发。

        ★ 回归测试：早期 `core/agent.py` 只传 messages，于是
          `real_llm.py` 的 tools 分支和 `tool.py` 的 `openai_tools()`
          全是**死代码** —— 代码和文档各说各话，谁也没发现。
        """
        seen: list[dict] = []

        class Recorder(LLM):
            name = "recorder"

            def _complete(self, messages, **kwargs):
                seen.append(kwargs)
                return LLMResponse(text="Thought: 不用工具。\nFinal Answer: 好的")

        reg = build_default_registry(ROOT)
        Agent(llm=Recorder(), tools=reg,
              prompt=PromptBuilder(style="function_calling"),
              max_steps=2, verbose=False).run("你好")
        self.assertTrue(seen, "模型应当至少被调用一次")
        self.assertIn("tools", seen[0], "原生 function calling 必须下发 tools")
        self.assertIn("calc", [t["function"]["name"] for t in seen[0]["tools"]])
        self.assertEqual(seen[0]["tool_choice"], "auto")

    def test_react_style_does_not_pass_tools_to_llm(self):
        """文本协议走系统提示词，不该下发 tools（否则干扰服务商 / 老端点报错）。"""
        seen: list[dict] = []

        class Recorder(LLM):
            name = "recorder"

            def _complete(self, messages, **kwargs):
                seen.append(kwargs)
                return LLMResponse(text="Thought: 不用工具。\nFinal Answer: 好的")

        Agent(llm=Recorder(), prompt=PromptBuilder(style="react"),
              max_steps=2, verbose=False).run("你好")
        self.assertTrue(seen)
        self.assertNotIn("tools", seen[0], "react 风格不该下发 tools")

    def test_real_llm_payload_carries_tools(self):
        """真实适配器的请求体要带上 tools / tool_choice（离线验证，不发网络请求）。"""
        llm = OpenAICompatLLM(api_key="sk-test", base_url="https://example.invalid/v1")
        body = llm._payload([Message.user("hi")],
                            tools=build_default_registry(ROOT).openai_tools(),
                            tool_choice="auto")
        self.assertIn("tools", body)
        self.assertEqual(body["tool_choice"], "auto")
        self.assertIn("calc", [t["function"]["name"] for t in body["tools"]])


# ===========================================================================
# Mock 模型自身
# ===========================================================================
class TestMockModels(unittest.TestCase):
    def test_scripted_records_calls(self):
        llm = ScriptedLLM(["A", "B"])
        llm.complete([Message.user("q")])
        self.assertEqual(len(llm.calls), 1)

    def test_scripted_repeat_last(self):
        llm = ScriptedLLM(["A"], repeat_last=True)
        for _ in range(3):
            llm.complete([Message.user("q")])
        self.assertEqual(llm.total_calls, 3)

    def test_scripted_exhausted_raises(self):
        llm = ScriptedLLM(["A"], repeat_last=False)
        llm.complete([Message.user("q")])
        with self.assertRaises(Exception):
            llm.complete([Message.user("q")])

    def test_spy_wraps_and_records(self):
        spy = SpyLLM(default_mock())
        spy.complete([Message.user("计算 1+1")])
        self.assertEqual(len(spy.seen), 1)
        self.assertIn("1+1", spy.last_prompt())

    def test_flaky_fails_then_succeeds(self):
        llm = FlakyLLM(fail_times=2)
        with self.assertRaises(LLMError):
            llm.complete([Message.user("q")])
        with self.assertRaises(LLMError):
            llm.complete([Message.user("q")])
        resp = llm.complete([Message.user("q")])
        self.assertIn("重试成功", resp.text)

    def test_default_mock_plans_tool_calls(self):
        llm = default_mock()
        self.assertTrue(llm.plan("计算 1+1"))
        self.assertTrue(llm.plan("订单 A1001 到哪了"))

    def test_stats_accumulate(self):
        llm = RuleBasedLLM()
        llm.complete([Message.user("计算 1+1")])
        stats = llm.stats()
        self.assertEqual(stats["calls"], 1)
        self.assertGreater(stats["total_tokens"], 0)


# ===========================================================================
# 异常体系
# ===========================================================================
class TestErrors(unittest.TestCase):
    def test_hierarchy(self):
        from core.errors import AbortAgent, AgentError
        self.assertTrue(issubclass(ToolNotFound, AgentError))
        self.assertTrue(issubclass(GuardrailTripped, AbortAgent))
        self.assertTrue(issubclass(BudgetExceeded, AbortAgent))
        self.assertTrue(issubclass(AbortAgent, AgentError))

    def test_tool_not_found_message_lists_tools(self):
        reg = build_default_registry(ROOT)
        with self.assertRaises(ToolNotFound) as ctx:
            reg.get("nope")
        self.assertIn("calc", str(ctx.exception))


# ===========================================================================
# 课程材料结构（保证 13 章契约不被破坏）
# ===========================================================================
class TestCourseStructure(unittest.TestCase):
    def test_core_imports(self):
        import core
        self.assertTrue(core.__version__)

    def test_console_never_raises(self):
        """教学输出工具绝不能抛异常（否则会掩盖真正的知识点）。"""
        import io
        from contextlib import redirect_stdout
        from core.console import banner, code, essence, kv, note, section, warn

        buf = io.StringIO()
        with redirect_stdout(buf):
            banner("t", "s")
            section("t", "①")
            note("n")
            warn("w")
            kv("k", "v")
            code("c", indent=2)
            essence("e")
        # 确认真的产出了内容（而不是静默吞掉一切）
        self.assertIn("一句话本质", buf.getvalue())

    def test_every_stage_has_required_files(self):
        """已完成的章节必须有完整三件套。

        只检查"有 demo.py 的章节"——正在编写的章节目录可能先建目录后补文件，
        这种半成品不应该让测试失败（否则会误报）。
        """
        stages = [p for p in (ROOT / "stages").glob("stage*") if p.is_dir()]
        self.assertGreater(len(stages), 0, "没有发现任何章节")
        for stage in stages:
            if not (stage / "demo.py").exists():
                continue          # 尚未开始编写的章节，跳过
            for fname in ("__init__.py", "demo.py"):
                self.assertTrue((stage / fname).exists(),
                                f"{stage.name} 缺少 {fname}")

    def test_every_stage_demo_compiles(self):
        import ast
        for stage in (ROOT / "stages").glob("stage*"):
            demo = stage / "demo.py"
            if not demo.exists():
                continue
            try:
                ast.parse(demo.read_text(encoding="utf-8"), filename=str(demo))
            except SyntaxError as exc:
                self.fail(f"{stage.name}/demo.py 语法错误 第 {exc.lineno} 行: {exc.msg}")

    def test_every_stage_exposes_run_checks(self):
        for stage in sorted((ROOT / "stages").glob("stage*")):
            demo = stage / "demo.py"
            if not demo.exists():
                continue
            src = demo.read_text(encoding="utf-8")
            self.assertIn("def run_checks", src,
                          f"{stage.name}/demo.py 未实现 run_checks()（违反课程契约）")
            self.assertIn("setup_console", src,
                          f"{stage.name}/demo.py 未调用 setup_console（GBK 下会崩）")


# ===========================================================================
# 文档与 Notebook 产物（防止"文档指向不存在的文件"这类静默腐化）
# ===========================================================================
class TestDocsAndNotebooks(unittest.TestCase):
    """文档会随代码演进腐化：链接失效、命令改名、Notebook 产物过期。

    这些断言让腐化"立刻可见"，而不是等读者点到 404 才发现。
    """

    TOP_DOCS = ["README.md", "CHAPTERS.md", "ROADMAP.md",
                "NOTES.md", "notebooks/README.md"]

    @staticmethod
    def _links(text: str) -> list[str]:
        """提取 markdown 链接，先剥掉代码块与行内代码。

        剥代码是必须的：文档里会写 `self.tools[name](**args)` 这种行内代码，
        朴素正则会把它误判成链接（`name](**args)` 长得就像链接）。
        """
        import re
        text = re.sub(r"```.*?```", "", text, flags=re.S)
        text = re.sub(r"`[^`\n]*`", "", text)
        return re.findall(r"\]\(([^)\s]+)\)", text)

    def test_top_level_docs_exist(self):
        for name in self.TOP_DOCS:
            self.assertTrue((ROOT / name).exists(), f"缺少顶层文档 {name}")

    def test_no_broken_links_in_docs(self):
        for name in self.TOP_DOCS:
            p = ROOT / name
            if not p.exists():
                continue
            broken = [
                t for t in self._links(p.read_text(encoding="utf-8"))
                if not t.startswith(("http://", "https://", "#", "mailto:"))
                and not (ROOT / t.split("#")[0]).exists()
            ]
            self.assertEqual(broken, [], f"{name} 里有死链：{broken}")

    def test_documented_py_m_commands_exist(self):
        """README 里写的 `py -m stages.xxx` 必须真的能解析到模块。"""
        import re
        for stage in sorted((ROOT / "stages").glob("stage*")):
            readme = stage / "README.md"
            if not readme.exists():
                continue
            mods = set(re.findall(r"py -m ((?:stages|scripts|tests)[\w.]*)",
                                  readme.read_text(encoding="utf-8")))
            for mod in mods:
                target = ROOT.joinpath(*mod.split(".")).with_suffix(".py")
                self.assertTrue(target.exists(),
                                f"{stage.name}/README.md 里的 `py -m {mod}` 无效")

    def test_notebooks_are_valid_nbformat(self):
        """已生成的 .ipynb 必须是合法 nbformat v4（source 得是行列表）。"""
        from notebooks.notebook_lib import validate_ipynb

        nbs = sorted((ROOT / "notebooks").glob("*.ipynb"))
        self.assertGreater(len(nbs), 0,
                           "没有生成任何 Notebook（跑 py scripts\\build_notebooks.py）")
        for p in nbs:
            good, msg = validate_ipynb(p)
            self.assertTrue(good, f"{p.name} 不合法：{msg}")

    def test_notebook_checkpoint_module_resolution(self):
        """回归测试：自检单元必须能按章号找到真实的 stage 包。

        曾经 `checkpoint()` 把模块名拼成 `stages.stage01`，
        而真实目录是 `stages.stage01_agent_loop` —— 结果 13 个自检单元
        全部 `ModuleNotFoundError`。这条测试守住那个修复。
        """
        from notebooks.nb_blocks import resolve_stage_module

        for chapter in [f"{i:02d}" for i in range(1, 14)]:
            mod = resolve_stage_module(chapter)
            self.assertNotEqual(mod, f"stages.stage{chapter}",
                                f"第 {chapter} 章没能解析到真实 stage 包")
            self.assertTrue((ROOT.joinpath(*mod.split(".")) / "demo.py").exists(),
                            f"{chapter} 解析出的模块不存在：{mod}")

    def test_notebook_cells_were_actually_executed(self):
        """Notebook 里的代码单元必须都执行过（否则输出是空的/手写的）。"""
        import json

        for p in sorted((ROOT / "notebooks").glob("*.ipynb")):
            data = json.loads(p.read_text(encoding="utf-8"))
            code_cells = [c for c in data["cells"] if c["cell_type"] == "code"]
            self.assertGreater(len(code_cells), 0, f"{p.name} 没有代码单元")
            unexecuted = [i for i, c in enumerate(code_cells)
                          if c.get("execution_count") is None]
            self.assertEqual(unexecuted, [],
                             f"{p.name} 有未执行的代码单元：{unexecuted}")


# ===========================================================================
# explain() —— 读者查 API 的工具（"看不懂怎么办"的标准答案）
# ===========================================================================
class TestExplain(unittest.TestCase):
    """守住 explain() 的契约：框架里每个公开名字都必须能查、且不抛异常。

    为什么值得为它单独写测试？
        因为它是读者**唯一的自助查询入口**。如果 explain(某个名字) 报错，
        读者就卡住了 —— 而卡住的地方恰恰是"我看不懂"，最不该再抛异常。
    """

    def _names(self) -> list[str]:
        import sys as _sys
        if str(ROOT) not in _sys.path:
            _sys.path.insert(0, str(ROOT))
        from notebooks.nb_explain import LAYERS, MOCK_MODELS
        return ([n for _, _, ns in LAYERS for n in ns]
                + [n for n, _ in MOCK_MODELS])

    def test_every_public_name_is_explainable(self):
        import io
        from contextlib import redirect_stdout
        from notebooks.nb_explain import explain

        for name in self._names():
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    explain(name)
            except Exception as exc:
                self.fail(f"explain({name!r}) 抛异常：{type(exc).__name__}: {exc}")
            out = buf.getvalue()
            self.assertFalse(out.startswith("❌"), f"explain({name!r}) 解析不到对象")
            self.assertGreater(len(out), 80, f"explain({name!r}) 信息量不足")

    def test_explain_without_args_prints_index(self):
        import io
        from contextlib import redirect_stdout
        from notebooks.nb_explain import explain

        buf = io.StringIO()
        with redirect_stdout(buf):
            explain()
        out = buf.getvalue()
        self.assertIn("公开 API 索引", out)
        self.assertIn("explain(run_once)", out)

    def test_explain_handles_instances(self):
        """传实例时要显示当前值 —— 调试时最有用。"""
        import io
        from contextlib import redirect_stdout
        from core import run_once as _run_once
        from notebooks.nb_explain import explain

        r = _run_once("计算 6*7", verbose=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            explain(r)
        out = buf.getvalue()
        self.assertIn("实例", out)
        self.assertIn("当前 =", out)
        self.assertIn("42", out)          # 真实答案应该显示出来

    def test_param_docs_cover_core_agent_params(self):
        """Agent/run_once 的关键参数必须有人话解释。

        尤其是 llm=None —— 字面上完全看不出"不传就用离线 Mock 模型"。
        """
        import sys as _sys
        if str(ROOT) not in _sys.path:
            _sys.path.insert(0, str(ROOT))
        from notebooks.nb_explain import PARAM_DOCS

        for p in ("llm", "tools", "max_steps", "verbose", "approval_hook"):
            self.assertIn(p, PARAM_DOCS, f"参数 {p} 缺少人话解释")
        self.assertIn("Mock", PARAM_DOCS["llm"])

    def test_setup_cell_installs_explain(self):
        """每个 Notebook 的引导单元都要装好 explain()，否则读者用它会 NameError。"""
        import sys as _sys
        if str(ROOT) not in _sys.path:
            _sys.path.insert(0, str(ROOT))
        from notebooks.nb_blocks import setup_cell
        from notebooks.notebook_lib import Notebook

        nb = Notebook("t")
        setup_cell(nb)
        code = "".join(
            line for c in nb.cells if c["cell_type"] == "code"
            for line in c["source"]
        )
        self.assertIn("from notebooks.nb_explain import explain", code)


# ===========================================================================
# 代码单元的自包含性 —— 读者 "复制下来全是 NameError" 的那个问题
# ===========================================================================
class TestCellSelfContained(unittest.TestCase):
    """守住"每个代码单元都能单独运行"这条硬规矩。

    背景（读者原话）：
        "代码看起来完整，实际复制下来全是 NameError。"
        "TOOLS 不知道在哪、FINAL_RE 是什么、_extract_tool_call 谁实现的。"

    实测：改造前 13 章里 126 个代码单元有 78 个（62%）不能单独跑。

    这里做**两层**检查：
        ① 静态：notebooks.nb_lint 分析符号表，找出引用了但本单元没定义的名字
        ② 动态：把每个单元放进独立子进程真的跑一遍（最硬的证据）
    """

    # 已经完成"自包含"改造的章节。没改完的章先不强制，
    # 但每改完一章就往这里加一个 —— 逐步收紧，而不是留一堆豁免。
    # 全部 14 个 Notebook 都已按 TEACHING_CONTRACT.md 重写，
    # 所以这里不再有任何豁免 —— 每个代码单元都必须能单独运行。
    SELF_CONTAINED_NOTEBOOKS = [
        "00_setup.ipynb",
        "01_agent_loop.ipynb",
        "02_tools.ipynb",
        "03_react_prompt.ipynb",
        "04_planning.ipynb",
        "05_memory.ipynb",
        "06_rag.ipynb",
        "07_reflection.ipynb",
        "08_multi_agent.ipynb",
        "09_workflow.ipynb",
        "10_evaluation.ipynb",
        "11_guardrails.ipynb",
        "12_cost_latency.ipynb",
        "13_production.ipynb",
    ]

    def test_lint_no_undeclared_deps(self):
        """静态检查：已改造的章节不允许有未声明的外部依赖。"""
        import sys as _sys
        if str(ROOT) not in _sys.path:
            _sys.path.insert(0, str(ROOT))
        from notebooks.nb_lint import lint_notebook

        for name in self.SELF_CONTAINED_NOTEBOOKS:
            p = ROOT / "notebooks" / name
            if not p.exists():
                continue
            issues = lint_notebook(p)
            detail = "; ".join(f"单元[{i}]缺{n}" for i, n, _ in issues)
            self.assertEqual(issues, [],
                             f"{name} 有未声明依赖（读者单独跑会 NameError）：{detail}")

    def test_each_cell_runs_standalone(self):
        """动态检查：把每个代码单元放进**独立子进程**跑，必须退出码为 0。

        这是最硬的证据 —— 静态分析可能漏，真跑一遍不会。
        子进程隔离保证单元之间不可能互相借变量。
        """
        import json
        import os
        import subprocess
        import sys as _sys

        for name in self.SELF_CONTAINED_NOTEBOOKS:
            p = ROOT / "notebooks" / name
            if not p.exists():
                continue
            data = json.loads(p.read_text(encoding="utf-8"))
            cells = [c for c in data["cells"] if c["cell_type"] == "code"]

            failures = []
            for i, cell in enumerate(cells):
                src = "".join(cell["source"])
                # 单独进程跑：cwd 设为项目根，让 core 能被 import。
                #
                # ★ PYTHONIOENCODING / PYTHONUTF8：模拟 Jupyter 内核的环境。
                #   真实 Jupyter 的 stdout 是 UTF-8，所以打印 emoji 没问题；
                #   而 Windows 下 `py -c` 默认是 GBK，打印 ✅ 会抛 UnicodeEncodeError。
                #   那是**控制台编码**问题，不是"单元不自包含"，
                #   所以这里必须把编码对齐到 Jupyter 的真实情况再比。
                env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
                proc = subprocess.run(
                    [_sys.executable, "-c", src],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=60, cwd=str(ROOT), env=env,
                )
                if proc.returncode != 0:
                    tail = (proc.stderr or "").strip().splitlines()
                    failures.append(f"单元[{i}]: {tail[-1] if tail else '未知错误'}")

            self.assertEqual(failures, [],
                             f"{name} 有单元不能单独运行：\n  " + "\n  ".join(failures))

    def test_explain_resolves_builtins_and_stdlib(self):
        """读者会问的"内置/标准库函数"也必须查得到。

        回归背景：读者敲 `explain(compile)` 想看那个 compile 是什么，
        而 explain() 当时只在 core 里找名字，直接回"找不到" ——
        它恰恰是读者最需要帮助的时候。
        """
        import io
        from contextlib import redirect_stdout
        from notebooks.nb_explain import explain

        for name in ("compile", "len", "eval", "open", "isinstance",
                     "re.compile", "json.loads", "ast.parse"):
            buf = io.StringIO()
            with redirect_stdout(buf):
                explain(name)
            out = buf.getvalue()
            self.assertFalse(out.startswith("❌"), f"explain({name!r}) 解析不到")
            self.assertGreater(len(out), 80, f"explain({name!r}) 信息量不足")

    def test_explain_warns_about_compile_name_collision(self):
        """`compile` 与 `re.compile` 是两个不同的东西 —— 必须明确点出来。

        这正是读者实际卡住的点：代码里是 re.compile，他查的是内置 compile。
        """
        import io
        from contextlib import redirect_stdout
        from notebooks.nb_explain import explain

        buf = io.StringIO()
        with redirect_stdout(buf):
            explain("compile")
        out = buf.getvalue()
        self.assertIn("re.compile", out, "内置 compile 的说明里必须提到 re.compile")
        self.assertIn("重名", out)

        buf = io.StringIO()
        with redirect_stdout(buf):
            explain("re.compile")
        out2 = buf.getvalue()
        self.assertIn("正则", out2)
        # 正则参数要有人话解释
        self.assertIn("re.S", out2, "必须解释 re.S 标志的作用")

    def test_explain_warns_eval_is_forbidden(self):
        """eval/open/input 在 Agent 开发里都是禁忌或陷阱，解释里必须提醒。"""
        import io
        from contextlib import redirect_stdout
        from notebooks.nb_explain import explain

        for name, must_contain in (("eval", "禁忌"), ("open", "沙箱"), ("input", "别用")):
            buf = io.StringIO()
            with redirect_stdout(buf):
                explain(name)
            self.assertIn(must_contain, buf.getvalue(),
                          f"explain({name!r}) 缺少关键提醒 {must_contain!r}")


if __name__ == "__main__":
    unittest.main(verbosity=2)