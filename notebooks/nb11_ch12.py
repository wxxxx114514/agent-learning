"""第 12 章 · 成本与延迟优化 —— Notebook 内容（逐步推进版）。

遵守 TEACHING_CONTRACT.md：
  · 逐步给：每个知识点在「读者正好需要它」的那一刻出现
    （现在卡在哪 → 所以我需要一个…… → 它的用法 → 立刻用一次 → 结果说明什么）
  · 前置知识表保留在 ⓪，定位是索引（可跳过）
  · 每个代码单元自包含（notebooks/nb_lint.py 机器校验）：
    **绝不 import stages.stage12_cost_latency.demo**，需要什么就在格子里重新定义
  · 中文引号一律用「」，不在字符串里嵌 ASCII 双引号
  · 全章代码不 sleep：延迟全部来自假模型「声明」的模拟耗时 sim_latency_ms，
    所以总执行时间远小于 3 秒，而且结果可复现
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


def build_12() -> Notebook:
    """第 12 章 · 成本与延迟优化（逐步推进版）。"""
    nb = Notebook("第 12 章 · 成本与延迟优化")

    header(
        nb, "12", "成本与延迟优化",
        "优化的顺序是 `先测量 → 再缓存 → 再减量 → 最后才换模型`。\n"
        "**80% 的成本来自「本可以不发生的模型调用」** —— 所以「换个便宜的小模型」"
        "是最差的起手式：它直接牺牲质量，还治不了那些本可以不发生的调用。",
    )

    objectives(nb, [
        "把「贵不贵、慢不慢」变成可计算的数字：token 明细、成本、墙上时间、**TTFT**",
        "说清三个单位陷阱，并用「手算 == 计量器」把价目表钉死",
        "用「精确命中 + 语义命中 + **实体硬约束**」三层缓存，把重复问题变成 0 次模型调用",
        "亲手制造一次**假命中**事故（问 A1002 却答 A1001），并说清实体约束为什么不能省",
        "量化三种减量手段各自的收益：并行工具（sum→max）、上下文裁剪、流式输出",
        "说清路由的兜底为什么必须是**大**模型，以及预算检查为什么必须在调用**之前**",
    ])

    setup_cell(nb)

    nb.md("""---

## 这一章怎么讲

第 11 章结束时，你的 Agent 已经能安全上线了。然后账单来了。

而且大多数团队的第一反应是**错的**：「换个便宜的小模型吧。」——
这一刀直接砍在质量上，而且那些本可以不发生的调用一次都没少。

本章按「收益从大到小、风险从小到大」的顺序拆：

```
① 先看账单：一次任务花了多少钱、等了多少秒   → 不测量，就没有靶子
② 让成本可计算：价目表 + 计量器              → 单位和口径先钉死
③ 缓存第一层：精确命中 + 语义命中            → 重复的问题 0 次调用（不动质量）
④ 缓存第二层：实体硬约束                     → 先看一次假命中事故，再给修复
⑤ 减量：并行 / 裁剪 / 流式                   → 省延迟和输入 token（不动质量）
⑥ 路由：简单给小模型、复杂给大模型           → 第一次动质量，必须保守
⑦ 预算兜底：三维预算 + 调用前检查            → 优化降期望，预算控上界
⑧ before/after：每一步各省了多少             → 说不出省了多少的优化，就撤掉
```

**两个提前说明**（免得你以为是环境问题）：

1. **延迟数字不是真的等出来的。** 假模型的真实耗时接近 0，没法演示延迟优化，
   所以每一个假模型都「声明」一个模拟耗时（`sim_latency_ms`）。
   真实项目里这些数字就是实测 P50，口径完全一样，只是我们让它**可复现**。
2. **本章的五个零件都是现写的**（计量器 / 缓存 / 路由 / 预算 / 并行工具），
   故意没放进 `core/` —— 因为优化的前提是「你知道每个数字是怎么算出来的」。
   每一格都能单独复制出去跑。""")

    nb.md("""---

## ⓪ 本章速查表（初次阅读可跳过，忘了再回来查）

> 这是索引，不是教学部分。正文会在需要的地方就地讲清每个东西。

### 本章用到的标准库

| 名字 | 从哪来 | 干什么 | 关键签名与返回 |
|---|---|---|---|
| `dataclass` | 标准库 `dataclasses` | 快速定义「装数据的小类」 | `@dataclass(frozen=True)` 让实例不可改（价目表就该是常量） |
| `re.compile` | 标准库 `re` | 编译正则 | `re.compile(正则)` → `Pattern` |
| `Pattern.finditer` | 上面返回的对象 | 找出**所有**匹配 | 产出一个 `Match` 流（不是列表，要遍历） |
| `Match.group(0)` | `Match` 对象 | 取整个匹配 | 正则里没有括号时就用它 |
| `str.replace` | 内置 | 子串替换 | `"订单A1001".replace("订单", "")` |
| `math.isclose` | 标准库 `math` | 浮点数比较 | `math.isclose(a, b, rel_tol=1e-9)` |
| `ThreadPoolExecutor` | 标准库 `concurrent.futures` | 开线程池并行干活 | `pool.submit(函数)` → `Future`，`.result()` 取结果 |
| `frozenset` | 内置 | 不可变集合 | 可当字典 key、可比较相等 |
| `issubclass` | 内置 | 判断继承关系 | `issubclass(BudgetExceeded, AbortAgent)` → `True` |

### 本章用到的本项目 `core/` 代码

| 名字 | 导入路径 | 是什么 |
|---|---|---|
| `Agent` | `core.agent` | 框架版 Agent（第 ① 节用它跑一次**真**任务拿基线） |
| `RuleBasedLLM` | `core.mock_llm` | 规则驱动的确定性假模型，会真的发起工具调用 |
| `build_default_registry` | `core.tool` | 框架内置工具集（calc / lookup_order / search_kb …） |
| `estimate_tokens` | `core.llm` | 极简 token 估算（中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token） |
| `LLM` | `core.llm` | 模型抽象基类，子类实现 `_complete()` |
| `AbortAgent` | `core.errors` | **预期内的策略性停机**的基类（预算耗尽属于这一类） |
| `BudgetExceeded` | `core.errors` | 预算耗尽异常，它是 `AbortAgent` 的子类 |

> 本章的五个零件（`Price` / `UsageMeter` / `SemanticCache` / `ModelRouter` / `BudgetGuard`）
> **不在 `core/` 里** —— 它们在下面每一格里现写。真实项目里，它们对应你的
> 「LLM 网关 + 缓存层 + 路由层 + 预算中间件」。

### 随时可查

```python
explain(Agent)              # 构造参数逐个说明 + 返回什么
explain(estimate_tokens)    # 参数含义 + 例子
explain()                   # 列出框架全部公开名字
```""")

    # ==================================================================
    section(nb, "①", "先看账单：一次任务到底花了多少钱、等了多少秒？")

    nb.md("""### 现在卡在哪

「感觉有点慢」「好像有点贵」—— 这不是需求。

真实的优化需求长这样：**「P95 首字延迟 2.2 秒、月成本 ¥663」**。
没有这两个数字，你既不知道从哪下手，也不知道改完到底好了多少。

所以我们第一件事不是优化，是**测量**。

### 所以我需要一个「给每次模型调用记账」的东西

一次调用至少要有四个数字：

| 数字 | 为什么必须有 |
|---|---|
| 输入 token / 输出 token | 它们**单价不同**（输出通常是输入的 3~5 倍） |
| 耗时（latency） | 用户实际等的时间 |
| 首字延迟（TTFT） | 用户**感觉**等的时间（第 ⑤ 节会看到它和耗时不是一回事） |

### 它的用法：在「最靠近模型调用的那一层」套一个适配器

```
   业务代码 ──► MeteredLLM ──► 真模型
                    │
                    └─ 顺手记一条账：tier / token / 耗时 / 成本
```

**为什么不让业务代码「顺手记一下」？** 因为业务代码一定会漏 ——
而这一层是所有调用的必经之路。生产里它就是你自己的 LLM 网关。

下面这一格用**真 Agent + 真工具集**跑一次任务（只有模型是离线假模型），
口径和线上完全一致。""")

    nb.code('''# 单独可运行：给「真 Agent」套一层计量，看清一次任务的钱和时间花在哪
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass
from core.agent import Agent
from core.llm import LLM, estimate_tokens
from core.mock_llm import RuleBasedLLM
from core.tool import build_default_registry


# ---- 零件 1：价目表。为什么第一件事是它？因为「贵不贵」必须可计算 ----
@dataclass(frozen=True)          # frozen=True：价目表是常量，跑起来之后谁也不许改它
class Price:
    """一个模型的价目表 + 性能画像（单位：元 / 1K token、毫秒）。"""

    name: str
    prompt_per_1k: float         # 输入单价：每圈都要重发整段历史，所以这一项最要命
    completion_per_1k: float     # 输出单价：通常是输入的 3~5 倍，啰嗦的回答更贵
    sim_latency_ms: float        # 模拟总耗时（真实项目里换成实测的 P50）
    sim_ttft_ms: float           # 模拟首字延迟（只有流式输出才用得上）

    def cost(self, prompt_tokens, completion_tokens):
        """整个课程里唯一的成本公式：输入、输出分开计价，再相加。"""
        return (prompt_tokens / 1000 * self.prompt_per_1k
                + completion_tokens / 1000 * self.completion_per_1k)


# 两个档位：大模型强/贵/慢，小模型弱/便宜 10 倍/快 3 倍
PRICING = {
    "large": Price("large-pro", 0.012, 0.036, 2200, 700),
    "small": Price("small-flash", 0.001, 0.002, 600, 180),
}


# ---- 零件 2：一条账目。排查账单时，你唯一能看的就是它 ----
@dataclass
class CallRecord:
    index: int                   # 第几次调用（从 1 开始）
    tier: str                    # 走的哪个档位：large / small
    model: str                   # 具体模型名
    prompt_tokens: int           # 这次发过去多少 token
    completion_tokens: int       # 这次生成多少 token
    latency_ms: float            # 总耗时
    ttft_ms: float               # 首字延迟
    cost: float                  # 按档位单价算出来的钱


class UsageMeter:
    """用量计量器：把「花了多少钱」从感觉变成可查询的数字。"""

    def __init__(self, pricing=None):
        # pricing 是「可注入」的：测试时可以塞一张假价目表，不影响真账
        self.pricing = pricing if pricing is not None else PRICING
        self.calls = []          # list[CallRecord]，按发生顺序追加

    def record_call(self, tier, prompt_tokens, completion_tokens,
                    latency_ms, ttft_ms, model=""):
        """记一次调用。

        参数 tier：档位（决定单价）—— 后面「路由省了多少钱」就是从这里算出来的
        返回    ：刚记下的那条 CallRecord
        """
        price = self.pricing[tier]
        rec = CallRecord(len(self.calls) + 1, tier, model or price.name,
                         prompt_tokens, completion_tokens, latency_ms, ttft_ms,
                         price.cost(prompt_tokens, completion_tokens))
        self.calls.append(rec)
        return rec

    @property
    def model_calls(self):
        return len(self.calls)

    @property
    def prompt_tokens(self):
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self):
        return sum(c.completion_tokens for c in self.calls)

    @property
    def cost(self):
        return sum(c.cost for c in self.calls)


# ---- 零件 3：把「计量」和「模型」解耦的适配器 ----
class MeteredLLM(LLM):
    """给任意模型套一层计量。它自己不算任何东西，只负责转发 + 记账。"""

    def __init__(self, inner, tier, meter):
        super().__init__("metered(%s)" % inner.model)   # 模型名带上来源，便于对账
        self.inner, self.tier, self.meter = inner, tier, meter

    def _complete(self, messages, **kwargs):
        resp = self.inner.complete(messages, **kwargs)  # 先真的去问模型
        price = self.meter.pricing[self.tier]
        # ★ 假模型的真实耗时接近 0，没法演示延迟优化 ——
        #   所以让它「声明」自己花了多久（真实项目里直接用实测值）
        latency = float(resp.raw.get("sim_latency_ms") or price.sim_latency_ms)
        self.meter.record_call(
            tier=self.tier,
            # resp 没给 token 数就自己估一个：估算器统一用 core.llm.estimate_tokens
            prompt_tokens=resp.prompt_tokens or estimate_tokens(
                "".join(m.to_text() for m in messages)),
            completion_tokens=resp.completion_tokens or estimate_tokens(resp.text),
            latency_ms=latency, ttft_ms=price.sim_ttft_ms, model=self.inner.model)
        return resp


# ---- 跑一次真任务（只有模型是假模型，计量口径与线上一致）----
meter = UsageMeter()
agent = Agent(llm=MeteredLLM(RuleBasedLLM(), "large", meter),
              tools=build_default_registry(workspace=ROOT),   # 真工具集
              max_steps=6, verbose=False)                     # 静音，只留我们自己打印
result = agent.run("计算 (12+8)*3/4，然后查一下订单 A1001 到哪了")

print("  #  档位   模型       输入  输出    耗时     TTFT        成本")
for c in meter.calls:
    print("  %-3d %-6s %-10s %5d %5d %6.0fms %6.0fms  ¥%.5f" %
          (c.index, c.tier, c.model, c.prompt_tokens, c.completion_tokens,
           c.latency_ms, c.ttft_ms, c.cost))
print()
print("答案             :", result.answer[:40])
print("LLM 调用次数     :", meter.model_calls)
print("输入 / 输出 token:", meter.prompt_tokens, "/", meter.completion_tokens)
print("本次成本         : ¥%.5f" % meter.cost)
print()
print("★ 输入 token 逐次累加：%d -> %d（每调一次都要把整段历史重发一遍）"
      % (meter.calls[0].prompt_tokens, meter.calls[-1].prompt_tokens))
print("  这就是「上下文越长越贵」的根源 —— 第 05 章的上下文管理，直接决定这里的账单。")
print()
print("每天 1000 次任务 : ¥%.2f/天 ≈ ¥%.2f/月"
      % (meter.cost * 1000, meter.cost * 1000 * 30))
print("★ 在测量之前，你连这几分钱花在哪一步都不知道 —— 更别说优化了。")''')

    nb.md("""### 结果说明什么

