"""检查点仓库：把"运行中的状态"从内存搬到磁盘。

------------------------------------------------------------
一句话本质：
    Agent 的状态 = 会话消息列表 + 已完成步数 + 累计结果。
    只要每一步之后把这**三样东西**存下来，进程随时可以死，
    换个进程接着跑，用户完全无感。
------------------------------------------------------------

本模块提供四件生产基础设施（全部零依赖、可离线跑）：

    EventLog          结构化日志：JSON 行，可按 run_id 过滤
    CheckpointStore   检查点：run 状态落盘 + 原子写 + 崩溃后重新装载
    IdempotencyCache  幂等缓存：同一个幂等键返回同一个结果，副作用只发生一次
    Metrics           计数器：服务级指标（提交数 / 缓存命中 / 拒绝数…）

为什么不用 Redis / Postgres？
    课程约束是零第三方依赖。但请注意：
    **这里的接口就是真实系统的接口** —— `save()/load()/list_runs()` 换成
    `SET run:{id} <json> EX 3600` 或一张 `agent_runs` 表，逻辑一行都不用改。
    先手写一遍，你才知道 Redis 帮你省掉了什么（原子性、TTL、并发、集群）。
"""

from __future__ import annotations

import copy
import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from core.message import Conversation, Message, ToolCall

# 运行状态机的取值。生产系统里这张状态图必须显式定义，
# 否则你永远说不清"这条记录到底算不算跑完了"。
STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_CRASHED = "crashed"       # 进程没了 / 超时降级，但检查点还在 → 可续跑
STATUS_DONE = "done"
STATUS_FAILED = "failed"


# ===========================================================================
# 一、消息的序列化：能不能落盘，决定了能不能续跑
# ===========================================================================
def message_to_dict(msg: Message) -> dict[str, Any]:
    """把 Message 变成纯 JSON（可写文件、可进 Redis、可进数据库 JSON 列）。

    为什么要自己写而不是用 `dataclasses.asdict`？
        因为 Message 里的 ToolCall 也要展开，而 metadata 里可能混进
        任意不可序列化的对象（比如异常实例）。生产代码必须在边界处
        "贴地"处理：能转的转，不能转的降级成 repr —— 但**绝不抛异常**，
        因为"日志写不进去"不应该让"任务跑不下去"。
    """
    return {
        "role": msg.role,
        "content": msg.content,
        "name": msg.name,
        "tool_call_id": msg.tool_call_id,
        "tool_calls": [
            {"name": c.name, "args": c.args, "id": c.id} for c in msg.tool_calls
        ],
        "metadata": _safe_json(msg.metadata),
    }


def dict_to_message(raw: dict[str, Any]) -> Message:
    """从 JSON 还原 Message。落盘格式一旦上线就**不能随便改**（向后兼容）。"""
    calls = [
        ToolCall(name=str(c.get("name", "")), args=dict(c.get("args") or {}), id=str(c.get("id", "")))
        for c in (raw.get("tool_calls") or [])
    ]
    return Message(
        role=raw.get("role", "user"),
        content=raw.get("content", "") or "",
        name=raw.get("name", "") or "",
        tool_calls=calls,
        tool_call_id=raw.get("tool_call_id", "") or "",
        metadata=dict(raw.get("metadata") or {}),
    )


