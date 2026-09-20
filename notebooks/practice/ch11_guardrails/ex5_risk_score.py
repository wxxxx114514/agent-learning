r"""第 11 章 · 练习 5 / 5 · 把审计日志变成告警（进阶）

【要做什么】
  写一个 `risk_score(events)`：
  ① 同一来源 5 分钟内触发 3 次以上拦截 → 高危；
  ② `delete_all_data` 被调用 1 次 → 立刻告警（**无论是否被拒**）。

【已经给你了】
  risk_score(events)          ★ 你要写的函数：输入审计事件，输出高危规则名
  make_event(seq, layer, action, rule, target, detail)   快速造一条审计事件
  five_minute_burst()         同一来源 5 分钟内触发 4 次拦截（>3，应当高危）
  slow_burst()                同一来源跨 20 分钟的 4 次拦截（不构成 5 分钟窗口）
  real_delete_attempt()       真实的一次"尝试删库"：调用被 deny 档拦下，审计里有记录
  AuditEvent                 审计记录（字段：seq / layer / action / rule / target / detail）
  BURST_LAYERS / BURST_TARGET / DELETE_TOOL   本节用到的常量

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch11_guardrails\ex5_risk_score.py
  3. 验收本章：py scripts\run_all_checks.py 11
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from datetime import datetime, timedelta                     # noqa: E402

from core.console import bullet, kv, note, warn              # noqa: E402
from core.message import ToolCall                            # noqa: E402
from stages.stage11_guardrails.demo import (                 # noqa: E402
    ATTACK_DIRECT, AuditEvent, Guardrail, TOOL_POLICY, build_approval_hook, judge_attacks_guarded,
    sandbox_workspace,
)

DELETE_TOOL = "delete_all_data"
BURST_TARGET = "用户输入"
BURST_LAYERS = ("input", "permission", "tool_output")        # 哪几层算"拦截"
BLOCK_ACTIONS = ("block", "deny", "sanitize", "redact")      # 哪几种动作算"拦下来了"
BURST_LIMIT = 3                                              # ≥3 次 → 高危
WINDOW = timedelta(minutes=5)

BASE_TIME = datetime(2025, 1, 1, 9, 0, 0)


def make_event(seq: int, layer: str, action: str, rule: str, target: str,
               detail: str = "", *, seconds: float = 0.0) -> AuditEvent:
    """造一条审计事件。

    `seconds` 是相对 BASE_TIME 的偏移（用来构造"5 分钟窗口"这类时间条件）。
    `rule` 里会带上时间戳（ISO 格式），这样调度层不用改 AuditEvent 的结构也能做时间聚合。
    时间戳的写法：f"{rule}@{iso}" —— 例如 "ignore_instructions@2025-01-01T09:03:00"
    """
    stamp = (BASE_TIME + timedelta(seconds=seconds)).isoformat()
    return AuditEvent(seq=seq, layer=layer, action=action, rule=f"{rule}@{stamp}",
                      target=target, detail=detail)


def five_minute_burst() -> list[AuditEvent]:
    """同一来源 5 分钟内触发 4 次拦截（>3）→ 应当被判高危。"""
    return [make_event(i, "input", "block", "ignore_instructions", BURST_TARGET,
                       seconds=i * 30)                       # 0s / 30s / 60s / 90s
            for i in range(1, 5)]


def slow_burst() -> list[AuditEvent]:
    """同一来源的 4 次拦截，但每次相隔 6 分钟 → 不构成 5 分钟窗口。"""
    return [make_event(i, "input", "block", "ignore_instructions", BURST_TARGET,
                       seconds=i * 360)                      # 6min / 12min / 18min / 24min
            for i in range(1, 5)]


def real_delete_attempt() -> list[AuditEvent]:
    """真实跑一次「模型试图删库」，返回它留下的审计事件。

    deny 档会直接拒绝（审批人一张单都收不到），但审计里会留下一条 deny 记录 ——
    这正是第 ② 条规则要抓的东西。
    """
    with sandbox_workspace() as tmp:
        guard = Guardrail()
        hook = build_approval_hook(TOOL_POLICY, guard, lambda req: False)
        hook(ToolCall(DELETE_TOOL, {"confirm": "YES"}))
        return list(guard.events)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def risk_score(events: list[AuditEvent]) -> list[str]:
    """TODO ── 把审计日志变成告警：返回命中的高危规则名列表（没命中就返回空列表）。

    规则两条：

      ① "burst"：**同一来源 5 分钟内触发 3 次以上拦截** → 高危
         做法：先按 (target, 事件时间) 归组，再看任意一个 5 分钟窗口里的拦截次数。
         事件的字段是 `e.layer / e.action / e.rule / e.target / e.detail`，
         时间戳藏在 rule 里：`e.rule` 形如 "ignore_instructions@2025-01-01T09:03:00"。
             提示：rule_name, _, stamp = e.rule.partition("@")
                   when = datetime.fromisoformat(stamp)
         筛选条件：e.target 相同、e.action in BLOCK_ACTIONS、e.layer in BURST_LAYERS
         计数方式（最朴素也最好懂）：对每条事件 t，
             窗口内 = [x for x in 同来源的拦截事件 if timedelta(0) <= x.when - t.when <= WINDOW]
             如果 len(窗口内) >= BURST_LIMIT → 命中 "burst"
         （注意：`>= BURST_LIMIT` 里的 BURST_LIMIT=3 —— 题目说「3 次以上」，
           在告警语境里就是「达到 3 次就要看」，宁可早报也不要漏报。）

      ② "delete_attempt"：`delete_all_data` 被调用 1 次 → 立刻告警（**无论是否被拒**）
         筛选条件：`DELETE_TOOL in e.target` —— 不要求 action 是 allow，
         被拒（action='deny'）同样要告警。
             ★ 为什么？因为「有人尝试删库」这件事本身就是情报：
               要么有人在攻击，要么有人写错了代码 —— 两种都值得立刻知道。

    返回值：命中的规则名列表，例如 ["burst", "delete_attempt"]；按固定顺序 ["burst",
    "delete_attempt"] 返回（先报批量攻击，再报单次高危）。

    提示（卡住了再看）：
        ★ 别用 `e.detail` 里的自然语言去做判断 —— 结构化字段（layer/action/rule/target）
          才能被程序聚合。这正是第 10 章「轨迹要落库、要结构化」的同一个道理。
        ★ 时间戳放在 rule 里是本节的教学简化。生产里 AuditEvent 会有一个
          `ts: datetime` 字段，而且日志是**只追加、不可篡改、异地留存**的。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 5 · TODO  risk_score")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def report(events: list[AuditEvent], label: str) -> list[str]:
    hits = risk_score(events)
    print(f"      {label:<44}→ {hits or '（无告警）'}")
    return hits


