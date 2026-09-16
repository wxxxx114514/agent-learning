"""第 05 章 · 记忆与上下文工程 —— Notebook 内容（逐步推进版）。

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


def build_05() -> Notebook:
    """第 05 章 · 记忆与上下文工程（逐步推进版）。"""
    nb = Notebook("第 05 章 · 记忆与上下文工程")

    header(
        nb, "05", "记忆与上下文工程",
        "记忆 = `短期（消息窗）` + `工作（当前任务状态）` + `长期（外部存储）`。\n"
        "上下文管理的本质是：**在有限预算下保留最高价值的信息**。",
    )

    objectives(nb, [
        "说清「全量塞进去」和「只留最近 N 轮」这两个朴素方案分别怎么死",
        "先**算账**再做压缩：给上下文每一块列预算，并让账本自洽",
        "写出规则版**事实抽取 + 钉住区**，并解释为什么钉住区也必须带上限",
        "实现**增量滚动摘要**（旧摘要参与下一轮），并说清「摘要漂移」怎么来的",
        "实现跨会话的**长期记忆 + 相关性闸门**，并说清「注入污染」比不注入更糟",
        "用位置实验解释 Lost in the Middle，并据此决定六块内容的排列顺序",
        "拆掉任意一层护栏，观察哪条关键事实会丢（**每一层都在承重**）",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

第 04 章的 Planner-Executor 会产出大量中间结果：每一版计划、每一步的观测、
每一次重规划的原因。第 01 章的 `messages` 列表则会把它们**全部**留在一个不断增长的数组里。

于是上下文变成了一个只涨不跌的水池。本章按这个顺序拆：

```
① 先看 50 轮之后 Agent 还记不记得你的名字（两个朴素方案都死）
② 先算账，再决定放什么          -> 就地讲 token 估算与预算表
③ 什么值得记：事实抽取 + 钉住     -> 失败模式：钉住区没上限会怎样
④ 滚动摘要：增量，而不是每次重算   -> 摘要漂移实验
⑤ 长期记忆：跨会话 + 相关性闸门    -> 以及它的同义词盲区（第 06 章的引子）
⑥ 组装：顺序就是策略             -> Lost in the Middle 位置实验
⑦ 拆护栏：每一层都在承重          -> 把三层防护一层层拆掉看后果
⑧ 常见坑
```

每个知识点都出现在**你正好需要它**的时候。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `re.compile` | 标准库 `re` | 编译正则（事实抽取靠它） | `re.compile(正则)` → `Pattern`；`.finditer(文本)` → 逐个 `Match` |
| `re.sub` | 标准库 `re` | 按正则替换 | `re.sub(正则, 替换, 文本, count=1)` |
| `re.split` | 标准库 `re` | 按正则切分（切句子） | `re.split(r"[。；;\\n]+", 文本)` → `list[str]` |
| `dataclass` / `field` | 标准库 `dataclasses` | 快速定义数据结构 | `@dataclass`；`field(default_factory=list)` |
| `hashlib`? 不需要 | —— | 指纹直接用字符串拼接即可 | `f"{key}={value}"` |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `Message` | `core.message` | 一条消息：`Message.system(文本)` / `.user()` / `.assistant()` / `.tool_result()` |
| `estimate_tokens` | `core.llm` | 极简 token 估算：**中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token** |

> 完整的记忆管理器在 `stages/stage05_memory/memory.py`（约 380 行）：
> `FactExtractor` / `RuleSummarizer` / `LongTermStore` / `MemoryManager`。
> 本章每一节都会**先自己写一遍最小版**，再告诉你工程版多做了什么。

### 随时可查

```python
explain(Message)            # 消息结构：字段与四个构造方法
explain(estimate_tokens)    # token 估算函数的参数与返回
explain()                   # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "50 轮之后，Agent 还记得什么")

    nb.md("""### 现在卡在哪

第 01 章我们说「Agent 的记忆就是一个 list」：

```python
messages.append(...)                 # 每发生一件事就加一条
llm.complete(messages)               # 每次把整个 list 发给模型
```

这个设计在第 50 轮时会同时踩三个坑：

1. **物理上塞不下**：上下文窗口是硬上限，超了 API 直接报错；
2. **经济上不划算**：每一轮都要重发全部历史，成本随轮数**平方级**增长（第 12 章）；
3. **效果上更差**：上下文越长，模型对中间部分的注意力越弱（⑥ 节会实测）。

直觉的解法有两个，它们恰好死在两个极端：

| 方案 | 预算 | 效果 | 死因 |
|---|---|---|---|
| A 全量塞进去 | **爆** | 好 | 上下文有硬上限 |
| B 只留最近 N 轮 | 省 | **关键事实全丢** | 按时间淘汰 = 按无关性淘汰 |

### 先亲眼看一下

真实对话里有一条规律：**最要命的信息往往在最开始那几轮说出来。**
下面造一段 50 轮的对话，关键事实全部集中在**前 4 轮**，后面 46 轮全是寒暄和琐事。""")

    nb.code('''# 单独可运行：50 轮对话之后，Agent 还记不记得你的名字？
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.message import Message
from core.llm import estimate_tokens

BUDGET = 1200        # ← 试着改这里：改成 400，看两个方案分别变成什么样
KEEP_LAST = 6        # ← 方案 B 只保留最近几轮

SYSTEM = "你是团建筹备助手。只依据上下文里出现过的事实回答，不要凭猜测补充。"

# ---- 关键事实全在**最前面 4 轮**（真实对话就是这样）----
OPENING = [
    ("你好，我叫张三，我在筹备下个月的部门团建。", "你好张三！需要我帮你做什么？"),
    ("我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。", "好的：24 人 / 预算 5000 元 / 3 月 15 日。"),
    ("重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。", "收到，会避开海鲜。"),
    ("另外订单 A1001 的发票麻烦一起处理。", "好的，订单 A1001 的发票记下了。"),
]
NOISE_TOPICS = ["桌游道具", "交通安排", "拍照留念", "签到表", "伴手礼",
                "座位安排", "饮料清单", "背景音乐", "伴手礼包装", "游戏奖品"]


def build_turns(n=50):
    """造 n 轮对话：前 4 轮是干货，后面全是噪音。

    参数 n：总轮数
    返回  ：list[(用户说的话, 助手说的话)]
    """
    turns = list(OPENING)
    for i in range(len(OPENING) + 1, n + 1):
        topic = NOISE_TOPICS[i % len(NOISE_TOPICS)]          # 轮流换话题，制造"无关信息"
        turns.append((f"第 {i} 轮：再确认一下{topic}的事，你记一下。",
                      f"好的，第 {i} 轮关于{topic}的信息我记下了，后面安排的时候我会主动提醒你。"))
    return turns


def full_history(turns, query):
    """方案 A 的基线：把全部历史原样塞进去。"""
    msgs = [Message.system(SYSTEM)]
    for user, assistant in turns:
        msgs.append(Message.user(user))
        msgs.append(Message.assistant(assistant))
    msgs.append(Message.user(query))
    return msgs


def naive_truncate(turns, query, keep_last=KEEP_LAST):
    """方案 B 的基线：只保留最近 N 轮（新手最常写的代码）。"""
    msgs = [Message.system(SYSTEM)]
    for user, assistant in turns[-keep_last:]:
        msgs.append(Message.user(user))
        msgs.append(Message.assistant(assistant))
    msgs.append(Message.user(query))
    return msgs


def meter(used, total, width=30):
    """把预算用量画成一根进度条 —— 上下文工程里最直观的"算账"工具。"""
    ratio = min(used / total, 1.0) if total else 0.0
    filled = int(round(width * ratio))
    return f"[{'#' * filled}{'.' * (width - filled)}] {used:>5}/{total} token ({ratio * 100:>3.0f}%)"


# ---- 要检查的关键事实：值 -> 名字 ----
KEY_FACTS = {"张三": "姓名", "海鲜": "饮食禁忌", "5000": "预算", "A1001": "订单号"}


def recall(messages):
    """模拟"一个只会看上下文的模型"能回忆起什么。

    真实模型当然比这聪明，但它有一个不可逾越的限制：
    **上下文里没有的东西，它只能编。** 这里用"字符串在不在"来近似这件事。
    """
    text = "\\n".join(m.content for m in messages)
    found = {name: (value in text) for value, name in KEY_FACTS.items()}
    missing = [name for name, ok in found.items() if not ok]
    got = [name for name, ok in found.items() if ok]
    answer = "我在当前上下文里只能确认：" + ("（什么都没有）" if not got else "、".join(got))
    if missing:
        answer += "。以下信息在上下文里找不到：" + "、".join(missing)
    return got, missing, answer


TURNS = build_turns(50)
QUERY = "帮我订一家餐厅，安排 24 人的团建晚餐。"

print(f"对话共 {len(TURNS)} 轮。关键事实全在**最前面 4 轮**：")
for user, _ in OPENING:
    print("   -", user)
print()

for label, msgs in (("方案 A · 全量历史", full_history(TURNS, QUERY)),
                    ("方案 B · 只留最近 6 轮", naive_truncate(TURNS, QUERY))):
    used = sum(estimate_tokens(m.content) for m in msgs)
    print(f"{label:<22}: {len(msgs)} 条消息 / {used} token")
    print(f"    {meter(used, BUDGET)}")
    if used > BUDGET:
        print(f"    [!] 超出预算 {used / BUDGET:.1f} 倍 —— 真实 API 到这里会直接报错（上下文超限）")
    _, missing, answer = recall(msgs)
    print(f"    Agent 的回答: {answer}")
    print()

print("★ 方案 A 装不下，方案 B 装得下但**把最要命的那条丢了**。")
print("  第 1 轮说的「我对海鲜过敏」比第 46 轮说的「桌游道具」重要得多 ——")
print("  按时间淘汰 = 按无关性淘汰，早晚会把关键事实删掉。")''')

    nb.md("""### 结果说明什么

