"""nb_explain —— 随时查"这东西是什么、参数要什么、返回什么"。

------------------------------------------------------------
为什么需要它？
    课程用了一套自造的 `core/` 框架。读者（尤其是工程经验刚起步的）
    看到代码里的 `run_once(...)`、`AgentResult`、`count_words(text)`
    时会有三个问题：

        1. 这东西是什么？从哪来的？
        2. 参数要传什么？`llm=None` 是什么意思？
        3. 返回什么？我怎么知道结果里有哪些字段能取？

    源码注释回答不了这些 —— 注释是写给"读源码的人"的，
    而读者需要的是**接口说明**。所以这里做一个能随时查的工具。

用法（在任意 Notebook 里，先跑过引导单元）：
    from notebooks.nb_explain import explain
    explain()                  # 不给参数 → 列出框架全部公开名字（按层分组）
    explain(run_once)          # 查一个函数
    explain(AgentResult)       # 查一个数据类（会展开它的字段）
    explain(count_words)       # 查一个函数，含"能跑的例子"
    explain("count_words")     # 传字符串也行（会去 core 里找）
------------------------------------------------------------
"""

from __future__ import annotations

import inspect
import typing

# ===========================================================================
# 一、框架参数的"人话"解释
# ===========================================================================
# ★ 为什么需要这张表？
#   因为 `llm: LLM | None = None` 这种签名**字面上完全看不出**
#   "不传就用离线 Mock 模型"。类型注解只说得出"可以不传"，
#   说不出"不传会发生什么" —— 而后者才是读者真正要的信息。

PARAM_DOCS: dict[str, str] = {
    # ---- Agent / run_once 相关 ----
    "llm": "不传就用离线 Mock 模型（不需要 API Key）；想接真模型传 core.real_llm.from_env() 的返回值",
    "tools": "不传就用内置工具集（calc / count_words / lookup_order / 读写文件等），"
             "由 build_default_registry() 生成",
    "prompt": "不传就用 PromptBuilder(style='react')，也就是标准的 ReAct 提示词",
    "max_steps": "★ 循环圈数上限。到顶就停，stop_reason='max_steps'。"
                 "这是防止模型卡住时无限烧钱的**唯一**保险，别省",
    "max_parse_retries": "模型输出连续解析失败几次就放弃（默认 2，即最多重试 2 次后停机）",
    "max_llm_retries": "模型调用（网络/限流）失败重试几次（默认 2）",
    "repeat_limit": "同一个工具调用指纹重复出现几次后，往上下文里插一句提醒",
    "verbose": "True 会把每一圈的事件（llm_output / tool_result / run_end…）打印出来，"
               "调试时开着，测试时关掉",
    "observer": "事件回调 observer(event: str, payload: dict)，用来接日志/监控/UI。"
                "它抛异常不会影响 Agent 运行",
    "approval_hook": "高危工具的审批回调 approval_hook(call) -> bool。返回 False 表示拒绝执行",
    "workspace": "工具的沙箱根目录。文件类工具只能访问它内部（路径穿越会被拒绝）",
    "context_char_limit": "上下文硬上限（字符）。超了就折叠最老的工具结果，防止撑爆窗口",
    "question": "要问 Agent 的问题（自然语言字符串，比如 '计算 (12+8)*3/4'）",
    # ---- 工具相关 ----
    "expr": "要计算的数学表达式，**字符串形式**，例如 '(12+8)*3/4' 或 'sqrt(16)+1'",
    "text": "要处理的内容，**就是一段普通字符串**（不要带引号、不需要任何格式化）",
    "order_id": "订单号字符串，形如 'A1001'（大小写都行，内部会转大写）",
    "path": "**相对**工作目录的路径，例如 'notes.md'。用绝对路径或 ../ 逃逸会被拒绝",
    "max_chars": "最多读取/截断到多少字符（整数）",
    "name": "工具名，必须是合法标识符（字母/数字/下划线，且不以数字开头）",
    "description": "★ **写给模型看的**说明书，不是写给人看的注释。"
                   "要说清：功能 + 参数格式 + **什么时候该用我**",
    "parameters": "JSON Schema 字典，形如 {'type':'object','properties':{...},'required':[...]}",
    "func": "真正执行的 Python 函数（注册进注册表后由它干实事）",
    "tags": "工具标签列表，用于 ToolRegistry.subset(['math']) 按场景裁剪工具集",
    "requires_approval": "True 表示这是高危工具（如写文件），执行前必须人工审批",
    "max_result_chars": "工具返回值截断长度。防止一次调用返回 10MB 日志把上下文撑爆",
    "args": "参数字典，形如 {'expr': '1+1'}。Agent 从模型输出里解析出来就是这个",
    "ok": "True=成功 / False=失败。工具失败不会抛异常，而是变成 ok=False 的结果",
    "content": "结果正文（成功时给模型看的内容）",
    "error": "失败原因（**写给模型看的**，要包含「哪里错了 + 正确用法」）",
    # ---- 消息相关 ----
    "role": "只能是 'system' / 'user' / 'assistant' / 'tool' 四个之一",
    "tool_calls": "list[ToolCall]，模型这一轮想调用的工具（可能为空）",
    "tool_call_id": "工具结果对应的调用 id（把结果和请求配对，OpenAI 协议要求）",
    "metadata": "附加信息，比如 {'ok': True, 'elapsed_ms': 1.2}",
    "id": "调用标识符。不传会自动按 (工具名, 参数) 算一个稳定指纹",
    "known_tools": "已知工具名列表。**只用于参考，不会拦截**幻觉工具 —— "
                   "作者刻意留到 Agent 循环里去生成「工具不存在」的观察结果",
    "value": "要被校验的值",
    "schema": "JSON Schema 子集字典",
    "path_": "错误信息里的路径前缀（默认 '$'，用于定位嵌套结构里出错的位置）",
    # ---- 提示词相关 ----
    "style": "'react'（纯文本协议） / 'function_calling'（原生函数调用） / 'plain'（不用工具）",
    "persona": "追加的身份描述，例如 '你是电商客服'",
    "rules": "业务规则列表，每条一个字符串。会和身份一起注入系统提示词",
    "extra_context": "动态上下文（RAG 片段、长期记忆、当前时间…）",
    "max_tools": "工具数超过这个值时会附一句提醒（工具太多模型容易选错）",
    # ---- 教学输出相关 ----
    "title": "标题文字",
    "subtitle": "副标题（可省）",
    "index": "小节序号，如 '①'（可省）",
    "key": "左边的名字",
    "indent": "缩进空格数",
    "lang": "代码块的语言标记（可省）",
    "passed": "True / False",
    "detail": "补充说明，会跟在后面用括号显示（可省）",
    "force_ascii": "True 强制用 [想]/[做]/[看] 这类 ASCII 标记，不打印 emoji",
    # ---- 正则（re.compile / re.search 等）----
    "pattern": "**正则表达式字符串**，例如 r'<tool_call>\\s*(\\{.*?\\})\\s*</tool_call>'。"
               "注意它是**正则语法**，不是普通字符串：`.` `*` `?` `(` `)` 都有特殊含义",
    "flags": "可选标志位，默认 0。★ 最常用的是 `re.S`：让 `.` 也能匹配换行符 —— "
             "不加它，跨行的模型输出就匹配不到（Agent 里几乎必加）",
    "string": "要在里面查找的字符串",
    "source": "要编译的源码字符串（不是文件名）",
    "filename": "编译出错时用来报错的文件名（随便给个标识即可）",
    "mode": "'eval'（单个表达式）/ 'exec'（语句块）/ 'single'",
    "obj": "任意对象：函数、类、实例、模块，或名字字符串",
    # ---- 结果对象（AgentResult / StepRecord）的字段 ----
    "answer": "模型给出的最终答案（`Final Answer:` 后面那段）",
    "steps": "循环每一圈一条记录，见 explain(StepRecord)",
    "stop_reason": "'final_answer' 正常结束 / 'max_steps' 步数用完 / "
                   "'loop_detected' 重复动作 / 'parse_failed' 解析连续失败 / 'error' 模型调用失败",
    "elapsed_ms": "耗时（毫秒）",
    "llm_calls": "一共调了几次模型（成本相关）",
    "total_tokens": "累计消耗 token（成本相关）",
    "index": "第几圈（从 1 开始，不是 0）",
    "thought": "模型这一步的思考（Thought 那一段）",
    "observations": "工具返回的内容，和 tool_calls 一一对应",
    "parse_errors": "解析模型输出时遇到的问题；正常情况为空列表",
    "llm_ms": "这一步调用模型花了多少毫秒",
    "tool_ms": "这一步执行工具花了多少毫秒",
    "tokens": "这一步消耗的 token",
    "note": "这一圈的特殊事件：重试了几次、触发了重复动作提醒、上下文被折叠等",
    "tool_note": "工具层的额外说明：慢调用告警、审批被拒等",
}

