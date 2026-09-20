r"""第 04 章 · 练习 3 / 5 · 让重规划的提示词更省 token

【要做什么】
  现在的 `Planner.replan()` 把「上一版计划的**全部**结果」都塞进提示词
  （就是 `plan.render(with_result=True)` 那一大段）。
  改成只传「被后续步骤引用到的字段」。

  统计一下：一个 4 步计划能省掉多少字符？步数变成 20 步时呢？

【已经给你了】
  · _REF_RE                    引用语法的正则（`$1.status` 这种）
  · ORDER_RESULT               第 1 步的真实结果（一份订单的 6 个字段）
  · make_plan(n_extra)         造一份「已经跑完」的计划：第 1 步查订单，
                               后面 n_extra 步各自引用订单里的字段
  · used_fields(plan)          你要写的第一个函数：收集被引用到的 (步骤号, 字段路径)
  · compact_results(plan, u)   你要写的第二个函数：只把这些字段渲染成几行文本

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch04_planning\ex3_compact_replan_prompt.py
  3. 验收本章：py scripts\run_all_checks.py 04
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                   # noqa: E402
import re                     # noqa: E402

from stages.stage04_planning.planner import Plan, Step   # noqa: E402

# 引用语法：$<步骤号>.<字段路径>（字段路径允许 a.b 这种嵌套）
_REF_RE = re.compile(r"\$(\d+)\.([\w\.]+)")

ORDER_RESULT = {
    "order_id": "A1001",
    "status": "已发货",
    "carrier": "顺丰",
    "tracking": "SF1234567890",
    "weight_kg": 2.5,
    "amount": 328.0,
}


def make_plan(n_extra: int = 2) -> Plan:
    """造一份「已经执行完」的计划。

    第 1 步查订单（结果 = 上面那份 6 字段的 dict），
    后面 n_extra 步做通知，只引用第 1 步的 order_id 和 status 两个字段。
    —— 也就是说：6 个字段里只有 2 个是**真正被后续步骤用到**的。
    """
    obs = json.dumps(ORDER_RESULT, ensure_ascii=False)
    steps = [Step(1, "查询订单 A1001 的全部字段", "lookup_order",
                  {"order_id": "A1001"}, status="done",
                  result=dict(ORDER_RESULT), observation=obs)]
    for i in range(n_extra):
        steps.append(Step(
            2 + i, f"第 {2 + i} 条通知：把订单状态写进文案", "draft_reply",
            {"order_id": "$1.order_id", "kind": "shipped",
             "detail": f"当前状态：$1.status（第 {2 + i} 条）"},
            depends_on=[1], status="done",
            result={"kind": "shipped", "text": f"您的订单 A1001 已发货（第 {2 + i} 条）"},
            observation=json.dumps({"kind": "shipped", "text": "您的订单 A1001 已发货"},
                                   ensure_ascii=False),
        ))
    return Plan(version=1, reason="已执行完的计划", steps=steps)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def used_fields(plan: Plan) -> list[tuple[int, str]]:
    """收集计划里**被引用到**的 (步骤号, 字段路径)，去重后排序返回。

    例：`{"order_id": "$1.order_id"}` 贡献 (1, "order_id")；
        `{"detail": "状态：$1.status"}` 贡献 (1, "status")（内插值也要算）。

    前后都写好了（两层循环 + 返回），你只写中间那一句收集。

    TODO ① ── 提示：
        for m in _REF_RE.finditer(value):        # value 是参数字符串
            used.add((int(m.group(1)), m.group(2)))
      注意：参数值**不是字符串**时要跳过（数字、布尔直接透传，不存在引用）。
    """
    used: set[tuple[int, str]] = set()
    for step in plan.steps:
        for value in step.args.values():
            if not isinstance(value, str):
                continue
            # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
            raise NotImplementedError("练习 3 · TODO ①  用 _REF_RE 把引用抠出来")
            # ↑↑↑ 你的答案 ↑↑↑
    return sorted(used)


def compact_results(plan: Plan, used: list[tuple[int, str]]) -> str:
    """只把被引用到的字段渲染进提示词 —— 替代那一大段 plan.render(with_result=True)。

    输出形如：
        - 第 1 步的 order_id = A1001
        - 第 1 步的 status = 已发货

    前后都写好了（循环、拼装、join），你只写中间「从结果里按 path 取值」那几行。

    TODO ② ── 提示：
        src = plan.get(sid)               # 拿第 sid 步
        value = src.result                # 它的结构化结果（dict）
        for part in path.split("."):      # 支持 a.b 这种嵌套
            value = value[part]
      然后 lines.append(f"- 第 {sid} 步的 {path} = {value}")
    """
    lines: list[str] = []
    for sid, path in used:
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 3 · TODO ②  从上游结果里按 path 取值并渲染成一行")
        # ↑↑↑ 你的答案 ↑↑↑
    return "\n".join(lines)


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        small = make_plan(2)
        big = make_plan(20)

        small_used = used_fields(small)
        big_used = used_fields(big)
        if small_used != [(1, "order_id"), (1, "status")]:
            raise AssertionError(
                f"4 步计划里被引用到的字段应该是 [(1,'order_id'), (1,'status')]，"
                f"实际 {small_used}（内插值 `状态：$1.status` 也要算进去）")
        if big_used != small_used:
            raise AssertionError(
                f"步数变多不会新增被引用的字段，实际 {big_used}")

        small_compact = compact_results(small, small_used)
        big_compact = compact_results(big, big_used)
        for token in ("A1001", "已发货"):
            if token not in small_compact:
                raise AssertionError(f"精简后的提示词里丢了引用到的值：{token!r}")

        small_full = small.render(with_result=True)
        big_full = big.render(with_result=True)
        if len(small_compact) >= len(small_full):
            raise AssertionError("精简之后的提示词居然没变短 —— 检查 TODO ② 是不是拼多了东西")
        if len(big_compact) >= len(big_full):
            raise AssertionError("20 步计划里，精简版也应该明显更短")

        report.append("被后续步骤引用到的字段（只有这两个）：")
        report.append(f"    {small_used}")
        report.append("")
        report.append("精简后的「现状」块（全文就这两行）：")
        for line in small_compact.splitlines():
            report.append("    " + line)
        report.append("")
        report.append("两种写法的字符数对比（这就是重规划提示词的差距）：")
        report.append("")
        for label, full, compact in (("4 步计划", small_full, small_compact),
                                     ("21 步计划", big_full, big_compact)):
            save = 1 - len(compact) / len(full)
            report.append(f"    {label:<10} 全量 {len(full):>5} 字符  ->  "
                          f"精简 {len(compact):>4} 字符   省下 {save:.0%}")
        report.append("")
        report.append("★ 关键点：省下的比例随步数**线性增长** ——")
        report.append("  因为被引用的字段数基本不变，而全量结果随步数一路涨。")
        report.append("  这就是「上下文工程」在规划场景里的第一次应用：")
        report.append("  计划里的每一步结果都在涨，但重规划真正需要的只有**被引用到的那几个**。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    for line in report:
        print(line)
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
