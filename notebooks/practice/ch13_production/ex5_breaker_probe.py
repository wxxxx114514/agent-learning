r"""第 13 章 · 练习 5 / 5 · 给熔断器补上「半开只放一个探测」，并自证它成立

【要做什么】
  **给熔断器补上「半开只放一个探测」的保证性测试（本章代码已经实现，请自证）。**

  写一段代码证明：进入 `HALF_OPEN` 之后连续调用 5 次 `allow()`，**只有第 1 次返回 True**。

  再想一步：如果把 `probe_in_flight` 的复位删掉，会发生什么？
  为什么说这是熔断器最常见的实现 bug？

【已经给你了】
  · 第 13 章真正的熔断器：`CircuitBreaker`（runtime.py）：三态 + `allow()` / `record_success()` /
    `record_failure()` / `retry_after()` / `_to(state, why)`
  · `FakeClock`（virtual.py）：把「冷却 30 秒」压缩成「推进 30 秒」
  · `prove(类)`：跑完「跳闸 → 冷却 → 探测 → 再探测 → 恢复」的完整剧本
  · `NoResetBreaker`：故意删掉复位的对照版本（整份都写好了，不用改）

  ⚠️ 别搞混两份实现：`stages/stage13_production/runtime.py` 里的 `CircuitBreaker`
     **没有** `probe_in_flight`（它在 HALF_OPEN 下无条件放行）；
     `notebooks/nb12_ch13.py` 里手写的那份**有**。本练习就是把那份做法移植到框架版上。

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch13_production\ex5_breaker_probe.py
  3. 验收本章：py scripts\run_all_checks.py 13
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage13_production.runtime import CircuitBreaker  # noqa: E402
from stages.stage13_production.virtual import FakeClock  # noqa: E402

THRESHOLD = 3          # 连续失败几次就跳闸
COOLDOWN_S = 30.0      # 断开后冷却多久才放探测
PROBE_CALLS = 5        # 半开之后连续 allow() 几次 —— 期望只有 1 次放行


def table(headers: list[str], rows: list[list[str]], indent: int = 2) -> None:
    """极简表格：按**显示宽度**对齐，中日韩字符占 2 列（已经写好，不用改）。

    课程零第三方依赖，所以不引入 rich / tabulate —— 十几行自己画一个就够。
    """

    def width(text: str) -> int:
        return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)

    def pad(text: str, n: int) -> str:
        return text + " " * max(0, n - width(text))

    widths = [max([width(h)] + [width(r[i]) for r in rows]) for i, h in enumerate(headers)]
    print(" " * indent + "  ".join(pad(h, widths[i]) for i, h in enumerate(headers)))
    print(" " * indent + "  ".join("-" * w for w in widths))
    for r in rows:
        print(" " * indent + "  ".join(pad(c, widths[i]) for i, c in enumerate(r)))


class SingleProbeBreaker(CircuitBreaker):
    """给框架版熔断器补上「半开只放一个探测」。

    三态语义（父类的 `allow()` 少了下半截，我们在这里补全）：
        CLOSED     正常放行，统计失败
        OPEN       一律拒绝，不再打下游（快速失败）
        HALF_OPEN  只放**一个**探测：成了 → 恢复；不成 → 重新计时
    """

    def __init__(self, *args, **kwargs) -> None:
        """已经写好，不用改。"""
        super().__init__(*args, **kwargs)
        self.probe_in_flight = False        # 半开状态下，是否已经有一个探测在路上

    # =======================================================================
    # ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
    # =======================================================================
    def allow(self) -> bool:
        """TODO ① ── 现在能调用下游吗？（三态放行规则）

        要求：
          · CLOSED            → True
          · OPEN 还没到冷却   → False，并且 `self.short_circuited += 1`
          · OPEN 冷却到了     → 迁移到 HALF_OPEN（用现成的 `self._to(HALF_OPEN, 为什么)`），
                                **并且把探测标志复位** —— 少了这一行，熔断器就永远卡住了
          · HALF_OPEN 且已有探测在路上 → False，同样计一次 short_circuited
          · HALF_OPEN 且没有探测在路上 → 放这一个过去（把标志置 True），返回 True

        提示：写成一个「先处理 OPEN 的转换，再统一判断探测标志」的流程最省事；
              注意从 OPEN 转过来之后**不要**直接 return True，要落到下面那段探测判断里。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ①  allow")
        # ↑↑↑ 你的答案 ↑↑↑

    def record_success(self) -> None:
        """TODO ② ── 探测成功：交给父类恢复状态，然后**复位探测标志**。

        要求：`super().record_success()`（它会 HALF_OPEN → CLOSED、failures 清零），
              然后 `self.probe_in_flight = False`。
        提示：不复位 → 下一次进入半开时标志还是 True → 永远放不出探测。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ②  record_success")
        # ↑↑↑ 你的答案 ↑↑↑

    def record_failure(self, reason: str = "") -> None:
        """TODO ③ ── 记录失败：**先复位探测标志**，再交给父类（它会重新计时 / 重新跳闸）。

        要求：先 `self.probe_in_flight = False`，再 `super().record_failure(reason)`。
        提示：成功、失败**两条路径都必须复位** —— 只复位一条是这类 bug 最常见的写法。
        """
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ③  record_failure")
        # ↑↑↑ 你的答案 ↑↑↑
    # =======================================================================
    # ↑↑↑ 你的答案 ↑↑↑
    # =======================================================================


class NoResetBreaker(CircuitBreaker):
    """对照用的坏版本：和上面一模一样，只是**故意删掉了三处复位**（不用改，看结果就行）。

    ★ 这类「状态机卡死」比「状态机抖动」更危险：
      抖动有人投诉，卡死没人发现 —— 直到下游早就恢复了，你的流量却再也没有回去。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.probe_in_flight = False

    def allow(self) -> bool:
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            if self.clock() - self.opened_at >= self.cooldown_s:
                self._to(self.HALF_OPEN, "冷却结束，放一个探测请求过去")
                # ★ 少了 self.probe_in_flight = False
            else:
                self.short_circuited += 1
                return False
        if self.probe_in_flight:
            self.short_circuited += 1
            return False
        self.probe_in_flight = True
        return True

    def record_success(self) -> None:
        super().record_success()
        # ★ 少了 self.probe_in_flight = False

    def record_failure(self, reason: str = "") -> None:
        # ★ 少了 self.probe_in_flight = False
        super().record_failure(reason)


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   把 probe_in_flight 的复位删掉会发生什么？为什么它是熔断器最常见的实现 bug？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def prove(breaker_cls) -> dict:
    """跑完整个剧本（已经写好，不用改）。

    跳闸 → 冷却中 → 冷却结束连续 allow() 5 次 → 探测失败 → 再冷却 → 再 5 次 → 探测成功。
    全程真实耗时 0 秒（用 FakeClock 推进）。
    """
    clock = FakeClock()
    breaker = breaker_cls(threshold=THRESHOLD, cooldown_s=COOLDOWN_S, clock=clock)

    for _ in range(THRESHOLD):
        breaker.record_failure("下游 500")
    opened = breaker.state
    during = [breaker.allow() for _ in range(3)]          # 冷却中：应该全挡

    clock.advance(COOLDOWN_S)
    first_probe = [breaker.allow() for _ in range(PROBE_CALLS)]

    if any(first_probe):          # ★ 探测真的放出去了，才会有一个结果回来
        breaker.record_failure("探测还是失败")
    clock.advance(COOLDOWN_S)
    second_probe = [breaker.allow() for _ in range(PROBE_CALLS)]

    if any(second_probe):         # ★ 放不出探测 → 就永远等不到「成功」这个事件
        breaker.record_success()
    recovered_state = breaker.state
    recovered_allow = breaker.allow()

    clock.advance(10_000)                                  # 很久以后
    long_after = [breaker.allow() for _ in range(3)]
    return {"opened": opened, "during": during, "first_probe": first_probe,
            "second_probe": second_probe, "recovered_state": recovered_state,
            "recovered_allow": recovered_allow, "long_after": long_after,
            "short_circuited": breaker.short_circuited, "trips": breaker.trips,
            "events": list(breaker.events)}