# 有些参数名在框架里出现多次但含义不同，这里给"按函数名"的精确覆盖
PARAM_DOCS_BY_FUNC: dict[tuple[str, str], str] = {
    ("validate_schema", "path"): "错误信息里的路径前缀（默认 '$'，嵌套结构会拼成 $.order_id）",
    ("explain", "obj"): "任意对象：函数、类、实例、模块，或 core 里的名字（字符串）",
    ("build_default_registry", "workspace"): "工具沙箱的根目录（文件类工具只能访问它内部）",
    ("get_llm", "prefer_real"): "True 会尝试用环境变量里的 API Key 构造真实模型；"
                               "没有 Key 就自动回退 Mock 并说明原因",
    ("from_env", "model"): "覆盖默认模型名（如 'deepseek-chat'）",
    ("from_env", "base_url"): "覆盖默认接口地址（如 Ollama 的 http://localhost:11434/v1）",
    ("from_env", "api_key"): "直接传 Key（不传则从环境变量读）",
}


# 有些参数名在**不同类里含义不同**，必须按「类名 + 字段名」精确覆盖。
# 否则 explain(Message) 会显示 ToolSpec 的 name 说明 —— 看起来像对的，其实是错的。
FIELD_DOCS_BY_CLASS: dict[tuple[str, str], str] = {
    # ---- Message ----
    ("Message", "role"): "只能是 'system' / 'user' / 'assistant' / 'tool' 四个之一",
    ("Message", "content"): "消息正文（模型看到的文本就是这些拼起来的）",
    ("Message", "name"): "工具消息里填工具名；assistant 消息里可填模型名",
    ("Message", "tool_calls"): "list[ToolCall] —— 这条 assistant 消息想调用的工具（通常为空）",
    ("Message", "tool_call_id"): "工具结果对应哪次调用（把结果和请求配对，OpenAI 协议要求）",
    ("Message", "metadata"): "附加信息，例如 tool 消息里的 {'ok': True, 'elapsed_ms': 1.2}",
    # ---- ToolCall ----
    ("ToolCall", "name"): "工具名（要能被 ToolRegistry 找到）",
    ("ToolCall", "args"): "参数字典，形如 {'expr': '1+1'}。Agent 从模型输出里解析出来就是这个",
    ("ToolCall", "id"): "调用标识符。不传会自动按 (工具名, 参数) 算一个稳定指纹",
    # ---- ToolResult ----
    ("ToolResult", "name"): "工具名",
    ("ToolResult", "ok"): "True=成功 / False=失败。失败不会抛异常，而是变成 ok=False 的结果",
    ("ToolResult", "content"): "结果正文（成功时给模型看的内容）",
    ("ToolResult", "error"): "失败原因（**写给模型看的**，要包含「哪里错了 + 正确用法」）",
    ("ToolResult", "elapsed_ms"): "工具执行耗时（毫秒）；超过 1 秒会记一条「偏慢」告警",
    ("ToolResult", "meta"): "附加信息字典，例如 {'traceback_hint': '...'}",
    # ---- ToolSpec ----
    ("ToolSpec", "name"): "工具名，必须是合法标识符（字母/数字/下划线，且不以数字开头）",
    ("ToolSpec", "description"): "★ **写给模型看的**说明书，不是注释。要说清：功能 + 参数格式 + **什么时候该用我**",
    ("ToolSpec", "parameters"): "JSON Schema 字典：{'type':'object','properties':{...},'required':[...]}",
    ("ToolSpec", "func"): "真正执行的 Python 函数（注册进注册表后由它干实事）",
    ("ToolSpec", "tags"): "标签列表，用于 ToolRegistry.subset(['math']) 按场景裁剪工具集",
    ("ToolSpec", "requires_approval"): "True 表示高危工具（如写文件），执行前必须人工审批",
    ("ToolSpec", "max_result_chars"): "返回值截断长度。防止一次调用返回 10MB 日志把上下文撑爆",
    # ---- StepRecord 里和 AgentResult 同名字段含义不同 ----
    ("StepRecord", "answer"): "只有最后一圈可能有值；非空说明这一圈给出了最终答案",
    ("StepRecord", "tool_calls"): "这一步调用了哪些工具（可能一次多个）",
    ("StepRecord", "index"): "第几圈（从 1 开始，不是 0）",
    # ---- ParsedOutput ----
    ("ParsedOutput", "thought"): "从模型输出里提取到的 Thought（可能为空）",
    ("ParsedOutput", "answer"): "从模型输出里提取到的 Final Answer（没有则为空字符串）",
    ("ParsedOutput", "tool_calls"): "解析出的工具调用列表（可能为空）",
    ("ParsedOutput", "errors"): "list[str] —— 解析遇到的问题。为空 = 一切正常",
    ("ParsedOutput", "raw"): "模型的原始输出（排查解析问题时看这个）",
    # ---- LLMResponse ----
    ("LLMResponse", "text"): "★ 模型回复的正文 —— 后面所有解析都基于它",
    ("LLMResponse", "model"): "模型名（complete() 会自动填）",
    ("LLMResponse", "prompt_tokens"): "输入 token 数",
    ("LLMResponse", "completion_tokens"): "输出 token 数",
    ("LLMResponse", "latency_ms"): "这次调用耗时（complete() 自动填）",
    ("LLMResponse", "raw"): "厂商返回的原始响应（调试用）",
    # ---- PromptBuilder ----
    ("PromptBuilder", "style"): "'react'（纯文本协议） / 'function_calling'（原生函数调用） / 'plain'（不用工具）",
    ("PromptBuilder", "persona"): "追加的身份描述，例如「你是电商客服」",
    ("PromptBuilder", "rules"): "业务规则列表，每条一个字符串，会和身份一起注入系统提示词",
    ("PromptBuilder", "extra_context"): "动态上下文（RAG 片段、长期记忆、当前时间…）",
    ("PromptBuilder", "max_tools"): "工具数超过这个值时会附一句提醒（工具太多模型容易选错）",
}


