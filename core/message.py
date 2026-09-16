"""消息（Message）与会话数据结构的统一约定。

为什么要有自己的 Message 类型？
    各家 API 的消息字段名千奇百怪（role/content/tool_calls/tool_call_id/name…）。
    统一成一种内部表示，转换只发生在适配器边界，Agent 内核就干净了。

内部消息角色只有 5 种：
    system        系统提示词（规则、身份、工具说明）
    user          用户输入
    assistant     模型输出（可能含思考 + 工具调用）
    tool          工具执行结果（= 经典 ReAct 里的 Observation）
    (tool 也承载"错误回灌"，不区分成功失败，由 metadata 标记)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ToolCall:
    """一次工具调用请求。"""

    name: str
    args: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"call_{abs(hash((self.name, json.dumps(self.args, sort_keys=True, default=str)))) % 10**8:08d}"

    def signature(self) -> str:
        """用于去重 / 死循环检测的指纹。"""
        return f"{self.name}({json.dumps(self.args, sort_keys=True, ensure_ascii=False, default=str)})"

    def __str__(self) -> str:
        return self.signature()


@dataclass
class Message:
    role: Role
    content: str = ""
    name: str = ""          # 工具消息：工具名；assistant：模型名
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_call_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    # ---- 构造快捷方法 -------------------------------------------------
    @classmethod
    def system(cls, content: str) -> "Message":
        return cls(role="system", content=content)

    @classmethod
    def user(cls, content: str) -> "Message":
        return cls(role="user", content=content)

    @classmethod
    def assistant(cls, content: str, tool_calls: list[ToolCall] | None = None) -> "Message":
        return cls(role="assistant", content=content, tool_calls=tool_calls or [])

    @classmethod
    def tool_result(
        cls,
        name: str,
        content: str,
        tool_call_id: str = "",
        ok: bool = True,
        **metadata: Any,
    ) -> "Message":
        return cls(
            role="tool",
            name=name,
            content=content,
            tool_call_id=tool_call_id,
            metadata={"ok": ok, **metadata},
        )

    # ---- 转换 ---------------------------------------------------------
    def to_openai(self) -> dict[str, Any]:
        """转成 OpenAI 兼容协议的 message 结构。"""
        if self.role == "tool":
            return {"role": "tool", "tool_call_id": self.tool_call_id, "content": self.content}
        if self.role == "assistant" and self.tool_calls:
            return {
                "role": "assistant",
                "content": self.content or None,
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.args, ensure_ascii=False)},
                    }
                    for c in self.tool_calls
                ],
            }
        return {"role": self.role, "content": self.content}

    def to_text(self) -> str:
        """转成纯文本（用于喂给只支持文本的模型，以及写日志）。"""
        head = {"system": "【系统】", "user": "【用户】", "assistant": "【助手】", "tool": "【工具】"}[self.role]
        body = self.content
        if self.tool_calls:
            calls = "\n".join(f"  <tool_call>{c.signature()}</tool_call>" for c in self.tool_calls)
            body = f"{body}\n{calls}".strip()
        return f"{head}{body}"

    def char_len(self) -> int:
        return len(self.content) + sum(len(str(c)) for c in self.tool_calls)


class Conversation:
    """一个会话（消息列表）的薄封装：Agent 的记忆就是这个列表。"""

    def __init__(self, messages: list[Message] | None = None) -> None:
        self.messages: list[Message] = list(messages or [])

    def add(self, msg: Message) -> Message:
        self.messages.append(msg)
        return msg

    def extend(self, msgs: list[Message]) -> None:
        self.messages.extend(msgs)

    def __len__(self) -> int:
        return len(self.messages)

    def __iter__(self):
        return iter(self.messages)

    def __getitem__(self, i):
        return self.messages[i]

    @property
    def last(self) -> Message | None:
        return self.messages[-1] if self.messages else None

    def by_role(self, role: Role) -> list[Message]:
        return [m for m in self.messages if m.role == role]

    def render(self) -> str:
        return "\n\n".join(m.to_text() for m in self.messages)

    def total_chars(self) -> int:
        return sum(m.char_len() for m in self.messages)

    def tool_signatures(self) -> list[str]:
        return [c.signature() for m in self.messages for c in m.tool_calls]

    def reset(self, keep_system: bool = True) -> None:
        self.messages = [m for m in self.messages if m.role == "system"] if keep_system else []