- **方案 A 超出预算约 2 倍**：这不是"慢一点"，是真实 API 会直接返回错误；
- **方案 B 把姓名/忌口/预算/订单号全丢了**，而且它**不报错** ——
  Agent 会很自信地把「你叫什么我没印象」当成正常回答。这类事故的根因是
  **上下文供给不足**，而不是模型能力不足；
- 两个方案都在用同一个错误的假设：**信息价值和出现时间无关。**
  第 46 轮的「桌游道具」可以忘，第 1 轮的「海鲜过敏」不能忘。

### 所以正确的目标不是「压缩」，而是「按价值取舍」

工业界的做法是**四件套**，缺一不可：

| 机制 | 覆盖范围 | 保真度 | 致命弱点 |
|---|---|---|---|
| 滑动窗口 | 最近几轮 | 原文，100% | 覆盖太短 |
| 摘要压缩 | 全部历史 | 有损，会悄悄漏 | 一定漏 |
| 事实钉住 | 关键事实 | 精确 | 必须有上限 |
| 长期存储 | 跨会话 | 精确 | 检索不准时注入的是**污染** |

它们不是"四选一"，而是**四层纵深防御**：摘要漏掉的靠钉住兜，钉住装不下的靠存储兜。

但在动手压缩之前，有一件事必须先做。""")

    # ==================================================================
    section(nb, "②", "先算账，再决定放什么")

    nb.md("""### 现在卡在哪

新手做上下文管理的第一反应是「压缩」。但压缩之前得先回答：

- 我的**总预算**是多少 token？
- 每一块（系统提示 / 事实 / 摘要 / 窗口）**各占多少**？
- 压哪一块才有效？

没有这张账，压缩就是凭感觉 —— 最后一定会失控，而且失控时你不知道是哪一块涨上去的。

### 所以我需要「一个能算 token 的尺子 + 一张分块的账」

**尺子**：`estimate_tokens(文本)`，来自 `core.llm`。

```python
estimate_tokens(文本) -> int
    参数：任意字符串
    返回：估算的 token 数（中文按 1 字 ≈ 1 token，英文按 4 字符 ≈ 1 token）
```

> 它只是**估算**，真实上线必须用厂商的分词器（tiktoken 之类）。
> 差几个 token 就可能在"刚好卡窗口"的请求上 400 报错。这里用它观察趋势足够。

**账本**：一个 `Section`，记录每一块的名字、token 数、条数、以及**为什么存在**。

### 预算分配顺序 = 策略

```
   ① 系统提示   不可压缩（压缩它等于改程序）
   ② 钉住事实   硬上限 MAX_PINNED=8，按重要性排序
   ③ 长期召回   必须过相关性闸门（宁可少注入，不可乱注入）
   ④ 滚动摘要   有字数上限，是「更早的对话」的唯一代表
   ⑤ 对话窗口   拿走剩下的全部（最新的原文，细节最全）
   ⑥ 当前问题   永远放最后
```

排序依据是**不可替代性**：系统提示不可替代，最新一轮也不可替代（它带着当前问题）。