def _field_doc(cls_name: str, field_name: str) -> str:
    """查字段说明：先按「类+字段」精确匹配，再退回通用参数表。"""
    return FIELD_DOCS_BY_CLASS.get((cls_name, field_name)) or PARAM_DOCS.get(field_name, "")


# ===========================================================================
# 一·B、内置函数 / 标准库的人话解释
# ===========================================================================
# ★ 为什么要专门管这类名字？
#   读者的困惑有一大半来自**重名**：
#       compile(...)        ← Python 内置：把源码字符串编译成代码对象
#       re.compile(...)     ← re 模块的函数：把正则字符串编译成正则对象
#   两个完全不同的东西，只因为都叫 compile，就足以让人卡住。
#   所以这里既解释内置的 compile，也解释 re.compile，并**点明它们不是一回事**。

BUILTIN_NOTES: dict[str, str] = {
    "compile": (
        "⚠️ 注意重名！这个是 **Python 内置** 的 compile："
        "把一段**源码字符串**编译成可执行的代码对象。\n"
        "       你在这门课里看到的多半是 `re.compile(...)` —— 那是 **re 模块**的函数，"
        "把**正则字符串**编译成正则对象，和这个内置函数毫无关系。\n"
        "       看代码时先问一句「点号左边是谁」：`re.compile` 是 re 模块里的 compile。"
    ),
    "len": "返回长度（字符串字符数 / 列表元素个数 / 字典键数）",
    "range": "生成整数序列",
    "print": "打印到 stdout。**Agent 循环里慎用**：会混进模型的输出流，干扰解析",
    "open": "打开文件。★ Agent 里不要直接用 —— 参数可能来自模型，必须走沙箱工具",
    "eval": (
        "⚠️ **Agent 开发里的头号禁忌**：把字符串当代码执行。\n"
        "       模型输出是不可信输入，`eval(\"__import__('os').system(...)\")` 会真的执行。\n"
        "       课程里算表达式一律用 `ast` 白名单（见第 02 章）。"
    ),
    "exec": "同 eval，执行一段语句。在 Agent 里同样是禁忌",
    "isinstance": "判断对象是不是某个类型。★ 注意 `isinstance(True, int)` 是 True —— "
                  "bool 是 int 的子类，这是参数校验的经典陷阱（第 02 章）",
    "sorted": "返回排序后的新列表（不改原列表）",
    "enumerate": "遍历时同时拿到下标和元素",
    "zip": "把多个序列按位置配对",
    "getattr": "按名字取属性：getattr(obj, 'answer') 等价于 obj.answer",
    "hasattr": "判断对象有没有某个属性",
    "setattr": "按名字设属性",
    "repr": "返回对象的官方字符串形式（调试用，dataclass 会自动生成好读的）",
    "str": "转成字符串",
    "int": "转成整数",
    "float": "转成小数",
    "bool": "转成 True/False",
    "list": "转成列表",
    "dict": "转成字典",
    "tuple": "转成元组",
    "sum": "求和",
    "min": "最小值",
    "max": "最大值",
    "abs": "绝对值",
    "round": "四舍五入",
    "any": "有没有任意一个为真",
    "all": "是不是全部为真",
    "type": "返回对象的类型",
    "id": "返回对象的内存地址标识",
    "dir": "列出对象的所有属性名（不知道有啥可看时用它）",
    "vars": "返回对象的 __dict__",
    "input": "★ **Notebook / 自动化脚本里别用**：会阻塞等待人工输入。"
             "课程里需要「人工介入」的地方都用确定性剧本模拟",
}

# 标准库函数的补充说明（按「模块.函数」）
STDLIB_NOTES: dict[str, str] = {
    "re.compile": "把正则字符串编译成正则对象（re.Pattern），之后复用它的 .search() / .findall()。"
                  "★ 和第 1 个参数是**正则语法**，不是普通字符串",
    "re.search": "在字符串里找第一个匹配，返回 Match 或 None。**返回 None 不报错** —— 必须判空",
    "re.findall": "找出所有匹配，返回字符串列表",
    "re.sub": "替换匹配到的内容",
    "re.match": "只从字符串**开头**匹配（search 是任意位置）",
    "json.loads": "JSON 字符串 → Python 对象（dict/list）。★ 格式不合法会抛 JSONDecodeError",
    "json.dumps": "Python 对象 → JSON 字符串。ensure_ascii=False 才会保留中文原文",
    "ast.parse": "把源码字符串解析成语法树（AST）。**不执行代码** —— 这正是它比 eval 安全的原因",
    "ast.literal_eval": "只解析字面量（数字/字符串/列表/字典），不执行任何调用",
    "inspect.signature": "拿到函数的签名（参数名、默认值、类型注解）—— 「函数即工具」靠它",
    "inspect.getdoc": "拿到函数的 docstring",
    "math.sqrt": "平方根",
    "dataclasses.fields": "列出一个 dataclass 的所有字段",
    "dataclasses.is_dataclass": "判断是不是 dataclass",
}


def _builtin_note(full_name: str) -> str:
    """查内置/标准库说明。full_name 形如 'compile' 或 're.compile'。"""
    if full_name in STDLIB_NOTES:
        return STDLIB_NOTES[full_name]
    short = full_name.rsplit(".", 1)[-1]
    if full_name in BUILTIN_NOTES:
        return BUILTIN_NOTES[full_name]
    return BUILTIN_NOTES.get(short, "")