def check_5() -> None:
    if not isinstance(risk_score([]), list):
        raise AssertionError("risk_score 必须返回列表（哪怕是空列表）")

    print("    三种场景的告警结果：")
    burst = report(five_minute_burst(), "同一来源 5 分钟内 4 次拦截")
    slow = report(slow_burst(), "同一来源 4 次拦截，但每次相隔 6 分钟")
    delete_events = real_delete_attempt()
    delete = report(delete_events, f"模型试图调用 {DELETE_TOOL}（被 deny 档拦下）")
    print()

    if "burst" not in burst:
        raise AssertionError("5 分钟内 4 次拦截必须报 burst —— 规则 ① 没写对")
    if "burst" in slow:
        raise AssertionError("相隔 6 分钟的拦截不构成 5 分钟窗口，不该报 burst")
    if "delete_attempt" not in delete:
        raise AssertionError(
            f"「有人尝试删库」必须立刻告警（无论是否被拒）—— 规则 ② 没写对；"
            f"这次的事件是 {[(e.layer, e.action, e.target) for e in delete_events]}")
    if "delete_attempt" in burst or "delete_attempt" in slow:
        raise AssertionError("普通注入拦截不该误报 delete_attempt")
    if "burst" in delete:
        raise AssertionError("单次删库尝试不该被算成 burst（它只有 1 条事件）")

    # 不能只认 allow：被拒绝的调用同样要告警
    denied_only = [e for e in delete_events if e.action == "deny"]
    if not denied_only:
        raise AssertionError("这次删库尝试本来应该是被 deny 掉的，先检查环境")
    if "delete_attempt" not in risk_score(denied_only):
        raise AssertionError("只喂给『被拒绝』的那条事件也必须告警 —— 拒绝 ≠ 没发生")

    kv("规则 ①", f"5 分钟窗口内 ≥{BURST_LIMIT} 次拦截 → burst")
    kv("规则 ②", f"1 次 {DELETE_TOOL} 尝试 → delete_attempt（无论是否被拒）")
    kv("审计事件统计", f"共 {len(delete_events)} 条："
                       f"{sorted({e.layer for e in delete_events})}")
    print()

    # 顺手看一眼"真实的攻击流量"会长什么样
    with sandbox_workspace() as tmp:
        guard = Guardrail()
        judge_attacks_guarded(tmp, guard, approver=lambda req: False)
        layers = sorted({e.layer for e in guard.events})
        kv("跑完整套攻击后的审计", f"{len(guard.events)} 条事件，覆盖层 {layers}")
        kv("  其中被拦下的", f"{sum(1 for e in guard.events if e.action in BLOCK_ACTIONS)} 条")
    print()
    note("★ 审计日志的四个用途：向用户解释为什么被拒 / 事后复盘攻击怎么进来的 /")
    note("  聚合告警（同一来源反复触发 → 封禁）/ 合规审计（谁批准了什么高危操作）")
    warn("★ 为什么第 ② 条要「无论是否被拒」都告警？因为「有人尝试删库」本身就是情报 ——")
    warn("  它意味着要么有人在攻击，要么有人写错了代码。两种都值得立刻知道。")
    bullet("被拒绝 ≠ 没发生：deny 记录是攻击画像里最有价值的那一条")
    bullet("聚合必须基于结构化字段（layer/action/rule/target），不是自然语言")
    bullet("生产要求：审计日志只追加、不可篡改、异地留存，而且本身也要脱敏")


def main() -> int:
    try:
        check_5()
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
