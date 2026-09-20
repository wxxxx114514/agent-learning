r"""第 07 章 · 练习 3 / 5 · 给经验库加失效机制：教训也有寿命

【要做什么】
  **给经验库加失效机制。**
  现在的经验库只增不减。改成：一条教训被后续 3 次同类任务证明「已经不再出错」后，
  降低它的优先级（或归档）。

【已经给你了】
  · Lesson：课程里那条结构化教训（kind / mistake / fix / source）
  · TrackedLesson：教训 + `success_streak`（连续几次同类任务没再犯）
  · TrackedMemory.as_prompt(kind)：**已经改好了** —— 只注入 success_streak < limit 的教训
  · 一次模拟流程（4 步）已经写好，你只要补 decay()

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch07_reflection\ex3_lesson_decay.py
  3. 验收本章：py scripts\run_all_checks.py 07
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
from core.console import bullet, kv, note, warn                        # noqa: E402
from stages.stage07_reflection.demo import Lesson, LESSON_HINT         # noqa: E402

ARCHIVE_AFTER = 3          # 连续 3 次同类任务没再犯 → 这条教训退场（题面里的数字）


@dataclass
class TrackedLesson:
    """一条带「战绩」的教训。"""

    lesson: Lesson
    success_streak: int = 0


class TrackedMemory:
    """只增不减的经验库 → 有寿命的经验库。"""

    def __init__(self, limit: int = ARCHIVE_AFTER) -> None:
        self.items: list[TrackedLesson] = []
        self.limit = limit
        self.retired: list[str] = []          # 已经退场的教训（归档区）

    def add(self, lesson: Lesson) -> None:
        if all(x.lesson != lesson for x in self.items):
            self.items.append(TrackedLesson(lesson))

    def as_prompt(self, kind: str) -> str:
        """只注入**还没失效**的教训（success_streak < limit）。不用改。"""
        live = [x for x in self.items if x.lesson.kind == kind and x.success_streak < self.limit]
        if not live:
            return ""
        head = "历史教训（同类任务曾经失败过，开工前务必避免）：\n"
        return head + "\n".join(x.lesson.render() for x in live)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def decay(memory: TrackedMemory, kind: str, succeeded: bool) -> list[str]:
    """TODO ── 一次同类任务跑完后，更新经验库的「战绩」。

    规则（就照着这两条写）：
      · succeeded=True  → 这条教训的 success_streak += 1；
                          如果正好达到 memory.limit，把它**退场**（记进返回值和 memory.retired）
      · succeeded=False → success_streak 清零（教训刚刚又被证明有用，不能退场）

    只处理 lesson.kind == kind 的条目（别的任务的战绩与它无关）。
    返回：本次新退场的教训描述（没有就返回 []）。
    """
    retired: list[str] = []
    for entry in memory.items:
        if entry.lesson.kind != kind:
            continue
        # ↓↓↓ 把下面这行删掉，写上你的答案（4~6 行）↓↓↓
        raise NotImplementedError("练习 3 · TODO  decay")
        # ↑↑↑ 你的答案 ↑↑↑
    return retired
# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================


def line(title: str, memory: TrackedMemory, kind: str = "销售速报") -> str:
    prompt = memory.as_prompt(kind)
    n = prompt.count("- 在「")                    # 注入了几条教训
    print(f"  {title:<34}streak={[x.success_streak for x in memory.items]}"
          f"  归档={len(memory.retired)}  注入教训={n} 条（{len(prompt)} 字）")
    return prompt


def check() -> str:
    memory = TrackedMemory()
    lesson = Lesson(kind="销售速报", mistake="合计写成了 801（少算 10 元）",
                    fix=LESSON_HINT, source="2025Q1 销售速报")
    memory.add(lesson)

    print("\n" + "=" * 66)
    print(f"  模拟：一条教训的完整生命周期（ARCHIVE_AFTER = {ARCHIVE_AFTER}）")
    print("=" * 66)
    first = line("① 第一次失败后记下教训", memory)
    if not first:
        raise NotImplementedError("练习 3 · TODO  decay 之前，as_prompt() 应该能注入这条教训")

    for i in range(1, ARCHIVE_AFTER + 1):
        decay(memory, "销售速报", succeeded=True)
        line(f"② 第 {i} 次同类任务成功", memory)

    live_before = memory.as_prompt("销售速报")
    if live_before:
        raise NotImplementedError(
            f"练习 3 · TODO  decay 还没生效：连续 {ARCHIVE_AFTER} 次成功后教训仍在注入")
    if not memory.retired:
        raise NotImplementedError("练习 3 · TODO  decay 忘了把退场的教训记进返回值/归档区")

    third = line("③ 同类任务换成别的类型（不相关）", memory, kind="数据周报")
    if third:
        raise NotImplementedError("练习 3 · TODO  别的任务类型不该看到这条教训")

    decay(memory, "销售速报", succeeded=False)
    after_fail = line("④ 又一次失败 → 教训重新生效", memory)
    if not after_fail:
        raise NotImplementedError("练习 3 · TODO  decay 忘了在失败时把 success_streak 清零")

    print()
    kv("归档区", f"{len(memory.retired)} 条：{'；'.join(memory.retired)}")
    note("现象：经验库从「只增不减」变成了**有进有出** —— 上下文预算花在真正还会犯的错上。")
    note("想一想：这和第 05 章的「记忆遗忘策略」是不是同一个问题？")
    warn("（是 —— 都是「在有限预算里保留最高价值的信息」。）")
    bullet("退了场的教训别删，放进归档区：下次同类任务真又失败了，可以直接复活它。")
    bullet("教训要有来源与战绩，否则你分不清「它过时了」和「它还没被验证过」。")
    return (f"连续 {ARCHIVE_AFTER} 次成功后归档 1 条；失败一次后重新生效")


def main() -> int:
    try:
        summary = check()
    except NotImplementedError as exc:
        print(f"⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"❌ 报错了：{type(exc).__name__}: {exc}")
        return 1
    print()
    print(f"  → {summary}")
    print("✅ 跑通了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