# ===========================================================================
# 二、可以直接抄的例子
# ===========================================================================
# ★ 为什么把例子写死，而不是自动生成？
#   自动生成只能拼出 `run_once(question=...)` 这种**形状正确但毫无信息量**的骨架。
#   读者要的是"真实可跑的一行 + 它大概会输出什么"，这必须人写。

EXAMPLES: dict[str, str] = {
    # ---- Agent ----
    "run_once": '''r = run_once("计算 (12+8)*3/4")
print(r.answer)          # '根据 calc 的结果：(12+8)*3/4 = 15'
print(r.stop_reason)     # 'final_answer'
print(len(r.steps))      # 2   —— 循环跑了两圈''',
    "quick_agent": '''a = quick_agent(verbose=False)
r = a.run("计算 6*7")
print(r.answer)          # '根据 calc 的结果：6*7 = 42'
# 常用调试：看完整推理轨迹
print(r.trace())''',
    "Agent": '''from core.mock_llm import ScriptedLLM

agent = Agent(
    llm=ScriptedLLM([                       # 按剧本返回的假模型
        'Thought: 算一下。\\n<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>',
        'Thought: 好了。\\nFinal Answer: 1+1 = 2',
    ]),
    max_steps=4,
    verbose=False,                          # 测试时关掉打印
)
result = agent.run("计算 1+1")
print(result.answer)                        # '1+1 = 2'
print(result.stop_reason)                   # 'final_answer'（其他可能见下）''',
    "AgentResult": '''# 这是 run() 的返回值。7 个字段，最常用的是前三个：
result.answer          # str   —— 最终答案（模型给的 Final Answer）
result.steps           # list  —— 每一圈一条 StepRecord，见 explain(StepRecord)
result.stop_reason     # str   —— 为什么停的

# stop_reason 的全部取值：
#   'final_answer'   正常结束（模型给出答案）
#   'max_steps'      步数用完（保护性停机）
#   'loop_detected'  重复动作太多（保护性停机）
#   'parse_failed'   模型输出连续解析不了（保护性停机）
#   'error'          模型调用连续失败（真故障）
result.error           # str   —— stop_reason 不是 final_answer 时，这里说明原因
result.elapsed_ms      # float —— 总耗时（毫秒）
result.llm_calls       # int   —— 调了几次模型（成本相关）
result.total_tokens    # int   —— 累计 token（成本相关）

# 最有用的一招：把整条轨迹打印出来
print(result.trace())''',
    "StepRecord": '''# result.steps[i] 是循环第 i+1 圈（注意 index 从 1 开始）
s = result.steps[0]
s.index          # 1        —— 第几圈
s.thought        # str      —— 模型这一步的思考
s.tool_calls     # list     —— 这一步调用了哪些工具（可多个）
s.observations   # list[str]—— 工具返回的内容（和 tool_calls 一一对应）
s.answer         # str      —— 只有最后一圈可能有；非空说明这圈给了最终答案
s.parse_errors   # list[str]—— 解析模型输出时遇到的问题（正常情况为空）
s.llm_ms         # float    —— 这一步调模型花了多久
s.tool_ms        # float    —— 这一步跑工具花了多久
s.tokens         # int      —— 这一步消耗的 token
s.note           # str      —— 特殊事件：重试了几次、被护栏拦了等
s.tool_note      # str      —— 工具层的额外说明（慢调用告警、审批拦截）

# 一眼看懂一圈发生了什么
print(result.steps[0].summary())''',
    # ---- 工具 ----
    "build_default_registry": '''reg = build_default_registry(ROOT)     # ROOT 是项目根目录
print(reg.names())
# ['calc', 'count_words', 'list_dir', 'lookup_order', 'read_file', 'write_note']
reg.describe()                        # 打印"模型看到的工具说明书"''',
    "count_words": '''# text 就是一段普通字符串，不需要任何格式化
count_words("你好 world")
# -> {'总字符数': 8, '中文字数': 2, '英文单词数': 1, '行数': 1}

# 通过注册表调用（有参数校验，失败也不抛异常）
r = build_default_registry(ROOT).execute("count_words", {"text": "你好 world"})
print(r.ok, r.content)''',
    "lookup_order": '''lookup_order("A1001")
# -> {'order_id': 'A1001', 'status': '已发货',
#     'carrier': '顺丰', 'tracking': 'SF1234567890', 'eta': '2025-01-05'}

lookup_order("Z9999")     # 会抛 ValueError —— 但在 Agent 里会被转成可读的 observation''',
    "ToolRegistry": '''reg = ToolRegistry()

# 写法一：手写规格（要自己写 JSON Schema）
reg.register(ToolSpec(
    name="add",
    description="把两个数相加",
    parameters={"type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "required": ["a", "b"],
                "additionalProperties": False},
    func=lambda a, b: a + b,
))

# 写法二：函数即工具（自动从签名生成 schema）
def multiply(x: int, y: int) -> int:
    """把两个整数相乘。"""
    return x * y
reg.from_function(multiply)

# 执行：**任何情况下都不抛异常**，失败会变成 ok=False
r = reg.execute("add", {"a": 1, "b": 2})
print(r.ok, r.content)          # True  3
r = reg.execute("add", {"a": 1})            # 少参数
print(r.ok, r.error)            # False 参数校验失败：... 正确用法：add(...)''',
    "ToolSpec": '''ToolSpec(
    name="calc",                       # 工具名（合法标识符）
    description="计算数学表达式…",       # ★ 写给模型看的，不是注释
    parameters={                       # JSON Schema
        "type": "object",
        "properties": {"expr": {"type": "string", "description": "表达式"}},
        "required": ["expr"],          # 必填清单
        "additionalProperties": False,  # ★ 拒绝一切未定义参数（防幻觉参数）
    },
    func=my_calc_function,             # 真正执行的函数
    tags=["math"],                     # 用于 subset() 裁剪
    requires_approval=False,           # 高危工具设 True
    max_result_chars=4000,             # 结果截断
)''',
    "ToolResult": '''r = reg.execute("calc", {"expr": "6*7"})
r.ok            # True        —— 成功还是失败
r.content       # '6*7 = 42'   —— 结果正文
r.error         # ''           —— 失败原因
r.elapsed_ms    # 0.05         —— 耗时
r.to_observation()  # 转成给模型看的文本（带 <result> 包裹）''',
    "validate_schema": '''validate_schema({"expr": "1+1"},
                {"type": "object",
                 "properties": {"expr": {"type": "string"}},
                 "required": ["expr"],
                 "additionalProperties": False})
# -> []            空列表 = 通过

validate_schema({"exp": "1+1"}, SCHEMA)
# -> ["$: 缺少必填参数 'expr'", "$: 出现未定义参数 ['exp']，允许的只有 ['expr']"]
#     ★ 一次给出全部错误（省模型调用次数），而不是遇到第一个就返回''',
    # ---- 消息 ----
    "Message": '''# 四种 role，对应四种消息
Message.system("你是助手")                    # 系统提示词（角色/规则/工具说明）
Message.user("计算 1+1")                     # 用户输入
Message.assistant("Thought: …")              # 模型输出
Message.tool_result("calc", "1+1 = 2")       # 工具结果（= ReAct 里的 Observation）

m = Message.user("你好")
m.role        # 'user'
m.content     # '你好'
m.to_text()   # '【用户】你好'    —— 转成纯文本（喂给纯文本模型/写日志）
m.to_openai() # {'role': 'user', 'content': '你好'}   —— 转成 OpenAI 协议格式''',
    "ToolCall": '''c = ToolCall("calc", {"expr": "1+1"})
c.name            # 'calc'
c.args            # {'expr': '1+1'}
c.id              # 'call_00012345'  —— 不传就自动生成稳定指纹
c.signature()     # 'calc({"expr": "1+1"})'  —— 用于去重/死循环检测''',
    "Conversation": '''conv = Conversation()
conv.add(Message.system("你是助手"))
conv.add(Message.user("你好"))
len(conv)                  # 2
conv.last                  # 最后一条消息
conv.by_role("user")       # 按角色筛选
conv.total_chars()         # 总字符数（上下文预算用）
conv.render()              # 渲染成可读文本
# 这就是 Agent 的"记忆" —— 一个消息列表，每圈整段重发给模型''',
    # ---- 模型 ----
    "LLM": '''# 抽象基类：只要求子类实现 _complete()，把 messages 变成一段文本
class MyLLM(LLM):
    def _complete(self, messages, **kwargs):
        return LLMResponse(text="Final Answer: 42")

# 对外只用 complete()：它负责计时、统计 token、统一包装异常
resp = MyLLM().complete([Message.user("随便问")])
resp.text          # 'Final Answer: 42'
resp.total_tokens  # 累计 token''',
    "LLMResponse": '''LLMResponse(
    text="Final Answer: 42",   # ★ 模型回复的正文（唯一必填）
    model="my-model",          # 模型名
    prompt_tokens=10,          # 输入 token
    completion_tokens=5,       # 输出 token
    latency_ms=12.3,           # 耗时（complete() 会自动填）
)
# resp.total_tokens 是 prompt_tokens + completion_tokens（计算属性）''',
    "ScriptedLLM": '''# 按剧本逐条返回 —— 学习循环结构最常用的假模型
llm = ScriptedLLM([
    'Thought: 先算数。\\n<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>',
    'Thought: 算好了。\\nFinal Answer: 1+1 = 2',
])
from core import Agent
print(Agent(llm=llm, verbose=False).run("计算 1+1").answer)   # '1+1 = 2'

llm.calls    # 它收到的每次上下文都记着 —— 看"模型到底看到了什么"就用它
# 剧本用完后默认重复最后一条（方便观察循环保护）；
# 设 repeat_last=False 则抛 LLMError''',
    "RuleBasedLLM": '''# 默认的 Mock 模型：真的"看懂"问题，然后模仿 ReAct 两拍
llm = RuleBasedLLM()
llm.plan("计算 (12+8)*3/4")     # [('calc', {'expr': '(12+8)*3/4'})]
llm.plan("订单 A1001 到哪了")    # [('lookup_order', {'order_id': 'A1001'})]
llm.plan("你好")               # []  —— 不需要工具，直接回答

# 两拍的分界：这一轮里有没有出现 tool 角色的消息
#   没有 → 第一拍：输出 Thought + Action + <tool_call>{...}
#   有   → 第二拍：把工具结果讲成人话，输出 Final Answer''',
    "default_mock": '''llm = default_mock()      # 等价于 RuleBasedLLM(profile='generic')
# Agent 不传 llm 时内部用的就是它 —— 这就是"不需要 API Key"的原因''',
    "estimate_tokens": '''estimate_tokens("你好世界")          # 4   （中文 1 字 ≈ 1 token）
estimate_tokens("hello world")     # 3   （英文 4 字符 ≈ 1 token）
# 用于在没接真模型时估算成本趋势，不追求精确''',
    # ---- 解析 ----
    "parse_output": '''p = parse_output('Thought: 算一下。\\nAction: calc(expr="1+1")')
p.thought       # '算一下。'
p.answer        # ''            —— 没有 Final Answer 时为空
p.tool_calls    # [ToolCall(name='calc', args={'expr': '1+1'})]
p.errors        # []            —— 解析问题（空 = 正常）
p.has_tool_call # True
p.is_final      # False

# ★ 关键行为：出现 Action/tool_call 却解析不出调用时，**不会**把这段当答案，
#   而是往 errors 里报"协议违规"，交给 Agent 回灌纠错。
#   （否则半截坏 JSON 会被当成最终答案交给用户 —— 静默错误）''',
    "parse_tool_calls": '''parse_tool_calls('<tool_call>{"name": "calc", "args": {"expr": "1+1"}}</tool_call>')
# -> [ToolCall(name='calc', args={'expr': '1+1'})]   —— 只要工具调用，不要别的''',
    # ---- 提示词 ----
    "PromptBuilder": '''pb = PromptBuilder(
    style="react",                       # react / function_calling / plain
    persona="你是电商客服",                # 身份
    rules=["不要泄露内部订单号规则"],        # 业务规则
    extra_context="当前时间：2025-01-01",  # 动态上下文（RAG/记忆）
)
system = pb.build_system(reg)            # reg 是 ToolRegistry
# 生成四块结构：① 身份与规则 ② 工具说明书 ③ 输出格式契约 ④ 参考资料
# ★ 第 ③ 块的读者是**解析器**，不是用户 —— 这是 Agent 提示词最特别的地方''',
    # ---- 异常 ----
    "AgentError": '''# 异常体系（决定恢复策略）：
#   AgentError
#   ├─ LLMError            模型调用失败（网络/限流）→ 指数退避重试
#   ├─ ParseError          输出解析不了          → 回灌纠错提示
#   ├─ ToolError
#   │   ├─ ToolNotFound    工具不存在            → 返回可用工具清单
#   │   └─ ToolValidationError  参数不合法        → 回灌正确用法
#   ├─ MaxStepsExceeded    步数用完（保护，不是崩溃）
#   ├─ LoopDetected        重复动作（保护）
#   └─ AbortAgent          策略性中止
#       ├─ GuardrailTripped  护栏拦截（第 11 章）
#       └─ BudgetExceeded    预算耗尽（第 12 章）''',
    # ---- 教学输出 ----
    "setup_console": '''setup_console()     # 把 stdout 切到 UTF-8，并探测能否安全打印 emoji
# ★ 每个 demo / Notebook 开头都要调一次，否则 Windows GBK 控制台打印中文会抛
#   UnicodeEncodeError，整个程序崩掉''',
    "essence": '''essence("Agent = 循环 + 工具 + 历史")   # 用方框打印"一句话本质"''',
}


