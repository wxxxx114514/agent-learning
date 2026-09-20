r"""第 11 章 · 练习 1 / 5 · 打破护栏，观察会发生什么

【要做什么】
  把 `TOOL_POLICY["export_customers"]` 从 `TIER_APPROVAL` 改成 `TIER_AUTO`，重跑第 ⑦ 节。

  预期：`越权外泄` 一行从 🟢 变成 🔴，审计日志里那条 `permission deny` 消失。

【已经给你了】
  break_export_policy()   造一份把 export_customers 降级成 auto 的权限表 —— ★ 你要写的第一个
  break_delete_policy()   造一份把 delete_all_data 降级成 approval 的权限表 —— ★ 第二个
  compare_export()        用指定的权限表跑「越权外泄」这条攻击，返回 (是否得手, 审计事件数, 描述)
  describe_deny_tier()    对 delete_all_data 走一次审批钩子，返回 (钩子返回值, 审批人收到几张单)
  ATTACK_EXFIL / ATTACK_WRITE / TOOL_POLICY / TIER_AUTO / TIER_APPROVAL / TIER_DENY  课程常量

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch11_guardrails\ex1_break_policy.py
  3. 验收本章：py scripts\run_all_checks.py 11
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn  # noqa: E402
from core.message import ToolCall  # noqa: E402
from stages.stage11_guardrails.demo import (  # noqa: E402
    ATTACK_EXFIL, ATTACK_WRITE, DELETE_SINK, EXPORT_SINK, TIER_APPROVAL, TIER_AUTO, TIER_DENY,
    TOOL_POLICY, ApprovalRequest, Guardrail, build_approval_hook, build_guard_registry,
    judge_attacks_guarded, sandbox_workspace,
)


def compare_export(policy: dict[str, str], approver=None) -> tuple[bool, int, str]:
    """用给定的权限表跑一遍「越权外泄」攻击。

    返回 (攻击是否得手, 审计事件条数, 说明)。
    approver 默认「永远拒绝」（模拟审批人不同意）。
    """
    say_no = approver or (lambda req: False)
    with sandbox_workspace() as tmp:
        guard = Guardrail(policy=dict(policy))
        outcomes = judge_attacks_guarded(tmp, guard, approver=say_no)
        hit = outcomes["越权外泄"].succeeded
        denies = [e for e in guard.events
                  if e.layer == "permission" and e.action == "deny"]
        detail = (f"副作用={'有' if EXPORT_SINK else '无'}　"
                  f"permission deny 事件 {len(denies)} 条　"
                  f"审批人被问了 {1 if guard.last_approval else 0} 次")
        return hit, len(guard.events), detail


def describe_deny_tier(policy: dict[str, str]) -> tuple[bool, int]:
    """对 `delete_all_data` 走一次审批钩子，返回 (钩子返回值, 审批人收到几张审批单)。

    这就是第 ④ 节场景 F 的那段代码：审批人是一个"来者不拒"的钩子。
    """
    with sandbox_workspace() as tmp:
        guard = Guardrail(policy=dict(policy))
        seen: list[ApprovalRequest] = []
        reg = build_guard_registry(tmp, guard)
        allowed = build_approval_hook(guard.policy, guard,
                                      lambda req: seen.append(req) or True, reg)(
            ToolCall("delete_all_data", {"confirm": "YES"}))
        return bool(allowed), len(seen)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def break_export_policy() -> tuple[dict[str, str], str]:
    """TODO ① ── 把 `export_customers` 从 `TIER_APPROVAL` 降级成 `TIER_AUTO`。

    两步：
      ① 复制一份权限表（**不要**改模块级的 TOOL_POLICY，那样整个进程都被你改了）：
             policy = dict(TOOL_POLICY)
             policy["export_customers"] = TIER_AUTO
      ② 返回 (policy, 一句话结论)：降级之后，「审批未通过，未产生任何副作用」
         这句话为什么就不成立了？

    提示（卡住了再看）：
        ★ auto 档意味着「只读、无副作用、自动放行」——
          可 export_customers 是**会外发数据**的工具，它根本不该拿这张通行证。
        ★ 降级之后审批钩子直接 return True，审批人**连单子都收不到**，
          模型一调工具，客户手机号就真的被导出了。护栏被绕过的样子就是这么平淡。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO ①  break_export_policy")
    # ↑↑↑ 你的答案 ↑↑↑


