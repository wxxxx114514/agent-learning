r"""第 09 章 · 练习 5 / 5 · 让检查点真的落盘（并亲眼看见「版本漂移」）

【要做什么】
  把 `Checkpoint.to_json()` 写进文件，再从文件读回来恢复。
  然后**故意在恢复前改掉图的结构**（比如删掉一个节点），观察 `resume()` 会怎么报错。

【已经给你了】
  make_checkpoint(tmp_dir)   跑一次「审批人不在线」的工单，返回挂起时的检查点
  save_checkpoint(cp, path)  把检查点写进文件（你要写的第一个 TODO 就是它的内容）
  load_checkpoint(path)      从文件读回检查点（已经写好，对照着看）
  resume_with(cp, graph)     用指定的图去恢复，返回 RunResult
  dismantle(graph)           把图拆掉一个节点（模拟"用旧检查点喂给新版图"）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch09_workflow\ex5_checkpoint_file.py
  3. 验收本章：py scripts\run_all_checks.py 09
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                                                    # noqa: E402

from core.console import bullet, code, kv, note, warn          # noqa: E402
from stages.stage09_workflow.demo import (                     # noqa: E402
    APPROVE, TICKET_LOGISTICS, Checkpoint, HumanChannel, RunResult, StateGraph, build_graph,
)

WORKDIR = Path(__file__).resolve().parent / ".sandbox"         # 练习自己的沙箱目录
CP_FILE = WORKDIR / "ticket_checkpoint.json"


def make_checkpoint(tmp_dir: Path) -> Checkpoint:
    """跑一次「审批人不在线」的工单 → 拿到挂起时的检查点。"""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    graph = build_graph()
    result = graph.run(dict(TICKET_LOGISTICS), human=HumanChannel([]))   # 没人在线 → 挂起
    assert result.status == "interrupted" and result.checkpoint is not None, "预期是挂起"
    return result.checkpoint


def load_checkpoint(path: Path) -> Checkpoint:
    """从文件读回检查点（已经写好 —— 你要写的是反方向的 save）。"""
    return Checkpoint.from_json(path.read_text(encoding="utf-8"))


def resume_with(checkpoint: Checkpoint, graph: StateGraph | None = None,
                reply: dict | None = None) -> RunResult:
    """用一个（可能是新版本的）图去恢复检查点。

    `reply` 是恢复后交给人工节点的答复，默认「批准」。
    """
    return (graph or build_graph()).resume(
        checkpoint, human=HumanChannel([dict(reply or APPROVE)]))


def dismantle(graph: StateGraph) -> StateGraph:
    """模拟「版本漂移」：新版图里，检查点记录的那个节点已经没了。

    生产里这种事天天发生：发布新版本时删掉/改名了一个节点，
    而队列里还躺着用旧版图存下来的检查点。
    """
    gone = graph.nodes.pop("human_review")
    graph.edges = [e for e in graph.edges if e.src != gone.name and e.dst != gone.name]
    graph.conditionals = [c for c in graph.conditionals if c.src != gone.name]
    return graph


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================

def save_checkpoint(checkpoint: Checkpoint, path: Path) -> None:
    """TODO ── 把检查点写进文件（落盘）。

    两行就够：
      ① 确保父目录存在：path.parent.mkdir(parents=True, exist_ok=True)
      ② 写进去：path.write_text(checkpoint.to_json(), encoding="utf-8")
         —— 注意是 `checkpoint.to_json()`（**字符串**），不是 to_json(indent=2) 之后再 json.loads
            （indent 只影响好看程度，读写都行，随你）

    ★ 为什么这一步是本章的分水岭？
      `state` 是纯 JSON，所以检查点能落盘、能进 Redis、能被**另一个进程**接手。
      如果谁把模型客户端或回调函数塞进了 state，这一行当场就会报 TypeError。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 5 · TODO ①  save_checkpoint")
    # ↑↑↑ 你的答案 ↑↑↑


