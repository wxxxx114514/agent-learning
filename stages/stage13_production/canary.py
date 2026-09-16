"""灰度发布与自动回滚 —— 只在生产环境才存在的那个问题。

------------------------------------------------------------
一句话本质：
    灰度 = **让新旧两个版本同时接客，用真实流量验证新版本**。
    回滚 = **在用户大面积受影响之前，把流量切回去**。
    没有"自动回滚触发条件"的灰度发布，等于把线上当测试环境。
------------------------------------------------------------

为什么 Agent 系统特别需要灰度？
    因为 Agent 的输出是**概率性的**。传统服务改代码，单元测试能覆盖 90%；
    Agent 改了提示词 / 换了模型 / 加了工具，你**没法靠单元测试证明它没变坏**，
    只能靠真实流量上的指标（错误率、工具失败率、用户点踩率）来判定。
    所以第 10 章的评估集（离线） + 本章的灰度（在线）是一对：离线挡住明显的退化，
    在线兜住剩下的那部分。

路由怎么分？
    不能用 `random()` —— 同一次请求重试时可能被分到不同版本，
    导致"用户刷新一下答案就变了"。必须**按某个稳定键做哈希**：
        bucket = hash(request_id) % 100
        bucket < rollout_percent ? canary : stable
    这样同一个请求永远落进同一个版本（**粘性**），
    也方便你把某一次出问题的请求"钉"在某个版本上复现。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable

from core.llm import LLM, LLMError, LLMResponse
from core.mock_llm import as_mock_response

# 每个版本的 Agent 实现：给一个 request_id，返回 (回答, 是否失败)。
# 真实系统里它就是"两个不同镜像的 Pod"，我们这里用一个可注入的函数代替。
Implementation = Callable[[str], tuple[str, bool]]


@dataclass
class CanaryConfig:
    """看板上的那几个旋钮。

    每一条都对应一个真实的运维决策：
        rollout_percent   先 5% 还是先 50%？影响面越大越要小步走
        error_threshold   错误率超过多少算"坏了"？通常取基线的 2~3 倍
        min_samples       样本太少时比例没有统计意义（1 个请求失败 = 100%）
        lookback_n        只看最近 N 个请求，避免几天前的历史把它拖住
    """

    rollout_percent: int = 40
    error_threshold: float = 0.25
    min_samples: int = 4
    lookback_n: int = 20
    auto_rollback: bool = True


@dataclass
class VersionStats:
    """一个版本的在线指标（灰度决策的唯一依据）。"""

    name: str
    total: int = 0
    errors: int = 0
    latencies: list[float] = field(default_factory=list)
    recent: list[bool] = field(default_factory=list)   # 最近 N 次的成败

    def record(self, ok: bool, ms: float = 0.0, lookback: int = 20) -> None:
        self.total += 1
        self.latencies.append(ms)
        self.recent.append(bool(ok))
        if len(self.recent) > lookback:
            self.recent = self.recent[-lookback:]
        if not ok:
            self.errors += 1

    def error_rate(self) -> float:
        """总体错误率（值班看板上的数字）。"""
        return self.errors / self.total if self.total else 0.0

    def window_error_rate(self, window: int = 20) -> float:
        """滑动窗口错误率（灰度决策用的数字）。

        为什么要用窗口而不是总错误率？
            因为新版本刚上线时，总错误率被"启动前的健康历史"稀释了，
            你会眼睁睁看着错误率从 0.1% 慢慢爬，等它超过阈值时已经烧了一片。
            窗口对**最近**的行为敏感，能让你早 10 分钟发现问题。
        """
        recent = self.recent[-window:]
        return sum(1 for ok in recent if not ok) / len(recent) if recent else 0.0

    def p95_ms(self) -> float:
        if not self.latencies:
            return 0.0
        ordered = sorted(self.latencies)
        idx = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return ordered[idx]

    def render(self) -> str:
        return (f"{self.name:<8} 请求 {self.total:>3} | 错误 {self.errors:>2} "
                f"({self.error_rate()*100:>5.1f}%) | 窗口错误率 {self.window_error_rate()*100:>5.1f}% "
                f"| p95 {self.p95_ms():.0f}ms")


class CanaryRouter:
    """灰度路由器：决定"这个请求走哪个版本"，并在新版本变坏时自动回滚。"""

    def __init__(self, stable: Implementation, canary: Implementation,
                 cfg: CanaryConfig | None = None, clock: Callable[[], float] | None = None) -> None:
        self.stable = stable
        self.canary = canary
        self.cfg = cfg or CanaryConfig()
        self.enabled = True                     # 灰度开关（feature flag）
        self.stats: dict[str, VersionStats] = {"stable": VersionStats("stable"),
                                              "canary": VersionStats("canary")}
        from .virtual import real_clock

        self.clock = clock or real_clock
        self.rollback_reason = ""
        self.rollback_at = 0.0
        self.audit: list[str] = []              # 每一次路由决策都要留痕（合规要求）

    # ---- 路由决策 -----------------------------------------------------
    def bucket(self, request_id: str) -> int:
        """把 request_id 稳定地映射到 0~99 的一个桶。

        用 sha256 而不是内置 hash()：内置 hash 带随机盐、跨进程不一致，
        会导致"同一个请求在 A 机器走 stable、在 B 机器走 canary" ——
        灰度比例会变成一锅粥，而且实验数据彻底不可信。
        """
        digest = hashlib.sha256(request_id.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) % 100

    def pick(self, request_id: str) -> str:
        if not self.enabled or self.cfg.rollout_percent <= 0:
            return "stable"
        return "canary" if self.bucket(request_id) < self.cfg.rollout_percent else "stable"

    # ---- 处理一个请求 -------------------------------------------------
    def handle(self, request_id: str) -> dict[str, Any]:
        version = self.pick(request_id)
        impl = self.canary if version == "canary" else self.stable
        t0 = self.clock()
        try:
            answer, failed = impl(request_id)
            error = "" if not failed else (answer or "下游返回失败")
        except Exception as exc:                 # 版本实现抛异常也算失败，绝不能漏出去
            answer, failed, error = "", True, f"{type(exc).__name__}: {exc}"
        ms = (self.clock() - t0) * 1000
        self.record(version, ok=not failed, ms=ms)
        self.audit.append(f"req={request_id} bucket={self.bucket(request_id):>2} → {version}"
                          + ("（失败）" if failed else ""))
        return {"request_id": request_id, "version": version, "answer": answer,
                "failed": failed, "error": error, "ms": round(ms, 2)}

    # ---- 指标 + 自动回滚 ----------------------------------------------
    def record(self, version: str, *, ok: bool, ms: float = 0.0) -> None:
        st = self.stats[version]
        st.record(ok, ms, lookback=self.cfg.lookback_n)
        self._maybe_rollback()

    def _maybe_rollback(self) -> None:
        """**自动回滚**：唯一正确的触发方式是"由指标驱动"，而不是"由人盯着"。"""
        if not self.enabled or not self.cfg.auto_rollback:
            return
        canary = self.stats["canary"]
        if canary.total < self.cfg.min_samples:
            return                       # 样本不足，比例没有统计意义，先别急着回滚
        rate = canary.window_error_rate(self.cfg.lookback_n)
        if rate <= self.cfg.error_threshold:
            return
        self.enabled = False
        self.rollback_at = self.clock()
        self.rollback_reason = (
            f"新版本窗口错误率 {rate*100:.1f}% 超过阈值 {self.cfg.error_threshold*100:.0f}%"
            f"（样本 {canary.total}），已自动回滚到 stable"
        )
        self.audit.append(f"[{self.rollback_at:.2f}s] AUTO-ROLLBACK: {self.rollback_reason}")

    # ---- 观测 ---------------------------------------------------------
    def seed_canary_window(self, ok: bool, times: int = 1, ms: float = 8.0) -> None:
        """预置一段"新版本上线前窗口内的历史"（演示用；真实里这段是时间攒出来的）。

        为什么演示需要它？因为 min_samples 这个护栏会拦住"1 个请求失败就回滚"，
        而教学里我们不想真的打 20 个请求。预置历史 = 模拟"灰度已经跑了一会儿"。
        """
        for _ in range(times):
            self.stats["canary"].record(ok, ms, lookback=self.cfg.lookback_n)

    def report(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rollout_percent": self.cfg.rollout_percent,
            "stable": self.stats["stable"].render(),
            "canary": self.stats["canary"].render(),
            "rolled_back": not self.enabled,
            "rollback_reason": self.rollback_reason,
            "audit_tail": self.audit[-4:],
        }


# ===========================================================================
# 把路由器接进 Agent：一个"会选版本"的假模型
# ===========================================================================
class VersionedLLM(LLM):
    """按灰度决策返回不同质量的模型输出 —— 让 demo 能端到端跑一遍灰度。

    为什么要在 LLM 这一层做文章？
        因为换模型（stable 用旧模型 / canary 用新模型）正是最常见的灰度场景。
        把它做成一个 LLM 装饰器，上层 Agent 代码**一行都不用改** ——
        这就是"抽象层"的价值（第 01 章埋下的伏笔在这里回收）。
    """

    name = "versioned"

    def __init__(self, request_id: str, router: CanaryRouter, *,
                 stable_text: str = "Final Answer: 这是 stable 版本的答案。",
                 canary_fail: bool = False, model: str = "mock-versioned") -> None:
        super().__init__(model)
        self.request_id = request_id
        self.router = router
        self.stable_text = stable_text
        self.canary_fail = canary_fail

    def _complete(self, messages, **kwargs: Any) -> LLMResponse:
        version = self.router.pick(self.request_id)
        self.model = f"mock-{version}"
        if version == "canary" and self.canary_fail:
            raise LLMError("新版本模型返回 500（模拟灰度中的坏版本）")
        text = self.stable_text if version == "stable" else "Final Answer: 这是 canary 版本的答案。"
        return as_mock_response(text, self.model)


__all__ = ["CanaryConfig", "CanaryRouter", "VersionStats", "VersionedLLM", "Implementation"]
