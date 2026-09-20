r"""第 10 章 · 练习 5 / 5 · 给评估加上「稳定性」维度（进阶）

【要做什么】
  同一个配置连跑 3 次，统计每条用例的通过情况，把「3 次里过了 2 次」的用例单独列出来。

【已经给你了】
  stability_report(cfg, runs)  连跑 N 次，统计每条用例的通过次数 —— ★ 就是你要写的东西
  FlakyModel                   一个"偶尔拒绝回答"的假模型（真实模型抖动的替身，确定性）
  stability_probe(cfg, runs)   跑两次稳定性统计，检查"两次统计是否一致"（框架有没有隐藏状态）
  CONFIGS / CONFIG_V3          课程里的配置
  run_suite(cfg)               跑一整套，返回 SuiteResult（有 .results / .by_id()）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch10_evaluation\ex5_stability.py
  3. 验收本章：py scripts\run_all_checks.py 10
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import copy                                                  # noqa: E402
from dataclasses import replace                              # noqa: E402

from core.console import bullet, kv, note, warn              # noqa: E402
from core.llm import LLM, LLMResponse                        # noqa: E402
from core.message import Message                             # noqa: E402
from stages.stage10_evaluation.demo import (                 # noqa: E402
    CONFIG_V3, CONFIGS, EvalConfig, SimulatedModel, SuiteResult, run_suite,
)

RUNS = 3


class FlakyModel(SimulatedModel):
    """"每三次里有一次拒绝回答"的假模型（确定性抖动，用来验证稳定性统计真的能抓到抖动）。

    为什么假模型也要能"抖"？因为真实模型的抖动是你必须提前布防的东西 ——
    先用一个可控的抖动源把统计逻辑测通，等接上真模型时你才不是在猜。
    """

    name = "flaky-model"

    def __init__(self, fail_every: int = 3, label: str = "flaky") -> None:
        super().__init__(label=label)
        self.fail_every = fail_every
        self.attempt = 0

    def complete(self, messages, **kwargs) -> LLMResponse:
        self.attempt += 1
        if self.attempt % self.fail_every == 0:
            text = "Thought: 这次我拒绝回答。\n\nFinal Answer: （本次无回答）"
            return LLMResponse(text=text, model=self.model)
        return super().complete(messages, **kwargs)


def run_suite_with(cfg: EvalConfig, runs: int, llm_factory=None) -> list[SuiteResult]:
    """连跑 `runs` 次，返回每次的 SuiteResult。

    llm_factory 留空时用课程原版；传 FlakyModel 就能看到"统计真的抓到了抖动"。

    ★ 实现细节：`run_case()` 内部会自己 new 一个 SimulatedModel，
      所以我们在这里**临时把 Agent 类换成一个"总会塞进指定模型"的工厂** ——
      这样不用改课程源码，也能把抖动注入进去。
    """
    from stages.stage10_evaluation import demo as evaldemo

    original = evaldemo.Agent
    shared: dict[str, LLM] = {}
    out: list[SuiteResult] = []
    try:
        if llm_factory is not None:
            shared["llm"] = llm_factory()          # ★ 整个"一次评估"共用一个模型实例

            def flaky_agent(*args, **kwargs):
                kwargs["llm"] = shared["llm"]
                return original(*args, **kwargs)

            evaldemo.Agent = flaky_agent
        for _ in range(runs):
            shared.pop("llm", None)                # 每一轮换一个全新的模型（干净世界）
            if llm_factory is not None:
                shared["llm"] = llm_factory()
            out.append(run_suite(cfg))
    finally:
        evaldemo.Agent = original
    return out


def count_passes(suites: list[SuiteResult]) -> dict[str, int]:
    """把多次运行的 SuiteResult 压成 {用例 id: 通过次数}。

    ★ 这就是 stability_report 的核心逻辑 —— 它被单独抽出来，是为了让下面那段
      "换成抖动模型再统计一次"的验证也能复用它（否则验证代码就得把逻辑再抄一遍）。
    """
    counter: dict[str, int] = {r.case.id: 0 for r in suites[0].results}
    for suite in suites:
        for result in suite.results:
            if result.passed:
                counter[result.case.id] += 1
    return counter


def stability_probe(cfg: EvalConfig, runs: int = RUNS) -> tuple[dict, dict]:
    """跑两次稳定性统计：用来验证「评估框架本身没有隐藏的全局状态」。

    如果两次统计结果不一致，说明用例之间有污染（上一轮的缓存 / sink / 记忆泄漏到下一轮）——
    那才是评估里最隐蔽的 bug：数字漂亮，但没有意义。
    """
    first = stability_report(cfg, runs)
    second = stability_report(cfg, runs)
    return first, second


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def stability_report(cfg: EvalConfig, runs: int = RUNS) -> dict[str, int]:
    """TODO ① ── 同一个配置连跑 `runs` 次，统计**每条用例通过了几次**。

    返回一个字典：{用例 id: 通过的次数}，每个用例都必须在里面（哪怕是 0）。

    两行就够：
      ① suites = run_suite_with(cfg, runs)      ← 跑 runs 次（返回每次的 SuiteResult）
      ② return count_passes(suites)             ← 统计（上面已经写好了，直接用）

    ★ 为什么「3 次里过了 0 次」的用例也必须被统计到？
      因为只在通过时 +1 的话，你会**看不见一直失败的用例** ——
      而"一直失败"恰恰是最需要被看见的那一类。
      （count_passes 用第一次运行的用例列表先把骨架建全，正是为了这个。）

    提示（卡住了再看）：
        ★ 一条用例的"稳定性"= 通过次数 / 总次数。
          runs=3 时可能的值只有 0/3、1/3、2/3、3/3 —— 只有 3/3 算稳定。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 5 · TODO ①  stability_report")
    # ↑↑↑ 你的答案 ↑↑↑