# ===========================================================================
# 三、按层分组（explain() 不带参数时用）
# ===========================================================================
LAYERS: list[tuple[str, str, list[str]]] = [
    ("① Agent 层", "跑循环、拿结果 —— 你最常用的一层", [
        "run_once", "quick_agent", "Agent", "AgentResult", "StepRecord",
    ]),
    ("② 工具层", "模型能调的「手和脚」", [
        "ToolRegistry", "ToolSpec", "ToolResult", "build_default_registry",
        "validate_schema",
    ]),
    ("③ 消息层", "Agent 的「记忆」就是这些", [
        "Message", "ToolCall", "Conversation",
    ]),
    ("④ 模型层", "把消息列表变成一段文本的东西", [
        "LLM", "LLMResponse", "estimate_tokens",
    ]),
    ("⑤ 提示词层", "怎么写给模型看的说明书", [
        "PromptBuilder",
    ]),
    ("⑥ 解析层", "模型输出 → 结构化动作", [
        "parse_output", "parse_tool_calls", "ParsedOutput",
    ]),
    ("⑦ 异常层", "错误分类决定恢复策略", [
        "AgentError", "LLMError", "ParseError", "ToolError", "ToolNotFound",
        "ToolValidationError", "MaxStepsExceeded", "LoopDetected",
        "AbortAgent", "GuardrailTripped", "BudgetExceeded",
    ]),
    ("⑧ 教学输出层", "打印用的（不影响 Agent 逻辑）", [
        "setup_console", "banner", "section", "note", "warn", "ok", "kv",
        "code", "essence", "check",
    ]),
]

