"""虚拟时钟：让"超时"这件事变成**确定性可测**的。

------------------------------------------------------------
一句话本质：
    生产代码里最难测的不是逻辑，而是**时间**。
    `time.sleep` / 线程 / 真实网络都会让测试变成"碰运气"。
    解法：把"现在几点"抽成一个可以注入的对象。
------------------------------------------------------------

为什么这一章要单独写一个时钟？
    第 13 章要演示"任务超时后降级"。如果真用 `time.sleep(3)` 去等，
    会带来三个问题：
      1. 自检（run_checks）要跑 3 秒 —— 违反"< 1 秒"的课程契约；
      2. 结果不确定 —— CI 机器慢一点就可能变成"没超时"；
      3. 无法演示"熔断冷却 30 秒后恢复"这种场景（真等 30 秒？）。

    所以生产级测试的通用做法是 **注入时钟（Clock Injection）**：
        运行时代码只调用 `clock()` 拿当前时间，从不直接读系统时间。
        测试时换成一个"我说现在几点就几点"的 FakeClock。

    这不是教学玩具 —— Java 的 `java.time.Clock`、Go 的 `clockwork`、
    Python 的 `freezegun` 都是同一个思路。你手写的这 20 行就是它们的原理。

注意：默认时钟是**单调时钟** `time.perf_counter`，不是 `time.time()`。
    因为墙上时钟会被 NTP 校准、夏令时、手工改时间跳变，
    用它算"任务跑了多久"会出现负数。生产环境算 duration 一律用单调时钟。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from core.errors import BudgetExceeded

# 时钟的形态：调一次，返回一个"秒"（浮点）。单调、不会被系统改时间影响。
Clock = Callable[[], float]


def real_clock() -> float:
    """生产时钟：单调递增，用于计算耗时与判断超时。"""
    return time.perf_counter()


class FakeClock:
    """可以手动推进的假时钟 —— 只在教学与测试里用。

    真实代码里注入它，就能把"30 秒熔断冷却"压缩成"推进 30 秒"，
    测试瞬间完成且永远稳定。
    """

    def __init__(self, start: float = 1000.0) -> None:
        # 起始值故意不是 0：这样如果哪里误用了"时间戳是否为 0"做判断，会立刻暴露。
        self._now = float(start)

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        """把时间往前推 seconds 秒（可以为小数）。"""
        self._now += float(seconds)
        return self._now

    def advance_ms(self, ms: float) -> float:
        return self.advance(ms / 1000.0)

    @property
    def now(self) -> float:
        return self._now


# ---------------------------------------------------------------------------
# 预算（Deadline / Budget）
# ---------------------------------------------------------------------------
@dataclass
class Budget:
    """一次运行的资源预算：**墙上时间 + 步数**。

    为什么 Agent 必须带预算？
        一次 Agent run 的耗时是不可预测的（模型可能想 5 步，也可能想 50 步）。
        没有预算，一个卡住的请求就能占满连接池 → 拖垮整个服务。
        预算把"不可预测"变成"有界"。

    两个字段缺一不可：
        max_seconds —— 面向用户体验的承诺（"3 秒内必须给点东西"）
        max_steps   —— 面向成本的保护（第 01 章的 max_steps 在这里重新出现）

    `check()` 用 raise 而不是返回 bool：这样超时不能被"忘了判断"悄悄吞掉。
    """

    max_seconds: float = 30.0
    max_steps: int = 8
    clock: Clock = field(default=real_clock)
    started_at: float = field(init=False)

    def __post_init__(self) -> None:
        self.started_at = self.clock()

    def elapsed(self) -> float:
        return self.clock() - self.started_at

    def remaining(self) -> float:
        return max(0.0, self.max_seconds - self.elapsed())

    def expired(self) -> bool:
        return self.elapsed() >= self.max_seconds

    def check(self, *, about_to: str = "继续执行", reserve: float = 0.0,
              signal: type[BaseException] | None = None) -> None:
        """超时就抛 BudgetExceeded。

        参数 reserve 是"预留量"：如果剩下的时间连**下一步的最小开销**都不够，
        那么现在就该收手 —— 与其做到一半被打断，不如现在体面降级。

        参数 signal 允许调用方换一个"异常类型"来抛（默认就是 BudgetExceeded）。
        为什么需要这个开关？见 runtime.py 里 _BudgetSignal 的注释：
        Agent 主循环的兜底 `except AgentError` 会把 BudgetExceeded 翻译成普通错误，
        所以引擎需要用一个"兜不住"的信使类型把它送出来，再翻译回 BudgetExceeded。
        这是**依赖注入**思想用在异常类型上：谁来决定"怎么中断"，
        由调用方按自己的错误处理结构来决定，而不是硬编码在预算里。
        """
        left = self.max_seconds - self.elapsed()
        if left <= reserve:
            message = (
                f"预算耗尽：已用 {self.elapsed():.2f}s / 上限 {self.max_seconds:.2f}s，"
                f"剩余 {max(0.0, left):.2f}s 不足以{about_to}"
            )
            raise (signal or BudgetExceeded)(message)

    def snapshot(self) -> dict[str, float]:
        return {
            "elapsed_s": round(self.elapsed(), 3),
            "remaining_s": round(self.remaining(), 3),
            "max_seconds": self.max_seconds,
            "max_steps": self.max_steps,
        }