两个立刻能看出来、而且后面每一节都要用的事实：

1. **输入 token 是逐次累加的**（778 → 828）：每调一次模型，整段历史都要重发一遍。
   所以「省一次调用」永远比「省一点 token」值钱。
2. **成本是可以算出来的**：有单价和 token 数，「贵不贵」就不再是感觉。
   一次任务 ¥0.022 听着不多，乘上量级就是决策问题：每天 1000 次就是 ¥663/月。

于是优化有了靶子。但等一下 —— 上面那个成本和手算对得上吗？
**计量器本身也可能是错的**，而线上的价目表改错了是不会有任何报错的。
这就是下一节要钉死的东西。""")

    # ==================================================================
    section(nb, "②", "让成本可计算：价目表 + 计量器")

    nb.md("""### 现在卡在哪

第 ① 节那张表里 `¥0.01106` 是怎么来的？如果我们算错了，
后面所有的「省了 73%」都是假的 —— 而且**不会有任何报错**。

### 所以我需要一个「能被人手验证」的成本公式

```
成本 = 输入 token / 1000 × 输入单价  +  输出 token / 1000 × 输出单价
```

### 三个必须记住的单位陷阱

| 陷阱 | 后果 | 纪律 |
|---|---|---|
| 各家报价都是「每 **100 万** token」，内部换算成「每 1K」要 ÷1000 | 差 **1000 倍**（少乘 / 多乘一个零） | 内部统一用「元 / 1K token」，并写一条手算校验的断言 |
| 输入和输出**不同价**（输出常是输入的 3~5 倍） | 用平均价算，长回答全算错 | 分开记 `prompt_tokens` / `completion_tokens` |
| 缓存命中、批处理、夜间折扣是**不同档位** | 一个单价表达不了 | 价目表做成 `tier -> Price` 的字典 |

### 它给我什么

一个 `UsageMeter`：`record_call(...)` 记账，`.cost` / `.prompt_tokens` / `.by_tier()` 汇总。
另外还有一个**容易写错**的地方：缓存命中省下来的钱，要按「被替代的那次调用」计价，
不能按 0 计 —— 否则你永远算不出缓存值多少钱。