# 这些名字来自别的模块（mock 模型 / 真实模型），单独列
MOCK_MODELS: list[tuple[str, str]] = [
    ("ScriptedLLM", "按剧本逐条返回 → 学习循环结构"),
    ("RuleBasedLLM", "规则驱动、能多步调工具 → 默认模型"),
    ("default_mock", "= RuleBasedLLM()；Agent 不传 llm 时用的就是它"),
    ("FlakyLLM", "前 N 次调用抛错 → 学习重试"),
    ("MalformedLLM", "输出格式崩坏 → 学习鲁棒解析"),
    ("HallucinatingLLM", "调用不存在的工具 → 学习错误回灌"),
    ("LoopingLLM", "永远重复同一动作 → 学习死循环检测"),
    ("SpyLLM", "包一层，记录每次收到的完整提示词 → 学习提示词工程"),
    ("HumanInLoopLLM", "模拟人类兜底 → 人工审批"),
]


# ===========================================================================
# 四、内省工具
# ===========================================================================
def _resolve(obj):
    """把字符串名字解析成真实对象。

    查找顺序（很重要，因为**重名**在 Python 里非常常见）：
        1. 调用方给的就是对象 → 直接返回
        2. core 框架里的公开名字
        3. mock / real 模型里的名字
        4. **Python 内置函数**（compile / len / open / eval …）
        5. **标准库常见模块**里的名字（re.compile / json.loads / math.sqrt …）
    """
    if not isinstance(obj, str):
        return obj
    name = obj.strip()

    # ---- 支持 "re.compile" / "json.loads" 这种带点的写法 ----
    if "." in name:
        mod_name, _, attr = name.rpartition(".")
        try:
            mod = __import__(mod_name, fromlist=["_"])
            if hasattr(mod, attr):
                return getattr(mod, attr)
        except ImportError:
            pass

    # ---- core 框架 ----
    import core
    if hasattr(core, name):
        return getattr(core, name)

    # ---- mock / real 模型 ----
    for mod_name in ("core.mock_llm", "core.real_llm"):
        try:
            mod = __import__(mod_name, fromlist=["_"])
            if hasattr(mod, name):
                return getattr(mod, name)
        except ImportError:
            continue

    # ---- Python 内置（compile / len / open …）----
    import builtins
    if hasattr(builtins, name):
        return getattr(builtins, name)

    # ---- 标准库常见模块 ----
    for mod_name in ("re", "json", "math", "ast", "inspect", "itertools",
                     "collections", "functools", "pathlib", "typing",
                     "dataclasses", "time", "random", "textwrap", "difflib"):
        try:
            mod = __import__(mod_name, fromlist=["_"])
            if hasattr(mod, name):
                return getattr(mod, name)
        except ImportError:
            continue

    return None


def _describe_type(t) -> str:
    """把类型注解变成**短**字符串。

    ★ 读者看的是 "list[StepRecord]"，不是 "list[core.agent.StepRecord]"。
      所以这里要剥掉模块前缀 —— 类型名字太长会让人直接放弃阅读。

    ★ 另一个真实的坑（写这个函数时踩到的）：
      `list[StepRecord]` 这种泛型别名的 `__name__` 就是字符串 "list"！
      所以**不能先看 __name__**，否则会直接返回 "list"，
      把最重要的信息（里面装的是什么）丢掉。
      必须**先看 __origin__ 处理泛型**，再看 __name__。
    """
    if t is None or t is type(None):
        return "None"
    if isinstance(t, str):
        return _short_name(t)
    try:
        origin = getattr(t, "__origin__", None)
        args = getattr(t, "__args__", None)

        # ① 联合类型：Optional[X] / X | Y
        if origin is typing.Union or str(origin) == "typing.Union":
            if args:
                return " | ".join(_describe_type(a) for a in args)

        # ② 泛型容器：list[X] / dict[K, V] / tuple[...]
        if origin in (list, tuple, dict, set, frozenset) and args:
            inner = ", ".join(_describe_type(a) for a in args)
            return f"{origin.__name__}[{inner}]"

        # ③ 普通类
        name = getattr(t, "__name__", None)
        if name and name not in ("list", "dict", "tuple", "set"):
            return name
        if name:
            return name

        # ④ 兜底：字符串化后剥模块前缀
        return _short_name(str(t).replace("typing.", ""))
    except Exception:
        return str(t)


def _short_name(s: str) -> str:
    """把 'list[core.agent.StepRecord] | None' 这种剥成 'list[StepRecord] | None'。

    做法：逐个 token 处理，遇到带点的名字只保留最后一段。
    这样既处理了泛型参数，也处理了联合类型，还不会误伤 'core.agent' 这种模块名
    （模块名只出现在点号左边，保留最后一段正好把模块前缀去掉）。
    """
    import re

    def shrink(match: re.Match) -> str:
        tok = match.group(0)
        # 只对"看起来像类路径"的 token 动手：至少一个大写字母开头，或含点
        if "." not in tok:
            return tok
        return tok.rsplit(".", 1)[-1]

    # 匹配形如 xxx.yyy.ClassName 的 token（字母/数字/下划线/点）
    return re.sub(r"[A-Za-z_][A-Za-z0-9_.]*", shrink, s)


