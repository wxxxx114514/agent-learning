r"""第 13 章 · 练习 3 / 5 · 破坏性实验：删掉恢复时的「倒回」，看工具调用怎么翻倍

【要做什么】
  **破坏性实验：删掉恢复时的「倒回」，看工具调用怎么翻倍。**

  在 ③ 的恢复 B 里，把 `start=saved["start"], facts=saved["facts"]` 改成
  `start=saved["messages"]`（也就是恢复 A 的写法）。

  观察三件事：用户消息几条？`WORLD` 里的副作用计数是多少？最终答案看起来对不对？

  **然后回答：本章所有的破坏性实验里，哪一处的「坏」最不容易被发现？**

【已经给你了】
  · 第 13 章真正的生产零件：`ProductionRuntime` / `CheckpointedEngine` / `SimulatedCrash` /
    `FileCheckpointStore` / `Request` / `EventLog`
  · 两个真实模型：`RuleBasedLLM`（前 11 章一直在用）与 `ProductionLLM`（本章自己的）
  · `scenario(模型)`：提交 → 第 1 步之后进程被杀 → 换一个进程带同一个 run_id 续跑
  · `side_effects()`：从 `STATS` 里读「外部世界真正发生了几次副作用」

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch13_production\ex3_break_rollback.py
  3. 验收本章：py scripts\run_all_checks.py 13
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import shutil  # noqa: E402

from core.agent import Agent  # noqa: E402
from core.mock_llm import RuleBasedLLM  # noqa: E402
from stages.stage13_production.handlers import (  # noqa: E402
    STATS, ProductionLLM, demo_tools, reset_world,
)
from stages.stage13_production.journal import (  # noqa: E402
    EventLog, FileCheckpointStore, Request,
)
from stages.stage13_production.runtime import (  # noqa: E402
    CheckpointedEngine, ProductionRuntime, SimulatedCrash,
)

SCRATCH = Path(__file__).resolve().parent / "_scratch_ckpt3"    # 跑完会被删掉
TASK = "查一下订单 A1001 到哪了"
RUN_ID = "run-001"


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


def new_runtime(store, llm_name: str, tag: str) -> ProductionRuntime:
    """建一个全新的运行时 = 换一个进程 / 换一个 Pod（已经写好，不用改）。"""
    log = EventLog()
    if llm_name == "rule":
        llm = RuleBasedLLM(model=f"mock-{tag}")
    else:
        llm = ProductionLLM(model=f"mock-{tag}")
    agent = Agent(llm=llm, tools=demo_tools(), max_steps=4, verbose=False)
    return ProductionRuntime(CheckpointedEngine(agent, store, log), store, log=log)


def side_effects() -> dict[str, int]:
    """外部世界已经发生的副作用次数（已经写好，不用改）。

    ★ 它是唯一可信的证据：最终答案、日志、检查点**全都可能看起来是对的**。
    """
    return {"lookup_order": STATS["lookup_calls"].get("A1001"),
            "archive_order": STATS["archive_applied"].get("A1001")}


def scenario(llm_name: str) -> dict:
    """跑完整个破坏性实验（已经写好，不用改）。

    提交 → 第 1 步之后「进程被杀」→ 换一个进程带同一个 run_id 续跑 → 交回全部观测。
    """
    store = FileCheckpointStore(SCRATCH / llm_name)
    reset_world()
    req = Request(request_id=RUN_ID, user_id="u_42", task=TASK, max_steps=4)
    try:
        new_runtime(store, llm_name, "first").submit(req, crash_at=1)
    except SimulatedCrash:
        pass
    before = side_effects()
    resp = new_runtime(store, llm_name, "second").submit(req, resume=True)
    after = side_effects()
    state = store.load(RUN_ID)
    return {"llm": llm_name, "before": before, "after": after,
            "messages": state.messages, "answer": resp.answer,
            "reason": resp.reason, "steps": state.steps_done}


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def audit_resume(before: dict[str, int], after: dict[str, int],
                 messages: list[dict]) -> None:
    """TODO ① ── 恢复对账：两条断言，任何一条不成立就抛 AssertionError。

    ① **副作用不许翻倍**：`after` 里每个工具的计数都不能比 `before` 多。
       多了就说明恢复时把已经做完的事又做了一遍。
    ② **会话里只许有 1 条用户消息**（`role == "user"`）。
       多了说明恢复时用户消息被追加了第二次 —— 这就是脏数据的源头。

    要求：AssertionError 的消息里必须说清**哪个工具多跑了几次** / **有几条用户消息**，
          因为排障的人只看得到这行字。
    提示：`for tool, n in after.items():` 配上 `before.get(tool, 0)`；
          用户消息数用 `sum(1 for m in messages if m.get("role") == "user")`。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 3 · TODO ①  audit_resume")
    # ↑↑↑ 你的答案 ↑↑↑


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   本章所有的破坏性实验里，哪一处的「坏」最不容易被发现？为什么它比崩溃危险？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        rows = []
        scenes = {}
        caught_count = 0
        for llm_name, label in [("rule", "RuleBasedLLM（前 11 章的模型）"),
                                ("production", "ProductionLLM（本章的模型）")]:
            print(f"\n    ── {label}")
            sc = scenario(llm_name)
            scenes[llm_name] = sc
            print(f"       崩溃时已发生的副作用：{sc['before']}")
            print(f"       续跑之后累计副作用  ：{sc['after']}   （停机原因 {sc['reason']}）")
            users = sum(1 for m in sc["messages"] if m.get("role") == "user")
            print(f"       会话里的用户消息    ：{users} 条")
            print(f"       最终答案看起来      ：{sc['answer'][:52]!r}")

            caught = "❌ 没抓到"
            try:
                audit_resume(sc["before"], sc["after"], sc["messages"])
            except AssertionError as exc:
                caught = f"✅ 抓到：{exc}"
                caught_count += 1
            print(f"       你的对账            ：{caught}")
            rows.append([label.split("（")[0], str(sc["before"]["lookup_order"]),
                         str(sc["after"]["lookup_order"]), f"{users} 条",
                         "看起来正确", "抓到" if caught.startswith("✅") else "没抓到"])

        table(["模型", "崩溃时 lookup", "恢复后 lookup", "用户消息", "最终答案", "你的对账"], rows)
        print()

        rule = scenes["rule"]
        assert rule["after"]["lookup_order"] > rule["before"]["lookup_order"], \
            "实验失效：RuleBasedLLM 这一路本该翻倍（它只看「最后一条用户消息之后」做过什么）"
        assert caught_count == 2, f"两个场景都必须被你的对账抓到，实际抓到 {caught_count} 个"

        print("    ★ 三件事一起看：用户消息 2 条、副作用翻倍、最终答案**看起来完全正确**。")
        print("      没有异常、没有 error 日志、检查点也在 —— 只有对账（副作用计数）能发现它。")
        print()
        print("    ★ 为什么「倒回」没生效：运行时里那段倒回的条件是")
        print("      `conv.messages[-1].role == \"user\"`；而崩溃点钉在**工具边界**上，")
        print("      末尾是一条工具结果 → 条件不成立 → `Agent.run()` 又把用户消息追加了一次。")
        print()
        print("    ★ 为什么两个模型表现不一样：")
        print("      RuleBasedLLM 只统计「最后一条用户消息之后」的工具结果 → 什么都没看到 → 重做一遍；")
        print("      ProductionLLM 扫的是**整个会话**（handlers.py 的 `_done_actions`）→ 侥幸躲过。")
        print("      同一个坏掉的恢复，换个模型实现结果就不同 —— 这种 bug 更难被发现。")
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    finally:
        shutil.rmtree(SCRATCH, ignore_errors=True)      # 不留残留文件

    print()
    print(f"    你的结论：{CONCLUSION or '（还没写 —— 写在文件里的 CONCLUSION 那一行）'}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
