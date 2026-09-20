r"""第 05 章 · 练习 1 / 5 · 给钉住区加「优先级抢占」

【要做什么】
  现在 `MAX_PINNED = 8`，超出的事实按重要性排序后**直接丢弃**。
  请改成「新事实抢占最低优先级的旧事实」，并打印每一次抢占（谁挤掉了谁）。

  想清楚：被挤掉的事实要不要写进长期存储？

【已经给你了】
  · Fact                一条结构化事实：key / value / importance / turn / pinned
                        .text -> "姓名：张三"，.fingerprint -> "姓名=张三"
  · LongTermStore       长期记忆的写入与检索（store.write(fact) / store.items / store.render）
  · MAX_PINNED          钉住区上限（真实值 8）
  · INCOMING            10 条事实：**重要性从低到高**依次到达 —— 专门用来触发抢占
  · run_experiment(...) 把 INCOMING 依次喂给你的 pin_new 的成品代码（记账也写好了）

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch05_memory\ex1_pin_preemption.py
  3. 验收本章：py scripts\run_all_checks.py 05
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from stages.stage05_memory.memory import (   # noqa: E402
    MAX_PINNED, Fact, LongTermStore,
)

# 10 条事实，**重要性从低到高**依次到达：
# 先来的都是「偏好」这种锦上添花的信息，后来的才是「过敏」「姓名」这种丢了会出事的信息。
INCOMING = [
    Fact("偏好", "靠窗", importance=0.55, turn=1),
    Fact("偏好", "包间", importance=0.55, turn=2),
    Fact("偏好", "安静", importance=0.50, turn=3),
    Fact("人数", "24", importance=0.78, turn=4),
    Fact("日期", "3 月 15 日", importance=0.80, turn=5),
    Fact("禁忌", "辣", importance=0.88, turn=6),
    Fact("订单号", "A1001", importance=0.92, turn=7),
    Fact("预算", "5000", importance=0.98, turn=8),
    Fact("姓名", "张三", importance=1.00, turn=9),
    Fact("饮食禁忌", "海鲜", importance=1.00, turn=10),
]


def run_experiment(max_pinned: int = 3) -> dict:
    """把 INCOMING 依次喂进钉住区，记录每一次抢占。**成品代码，不用改。**"""
    pinned: list[Fact] = []
    store = LongTermStore()
    log: list[str] = []
    for fact in INCOMING:
        evicted = pin_new(pinned, fact, store, max_pinned=max_pinned)
        if evicted is not None:
            log.append(f"{fact.text} 挤掉了 {evicted.text}"
                       f"（{fact.importance:.2f} > {evicted.importance:.2f}）")
    return {"pinned": pinned, "store": store, "log": log, "max_pinned": max_pinned}


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def pin_new(pinned: list[Fact], fact: Fact, store: LongTermStore,
            max_pinned: int = MAX_PINNED) -> Fact | None:
    """把新事实放进钉住区；名额满了就抢占最弱的一条。返回**被挤掉的事实**（没挤掉则 None）。

    参数 pinned   ：当前的钉住区（list[Fact]，**就地修改**）
         fact     ：新到达的事实
         store    ：长期存储（被挤掉的事实必须落库，否则它就真的丢了）
         max_pinned：钉住区上限

    前后都写好了（判重 + 返回值语义），你写中间三种情况。

    TODO ── 按顺序写三段：

      ① 名额没满（len(pinned) < max_pinned）
             pinned.append(fact)；返回 None

      ② 名额满了：先找出**最弱**的一条
             weakest = min(pinned, key=lambda f: (f.importance, -f.turn))
             （重要性相同时，-turn 让「后来才确认的那条」先被挤掉）

         然后判断新事实够不够强：
           · fact.importance > weakest.importance
                 -> store.write(weakest)   ★ 落库，不能丢
                    pinned.remove(weakest)；pinned.append(fact)；返回 weakest
           · 否则新事实进不来：返回 None（它虽然没进钉住区，但仍在长期存储里）

    提示：别忘了情况 ①。忘了它，前 3 条事实一条都进不去。
    """
    if any(f.fingerprint == fact.fingerprint for f in pinned):
        return None          # 同一条事实重复到达，不占新名额（这段送给你）

    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO  pin_new：名额没满 / 满了要抢占，两种情况都要处理")
    # ↑↑↑ 你的答案 ↑↑↑


# TODO ② ── 纯思考题：写下你的结论（一两句话就行）
#   提示：想想「钉住区」和「长期存储」分别解决什么问题 ——
#         一个是「当前上下文的名额」，一个是「跨会话的存储」。
#         被挤出去的事实如果不写进 store，它下次还能被召回吗？
CONCLUSION = ""      # ← 在这里写下你的结论


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    report: list[str] = []
    try:
        LIMIT = 3                     # 故意把上限压到 3，抢占才看得清
        got = run_experiment(max_pinned=LIMIT)
        pinned, store, log = got["pinned"], got["store"], got["log"]

        if len(pinned) > LIMIT:
            raise AssertionError(f"钉住区超限了：{len(pinned)} 条 > 上限 {LIMIT}")
        if len(pinned) < LIMIT:
            raise AssertionError(
                f"钉住区只装了 {len(pinned)} 条，上限是 {LIMIT} —— "
                "检查 TODO 的「名额没满」那一支是不是漏了")

        strongest = sorted(INCOMING, key=lambda f: -f.importance)[:LIMIT]
        want = sorted(f.fingerprint for f in strongest)
        got_fp = sorted(f.fingerprint for f in pinned)
        if got_fp != want:
            raise AssertionError(
                f"最后留在钉住区的应该是最强的 {LIMIT} 条 {want}，实际 {got_fp}")

        evicted_count = len(INCOMING) - LIMIT
        if len(store.items) < evicted_count:
            raise AssertionError(
                f"被挤掉的事实必须全部写进长期存储：应该有 {evicted_count} 条，"
                f"实际 {len(store.items)} 条 —— 检查那一步有没有调 store.write()")
        stored_texts = {it.text for it in store.items}
        for text in ("偏好：靠窗", "偏好：包间", "偏好：安静"):
            if text not in stored_texts:
                raise AssertionError(f"被挤掉的 {text!r} 没落库，它就真的丢了")

        report.append(f"钉住区上限 = {LIMIT}，{len(INCOMING)} 条事实按「先弱后强」依次到达：")
        report.append("")
        report.append("    每一次抢占：")
        for line in log:
            report.append(f"      {line}")
        report.append("")
        report.append(f"    最终钉住区（{len(pinned)} 条，都是最强的）：")
        for f in pinned:
            report.append(f"      - {f.text}（重要性 {f.importance:.2f}）")
        report.append("")
        report.append(f"    长期存储（{len(store.items)} 条，被挤掉的一条都没丢）：")
        for line in store.render(store.items).splitlines()[:8]:
            report.append(f"      {line}")
        report.append("")
        report.append("★ 两个关键设计：")
        report.append("  ① 「永不淘汰」的机制**必须自带配额** —— 钉住区没上限就会挤爆窗口")
        report.append("     （练习 3 会把上限改成 1000，你会亲眼看到窗口被挤到 1 轮）；")
        report.append("  ② 被挤掉 ≠ 被删除：它必须落进长期存储，下次还能被检索回来。")
        report.append("     钉住区管的是「当前上下文的名额」，不是「存储」。")
        report.append("")
        report.append(f"★ 你的结论：{CONCLUSION or '（还没写）'}")
        if not CONCLUSION.strip():
            raise NotImplementedError("练习 1 · TODO ②  写下你的结论")
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