def _plain_meaning(t) -> str:
    """给容器类型一句人话解释 —— 光看 list[StepRecord] 读者不知道能取什么。"""
    s = _describe_type(t)
    mapping = {
        "str": "一段文本",
        "int": "整数",
        "float": "小数",
        "bool": "True / False",
        "list": "列表",
        "dict": "字典",
        "NoneType": "无",
        "None": "无",
    }
    if s in mapping:
        return mapping[s]
    if s.startswith("list[") or s.startswith("List["):
        inner = s[s.index("[") + 1:-1]
        return f"列表，每个元素是 {inner}"
    if s.startswith("dict[") or s.startswith("Dict["):
        return "字典"
    if s.startswith("Callable"):
        return "可调用对象（函数）"
    return ""


def _get_hints(obj) -> dict:
    """安全地取类型注解（处理 PEP 563 延迟注解）。"""
    try:
        return typing.get_type_hints(obj)
    except Exception:
        return dict(getattr(obj, "__annotations__", {}) or {})


def _fields_of(cls) -> list[tuple[str, str, str]]:
    """取 dataclass 的字段：(名字, 类型字符串, 默认值)。

    ★ 为什么要用 get_type_hints 而不是直接读 f.type？
        因为 `from __future__ import annotations`（PEP 563）会让 f.type 变成
        **字符串** 'list[StepRecord]'，而直接 str() 一个泛型对象又会得到
        'list[core.agent.StepRecord]' 这种带完整模块路径的长名字。
        get_type_hints 能解析成真实类型对象，再由 _describe_type 规整成短名字。
    """
    import dataclasses
    if not dataclasses.is_dataclass(cls):
        return []
    hints = _get_hints(cls)
    out = []
    for f in dataclasses.fields(cls):
        raw = hints.get(f.name, f.type)
        t = _describe_type(raw)
        d = "" if f.default is dataclasses.MISSING else repr(f.default)
        out.append((f.name, t, d))
    return out


# ===========================================================================
# 五、主函数
# ===========================================================================
def _print_kv(key: str, value: str, width: int = 12) -> None:
    print(f"    {key:<{width}} {value}")


def explain(obj=None) -> None:
    """解释一个函数 / 类 / 实例 / 模块：它是什么、参数要什么、返回什么。

    用法：
        explain()                 列出 core 的全部公开名字（按层分组）
        explain(run_once)         查函数（含参数含义和可跑的例子）
        explain(AgentResult)      查数据类（会展开它的字段）
        explain(count_words)      查任意函数
        explain("run_once")       传名字字符串也行
    """
    # ---- 不给参数：打印总索引 ----
    if obj is None:
        _print_index()
        return

    target = _resolve(obj)
    if target is None:
        print(f"❌ 在 core 里找不到 {obj!r}。")
        print()
        print("   可能的原因：")
        print("     · 名字拼错了 —— explain() 不带参数可以列出全部公开名字")
        print("     · 它是**工具**而不是框架 API：内置工具（calc / count_words /")
        print("       lookup_order / read_file…）是注册在注册表里的，不是模块级函数。")
        print("       查这类请看：explain(build_default_registry)")
        print("     · 它是某一章内部定义的局部函数（在那一章的代码单元里）")
        return

    name = getattr(target, "__name__", None) or type(target).__name__

    # ---- 模块 ----
    if inspect.ismodule(target):
        print(f"📦 模块 {target.__name__}")
        doc = (target.__doc__ or "").strip().splitlines()
        if doc:
            print()
            for line in doc[:12]:
                print("   ", line)
        print()
        print("   导出：", ", ".join(getattr(target, "__all__", [])[:20]) or "（无 __all__）")
        return

    # ---- 类 ----
    if inspect.isclass(target):
        _explain_class(target, name)
        return

    # ---- 函数 / 方法 ----
    if inspect.isfunction(target) or inspect.ismethod(target) or callable(target):
        _explain_callable(target, name)
        return

    # ---- 实例 ----
    print(f"🔹 实例：{name}")
    print(f"    类型      {type(target).__module__}.{type(target).__qualname__}")
    if hasattr(target, "__dataclass_fields__"):
        print()
        print("    字段（可以直接用 .名字 取；下面同时给出**当前值**）：")
        for fname, ftype, fdefault in _fields_of(type(target)):
            try:
                cur = repr(getattr(target, fname))
                if len(cur) > 40:
                    cur = cur[:40] + "…"
            except Exception:
                cur = "(取不到)"
            print(f"      .{fname:<16} {ftype:<22} 当前 = {cur}")
            meaning = _field_doc(name, fname)
            if meaning:
                print(f"        → {meaning}")
    else:
        attrs = [a for a in dir(target) if not a.startswith("_")][:20]
        print("    可用的属性和方法：", ", ".join(attrs))


