r"""第 04 章 · 练习 5 / 5 · 给 Plan 加一个 `to_mermaid()` 方法

【要做什么】
  把步骤和依赖渲染成 Mermaid 流程图，贴进任意 Markdown 编辑器就能看到图。

  为什么值得做？因为「计划长什么样」是给人看的 ——
  线上排障时，一张图比 200 行 JSON 有用得多。

【已经给你了】
  · PLAN        一份 4 步计划（有串行、有分叉、有汇合）
  · to_mermaid(plan)
                你要写的函数：节点循环和依赖循环都搭好了，各留一个 TODO
  · Plan / Step 课程自带的结构化计划（来自 stages/stage04_planning/planner.py）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch04_planning\ex5_plan_mermaid.py
  3. 验收本章：py scripts\run_all_checks.py 04
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage04_planning.planner import Plan, Step   # noqa: E402

PLAN = Plan(version=1, reason="发货通知任务", steps=[
    Step(1, "查询订单 A1001", "lookup_order", {"order_id": "A1001"}),
    Step(2, "算加急运费", "calc_freight", {"order_id": "$1.order_id",
                                          "weight_kg": "$1.weight_kg",
                                          "speed": "加急"}, depends_on=[1]),
    Step(3, "拟发货通知", "draft_reply", {"order_id": "$1.order_id",
                                          "kind": "shipped"}, depends_on=[1]),
    Step(4, "发给客户", "send_reply", {"order_id": "$1.order_id",
                                       "text": "$3.text"}, depends_on=[2, 3]),
])


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def to_mermaid(plan: Plan) -> str:
    """把计划渲染成 Mermaid 流程图文本（第一行必须是 `graph TD`）。

    预期输出形如：

        graph TD
          n1["1. 查询订单 A1001<br/>(lookup_order)"]
          n2["2. 算加急运费<br/>(calc_freight)"]
          n1 --> n2
          n1 --> n3
          n2 --> n4
          n3 --> n4

    节点 id 用 `n<步骤号>`；节点文字里带上「序号 + 目标 + 工具名」。
    """
    lines: list[str] = ["graph TD"]

    # ---- ① 节点：每个步骤一行 ----
    for step in plan.steps:
        label = f"{step.id}. {step.goal}<br/>({step.tool})"
        # TODO ① ── 追加一行节点定义
        #   提示：lines.append(f'  n{step.id}["{label}"]')
        #        （label 已经帮你算好了，直接用）
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ①  追加节点定义行")
        # ↑↑↑ 你的答案 ↑↑↑

    # ---- ② 依赖边：depends_on 里每个 d 画一条 d --> 本步骤 ----
    for step in plan.steps:
        # TODO ② ── 给 step.depends_on 里的每个 d 追加一行边
        #   提示：for d in step.depends_on: lines.append(f"  n{d} --> n{step.id}")
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 5 · TODO ②  追加依赖边")
        # ↑↑↑ 你的答案 ↑↑↑

    return "\n".join(lines)


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        text = to_mermaid(PLAN)
        if not isinstance(text, str):
            raise AssertionError("to_mermaid 要返回字符串")

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines or lines[0] != "graph TD":
            raise AssertionError(f"第一行必须是 `graph TD`，实际是 {lines[0] if lines else '(空)'!r}")

        nodes = [ln for ln in lines[1:] if "-->" not in ln]
        edges = [ln for ln in lines[1:] if "-->" in ln]
        if len(nodes) != len(PLAN.steps):
            raise AssertionError(f"应该有 {len(PLAN.steps)} 个节点，实际 {len(nodes)} 个：{nodes}")
        for step in PLAN.steps:
            if not any(ln.startswith(f"n{step.id}[") for ln in nodes):
                raise AssertionError(f"缺少第 {step.id} 步的节点（id 应该写成 n{step.id}）")
            if step.tool not in text:
                raise AssertionError(f"节点文字里应该带上工具名 {step.tool!r}")

        want_edges = {f"n{d} --> n{s.id}" for s in PLAN.steps for d in s.depends_on}
        got_edges = {ln.replace(" ", "") for ln in edges}
        if got_edges != {e.replace(" ", "") for e in want_edges}:
            raise AssertionError(
                f"依赖边不对。\n      期望 {sorted(want_edges)}\n      实际 {sorted(edges)}")

        report.append("生成的 Mermaid 图（贴进任意 Markdown 编辑器就能渲染）：")
        report.append("")
        for line in text.splitlines():
            report.append("    " + line)
        report.append("")
        report.append(f"    {len(nodes)} 个节点 / {len(edges)} 条依赖边，"
                      f"和计划里的 depends_on 完全一致")
        report.append("")
        report.append("★ 注意第 4 步有两条入边（n2 --> n4 和 n3 --> n4）：")
        report.append("  这就是「汇合」—— 第 2、3 步都完成了，第 4 步才能发出去。")
        report.append("  一张图能一眼看出的东西，200 行 JSON 要看十分钟。")
        report.append("")
        report.append("★ 顺带一提：这个图还能反过来用 —— ")
        report.append("  「哪些步骤可以并行」在图上一眼可见（同一层的节点）。")
        report.append("  练习 4 的 first_wave() 算的就是同一件事。")
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