### 立刻用一次""")

    nb.code('''# 单独可运行：先算账 —— 一张预算表告诉你该压哪一块
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, field
from core.llm import estimate_tokens

BUDGET = 1200        # ← 试着改这里：改成 400，看账本里哪几块被挤掉


def meter(used, total, width=30):
    """预算进度条。ratio 用 min() 截断，否则超预算时进度条会画到屏幕外面。"""
    ratio = min(used / total, 1.0) if total else 0.0
    filled = int(round(width * ratio))
    return f"[{'#' * filled}{'.' * (width - filled)}] {used:>5}/{total} token ({ratio * 100:>3.0f}%)"


@dataclass
class Section:
    """上下文里的一块。note 说明这一块**为什么存在**（不是装饰，是给排障用的）。"""
    name: str
    text: str = ""
    items: int = 0
    note: str = ""
    budget: int = 0

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)

    def line(self) -> str:
        cap = f"/{self.budget}" if self.budget else ""
        return f"{self.name:<10} {self.tokens:>5}{cap:<7} token  {self.items:>2} 条  {self.note}"


# ---- 六块内容的真实文本（这里写成字面量，方便你先只看"账"）----
SYSTEM = "你是团建筹备助手。只依据上下文里出现过的事实回答，不要凭猜测补充。"
PINNED = ("已确认的关键事实（必须遵守）：\\n"
          "- 姓名：张三\\n- 饮食禁忌：海鲜\\n- 预算：5000 元\\n"
          "- 日期：3 月 15 日\\n- 人数：24 人\\n- 订单号：A1001")
RECALLED = ("可能相关的历史记忆（仅供参考，冲突时以本轮对话为准）：\\n"
            "- 饮食禁忌：海鲜（第 1 次会话）\\n- 预算：5000（第 1 次会话）")
SUMMARY = ("更早对话的摘要（共 44 轮，已压缩）：\\n"
           "我们一共 24 人；预算 5000 元；日期定在 3 月 15 日；我对海鲜过敏，餐厅要避开海鲜；"
           "订单 A1001 的发票要一起处理")
WINDOW = ("用户：第 45 轮：再确认一下游戏奖品的事。\\n助手：好的，记下了。\\n"
          "用户：第 46 轮：再确认一下座位安排的事。\\n助手：好的，记下了。\\n"
          "用户：第 47 轮：再确认一下伴手礼包装的事。\\n助手：好的，记下了。\\n"
          "用户：第 48 轮：再确认一下饮料清单的事。\\n助手：好的，记下了。\\n"
          "用户：第 49 轮：再确认一下背景音乐的事。\\n助手：好的，记下了。\\n"
          "用户：第 50 轮：再确认一下游戏奖品的事。\\n助手：好的，记下了。")
QUERY = "帮我订一家餐厅，安排 24 人的团建晚餐。"

sections = [
    Section("系统提示", SYSTEM, 1, "不可压缩", budget=estimate_tokens(SYSTEM)),
    Section("钉住事实", PINNED, 6, "永不淘汰（上限 8 条）"),
    Section("长期召回", RECALLED, 2, "过相关性闸门"),
    Section("滚动摘要", SUMMARY, 1, "覆盖 44 轮"),
    Section("对话窗口", WINDOW, 6, "最近 6 轮原文"),
    Section("当前问题", QUERY, 1, "永远放最后"),
]

print(f"预算：{BUDGET} token")
print("预算账本：")
print("-" * 68)
for s in sections:
    print("  |", s.line())
total = sum(s.tokens for s in sections)
print("-" * 68)
print(f"  | {'合计':<10} {total:>5} token   （窗口内 {sum(s.items for s in sections)} 条）")
print(f"    {meter(total, BUDGET)}")
print()

# ---- 账本自洽检查：分块之和必须等于你真正发出去的那些消息的 token 之和 ----
by_message = sum(estimate_tokens(t) for t in
                 [SYSTEM, PINNED, RECALLED, SUMMARY, WINDOW, QUERY])
print(f"逐条重算：{by_message} token     分块之和：{total} token")
print("账本自洽" if by_message == total else "[!] 账本对不上 —— 你就在按一个不存在的数字做预算")
print()
print("★ 看两件事：")
print("  1. 最大的两块是「对话窗口」和「摘要」—— 想省钱就得从这两块下手；")
print("  2. 「钉住事实」只有几十 token，却装着最不能丢的信息 —— 这是性价比最高的一块。")''')

    nb.md("""### 结果说明什么

- **先算账，再压缩**。账本让你知道"压哪一块有效"，也让你在出问题时能一眼看出
  是哪一块涨上去了（线上排障全靠它）；
- **账本必须自洽**：分块之和要等于真正发出去的消息的 token 之和。
  对不上就说明你在按一个不存在的数字做预算 —— 这种 bug 很隐蔽，但很致命；
- 钉住事实只占几十 token，却装着最不能丢的东西。**预算不是均分的，是按其不可替代性分的。**

现在知道该压哪一块了。第一个要保护的，是那几件「丢了就出事」的事实。""")

    # ==================================================================
    section(nb, "③", "什么值得记：事实抽取 + 钉住")

    nb.md("""### 现在卡在哪

窗口和摘要都是**有损**的：窗口只覆盖最近几轮，摘要一定会漏。
可有些信息漏一次就出事：

- 用户说「我对海鲜过敏」→ 漏了，模型推荐海鲜餐厅 → **这是安全事故，不是体验问题**；
- 用户说「订单 A1001」→ 漏了，模型编一个订单号去查 → 查到别人的订单。

### 所以我需要「把关键信息从对话里抽出来，单独钉在一个永不淘汰的地方」

判断标准只有一条：**这条信息后面还会不会被用到？用错了会不会出事？**

| 信息 | 会不会再用到 | 用错了会怎样 |
|---|---|---|
| 姓名 / 称呼 | 反复用到 | 叫错了很难受 |
| 禁忌 / 过敏 | 每次推荐都要用 | **会出人命** |
| 预算 / 约束 | 是后续所有决策的边界 | 超支 |
| 订单号 / 单号 | 是工具调用的参数 | 错一位就查不到 |

反过来，「今天天气不错」这类寒暄，价值 ≈ 0，第一个该被压缩掉。

### 它的用法

用**正则规则**把"值得记的话"抽成结构化事实：

```python
FACT_RULES = [
    (r"我叫([\\u4e00-\\u9fa5A-Za-z]{2,4})", "姓名", 1.00),      # (正则, 字段名, 重要性)
    (r"我(?:对|吃)?([\\u4e00-\\u9fa5]{2,6})过敏", "饮食禁忌", 1.00),
    ...
]
```

| 部分 | 含义 |
|---|---|
| `re.compile(正则)` | 预先编译，反复用同一个 Pattern（比每次现编译快） |
| `Pattern.finditer(文本)` | 找出**所有**匹配 → 逐个 `Match` 对象 |
| `Match.group(1)` | 第 1 个括号里捕获的内容（就是我们要的值） |
| `\\u4e00-\\u9fa5` | 常用汉字的 Unicode 范围（正则里表示「一个汉字」） |
| 重要性 ≥ 阈值 | 这条事实进**钉住区**（`PIN_THRESHOLD = 0.75`） |

生产环境里这一步常常让模型来做抽取（更准，但要花钱、不确定）；
规则版的价值是**可测试、可解释、零成本** —— 学习阶段先用它。

### 立刻用一次""")

    nb.code('''# 单独可运行：什么值得钉住？—— 规则版事实抽取
MAX_PINNED = 8          # ← 试着改这里：改成 1000，看钉住区会不会吃掉整个窗口
PIN_THRESHOLD = 0.75    # <- 也可以改成 0.0（题目要求：什么都钉住）

import re
from dataclasses import dataclass, field
from core.llm import estimate_tokens    # 算账用的尺子（② 节讲过）

# (正则, 字段名, 重要性)：重要性 >= PIN_THRESHOLD 的事实会被钉住
FACT_RULES = [
    (r"我叫([\\u4e00-\\u9fa5A-Za-z]{2,4})", "姓名", 1.00),
    (r"我(?:对|吃)?([\\u4e00-\\u9fa5]{2,6})过敏", "饮食禁忌", 1.00),
    (r"预算(?:是|为|大概)?\\s*([0-9,]+)\\s*(?:元|块|万)", "预算", 0.98),
    (r"订单\\s*([A-Za-z]{0,2}\\d{3,})", "订单号", 0.92),
    (r"日期(?:定在|是|为|改到)\\s*([0-9]{1,2}\\s*月\\s*[0-9]{1,2}\\s*[日号])", "日期", 0.80),
    (r"一共\\s*([0-9]+)\\s*(?:人|位|个)", "人数", 0.78),
    (r"我(?:喜欢|偏好|习惯|希望)([\\u4e00-\\u9fa5]{2,8}?)(?:[，,。]|$)", "偏好", 0.55),
]


@dataclass
class Fact:
    """一条结构化事实。**结构化是关键**：可以判重、可以打分、可以排序、可以落库。"""
    key: str
    value: str
    turn: int = 0
    importance: float = 0.5
    pinned: bool = False

    @property
    def text(self) -> str:
        return f"{self.key}：{self.value}"

    @property
    def fingerprint(self) -> str:
        """指纹用于判重：同一个事实说两遍，不该占两个位置。"""
        return f"{self.key}={self.value}"


def extract(text: str, turn: int = 0) -> list:
    """从一段文本里抽出所有事实。

    参数 text：用户说的话（**只用用户消息**，理由见下面那个坑）
         turn：这是第几轮（保留出处，便于溯源）
    返回      ：list[Fact]
    """
    out = []
    for pattern, key, importance in FACT_RULES:
        for m in re.compile(pattern).finditer(text or ""):
            value = m.group(1).strip()
            if value:
                out.append(Fact(key, value, turn, importance,
                                pinned=importance >= PIN_THRESHOLD))
    return out


# ---- 立刻用一次：从第 1~4 轮里抽事实 ----
UTTERANCES = [
    "你好，我叫张三，我在筹备下个月的部门团建。",
    "我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。",
    "重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。",
    "另外订单 A1001 的发票麻烦一起处理。",
    "今天天气不错，随便聊聊。",                 # 寒暄：抽不出任何事实（正确）
]

facts = []
for i, text in enumerate(UTTERANCES, 1):
    for f in extract(text, turn=i):
        # 判重：同一个指纹只留一条（用户可能反复强调同一件事）
        if f.fingerprint not in {x.fingerprint for x in facts}:
            facts.append(f)

print("抽出来的事实（按重要性排序）：")
for f in sorted(facts, key=lambda x: -x.importance):
    mark = "钉住" if f.pinned else "普通"
    print(f"   [{mark}] {f.text:<22} 重要性 {f.importance:.2f}  出处：第 {f.turn} 轮")

pinned = [f for f in facts if f.pinned][:MAX_PINNED]
print()
print(f"钉住区（最多 {MAX_PINNED} 条，实际 {len(pinned)} 条）：")
print("   已确认的关键事实（必须遵守）：")
for f in pinned:
    print("      -", f.text)
print()

# ---- 失败模式：把上限和阈值都放开会怎样 ----
# 造 46 轮"每条都提到一个订单号"的噪音（真实场景：销售助理天天在处理订单）
NOISE = [f"第 {i} 轮：订单 B{2000 + i} 的进度也帮我盯一下。" for i in range(5, 51)]
all_facts = list(facts)
for i, text in enumerate(NOISE, 5):
    all_facts.extend(extract(text, turn=i))          # 噪音轮也在源源不断地"贡献事实"

tight_text = "已确认的关键事实（必须遵守）：\\n" + "\\n".join("- " + f.text for f in pinned)
loose_text = "已确认的关键事实（必须遵守）：\\n" + "\\n".join("- " + f.text for f in all_facts)

print(f"50 轮对话一共抽出 {len(all_facts)} 条事实（其中 {len(pinned)} 条够格钉住）")
print("对照（把 MAX_PINNED 放开成 1000、阈值调成 0.0，也就是【什么都钉住】）：")
print(f"   正常设置（{len(pinned):>2} 条）      : {estimate_tokens(tight_text):>4} token")
print(f"   什么都钉住（{len(all_facts):>2} 条）  : {estimate_tokens(loose_text):>4} token")
print("   -> 在 1200 token 的预算里，第二行会挤掉几乎整个对话窗口。")
print()
print("★ 结论：**「永不淘汰」的机制必须自带配额。**")
print("  钉住区一旦没有上限，它自己就变成了一个新的、不可压缩的超支来源。")
print("  所有缓存 / 记忆系统都是同一条规矩：能永久保留的东西，必须限量。")
print()
print("★ 规则抽取还有一个真实的坑（本章实测踩过）：")
for q in ["我叫什么？", "我对什么过敏来着？"]:
    print(f"   抽「{q}」 -> {[f.text for f in extract(q)]}")
print("   用户是在**提问**，不是在陈述 —— 规则抽取必须区分这两者，")
print("   最省事的做法是：只在「用户陈述」上跑抽取，别在提问上跑。")''')

    nb.md("""### 结果说明什么

- 抽取出来的事实是**结构化**的：有字段名、有重要性、有出处。这让它
  可判重（`fingerprint`）、可排序（`importance`）、可落库（④ 节）；
- **钉住区必须带上限**。上面那组对照说明：一旦"什么都钉住"，
  钉住区会膨胀到挤掉几乎整个对话窗口 —— 你为了保住信息，把上下文全弄丢了；
- 规则抽取会把**提问**误当成**陈述**（「我叫什么？」→ `姓名：什么`）。
  这是真实踩过的坑，也是"上模型做抽取"的动机之一。

现在最要命的信息有地方放了。**剩下的历史怎么办？**""")

    # ==================================================================
    section(nb, "④", "滚动摘要：增量，而不是每次重算")

    nb.md("""### 现在卡在哪

超出窗口的旧对话不能直接扔（那里可能有钉住规则没覆盖到的信息）。
把它们压成一段**摘要**，是唯一可行的做法。

但摘要有个反直觉的坑：**"摘要的摘要"会漂移。**
如果每一轮都拿"最近淘汰的对话"重新算一遍摘要，那么很早以前的事
会在反复重算里一点点模糊掉 —— 每压一次丢一点，压十次就没了。

### 所以我需要「增量滚动」的摘要

```
   ✗ 每次重算：summary = summarize(最近淘汰的对话)          <- 老信息每轮被稀释一次
   ✓ 增量滚动：summary = summarize(旧摘要 + 新淘汰的对话)    <- 旧摘要始终参与
```

两个细节决定成败：

1. **旧摘要参与下一轮压缩** —— 否则"很久以前的事"会在反复重算中消失；
2. **摘要必须有字数上限** —— 摘要自己无限膨胀的话，压缩就白做了。

生产环境里摘要是让模型写的（一次模型调用，也要花钱、也有延迟）；
本课程用**规则版抽取式摘要**（挑出含关键词的句子），保证输出完全可复现。

### 立刻用一次""")

    nb.code('''# 单独可运行：滚动摘要 —— 增量，而不是每次重算
FEED_OLD_SUMMARY = True     # ← 试着改这里：改成 False，看"很久以前的事"怎么消失

import re
from dataclasses import dataclass, field

# ---- 规则版摘要器：从若干段文本里挑出"值得记住"的句子 ----
KEEP_HINTS = ("预算", "日期", "过敏", "人数", "订单", "发票", "元", "必须",
              "不要", "禁忌", "一共", "人")


class RuleSummarizer:
    """确定性的抽取式摘要器（零依赖、可测试）。

    它扮演的是"摘要模型"这个角色：真实项目里换成一次 LLM 调用即可。
    """

    def __init__(self, max_chars: int = 260):
        self.max_chars = max_chars        # ★ 摘要自己也要封顶

    def summarize(self, pieces) -> str:
        """参数 pieces：若干段文本（旧摘要 + 新淘汰的对话）；返回一段摘要字符串。"""
        kept, seen = [], set()
        for piece in pieces:
            # 按句号/分号/换行切句 —— 摘要的单位是"句子"，不是"字符"
            for sentence in re.split(r"[。；;\\n]+", piece or ""):
                s = sentence.strip()
                if len(s) < 4 or s in seen:       # 太短 / 重复的丢掉
                    continue
                if any(h in s for h in KEEP_HINTS):   # 命中关键词才留
                    seen.add(s)
                    kept.append(s)
        text = "；".join(kept)
        if len(text) > self.max_chars:
            text = text[:self.max_chars].rstrip("；") + "…"
        return text


OPENING = [
    "你好，我叫张三，我在筹备下个月的部门团建。",
    "我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。",
    "重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。",
    "另外订单 A1001 的发票麻烦一起处理。",
]
NOISE_TOPICS = ["桌游道具", "交通安排", "拍照留念", "签到表", "伴手礼",
                "座位安排", "饮料清单", "背景音乐", "伴手礼包装", "游戏奖品"]


def turn_text(i: int) -> str:
    """第 i 轮用户说的话。前 4 轮是干货，后面全是噪音。"""
    if i <= len(OPENING):
        return OPENING[i - 1]
    return f"第 {i} 轮：再确认一下{NOISE_TOPICS[i % len(NOISE_TOPICS)]}的事，你记一下。"


class WindowMemory:
    """只做两件事：留最近 N 轮原文 + 把更早的压成滚动摘要。"""

    def __init__(self, window_turns=6, summarizer=None, feed_old=True):
        self.window_turns = window_turns
        self.summarizer = summarizer or RuleSummarizer()
        self.feed_old = feed_old
        self.turns = []              # 全部轮次（教学里留着做对照，生产里该落库）
        self.summary = ""            # 当前摘要
        self.compressed_turns = 0    # 已经被摘要吸收掉的轮数
        self.calls = 0               # 摘要调用次数（每次都是一次"模型调用"）

    def add(self, user_text: str) -> None:
        self.turns.append(user_text)
        self._compress_if_needed()

    def _compress_if_needed(self) -> None:
        """超出窗口的旧对话 -> 摘要。**增量滚动**，不是每次重算。"""
        if len(self.turns) <= self.window_turns:
            return
        aged = self.turns[: len(self.turns) - self.window_turns]
        if len(aged) <= self.compressed_turns:
            return                              # 没有新的内容需要压，直接跳过
        fresh = aged[self.compressed_turns:]
        pieces = ([self.summary] if (self.feed_old and self.summary) else []) + fresh
        self.summary = self.summarizer.summarize(pieces)
        self.compressed_turns = len(aged)
        self.calls += 1

    def build(self, query: str):
        """组装上下文：系统提示 + 摘要 + 最近窗口 + 当前问题。"""
        msgs = ["系统提示：你是团建筹备助手。"]
        if self.summary:
            msgs.append(f"更早对话的摘要（共 {self.compressed_turns} 轮，已压缩）：\\n{self.summary}")
        msgs.extend(self.turns[-self.window_turns:])
        msgs.append("当前问题：" + query)
        return msgs


mem = WindowMemory(window_turns=6, feed_old=FEED_OLD_SUMMARY)
print(f"FEED_OLD_SUMMARY = {FEED_OLD_SUMMARY}")
print()
for i in range(1, 51):
    mem.add(turn_text(i))
    if i in (10, 20, 30, 50):
        print(f"第 {i:>2} 轮后 : 摘要 {len(mem.summary):>3} 字，已折叠 {mem.compressed_turns:>2} 轮，"
              f"摘要调用 {mem.calls} 次")
        print(f"    | {mem.summary[:96]}")
print()
print("早期事实在不在摘要里：")
for key, value in (("姓名", "张三"), ("禁忌", "海鲜"), ("预算", "5000"), ("订单号", "A1001")):
    print(f"   {key:<6}: {'在' if value in mem.summary else '[!] 不在'}")
print()
if FEED_OLD_SUMMARY:
    print("★ 46 轮噪音没有挤掉任何一条**命中关键词**的句子 —— 因为旧摘要每轮都参与了压缩。")
    print("  但注意上面有个 [!]：摘要**确实漏掉了「姓名」** —— 那句话没命中任何关键词。")
    print("  摘要一定会漏，这就是为什么关键事实还必须同时进**钉住区**（③ 节）。")
else:
    print("★ 关掉 feed_old 之后：摘要只覆盖最近被淘汰的那一批对话，")
    print("  早期事实（忌口、预算、订单号）已经掉出了摘要 —— 这就是「摘要漂移」。")
print(f"★ 而且摘要本身只有 {len(mem.summary)} 字（上限 260）—— 摘要自己膨胀的话，压缩就白做了。")
print(f"★ 代价：一共做了 {mem.calls} 次摘要调用。真实系统里每一次都是一次模型调用，")
print("  所以工程上会「攒够一批再压」或放到后台异步压，绝不会每轮都重压。")''')

    nb.md("""### 结果说明什么

| 设置 | 摘要里的早期事实 | 说明 |
|---|---|---|
| `FEED_OLD_SUMMARY = True` | 姓名 / 忌口 / 预算 / 订单号**都在** | 旧摘要参与压缩，老信息不会漂移 |
| `FEED_OLD_SUMMARY = False` | 姓名、忌口、订单号**丢了** | 每轮只压"最近淘汰的那批"，老信息被挤出去 |

三条工程纪律：

1. **摘要要增量滚动**，旧摘要必须参与下一轮 —— 否则"摘要的摘要"会一层层衰减；
2. **摘要必须封顶**（`max_chars`），否则它自己会变成新的超支来源；
3. **摘要本身也是一次模型调用**，也花钱、也有延迟。触发式压缩（攒够一批再压）
   或后台异步压缩才是现实做法，不要每轮重压（那是 O(n²) 次调用）。

摘要能覆盖"全部历史的梗概"，但它救不回**跨会话**的信息。""")

    # ==================================================================
    section(nb, "⑤", "长期记忆：跨会话 + 相关性闸门")

    nb.md("""### 现在卡在哪

窗口和摘要都是「这一次会话」内的事。用户关掉页面、下周再来：

- 窗口空了；
- 摘要归零；
- 于是 Agent 又问一遍「请问怎么称呼您？」—— 而它上周已经问过三次。

### 所以我需要一个「跨会话的事实库」

它的机制和 RAG（第 06 章）**一模一样**：写入 → 索引 → 按相关性检索 → 注入上下文。
区别只在数据来源：RAG 检索文档，长期记忆检索「关于这个用户的事实」。

### 它的用法：写入 + 检索 + 闸门

```python
store.write(fact)                       # 写入（要判重，重复写入会挤占检索位）
store.search(query, top_k=3, min_score=1.0)   # 检索：返回最相关的几条
```

检索怎么打分？**中文按字符二元组（bigram）重叠度**：

```python
bigrams("海鲜过敏")  ->  {海鲜, 鲜过, 过敏}
bigrams("他对海鲜过敏") -> {他对, 对海, 海鲜, 鲜过, 过敏}
                                                        ↑ 重叠 3 个 -> 命中
```

为什么用二元组而不是单字？单字切分下「退」和「货」分开，`退货` 这个概念就没了，
而且单字 IDF 极低（几乎每个字都常见）。二元组零依赖，又天然保留搭配信息。

**`min_score` 是闸门**：不相关就不注入。为什么必须有它？

> 注入无关记忆比不注入**更糟**：模型会把旧任务的约束当成当前任务的约束
> —— 上次说要 24 人，这次只有 6 人，它也按 24 人办。

### 立刻用一次（含它救不了的情况）""")

    nb.code('''# 单独可运行：长期记忆 —— 写入、检索、闸门，以及它的盲区
import re
from dataclasses import dataclass, field


def bigrams(text: str) -> set:
    """中文按字符二元组切分 —— 零依赖、无需分词库。

    参数 text：任意文本
    返回    ：相邻两字组成的集合，例如「海鲜过敏」-> {海鲜, 鲜过, 过敏}
    """
    clean = re.sub(r"\\s+", "", text or "")
    return {clean[i:i + 2] for i in range(len(clean) - 1)} or ({clean} if clean else set())


@dataclass
class MemoryItem:
    """长期记忆里的一条。带 session/turn（**哪一次会话的第几轮说的**）才能溯源。"""
    text: str
    key: str = ""
    session: int = 1
    turn: int = 0
    importance: float = 0.5
    hits: int = 0


class LongTermStore:
    """极简长期记忆：写入 + 关键词检索。生产里换成向量库，但**接口就这两个**。"""

    def __init__(self):
        self.items = []

    def write(self, text: str, key: str = "", session: int = 1, turn: int = 0,
              importance: float = 0.5):
        """写入一条。**判重是必须的**：同一个事实反复写入会挤占检索位。"""
        for it in self.items:
            if it.text == text:
                it.hits += 1           # 说过多次 -> 计数 +1（说明它重要）
                return it
        item = MemoryItem(text=text, key=key, session=session, turn=turn,
                          importance=importance)
        self.items.append(item)
        return item

    def search(self, query: str, top_k: int = 3, min_score: float = 1.0):
        """按二元组重叠度打分。

        参数 query    ：当前用户的问题
             top_k    ：最多返回几条
             min_score：**相关性闸门** —— 重叠度不到这个值就不注入
        返回          ：list[MemoryItem]，按分数从高到低
        """
        q = bigrams(query)
        if not q:
            return []
        scored = []
        for it in self.items:
            overlap = len(q & bigrams(it.text))
            if overlap >= min_score:            # 闸门：不相关就不进候选
                # 相关性 + 重要性加权：重要的事实更容易被想起来
                scored.append((overlap + it.importance, it))
        scored.sort(key=lambda pair: (-pair[0], pair[1].text))
        return [it for _, it in scored[:top_k]]

    def render(self, items) -> str:
        """渲染成给模型看的文本 —— **带上出处**，否则用户没法核对。"""
        return "\\n".join(f"- {it.text}（第 {it.session} 次会话）" for it in items)


store = LongTermStore()
# ---- 第 1 次会话（上个月）落库的事实 ----
store.write("姓名：张三", key="姓名", session=1, turn=1, importance=1.0)
store.write("饮食禁忌：海鲜过敏", key="饮食禁忌", session=1, turn=3, importance=1.0)
store.write("预算：5000 元", key="预算", session=1, turn=2, importance=0.98)
store.write("订单号：A1001", key="订单号", session=1, turn=4, importance=0.92)
store.write("偏好：靠窗的位置", key="偏好", session=1, turn=7, importance=0.55)

print("长期记忆里有", len(store.items), "条（都来自第 1 次会话）")
print()

print("=== 第 2 次会话：用户问了四个问题，看检索器召回了什么 ===")
for query in ["上次说的海鲜过敏，餐厅别踩雷", "帮我订餐厅，24 人",
              "今天天气怎么样", "上次说的忌口是什么来着"]:
    hits = store.search(query, top_k=3, min_score=1.0)
    print(f"   提问：{query}")
    if hits:
        for it in hits:
            print(f"      -> {it.text}（重叠分 {len(bigrams(query) & bigrams(it.text)) + it.importance:.2f}）")
    else:
        print("      -> （无召回：过了相关性闸门，一条都不注入）")
    print()

print("★ 三种结果分别是：")
print("  1. 「海鲜过敏」命中了忌口 —— 关键词级召回可用；")
print("  2. 「今天天气怎么样」一条都不召回 —— **闸门生效，宁可不注入也不污染**；")
print("  3. 「忌口」**召不回**「饮食禁忌：海鲜过敏」—— 二元组不懂同义词。")
print()
print("★ 第 3 条是本章实测出来的硬伤，也是第 06 章的动机：")
print("  要跨过'字面不同但意思相同'这道坎，需要的是**向量检索**（embedding），")
print("  而不是更好的字符串匹配。")''')

    nb.md("""### 结果说明什么

| 查询 | 结果 | 说明 |
|---|---|---|
| 「海鲜过敏」 | 命中忌口 | 关键词级召回足够好 |
| 「今天天气怎么样」 | **一条都不召回** | 闸门生效，宁可少注入也不污染 |
| 「忌口」 | **召不回来** | 二元组不懂同义词 —— 这是机制层面的硬伤 |

第三条是这个设计的**能力边界**，不是 bug。真实系统里跨过它的办法是：

- **向量检索**（embedding）：把「忌口」和「饮食禁忌」映射到相近的向量（第 06 章）；
- **混合检索**：关键词 + 向量两路召回，再融合重排；
- **写入时就做好归一化**：把同义表达在写入阶段就统一（治标，但便宜有效）。

现在四件套的零件齐了：窗口、摘要、钉住、长期存储。**怎么把它们拼成一次请求？**""")

    # ==================================================================
    section(nb, "⑥", "组装：顺序就是策略")

    nb.md("""### 现在卡在哪

六块内容都准备好了，接下来是一个看起来纯排版的问题：**它们按什么顺序拼？**

顺序真的重要吗？同一份内容、同样的 token 数，只换位置 —— 模型的利用率会差很多。
这个现象有名字：**Lost in the Middle**（Liu et al., 2023）。

```
   ┌─────────────────────────────┐
   │ 系统提示 + 钉住事实          │ <- 注意力高 ✓
   │ ...                         │
   │ 大段大段的参考资料           │ <- 注意力低 ✗（内容再好也可能被忽略）
   │ ...                         │
   │ 最近几轮对话 + 当前问题      │ <- 注意力高 ✓
   └─────────────────────────────┘
```

### 所以排列规则是「两头放最不可替代的」

```
   ① 系统提示   最前（模型的"身份"，且不可压缩）
   ② 钉住事实   紧跟系统提示（丢了会出事的信息，放注意力最高的位置）
   ③ 长期召回   中间（参考资料，允许被"半读"）
   ④ 滚动摘要   中间
   ⑤ 对话窗口   靠后（最新的原文，细节最全）
   ⑥ 当前问题   **最后**（位置本身就是一种强调）
```

### 立刻用一次：做个位置实验

下面用一个"注意力只覆盖开头和结尾"的假读者来近似这件事
（真实模型不是这么机械的，但**方向**就是这样）。""")

    nb.code('''# 单独可运行：位置实验 —— 同样的内容，换个位置就"看不见"了
HEAD_CHARS = 320     # ← 试着改这里：把"注意力窗口"调大调小，看结论怎么变
TAIL_CHARS = 320

FACTS = ["姓名：张三", "饮食禁忌：海鲜过敏", "预算：5000 元", "订单号：A1001"]


def weak_reader(context: str, keys) -> list:
    """模拟「注意力只覆盖开头和结尾」的模型。

    参数 context：完整上下文文本
         keys   ：要确认的事实列表
    返回        ：能确认的事实（中间那段被"漏读"）
    """
    head = context[:HEAD_CHARS]
    tail = context[-TAIL_CHARS:]
    visible = head + tail
    return [k for k in keys if k in visible]


NOISE = "\\n".join(f"第 {i} 轮：再确认一下第 {i} 类杂事，你记一下。" for i in range(1, 31))

# ---- 位置 A：事实放在开头（紧跟系统提示）----
ctx_head = ("系统提示：你是团建筹备助手。\\n"
            "已确认的关键事实（必须遵守）：\\n" + "\\n".join("- " + f for f in FACTS) + "\\n"
            + NOISE + "\\n当前问题：帮我订餐厅。")

# ---- 位置 B：事实放在中间（第 30 条噪音之后）----
ctx_mid = ("系统提示：你是团建筹备助手。\\n"
           + NOISE + "\\n"
           "已确认的关键事实（必须遵守）：\\n" + "\\n".join("- " + f for f in FACTS) + "\\n"
           "当前问题：帮我订餐厅。")

def est(text):
    """极简 token 估算（和 core.llm.estimate_tokens 同一套规则）。"""
    cjk = sum(1 for ch in text if "\\u4e00" <= ch <= "\\u9fff")
    return cjk + max(1, (len(text) - cjk) // 4)

for label, ctx in (("事实放在开头（紧跟系统提示）", ctx_head),
                   ("事实放在中间（第 30 条噪音之后）", ctx_mid)):
    print(f"{label:<26}: {est(ctx):>4} token")
    got = weak_reader(ctx, FACTS)
    print(f"    模型能确认的事实: {got if got else '（什么都没有）'}")
    print(f"    漏掉的事实      : {[f for f in FACTS if f not in got]}")
    print()

print("★ 两份上下文的 token 数**完全一样**（" + str(est(ctx_head)) + " vs " + str(est(ctx_mid)) + "），")
print("  唯一的差别是位置 —— 但模型能读到的事实差别巨大。")
print()
print("★ 所以「钉住事实」要放在最前面（紧跟系统提示），")
print("  「当前问题」要放在最后面。这不是排版偏好，是**性能优化**。")''')

    nb.md("""### 结果说明什么

- 两份上下文的 token 数**完全一样**，只是换了位置，模型能读到的事实差别巨大；
- 这不是"模型不行"，而是注意力机制的固有特性。
  **工程上能做的是顺着它，而不是对抗它**：
  把最不可替代的信息放在注意力最高的两端；
- 另一条推论：**不要把关键信息埋在长资料的中间**。
  所以第 06 章注入检索片段时，会限制 top-k 并给每条编号（而不是倒进去 20 条）。

现在四件套 + 顺序都有了。最后做一件工程师必做的事：**把每一层拆掉，看谁在承重。**""")

    # ==================================================================
    section(nb, "⑦", "拆护栏：每一层都在承重")

    nb.md("""### 现在卡在哪

「四层纵深防御」听起来很美，但你怎么知道每一层都有用？

新手容易得出两个错误结论：

- 「我都用上了，效果当然好」→ 说不清哪一层在起作用；
- 「只拆一层没变化啊，那层是多余的」→ 因为**另一层兜住了**（冗余设计就是这样）。

正确做法是**逐层拆掉，看哪条事实先丢**。

### 立刻用一次：四个开关跑一遍

下面把完整实现拼起来（窗口 + 摘要 + 钉住 + 召回），然后用开关逐个关掉。""")

    nb.code('''# 单独可运行：把四层防御逐个拆掉，看哪条关键事实先丢
USE_PINNING = True      # ← 试着改这里：关掉"事实钉住"
USE_RECALL = True       # ← 试着改这里：关掉"长期召回"
USE_SUMMARY = True      # ← 试着改这里：关掉"滚动摘要"

import re
from dataclasses import dataclass, field

BUDGET = 1200
WINDOW_TURNS = 6
MAX_PINNED = 8
KEEP_HINTS = ("预算", "日期", "过敏", "人数", "订单", "发票", "元", "一共", "人")
FACT_RULES = [
    (r"我叫([\\u4e00-\\u9fa5A-Za-z]{2,4})", "姓名", 1.00),
    (r"我(?:对|吃)?([\\u4e00-\\u9fa5]{2,6})过敏", "饮食禁忌", 1.00),
    (r"预算(?:是|为|大概)?\\s*([0-9,]+)\\s*(?:元|块|万)", "预算", 0.98),
    (r"订单\\s*([A-Za-z]{0,2}\\d{3,})", "订单号", 0.92),
    (r"我(?:喜欢|偏好|习惯)([\\u4e00-\\u9fa5]{2,8}?)(?:[，,。]|$)", "偏好", 0.55),
]
# ★ 两个刻意的安排，为的是让你看清每一层各自在管什么：
#   · 这里**没有**「日期」规则 -> "3 月 15 日"只能靠摘要活着；
#   · 「偏好」的重要性 0.55 < 阈值 0.75 -> 它进不了钉住区，只能靠长期召回捞回来。
KEY = {"张三": "姓名", "海鲜": "饮食禁忌", "5000": "预算",
       "A1001": "订单号", "3 月 15 日": "团建日期", "靠窗的位置": "座位偏好"}


def est(text):
    cjk = sum(1 for ch in text if "\\u4e00" <= ch <= "\\u9fff")
    return cjk + max(1, (len(text) - cjk) // 4)


def bigrams(text):
    clean = re.sub(r"\\s+", "", text or "")
    return {clean[i:i + 2] for i in range(len(clean) - 1)} or ({clean} if clean else set())


def summarize(pieces, max_chars=260):
    kept, seen = [], set()
    for piece in pieces:
        for s in re.split(r"[。；;\\n]+", piece or ""):
            s = s.strip()
            if len(s) >= 4 and s not in seen and any(h in s for h in KEEP_HINTS):
                seen.add(s)
                kept.append(s)
    text = "；".join(kept)
    return text[:max_chars].rstrip("；") + "…" if len(text) > max_chars else text


@dataclass
class Fact:
    key: str
    value: str
    importance: float = 0.5
    turn: int = 0
    session: int = 1

    @property
    def text(self):
        return f"{self.key}：{self.value}"

    @property
    def fingerprint(self):
        return f"{self.key}={self.value}"


class MemoryManager:
    """窗口 + 摘要 + 钉住 + 长期召回。三个开关是**故意留的**（只为教学对照）。"""

    def __init__(self, budget=BUDGET, window_turns=WINDOW_TURNS,
                 use_pinning=True, use_recall=True, use_summary=True):
        self.budget = budget
        self.window_turns = window_turns
        self.use_pinning = use_pinning
        self.use_recall = use_recall
        self.use_summary = use_summary
        self.turns = []          # [(用户, 助手)]
        self.facts = []          # 抽出来的事实
        self.store = []          # 长期记忆：[(text, session)]
        self.summary = ""
        self.compressed = 0

    def add_turn(self, user, assistant=""):
        self.turns.append((user, assistant))
        # ① 抽事实（只在**用户陈述**上抽）
        for pattern, key, imp in FACT_RULES:
            for m in re.compile(pattern).finditer(user):
                f = Fact(key, m.group(1).strip(), imp, len(self.turns))
                if f.fingerprint not in {x.fingerprint for x in self.facts}:
                    self.facts.append(f)
                    self.store.append((f.text, 1))     # 关键事实同时落库（双保险）
        # ② 压缩
        if self.use_summary:
            self._compress()

    def _compress(self):
        if len(self.turns) <= self.window_turns:
            return
        aged = self.turns[: len(self.turns) - self.window_turns]
        if len(aged) <= self.compressed:
            return
        fresh = [u + "。" + a for u, a in aged[self.compressed:]]
        pieces = ([self.summary] if self.summary else []) + fresh   # 旧摘要参与
        self.summary = summarize(pieces)
        self.compressed = len(aged)

    def build(self, query):
        """按 ⑥ 节的顺序组装。返回 (消息列表, 每一块的账)。"""
        msgs, ledger = [], []
        msgs.append("系统提示：你是团建筹备助手。")
        ledger.append(("系统提示", "不可压缩"))

        if self.use_pinning:
            pinned = sorted([f for f in self.facts if f.importance >= 0.75],
                            key=lambda f: -f.importance)[:MAX_PINNED]
            if pinned:
                text = "已确认的关键事实（必须遵守）：\\n" + "\\n".join("- " + f.text for f in pinned)
                msgs.append(text)
                ledger.append(("钉住事实", f"{len(pinned)} 条"))
        else:
            pinned = []

        if self.use_recall and query:
            hits = []
            for text, session in self.store:
                if len(bigrams(query) & bigrams(text)) >= 1.0:      # 相关性闸门
                    hits.append((text, session))
            if hits:
                msgs.append("可能相关的历史记忆（仅供参考）：\\n"
                            + "\\n".join(f"- {t}（第 {s} 次会话）" for t, s in hits[:3]))
                ledger.append(("长期召回", f"{len(hits[:3])} 条"))

        if self.use_summary and self.summary:
            msgs.append(f"更早对话的摘要（共 {self.compressed} 轮，已压缩）：\\n{self.summary}")
            ledger.append(("滚动摘要", f"覆盖 {self.compressed} 轮"))

        # 窗口：拿走剩下的全部预算（从最近往前装，装不下就停）
        used = sum(est(m) for m in msgs) + est(query)
        remaining = max(self.budget - used, est(query) + 8)
        picked = []
        for user, assistant in reversed(self.turns[-self.window_turns:]):
            cost = est(user) + est(assistant)
            if cost > remaining:
                break
            picked.append((user, assistant))
            remaining -= cost
        picked.reverse()
        for user, assistant in picked:
            msgs.append(user)
            msgs.append(assistant)
        ledger.append(("对话窗口", f"最近 {len(picked)} 轮"))

        msgs.append("当前问题：" + query)
        ledger.append(("当前问题", "永远放最后"))
        return msgs, ledger


OPENING = ["你好，我叫张三，我在筹备下个月的部门团建。",
           "我们一共 24 人，预算 5000 元，日期定在 3 月 15 日。",
           "重要提醒：我对海鲜过敏，餐厅一定要避开海鲜。",
           "另外订单 A1001 的发票麻烦一起处理。",
           "另外我喜欢靠窗的位置，上次坐角落太吵了。"]
NOISE_TOPICS = ["桌游道具", "交通安排", "拍照留念", "签到表", "伴手礼",
                "座位安排", "饮料清单", "背景音乐", "伴手礼包装", "游戏奖品"]
QUERY = "帮我订餐厅，最好能靠窗，别踩雷。"


def make_manager(**kwargs):
    m = MemoryManager(**kwargs)
    for i in range(1, 51):
        text = OPENING[i - 1] if i <= len(OPENING) else \\
            f"第 {i} 轮：再确认一下{NOISE_TOPICS[i % len(NOISE_TOPICS)]}的事，你记一下。"
        m.add_turn(text, "好的，记下了。")
    return m


def report(label, mgr):
    """跑一种开关组合，打印它的 token 用量与"能确认 / 丢掉"的事实。"""
    msgs, ledger = mgr.build(QUERY)
    context = "\\n".join(msgs)
    found = [name for value, name in KEY.items() if value in context]
    missing = [name for value, name in KEY.items() if value not in context]
    used = sum(est(m) for m in msgs)
    flag = "" if not missing else "  <- 有事实丢了"
    print(f"{label:<24}{used:>5} token   丢掉的: {missing if missing else '（无）'}{flag}")
    return missing


CONFIGS = [
    ("完整方案（四层都在）", dict(use_pinning=True, use_recall=True, use_summary=True)),
    ("拆掉钉住（召回还在）", dict(use_pinning=False, use_recall=True, use_summary=True)),
    ("拆掉钉住 + 拆掉召回", dict(use_pinning=False, use_recall=False, use_summary=True)),
    ("拆掉摘要（钉住还在）", dict(use_pinning=True, use_recall=True, use_summary=False)),
]

print("对比表（同一份 50 轮对话，只改开关）：")
print("-" * 78)
for label, cfg in CONFIGS:
    report(label, make_manager(**cfg))
print("-" * 78)
print()
print(f"你当前选中的组合：钉住={USE_PINNING}  召回={USE_RECALL}  摘要={USE_SUMMARY}")
report("（当前组合）", make_manager(use_pinning=USE_PINNING,
                                   use_recall=USE_RECALL,
                                   use_summary=USE_SUMMARY))
print()
print("★ 读表要点：")
print("  · 「姓名」抽得到、钉得住，但摘要不爱留它、召回也够不着它")
print("     -> 一拆钉住就丢；")
print("  · 「座位偏好」重要性只有 0.55，**进不了钉住区**，只能靠长期召回捞回来")
print("     -> 再拆召回，它也丢了；")
print("  · 「团建日期」根本没有抽取规则，只能靠摘要活着 -> 一拆摘要就丢；")
print("  · 三层各自覆盖**不同的失效场景**，这就是纵深防御（defense in depth）。")
print("  · 换你自己的开关组合再跑一次（代码开头那三行），看丢的东西怎么变。")''')

    nb.md("""### 结果说明什么

把上面那张表读成「谁在管哪条信息」：

| 拆掉哪一层 | 丢的事实 | 原因 |
|---|---|---|
| 都不拆 | （无） | 三层各管一段，合起来才完整 |
| 拆掉钉住 | 姓名 | 它抽得到、也够重要，但摘要不爱留它、召回也够不着它 |
| 再拆掉召回 | 姓名 + 座位偏好 | 座位偏好的重要性只有 0.55，本来就进不了钉住区 |
| 拆掉摘要 | 团建日期 | 没有对应的抽取规则，它只活在摘要里 |

三条结论：

1. **每一层覆盖的是不同的失效场景**，不是重复劳动：
   钉住管「够重要、且规则抽得到」的，召回管「重要性不够、但和当前问题相关」的，
   摘要管「剩下的全部」；
2. **拆掉一层往往只丢一两条** —— 所以做优化时很容易产生「这层没用」的错觉。
   要判断一层有没有用，得看它**独有的贡献**（比如召回独有的是座位偏好）；
3. **每一层都要付 token**。正确做法不是"全都拉满"，而是：
   先都装上 → 用真实数据测每层的边际收益 → 再决定哪些可以省。

至此，记忆管理的四个零件和组装顺序都齐了。""")

    # ==================================================================
    section(nb, "⑧", "常见坑汇总")

    pitfall_table(nb, [
        ("按时间淘汰最老的消息", "**按时间淘汰 = 按无关性淘汰**：最早说的往往是最关键的约束",
         "抽事实 + 钉住高价值信息，再压缩其余"),
        ("把全部历史塞进上下文", "超出窗口直接报错；每轮重发全部历史，成本平方级增长",
         "预算表 + 分层压缩"),
        ("钉住区没有上限", "「永不淘汰」的机制变成新的、不可压缩的超支来源",
         "`MAX_PINNED`，按重要性排序"),
        ("摘要每次从头重算", "老信息在反复重算里一点点漂移消失（摘要的摘要）",
         "增量滚动：旧摘要参与下一轮压缩"),
        ("摘要自己不封顶", "摘要无限膨胀，压缩等于白做", "`max_chars` + 超长截断"),
        ("每轮都重压一次摘要", "O(n²) 次模型调用，既贵又慢",
         "触发式压缩（攒够一批）或后台异步压"),
        ("长期记忆不过闸门", "注入无关旧约束 → 模型拿上次的 24 人办这次的 6 人",
         "`min_score` 相关性闸门，宁可不注入"),
        ("把二元组检索当成「语义检索」", "「忌口」召不回「饮食禁忌：海鲜过敏」",
         "向量检索 / 混合检索（第 06 章）"),
        ("关键事实只靠摘要活着", "摘要是有损通道，迟早漏", "双保险：钉住 + 落库"),
        ("规则抽取把提问当陈述", "「我叫什么？」被抽成 `姓名：什么`",
         "只在用户**陈述**上抽；或改用模型抽取 + 校验"),
        ("把关键信息埋在长资料中间", "Lost in the Middle：中间的内容可能被整体忽略",
         "关键信息放头尾，长资料限长 + 编号"),
        ("token 估算当成真值", "差几个 token 就可能在卡窗口的请求上 400",
         "上线用厂商分词器算真实 token"),
        ("长期记忆没有过期/删除", "隐私成本：用户说过的话被永久保存",
         "TTL + 真删除 + 区分 PII"),
    ])

    summary(nb, [
        "**上下文管理的本质是：在有限预算下保留最高价值的信息。**"
        "不是「压缩」，是「按价值取舍」。",
        "**按时间淘汰 = 按无关性淘汰。** 第 1 轮的「海鲜过敏」比第 46 轮的"
        "「桌游道具」重要得多。",
        "**先算账，再压缩。** 每一块花了多少 token、为什么存在，账本必须自洽。",
        "**四件套缺一不可**：滑动窗口（近处原文）+ 摘要（远处梗概）"
        "+ 事实钉住（关键约束）+ 长期存储（跨会话）。",
        "**「永不淘汰」的机制必须自带配额** —— 钉住区没上限就会挤爆窗口。",
        "**摘要要增量滚动**：旧摘要参与下一轮压缩，否则老信息会漂移消失。",
        "**相关性闸门是必需品**：注入无关记忆比不注入更糟（污染比缺失更危险）。",
        "**位置也是信息**：关键信息放头尾，当前问题永远放最后。",
        "**每一层都会付 token**，但每一层也在替你挡事故 —— 拆两层才知道谁在承重。",
    ], "第 06 章要解决一个记忆管不了的问题："
       "记忆记住的是「用户说过的话」，但 Agent 还需要读懂**公司文档库里"
       "没写在提示词里的知识** —— 客户服务手册、产品文档、政策条款。"
       "那是另一个量级的检索问题：**RAG**。"
       "而且 ⑤ 节那个「同义词盲区」，正好是它要正面解决的问题。")

    exercises(nb, [
        ("**给钉住区加优先级抢占。**\n\n"
         "现在 `MAX_PINNED=8`，超出的事实按重要性排序后**丢弃**。"
         "请改成「新事实抢占最低优先级的旧事实」，并打印每一次抢占（谁挤掉了谁）。",
         "改动点在 `build()` 里的 `pinned` 切片处：先按重要性排序，"
         "插入新事实时把最弱的那条挤出去。\n\n"
         "想清楚：被挤掉的事实要不要写进长期存储？"
         "（答案：要 —— 钉住区是「当前上下文的名额」，不是「存储」。）"),

        ("**给摘要加一个「覆盖度自检」。**\n\n"
         "写一个 `summary_covers(summary, facts)`：检查所有钉住的事实是否都能在摘要里找到，"
         "并统计漏检率。目标是**量化摘要的漏检**，而不是假设它不漏。",
         "用字符二元组做重叠度判断即可（复用 ⑤ 节的 `bigrams()`）。\n\n"
         "连续跑 50 轮，统计摘要漏掉了哪几条 —— 你会发现它一直都在漏，"
         "只是漏的那些恰好被钉住区兜住了。"),

        ("**破坏护栏并观察：把钉住变成「什么都钉住」。**\n\n"
         "把 `MAX_PINNED` 改成 `1000`，把阈值改成 `0.0`，然后跑 ③ 和 ⑦ 两格。\n\n"
         "观察两件事：钉住区的 token 涨到多少？对话窗口被挤到只剩几轮？",
         "你会看到对话窗口被挤到 1~2 轮 —— 这就是「永不淘汰的机制必须自带配额」的实证。\n\n"
         "再想一步：如果这时用户问的是「我刚才说的最后一句话是什么」，"
         "Agent 还能答对吗？（窗口里还有东西吗？）"),

        ("**换一种淘汰策略：按「重要性密度」淘汰。**\n\n"
         "现在超窗的消息是**整轮**折进摘要。请改成按「每条消息的价值 / token 数」排序淘汰，"
         "优先保留高密度的消息。",
         "价值可以先用「这条消息里抽出的事实数」近似。\n\n"
         "对比一下：你的新策略和「整轮折叠」相比，同样的预算下多保住了几条事实？"
         "这就是第 10 章「用评测集做优化」的雏形 —— 先有数字，再谈改进。"),

        ("**把规则摘要换成模型摘要。**\n\n"
         "写一个假模型（继承 `core.llm.LLM`，实现 `_complete()`），让它扮演摘要模型，"
         "用 `SUMMARY_PROMPT` 那种提示词。对比两种摘要的 token 数与关键事实保留率。\n\n"
         "然后回答一个工程问题：**摘要调用失败时（返回空 / 超长 / 胡说）怎么办？**",
         "假模型可以用固定字符串拼接，只要保证确定性即可。\n\n"
         "失败处理至少要有三条：空摘要不能覆盖旧摘要、超长要截断、"
         "失败时保留旧摘要并记一条告警 —— **绝不因为摘要失败而丢历史**。"),
    ])

    checkpoint(nb, "05")

    return nb