def _explain_callable(fn, name: str) -> None:
    """解释一个函数。"""
    # 内置函数 / 标准库函数：它们没有我们的 PARAM_DOCS，但重名陷阱特别多
    full = getattr(fn, "__qualname__", name)
    module = getattr(fn, "__module__", "") or ""
    is_builtin = module in ("builtins",) or not getattr(fn, "__doc__", None) and not module
    label = f"{module}.{full}" if module and module != "builtins" else full
    builtin_note = _builtin_note(label) or _builtin_note(name)

    if is_builtin or builtin_note:
        print(f"🔧 函数 {name}()" + (f"    ← 来自 {module}" if module and module != "builtins" else "    ← Python 内置"))
    else:
        print(f"🔧 函数 {name}()")
    print()

    # 内置/标准库的说明优先（往往讲的是"别踩这个坑"）
    if builtin_note:
        print("    ★ 说明：")
        for line in builtin_note.split("\n"):
            print("      " + line)
        print()

    # 它是什么（docstring 第一段）
    doc = (fn.__doc__ or "").strip()
    if doc:
        first = []
        for line in doc.splitlines():
            if line.strip().startswith(("参数", "Args", "----", "返回", "Returns")):
                break
            first.append(line.strip())
        if first:
            print("    是什么：")
            for line in first[:4]:
                print("      ", line)
            print()
    else:
        print("    是什么：（这个函数没有 docstring —— 直接看下面的参数说明）")
        print()

    # 参数
    try:
        sig = inspect.signature(fn)
    except (ValueError, TypeError):
        print("    （无法读取签名）")
        return
    hints = _get_hints(fn)

    params = [p for p in sig.parameters.values()
              if p.name not in ("self", "cls")]
    required = [p for p in params if p.default is inspect.Parameter.empty]
    optional = [p for p in params if p.default is not inspect.Parameter.empty]

    print(f"    参数（{len(required)} 个必填，{len(optional)} 个可选）：")
    if not params:
        print("      （无参数）")
    for p in required + optional:
        raw = hints.get(p.name, p.annotation)
        if raw is inspect.Parameter.empty:
            type_str = ""
        else:
            type_str = _describe_type(raw)
        # 组装一行的右半部分：类型 + 默认值
        tail = []
        if type_str:
            tail.append(type_str)
        if p.default is not inspect.Parameter.empty:
            tail.append(f"默认 {p.default!r}")
        suffix = ("  " + "  ".join(tail)) if tail else ""
        print(f"      {p.name}{suffix}")
        meaning = (PARAM_DOCS_BY_FUNC.get((name, p.name))
                   or PARAM_DOCS.get(p.name))
        if meaning:
            for i, line in enumerate(meaning.split("\n")):
                print(f"        {'  ' if i else '→ '}{line}")

    # 返回
    print()
    ret = hints.get("return", sig.return_annotation)
    if ret is not inspect.Signature.empty:
        ret_name = _describe_type(ret)
        print(f"    返回：{ret_name}")
        cls = None
        if inspect.isclass(ret):
            cls = ret
        elif isinstance(ret, str):
            cls = _resolve(ret)
        if inspect.isclass(cls):
            fields = _fields_of(cls)
            if fields:
                print("      它的字段（可以用 .名字 取）：")
                for fname, ftype, fdefault in fields:
                    d = f"   默认 {fdefault}" if fdefault else ""
                    print(f"        .{fname:<16} {ftype}{d}")
    else:
        print("    返回：（没有标注）")

    # 例子
    ex = EXAMPLES.get(name)
    if ex:
        print()
        print("    可以抄的例子：")
        for line in ex.split("\n"):
            print("      " + line)

    # 相关
    rel = _related(name)
    if rel:
        print()
        print("    相关：", ", ".join(f"explain({r})" for r in rel))


def _explain_class(cls, name: str) -> None:
    """解释一个类（数据类会展开字段，普通类会列出方法）。"""
    bases = [b.__name__ for b in cls.__mro__[1:] if b is not object]
    kind = "数据类" if hasattr(cls, "__dataclass_fields__") else "类"
    print(f"🔷 {kind} {name}" + (f"（继承自 {', '.join(bases)}）" if bases else ""))
    print()

    doc = (cls.__doc__ or "").strip()
    if doc:
        # ★ dataclass 的 __doc__ 第一行是**自动生成的签名**
        #   （形如 "Message(role: 'Role', content: 'str' = '', ...)"），
        #   直接打印出来是一堆噪音。这里跳过它，只留人写的说明部分。
        lines = [ln.strip() for ln in doc.splitlines()]
        if lines and "(" in lines[0] and ")" in lines[0]:
            lines = lines[1:]
        lines = [ln for ln in lines if ln]
        if lines:
            print("    是什么：")
            for line in lines[:5]:
                print("      ", line)
            print()
        else:
            print("    是什么：（没有说明 —— 看下面的字段）")
            print()
    else:
        print("    是什么：（没有 docstring —— 看下面的字段/方法）")
        print()

    fields = _fields_of(cls)
    if fields:
        # dataclass：列出每个字段
        req = [f for f in fields if not f[2]]
        opt = [f for f in fields if f[2]]
        print(f"    字段（{len(req)} 个必填，{len(opt)} 个有默认值）：")
        hints = _get_hints(cls)
        for fname, ftype, fdefault in req + opt:
            d = f"   默认 {fdefault}" if fdefault else ""
            print(f"      .{fname:<16} {ftype}{d}")
            # 字段的人话解释（这就是读者真正需要的部分）
            meaning = _field_doc(name, fname)
            if meaning:
                print(f"        → {meaning}")
        # 计算属性
        props = [n for n, _ in inspect.getmembers(cls, lambda o: isinstance(o, property))]
        if props:
            print()
            print("    计算属性（不用传，直接 .名字 取）：", ", ".join(props))
    else:
        # 普通类：列出公开方法
        methods = []
        for n, m in inspect.getmembers(cls, predicate=inspect.isfunction):
            if n.startswith("_") and n not in ("__init__",):
                continue
            try:
                msig = str(inspect.signature(m)).replace("self, ", "").replace("(self)", "()")
            except (ValueError, TypeError):
                msig = "(...)"
            methods.append((n, msig))
        if methods:
            print("    方法：")
            for n, msig in methods[:14]:
                print(f"      .{n}{msig}")

    ex = EXAMPLES.get(name)
    if ex:
        print()
        print("    可以抄的例子：")
        for line in ex.split("\n"):
            print("      " + line)

    rel = _related(name)
    if rel:
        print()
        print("    相关：", ", ".join(f"explain({r})" for r in rel))


def _related(name: str) -> list[str]:
    """给出常见搭配 —— 读者查一个东西时，往往接着要查另一个。"""
    table = {
        "run_once": ["quick_agent", "AgentResult", "Agent"],
        "quick_agent": ["Agent", "AgentResult"],
        "Agent": ["AgentResult", "StepRecord", "PromptBuilder"],
        "AgentResult": ["StepRecord", "Agent"],
        "StepRecord": ["AgentResult"],
        "build_default_registry": ["ToolRegistry", "ToolSpec"],
        "ToolRegistry": ["ToolSpec", "ToolResult"],
        "ToolSpec": ["ToolRegistry"],
        "Message": ["ToolCall", "Conversation"],
        "ScriptedLLM": ["LLM", "LLMResponse"],
        "parse_output": ["ParsedOutput", "ToolCall"],
        "PromptBuilder": ["ToolRegistry"],
    }
    return table.get(name, [])


def _print_index() -> None:
    """打印 core 的公开 API 总索引（按层分组）。"""
    print("=" * 66)
    print("  core 框架 · 公开 API 索引")
    print("=" * 66)
    print()
    print("  用 explain(名字) 查详情，例如：explain(run_once)")
    print()

    for layer_name, layer_desc, names in LAYERS:
        print(f"  {layer_name} —— {layer_desc}")
        for n in names:
            print(f"      explain({n})")
        print()

    print("  离线假模型（不需要 API Key 的关键）")
    for n, desc in MOCK_MODELS:
        print(f"      {n:<18} {desc}")
    print()
    print("  提示：explain() 能处理函数、类、实例、模块，也接受字符串名字。")
    print("       想看某个函数怎么用 → explain(那个函数)")


def api_index() -> None:
    """`explain()` 的别名，语义更直白一点。"""
    _print_index()
