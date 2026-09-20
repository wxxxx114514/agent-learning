r"""第 04 章 · 练习 4 / 5 · 并行执行互不依赖的步骤

【要做什么】
  找出计划里 `depends_on` 互不相交、且都无副作用的步骤，
  用 `concurrent.futures.ThreadPoolExecutor` 并行跑，打印串行 / 并行的耗时对比。

【已经给你了】
  · TOOLS           一套真实的工具注册表：三个慢的只读工具（各睡 0.2 秒）+ 一个写工具
  · PLAN            一份 5 步计划，故意混了「能并行」「依赖别人」「有副作用」三种步骤
  · first_wave(...) 你要写的函数：挑出**第一批可以并行**的步骤
  · run_serial / run_parallel
                    串行 / 并行跑一批步骤的成品代码（计时也写好了），直接调用

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch04_planning\ex4_parallel_steps.py
  3. 验收本章：py scripts\run_all_checks.py 04
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import time                                              # noqa: E402
from concurrent.futures import ThreadPoolExecutor         # noqa: E402

from core.tool import ToolRegistry                        # noqa: E402
from stages.stage04_planning.planner import Step          # noqa: E402

SLEEP_S = 0.2          # 每个慢工具睡多久


def build_tools() -> ToolRegistry:
    """三个只读工具（慢）+ 一个写工具（也慢，但它有副作用）。"""
    reg = ToolRegistry()

    @reg.tool("read_stock", "查库存（慢，约 0.2 秒）。",
              {"type": "object", "properties": {"sku": {"type": "string"}},
               "required": ["sku"], "additionalProperties": False}, tags=["read"])
    def read_stock(sku: str) -> dict:
        time.sleep(SLEEP_S)
        return {"sku": sku, "stock": 12}

    @reg.tool("read_price", "查价格（慢，约 0.2 秒）。",
              {"type": "object", "properties": {"sku": {"type": "string"}},
               "required": ["sku"], "additionalProperties": False}, tags=["read"])
    def read_price(sku: str) -> dict:
        time.sleep(SLEEP_S)
        return {"sku": sku, "price": 99.0}

    @reg.tool("read_eta", "查到货时效（慢，约 0.2 秒）。",
              {"type": "object", "properties": {"sku": {"type": "string"}},
               "required": ["sku"], "additionalProperties": False}, tags=["read"])
    def read_eta(sku: str) -> dict:
        time.sleep(SLEEP_S)
        return {"sku": sku, "eta_days": 2}

    @reg.tool("write_note", "把结论写进备注（**有副作用**，也慢）。",
              {"type": "object", "properties": {"text": {"type": "string"}},
               "required": ["text"], "additionalProperties": False}, tags=["write"])
    def write_note(text: str) -> dict:
        time.sleep(SLEEP_S)
        return {"ok": True, "chars": len(text)}

    return reg


TOOLS = build_tools()

# 5 步计划：1/2/3 互不依赖且都是只读；4 有副作用；5 依赖第 2 步
PLAN = [
    Step(1, "查库存", "read_stock", {"sku": "SKU-1"}),
    Step(2, "查价格", "read_price", {"sku": "SKU-1"}),
    Step(3, "查到货时效", "read_eta", {"sku": "SKU-1"}),
    Step(4, "把结论写进备注（有副作用）", "write_note", {"text": "SKU-1 有货"}, depends_on=[1]),
    Step(5, "再查一次时效（依赖第 2 步）", "read_eta", {"sku": "SKU-1"}, depends_on=[2]),
]


def run_serial(wave: list[Step], tools: ToolRegistry) -> float:
    """串行跑一批步骤，返回耗时（秒）。"""
    t0 = time.perf_counter()
    for step in wave:
        tools.execute(step.tool, dict(step.args))
    return time.perf_counter() - t0


def run_parallel(wave: list[Step], tools: ToolRegistry) -> float:
    """并行跑一批步骤，返回耗时（秒）。"""
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=max(len(wave), 1)) as pool:
        futures = [pool.submit(tools.execute, s.tool, dict(s.args)) for s in wave]
        for f in futures:
            f.result()          # 拿一下结果，异常会在这里冒出来
    return time.perf_counter() - t0


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def first_wave(steps: list[Step], tools: ToolRegistry, done: set[int] | None = None) -> list[Step]:
    """挑出「第一批可以并行执行」的步骤。

    两个条件，缺一不可：
      ① 依赖都已满足：step.depends_on 里的每个编号都在 done 里（没有依赖当然也算满足）
      ② 无副作用：这个工具的 tags 里有 "read"
         —— 拿标签用 tools.get(step.tool).tags

    顺带说明为什么两个条件都要：
      · 少了 ①，你会让「还没拿到上游数据」的步骤先跑，它只会报错；
      · 少了 ②，你会让两条短信同时发出去 —— 那就是事故（第 ⑥ 节）。

    前后都写好了（跳过已完成的步骤、返回 wave），你只写中间那个判断。

    TODO ── 提示：
        if not set(step.depends_on) <= done_set:        # 依赖没满足
            continue
        if "read" not in tools.get(step.tool).tags:     # 有副作用
            continue
        wave.append(step)
    """
    done_set = set(done or ())
    wave: list[Step] = []
    for step in steps:
        if step.id in done_set:
            continue
        # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
        raise NotImplementedError("练习 4 · TODO  first_wave：挑出依赖满足且只读的步骤")
        # ↑↑↑ 你的答案 ↑↑↑
    return wave


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        wave = first_wave(PLAN, TOOLS)
        ids = [s.id for s in wave]
        if ids != [1, 2, 3]:
            raise AssertionError(
                f"第一批可并行的应该是 [1, 2, 3]，实际 {ids}。"
                "检查两件事：第 4 步有副作用吗？第 5 步的依赖满足了吗？")

        later = first_wave(PLAN, TOOLS, done={1, 2})
        if [s.id for s in later] != [3, 5]:
            raise AssertionError(
                f"第 1、2 步完成之后，可并行的应该是 [3, 5]，实际 {[s.id for s in later]}")

        serial_s = run_serial(wave, TOOLS)
        parallel_s = run_parallel(wave, TOOLS)
        if parallel_s >= serial_s:
            raise AssertionError(
                f"并行没有变快（串行 {serial_s:.2f}s / 并行 {parallel_s:.2f}s）——"
                "确认真的提交到线程池了")

        report.append(f"计划共 {len(PLAN)} 步，第一批可并行的：{[s.id for s in wave]}")
        for s in wave:
            report.append(f"    第 {s.id} 步  {s.tool:<12} tags={TOOLS.get(s.tool).tags}"
                          f"  depends_on={s.depends_on}")
        report.append("")
        report.append("被排除的步骤：")
        for s in PLAN:
            if s.id in ids:
                continue
            why = "有依赖未满足" if s.depends_on else "有副作用（tags 里没有 read）"
            tags = TOOLS.get(s.tool).tags
            if "read" not in tags:
                why = f"有副作用（tags={tags}，写操作绝不并行）"
            report.append(f"    第 {s.id} 步  {s.tool:<12} depends_on={s.depends_on}"
                          f"  -> {why}")
        report.append("")
        report.append("耗时对比（三个只读工具，每个 0.2 秒）：")
        report.append(f"    串行 : {serial_s:5.2f}s")
        report.append(f"    并行 : {parallel_s:5.2f}s   （快了 {serial_s / parallel_s:.1f} 倍）")
        report.append("")
        report.append("★ 并行的前提有两条：**无依赖** + **无副作用冲突**。")
        report.append("  两个都写同一个订单的步骤绝对不能并行；")
        report.append("  真实系统里还要考虑「同一个工具被限流」这种情况。")
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
