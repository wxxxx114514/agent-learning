"""第 07 章 · 反思与自我修正 —— Notebook 内容（逐步推进版）。

遵守 TEACHING_CONTRACT.md：
  · 逐步给：每个知识点在「读者正好需要」时出现
  · 前置知识表保留在 ⓪，定位是索引（可跳过）
  · 每个代码单元自包含（nb_lint 机器校验）
  · 中文引号一律用 「」，代码单元里只用 GBK 也能编码的符号
"""

from __future__ import annotations

from notebooks.nb_blocks import (
    checkpoint,
    exercises,
    header,
    objectives,
    pitfall_table,
    section,
    setup_cell,
    summary,
)
from notebooks.notebook_lib import Notebook


def build_07() -> Notebook:
    """第 07 章 · 反思与自我修正（逐步推进版）。"""
    nb = Notebook("第 07 章 · 反思与自我修正")

    header(
        nb, "07", "反思与自我修正",
        "反思 = `换个视角检查自己的输出` → `产出具体可执行的修正`。\n"
        "没有「具体修正」的反思只是废话；没有「验证器」的反思只是自我安慰。",
    )

    objectives(nb, [
        "说清「自评为什么不可靠」（self-consistency bias），以及代码验证器为什么更强",
        "写出一份**确定性验证器**：重算每一个数字，并记录它到底检查了什么",
        "说清一条**有效反馈**的三要素：位置 + 事实 + 动作",
        "实现 Reflexion 主循环（生成 → 审查 → 修正 → 再验证），并把**三道刹车**写进结构里",
        "区分三种停机原因（`verified_pass` / `no_progress` / `max_rounds`），"
        "并知道什么情况下必须把**未闭环的异议**交给用户",
        "把失败沉淀成**结构化经验**，让同一个坑只踩一次",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

前面的 Agent 已经能查资料（第 06 章）、能规划（第 04 章）、能记东西（第 05 章）。
但它有一个致命盲区：**它错了，它自己不知道。**

本章按这个顺序拆：

```
① 先看现场：三个分项全对，合计错了 10 元，而它很自信
② 新手的第一反应「你再仔细检查一遍」为什么没用  -> 自评 vs 代码验证
③ 什么反馈才有效：位置 + 事实 + 动作            -> 笼统派对具体派的对照实验
④ Reflexion 主循环：把三道刹车写进结构里         -> 什么时候必须停
⑤ 经验库：让同一个坑只踩一次                    -> 反思的收益怎么留存
⑥ 常见坑
```

全部离线可跑：这里用几个**确定性的假模型**精确复现真实模型的两条行为规律
（对具体反馈敏感、对笼统反馈免疫），所以同一条因果链你可以跑一百遍，结论都一样。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `dataclass(frozen=True)` | 标准库 `dataclasses` | 不可变的数据结构 | 字段赋值会抛 `FrozenInstanceError` |
| `re.search` | 标准库 `re` | 找第一个匹配 | → `Match` 或 `None` |
| `re.finditer` | 标准库 `re` | 逐个找出所有匹配 | 产生 `Match` 流（用来抽"把 X 改成 Y"） |
| `field(default_factory=list)` | 标准库 `dataclasses` | 可变默认值 | 别写成 `= []` |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `LLM` / `LLMResponse` | `core.llm` | 模型基类：实现 `_complete(messages)`；`llm.total_calls` 自动记调用次数 |
| `Message` | `core.message` | 消息：`Message.system(文本)` / `.user(文本)` / `.assistant(文本)` |

> 完整实现（含 7 个小节与 17 项自检）在 `stages/stage07_reflection/demo.py`。
> 本章把它拆成"一次只讲一件事"，每格都能单独跑。

### 随时可查

```python
explain(LLM)        # 模型基类：要实现哪个方法、返回什么
explain(Message)    # 消息结构与四个构造方法
explain()           # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "它错了，它自己不知道")

    nb.md("""### 现在卡在哪

让模型写一份销售速报（三个商品的小计 + 一个合计）。它交出来的是这样：

```
   2025 年 Q1 销售速报
   分项：
   - A 商品：17 件 × 23 元 = 391 元
   - B 商品：8 件 × 45 元 = 360 元
   - C 商品：5 件 × 12 元 = 60 元
   合计：801 元                     <- 391+360+60 = 811，少了 10 元
   结论：本季度销售整体稳健，建议优先补货 A 商品。
```

三个分项全对，**合计错了 10 元**。而模型对自己的产出非常自信 ——
它不会说「我可能算错了」。

### 所以我需要一个「能判定对错」的东西

注意这里的关键：**「合计 = 逐项之和」是确定的**。
也就是说，这件事的对错**能被代码判定** —— 那就轮不到模型来"感觉"。

```
   生成     ：写一份速报          <- 语言能力，会错
   自评     ：你觉得写得怎么样？    <- 同一套语言能力，会放水
   验证     ：391+360+60 等于几？  <- 事实源 + 规则，100% 确定，且 0 次调用
```

### 它的用法

一个验证器要做三件事：

```python
class ReportVerifier:
    def check(self, text, task) -> Verdict:
        # ① 逐项重算：不信任文本里的任何数字，直接用事实源算
        # ② 合计必须等于逐项之和（模型最容易错、也最容易验的一步）
        # ③ 格式契约：交付物必须包含「结论：」段落（下游系统靠它做摘要）
```

返回的 `Verdict` 里有三个字段，每一个都有用：

| 字段 | 含义 | 为什么需要 |
|---|---|---|
| `ok` | 是否通过 | 停机判据 |
| `issues` | 问题列表 | **直接就是给模型的修正意见** |
| `checked` | 做过哪些检查 | 可审计、可回归、能写进测试 |

### 立刻用一次""")

    nb.code('''# 单独可运行：事实源 + 会算错的写作模型 + 确定性验证器
import sys, pathlib, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.llm import LLM, LLMResponse
from core.message import Message


# ============ 1. 事实源：反思要有一个可以对照的真相 ============
@dataclass(frozen=True)
class Rec:
    """一条销售记录。★ frozen=True：事实源在反思过程中**绝不能被改写** ——
    如果"正确答案"会随对话漂移，验证器就失去意义了。"""
    sku: str
    qty: int
    price: int

    @property
    def subtotal(self) -> int:
        return self.qty * self.price


@dataclass(frozen=True)
class Task:
    """一个"写销售速报"的任务。"""
    key: str                       # 任务编号（经验库溯源用）
    kind: str                      # 任务类型（经验库按类型复用）
    title: str
    records: tuple

    def correct_total(self) -> int:
        return sum(r.subtotal for r in self.records)

    def wrong_total(self) -> int:
        """假模型"心算"出来的错误合计：刻意少算 10 元。

        这模拟真实模型最常见的错误：长表达式心算漏进位/漏一项。
        两个同类任务犯的是**同一类错**，第 ⑤ 节才能演示"教训能迁移"。
        """
        return self.correct_total() - 10

    def table_text(self) -> str:
        return "\\n".join(f"- {r.sku}：{r.qty} 件 × {r.price} 元" for r in self.records)

    def formula_text(self) -> str:
        return " + ".join(str(r.subtotal) for r in self.records)


TASK_Q1 = Task("2025Q1", "销售速报", "2025 年 Q1 销售速报", (
    Rec("A 商品", 17, 23),      # 391
    Rec("B 商品", 8, 45),       # 360
    Rec("C 商品", 5, 12),       # 60  -> 合计 811
))
TASK_Q2 = Task("2025Q2", "销售速报", "2025 年 Q2 销售速报", (
    Rec("A 商品", 12, 31),      # 372
    Rec("B 商品", 9, 28),       # 252
    Rec("C 商品", 4, 15),       # 60  -> 合计 684
))

SYSTEM_TMPL = """你是一名数据分析助理，负责撰写销售速报。

# 任务
根据给定的商品明细产出速报，格式必须严格如下：
{title}
分项：
- <商品>：<数量> 件 × <单价> 元 = <小计> 元
合计：<逐项之和> 元
结论：<一句话结论>

# 事实源（只读，不得修改）
{table}

{lessons}"""

REQUEST_TMPL = "请写出「{title}」。只输出报告正文，不要解释。"


# ============ 2. 写作模型（假模型，但遵守真实规律） ============
LESSON_HINT = "写出合计前必须逐项重算"


class ReportWriterLLM(LLM):
    """扮演"写作 Agent"的假模型：负责产出速报正文。

    它有两条真实规律：
      规律 1：给**具体到字符**的修改意见（把 X 改成 Y），它会照做；
              给**笼统**的建议，它只会改措辞（"销售速报（修订稿）"）。
      规律 2：系统提示词里写了历史教训，它会遵守（开工前先把合计算对）。
    """

    name = "report-writer"

    def __init__(self, task, model="mock-writer"):
        super().__init__(model)
        self.task = task
        self.drafts = []            # 每次产出的原稿，便于断言"到底改没改"

    def _complete(self, messages, **kwargs):
        system = messages[0].content
        user_msgs = [m.content for m in messages if m.role == "user"]
        feedback = user_msgs[-1] if len(user_msgs) > 1 else ""      # 第 1 条是任务书

        # ---- 规律 2：读到教训就按教训做（开写前先把合计算对）----
        remembers = LESSON_HINT in system and self.task.kind in system
        total = self.task.correct_total() if remembers else self.task.wrong_total()
        text = self._render(total)

        # ---- 规律 1：只认「把 X 改成 Y」这种可执行的反馈 ----
        applied = []
        for m in re.finditer(r"把\\s*(\\d+)\\s*改成\\s*(\\d+)", feedback):
            old, new = m.group(1), m.group(2)
            if old in text:
                text = text.replace(old, new)
                applied.append(f"{old} -> {new}")
        if feedback and not applied:
            # 收到一堆"建议"却没有具体动作 -> 只能改改标题措辞，事实分毫未动。
            # 这正是真实世界里"反思了个寂寞"的样子。
            text = text.replace("销售速报", "销售速报（修订稿）")

        self.drafts.append(text)
        return LLMResponse(text=text)

    def _render(self, total):
        lines = [self.task.title, "分项："]
        lines += [f"- {r.sku}：{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
                  for r in self.task.records]
        lines.append(f"合计：{total} 元")
        lines.append("结论：本季度销售整体稳健，建议优先补货 A 商品。")
        return "\\n".join(lines)


def first_draft(task):
    """单独拿到"第一次生成"的原稿（还牵着后面几节的对照实验）。"""
    writer = ReportWriterLLM(task)
    return writer.complete([
        Message.system(SYSTEM_TMPL.format(title=task.title, table=task.table_text(),
                                          lessons="（暂无历史教训）")),
        Message.user(REQUEST_TMPL.format(title=task.title)),
    ]).text


# ============ 3. 验证器：不靠"感觉"，只靠重算 ============
@dataclass
class Verdict:
    """验证结论。issues 为空 = 通过；checked 记录"我到底检查了什么"。"""
    ok: bool
    issues: list = field(default_factory=list)
    checked: list = field(default_factory=list)


class ReportVerifier:
    """确定性验证器：重算每一个数字，校验格式契约。**一次模型调用都不需要。**"""

    name = "report-verifier"

    def check(self, text, task) -> Verdict:
        issues, checked = [], []

        # ① 逐项重算：不信任文本里的任何数字，直接拿事实源算
        for r in task.records:
            want = f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
            checked.append(f"分项 {r.sku}：数量 × 单价 = {r.subtotal}")
            if want not in text:
                issues.append(f"分项「{r.sku}」缺失或金额不等于 {r.subtotal} 元（应为 {want}）")

        # ② 合计必须等于逐项之和（模型最容易错、也最容易验的一步）
        total = task.correct_total()
        checked.append(f"合计 = {task.formula_text()} = {total}")
        m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
        if not m:
            issues.append(f"缺少「合计：{total} 元」这一行")
        elif int(m.group(1)) != total:
            got = int(m.group(1))
            # ★ 错误信息里直接带上正确值 —— 这句话本身就是一条可执行的修正意见
            issues.append(f"合计错误：逐项重算应为 {total}，你写成了 {got}；请把 {got} 改成 {total}")

        # ③ 格式契约：交付物必须包含结论段（下游系统靠它做摘要）
        checked.append("必须包含「结论：」段落")
        if "结论：" not in text:
            issues.append("缺少「结论：」段落，交付格式不合规")

        return Verdict(ok=not issues, issues=issues, checked=checked)


# ============ 4. 跑一次：错在哪，一眼看清 ============
draft = first_draft(TASK_Q1)
print("模型交出的初稿：")
print("    " + draft.replace("\\n", "\\n    "))
print()
verdict = ReportVerifier().check(draft, TASK_Q1)
got = int(re.search(r"合计[:：]\\s*(\\d+)\\s*元", draft).group(1))

print("模型自己的说法 : 报告已生成（它并不知道自己算错了）")
print(f"文本里的合计   : 合计：{got} 元")
print(f"验证器逐项重算 : {TASK_Q1.formula_text()} = {TASK_Q1.correct_total()} 元")
print(f"差了多少       : {TASK_Q1.correct_total() - got} 元")
print(f"验证器结论     : {'通过' if verdict.ok else '不通过'}")
for i in verdict.issues:
    print("    -", i)
print()
print("验证器做过哪些检查（可审计、可回归、能直接写进测试）：")
for c in verdict.checked:
    print("    -", c)
print()
print("★ 注意验证器**一次模型调用都没用**：它只做算术和字符串检查。")
print("  快、免费、100% 稳定 —— 所以「能由代码判定的事，永远不要交给模型」。")''')

    nb.md("""### 结果说明什么

- 模型给的三个分项全对，**合计错了 10 元**，而它自己完全没有察觉；
- 验证器不需要任何模型调用，就把错误抓出来，而且**说清了错在哪、正确值是多少**；
- `checked` 字段是很多人会漏掉的设计：**验证器必须能说清"我检查了什么"**。
  没有它，你没法回答"这条检查到底跑没跑"。

现在有了裁判。但新手的第一反应通常不是写验证器，而是加一句提示词。""")

    # ==================================================================
    section(nb, "②", "「你再仔细检查一遍」为什么没用")

    nb.md("""### 现在卡在哪

新手看到合计错了，第一反应是加一句提示词：

```python
"请你再仔细检查一遍上面的内容，确认无误后再输出。"
```

跑一下，你会得到：

```
   整体结构清晰、逻辑通顺、语言表达自然，建议进一步打磨细节，
   确保数据准确、结论更有深度，表述更加凝练。
```

**合计还是 801。** 这段"自评"一个字都没改，还吃掉了一次模型调用。

### 为什么会这样

因为**自评和生成用的是同一个模型、同一套先验**。
它算错的地方，它同样看不出来 —— 这就是 `self-consistency bias`。
指望它"再想一遍就想对了"，等于指望同一个人用同样的思路得出不同结论。

### 所以要么换个问题，要么换个裁判

| | 生成 | 自评 | 验证（verifier） |
|---|---|---|---|
| 问题 | 写一份速报 | 你觉得写得怎么样？ | 391+360+60 等于几？ |
| 依据 | 语言能力 | 语言能力（同一套） | **事实源 / 规则** |
| 结论 | 文本 | 「整体不错」 | 是 / 否，可复现 |
| 成本 | 1 次调用 | 1 次调用 | **0 次调用** |
| 可靠 | 会错 | **会放水** | 100% 确定 |

### 立刻用一次：把"自评"和"验证"摆在一起看""")

    nb.code('''# 单独可运行：让模型"自己再检查一遍" vs 让代码验证
import sys, pathlib, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.llm import LLM, LLMResponse
from core.message import Message


# ---- 事实源（和 ① 节同一套，精简版）----
@dataclass(frozen=True)
class Rec:
    sku: str
    qty: int
    price: int

    @property
    def subtotal(self):
        return self.qty * self.price


@dataclass(frozen=True)
class Task:
    key: str
    kind: str
    title: str
    records: tuple

    def correct_total(self):
        return sum(r.subtotal for r in self.records)

    def wrong_total(self):
        return self.correct_total() - 10

    def table_text(self):
        return "\\n".join(f"- {r.sku}：{r.qty} 件 × {r.price} 元" for r in self.records)

    def formula_text(self):
        return " + ".join(str(r.subtotal) for r in self.records)


TASK = Task("2025Q1", "销售速报", "2025 年 Q1 销售速报", (
    Rec("A 商品", 17, 23), Rec("B 商品", 8, 45), Rec("C 商品", 5, 12)))

SYSTEM_TMPL = """你是数据分析助理，负责撰写销售速报。
# 事实源（只读）
{table}
格式：{title} / 分项：… / 合计：… 元 / 结论：…
{lessons}"""


class WriterLLM(LLM):
    """会算错的写作模型（规律同 ① 节）。"""

    name = "writer"

    def _complete(self, messages, **kwargs):
        system = messages[0].content
        users = [m.content for m in messages if m.role == "user"]
        feedback = users[-1] if len(users) > 1 else ""
        remembers = "写出合计前必须逐项重算" in system
        total = TASK.correct_total() if remembers else TASK.wrong_total()
        text = self._render(total)
        applied = False
        for m in re.finditer(r"把\\s*(\\d+)\\s*改成\\s*(\\d+)", feedback):
            if m.group(1) in text:
                text = text.replace(m.group(1), m.group(2))
                applied = True
        if feedback and not applied:
            text = text.replace("销售速报", "销售速报（修订稿）")     # 只能改措辞
        return LLMResponse(text=text)

    def _render(self, total):
        lines = [TASK.title, "分项："]
        lines += [f"- {r.sku}：{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" for r in TASK.records]
        lines.append(f"合计：{total} 元")
        lines.append("结论：本季度销售整体稳健，建议优先补货 A 商品。")
        return "\\n".join(lines)


class SelfReviewLLM(LLM):
    """扮演"被要求自评"的同一个模型：它只会说场面话。"""

    name = "self-review"

    def _complete(self, messages, **kwargs):
        return LLMResponse(text=(
            "整体结构清晰、逻辑通顺、语言表达自然，建议进一步打磨细节，"
            "确保数据准确、结论更有深度，表述更加凝练。"))


@dataclass
class Verdict:
    ok: bool
    issues: list = field(default_factory=list)
    checked: list = field(default_factory=list)


class Verifier:
    """确定性验证器（同 ① 节）。"""

    def check(self, text, task):
        issues, checked = [], []
        for r in task.records:
            want = f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
            checked.append(f"分项 {r.sku}: {r.subtotal}")
            if want not in text:
                issues.append(f"分项「{r.sku}」金额不对，应为 {r.subtotal} 元")
        total = task.correct_total()
        checked.append(f"合计 = {task.formula_text()} = {total}")
        m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
        if not m:
            issues.append(f"缺少「合计：{total} 元」")
        elif int(m.group(1)) != total:
            issues.append(f"合计错误：应为 {total}，你写成了 {m.group(1)}；"
                          f"请把 {m.group(1)} 改成 {total}")
        checked.append("必须含「结论：」段落")
        if "结论：" not in text:
            issues.append("缺少「结论：」段落")
        return Verdict(ok=not issues, issues=issues, checked=checked)


def total_of(text):
    """从文本里抠出「合计：N 元」的数字（没有就返回 None）。"""
    m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
    return int(m.group(1)) if m else None


# ================= 对照实验：自评 vs 验证 =================
writer = WriterLLM()
messages = [Message.system(SYSTEM_TMPL.format(title=TASK.title, table=TASK.table_text(),
                                              lessons="（暂无历史教训）")),
            Message.user(f"请写出「{TASK.title}」。")]
draft1 = writer.complete(messages).text
messages.append(Message.assistant(draft1))

print("第 1 版草稿的合计 :", total_of(draft1), "元（正确值是", TASK.correct_total(), "元）")
print()

# ---- 路线 A：让模型自己检查 ----
messages.append(Message.user("请你再仔细检查一遍上面的内容，确认无误后再输出。"))
review = SelfReviewLLM().complete(messages).text
messages.append(Message.assistant(review))
draft2 = writer.complete(messages).text
print("路线 A · 让模型自评")
print("   自评说了什么 :", review[:44] + "…")
print("   改后的合计   :", total_of(draft2), "元")
print("   结果         :", "还是错的" if total_of(draft2) != TASK.correct_total() else "对了")
print("   代价         : 自评 1 次调用 + 重写 1 次调用")
print()

# ---- 路线 B：让代码验证，并把验证结果当成反馈 ----
verdict = Verifier().check(draft1, TASK)
print("路线 B · 让代码验证")
print("   验证器说了什么 :", verdict.issues[0])
messages2 = [Message.system(SYSTEM_TMPL.format(title=TASK.title, table=TASK.table_text(),
                                               lessons="（暂无历史教训）")),
             Message.user(f"请写出「{TASK.title}」。"),
             Message.assistant(draft1),
             Message.user("【修正意见】请逐条落实（只改被指出的地方，不要重写全文）：\\n"
                          + "\\n".join("- [验证器] " + i for i in verdict.issues))]
draft3 = WriterLLM().complete(messages2).text
print("   改后的合计   :", total_of(draft3), "元")
print("   结果         :", "对了" if total_of(draft3) == TASK.correct_total() else "还是错的")
print("   代价         : **0 次验证调用** + 1 次重写调用")
print()
print("★ 同样是「再来一遍」，差别在于**给模型看的是什么**：")
print("  路线 A 给的是「建议」（无位置、无事实、无动作），它只能改措辞；")
print("  路线 B 给的是「把 801 改成 811」（位置 + 事实 + 动作），它一次就改对。")''')

    nb.md("""### 结果说明什么

| 路线 | 给模型看的东西 | 结果 | 代价 |
|---|---|---|---|
| A 让模型自评 | 「建议进一步打磨细节」 | 合计还是 801 | 2 次模型调用 |
| B 让代码验证 | 「请把 801 改成 811」 | 合计变成 811 | **0 次验证** + 1 次重写 |

两条结论：

1. **能由代码判定的事，永远不要交给模型** —— 算术、格式、必填字段、
   引用编号、JSON 合法性，这些一旦交给模型，你就得到一个"这次说行、下次说不行"的系统；
2. **验证器的输出，本身就是一条可执行的修正意见**。
   这是最省钱的用法：不用再花钱请一个"审查者模型"。

但有些事情代码判定不了（文风、结论有没有深度、要不要补充趋势判断）——
那才轮到"审查者模型"。问题是：**怎么让它的意见有用？**""")

    # ==================================================================
    section(nb, "③", "有效反馈的三要素：位置 + 事实 + 动作")

    nb.md("""### 现在卡在哪

同一份草稿，两个审查者会给出完全不同的意见：

```
   ┌────────────────────────────────┬──────────────────────────────┐
   │  笼统反馈（无效）                │  具体反馈（有效）             │
   ├────────────────────────────────┼──────────────────────────────┤
   │  「建议进一步打磨细节，          │  「第 5 行「合计」有误：      │
   │   确保数据准确」                 │   391 + 360 + 60 = 811，     │
   │                                │   你写成了 801；            │
   │  <- 无位置、无事实、无动作       │   请把 801 改成 811。」      │
   │  -> 模型只能改措辞               │  <- 位置 + 事实 + 动作       │
   └────────────────────────────────┴──────────────────────────────┘
```

三要素缺一不可：

| 要素 | 回答什么 | 缺了会怎样 |
|---|---|---|
| **位置** | 哪一行 / 哪个字段 | 模型不知道该动哪里 |
| **事实** | 正确值是多少、依据是什么 | 模型只能猜 |
| **动作** | 把 X 改成 Y | 模型不知道要干什么 |

### 所以反馈必须被"合成"，而不是原样转发

```python
def build_feedback(critique, verdict, use_verifier_feedback=True) -> str:
    # ① 验证器的结论排在最前面（它是事实，优先级高于主观意见）
    # ② 只保留**可执行**的条目（带数字/位置的），笼统建议是噪声
```

为什么要过滤掉"不可执行条目"？因为笼统建议对模型是**噪声**：
它会挤占上下文、稀释真正的修改点，还会让模型以为"我改过了"。

### 立刻用一次：只改一个变量 —— 审查者的说话方式

下面是一个完整的 Reflexion 循环。两个审查者用同一个类、同一批事实，
**唯一的差别是 mode**（`vague` 说场面话 / `specific` 逐行重算）。

> 顺便把 `USE_VERIFIER_FEEDBACK` 也露出来：关掉它，"验证器兜底"这条退路就没了。
> 工程上这叫**单变量对照实验** —— 一次只改一个东西，才知道是哪个东西在起作用。""")

    nb.code('''# 单独可运行：笼统批评 vs 具体修正（只改一个变量）
CRITIC_MODE = "specific"        # ← 试着改这里："vague"（笼统派）/ "specific"（具体派）
USE_VERIFIER_FEEDBACK = True    # ← 试着改这里：改成 False，看"笼统派"会怎么死

import sys, pathlib, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.llm import LLM, LLMResponse
from core.message import Message

LESSON_HINT = "写出合计前必须逐项重算"


# ================= 事实源 =================
@dataclass(frozen=True)
class Rec:
    sku: str
    qty: int
    price: int

    @property
    def subtotal(self):
        return self.qty * self.price


@dataclass(frozen=True)
class Task:
    key: str
    kind: str
    title: str
    records: tuple

    def correct_total(self):
        return sum(r.subtotal for r in self.records)

    def wrong_total(self):
        return self.correct_total() - 10

    def table_text(self):
        return "\\n".join(f"- {r.sku}：{r.qty} 件 × {r.price} 元" for r in self.records)

    def formula_text(self):
        return " + ".join(str(r.subtotal) for r in self.records)


TASK = Task("2025Q1", "销售速报", "2025 年 Q1 销售速报", (
    Rec("A 商品", 17, 23), Rec("B 商品", 8, 45), Rec("C 商品", 5, 12)))

SYSTEM_TMPL = """你是一名数据分析助理，负责撰写销售速报。

# 任务
格式必须严格如下：
{title}
分项：
- <商品>：<数量> 件 × <单价> 元 = <小计> 元
合计：<逐项之和> 元
结论：<一句话结论>

# 事实源（只读，不得修改）
{table}

{lessons}"""


# ================= 写作模型 =================
class WriterLLM(LLM):
    """会算错的写作模型：只认「把 X 改成 Y」这种可执行的反馈。"""

    name = "writer"

    def _complete(self, messages, **kwargs):
        system = messages[0].content
        users = [m.content for m in messages if m.role == "user"]
        feedback = users[-1] if len(users) > 1 else ""
        remembers = LESSON_HINT in system and TASK.kind in system
        text = self._render(TASK.correct_total() if remembers else TASK.wrong_total())
        applied = False
        for m in re.finditer(r"把\\s*(\\d+)\\s*改成\\s*(\\d+)", feedback):
            if m.group(1) in text:
                text = text.replace(m.group(1), m.group(2))
                applied = True
        if feedback and not applied:
            text = text.replace("销售速报", "销售速报（修订稿）")
        return LLMResponse(text=text)

    def _render(self, total):
        lines = [TASK.title, "分项："]
        lines += [f"- {r.sku}：{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" for r in TASK.records]
        lines.append(f"合计：{total} 元")
        lines.append("结论：本季度销售整体稳健，建议优先补货 A 商品。")
        return "\\n".join(lines)


# ================= 审查者（两种说话方式，同一套事实） =================
VAGUE_REVIEW = ("整体结构清晰、逻辑通顺、语言表达自然，建议进一步打磨细节，"
                "确保数据准确、结论更有深度，表述更加凝练。")
CLEAN_REVIEW = "未发现事实性错误。"


class CriticLLM(LLM):
    """审查者。mode 是本章最重要的对照变量：

        "specific" 具体派：手里有事实源，逐行重算，说出「哪一行、错在哪、改成什么」
        "vague"    场面话派：只会说「建议进一步优化」，一个字都落不了地
    """

    name = "critic"

    def __init__(self, mode="specific"):
        super().__init__("mock-critic")
        self.mode = mode

    def _complete(self, messages, **kwargs):
        draft = next((m.content for m in reversed(messages) if m.role == "user"), "")
        if self.mode == "vague":
            return LLMResponse(text=VAGUE_REVIEW)
        # ---- 具体派：它手里有事实源，所以能说出确定的话 ----
        want = TASK.correct_total()
        m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", draft)
        items = []
        if m and int(m.group(1)) != want:
            items.append(f"合计行有误：{TASK.formula_text()} = {want}，你写成了 {m.group(1)}；"
                         f"请把 {m.group(1)} 改成 {want}，其余内容不要改动。")
        return LLMResponse(text="\\n".join("- " + i for i in items) if items else CLEAN_REVIEW)


# ================= 验证器 =================
@dataclass
class Verdict:
    ok: bool
    issues: list = field(default_factory=list)
    checked: list = field(default_factory=list)


class Verifier:
    def check(self, text, task):
        issues, checked = [], []
        for r in task.records:
            checked.append(f"分项 {r.sku}: {r.subtotal}")
            if f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" not in text:
                issues.append(f"分项「{r.sku}」金额不对，应为 {r.subtotal} 元")
        total = task.correct_total()
        checked.append(f"合计 = {task.formula_text()} = {total}")
        m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
        if not m:
            issues.append(f"缺少「合计：{total} 元」")
        elif int(m.group(1)) != total:
            issues.append(f"合计错误：逐项重算应为 {total}，你写成了 {m.group(1)}；"
                          f"请把 {m.group(1)} 改成 {total}")
        checked.append("必须含「结论：」段落")
        if "结论：" not in text:
            issues.append("缺少「结论：」段落，交付格式不合规")
        return Verdict(ok=not issues, issues=issues, checked=checked)


# ================= 反馈合成：事实优先于意见 =================
@dataclass
class Critique:
    raw: str
    items: list = field(default_factory=list)

    @property
    def actionable(self):
        """可执行条目 = 带数字/位置的条目（模型照着就能改）。"""
        return [i for i in self.items if re.search(r"\\d", i)]

    @property
    def vague(self):
        """笼统条目 = 没有数字、没有位置的"建议"。"""
        return [i for i in self.items if not re.search(r"\\d", i)]

    @property
    def blocking(self):
        """审查者是否认为"还不能交付"。"""
        return bool(self.items)


def parse_critique(text):
    """把审查者的文本解析成条目列表。

    真实系统里这一步同样重要：**不可解析的反馈无法驱动修正**，
    所以提示词要规定审查者逐条输出（这里用 `- ` 开头一行一条）。
    """
    raw = (text or "").strip()
    if not raw or "未发现" in raw:
        return Critique(raw=raw, items=[])
    items = [ln.strip("-• \\t") for ln in raw.splitlines() if ln.strip().startswith(("-", "•"))]
    if not items:
        items = [raw]                        # 没按规定格式输出 -> 整段当成一条
    return Critique(raw=raw, items=items)


def build_feedback(critique, verdict, use_verifier_feedback=True):
    """把"审查意见 + 验证结论"合成下一轮给模型的反馈。

    两个工程决定：
      1. **验证器的结论排在最前面** —— 它是事实，优先级高于主观意见；
      2. 只保留**可执行**条目 —— 笼统建议是噪声，写进去只会稀释真正的修改点。
    """
    lines = []
    if use_verifier_feedback:
        lines += [f"- [验证器] {i}" for i in verdict.issues]
    lines += [f"- [审查者] {i}" for i in critique.actionable]
    if not lines:
        return ""
    return "【修正意见】请逐条落实（只改被指出的地方，不要重写全文）：\\n" + "\\n".join(lines)


# ================= Reflexion 主循环 =================
@dataclass
class Round:
    index: int
    draft: str
    critique: Critique
    verdict: Verdict
    feedback: str


@dataclass
class Result:
    final: str
    rounds: list
    stop_reason: str
    llm_calls: int

    @property
    def reflections(self):
        """真正的"反思轮数" = 总轮数 - 1（第一轮是初次生成）。"""
        return max(len(self.rounds) - 1, 0)

    @property
    def verified(self):
        return bool(self.rounds) and self.rounds[-1].verdict.ok

    @property
    def unresolved(self):
        """停机时仍未解决的问题（交付时必须如实告诉用户）。"""
        if not self.rounds:
            return []
        last = self.rounds[-1]
        return list(last.verdict.issues) + list(last.critique.items)


class ReflexionAgent:
    """生成 -> 审查 -> 修正 -> 再验证。三道刹车缺一不可。

    `use_verifier_feedback` 这个开关是**刻意留的**：关掉它做实验，
    就能把"审查者的话"这一个变量单独拎出来，看清笼统批评和具体修正的差距。
    """

    def __init__(self, llm, critic, verifier, max_rounds=3, use_verifier_feedback=True):
        self.llm = llm
        self.critic = critic
        self.verifier = verifier
        self.max_rounds = max_rounds
        self.use_verifier_feedback = use_verifier_feedback

    def run(self, task):
        messages = [Message.system(SYSTEM_TMPL.format(
            title=task.title, table=task.table_text(), lessons="（暂无历史教训）")),
            Message.user(f"请写出「{task.title}」。只输出报告正文，不要解释。")]
        rounds, feedback = [], ""
        last_issues = ()
        stop_reason = "max_rounds"

        for i in range(1, self.max_rounds + 1):
            if feedback:
                messages.append(Message.user(feedback))

            # ① 生成（第一轮）/ 修正（后续轮）—— 对模型来说都是"接着写一段"
            draft = self.llm.complete(messages).text
            messages.append(Message.assistant(draft))

            # ② 两条独立的检查线：一条靠事实（verifier），一条靠语言（critic）
            verdict = self.verifier.check(draft, task)
            critique = self.critic.review(draft)
            rounds.append(Round(i, draft, critique, verdict, feedback))

            # ③ 刹车 1：事实无误 **且** 审查者不再提意见 -> 收工
            if verdict.ok and not critique.blocking:
                stop_reason = "verified_pass"
                break

            # ④ 刹车 2：事实错误一字未改 -> 反馈没被采纳，再跑也是白跑
            key = tuple(verdict.issues)
            if key and key == last_issues:
                stop_reason = "no_progress"
                break
            last_issues = key
            feedback = build_feedback(critique, verdict, self.use_verifier_feedback)

        return Result(rounds[-1].draft if rounds else "", rounds, stop_reason,
                      self.llm.total_calls)


class CriticWrapper:
    """把 CriticLLM 包一层：review(draft) -> Critique（解析成结构）。"""

    def __init__(self, llm):
        self.llm = llm

    def review(self, draft):
        resp = self.llm.complete([Message.system("你是审查者，逐条给出可执行的修改意见。"),
                                  Message.user(draft)])
        return parse_critique(resp.text)


def make_agent(mode, max_rounds=3, use_verifier_feedback=True):
    return ReflexionAgent(WriterLLM(), CriticWrapper(CriticLLM(mode)), Verifier(),
                          max_rounds=max_rounds,
                          use_verifier_feedback=use_verifier_feedback)


def total_of(text):
    m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
    return int(m.group(1)) if m else None


# ================= 对照实验 =================
CASES = [
    ("笼统派（无验证器反馈）", "vague", False),
    ("笼统派 + 验证器兜底", "vague", True),
    ("具体派", "specific", True),
]

print(f"当前组合：CRITIC_MODE={CRITIC_MODE}  USE_VERIFIER_FEEDBACK={USE_VERIFIER_FEEDBACK}")
print()
print(f"{'配置':<24}{'轮数':>5}{'停机原因':>16}{'最终合计':>10}{'验证通过':>10}")
print("-" * 68)
for label, mode, uv in CASES:
    r = make_agent(mode, use_verifier_feedback=uv).run(TASK)
    mark = "  <- 当前组合" if (mode == CRITIC_MODE and uv == USE_VERIFIER_FEEDBACK) else ""
    print(f"{label:<24}{len(r.rounds):>5}{r.stop_reason:>16}"
          f"{str(total_of(r.final)):>10}{('是' if r.verified else '否'):>10}{mark}")
print()
r = make_agent(CRITIC_MODE, use_verifier_feedback=USE_VERIFIER_FEEDBACK).run(TASK)
print(f"当前组合的完整轨迹（{CRITIC_MODE} / 验证器反馈 {USE_VERIFIER_FEEDBACK}）：")
for rd in r.rounds:
    print(f"  --- 第 {rd.index} 轮 ---")
    print(f"      产出    : 合计：{total_of(rd.draft)} 元")
    if rd.feedback:
        print(f"      收到的反馈: {rd.feedback.splitlines()[-1][:60]}")
    print(f"      审查意见: {(rd.critique.raw or '（无）')[:56]}")
    print(f"      验证结论: {'通过' if rd.verdict.ok else '不通过 · ' + rd.verdict.issues[0][:44]}")
print()
print("★ 三行对照说明了两件事：")
print("  1. 笼统派（无验证器反馈）：反馈里**一个可执行的数字都没有**，")
print("     模型只能改措辞 -> 合计仍是 801 -> 命中刹车 2（no_progress）；")
print("  2. 同一批事实，具体派两轮就 verified_pass ——")
print("     差别不在模型能力，而在反馈里有没有「位置 + 事实 + 动作」。")
print("  3. 中间那行值得注意：笼统派 + 验证器兜底**也能改对**（改成 811），")
print("     但它白跑了满轮数才停 —— 冗余可以兜住质量，兜不住成本。")''')

    nb.md("""### 结果说明什么

| 配置 | 轮数 | 停机原因 | 最终合计 | 说明 |
|---|---|---|---|---|
| 笼统派（无验证器反馈） | 2 | `no_progress` | 801（**错的**） | 反馈里没有任何可执行信息 |
| 笼统派 + 验证器兜底 | 3 | `max_rounds` | 811 | 质量兜住了，但白跑满轮数 |
| 具体派 | 2 | `verified_pass` | 811 | 一轮反思就收敛 |

三条结论：

1. **反馈里没有「位置 + 事实 + 动作」，模型就只能改措辞。**
   笼统派那一行是最典型的"反思了个寂寞"；
2. **`no_progress` 这条刹车本身就是「反馈质量」的探测器** ——
   它响了，说明反馈管道有问题（审查者在说废话，或者反馈没送进模型），
   而不是模型不行；
3. **冗余可以兜住质量，但兜不住成本。** 中间那一行说明：
   即使审查者很水，验证器也能把事实救回来 —— 代价是白跑满轮数。

主循环现在已经能跑了。但还有一个必须写进结构里的东西：**它什么时候停。**""")

    # ==================================================================
    section(nb, "④", "把刹车写进结构里")

    nb.md("""### 现在卡在哪

反思的成本是 **N 倍**：一次反思 = 至少 2 次模型调用（审查 + 重写）。
如果审查者永远不满意呢？

```
   · 第 1 轮：结论段落缺乏前瞻性，建议补充下季度趋势判断。
   · 第 2 轮：结论仍然不够具体，建议加入同比环比口径。
   · 第 3 轮：结论的措辞可以更有说服力，建议再优化一次表达。
   ...（它总能找出新的、无法验证的毛病）
```

**主观标准下，反思永远不会收敛。** 所以必须有三道刹车：

| 刹车 | 触发条件 | 停机原因 | 运维动作 |
|---|---|---|---|
| ① 真的好了 | 验证通过 + 审查者无意见 | `verified_pass` | 正常交付 |
| ② 原地踏步 | 事实错误和上一轮一模一样 | `no_progress` | 查反馈管道 |
| ③ 轮数用完 | 到达 `max_rounds` | `max_rounds` | 查目标是否可满足 |

★ **停机原因必须分类，不能只有一个 `failed`。** 三种停机的运维动作完全不同，
混成一个你永远定位不到问题。

### 还有一件经常被忽略的事

`max_rounds` 停机时，**审查者的意见并没有解决**。这时候应该：

```
   ❌ 假装完美：直接交付，什么都不说
   ✓ 如实交付 + 标注未闭环的异议（Result.unresolved）
```

生产系统里这些异议应该出现在工单备注、UI 提示、或者日志的 WARN 级别里。

### 立刻用一次：换一个"永远不满意"的审查者

同时把 `MAX_ROUNDS` 露出来 —— 这是本章最值得亲手改的数字。""")

    nb.code('''# 单独可运行：永远不满意的审查者 + 轮数上限
MAX_ROUNDS = 3       # ← 试着改这里：改成 10（账单翻几倍？）、改成 1（还反思吗？）

import sys, pathlib, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.llm import LLM, LLMResponse
from core.message import Message

LESSON_HINT = "写出合计前必须逐项重算"


# ---- 事实源 ----
@dataclass(frozen=True)
class Rec:
    sku: str
    qty: int
    price: int

    @property
    def subtotal(self):
        return self.qty * self.price


@dataclass(frozen=True)
class Task:
    key: str
    kind: str
    title: str
    records: tuple

    def correct_total(self):
        return sum(r.subtotal for r in self.records)

    def wrong_total(self):
        return self.correct_total() - 10

    def table_text(self):
        return "\\n".join(f"- {r.sku}：{r.qty} 件 × {r.price} 元" for r in self.records)

    def formula_text(self):
        return " + ".join(str(r.subtotal) for r in self.records)


TASK = Task("2025Q1", "销售速报", "2025 年 Q1 销售速报", (
    Rec("A 商品", 17, 23), Rec("B 商品", 8, 45), Rec("C 商品", 5, 12)))

SYSTEM_TMPL = """你是数据分析助理，负责撰写销售速报。
# 事实源（只读）
{table}
格式：{title} / 分项：… / 合计：… 元 / 结论：…
{lessons}"""


class WriterLLM(LLM):
    name = "writer"

    def _complete(self, messages, **kwargs):
        system = messages[0].content
        users = [m.content for m in messages if m.role == "user"]
        feedback = users[-1] if len(users) > 1 else ""
        remembers = LESSON_HINT in system and TASK.kind in system
        text = self._render(TASK.correct_total() if remembers else TASK.wrong_total())
        applied = False
        for m in re.finditer(r"把\\s*(\\d+)\\s*改成\\s*(\\d+)", feedback):
            if m.group(1) in text:
                text = text.replace(m.group(1), m.group(2))
                applied = True
        if feedback and not applied:
            text = text.replace("销售速报", "销售速报（修订稿）")
        return LLMResponse(text=text)

    def _render(self, total):
        lines = [TASK.title, "分项："]
        lines += [f"- {r.sku}：{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" for r in TASK.records]
        lines.append(f"合计：{total} 元")
        lines.append("结论：本季度销售整体稳健，建议优先补货 A 商品。")
        return "\\n".join(lines)


NITPICKS = (
    "结论段落缺乏前瞻性，建议重写结论，补充下季度趋势判断。",
    "结论仍然不够具体，建议加入同比与环比的口径说明。",
    "结论的措辞可以更有说服力，建议再优化一次表达。",
)


class NitpickCriticLLM(LLM):
    """挑刺派审查者：**永远能找出新的、无法验证的毛病**。

    它模拟的是"主观标准"：没有事实源，只有品味。这类审查者不配上刹车就是灾难。
    """

    name = "nitpick-critic"

    def _complete(self, messages, **kwargs):
        # total_calls 是基类自动维护的调用计数：每被问一次，就换一条毛病
        return LLMResponse(text="- " + NITPICKS[self.total_calls % len(NITPICKS)])


@dataclass
class Verdict:
    ok: bool
    issues: list = field(default_factory=list)
    checked: list = field(default_factory=list)


class Verifier:
    def check(self, text, task):
        issues, checked = [], []
        for r in task.records:
            checked.append(f"分项 {r.sku}: {r.subtotal}")
            if f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" not in text:
                issues.append(f"分项「{r.sku}」金额不对，应为 {r.subtotal} 元")
        total = task.correct_total()
        checked.append(f"合计 = {task.formula_text()} = {total}")
        m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
        if not m:
            issues.append(f"缺少「合计：{total} 元」")
        elif int(m.group(1)) != total:
            issues.append(f"合计错误：逐项重算应为 {total}，你写成了 {m.group(1)}；"
                          f"请把 {m.group(1)} 改成 {total}")
        checked.append("必须含「结论：」段落")
        if "结论：" not in text:
            issues.append("缺少「结论：」段落")
        return Verdict(ok=not issues, issues=issues, checked=checked)


@dataclass
class Critique:
    raw: str
    items: list = field(default_factory=list)

    @property
    def actionable(self):
        return [i for i in self.items if re.search(r"\\d", i)]

    @property
    def blocking(self):
        return bool(self.items)


def parse_critique(text):
    raw = (text or "").strip()
    if not raw or "未发现" in raw:
        return Critique(raw=raw, items=[])
    items = [ln.strip("-• \\t") for ln in raw.splitlines() if ln.strip().startswith(("-", "•"))]
    return Critique(raw=raw, items=items or [raw])


def build_feedback(critique, verdict):
    lines = [f"- [验证器] {i}" for i in verdict.issues]
    lines += [f"- [审查者] {i}" for i in critique.actionable]
    if not lines:
        return ""
    return "【修正意见】请逐条落实（只改被指出的地方，不要重写全文）：\\n" + "\\n".join(lines)


@dataclass
class Round:
    index: int
    draft: str
    critique: Critique
    verdict: Verdict
    feedback: str


class ReflexionAgent:
    def __init__(self, llm, critic, verifier, max_rounds=MAX_ROUNDS):
        self.llm, self.critic, self.verifier = llm, critic, verifier
        self.max_rounds = max_rounds

    def run(self, task):
        messages = [Message.system(SYSTEM_TMPL.format(title=task.title, table=task.table_text(),
                                                      lessons="（暂无历史教训）")),
                    Message.user(f"请写出「{task.title}」。只输出报告正文，不要解释。")]
        rounds, feedback, last_issues = [], "", ()
        stop_reason = "max_rounds"          # 默认值就是"跑满了"—— 只有提前 break 才会改
        for i in range(1, self.max_rounds + 1):
            if feedback:
                messages.append(Message.user(feedback))
            draft = self.llm.complete(messages).text
            messages.append(Message.assistant(draft))
            verdict = self.verifier.check(draft, task)
            critique = parse_critique(self.critic.complete(
                [Message.system("你是审查者。"), Message.user(draft)]).text)
            rounds.append(Round(i, draft, critique, verdict, feedback))

            if verdict.ok and not critique.blocking:        # 刹车 1
                stop_reason = "verified_pass"
                break
            key = tuple(verdict.issues)
            if key and key == last_issues:                  # 刹车 2
                stop_reason = "no_progress"
                break
            last_issues = key
            feedback = build_feedback(critique, verdict)    # 刹车 3 是 for 循环本身
        return {"final": rounds[-1].draft if rounds else "", "rounds": rounds,
                "stop_reason": stop_reason, "calls": self.llm.total_calls}


def total_of(text):
    m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
    return int(m.group(1)) if m else None


res = ReflexionAgent(WriterLLM(), NitpickCriticLLM(), Verifier(), max_rounds=MAX_ROUNDS).run(TASK)
print(f"MAX_ROUNDS = {MAX_ROUNDS}")
print()
for rd in res["rounds"]:
    print(f"  · 第 {rd.index} 轮：验证{'通过' if rd.verdict.ok else '不通过'}"
          f" / 审查意见：{(rd.critique.raw or '（无）')[:40]}")
print()
print(f"轮数        : {len(res['rounds'])}（上限 {MAX_ROUNDS}）")
print(f"停机原因    : {res['stop_reason']}")
print(f"事实层      : {'已通过验证' if res['rounds'][-1].verdict.ok else '仍未通过'}")
print(f"模型调用次数: {res['calls']} 次（每一轮都是一次真实调用）")
last = res["rounds"][-1]
unresolved = list(last.verdict.issues) + list(last.critique.items)
print(f"未解决的异议: {len(unresolved)} 条")
for u in unresolved:
    print("    -", u[:56])
print()
print("★ 这里的事实层其实第 1 轮就通过了（合计从一开始就是对的）——")
print("  真正卡住的是**主观标准**：结论写得「够不够有前瞻性」，永远没有标准答案。")
print("  所以 max_rounds 不是可选项：主观审查者不配上刹车，就是无限烧钱。")
print("★ 更重要的工程习惯：**停机时把未闭环的异议如实交出去**，")
print("  而不是假装完美交付 —— 生产里它应该出现在工单备注/UI 提示/日志 WARN 里。")''')

    nb.md("""### 结果说明什么

- 事实层其实**第 1 轮就通过了**（合计一开始就是对的），
  卡住的是**主观标准** —— 结论"够不够有前瞻性"永远没有标准答案；
- 所以 `max_rounds` 不是可选项：**主观审查者不配上刹车，就是无限烧钱**；
- 停机时必须**如实交出未闭环的异议**，而不是假装完美。

对照一下三种停机的运维动作：

| 停机原因 | 真实含义 | 你该去哪里查 |
|---|---|---|
| `no_progress` | 反馈没被采纳 | 反馈管道（审查者在说废话？反馈没送进模型？） |
| `max_rounds` | 目标不可满足 | 审查标准是不是主观的、无法收敛的？ |
| 事实错误仍在 | 验证器不够强 / 事实源不对 | 验证器，而不是模型 |

改 `MAX_ROUNDS` 到 10 跑一遍，你会看到模型调用次数跟着涨 ——
**反思的每一步都是有价格的。**

最后一块拼图：这次的教训怎么留给下次？""")

    # ==================================================================
    section(nb, "⑤", "经验库：让同一个坑只踩一次")

    nb.md("""### 现在卡在哪

反思改对的是**这一次**。下一个季度写同样的速报，模型**照样会算错合计** ——
因为它对"上一轮发生了什么"没有任何记忆（第 05 章讲过：模型没有记忆）。

### 所以我需要「把教训结构化地存下来，下次开工前注入」

```python
Lesson(kind="销售速报", mistake="合计错误：应为 811，写成了 801", fix="写出合计前必须逐项重算",
       source="2025Q1 2025 年 Q1 销售速报")
```

四个字段各有职责：

| 字段 | 作用 | 缺了会怎样 |
|---|---|---|
| `kind` | 任务**类型** | 不分类的经验库 = 往上下文里倒垃圾（只会注入无关教训） |
| `mistake` | 具体错在哪 | 人无法判断这条教训还适不适用 |
| `fix` | 下次怎么做 | 教训没法执行 |
| `source` | 来自哪个任务 | 不可溯源，人不敢信也不敢删 |

### 两个必须想清楚的工程决定

1. **只注入同类任务的教训。** 无关教训是噪声（第 05 章的教训）；
2. **写回时机是「第一轮就错了」，而不是「最终没通过」。**
   反思把错误改对了，不代表这个坑不存在 —— 教训要能被下一次同类任务读到。

### 立刻用一次：同一个坑，踩两次

下面跑两个同类任务（Q1、Q2）。第一遍有经验库，第二遍注入教训。""")

    nb.code('''# 单独可运行：失败经验库 —— 让同一个坑只踩一次
USE_MEMORY = True      # ← 试着改这里：改成 False（对照组），看第二遍还要不要反思

import sys, pathlib, re
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.llm import LLM, LLMResponse
from core.message import Message

LESSON_HINT = "写出合计前必须逐项重算"


# ---- 事实源：两个同类任务（都是"销售速报"）----
@dataclass(frozen=True)
class Rec:
    sku: str
    qty: int
    price: int

    @property
    def subtotal(self):
        return self.qty * self.price


@dataclass(frozen=True)
class Task:
    key: str
    kind: str
    title: str
    records: tuple

    def correct_total(self):
        return sum(r.subtotal for r in self.records)

    def wrong_total(self):
        return self.correct_total() - 10        # 同类任务犯同一类错（漏一项/漏进位）

    def table_text(self):
        return "\\n".join(f"- {r.sku}：{r.qty} 件 × {r.price} 元" for r in self.records)

    def formula_text(self):
        return " + ".join(str(r.subtotal) for r in self.records)


TASK_Q1 = Task("2025Q1", "销售速报", "2025 年 Q1 销售速报", (
    Rec("A 商品", 17, 23), Rec("B 商品", 8, 45), Rec("C 商品", 5, 12)))     # 811
TASK_Q2 = Task("2025Q2", "销售速报", "2025 年 Q2 销售速报", (
    Rec("A 商品", 12, 31), Rec("B 商品", 9, 28), Rec("C 商品", 4, 15)))     # 684

SYSTEM_TMPL = """你是数据分析助理，负责撰写销售速报。
# 任务
格式：{title} / 分项：… / 合计：… 元 / 结论：…
# 事实源（只读）
{table}
{lessons}"""


class WriterLLM(LLM):
    """写作模型：**系统提示词里有没有教训**，决定它开局算不算得对。"""

    name = "writer"

    def __init__(self, task):
        super().__init__("mock-writer")
        self.task = task

    def _complete(self, messages, **kwargs):
        system = messages[0].content
        users = [m.content for m in messages if m.role == "user"]
        feedback = users[-1] if len(users) > 1 else ""
        # 教训在提示词里（且是同类任务）-> 开工前就逐项重算，不再犯同一个错
        remembers = LESSON_HINT in system and self.task.kind in system
        total = self.task.correct_total() if remembers else self.task.wrong_total()
        text = self._render(total)
        applied = False
        for m in re.finditer(r"把\\s*(\\d+)\\s*改成\\s*(\\d+)", feedback):
            if m.group(1) in text:
                text = text.replace(m.group(1), m.group(2))
                applied = True
        if feedback and not applied:
            text = text.replace("销售速报", "销售速报（修订稿）")
        return LLMResponse(text=text)

    def _render(self, total):
        lines = [self.task.title, "分项："]
        lines += [f"- {r.sku}：{r.qty} 件 × {r.price} 元 = {r.subtotal} 元"
                  for r in self.task.records]
        lines.append(f"合计：{total} 元")
        lines.append("结论：本季度销售整体稳健，建议优先补货 A 商品。")
        return "\\n".join(lines)


class CriticLLM(LLM):
    """具体派审查者（③ 节那个）：手里有事实源，逐行重算。"""

    name = "critic"

    def __init__(self, task):
        super().__init__("mock-critic")
        self.task = task

    def _complete(self, messages, **kwargs):
        draft = next((m.content for m in reversed(messages) if m.role == "user"), "")
        want = self.task.correct_total()
        m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", draft)
        if m and int(m.group(1)) != want:
            return LLMResponse(text=f"- 合计行有误：{self.task.formula_text()} = {want}，"
                                    f"你写成了 {m.group(1)}；请把 {m.group(1)} 改成 {want}。")
        return LLMResponse(text="未发现事实性错误。")


@dataclass
class Verdict:
    ok: bool
    issues: list = field(default_factory=list)
    checked: list = field(default_factory=list)


class Verifier:
    def check(self, text, task):
        issues, checked = [], []
        for r in task.records:
            checked.append(f"分项 {r.sku}: {r.subtotal}")
            if f"{r.qty} 件 × {r.price} 元 = {r.subtotal} 元" not in text:
                issues.append(f"分项「{r.sku}」金额不对，应为 {r.subtotal} 元")
        total = task.correct_total()
        checked.append(f"合计 = {task.formula_text()} = {total}")
        m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
        if not m:
            issues.append(f"缺少「合计：{total} 元」")
        elif int(m.group(1)) != total:
            issues.append(f"合计错误：逐项重算应为 {total}，你写成了 {m.group(1)}；"
                          f"请把 {m.group(1)} 改成 {total}")
        checked.append("必须含「结论：」段落")
        if "结论：" not in text:
            issues.append("缺少「结论：」段落")
        return Verdict(ok=not issues, issues=issues, checked=checked)


@dataclass
class Critique:
    raw: str
    items: list = field(default_factory=list)

    @property
    def actionable(self):
        return [i for i in self.items if re.search(r"\\d", i)]

    @property
    def blocking(self):
        return bool(self.items)


def parse_critique(text):
    raw = (text or "").strip()
    if not raw or "未发现" in raw:
        return Critique(raw=raw, items=[])
    items = [ln.strip("-• \\t") for ln in raw.splitlines() if ln.strip().startswith(("-", "•"))]
    return Critique(raw=raw, items=items or [raw])


def build_feedback(critique, verdict):
    lines = [f"- [验证器] {i}" for i in verdict.issues]
    lines += [f"- [审查者] {i}" for i in critique.actionable]
    return ("【修正意见】请逐条落实（只改被指出的地方，不要重写全文）：\\n"
            + "\\n".join(lines)) if lines else ""


# ---- 失败经验库：结构化的教训 ----
@dataclass(frozen=True)
class Lesson:
    kind: str        # 任务类型
    mistake: str     # 具体错在哪
    fix: str         # 下次怎么做
    source: str      # 来自哪个任务（可溯源）

    def render(self):
        return f"- 在「{self.source}」上犯过：{self.mistake}\\n  教训：{self.fix}"


class LessonMemory:
    """跨任务的失败经验库（现实中会落库/落向量库，这里先用内存列表）。"""

    def __init__(self):
        self.items = []

    def add(self, lesson):
        if lesson not in self.items:        # 去重：同一个坑记一次就够
            self.items.append(lesson)

    def as_prompt(self, kind):
        """只注入**同类任务**的教训 —— 无关教训是噪声（第 05 章的教训）。"""
        same = [x for x in self.items if x.kind == kind]
        if not same:
            return ""
        return "历史教训（同类任务曾经失败过，开工前务必避免）：\\n" + "\\n".join(
            x.render() for x in same)

    def __len__(self):
        return len(self.items)


@dataclass
class Round:
    index: int
    draft: str
    critique: Critique
    verdict: Verdict
    feedback: str


class ReflexionAgent:
    def __init__(self, task, max_rounds=3, memory=None):
        self.task = task
        self.max_rounds = max_rounds
        self.memory = memory

    def run(self):
        lessons = self.memory.as_prompt(self.task.kind) if self.memory else ""
        writer = WriterLLM(self.task)
        critic = CriticLLM(self.task)
        verifier = Verifier()
        messages = [Message.system(SYSTEM_TMPL.format(
            title=self.task.title, table=self.task.table_text(),
            lessons=lessons or "（暂无历史教训）")),
            Message.user(f"请写出「{self.task.title}」。只输出报告正文，不要解释。")]

        rounds, feedback, last_issues = [], "", ()
        stop_reason = "max_rounds"
        for i in range(1, self.max_rounds + 1):
            if feedback:
                messages.append(Message.user(feedback))
            draft = writer.complete(messages).text
            messages.append(Message.assistant(draft))
            verdict = verifier.check(draft, self.task)
            critique = parse_critique(critic.complete(
                [Message.system("你是审查者。"), Message.user(draft)]).text)
            rounds.append(Round(i, draft, critique, verdict, feedback))

            if verdict.ok and not critique.blocking:
                stop_reason = "verified_pass"
                break
            key = tuple(verdict.issues)
            if key and key == last_issues:
                stop_reason = "no_progress"
                break
            last_issues = key
            feedback = build_feedback(critique, verdict)

        # ---- 收尾：只要**初次生成**是错的，就把这次失败沉淀成教训 ----
        # 判据是"第一轮错了"，而不是"最终没通过"：反思把错误改对了，
        # 不代表这个坑不存在 —— 教训要能被下一次同类任务读到。
        if self.memory is not None and rounds and not rounds[0].verdict.ok:
            first = rounds[0].verdict.issues
            self.memory.add(Lesson(kind=self.task.kind,
                                   mistake=first[0] if first else "未通过验证",
                                   fix=LESSON_HINT,
                                   source=f"{self.task.key} {self.task.title}"))
        return {"rounds": rounds, "stop_reason": stop_reason,
                "calls": writer.total_calls,
                "first_total": total_of(rounds[0].draft) if rounds else None,
                "final": rounds[-1].draft if rounds else ""}


def total_of(text):
    m = re.search(r"合计[:：]\\s*(\\d+)\\s*元", text)
    return int(m.group(1)) if m else None


# ================= 第一遍：没有经验库 =================
mem = LessonMemory() if USE_MEMORY else None
r1 = ReflexionAgent(TASK_Q1, memory=mem).run()
print("=== 第一遍（2025Q1，经验库是空的）===")
print(f"   首轮合计   : 合计：{r1['first_total']} 元（正确 {TASK_Q1.correct_total()} 元）")
print(f"   轮数       : {len(r1['rounds'])}")
print(f"   停机原因   : {r1['stop_reason']}")
print(f"   最终验证   : {'通过' if r1['rounds'][-1].verdict.ok else '不通过'}")
print(f"   经验库条数 : {len(mem) if mem else 0}")
if mem and len(mem):
    print()
    print("   自动写进经验库的教训（结构化存储，下次可直接注入提示词）：")
    for line in mem.as_prompt("销售速报").splitlines():
        print("      " + line)
print()

# ================= 第二遍：同类任务，教训已注入 =================
r2 = ReflexionAgent(TASK_Q2, memory=mem).run()
print("=== 第二遍（2025Q2，同类任务，教训已注入）===")
print(f"   首轮合计   : 合计：{r2['first_total']} 元（正确 {TASK_Q2.correct_total()} 元）")
print(f"   反思轮数   : {max(len(r2['rounds']) - 1, 0)}")
print(f"   模型调用   : {r2['calls']} 次")
print()

# ================= 对照组：把经验库关掉 =================
r3 = ReflexionAgent(TASK_Q2, memory=None).run()
print("=== 对照组（同样的 Q2，但**没有**经验库）===")
print(f"   首轮合计   : 合计：{r3['first_total']} 元（正确 {TASK_Q2.correct_total()} 元）")
print(f"   反思轮数   : {max(len(r3['rounds']) - 1, 0)}")
print(f"   模型调用   : {r3['calls']} 次")
print()
print("★ 对照结果说明一件事：**教训必须在下一次开工前注入提示词**，")
print("  否则「记下来」等于没记。只改这一次的反思是昂贵的补丁；")
print("  能让下一次不犯的反思才是资产。")''')

    nb.md("""### 结果说明什么

| 运行 | 首轮合计 | 反思轮数 | 说明 |
|---|---|---|---|
| 第一遍 Q1（经验库空） | 错的 | 1 轮 | 犯了错 → 反思修正 → **顺手写下教训** |
| 第二遍 Q2（有经验库） | **对的** | **0 轮** | 开工前就避开了同一个坑 |
| 对照组 Q2（无经验库） | 错的 | 1 轮 | 没有教训 → 又踩一次 |

三件事值得记住：

1. **教训要结构化**（类型 / 错在哪 / 怎么避免 / 来源）；
2. **只注入同类任务的教训** —— 不分类的经验库等于往上下文里倒垃圾；
3. **写回判据是"第一轮就错了"**，不是"最终没通过"：
   反思把错误改对，不代表这个坑不存在。

**只改这一次的反思是昂贵的补丁；能让下一次不犯的反思才是资产。**""")

    # ==================================================================
    section(nb, "⑥", "常见坑汇总")

    pitfall_table(nb, [
        ("让模型「自己再检查一遍」", "自评与生成用同一套先验，它错的地方看不出来（self-consistency bias）",
         "用**代码验证器**（事实源 + 规则），或换一个**不同的问题**"),
        ("反馈里没有位置/事实/动作", "模型只能改措辞（改成「修订稿」），事实一字未动",
         "反馈必须含「哪一行 + 正确值 + 把 X 改成 Y」"),
        ("把笼统建议也塞进反馈", "噪声挤占上下文，稀释真正的修改点，还让模型以为改过了",
         "只保留**可执行条目**（带数字/位置的）"),
        ("没有 `max_rounds`", "主观审查者永远不满意 → 无限烧钱（每轮 2 次调用起步）",
         "`max_rounds` 1~3，再高先问「是不是验证器太弱」"),
        ("停机原因只有一个 `failed`", "`no_progress` 和 `max_rounds` 的运维动作完全不同，混在一起就查不出问题",
         "停机必须分类"),
        ("未闭环的异议不告诉用户", "假装完美交付，用户以为都对",
         "把 `unresolved` 放进工单备注 / UI 提示 / 日志 WARN"),
        ("验证器不说自己检查了什么", "无法审计、无法回归，也不知道检查有没有跑",
         "`Verdict.checked` 记录每条确定性检查"),
        ("重写时让模型「重写全文」", "已经对的部分被改坏，副作用风险变大",
         "反馈里明确：**只改被指出的地方**"),
        ("把整段对话塞给审查者", "上下文越长越容易走神（第 05 章）", "只给草稿 + 事实源"),
        ("经验库不分类", "注入无关教训 = 污染（第 05 章的同一条坑）", "`Lesson.kind` + 同类注入"),
        ("经验库只增不减", "过期教训一直干扰新任务",
         "给教训加成功计数 / 过期策略，长期不再出错就归档"),
        ("把「最终没通过」当成写教训的条件", "反思改对了错误，坑却没人记下来，下次照踩",
         "判据是「第一轮就错了」"),
        ("用反思代替更强的验证器", "一次调用换一个不确定的裁判，不划算",
         "先问：这件事的对错，谁能判定？找不到判据就该上人工节点"),
    ])

    summary(nb, [
        "**反思 = 换个视角检查自己的输出 → 产出具体可执行的修正。**"
        "没有具体修正的反思只是废话。",
        "**自评不可靠**：它和生成用同一套先验。只要对错能被代码判定，就交给代码 —— "
        "快、免费、100% 稳定。",
        "**一条有效反馈的三要素**：位置 + 事实 + 动作。"
        "缺任何一个，模型都只能改措辞。",
        "**验证器的输出本身就是修正意见**（「请把 801 改成 811」），"
        "这是最省钱的用法，不用再请一个审查者模型。",
        "**三道刹车写进结构里**：`verified_pass` / `no_progress` / `max_rounds`。"
        "停机必须分类，否则定位不到问题。",
        "**未闭环的异议要如实交付**，不要假装完美。",
        "**教训要结构化并注入下一次同类任务**：只改这一次的反思是昂贵的补丁，"
        "能让下一次不犯的才是资产。",
    ], "下一章（第 08 章）会把单个 Agent 扩展成**多个 Agent 协作**："
       "规划者、执行者、审查者各司其职 —— "
       "本章的「审查者」其实就是多智能体分工的雏形（生成与检查分离）。"
       "你会看到分工带来的收益，以及它引入的新问题：通信成本、责任边界、"
       "以及「谁来审查审查者」。")

    exercises(nb, [
        ("**把刹车拆掉，观察会发生什么。**\n\n"
         "把 ④ 节的 `MAX_ROUNDS` 改成 `50`，用挑刺派审查者跑一次，"
         "看 `轮数` 和 `模型调用次数`。\n\n"
         "然后回答：如果这是线上系统，一个「永远不满意」的审查者会花掉你多少钱？",
         "你会得到 50 轮 —— **每一轮都是一次真实的模型调用**。\n\n"
         "再想一步：为什么「把轮数调大」不能提高质量？"
         "因为主观标准下它根本不收敛 —— 它只增加了成本，没有增加确定性。"),

        ("**让验证器更严。**\n\n"
         "给验证器加一条检查：**结论段里提到的商品必须出现在分项里**"
         "（防止模型在结论里编一个「补货 D 商品」）。\n\n"
         "然后构造一个「合计对、但结论编了商品」的草稿做反向验证。",
         "在 `check()` 里加第 ④ 条规则：用正则从结论段里抽出商品名，"
         "与 `task.records` 里的 `sku` 做差集。\n\n"
         "★ 关键是最后那半句：**新加的检查必须有一个「该拦住的坏例子」来验证**，"
         "否则你不知道它到底有没有生效。"),

        ("**给经验库加失效机制。**\n\n"
         "现在的经验库只增不减。改成：一条教训被后续 3 次同类任务证明"
         "「已经不再出错」后，降低它的优先级（或归档）。",
         "给 `Lesson` 加 `hits` / `success_streak` 字段，在 `as_prompt()` 里按它过滤。\n\n"
         "想一想：这和第 05 章的「记忆遗忘策略」是不是同一个问题？"
         "（是 —— 都是「在有限预算里保留最高价值的信息」。）"),

        ("**把笼统批评「翻译」成具体修正。**\n\n"
         "新增一个 `RepairPlanner`：接收笼统的审查意见 + 事实源，"
         "输出可执行的修正条目（就是「具体派审查者」干的事），"
         "接在笼统派审查者后面。\n\n"
         "跑对照实验：笼统派 + 翻译器，能不能追平具体派？代价是几次调用？",
         "这就是工业界的 `critique -> actionable plan` 两步走。\n\n"
         "如果追平了：你多花了一次调用，换来的是「审查者可以换成一个便宜的模型」——"
         "这笔账划不划算，取决于你的场景。"),

        ("**换一个真实模型试试（可选，需要 API Key）。**\n\n"
         "把写作模型换成 `core.real_llm` 里的真实模型，跑同一套流程。\n\n"
         "你会观察到两件事：① 真实模型第一次**未必**算错（它可能直接给出 811）；"
         "② 但它一旦算错，笼统的「再检查一遍」依然救不回来。",
         "这说明本章的结构与模型强弱无关：**反思是架构问题，不是模型问题。**\n\n"
         "顺便观察：真实模型的输出格式比假模型脏得多（会加「好的，这是我的报告：」），"
         "所以解析器要更宽容 —— 这正是第 03 章的内容。"),
    ])

    checkpoint(nb, "07")

    return nb