### 立刻用一次：记账 + 手算对照""")

    nb.code('''# 单独可运行：价目表 + 计量器 + 手算校验 + 省下的钱怎么算
import sys, pathlib, math
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass
from core.llm import estimate_tokens


@dataclass(frozen=True)
class Price:
    """价目表：单位统一成「元 / 1K token」，毫秒。"""

    name: str
    prompt_per_1k: float         # 输入单价
    completion_per_1k: float     # 输出单价
    sim_latency_ms: float        # 模拟总耗时
    sim_ttft_ms: float           # 模拟首字延迟

    def cost(self, prompt_tokens, completion_tokens):
        # ★ 这一行就是全章所有金额的唯一来源：把它写对，比优化重要得多
        return (prompt_tokens / 1000 * self.prompt_per_1k
                + completion_tokens / 1000 * self.completion_per_1k)


PRICING = {
    "large": Price("large-pro", 0.012, 0.036, 2200, 700),
    "small": Price("small-flash", 0.001, 0.002, 600, 180),
}


@dataclass
class CallRecord:
    """一条账目。字段全是「事后排查账单」时必须能看到的。"""

    index: int
    tier: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cost: float

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens


class UsageMeter:
    """用量计量器：本章所有优化效果的裁判。"""

    def __init__(self, pricing=None):
        self.pricing = pricing if pricing is not None else PRICING
        self.calls = []
        self.cache_hits = 0          # 命中次数：成本与延迟同时受益的证据
        self.cache_saved = 0.0       # 缓存「省下的钱」，不是「花了 0 元」

    def record_call(self, tier, prompt_tokens, completion_tokens, latency_ms):
        """记一次真实调用。"""
        price = self.pricing[tier]
        rec = CallRecord(len(self.calls) + 1, tier, price.name,
                         prompt_tokens, completion_tokens, latency_ms,
                         price.cost(prompt_tokens, completion_tokens))
        self.calls.append(rec)
        return rec

    def record_cache_hit(self, saved_tier, prompt_tokens, completion_tokens):
        """缓存命中：省下的钱要按**被替代的那次调用**计价，不能按 0 计。

        参数 saved_tier：如果没命中缓存，这次调用本来会走哪个档位
        返回          ：省下的金额
        """
        self.cache_hits += 1
        saved = self.pricing[saved_tier].cost(prompt_tokens, completion_tokens)
        self.cache_saved += saved
        return saved

    @property
    def model_calls(self):
        return len(self.calls)

    @property
    def prompt_tokens(self):
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self):
        return sum(c.completion_tokens for c in self.calls)

    @property
    def cost(self):
        return sum(c.cost for c in self.calls)

    def by_tier(self):
        """按档位统计调用次数 —— 一眼看出「钱主要花在哪个模型上」。"""
        out = {}
        for c in self.calls:
            out[c.tier] = out.get(c.tier, 0) + 1
        return out


def money(x):
    """金额格式化：大额少几位小数，小额多几位 —— 教学输出要一眼能看出量级。"""
    return "¥%.2f" % x if abs(x) >= 1 else "¥%.5f" % x


print("价目表（内部统一用「元 / 1K token」）：")
for tier, p in PRICING.items():
    print("   %-6s %-12s 输入 %.4f  输出 %.4f  模拟耗时 %.0fms  模拟TTFT %.0fms"
          % (tier, p.name, p.prompt_per_1k, p.completion_per_1k,
             p.sim_latency_ms, p.sim_ttft_ms))
print()

meter = UsageMeter()
meter.record_call("large", 1200, 300, 2200)     # 第 1 次：大模型首答
meter.record_call("large", 1800, 400, 2400)     # 第 2 次：历史更长，输入 token 涨了
meter.record_call("small", 800, 150, 600)       # 第 3 次：路由到小模型，便宜 10 倍
for c in meter.calls:
    print("   #%d %-6s 输入 %5d 输出 %5d 耗时 %5.0fms 成本 %s"
          % (c.index, c.tier, c.prompt_tokens, c.completion_tokens,
             c.latency_ms, money(c.cost)))
print()
print("总 token     :", meter.prompt_tokens + meter.completion_tokens,
      "（输入 %d / 输出 %d）" % (meter.prompt_tokens, meter.completion_tokens))
print("总成本       :", money(meter.cost))
print("按档位分布   :", meter.by_tier())
print()

# ---- 校验 1：手算必须与计量器一致（这条断言值得抄进你的项目）----
manual = 1200 / 1000 * 0.012 + 300 / 1000 * 0.036
print("手算第 1 条  : 1200/1000×0.012 + 300/1000×0.036 = %.5f" % manual)
print("计量器第 1 条: %.5f" % meter.calls[0].cost)
print("一致？       :", math.isclose(manual, meter.calls[0].cost, rel_tol=1e-9))
print()

# ---- 校验 2：少除一个 1000 会怎样（真实事故：账单差 1000 倍）----
correct_input = 1200 / 1000 * 0.012     # 正确：1200 token × 「每 1K」的单价
wrong = 1200 * 0.012                    # 错误：把「每 1K」当成了「每 1 token」
print("★ 单位陷阱：同样 1200 个输入 token，正确 %.5f 元，算错 %.2f 元"
      % (correct_input, wrong))
print("  相差 %.0f 倍 —— 而这种错在线上是**不会报错**的，只会悄悄多扣钱。"
      % (wrong / correct_input))
print()

# ---- 校验 3：缓存省下的钱，按被替代的调用计价 ----
saved = meter.record_cache_hit("large", 1200, 120)
print("缓存命中 1 次，省下 :", money(saved),
      "（按 large 档位计价，不是 0 元）")
print("缓存累计省下        :", money(meter.cache_saved))
print()

# ---- 顺便看一眼 token 是怎么估出来的 ----
sample = "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。"
print("estimate_tokens(%s...)" % sample[:10], "=", estimate_tokens(sample),
      "（中文 1 字 ≈ 1 token，英文 4 字符 ≈ 1 token）")
print()
print("★ 一句话：**计量必须可验证**。价目表改错了不会报错，只会悄悄多扣钱。")
print("★ 另一句话：记账要发生在最靠近模型调用的那一层（网关），不要散在业务代码里。")''')

    nb.md("""### 结果说明什么

- 手算与计量器**完全一致** —— 这就是「计量器必须可验证」的意义。
  真实项目里把它写成一条断言，价目表改错时立刻变红。
- `少除一个 1000` 让成本差 1000 倍：**账单类 bug 不会报错，只会悄悄多扣钱**。
- 缓存省下的钱必须按「被替代的那次调用」计价，否则你永远算不出缓存的价值。

现在成本可计算了。接下来按顺序做优化 —— 第一件、也是最划算的一件：**缓存**。""")

    # ==================================================================
    section(nb, "③", "缓存第一层：第二次问同一个问题，0 次模型调用")

    nb.md("""### 现在卡在哪

真实流量的重复率高得惊人（客服场景常常 **30%~60%**），而这些重复问题
每一次都在**重新付一遍完整的钱**（整段上下文 + 输出）。

### 所以我需要一个「问过的问题就别再问一遍」的东西

难点在于：用户**不会用同一句话**问同一个问题。

```
订单 A1001 到哪了？
订单 A1001 到哪里了？
帮我查一下订单 A1001 到哪里了
```

三句话的字符串完全不一样，但它们是同一个问题。所以缓存要走两道门：

```
新问题 ──► 归一化 key ──完全相同？──是──► ① 精确命中（最安全，0 风险）
              │ 否
              ▼
        相似度 ≥ 阈值？ ──否──► 未命中（老老实实调模型）
              │ 是
              ▼
        实体集合一致？ ──否──► 拒绝命中（第 ④ 节的主角）
              │ 是
              ▼
           ② 语义命中
```

### 它的用法

| 零件 | 干什么 | 关键点 |
|---|---|---|
| `_norm(text)` | 归一化：去标点、去礼貌词、去空白 | 它每改一次，命中率就变一次，是线上最容易被改坏的代码 |
| `bigrams(text)` | 把文本切成**字符二元组**集合 | 中文不需要分词，二元组就够表达「哪些字连在一起出现过」 |
| `similarity(a, b)` | Dice 相似度 `2|A∩B| / (|A|+|B|)` | 取值 0~1；不引入 embedding，可解释、可复现 |
| `SemanticCache.get(问题)` | 查缓存 | 返回 `CacheLookup`：`.hit` / `.kind` / `.score` / `.reason` |
| `SemanticCache.put(...)` | 花完钱立刻写进去 | 真实项目里要带 TTL，写操作后还要主动失效 |

### 立刻用一次""")

    nb.code('''# 单独可运行：精确命中 + 语义命中 —— 第二次问同一个问题，0 次模型调用
import re
from dataclasses import dataclass

# ← 试着改这里：把阈值降到 0.5，看还有哪些本来不该命中的问题「被判成同一个问题」
THRESHOLD = 0.72
ENTITY_GUARD = True      # ← 试着改这里：改成 False，第 ④ 节会看到假命中事故


# ---- 归一化：把「看起来不同、其实是同一个问题」的说法合并成同一个 key ----
# ★ 为什么用「字符集合 + str.replace」而不是正则？
#   因为这一层的规则你必须能一眼看懂 —— 它每改一次，缓存命中率就变一次。
PUNCT = "，。！？、；：,.!?;:~'\\"“”‘’()（）[]【】"      # 要丢掉的标点
POLITE = ("帮我", "请", "麻烦", "一下", "一下子", "谢谢", "好吗",
          "可以", "能不能", "我想", "我要")                  # 要丢掉的礼貌词


def _norm(text):
    """归一化：用户原话 → 缓存 key。

    参数 text：用户原话，例如 帮我查一下订单 A1001 到哪里了
    返回    ：归一化后的字符串，例如 查订单a1001到哪里了
    """
    t = (text or "").strip().lower()                     # 首尾空白与大小写不算差异
    t = "".join(ch for ch in t if ch not in PUNCT)       # 去标点
    for word in POLITE:                                  # 去礼貌词：它们不改变意图
        t = t.replace(word, "")
    return "".join(ch for ch in t if not ch.isspace())   # 去所有空白


# ---- 实体抽取：这些词「必须完全一致」才允许命中 ----
ENTITY_RE = re.compile(r"[A-Za-z]{0,2}\\d{2,}")          # 订单号/编号：最多 2 个字母 + 至少 2 位数字
NUMBER_RE = re.compile(r"\\d+(?:\\.\\d+)?")               # 金额/日期/数量：任何数字


def entities_of(text):
    """抽出「必须完全一致才算同一件事」的实体。

    订单号、金额、日期、数量、版本号…… 任何数字/编号都属于这一类。
    宁可多抽一些、宁可命中率低一点，也不能让 A 的答案落到问 B 的头上。

    参数 text：用户原话
    返回    ：frozenset，例如 订单 A1001 到哪了？ → {'1001', 'A1001'}
    """
    found = {m.group(0).upper() for m in ENTITY_RE.finditer(text)}   # finditer：所有匹配
    found |= {m.group(0) for m in NUMBER_RE.finditer(text)}          # |= 是集合并集
    return frozenset(found)


# ---- 相似度：字符二元组 + Dice 系数 ----
def bigrams(text):
    """字符二元组集合：text 每个相邻两字组成一个元素。

    为什么不用 embedding？本章要零依赖、可解释、可复现。
    生产里可以换成 embedding + 向量库，但下面那层「实体硬约束」不能省。
    """
    t = _norm(text)
    if len(t) < 2:
        return {t} if t else set()          # 单字问题也要能参与比较
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a, b):
    """Dice 相似度 = 2|A∩B| / (|A|+|B|)，取值 0~1。

    参数 a, b：两段文本（内部会先归一化）
    返回     ：浮点数；完全无关是 0，完全一样是 1
    """
    ga, gb = bigrams(a), bigrams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))


# ---- 缓存本体 ----
@dataclass
class CacheEntry:
    """一条缓存记录。"""

    key: str                      # 归一化后的 key（精确命中靠它）
    question: str                 # 原话（相似度比较、排查问题靠它）
    entities: frozenset           # 实体集合（防假命中靠它）
    answer: str                   # 上次的答案
    tier: str                     # 上次走的是哪个档位（算「省下多少钱」要用）
    prompt_tokens: int            # 上次花了多少输入 token
    completion_tokens: int        # 上次花了多少输出 token
    hits: int = 0                 # 被命中过几次


@dataclass
class CacheLookup:
    """一次缓存查询的结果（带解释，方便调试和观察）。"""

    hit: bool                     # 是否允许命中
    kind: str = ""                # exact / semantic / miss / entity_blocked
    entry: CacheEntry = None      # 命中的是哪条
    score: float = 0.0            # 最高相似度
    reason: str = ""              # 人话解释 —— 上线后排查就靠它


class SemanticCache:
    """精确 + 语义 + 实体硬约束的混合缓存（零依赖实现）。"""

    def __init__(self, threshold=0.72, entity_guard=True):
        self.threshold = threshold        # 相似度阈值（要用真实流量调，不能拍脑袋）
        self.entity_guard = entity_guard  # 实体硬约束开关（生产里永远是 True）
        self.entries = []
        self.stats = {"exact_hit": 0, "semantic_hit": 0, "miss": 0,
                      "entity_blocked": 0, "put": 0}

    def get(self, question):
        """查缓存。返回 CacheLookup（**不抛异常**：缓存永远不该搞崩主流程）。"""
        key = _norm(question)
        ents = entities_of(question)

        # ① 精确命中：归一化后完全一致 —— 最安全的一层，零风险
        for e in self.entries:
            if e.key == key:
                e.hits += 1
                self.stats["exact_hit"] += 1
                return CacheLookup(True, "exact", e, 1.0, "归一化后完全一致")

        # ② 语义命中：先找最像的那条，再判断「够不够像」和「是不是同一个对象」
        best_score, best_entry = 0.0, None
        for e in self.entries:
            score = similarity(question, e.question)
            if score > best_score:
                best_score, best_entry = score, e

        if best_entry is not None and best_score >= self.threshold:
            # ★★ 实体硬约束：相似度说「是同一个问题」，实体说「不是同一个对象」→ 拒绝
            if self.entity_guard and best_entry.entities != ents:
                self.stats["entity_blocked"] += 1
                return CacheLookup(
                    False, "entity_blocked", best_entry, best_score,
                    "相似度 %.2f 达标，但实体不同 %s ≠ %s → 拒绝命中"
                    % (best_score, sorted(best_entry.entities), sorted(ents)))
            best_entry.hits += 1
            self.stats["semantic_hit"] += 1
            return CacheLookup(True, "semantic", best_entry, best_score,
                               "相似度 %.2f" % best_score)

        self.stats["miss"] += 1
        return CacheLookup(False, "miss", None, best_score,
                           "最高相似度 %.2f" % best_score)

    def put(self, question, answer, tier, prompt_tokens=0, completion_tokens=0):
        """花完钱立刻把答案写进缓存。

        ★ 生产里的 key 绝不只是问题本身，必须带上：
          用户/租户 ID（**绝不能跨用户共享缓存！**）、权限级别、工具集版本、
          模型版本、知识库版本、语言。少一个就是数据泄露或答非所问。
        """
        entry = CacheEntry(_norm(question), question, entities_of(question), answer,
                           tier, prompt_tokens, completion_tokens)
        self.entries.append(entry)
        self.stats["put"] += 1
        return entry

    @property
    def hit_rate(self):
        """命中率：成本、延迟、用户体验三者共同的一等指标。"""
        total = self.stats["exact_hit"] + self.stats["semantic_hit"] + self.stats["miss"]
        if not total:
            return 0.0
        return (self.stats["exact_hit"] + self.stats["semantic_hit"]) / total


# ---- 缓存能省多少钱？按被替代的那次调用计价 ----
PRICES = {"large": (0.012, 0.036), "small": (0.001, 0.002)}


def call_cost(tier, prompt_tokens, completion_tokens):
    """一次调用要花多少钱（这里是 ② 的 Price.cost 的等价简化版）。"""
    pp, cp = PRICES[tier]
    return prompt_tokens / 1000 * pp + completion_tokens / 1000 * cp


cache = SemanticCache(threshold=THRESHOLD, entity_guard=ENTITY_GUARD)

Q1 = "订单 A1001 到哪了？"
ANSWER1 = "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。"
PT, CT = 1200, 40                       # 上次那次调用的 token 账

print("第 1 次提问 :", Q1)
print("   结果    : 未命中 → 调用大模型 1 次，花掉 ¥%.5f" % call_cost("large", PT, CT))
cache.put(Q1, ANSWER1, "large", PT, CT)     # ← 花完钱立刻写缓存，这一步最容易被忘
print()

saved_total = 0.0
for i, q in enumerate([Q1, "帮我查一下订单 A1001 到哪里了"], start=2):
    look = cache.get(q)                     # 查缓存（不会花钱）
    print("第 %d 次提问 : %s" % (i, q))
    print("   相似度  : %.3f" % look.score)
    if look.hit:
        saved_total += call_cost(look.entry.tier, look.entry.prompt_tokens,
                                 look.entry.completion_tokens)
        print("   结果    : %s 命中（%s）→ **0 次模型调用**" % (look.kind, look.reason))
    else:
        print("   结果    : %s（%s）→ 仍然要调模型" % (look.kind, look.reason))
    print()

print("归一化后的 key：", [_norm(q) for q in (Q1, "帮我查一下订单 A1001 到哪里了")])
print("缓存统计       :", cache.stats)
print("命中率         : %.0f%%" % (cache.hit_rate * 100))
print("这两次命中省下 : ¥%.5f" % saved_total)
print()
print("★ 缓存是投入产出比最高的优化：它不牺牲任何质量（命中的就是上次那个答案），")
print("  同时降成本、降延迟。真实流量里重复/近似重复常常占 30%~60%。")
print("★ 但它有一个致命失败模式 —— 下一节就用一对只差一个字符的订单号演示。")''')

    nb.md("""### 结果说明什么

- 第 2 次是 `exact` 命中（归一化后完全一致），第 3 次是 `semantic` 命中（相似度 0.80），
  **两次都是 0 次模型调用** —— 这就是「本可以不发生的调用」被消灭的样子。
- 注意 `_norm` 的作用：三句看起来完全不同的话，归一化之后前两句的 key 完全一样。
- `entity_blocked` 这个统计项现在还是 0，但它是本缓存**最重要的一个计数器**。

为什么？因为语义缓存有一个不会报错的失败模式。下面这一节就是它的现场。""")

    # ==================================================================
    section(nb, "④", "缓存第二层：一次假命中事故（先看失败，再给修复）")

    nb.md("""### 现在卡在哪

用户问：「订单 **A1002** 到哪了？」

缓存里存着订单 **A1001** 的答案。这两句话在字符层面**只差一个字符**：

```
订单 A1001 到哪了？
订单 A1002 到哪了？
        ↑ 只差这一个字符
```

相似度高达 **0.78**，早就超过了阈值 0.72 —— 相似度认为「这是同一个问题」。

### 失败长什么样

如果缓存只看相似度（把实体约束关掉），系统会这样回答：

```
用户问：订单 A1002 到哪了？
系统答：订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。
```

**这就是假命中。** 它不报错、不变慢，格式正确、语气正常，
演示环境里完全看不出来 —— 上线就是「把 A 的信息发给问 B 的客户」的数据事故。

### 所以我需要一个「对象级」的判断

相似度只能回答「**是不是同一个问题**」，它回答不了「**是不是同一个对象**」。

**订单号、金额、日期、数量、版本号 —— 这些词必须完全一致，才允许命中。**

### 立刻用一次：先复现事故，再打开修复""")

    nb.code('''# 单独可运行：语义缓存的假命中 —— 先看事故，再打开实体硬约束修复它
import re
from dataclasses import dataclass

# 下面这段归一化/相似度/实体抽取，与上一格完全一致（每格都要能单独复制出去跑）
PUNCT = "，。！？、；：,.!?;:~'\\"“”‘’()（）[]【】"
POLITE = ("帮我", "请", "麻烦", "一下", "一下子", "谢谢", "好吗",
          "可以", "能不能", "我想", "我要")


def _norm(text):
    """归一化：去标点、去礼貌词、去空白。参数 text 是用户原话，返回 key。"""
    t = (text or "").strip().lower()
    t = "".join(ch for ch in t if ch not in PUNCT)
    for word in POLITE:
        t = t.replace(word, "")
    return "".join(ch for ch in t if not ch.isspace())


ENTITY_RE = re.compile(r"[A-Za-z]{0,2}\\d{2,}")
NUMBER_RE = re.compile(r"\\d+(?:\\.\\d+)?")


def entities_of(text):
    """抽出必须完全一致才算同一件事的实体，返回 frozenset。"""
    found = {m.group(0).upper() for m in ENTITY_RE.finditer(text)}
    found |= {m.group(0) for m in NUMBER_RE.finditer(text)}
    return frozenset(found)


def bigrams(text):
    """字符二元组集合（中文不需要分词）。"""
    t = _norm(text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a, b):
    """Dice 相似度 = 2|A∩B| / (|A|+|B|)，返回 0~1。"""
    ga, gb = bigrams(a), bigrams(b)
    return 2 * len(ga & gb) / (len(ga) + len(gb)) if ga and gb else 0.0


@dataclass
class CacheEntry:
    key: str
    question: str
    entities: frozenset
    answer: str
    tier: str
    hits: int = 0


@dataclass
class CacheLookup:
    hit: bool
    kind: str = ""
    entry: CacheEntry = None
    score: float = 0.0
    reason: str = ""


class SemanticCache:
    """只保留本节需要的三个能力：精确命中 / 语义命中 / 实体闸门。"""

    def __init__(self, threshold=0.72, entity_guard=True):
        self.threshold = threshold
        self.entity_guard = entity_guard      # ★ 这就是本节的唯一开关
        self.entries = []
        self.stats = {"exact_hit": 0, "semantic_hit": 0, "miss": 0, "entity_blocked": 0}

    def get(self, question):
        """查缓存，返回一个带解释的 CacheLookup。"""
        key, ents = _norm(question), entities_of(question)
        for e in self.entries:                       # ① 精确命中优先
            if e.key == key:
                self.stats["exact_hit"] += 1
                return CacheLookup(True, "exact", e, 1.0, "归一化后完全一致")

        best_score, best_entry = 0.0, None           # ② 找最像的那条
        for e in self.entries:
            s = similarity(question, e.question)
            if s > best_score:
                best_score, best_entry = s, e

        if best_entry is not None and best_score >= self.threshold:
            if self.entity_guard and best_entry.entities != ents:
                self.stats["entity_blocked"] += 1
                return CacheLookup(False, "entity_blocked", best_entry, best_score,
                                   "相似度 %.2f 达标，但实体不同 %s ≠ %s → 拒绝命中"
                                   % (best_score, sorted(best_entry.entities), sorted(ents)))
            self.stats["semantic_hit"] += 1
            return CacheLookup(True, "semantic", best_entry, best_score,
                               "相似度 %.2f" % best_score)

        self.stats["miss"] += 1
        return CacheLookup(False, "miss", None, best_score, "最高相似度 %.2f" % best_score)

    def put(self, question, answer, tier="large"):
        """把一条答案写进缓存。"""
        e = CacheEntry(_norm(question), question, entities_of(question), answer, tier)
        self.entries.append(e)
        return e


# ================= 现场：一次假命中事故 =================
Q_ASKED = "订单 A1001 到哪了？"          # 缓存里已经有它
A_ASKED = "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890。"
Q_NEW = "订单 A1002 到哪了？"            # ← 用户真正问的（另一个订单！）

print("① 两道闸门各自的判断：")
print("   相似度        : %.3f（阈值 %.2f → 相似度认为「是同一个问题」）"
      % (similarity(Q_NEW, Q_ASKED), 0.72))
print("   实体（订单号）: %s  vs  %s  ← 完全不同"
      % (sorted(entities_of(Q_ASKED)), sorted(entities_of(Q_NEW))))
print()

print("② 把实体约束关掉，只按相似度命中 —— 事故现场：")
naive = SemanticCache(threshold=0.72, entity_guard=False)     # ← 故意拆掉护栏
naive.put(Q_ASKED, A_ASKED)
bad = naive.get(Q_NEW)
print("   用户问        :", Q_NEW)
print("   系统答        :", bad.entry.answer if bad.entry else "")
print("   相似度        : %.3f  → kind = %s" % (bad.score, bad.kind))
print("   ↑ 不报错、不变慢、格式正确 —— 只是**把 A 的信息答给了问 B 的用户**。")
print()

print("③ 打开实体约束（生产里永远是 True）—— 同一个问题，拒绝命中：")
safe = SemanticCache(threshold=0.72, entity_guard=True)
safe.put(Q_ASKED, A_ASKED)
good = safe.get(Q_NEW)
print("   用户问        :", Q_NEW)
print("   结果          : %s" % good.kind)
print("   理由          : %s" % good.reason)
print("   → 拒绝命中的代价只是「多花一次模型调用的钱」；")
print("     而假命中的代价是「答错对象」——这两者根本不是一个量级。")
print()

print("④ 边界：完全不同的订单号呢？")
far = safe.get("订单 B2043 到哪了？")
print("   相似度        : %.3f（连阈值都够不着 → %s）" % (far.score, far.kind))
print()
print("★ 两道闸门是**互补**的：相似度防「不相干」，实体约束防「差一点」。")
print("★ 经验法则：相似度决定「是不是同一个问题」，实体决定「是不是同一个对象」，")
print("  两者必须同时满足才允许命中。宁可命中率低一点，也不能答错对象。")
print("★ 统计里的 entity_blocked 就是「实体闸门替你挡下了几次事故」，它必须被监控。")''')

    nb.md("""### 结果说明什么

| 配置 | 问「订单 A1002 到哪了？」的结果 |
|---|---|
| `entity_guard=False`（只看相似度） | **假命中** —— 答了 A1001 的信息 ❌ |
| `entity_guard=True`（默认） | `entity_blocked` —— 拒绝命中，老老实实调模型 ✅ |

两条必须记住的工程纪律：

1. **假命中率必须为 0，命中率低没关系。** 因为还有 100% 安全的精确命中兜着。
   真实项目里用 **shadow mode**（只记日志不生效）先观察 200 组「被判定为相似」的样本，
   人工确认没有假命中，再打开阈值。
2. **阈值要用真实流量调，不能拍脑袋。** 而且 `_norm()` 改一次就要重新看一遍 ——
   这两个都是事故级信号。

> 还有一种「完全不同的订单号」（如 `B2043`）相似度只有 0.33，连阈值都够不着。
> 所以**不能只靠实体约束**：相似度阈值和实体闸门缺一不可。

缓存的账算完了。接下来省**延迟**和**输入 token**。""")

    # ==================================================================
    section(nb, "⑤", "减量：并行工具、上下文裁剪、流式输出")

    nb.md("""### 现在卡在哪

账单一共两块：**成本**和**延迟**。缓存把「重复问题」的那部分消掉了，
但剩下的调用依然又贵又慢。三个具体毛病：

| 毛病 | 现象 | 该减什么 |
|---|---|---|
| 两个不相干的工具被串着跑 | 700ms（300 + 400） | **延迟** |
| 每圈都把整段历史重发一遍 | 输入 token 随轮数线性涨 | **成本** |
| 用户对着空白屏幕等 2.2 秒 | 感受上「很慢」 | **首字延迟 TTFT** |

### 所以我需要三个不同的手段

**① 并行工具调用。** 能不能并行的判据只有一句：

```
B 的参数里有没有用到 A 的返回值？    没有 → 可以并行
```

串行 N 个工具的总耗时是 `sum`，并行是 `max` —— 2 个工具就从 700ms 变成 400ms。

**② 上下文裁剪。** 第 05 章讲过滑动窗口 / 摘要压缩，在这里它变成了钱：
输入 token 少了，每一次调用的账单就少了。裁剪的本质不是「删最老的」，
而是**在有限预算下保留最高价值的信息**。

**③ 流式输出。** 它**不省一分钱、总时长也不变**，但它把
「对着空白屏幕等 2.2 秒」变成「0.7 秒后开始持续出字」——

```
非流式：  |-------------------- 2200ms --------------------|  全部内容一次性出现
流式  ：  |-- 700ms --|▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏▏|  TTFT 700ms
                        ↑ 用户 0.7 秒就看到第一个字了
```

### 立刻用一次""")

    nb.code('''# 单独可运行：三种减量 —— 并行（省延迟）、裁剪（省钱）、流式（省首字延迟）
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

# 各工具的模拟耗时（真实项目里就是实测 P50；口径完全一样，只是这里可复现）
TOOL_SIM_MS = {
    "calc": 120.0,
    "count_words": 100.0,
    "lookup_order": 300.0,
    "search_kb": 400.0,
}


@dataclass
class ToolCallPlan:
    """一次「计划中的工具调用」。"""

    name: str                    # 工具名
    args: dict                   # 参数字典

    @property
    def sim_ms(self):
        """这个工具的模拟耗时；不在表里的工具给一个默认值 200ms。"""
        return TOOL_SIM_MS.get(self.name, 200.0)


def run_tools_sequential(calls):
    """串行执行：总耗时 = 各工具耗时之和。

    参数 calls：list[ToolCallPlan]
    返回     ：(结果列表, 总耗时 ms)
    """
    out, total = [], 0.0
    for c in calls:
        out.append(c.name + ":ok")      # 真实现里这里是工具函数在干活
        total += c.sim_ms               # 一个一个排队，耗时直接相加
    return out, total


def run_tools_parallel(calls):
    """并行执行：总耗时 ≈ 最慢的那个。

    ★ 这里用线程池而不是 asyncio：工具调用绝大多数时间在等 IO（网络/数据库），
      线程足够，而且不用把整条链路改成异步。
    ★ `lambda c=c:` 里的默认参数是必须的 —— 不写它，所有 lambda 会共享同一个 c
      （闭包的延迟绑定坑），结果全部变成最后一个工具。
    """
    with ThreadPoolExecutor(max_workers=max(1, len(calls))) as pool:
        futures = [pool.submit(lambda c=c: c.name + ":ok") for c in calls]
        out = [f.result() for f in futures]         # 等全部完成（也可用 as_completed 流式收）
    return out, max((c.sim_ms for c in calls), default=0.0)


# ---- ① 并行工具调用 ----
CALLS = [ToolCallPlan("lookup_order", {"order_id": "A1001"}),
         ToolCallPlan("search_kb", {"query": "物流延迟"})]
_, seq_ms = run_tools_sequential(CALLS)
_, par_ms = run_tools_parallel(CALLS)
print("① 并行工具调用（前提：这两个工具之间没有依赖）")
print("   串行 %-28s %5.0fms   (= 300 + 400)"
      % (" → ".join(c.name for c in CALLS), seq_ms))
print("   并行 %-28s %5.0fms   (= max(300, 400))"
      % (" ∥ ".join(c.name for c in CALLS), par_ms))
print("   节省 %-28s %5.0fms（%.0f%%）"
      % ("", seq_ms - par_ms, (1 - par_ms / seq_ms) * 100))
print("   ★ 有依赖的工具必须串行（B 要用 A 的结果）；并行还会带来限流、")
print("     资源争抢、部分失败的处理 —— 先确认工具真的无依赖。")
print()

# ---- ② 上下文裁剪 ----
BASE_TOKENS = 900            # 系统提示词 + 工具说明：每次调用都要重发，跑不掉
PER_TURN_TOKENS = 260        # 每一轮对话在历史上新增的 token


def amortized_prompt_tokens(history_turns, window=None):
    """算一次调用要发多少输入 token。

    参数 history_turns：已经积累了多少轮历史
         window       ：滑动窗口/摘要后的最大轮数；None 表示不裁剪
    返回             ：输入 token 数
    """
    turns = history_turns if window is None else min(history_turns, window)
    return BASE_TOKENS + turns * PER_TURN_TOKENS


PRICE_PROMPT_PER_1K, PRICE_COMPLETION_PER_1K = 0.012, 0.036
COMPLETION_TOKENS = 200      # 每次回答的输出 token（假设固定，便于对比）


def call_cost(prompt_tokens, completion_tokens=COMPLETION_TOKENS):
    """按大模型单价算一次调用的成本。"""
    return (prompt_tokens / 1000 * PRICE_PROMPT_PER_1K
            + completion_tokens / 1000 * PRICE_COMPLETION_PER_1K)


print("② 上下文裁剪（第 05 章的滑动窗口/摘要，在这里变成钱）")


def _disp_width(text):
    """显示宽度：中日韩字符占 2 列 —— 不这样算，中文表格必然歪。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text, width):
    """按显示宽度补空格（不能用 %-10s：它按字符数算，中文会错位）。"""
    return text + " " * max(0, width - _disp_width(text))


def show(headers, rows, indent=2):
    """极简表格（课程零第三方依赖，不引入 rich/tabulate）。"""
    widths = [max([_disp_width(h)] + [_disp_width(r[i]) for r in rows])
              for i, h in enumerate(headers)]
    sp = " " * indent
    print(sp + "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)))
    print(sp + "  ".join("-" * w for w in widths))
    for r in rows:
        print(sp + "  ".join(_pad(c, widths[i]) for i, c in enumerate(r)))


WINDOW = 5            # ← 试着改这里：窗口改成 2（更省）或 10（保留更多上下文）
rows = []
for turns in (1, 5, 10, 30):
    raw = amortized_prompt_tokens(turns)                    # 不裁剪：历史有多长就发多长
    win = amortized_prompt_tokens(turns, window=WINDOW)     # 裁剪：只发最近 WINDOW 轮
    raw_cost, win_cost = call_cost(raw), call_cost(win)
    rows.append(["%d 轮" % turns, str(raw), "¥%.5f" % raw_cost,
                 str(win), "¥%.5f" % win_cost,
                 "%.0f%%" % ((1 - win_cost / raw_cost) * 100)])
show(["历史长度", "不裁剪 token", "成本", "窗口=%d token" % WINDOW, "裁剪后成本", "降幅"], rows)
print("   ★ 每次调用都要重发整段历史 → 输入 token 随轮数线性增长，账单也是。")
print()


# ---- ③ 流式输出 ----
def stream_timeline(text, ttft_ms, total_ms, chunk=2):
    """把一段回答切成流式片段，并给出「每个片段到达的时刻」。

    为什么要模拟时间轴？因为流式的价值全在时间轴上。
    参数 text    ：完整回答
         ttft_ms ：首字延迟（第一个片段到达的时刻）
         total_ms：总耗时（最后一个片段到达的时刻）
         chunk   ：每个片段几个字
    返回         ：(片段列表, 每个片段到达的时刻列表)
    """
    chunks = [text[i:i + chunk] for i in range(0, len(text), chunk)] or [""]
    span = max(1.0, total_ms - ttft_ms)              # 首个到末个之间的时间跨度
    if len(chunks) == 1:
        times = [ttft_ms]
    else:
        times = [ttft_ms + span * i / (len(chunks) - 1) for i in range(len(chunks))]
    return chunks, times


ANSWER = ("从订单 A1001 的物流节点看，延迟主要来自中转仓积压（占比约 60%）；"
          "建议：① 将该线路改走直发仓；② 对超 48 小时未更新的单子自动预警。")
LATENCY_MS, TTFT_MS = 2200.0, 700.0
chunks, times = stream_timeline(ANSWER, TTFT_MS, LATENCY_MS)

print("③ 流式输出：总时长不变，但用户看到的第一个字早了 3 倍")
print("   非流式 · 首字延迟 : %.0fms（用户对着空白屏幕等 %.1f 秒）"
      % (LATENCY_MS, LATENCY_MS / 1000))
print("   流式   · 首字延迟 : %.0fms（TTFT = Time To First Token）" % TTFT_MS)
print("   两种方式的总时长  : %.0fms（完全相同 —— 流式不省成本、不省总时长）"
      % LATENCY_MS)
print("   时间轴（前 5 个片段）：")
for c, t in list(zip(chunks, times))[:5]:
    print("      %6.0fms  %r" % (t, c))
print("      …共 %d 个片段" % len(chunks))
print()
print("★ 用户感知的「快」主要来自 TTFT。总时长 2.2s 但 0.7s 开始出字，")
print("  体感远好于「安静 2.2 秒然后一次性弹出全部内容」。")
print("★ 代价：复杂度上来了（异步生成器 + SSE 推给前端），而且首字之后出错更难处理。")''')

    nb.md("""### 结果说明什么

| 手段 | 省的是 | 本次演示的收益 | 动不动质量 |
|---|---|---|---|
| 并行工具 | 延迟 | 700ms → 400ms（-43%） | 不动 |
| 上下文裁剪 | 成本（输入 token） | 30 轮时降 70% | 不动（但要选对保留什么） |
| 流式输出 | **首字延迟** | 2200ms → 700ms | 不动（纯体验） |

注意最后一行：流式**一分钱都没省**，总时长也一模一样。
它优化的是「用户感觉等了多久」—— 而这件事在客服、搜索这类场景里直接决定留存。

到这里，三类「不动质量」的优化都用完了。接下来要动质量了，得格外小心。""")

    # ==================================================================
    section(nb, "⑥", "路由：简单任务给小模型，复杂任务给大模型")

    nb.md("""### 现在卡在哪

前面的优化都**不动质量**。但成本还能再降一个台阶 —— 只要敢换模型。

小模型便宜 **10 倍**、快 **3 倍**，代价是能力弱。所以路由的唯一任务是：

> **判断「这个问题到底需不需要大模型」。**

### 所以我需要一个「分流器」

```
                         ┌─ 长度超阈值（信息量大） ──────┐
   问题 ──► 规则判断 ────┼─ 命中复杂意图词（分析/对比/为什么）─┼──► large
                         ├─ 命中简单意图词（计算/查询/统计） ──┼──► small
                         └─ 都不命中 ────────────────────┘
                                      ▲
                                      └── ★ 兜底走**大**模型
```

**兜底为什么是大模型？因为路由错误的代价不对称：**

| 错误方向 | 代价 |
|---|---|
| 简单问题给了大模型 | 多花一点钱 —— **可控** |
| 复杂问题给了小模型 | 用户拿到一个「没错但没用」的答案 —— **不可控，而且会流失** |

### 它的用法

`ModelRouter.route(问题)` → `RouteDecision(tier, reason)`。
`reason` 不是给你看的注释，它是**上线后排查「为什么这个问题走了大模型」的唯一线索**。

### 立刻用一次""")

    nb.code('''# 单独可运行：模型路由 —— 简单给小模型，复杂给大模型，不确定保守走大模型
from dataclasses import dataclass

# 复杂意图词：出现任何一个，就认为「这个问题的回答质量比钱重要」
COMPLEX_HINTS = ("分析", "对比", "为什么", "原因", "设计", "规划", "方案", "权衡",
                 "推理", "评估", "建议", "优化", "架构", "debug", "排查", "总结并")
# 简单意图词：出现任何一个，就认为「小模型够用」
SIMPLE_HINTS = ("计算", "算一下", "统计", "查询", "查一下", "订单", "翻译",
                "格式化", "是多少", "有几个", "转换为")


@dataclass
class RouteDecision:
    """一次路由决策。"""

    tier: str        # "small" 或 "large"
    reason: str      # 为什么这么判 —— 这句话就是上线后的排查线索


class ModelRouter:
    """规则路由：便宜、可解释、可测试。生产里可以换成一个小模型分类器。"""

    def __init__(self, long_char_threshold=60):
        # ← 试着改这里：把阈值改成 20，长问题会全部涌向大模型（更贵但更稳）
        self.long_char_threshold = long_char_threshold
        self.stats = {"small": 0, "large": 0}      # 路由分布：成本结构的第一手数据

    def route(self, question):
        """给一个问题挑档位，返回 RouteDecision。"""
        q = question.strip()

        if len(q) > self.long_char_threshold:       # ① 长问题通常信息量大、要求高
            self.stats["large"] += 1
            return RouteDecision("large", "长度 %d 字符 > 阈值，信息量大" % len(q))

        if any(h in q for h in COMPLEX_HINTS):      # ② 命中复杂意图词
            self.stats["large"] += 1
            return RouteDecision("large", "命中复杂意图词")

        if any(h in q for h in SIMPLE_HINTS):       # ③ 命中简单意图词
            self.stats["small"] += 1
            return RouteDecision("small", "命中简单意图词")

        # ★ 兜底走大模型：不确定的时候，宁可多花钱，也不要给用户烂答案
        self.stats["large"] += 1
        return RouteDecision("large", "无法判断 → 保守走大模型")


SAMPLES = [
    "计算 (12+8)*3/4",
    "统计「护栏」这两个字有几个字",
    "订单 A1001 到哪了？",
    "今天天气怎么样",
    "帮我分析一下订单 A1001 延迟的原因，并给出改进建议",
    "对比一下两种退款方案的优劣，并给出你的建议",
    "请解释一下这段代码为什么会死循环，并给出修复方案，同时说明可能的影响范围",
]

def _disp_width(text):
    """显示宽度：中日韩字符占 2 列（中文表格对不齐，几乎总是因为漏了这一步）。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text, width):
    """按显示宽度补空格。"""
    return text + " " * max(0, width - _disp_width(text))


def show(headers, rows, indent=2):
    """极简表格（课程零第三方依赖，不引入 rich/tabulate）。"""
    widths = [max([_disp_width(h)] + [_disp_width(r[i]) for r in rows])
              for i, h in enumerate(headers)]
    sp = " " * indent
    print(sp + "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)))
    print(sp + "  ".join("-" * w for w in widths))
    for r in rows:
        print(sp + "  ".join(_pad(c, widths[i]) for i, c in enumerate(r)))


router = ModelRouter()
rows = []
for q in SAMPLES:
    d = router.route(q)      # ★ 每个问题只调一次 route()：它会累计统计，重复调用会污染分布
    rows.append([q[:40], d.tier, d.reason])
show(["问题", "路由到", "理由"], rows)
print()
print("路由分布 :", router.stats)
print("★ 注意「今天天气怎么样」——它既不含简单词也不含复杂词，也**保守地走了大模型**。")
print()

# ---- 路由错误会掉多少质量：两种回答摆在一起看 ----
ANSWER_BIG = ("从订单 A1001 的物流节点看，延迟主要来自中转仓积压（占比约 60%）；"
              "建议：① 将该线路改走直发仓；② 对超 48 小时未更新的单子自动预警。")
ANSWER_SMALL = "订单延迟了，建议尽快联系快递。"
print("把复杂问题错误地路由到小模型会怎样：")
print("   大模型 :", ANSWER_BIG)
print("   小模型 :", ANSWER_SMALL)
print("   ★ 小模型的回答「没错」，但它没有任何可执行信息。")
print("     这种退化**无法用「正确率」衡量** —— 只能用第 10 章的评估集 + 评判发现。")
print("     所以：**每一条路由规则都必须用评估集验证**，不能凭感觉。")
print()

# ---- 路由到底省了多少钱：全部走大模型 vs 按路由走 ----
PRICES = {"large": (0.012, 0.036), "small": (0.001, 0.002)}
BASE_TOKENS, PER_TURN_TOKENS, COMPLETION_TOKENS = 900, 260, 200


def one_call_cost(tier, question):
    """按档位估算回答这个问题要多少钱（复杂问题历史更长，所以更贵）。"""
    turns = 4 if len(question) > 30 else 1          # 复杂问题通常带着更多上下文
    prompt_tokens = BASE_TOKENS + turns * PER_TURN_TOKENS
    pp, cp = PRICES[tier]
    return prompt_tokens / 1000 * pp + COMPLETION_TOKENS / 1000 * cp


all_large = sum(one_call_cost("large", q) for q in SAMPLES)          # 不路由：全给大模型
routed = sum(one_call_cost(router.route(q).tier, q) for q in SAMPLES)  # 按路由分流
print("这 7 个问题，全部走大模型 : ¥%.5f" % all_large)
print("按路由分流后             : ¥%.5f" % routed)
print("省下                     : ¥%.5f（%.0f%%）"
      % (all_large - routed, (1 - routed / all_large) * 100))
print()
print("★ 注意：省下的这部分是**拿质量换的**（简单问题本来答案就一样，所以这次没掉质量）。")
print("  要证明「真的没掉」，只能靠评估集 —— 第 10 章的做法。")''')

    nb.md("""### 结果说明什么

- 三条规则覆盖了绝大多数流量，而且**每一条都带一句可读的理由**。
- 「今天天气怎么样」既不含简单词也不含复杂词 → **保守走大模型**。
  这就是「代价不对称」的直接体现。
- 路由省下的钱是**真实但不免费**的：它第一次动了质量。

> 优化到这里，成本和延迟都降下来了。但还有一个必须回答的问题：
> **如果优化失败了呢？** prompt 注入、死循环、用户刷量、上游重试风暴 ——
> 任何一个都能让成本失控。优化只是降低**期望值**，我们还需要控制**上界**。""")

    # ==================================================================
    section(nb, "⑦", "预算兜底：优化降低期望值，预算控制上界")

    nb.md("""### 现在卡在哪

我们已经有了缓存、裁剪、路由。但这些都是「平均情况下更便宜」。

**平均」救不了事故。** 下面任何一件事都能让账单失控：

```
提示词注入让模型反复调工具   死循环        用户刷量       上游重试风暴
        ↓                      ↓             ↓               ↓
     一个请求烧掉几百次调用，凌晨三点账单爆炸，而你还在睡觉
```

### 所以我需要一个「硬上限 + 优雅停机」

三个维度都要有，因为它们的失效方式不同：

| 维度 | 什么时候先撞上它 |
|---|---|
| 调用次数 | 死循环、反复重试 |
| 金额 | 上下文特别大、输出特别长 |
| 墙上时间 | 上游变慢、工具卡住 |

### 它的用法：检查必须放在**调用之前**

```
    ✗ 调用模型 ──► 记账 ──► 检查预算   ← 钱已经花出去了，这叫事后统计
    ✓ 检查预算 ──► 调用模型 ──► 记账   ← 这才拦得住账单
```

超限时抛 `core.errors.BudgetExceeded` —— 它继承自 `AbortAgent`，
意思是「**预期内的策略性停机**」，不是故障。所以上层应该：

```
优雅停机 + 返回已完成的部分 + 明确告知用户
   ↑ 而不是当成 500 错误去告警、去重试、去把账单再翻一倍
```

### 立刻用一次""")

    nb.code('''# 单独可运行：三维预算 + 调用前检查 + 优雅停机
import sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.errors import AbortAgent, BudgetExceeded

PRICES = {"large": (0.012, 0.036), "small": (0.001, 0.002)}


class UsageMeter:
    """精简版计量器：只保留预算需要的三个量（次数 / 金额 / 墙上时间）。"""

    def __init__(self):
        self.calls = []
        self.cost = 0.0
        self.wall_ms = 0.0        # 模拟的墙上时间（真实项目里是实测值）

    def record_call(self, tier, prompt_tokens, completion_tokens, latency_ms=2200.0):
        """记一次调用，同时累计金额与时间。"""
        pp, cp = PRICES[tier]
        self.cost += prompt_tokens / 1000 * pp + completion_tokens / 1000 * cp
        self.wall_ms += latency_ms
        self.calls.append(tier)
        return self.cost

    @property
    def model_calls(self):
        return len(self.calls)


class BudgetGuard:
    """三维预算：调用次数 / 金额 / 墙上时间。任一超限即抛 BudgetExceeded。"""

    def __init__(self, max_calls=3, max_cost=1.0, max_wall_ms=10000.0):
        self.max_calls = max_calls
        self.max_cost = max_cost
        self.max_wall_ms = max_wall_ms
        self.trips = 0            # 触发次数：这个指标应该被监控（触发变多说明有异常流量）

    def check(self, meter):
        """在**每次模型调用之前**调用它。

        参数 meter：当前的用量计量器
        返回      ：None（没超预算）；超了就抛 BudgetExceeded
        """
        if meter.model_calls >= self.max_calls:
            self.trips += 1
            raise BudgetExceeded(
                "调用次数预算耗尽：%d/%d" % (meter.model_calls, self.max_calls))
        if meter.cost >= self.max_cost:
            self.trips += 1
            raise BudgetExceeded(
                "成本预算耗尽：¥%.5f/¥%.5f" % (meter.cost, self.max_cost))
        if meter.wall_ms >= self.max_wall_ms:
            self.trips += 1
            raise BudgetExceeded(
                "时间预算耗尽：%.0fms/%.0fms" % (meter.wall_ms, self.max_wall_ms))


# ---- 演示：预算是 3 次调用，用户给了 5 个问题 ----
QUESTIONS = ["订单 A1001 到哪了？", "计算 (12+8)*3/4", "统计「护栏」这两个字有几个字",
             "订单 A1002 到哪了？", "计算 1+1"]
guard = BudgetGuard(max_calls=3, max_cost=1.0)
meter = UsageMeter()
done = []

for q in QUESTIONS:
    try:
        guard.check(meter)                 # ★ 调用「之前」检查 —— 这是本节的重点
    except BudgetExceeded as exc:
        print("预算触发        : %s: %s" % (type(exc).__name__, exc))
        print("已完成 / 未完成 : %d / %d" % (len(done), len(QUESTIONS) - len(done)))
        print("已花成本        : ¥%.5f / 上限 ¥%.2f" % (meter.cost, guard.max_cost))
        print("→ 正确姿势：返回已完成的部分 + 明确告知用户「因预算限制未全部完成」。")
        break
    meter.record_call("large", 1200, 120)  # 检查通过，才真的花钱
    done.append(q)

print()
print("BudgetExceeded 是 AbortAgent 的子类 →", issubclass(BudgetExceeded, AbortAgent))
print("  含义：这是**预期内的策略性停机**，不是故障 ——")
print("  不该触发 500 告警，也不该被重试（重试只会让账单再翻一倍）。")
print()

# ---- 三个维度要能各自独立触发（少一个维度就漏一类事故）----
print("三个维度各自独立触发：")
for label, g, calls in [
    ("次数", BudgetGuard(max_calls=1, max_cost=99, max_wall_ms=1e9), 3),
    ("金额", BudgetGuard(max_calls=99, max_cost=0.02, max_wall_ms=1e9), 3),
    ("时间", BudgetGuard(max_calls=99, max_cost=99, max_wall_ms=3000), 3),
]:
    m = UsageMeter()
    hit = ""
    for _ in range(calls):
        try:
            g.check(m)
        except BudgetExceeded as exc:
            hit = str(exc)
            break
        m.record_call("large", 1200, 120)
    print("   %s维度 : %s" % (label, hit or "（没触发，检查预算设置）"))
print()

# ---- 对照：把检查放在调用「之后」会发生什么 ----
late = UsageMeter()
for _ in range(5):
    late.record_call("large", 1200, 120)      # 先花钱，再检查
try:
    BudgetGuard(max_calls=3, max_cost=1.0).check(late)
except BudgetExceeded as exc:
    print("事后检查：%s" % exc)
    print("   ↑ 钱已经花完了。预算检查写在调用之后 = 只是事后统计，拦不住账单。")''')

    nb.md("""### 结果说明什么

- 预算在第 3 次调用**之前**触发，已完成的部分被完整保留 —— 这就是优雅停机。
- `issubclass(BudgetExceeded, AbortAgent)` 为 `True`：它是**策略性停机**，不是故障。
- 三个维度（次数 / 金额 / 时间）各自都能独立触发。**死循环往往先撞时间预算**，
  所以只设「次数」是不够的。
- 最后那段对照实验说明：**检查位置错了，预算就形同虚设**。

> 优化的顺序到现在走完了：测量 → 缓存 → 减量 → 路由，外加预算兜底。
> 但「我觉得快了、便宜了」不算数。下一节把它们放在同一张表里量一遍。""")

    # ==================================================================
    section(nb, "⑧", "before/after：每一步各省了多少？")

    nb.md("""### 现在卡在哪

前面每一节都在说「这样能省」。但**省了多少**必须用同一把尺子量出来，
否则你没法回答老板那句「这次优化值不值」。

### 所以我需要一条能开合开关的流水线

```
   问题 ──► ① 查缓存 ──命中──► 直接用旧答案（0 次调用，成本 0、延迟 0）
              │ 未命中
              ▼
           ② 路由 ──► large / small
              │
              ▼
           ③ 工具 ──► 串行（sum）或 并行（max）
              │
              ▼
           ④ 调模型 ──► 记账（token / 成本 / 耗时 / 首字延迟）
              │
              ▼
           ⑤ 写缓存（下次同样的问题就是 0 成本）
```

四个配置就是四个开关的组合：

| 配置 | 缓存 | 路由 | 并行 | 流式 |
|---|---|---|---|---|
| 朴素版 | ✗ | ✗ | ✗ | ✗ |
| ① 只加缓存 | ✓ | ✗ | ✗ | ✗ |
| ② 再加路由 | ✓ | ✓ | ✗ | ✗ |
| ③ 再加并行 + 流式 | ✓ | ✓ | ✓ | ✓ |

> 下面这一格比较长 —— 因为它把前面所有零件放在**同一个格子里**（自包含），
> 这样你才能看到它们怎么互相影响。跑完直接看两张表。""")

    nb.code('''# 单独可运行：优化前后对比 —— 一步一步加，每一步都量一遍
import re, sys, pathlib
ROOT = pathlib.Path.cwd()
while not (ROOT / "core").is_dir() and ROOT.parent != ROOT:
    ROOT = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from core.llm import estimate_tokens


# ============ 1. 价目表 ============
@dataclass(frozen=True)
class Price:
    """价目表：元 / 1K token + 模拟耗时与 TTFT。"""

    name: str
    prompt_per_1k: float
    completion_per_1k: float
    sim_latency_ms: float
    sim_ttft_ms: float

    def cost(self, prompt_tokens, completion_tokens):
        return (prompt_tokens / 1000 * self.prompt_per_1k
                + completion_tokens / 1000 * self.completion_per_1k)


PRICING = {
    "large": Price("large-pro", 0.012, 0.036, 2200, 700),
    "small": Price("small-flash", 0.001, 0.002, 600, 180),
}


# ============ 2. 计量器 ============
@dataclass
class CallRecord:
    """一条账目。"""

    index: int
    tier: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: float
    cost: float


class UsageMeter:
    """计量器：模型调用、缓存命中、成本、墙上时间、首字延迟。"""

    def __init__(self):
        self.calls = []
        self.cache_hits = 0
        self.wall_ms = 0.0          # 整轮任务的总耗时（用户实际等的时间）
        self.first_token_ms = 0.0   # 整轮任务的首字延迟（用户感觉等的时间）

    def record_call(self, tier, prompt_tokens, completion_tokens, latency_ms):
        price = PRICING[tier]
        rec = CallRecord(len(self.calls) + 1, tier, prompt_tokens, completion_tokens,
                         latency_ms, price.cost(prompt_tokens, completion_tokens))
        self.calls.append(rec)
        return rec

    def record_cache_hit(self, saved_tier, prompt_tokens, completion_tokens):
        """命中缓存：成本 0、延迟 0，但要记下「本来会花多少」。"""
        self.cache_hits += 1
        return PRICING[saved_tier].cost(prompt_tokens, completion_tokens)

    @property
    def model_calls(self):
        return len(self.calls)

    @property
    def prompt_tokens(self):
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def completion_tokens(self):
        return sum(c.completion_tokens for c in self.calls)

    @property
    def total_tokens(self):
        return self.prompt_tokens + self.completion_tokens

    @property
    def cost(self):
        return sum(c.cost for c in self.calls)


# ============ 3. 缓存（精确 + 语义 + 实体硬约束）============
PUNCT = "，。！？、；：,.!?;:~'\\"“”‘’()（）[]【】"
POLITE = ("帮我", "请", "麻烦", "一下", "一下子", "谢谢", "好吗",
          "可以", "能不能", "我想", "我要")


def _norm(text):
    """归一化：去标点、去礼貌词、去空白。"""
    t = (text or "").strip().lower()
    t = "".join(ch for ch in t if ch not in PUNCT)
    for word in POLITE:
        t = t.replace(word, "")
    return "".join(ch for ch in t if not ch.isspace())


ENTITY_RE = re.compile(r"[A-Za-z]{0,2}\\d{2,}")
NUMBER_RE = re.compile(r"\\d+(?:\\.\\d+)?")


def entities_of(text):
    """抽出必须完全一致才算同一件事的实体。"""
    found = {m.group(0).upper() for m in ENTITY_RE.finditer(text)}
    found |= {m.group(0) for m in NUMBER_RE.finditer(text)}
    return frozenset(found)


def bigrams(text):
    """字符二元组集合。"""
    t = _norm(text)
    if len(t) < 2:
        return {t} if t else set()
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a, b):
    """Dice 相似度 = 2|A∩B| / (|A|+|B|)。"""
    ga, gb = bigrams(a), bigrams(b)
    return 2 * len(ga & gb) / (len(ga) + len(gb)) if ga and gb else 0.0


@dataclass
class CacheEntry:
    key: str
    question: str
    entities: frozenset
    answer: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    hits: int = 0


@dataclass
class CacheLookup:
    hit: bool
    kind: str = ""
    entry: CacheEntry = None
    score: float = 0.0
    reason: str = ""


class SemanticCache:
    """精确 + 语义 + 实体硬约束的缓存。"""

    def __init__(self, threshold=0.72, entity_guard=True):
        self.threshold = threshold
        self.entity_guard = entity_guard
        self.entries = []
        self.stats = {"exact_hit": 0, "semantic_hit": 0, "miss": 0,
                      "entity_blocked": 0, "put": 0}

    def get(self, question):
        key, ents = _norm(question), entities_of(question)
        for e in self.entries:                             # ① 精确命中
            if e.key == key:
                e.hits += 1
                self.stats["exact_hit"] += 1
                return CacheLookup(True, "exact", e, 1.0, "归一化后完全一致")

        best_score, best_entry = 0.0, None                 # ② 语义命中
        for e in self.entries:
            s = similarity(question, e.question)
            if s > best_score:
                best_score, best_entry = s, e

        if best_entry is not None and best_score >= self.threshold:
            if self.entity_guard and best_entry.entities != ents:   # ★ 实体闸门
                self.stats["entity_blocked"] += 1
                return CacheLookup(False, "entity_blocked", best_entry, best_score,
                                   "实体不同 → 拒绝命中")
            best_entry.hits += 1
            self.stats["semantic_hit"] += 1
            return CacheLookup(True, "semantic", best_entry, best_score,
                               "相似度 %.2f" % best_score)

        self.stats["miss"] += 1
        return CacheLookup(False, "miss", None, best_score, "未命中")

    def put(self, question, answer, tier, prompt_tokens=0, completion_tokens=0):
        e = CacheEntry(_norm(question), question, entities_of(question), answer,
                       tier, prompt_tokens, completion_tokens)
        self.entries.append(e)
        self.stats["put"] += 1
        return e


# ============ 4. 路由 ============
COMPLEX_HINTS = ("分析", "对比", "为什么", "原因", "设计", "规划", "方案", "权衡",
                 "推理", "评估", "建议", "优化", "架构", "debug", "排查", "总结并")
SIMPLE_HINTS = ("计算", "算一下", "统计", "查询", "查一下", "订单", "翻译",
                "格式化", "是多少", "有几个", "转换为")


@dataclass
class RouteDecision:
    tier: str
    reason: str


class ModelRouter:
    """规则路由：简单给小模型，复杂给大模型，不确定保守走大模型。"""

    def __init__(self, long_char_threshold=60):
        self.long_char_threshold = long_char_threshold
        self.stats = {"small": 0, "large": 0}

    def route(self, question):
        q = question.strip()
        if len(q) > self.long_char_threshold:
            self.stats["large"] += 1
            return RouteDecision("large", "长度超阈值")
        if any(h in q for h in COMPLEX_HINTS):
            self.stats["large"] += 1
            return RouteDecision("large", "命中复杂意图词")
        if any(h in q for h in SIMPLE_HINTS):
            self.stats["small"] += 1
            return RouteDecision("small", "命中简单意图词")
        self.stats["large"] += 1
        return RouteDecision("large", "无法判断 → 保守走大模型")


# ============ 5. 减量：并行工具 + 上下文账 ============
TOOL_SIM_MS = {"calc": 120.0, "count_words": 100.0,
               "lookup_order": 300.0, "search_kb": 400.0}


@dataclass
class ToolCallPlan:
    name: str
    args: dict

    @property
    def sim_ms(self):
        return TOOL_SIM_MS.get(self.name, 200.0)


def run_tools_sequential(calls):
    """串行：总耗时 = sum。"""
    return [c.name + ":ok" for c in calls], sum(c.sim_ms for c in calls)


def run_tools_parallel(calls):
    """并行：总耗时 ≈ max（前提是工具之间没有依赖）。"""
    with ThreadPoolExecutor(max_workers=max(1, len(calls))) as pool:
        futures = [pool.submit(lambda c=c: c.name + ":ok") for c in calls]
        out = [f.result() for f in futures]
    return out, max((c.sim_ms for c in calls), default=0.0)


def amortized_prompt_tokens(history_turns, base_tokens=900, per_turn_tokens=260):
    """一次调用要发多少输入 token（每次都要重发整段历史）。"""
    return base_tokens + history_turns * per_turn_tokens


# ============ 6. 测试集：5 个问题，其中 2 个是重复的 ============
QUESTIONS = [
    "订单 A1001 到哪了？",
    "计算 (12+8)*3/4",
    "订单 A1001 到哪里了？",                            # ← 与第 1 条语义重复
    "帮我分析一下订单 A1001 延迟的原因，并给出改进建议",   # ← 复杂，需要大模型
    "统计「护栏」这两个字有几个字",
]

# 假模型的答案库：归一化问题 -> (大模型答案, 小模型答案)
ANSWER_BANK = {
    _norm("订单 A1001 到哪了？"): (
        "订单 A1001 已发货，承运商顺丰，运单号 SF1234567890，预计 2025-01-05 送达。",
        "订单 A1001 已发货。"),
    _norm("计算 (12+8)*3/4"): (
        "计算过程：(12+8)=20，20×3=60，60÷4=15。答案是 15。",
        "答案是 15。"),
    _norm("帮我分析一下订单 A1001 延迟的原因，并给出改进建议"): (
        "从订单 A1001 的物流节点看，延迟主要来自中转仓积压（占比约 60%）；"
        "建议：① 将该线路改走直发仓；② 对超 48 小时未更新的单子自动预警。",
        "订单延迟了，建议尽快联系快递。"),
    _norm("统计「护栏」这两个字有几个字"): ("「护栏」共有 2 个字。", "2 个字。"),
}
# 第 3 个问题和第 1 个是同一个问题，只是换了说法 —— 答案当然也一样。
# 朴素版会把它当成新问题，**再付一次完整的钱**；这正是缓存要吃掉的那部分。
ANSWER_BANK[_norm("订单 A1001 到哪里了？")] = ANSWER_BANK[_norm("订单 A1001 到哪了？")]

# 工具计划：哪个问题要调哪些工具
PLAN = {
    _norm("订单 A1001 到哪了？"): [ToolCallPlan("lookup_order", {"order_id": "A1001"})],
    _norm("计算 (12+8)*3/4"): [ToolCallPlan("calc", {"expr": "(12+8)*3/4"})],
    _norm("帮我分析一下订单 A1001 延迟的原因，并给出改进建议"): [
        ToolCallPlan("lookup_order", {"order_id": "A1001"}),
        ToolCallPlan("search_kb", {"query": "物流延迟"})],
    _norm("统计「护栏」这两个字有几个字"): [ToolCallPlan("count_words", {"text": "护栏"})],
}


# ============ 7. 流水线：四个开关的组合 ============
@dataclass
class PipelineConfig:
    """一份流水线配置 —— 这就是「优化开关」的集合。"""

    key: str
    title: str
    cache: bool = False
    router: bool = False
    parallel: bool = False
    stream: bool = False


BASELINE = PipelineConfig("baseline", "朴素版（全大模型 / 无缓存 / 串行 / 非流式）")
CACHE_ONLY = PipelineConfig("cache", "① 只加缓存", cache=True)
CACHE_ROUTER = PipelineConfig("cache_router", "② 再加路由", cache=True, router=True)
OPTIMIZED = PipelineConfig("optimized", "③ 再加并行 + 流式",
                           cache=True, router=True, parallel=True, stream=True)


@dataclass
class PipelineReport:
    """一次流水线运行的结果。"""

    config: PipelineConfig
    meter: UsageMeter
    answers: list = field(default_factory=list)
    cache: SemanticCache = None
    router: ModelRouter = None


def run_pipeline(questions, cfg):
    """跑一遍流水线，返回带完整账目的报告。"""
    meter = UsageMeter()
    cache = SemanticCache()
    router = ModelRouter()
    report = PipelineReport(cfg, meter, cache=cache, router=router)
    clock = 0.0                  # 模拟的累计时间轴
    first_token = None           # 整轮任务的首字时刻

    for q in questions:
        key = _norm(q)

        # ---- ① 缓存 ----
        if cfg.cache:
            look = cache.get(q)
            if look.hit and look.entry is not None:
                meter.record_cache_hit(look.entry.tier, look.entry.prompt_tokens,
                                       look.entry.completion_tokens)
                report.answers.append(look.entry.answer)
                if first_token is None:
                    first_token = clock          # 命中 = 立刻有答案，首字延迟≈0
                meter.wall_ms = clock
                continue                          # ★ 整个流程到此结束：0 次模型调用

        # ---- ② 路由 ----
        tier, route_reason = "large", "未启用路由"
        if cfg.router:
            decision = router.route(q)
            tier, route_reason = decision.tier, decision.reason

        # ---- ③ 工具（串行 / 并行）----
        calls = PLAN.get(key, [])
        if calls:
            if cfg.parallel:
                _, tool_ms = run_tools_parallel(calls)
            else:
                _, tool_ms = run_tools_sequential(calls)
        else:
            tool_ms = 0.0

        # ---- ④ 调模型（记账）----
        history_turns = 4 if len(q) > 30 else 1        # 复杂问题带更多历史 → 更贵
        prompt_tokens = amortized_prompt_tokens(history_turns)
        answer_big, answer_small = ANSWER_BANK.get(key, ("无法处理。", "不知道。"))
        answer = answer_big if tier == "large" else answer_small
        price = PRICING[tier]
        rec = meter.record_call(tier=tier, prompt_tokens=prompt_tokens,
                                completion_tokens=estimate_tokens(answer),
                                latency_ms=price.sim_latency_ms)
        report.answers.append(answer)

        # ---- ⑤ 写缓存 ----
        if cfg.cache:
            cache.put(q, answer, tier, rec.prompt_tokens, rec.completion_tokens)

        # 非流式：用户要等整段生成完才看到第一个字；流式：等到 TTFT 就有字了
        if first_token is None:
            first_token = clock + (rec.latency_ms if not cfg.stream else price.sim_ttft_ms)
        clock += tool_ms + rec.latency_ms
        meter.wall_ms = clock

    meter.first_token_ms = first_token or 0.0
    return report


# ============ 8. 出表 ============
def _disp_width(text):
    """显示宽度：中日韩字符占 2 列 —— 不这样算，中文表格必然歪。"""
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in text)


def _pad(text, width):
    return text + " " * max(0, width - _disp_width(text))


def show(headers, rows, indent=2):
    """极简表格（课程零第三方依赖，不引入 rich/tabulate）。"""
    widths = [max([_disp_width(h)] + [_disp_width(r[i]) for r in rows])
              for i, h in enumerate(headers)]
    sp = " " * indent
    print(sp + "  ".join(_pad(h, widths[i]) for i, h in enumerate(headers)))
    print(sp + "  ".join("-" * w for w in widths))
    for r in rows:
        print(sp + "  ".join(_pad(c, widths[i]) for i, c in enumerate(r)))


def money(x):
    """金额格式化：大额两位小数，小额五位。"""
    return "¥%.2f" % x if abs(x) >= 1 else "¥%.5f" % x


reports = [run_pipeline(QUESTIONS, BASELINE), run_pipeline(QUESTIONS, CACHE_ONLY),
           run_pipeline(QUESTIONS, CACHE_ROUTER), run_pipeline(QUESTIONS, OPTIMIZED)]

show(["配置", "模型调用", "缓存命中", "总 token", "成本", "总耗时", "首字延迟"],
     [[r.config.title, str(r.meter.model_calls), str(r.meter.cache_hits),
       str(r.meter.total_tokens), money(r.meter.cost),
       "%.0fms" % r.meter.wall_ms, "%.0fms" % r.meter.first_token_ms]
      for r in reports])
print()

base, final = reports[0].meter, reports[-1].meter
show(["增量优化", "成本降幅", "总耗时降幅", "首字延迟降幅", "模型调用"],
     [[r.config.title,
       "-%.1f%%" % ((1 - r.meter.cost / base.cost) * 100),
       "-%.1f%%" % ((1 - r.meter.wall_ms / base.wall_ms) * 100),
       "-%.1f%%" % ((1 - r.meter.first_token_ms / base.first_token_ms) * 100),
       "%d 次" % r.meter.model_calls] for r in reports[1:]])
print()
print("缓存统计 :", reports[-1].cache.stats)
print("路由分布 :", reports[-1].router.stats)
print()
print("★ 一步一步加，每一步都量一遍 —— 这就是本章的核心方法论。")
print("  如果某一步的降幅是 0，那就把它撤掉：它在增加复杂度却没有收益。")
print()
print("★ 优化后 5 条回答里，只有「复杂问题」那条还走大模型 —— 质量没有下降。")
print("  但这句结论**不能靠感觉**：必须用第 10 章的评估集证明。")
print()
print("结果：成本 %s → %s（-%.1f%%），首字延迟 %.0fms → %.0fms（-%.1f%%）"
      % (money(base.cost), money(final.cost),
         (1 - final.cost / base.cost) * 100,
         base.first_token_ms, final.first_token_ms,
         (1 - final.first_token_ms / base.first_token_ms) * 100))
print()
print("★ 还有一件事一分钱不花：prompt 前缀缓存（prefix caching）。")
print("  很多厂商对「相同前缀」的输入 token 打折。把**稳定的内容放前面**")
print("  （系统提示词、工具说明、长期记忆），把**变化的内容放后面**")
print("  （用户输入、检索结果），就能吃到这部分折扣 —— 不改一行逻辑。")''')

    nb.md("""### 结果说明什么

**每一步都单独说得清省了多少：**

| 步骤 | 省的是什么 | 动了质量吗 | 为什么 |
|---|---|---|---|
| ① 只加缓存 | 成本、延迟 | **没有** | 命中的就是上次那个答案 |
| ② 再加路由 | 成本、延迟（更大一档） | **动了**，要靠评估集兜住 | 简单问题换小模型 |
| ③ 再加并行 + 流式 | 延迟、首字延迟 | **没有** | 只是换了执行方式 |

两条纪律，是这一章真正要带走的东西：

1. **每一次优化都必须能说出省了多少。** 说不出来的，就撤掉 ——
   它在增加复杂度却没有收益。
2. **每一次动质量的优化（换模型、砍提示词）都必须用评估集证明质量没掉。**
   注意顺序：前两步都不动质量，所以可以放心做；换模型排在最后。

> **成本优化最大的敌人不是单价，是「没必要的调用」。** 常见的浪费来源：
> 每轮都重发全部历史、把没用到的工具说明塞进提示词、多智能体互相转发消息、
> 失败后无上限重试、循环检测不严导致的空转。""")

    # ==================================================================
    section(nb, "⑨", "常见坑汇总")

    pitfall_table(nb, [
        ("成本差 1000 倍",
         "报价是「每 100 万 token」，换算成「每 1K」时少乘 / 多乘了一个零",
         "内部统一用「元 / 1K token」，并写一条「手算 == 计量器」的断言"),
        ("计量散落在业务代码里",
         "总有几条调用路径忘了记账，账目永远对不上",
         "记账放在**最靠近模型调用的那一层**（LLM 网关/适配器）"),
        ("只统计 token 不统计 TTFT",
         "总时长看着还行，用户早就因为「没有反馈」跑了",
         "TTFT 和总时长是两个指标，要分开优化、分开看"),
        ("跨用户共享缓存 → 数据泄露（严重事故）",
         "缓存 key 里没带租户 / 用户 ID",
         "key 必须包含：用户 ID、权限级别、工具集版本、模型版本、知识库版本"),
        ("语义缓存假命中：A 的信息答给问 B 的人",
         "只按相似度命中；A1001 与 A1002 的相似度高达 0.78，超过阈值",
         "实体硬约束（订单号/数字必须完全一致）+ 假命中率监控（必须为 0）"),
        ("语义阈值拍脑袋定",
         "要么几乎不命中（白做），要么假命中（事故）",
         "shadow mode 先只记日志不生效，人工看 200 组样本再定阈值"),
        ("缓存旧数据，用户信息过期",
         "缓存没有 TTL，写操作后也不失效",
         "带 TTL；写操作成功后按实体主动失效（`invalidate_entities`）"),
        ("无脑并行所有工具",
         "有依赖的工具被并行 → 结果错乱；还可能触发上游限流",
         "判据只有一句：B 的参数里有没有用到 A 的返回值"),
        ("只看平均值",
         "P99 用户已经流失了，平均值还是很好看",
         "看 P50/P95/P99 和 TTFT；把成本与延迟当成一等评估指标"),
        ("路由过激，复杂问题掉质量",
         "为了省钱把「无法判断」也丢给小模型",
         "兜底走大模型；每条路由规则都用评估集验证"),
        ("预算检查写在调用之后",
         "那只是事后统计，拦不住账单",
         "调用前检查；三个维度都要有：次数 / 金额 / 墙上时间"),
        ("把 BudgetExceeded 当故障处理",
         "触发告警、自动重试，账单再翻一倍",
         "它是 AbortAgent：优雅停机 + 返回已完成的部分 + 告知用户"),
    ])

    summary(nb, [
        "**优化顺序：先测量 → 再缓存 → 再减量 → 最后才换模型**；前三步都不动质量。",
        "**「贵不贵」必须可计算。** 计量器要能被手算验证 —— 价目表改错了不会有任何报错。",
        "**缓存是性价比最高的优化**，但它的 key 设计比相似度算法重要 100 倍；"
        "实体硬约束是防假命中的底线。",
        "**假命中必须为 0，命中率低没关系。** 相似度防「不相干」，实体约束防「差一点」。",
        "**减量分三个层面**：并行省延迟（sum→max）、裁剪省输入 token、流式省 TTFT。",
        "**路由错误的代价不对称** → 不确定就保守走大模型，并用评估集证明质量没掉。",
        "**优化降低期望值，预算控制上界。** 预算检查必须在调用**之前**，且三个维度都要有。",
        "**说不出省了多少的优化，就撤掉。** 它在增加复杂度却没有收益。",
    ], "第 13 章会看到：这些东西一旦上线，就都变成分布式系统问题 —— "
       "单机的 `dict` 缓存不共享了、内存预算不跨请求了、"
       "进程随时可能被杀，而你已经花掉的钱不会退。"
       "下一章把它们装进一个「坏了也不出事」的服务外壳里。")

    exercises(nb, [
        ("**打破缓存护栏，观察会发生什么（必做）。**\n\n"
         "把第 ③ 节的 `THRESHOLD` 改成 `0.5`、再依次把 `ENTITY_GUARD` 改成 `False`，重跑那一格。\n"
         "然后加一句 `订单 A1003 到哪了？`，看实体约束是否兜住了它。\n\n"
         "最后回答：为什么「宁可命中率低一点，也不能答错对象」？",
         "阈值降到 0.5 后，更多问题会命中语义缓存（包括本来不该命中的）；\n"
         "关掉实体约束你会亲眼看到假命中：**问 A1002，答 A1001**。\n\n"
         "顺便试 `订单 B2043 到哪了？`：它相似度只有 0.33，连阈值都够不着 ——\n"
         "所以两道闸门是**互补**的：一个防「不相干」，一个防「差一点」。"),

        ("**让成本算错一次，并把它固定成一条断言。**\n\n"
         "把第 ② 节的 `call_cost` 里 `prompt_tokens / 1000` 改成 `/ 100`，重跑那一格。\n"
         "观察「手算 == 计量器」那一行变成什么。\n\n"
         "然后写一条 `assert`，把「手算与计量器一致」固定下来。",
         "差别会立刻显出来：`一致？: False`，而且成本差 10 倍。\n\n"
         "断言长这样（真实项目里就该这么写）：\n"
         "```python\n"
         "assert math.isclose(manual, meter.calls[0].cost, rel_tol=1e-9), '价目表算错了'\n"
         "```\n"
         "线上的价目表改错**不会报错**，只会悄悄多扣钱 —— 所以它必须被测试覆盖。"),

        ("**给路由加一条规则，并用评估集验证它。**\n\n"
         "现在的 `SIMPLE_HINTS` 里没有「总结」。加一条把「总结一下这段文字」路由到小模型的规则，"
         "重跑第 ⑥ 节观察分布变化。\n\n"
         "然后回答：你**凭什么**说这条规则是安全的？",
         "把 `SIMPLE_HINTS` 里加上 `总结`（注意别和 `COMPLEX_HINTS` 里的 `总结并` 打架）。\n\n"
         "「安全」的证明方式是第 10 章的做法：为它准备 10 条评估用例，\n"
         "对比大小模型的回答质量，确认没有一条退化。**凭感觉不算证明。**"),

        ("**把流式的 TTFT 收益算成钱。**\n\n"
         "假设「用户等待超过 1 秒就流失 5%」，每天 1000 次任务。\n"
         "算出把首字延迟从 2200ms 降到 700ms 能挽回多少用户、值多少钱。\n\n"
         "然后把它和成本收益放进同一张 ROI 表。",
         "2200ms → 700ms 意味着**不再触发 1 秒流失线** → 每天挽回约 50 次会话。\n\n"
         "关键不是这个数，而是「省了 ¥x」和「少流失 y 个用户」必须能放在一起比较，\n"
         "优化才有优先级 —— 否则你永远只会挑最容易改的那个去改。"),

        ("**进阶：给 `SemanticCache` 加 TTL 与写失效。**\n\n"
         "加一个 `ttl_ms` 参数（过期就不许命中），再加一个 "
         "`invalidate_entities(实体集合)` 方法。\n\n"
         "然后想清楚两个问题：哪些缓存**必须**失效？过期时长设多少？",
         "必须失效的是「任何被写操作影响到的实体」—— 比如用户改了收货地址，\n"
         "所有含这个订单号的缓存都要作废（哪怕还没到 TTL）。\n\n"
         "过期时长由业务决定：订单状态可以 5 分钟，商品价格可能 10 秒。\n"
         "**先问业务能容忍多旧的数据，再定 TTL。**"),
    ])

    checkpoint(nb, "12")

    return nb
