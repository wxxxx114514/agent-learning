"""core —— 我们自己的迷你 Agent 框架（手写，零依赖，全部可读）。

模块地图：
    errors    异常体系（错误分类决定恢复策略）
    message   消息 / 会话 / ToolCall 数据结构
    llm       模型抽象基类（依赖倒置：内核不依赖任何厂商 SDK）
    mock_llm  离线假模型（脚本化 / 规则化 / 各种捣乱模型）
    real_llm  真实模型适配器（OpenAI 兼容协议，urllib 实现）
    parser    模型文本 → 思考 + 工具调用的解析器
    tool      工具规格、JSON Schema 校验、注册表、内置工具
    prompts   提示词构建器（ReAct / Function Calling / 上下文注入）
    agent     Agent 主循环（本框架的心脏）
    console   教学输出工具（UTF-8 修复 + 排版原语）
"""

from .agent import Agent, AgentResult, StepRecord, quick_agent, run_once
from .console import (
    banner, boxed, check, code, essence, kv, note, ok, section, setup_console, warn,
)
from .errors import (
    AbortAgent, AgentError, BudgetExceeded, GuardrailTripped, LLMError, LoopDetected,
    MaxStepsExceeded, ParseError, ToolError, ToolNotFound, ToolValidationError,
)
from .llm import LLM, LLMResponse, estimate_tokens
from .message import Conversation, Message, ToolCall
from .parser import ParsedOutput, parse_output, parse_tool_calls
from .prompts import PromptBuilder
from .tool import ToolRegistry, ToolResult, ToolSpec, build_default_registry, validate_schema

__all__ = [
    "Agent", "AgentResult", "StepRecord", "quick_agent", "run_once",
    "LLM", "LLMResponse", "estimate_tokens",
    "Conversation", "Message", "ToolCall",
    "ParsedOutput", "parse_output", "parse_tool_calls",
    "PromptBuilder",
    "ToolRegistry", "ToolResult", "ToolSpec", "build_default_registry", "validate_schema",
    "AgentError", "LLMError", "LoopDetected", "MaxStepsExceeded",
    "ParseError", "ToolError", "ToolNotFound", "ToolValidationError",
    "AbortAgent", "GuardrailTripped", "BudgetExceeded",
    "setup_console", "banner", "section", "note", "warn", "ok", "kv",
    "code", "boxed", "essence", "check",
]

__version__ = "0.1.0"