def mark(hits: int) -> str:
    return f"{hits} 个放行" + (" ✅" if hits == 1 else " ❌")


def main() -> int:
    try:
        mine = prove(SingleProbeBreaker)

        print(f"    剧本：连续失败 {THRESHOLD} 次 → 冷却 {COOLDOWN_S:.0f}s → "
              f"连续 allow() {PROBE_CALLS} 次（全程真实耗时 0 秒）")
        print()
        print(f"    ① 跳闸后状态：{mine['opened']!r}，冷却中 3 次 allow() → "
              f"{sum(mine['during'])} 个放行（期望 0）")
        print(f"    ② 冷却结束后的 5 次 allow()：{mine['first_probe']}")
        print(f"       → {mark(sum(mine['first_probe']))} ← 这就是这道题要证明的那句话")
        print(f"    ③ 探测失败、再冷却 30s 后的 5 次 allow()：{mine['second_probe']}")
        print(f"       → {mark(sum(mine['second_probe']))}（失败路径也必须复位）")
        print(f"    ④ 探测成功 → 状态 {mine['recovered_state']!r}，"
              f"再 allow() → {mine['recovered_allow']}（恢复正常）")
        print(f"    ⑤ 再推进 10000 秒：{mine['long_after']}（CLOSED 下正常放行）")
        print(f"       累计挡掉 {mine['short_circuited']} 个请求，跳闸 {mine['trips']} 次")
        print()

        assert mine["opened"] == CircuitBreaker.OPEN, "失败到阈值必须先跳闸"
        assert sum(mine["during"]) == 0, "冷却期一次都不许放行"
        assert sum(mine["first_probe"]) == 1, \
            f"半开必须只放一个探测，实际放了 {sum(mine['first_probe'])} 个"
        assert mine["first_probe"][0] is True, "第 1 次必须放行（否则永远恢复不了）"
        assert sum(mine["second_probe"]) == 1, \
            "探测失败后的下一次冷却，必须还能再放一个（失败路径也要复位）"
        assert mine["recovered_state"] == CircuitBreaker.CLOSED and mine["recovered_allow"], \
            "探测成功必须回到 CLOSED 并正常放行"
        assert all(mine["long_after"]), "恢复之后不该再有任何拦截"

        # 对照：删掉复位的版本
        broken = prove(NoResetBreaker)
        rows = [["你的实现", mark(sum(mine["first_probe"])), mark(sum(mine["second_probe"])),
                 f"{mine['recovered_state']} / {mine['recovered_allow']}",
                 f"{sum(mine['long_after'])} 个放行 ✅"],
                ["删掉复位的版本", mark(sum(broken["first_probe"])),
                 mark(sum(broken["second_probe"])),
                 f"{broken['recovered_state']} / {broken['recovered_allow']} ❌",
                 f"{sum(broken['long_after'])} 个放行 ❌"]]
        table(["版本", "首次冷却后 5 次", "再冷却后 5 次", "探测成功后", "再等 10000 秒"], rows)
        print()
        assert sum(broken["second_probe"]) == 0, "对照版应该已经卡死"
        assert not any(broken["long_after"]), "对照版应该永远放不出请求"
        assert broken["recovered_state"] == CircuitBreaker.HALF_OPEN, \
            "对照版会永远卡在 HALF_OPEN"
        print("    ★ 删掉复位 → 熔断器**永远卡在半开**：放不出探测，也就不可能恢复成 CLOSED，")
        print("      整个下游从此被永久熔断 —— 而且它不报警、不掉请求量（因为压根没请求了）。")
        print("    ★ 所以「成功和失败两条路径都要复位」这句话，必须由一条断言钉住 ——")
        print("      就像你刚刚写的那两行自证。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print()
    print(f"    你的结论：{CONCLUSION or '（还没写 —— 写在文件里的 CONCLUSION 那一行）'}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