def _safe_json(obj: Any) -> Any:
    """尽力把任意对象变成可 JSON 化的结构（失败降级为字符串）。"""
    try:
        json.dumps(obj, ensure_ascii=False)
        return obj
    except Exception:
        if isinstance(obj, dict):
            return {str(k): _safe_json(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_safe_json(v) for v in obj]
        return repr(obj)


# ===========================================================================
# 二、一次运行的全部状态（RunState）
# ===========================================================================
@dataclass
class Request:
    """一次外部请求。注意它和一个"run"是一对一的。"""

    request_id: str
    user_id: str
    task: str
    idempotency_key: str = ""
    max_steps: int = 6
    max_seconds: float = 30.0
    source: str = "http"      # 便于灰度/统计区分来源（web / api / cron）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "Request":
        known = {f for f in Request.__dataclass_fields__}
        return Request(**{k: v for k, v in raw.items() if k in known})


@dataclass
class RunState:
    """**这就是"生产化的核心数据结构"**：一次 Agent 运行的可持久化快照。

    几个关键字段，一个都不能少：
        messages_before  本条 run 的**起点会话**（恢复时从这里重放，保证幂等）
        messages         最近一次保存时的完整会话（Agent 的全部记忆）
        steps_done       已经跑完几步（决定还剩几步预算）
        tool_hits        各工具已成功执行的次数（用来证明"没白跑、没重跑"）
        partial_answer   目前能拿得出手的半成品答案（超时降级时给用户看的东西）

    ★ 为什么"起点"和"当前"要分开存？（这是本章最容易设计错的地方）

        恢复策略是"**从起点重放**"：
            恢复 = 把会话倒回起点 → 重新交给 Agent 跑 → 它会自己把
                   用户那条消息再追加一次 → 于是模型看到的历史完全一致。

        如果只存"当前完整会话"，恢复时会这样：
            当前会话已经含用户消息 → 恢复后又追加一次用户消息 → 用户消息出现两次
            → 模型看到重复的问题、工具结果对不上号 → 重放事故。

        更糟的一种常见写法是"只存当前会话 + 记住步号"，
        然后让新进程从第 N 步接着算 —— 那样你**必须假设**模型和工具都是幂等的，
        而它们不是。所以 checkpoint 的正确语义永远是：
            **存起点 + 存已完成的事实，恢复时重放。**
        （LangGraph 的 Checkpointer 也是这个模型：存 thread state，恢复时重放图。）
    """

    run_id: str
    request: Request
    state: str = STATUS_PENDING
    version: str = "stable"
    messages: list[dict[str, Any]] = field(default_factory=list)
    messages_before: list[dict[str, Any]] = field(default_factory=list)
    # 起点是否已经捕获过。**不能用"messages_before 是否为空"来代表"没捕获"**：
    # 首次运行时起点本来就是空会话（连 system 都还没有），空值是有意义的取值。
    start_captured: bool = False
    steps_done: int = 0
    # 已完成步骤的**事实清单**：[{step, kind, tool, ok}, ...]
    # 为什么既存 steps_done 又存清单？前者用来快速判断"还剩几步"，
    # 后者用来在续跑时重建状态（并作为"这一步真的做过"的证据）。
    completed_steps: list[dict[str, Any]] = field(default_factory=list)
    tool_hits: dict[str, int] = field(default_factory=dict)
    partial_answer: str = ""
    stop_reason: str = ""
    answer: str = ""
    error: str = ""
    attempts: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0
    # 幂等键 → 业务结果。命中它就说明"这件事之前已经做成了，别再做了"。
    result_cache: dict[str, str] = field(default_factory=dict)

    # ---- 会话的存取（这是"续跑"的物理基础） ---------------------------
    def to_conversation(self) -> Conversation:
        """从**最近一次保存的完整会话**重建。

        注意是 `messages` 而不是 `messages_before`：
        恢复时要还原的是"崩溃前最后那个自洽的步骤边界"，
        而引擎随后会把末尾的用户消息摘掉再重放（见 CheckpointedEngine.start），
        这样 Agent 追加用户消息的动作恰好把历史精确复原。
        """
        return Conversation([dict_to_message(m) for m in self.messages])

    def snapshot_start(self, conv: Conversation) -> None:
        """记录"本条 run 的起点" —— **一次 run 只写一次，之后永不覆盖**。

        为什么必须"只写一次"？看下面这条真实的 bug 链（我们在本章真的踩了）：
            ① 起点在 start() 里正确记为 0 条消息（首次运行本来就是空会话）；
            ② 崩溃处理里"顺手"又写了一次 `messages_before = 当前会话`，
               把起点覆盖成了"跑了一半的状态"；
            ③ 恢复时按这个起点重放 → 用户消息被追加第二次 →
               模型看到重复的问题、以为什么都没做 → 从头再做一遍；
            ④ 最终答案是对的，检查点也在，日志也正常，
               只有**工具调用次数悄悄翻倍** —— 而这正是幂等要防的事故本身。

        教训：**同一个语义字段只能有一个写入点**。
        多写入点 + 无保护 = 迟早写错，而且错得很难看出来。
        （顺带一提：`if not self.messages_before` 这种"用空值代表未设置"的判据
          在第一次起点本来就是空的时候会直接失效 —— 空值是合法取值，
          要用独立的 bool 标记，而不是拿空值当哨兵。）
        """
        if self.start_captured:
            return
        self.messages_before = [message_to_dict(m) for m in conv.messages]
        self.start_captured = True
    def set_conversation(self, conv: Conversation) -> None:
        self.messages = [message_to_dict(m) for m in conv.messages]

    def preview(self, limit: int = 3) -> list[str]:
        """给终端看的简短会话摘要（教学输出用，避免刷屏）。"""
        out = []
        for m in self.messages[-limit:]:
            text = (m.get("content") or "").replace("\n", " ")
            out.append(f"[{m.get('role')}] {text[:60]}")
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["request"] = self.request.to_dict()
        return _safe_json(d)

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> "RunState":
        data = dict(raw)
        data["request"] = Request.from_dict(data.get("request") or {})
        known = {f for f in RunState.__dataclass_fields__}
        return RunState(**{k: v for k, v in data.items() if k in known})


# ===========================================================================
# 三、检查点仓库（可插拔：内存版 / 文件版）
# ===========================================================================
class CheckpointStore:
    """把 RunState 存下来、读回来。

    两种实现共用一个接口（这就是"面向接口编程"的价值）：
        InMemoryCheckpointStore —— 演示用，进程一死全没（正是我们要批判的做法）
        FileCheckpointStore     —— 落到磁盘目录，进程死了状态还在

    文件版的关键工程细节：**原子写**。
        直接 `open(path,"w").write(json)` 有个致命窗口：
        文件被截断了但新内容还没写完 → 此刻进程被杀 → 检查点变成一个坏 JSON。
        于是"崩溃恢复"变成了"崩溃 + 数据损坏"，比没有检查点更糟。
        解法：先写临时文件 → fsync → `os.replace()` 原子改名。
        `os.replace` 在同一文件系统内是原子操作，这是所有数据库的通用套路。
    """

    # ---- 接口 ---------------------------------------------------------
    def save(self, state: RunState) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError

    def patch(self, run_state: RunState, **fields: Any) -> None:
        """**只改指定字段**地保存一次。

        为什么不直接 `save(state)`？
            因为调用方（引擎 / 运行时）手里可能只有一个"部分视图"的 state 对象，
            直接整体覆盖会把别人写过的字段抹掉。
            生产里的通用做法有两种，都值得记住：
              ① 让每个写入方只写自己负责的字段（本方法）；
              ② 用 CAS / 版本号做乐观锁，冲突就重读重写（多进程场景必须这么做）。
            我们这里用 ①，并在注释里点明 ② 存在的必要性。

        参数名刻意叫 `run_state` 而不是 `state`：
        因为 RunState 自己有一个字段就叫 `state`（运行状态机），
        参数同名会让 `patch(s, state=...)` 直接抛 TypeError —— 小小的命名选择，
        能省掉一次真实的调试。
        """
        for key, value in fields.items():
            setattr(run_state, key, value)
        self.save(run_state)

    def load(self, run_id: str) -> RunState | None:  # pragma: no cover - 抽象
        raise NotImplementedError

    def list_run_ids(self) -> list[str]:  # pragma: no cover - 抽象
        raise NotImplementedError

    def delete(self, run_id: str) -> None:  # pragma: no cover - 抽象
        raise NotImplementedError


class InMemoryCheckpointStore(CheckpointStore):
    """内存版 —— 第 13 章开头要批判的"天真做法"就是它。"""

    def __init__(self) -> None:
        self._runs: dict[str, RunState] = {}

    def save(self, state: RunState) -> None:
        self._runs[state.run_id] = copy.deepcopy(state)

    def load(self, run_id: str) -> RunState | None:
        found = self._runs.get(run_id)
        return copy.deepcopy(found) if found else None

    def list_run_ids(self) -> list[str]:
        return sorted(self._runs)

    def delete(self, run_id: str) -> None:
        self._runs.pop(run_id, None)

    def simulate_restart(self) -> None:
        """模拟"进程被杀"：内存里的状态全部消失。这就是天真做法的死因。"""
        self._runs.clear()


class FileCheckpointStore(CheckpointStore):
    """磁盘版 —— 生产里对应 Redis / Postgres / S3。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        # run_id 可能来自外部输入 → 必须做路径穿越防护（第 02 章讲过同样的坑）
        safe = "".join(ch for ch in run_id if ch.isalnum() or ch in "-_")
        return self.root / f"{safe or 'unnamed'}.json"

    def save(self, state: RunState) -> None:
        state.updated_at = time.time()
        path = self._path(state.run_id)
        payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2)
        # 原子写：临时文件 → 替换。中途被杀也不会留下半截 JSON。
        fd, tmp = tempfile.mkstemp(dir=str(self.root), prefix=".tmp-", suffix=".json")
        try:
            with open(fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                try:
                    import os

                    os.fsync(f.fileno())   # 真正落盘，而不是留在页缓存里
                except OSError:
                    pass
            import os

            os.replace(tmp, path)          # 原子改名
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def load(self, run_id: str) -> RunState | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        try:
            return RunState.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            # 坏掉的检查点不能连累主流程：宁可当"没有"，也不要崩。
            return None

    def list_run_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("*.json"))

    def delete(self, run_id: str) -> None:
        self._path(run_id).unlink(missing_ok=True)


# ===========================================================================
# 四、结构化日志
# ===========================================================================
class EventLog:
    """结构化日志：一行一个 JSON 事件。

    为什么不用 `print("出错了")`？
        因为生产事故的第一个问题永远是：
            "**是哪一次运行的哪一步失败了？**"
        自由文本日志答不了这个问题（只能靠人肉 grep + 猜），
        结构化日志可以（按 run_id 一过滤，时间线直接出来）。

    字段设计（每一条都对应一个真实排障场景）：
        ts      时间戳（排障要还原时序）
        run_id  哪一次运行  —— 最重要的关联键，全链路追踪的种子
        step    第几步      —— 定位"卡在哪一步"
        event   事件类型    —— 机器可聚合（step_end 平均耗时？error 占比？）
        ms      耗时        —— 性能回归的第一手证据
        extra   附加上下文  —— 工具名、错误类型、路由决策……

    真实系统里这些字段直接进 OTel / ELK，并且 run_id 会作为 trace_id
    透传到所有下游调用（第 10 章的可观测性在这里闭环）。
    """

    def __init__(self, stream: list[dict[str, Any]] | None = None, echo: bool = False) -> None:
        self.records: list[dict[str, Any]] = stream if stream is not None else []
        self.echo = echo
        from .virtual import real_clock

        self.clock = real_clock

    # ---- 写 -----------------------------------------------------------
    def emit(self, event: str, *, run_id: str = "", step: int = 0, ms: float = 0.0,
             level: str = "info", **extra: Any) -> dict[str, Any]:
        rec = {
            "ts": round(self.clock(), 4),
            "run_id": run_id,
            "step": step,
            "event": event,
            "ms": round(float(ms), 2),
            "level": level,
            **{k: _safe_json(v) for k, v in extra.items()},
        }
        self.records.append(rec)
        if self.echo:
            print("  " + self.to_line(rec))
        return rec

    # ---- 读 -----------------------------------------------------------
    @staticmethod
    def to_line(rec: dict[str, Any]) -> str:
        """渲染成一行紧凑 JSON（就是它会写进日志文件的样子）。"""
        return json.dumps(rec, ensure_ascii=False, separators=(", ", ": "))

    def by_run(self, run_id: str) -> list[dict[str, Any]]:
        """★ 排障的核心操作：把一次运行的事件全部捞出来，按发生顺序看。"""
        return [r for r in self.records if r["run_id"] == run_id]

    def where_failed(self, run_id: str) -> dict[str, Any] | None:
        """回答那个价值百万的问题：**run X 是哪一步失败的？**"""
        for rec in self.by_run(run_id):
            if rec["level"] in {"error", "fatal"}:
                return rec
        return None

    def counts_by_event(self, run_id: str = "") -> dict[str, int]:
        out: dict[str, int] = {}
        for rec in (self.by_run(run_id) if run_id else self.records):
            out[rec["event"]] = out.get(rec["event"], 0) + 1
        return out

    def timeline(self, run_id: str) -> list[str]:
        """人读的时间线（就是 README/demo 里展示的那种）。"""
        lines = []
        for rec in self.by_run(run_id):
            extras = {k: v for k, v in rec.items()
                      if k not in {"ts", "run_id", "step", "event", "ms", "level"}}
            tail = (" " + json.dumps(extras, ensure_ascii=False)) if extras else ""
            lines.append(f"[{rec['event']:<16}] step={rec['step']:<2} {rec['ms']:>7.1f}ms{tail}")
        return lines

    def __len__(self) -> int:
        return len(self.records)


# ===========================================================================
# 五、幂等缓存
# ===========================================================================
class IdempotencyCache:
    """幂等键 → 结果。

    幂等键从哪来？两种都要有，作用不同：
        1. **客户端提供**（HTTP 头 `Idempotency-Key`）—— 防"用户重复点击 / 网络重发"；
        2. **服务端推导**（业务语义的指纹，如 hash(user_id + 任务内容)）——
           防"同一个业务意图被不同的 request_id 提交了两次"。
    只做第 1 种会漏：客户端换了 request_id 就绕过去了；
    只做第 2 种会误伤：用户今天和明天各让我"算一次 (12+8)*3/4"，
    其实那两次都该算（虽然结果一样，但语义上是两次请求）。

    生产上的四个必备细节：
        * 结果里要带 `replayed=True`，让调用方知道"你拿到的是回声，不是新的执行"；
        * 记录 `first_run_id`，出问题能回溯到第一次执行的那条轨迹；
        * 有容量上限（LRU）—— 这个实现了
        * 有 TTL —— **没实现**（`stored_at` 已留好，加惰性过期是 README 练习 2；
          不默认给 TTL，是因为"TTL 该设多长"是业务问题，没有通用答案）
    """

    def __init__(self, max_entries: int = 256) -> None:
        self._data: dict[str, dict[str, Any]] = {}
        self.max_entries = max_entries
        self.hits = 0

    @staticmethod
    def fingerprint(*parts: str) -> str:
        """把任意几段文本压成一个稳定的短指纹。

        用 sha256 而不是内置 hash()：内置 hash 带随机盐（PYTHONHASHSEED），
        **跨进程不稳定** —— 进程 A 算出的键，进程 B 认不出来，
        于是"重启后幂等失效"，重复扣款就回来了。这是极隐蔽的一类 bug。
        """
        import hashlib

        joined = "\x1f".join(p.strip() for p in parts)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def cache_key(cls, idempotency_key: str, user_id: str, task: str) -> str:
        """把"客户端给的幂等键"和"业务上下文"绑在一起，得到真正的去重键。

        ★ 为什么不能直接拿客户端的 key 当缓存键？看这条真实事故链：
            客户端 A 用 Idempotency-Key: "retry-1" 发起"给 u_42 扣款 350 分"，
            结果被缓存下来了；
            十分钟后，**另一个用户**的客户端也用了 "retry-1"
            （它只是自己本地的重试计数器！）发起"给 u_9 扣款 900 分" ——
            缓存直接命中，返回"已完成扣款（第 1 笔，350 分）"。
            结果：u_9 的钱没扣，系统还告诉他扣了 350 分。

            关键认知：**幂等键是"命名空间内的唯一"，不是"全局唯一"。**
            客户端的键只在它自己的作用域里有意义，
            服务端必须把它和 (user_id, 业务意图) 拼起来才能当全局键用。
            这就是为什么设计幂等 API 时一定要问："这个 key 的作用域是什么？"
        """
        if not idempotency_key:
            return ""
        return cls.fingerprint("idem", user_id, idempotency_key, task)

    def get(self, key: str) -> dict[str, Any] | None:
        if not key:
            return None
        found = self._data.get(key)
        if found is None:
            return None
        self.hits += 1
        return copy.deepcopy(found)

    def put(self, key: str, *, run_id: str, answer: str, meta: dict[str, Any] | None = None) -> None:
        if not key:
            return
        self._data[key] = {
            "run_id": run_id,
            "answer": answer,
            "meta": dict(meta or {}),
            "stored_at": time.time(),
        }
        # 简易 LRU：超限就丢最早插入的那条（dict 保持插入顺序）
        while len(self._data) > self.max_entries:
            self._data.pop(next(iter(self._data)))

    def __len__(self) -> int:
        return len(self._data)

    def keys(self) -> Iterable[str]:
        return tuple(self._data)


# ===========================================================================
# 六、服务级指标
# ===========================================================================
class Metrics:
    """计数器。生产的四项黄金指标（延迟/流量/错误/饱和度）从这里起步。

    注意 counter 的命名要能直接回答一个运维问题：
        duplicates_blocked 高 → 客户端在重试，是不是超时设得太短？
        degraded_total 高     → 任务普遍跑不完，该扩容或缩预算了。
    """

    KEYS = (
        "submitted", "completed", "rejected_overload", "duplicates_blocked",
        "degenerate_blocked", "cached_hits", "degraded_total", "failed_total",
        "breaker_short_circuit", "resumed",
    )

    def __init__(self) -> None:
        self.counters: dict[str, int] = {k: 0 for k in self.KEYS}

    def incr(self, key: str, n: int = 1) -> int:
        self.counters[key] = self.counters.get(key, 0) + n
        return self.counters[key]

    def get(self, key: str) -> int:
        return self.counters.get(key, 0)

    def as_dict(self) -> dict[str, int]:
        return dict(self.counters)

    def render(self) -> list[str]:
        return [f"{k:<22}{v}" for k, v in self.counters.items() if v]