def restore_after_removing_node(checkpoint: Checkpoint, graph: StateGraph) -> tuple[str, str]:
    """TODO ── 故意用「缺了节点的图」去恢复，把发生的事如实报告出来。

    步骤：
      ① fresh = build_graph()                 ← 一个全新的引擎（模拟"换了进程"）
      ② dismantle(fresh)                      ← 把 human_review 节点删掉
      ③ result = resume_with(checkpoint, fresh)   ← 用这个残图去恢复检查点
      ④ 返回 (result.status, result.error 或 "（没有报错）")

    提示：引擎不会抛异常给你 —— 它把"节点不存在"变成了一次
          `RunResult(status="error", error="节点不存在：human_review")`。
          想一想：**为什么宁可返回 error 也不抛异常？**
          （提示：宿主进程不该因为一个旧检查点就崩掉；失败要能被上层看见并记进日志。）
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 5 · TODO ②  restore_after_removing_node")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================

def check_5() -> None:
    WORKDIR.mkdir(parents=True, exist_ok=True)

    # ① 落盘
    original = make_checkpoint(WORKDIR)
    save_checkpoint(original, CP_FILE)
    if not CP_FILE.exists():
        raise AssertionError(f"检查点文件没生成：{CP_FILE}（save_checkpoint 还没写？）")
    raw = CP_FILE.read_text(encoding="utf-8")
    if not raw.strip():
        raise AssertionError("检查点文件是空的")
    try:
        payload = json.loads(raw)
    except ValueError as exc:
        raise AssertionError(f"落盘的内容不是合法 JSON：{exc}") from exc

    kv("检查点文件", f"{CP_FILE.name}（{len(raw)} 字符）")
    kv("JSON 顶层字段", ", ".join(payload.keys()))
    kv("挂起在哪个节点", f"{payload['node']}（恢复时从这里继续）")
    kv("state 里的关键判断", f"category={payload['state'].get('category')}, "
                            f"draft 已生成={bool(payload['state'].get('draft'))}, "
                            f"模型调用={payload['llm_calls']} 次")
    print()
    note("★ 这段 JSON 就是「断点续跑」的全部秘密：判断结果都在里面，恢复时不用重算。")
    code(raw[:220] + ("…" if len(raw) > 220 else ""), indent=4)
    print()

    # ② 读回来 + 原图恢复：必须和一次跑完的结果一致
    restored = load_checkpoint(CP_FILE)
    if restored.to_json() != original.to_json():
        raise AssertionError("从文件读回来的检查点和原来不一致（落盘/读回有损）")
    full = build_graph().run(dict(TICKET_LOGISTICS),
                             human=HumanChannel([dict(APPROVE)]))
    resumed = resume_with(restored)
    if resumed.status != "completed" or resumed.final_reply != full.final_reply:
        raise AssertionError(
            f"恢复结果应当与一次跑完完全一致："
            f"status={resumed.status} vs {full.status}")
    if resumed.visits.get("classify") != 1 or resumed.visits.get("draft_reply") != 1:
        raise AssertionError(
            f"恢复不能重跑已完成的节点，实际 visits={dict(resumed.visits)}")
    if resumed.llm_calls != original.llm_calls:
        raise AssertionError(
            f"恢复过程不该产生新的模型调用：{original.llm_calls} → {resumed.llm_calls}")
    kv("读回后恢复", f"status={resumed.status}，路径={' → '.join(resumed.history)}")
    kv("  模型调用", f"{original.llm_calls} 次（原始）→ {resumed.llm_calls} 次（恢复后，没有新增）")
    print()

    # ③ 版本漂移：用缺了节点的图去恢复
    status, error = restore_after_removing_node(restored, build_graph())
    print("    版本漂移（检查点是用旧版图存的，新版图删掉了一个节点）：")
    print(f"      恢复结果 → status={status!r}")
    print(f"      错误信息 → {error[:70]}")
    print()
    if status != "error":
        raise AssertionError(
            f"节点都没了，恢复不该'成功'（现在 status={status!r}）—— 这正是版本漂移的坑")
    if "human_review" not in error:
        raise AssertionError(f"错误信息里应当指名道姓说是哪个节点不存在，现在是：{error[:70]}")

    kv("你的实现", "落盘 → 读回 → 原图恢复成功 / 残图恢复 = error（可定位）")
    print()
    warn("★ 生产里这叫「版本漂移」：检查点用旧版图存的，新版图已经不一样了。")
    warn("  标准做法是在检查点里存一个 graph_version 并做兼容校验 —— 否则你会得到一个")
    warn("  「能恢复、但恢复出来的状态没人认识」的诡异 bug。")
    bullet("检查点必须是纯 JSON：能落盘、能进 Redis、能被另一个进程接手")
    bullet("resume 返回 error 而不是抛异常：宿主进程不崩，失败也能被看见、被记录")
    bullet("换进程恢复 = 0 次新模型调用：分类结果、订单结论、草稿全都躺在文件里")


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