def break_delete_policy() -> tuple[dict[str, str], str]:
    """TODO ② ── 把 `delete_all_data` 从 `TIER_DENY` 降级成 `TIER_APPROVAL`。

    做法同上（改 `policy["delete_all_data"] = TIER_APPROVAL`）。

    然后回答一句话：为什么说「一个不可逆的高危操作只差一次点击就会被执行」？
    （提示：deny 档**没有审批入口** —— 它连问都不问；改成 approval 之后，
      它开始问人了，而现实生活中人是会点「同意」的。审批流程本身没有错，
      错的是"把不可逆的操作放进了可以商量的通道"。）

    返回 (policy, 一句话结论)。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO ②  break_delete_policy")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_1() -> None:
    # ---------- ① 越权外泄：审批 vs 降级 ----------
    hit_ok, _, detail_ok = compare_export(TOOL_POLICY)
    if hit_ok:
        raise AssertionError("动手之前「越权外泄」应该是被挡住的（审批被拒），先检查环境")

    policy_a, conclusion_a = break_export_policy()
    if policy_a.get("export_customers") != TIER_AUTO:
        raise AssertionError(
            f"export_customers 现在还是 {policy_a.get('export_customers')!r}；要改成 {TIER_AUTO!r}")
    if TOOL_POLICY["export_customers"] != TIER_APPROVAL:
        raise AssertionError("你把模块级的 TOOL_POLICY 改坏了 —— 要复制一份改，别动原件")
    if len(str(conclusion_a).strip()) < 10:
        raise AssertionError("① 还没写结论：为什么「审批未通过，未产生任何副作用」不成立了？")

    hit_bad, _, detail_bad = compare_export(policy_a)
    if not hit_bad:
        raise AssertionError("降级成 auto 之后攻击居然还被挡住了？检查一下你返回的 policy")

    print("    越权外泄（export_customers）· 审批人一律拒绝：")
    print(f"      {TIER_APPROVAL:<10}→ 攻击{'🔴 得手' if hit_ok else '🟢 被挡住'}　{detail_ok}")
    print(f"      {TIER_AUTO:<10}→ 攻击{'🔴 得手' if hit_bad else '🟢 被挡住'}　{detail_bad}")
    print()

    # ---------- ② 不可逆操作：deny vs approval ----------
    allowed_deny, asked_deny = describe_deny_tier(TOOL_POLICY)
    if allowed_deny or asked_deny:
        raise AssertionError("动手之前 deny 档应当直接拒绝、且审批人收到 0 张单，先检查环境")

    policy_b, conclusion_b = break_delete_policy()
    if policy_b.get("delete_all_data") != TIER_APPROVAL:
        raise AssertionError(
            f"delete_all_data 现在还是 {policy_b.get('delete_all_data')!r}；"
            f"要改成 {TIER_APPROVAL!r}")
    if TOOL_POLICY["delete_all_data"] != TIER_DENY:
        raise AssertionError("你把模块级的 TOOL_POLICY 改坏了 —— 要复制一份改，别动原件")
    if len(str(conclusion_b).strip()) < 10:
        raise AssertionError("② 还没写结论：为什么说「不可逆的操作只差一次点击」？")

    allowed_appr, asked_appr = describe_deny_tier(policy_b)
    if not allowed_appr:
        raise AssertionError("降级成 approval 之后钩子应该返回 True（审批人点了同意）")
    if asked_appr != 1:
        raise AssertionError(f"降级之后审批人应当收到 1 张单，实际 {asked_appr} 张")

    print("    delete_all_data · 审批人是个「来者不拒」的钩子：")
    print(f"      {TIER_DENY:<10}→ 钩子返回 {str(allowed_deny):<5}　审批单 {asked_deny} 张　"
          f"数据库{'已被清空' if DELETE_SINK else '未被清空'}")
    print(f"      {TIER_APPROVAL:<10}→ 钩子返回 {str(allowed_appr):<5}　审批单 {asked_appr} 张　"
          f"★ 一个不可逆操作就这样被执行了")
    print()

    kv("你的结论 ①", str(conclusion_a).strip()[:54])
    kv("你的结论 ②", str(conclusion_b).strip()[:54])
    print()
    warn("★ deny 档的意义不是「多一道审批」，而是**根本不给审批入口**：")
    warn("  不可逆的操作不该出现在「可以商量」的通道里 —— 商量的结果可能是「同意」。")
    note("★ 默认档必须是 approval 而不是 auto：工具表会越来越大，新人最容易忘记标权限，")
    note("  默认审批能让「忘记标」变成一次可发现的失败，而不是一次静默的越权。")
    bullet("auto = 只读无副作用；approval = 有副作用要人点头；deny = 不可逆，永不执行")
    bullet("护栏的三档和「忘记标权限」的默认值，共同决定了攻击面有多大")


def main() -> int:
    try:
        check_1()
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
