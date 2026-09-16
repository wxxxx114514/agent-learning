"""统一的异常类型。

Agent 工程里，**报错信息就是给模型看的下一条上下文**。
所以异常要分得足够细：不同错误对应不同的恢复策略（重试 / 换工具 / 直接回灌给模型）。
"""

from __future__ import annotations


class AgentError(Exception):
    """所有 Agent 相关异常的基类。"""


class LLMError(AgentError):
    """模型调用层失败：网络抖动、限流、鉴权、超时。常见处理：指数退避重试。"""


class ParseError(AgentError):
    """模型输出无法解析成合法动作。常见处理：把错误回灌给模型要求重写。"""


class ToolError(AgentError):
    """工具执行失败（业务异常）。常见处理：变成 observation 让模型自己想办法。"""


class ToolNotFound(ToolError):
    """模型请求了不存在的工具。常见处理：返回可用工具清单。"""


class ToolValidationError(ToolError):
    """工具参数不合法。常见处理：把 schema 校验错误原文回灌。"""


class MaxStepsExceeded(AgentError):
    """达到最大步数上限，Agent 主动停机。这是**保护**，不是崩溃。"""


class LoopDetected(AgentError):
    """检测到重复动作（死循环）。"""


class AbortAgent(AgentError):
    """主动中止：护栏命中、预算耗尽、人类拒绝等。

    与普通错误的区别：这是**预期内的策略性停机**，不是故障。
    阶段 11（护栏）与阶段 12（成本预算）会大量使用它。
    """


class GuardrailTripped(AbortAgent):
    """护栏拦截：检测到提示词注入、越权访问、危险指令等。"""


class BudgetExceeded(AbortAgent):
    """预算耗尽：token 数 / 调用次数 / 金额 / 墙上时间超出上限。"""