def unstable_cases(counter: dict[str, int], runs: int = RUNS) -> list[tuple[str, int]]:
    """TODO ② ── 从统计里挑出「不稳定」的用例：通过次数 < runs 的那些。

    返回 [(用例 id, 通过次数), …]，按 id 排序。

    一行就够：
        return sorted((cid, n) for cid, n in counter.items() if n < runs)

    ★ 为什么"确定性的假模型也值得跑 3 次"？
      因为它能证明「评估框架本身没有隐藏的全局状态」：
      同一个配置跑 3 次，每条用例的通过次数必须**完全一样**。
      哪天某条用例变成 2/3 了，那不是模型的问题，是你的框架被污染了 ——
      用例之间的缓存、内存 sink、全局注册表泄漏，都会在这里现形。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 5 · TODO ②  unstable_cases")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_5() -> None:
    cfg = CONFIGS[CONFIG_V3]

    # ① 确定性假模型：3 次全稳
    counter = stability_report(cfg, RUNS)
    n_cases = len(run_suite(cfg).results)
    if len(counter) != n_cases:
        raise AssertionError(f"统计里应该有全部 {n_cases} 条用例，现在只有 {len(counter)} 条")
    bad_range = {k: v for k, v in counter.items() if not 0 <= v <= RUNS}
    if bad_range:
        raise AssertionError(f"通过次数必须在 0~{RUNS} 之间：{bad_range}")
    print(f"    确定性的假模型 · 连跑 {RUNS} 次（{n_cases} 条用例）")
    print(f"      通过次数分布："
          f"{ {n: sum(1 for v in counter.values() if v == n) for n in range(RUNS, -1, -1)} }"
          f"　（键=通过了几次，值=有几条用例）")
    unstable = unstable_cases(counter, RUNS)
    print(f"      「{RUNS} 次里过了不到 {RUNS} 次」的用例：{unstable or '（没有）'}")
    print()

    if unstable:
        raise AssertionError(f"确定性的假模型不该有不稳定用例：{unstable}")
    if any(v != RUNS for v in counter.values()):
        raise AssertionError(f"每条用例都该是 {RUNS}/{RUNS}：{counter}")

    # ② 框架没有隐藏状态：两次统计必须完全一致
    first, second = stability_probe(cfg, RUNS)
    if first != second:
        raise AssertionError(
            f"两次稳定性统计不一致 —— 说明用例之间有污染（隐藏的全局状态）：\n"
            f"      第一次={first}\n      第二次={second}")
    kv("两次统计一致", f"✅ 每条用例都是 {RUNS}/{RUNS} → 框架没有隐藏的全局状态")
    print()

    # ③ 反过来验证统计真的能抓到抖动（不然它就是个永远说"稳定"的假统计）
    flaky_counter = count_passes(
        run_suite_with(replace(cfg, key=f"{cfg.key}#flaky"), RUNS, llm_factory=FlakyModel))
    flaky_unstable = unstable_cases(flaky_counter, RUNS)
    print(f"    换成「每 {FlakyModel().fail_every} 次抖 1 次」的 FlakyModel · 再跑 {RUNS} 次")
    print(f"      通过次数分布："
          f"{ {n: sum(1 for v in flaky_counter.values() if v == n) for n in range(RUNS, -1, -1)} }")
    print(f"      不稳定用例 {len(flaky_unstable)} 条，例如：{flaky_unstable[:3]}")
    print()

    if not flaky_unstable:
        raise AssertionError("抖动的模型居然被判成 100% 稳定 —— 说明统计没真的在工作")
    if len(flaky_unstable) == n_cases:
        raise AssertionError("全都不稳定也不正常：抖动应当只影响「有答案期望」的那部分用例")
    if any(n >= RUNS for _, n in flaky_unstable):
        raise AssertionError(f"不稳定用例的通过次数必须小于 {RUNS}：{flaky_unstable}")

    kv("确定性模型", f"不稳定 {len(unstable)} 条 → 评估框架可信")
    kv("抖动模型", f"不稳定 {len(flaky_unstable)} 条 → 统计真的抓到了抖动")
    print()
    warn("★ 真模型有随机性时，这一步是必须的：一条 2/3 的用例和一条 3/3 的用例，")
    warn("  意义完全不同 —— 前者说明你的系统在「大部分时候」能过，后者才是「能过」。")
    note("★ 那为什么确定性的假模型仍然值得跑 3 次？")
    note("  因为它能证明「评估框架本身没有隐藏的全局状态」—— 用例之间的污染会在这里现形。")
    bullet("稳定性 = 通过次数 / 总次数；runs=3 时只有 0/3、1/3、2/3、3/3 四种可能")
    bullet("固定 seed / temperature、记录模型版本、跑多次取均值 —— 真模型评估的必备动作")


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
