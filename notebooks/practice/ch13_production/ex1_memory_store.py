r"""第 13 章 · 练习 1 / 5 · 把检查点换成内存版，看「假崩溃」为什么没复现真实故障

【要做什么】
  **把检查点换成内存版，观察「假崩溃」为什么没有复现真实故障。**

  把 ③ 里的 `save` / `load` 改成写一个普通 dict（不落盘），然后重跑整个实验。

  你会看到一个诡异的结果：**恢复居然成功了**。请回答：
  这个实验为什么没有复现真实故障？真实场景里丢掉的到底是什么？

【已经给你了】
  · 第 13 章真正的生产零件：
    `InMemoryCheckpointStore` / `FileCheckpointStore`（journal.py）
    `CheckpointedEngine` / `ProductionRuntime` / `SimulatedCrash`（runtime.py）
    `ProductionLLM` / `demo_tools` / `reset_world`（handlers.py）
  · `new_store(kind)` / `new_runtime(store, tag)` / `submit_and_crash(store)`：
    一条已经搭好的链路 —— 提交 → 跑到第 2 步时「进程被杀」
  · 磁盘版会在 `_scratch_ckpt/` 下建目录，跑完自动清掉

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch13_production\ex1_memory_store.py
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
from stages.stage13_production.handlers import (  # noqa: E402
    ProductionLLM, demo_tools, reset_world,
)
from stages.stage13_production.journal import (  # noqa: E402
    EventLog, FileCheckpointStore, InMemoryCheckpointStore, Request,
)
from stages.stage13_production.runtime import (  # noqa: E402
    CheckpointedEngine, ProductionRuntime, SimulatedCrash,
)

SCRATCH = Path(__file__).resolve().parent / "_scratch_ckpt"     # 跑完会被删掉
TASK = "查一下订单 A1001，然后把它归档"
RUN_ID = "run-001"


def new_store(kind: str):
    """按类型建检查点仓库（已经写好，不用改）。kind: "memory" / "file" """
    if kind == "memory":
        return InMemoryCheckpointStore()
    return FileCheckpointStore(SCRATCH / kind)


def new_runtime(store, tag: str) -> ProductionRuntime:
    """建一个全新的运行时 = 换一个进程 / 换一个 Pod（已经写好，不用改）。"""
    log = EventLog()
    agent = Agent(llm=ProductionLLM(model=f"mock-{tag}"), tools=demo_tools(),
                  max_steps=6, verbose=False)
    return ProductionRuntime(CheckpointedEngine(agent, store, log), store, log=log)


def submit_and_crash(store) -> str:
    """提交一次请求，并在第 2 步之后注入「进程被杀」（已经写好，不用改）。"""
    reset_world()
    req = Request(request_id=RUN_ID, user_id="u_42", task=TASK, max_steps=6)
    try:
        new_runtime(store, "first").submit(req, crash_at=2)
        print("       ⚠️ 预期中的崩溃没有发生 —— 实验无效")
    except SimulatedCrash as exc:
        print(f"       崩溃已注入：{exc}")
    return RUN_ID


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def kill_process(store) -> None:
    """TODO ① ── 模拟「进程真的死了」：把只活在内存里的状态销毁掉。

    要求：内存版必须真的丢光（它的类上有一个方法专门干这件事）；
          磁盘版什么都不用做 —— 状态本来就不在进程里。

    提示：去看 `InMemoryCheckpointStore` 的方法列表，有一个方法名很直白；
          判断类型用 `isinstance(store, InMemoryCheckpointStore)`。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO ①  kill_process")
    # ↑↑↑ 你的答案 ↑↑↑
    # （磁盘版没有这个方法，什么都不做就是对的：它的状态在文件里）


def resume_after_restart(kind: str) -> dict:
    """走完一条完整链路（已经写好，不用改）。

    提交 → 第 2 步后进程被杀 → kill_process(store) → 换一个进程续跑。
    返回 {"saved": 崩溃时检查点在不在, "reason": 续跑的停机原因, "ok": 续跑成功没}
    """
    store = new_store(kind)
    run_id = submit_and_crash(store)
    saved = store.load(run_id) is not None
    kill_process(store)                                   # ← 你的答案在这里生效
    store2 = store if kind == "memory" else new_store(kind)   # 磁盘版：新进程读同一个目录
    resp = new_runtime(store2, f"{kind}-second").resume(run_id)
    return {"saved": saved, "reason": resp.reason, "ok": resp.reason == "final_answer",
            "has_checkpoint": store2.load(run_id) is not None}


# 写下你的结论（不写也不影响运行，main() 会把它打印出来）：
#   教学里的「假崩溃」为什么看起来能恢复？真实场景里丢掉的到底是什么？
CONCLUSION = ""


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def main() -> int:
    try:
        results = {}
        for idx, (kind, name) in enumerate([("memory", "内存版 InMemoryCheckpointStore"),
                                            ("file", "磁盘版 FileCheckpointStore")], start=1):
            print(f"\n    {'①②'[idx - 1]} {name}")
            results[kind] = resume_after_restart(kind)
            r = results[kind]
            print(f"       崩溃那一刻，检查点在不在？{r['saved']}")
            print(f"       换一个进程续跑 → reason={r['reason']!r}，"
                  f"续跑{'成功 ✅' if r['ok'] else '失败 ❌'}")

        mem, fil = results["memory"], results["file"]

        print()
        assert mem["saved"] is True, "崩溃时内存里当然还留着检查点（进程只是抛了个异常）"
        assert mem["ok"] is False, "内存版必须续跑失败（状态已经没地方找了）"
        assert mem["reason"] == "no_checkpoint", \
            f"内存版应该报 no_checkpoint，实际 {mem['reason']!r}"
        print("    ★ 内存版：即使 run_id 一模一样，也找不到任何东西可以恢复。")
        print("      「进程死了」和「抛了个异常」根本不是一回事 —— 前者会把 dict 一起带走。")

        assert fil["ok"] is True, "磁盘版必须能续跑成功"
        assert fil["reason"] == "final_answer", f"磁盘版应该跑完，实际 {fil['reason']!r}"
        print()
        print("    ★ 磁盘版：换一个全新的运行时（新进程、新 Agent、新 LLM 实例）")
        print("      照样能从 run_id 续上 —— 因为状态在**文件**里，不在进程里。")
        print()
        print("    ★ 所以教学里的「假崩溃」骗人在哪：")
        print("      `SimulatedCrash` 只是抛了个异常，那个 store / agent / 变量**全都还在内存里**；")
        print("      而生产里丢掉的是**整个进程** —— OOM Killer、Pod 被驱逐、发布重启。")
        print("      想看真实效果：在恢复之前把内存清掉（你上面写的那一行），或者新建一个空 dict。")
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
