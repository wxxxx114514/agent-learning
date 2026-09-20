# 练习工作区

**每个练习一个文件。题目、可调用的东西、验证代码都已经写好了 —— 你只填中间那一段。**

共 **69 个练习**，覆盖第 00 ~ 13 章。

## 怎么用

```powershell
# 1. 打开对应章节的文件（见下面的索引）
# 2. 找到这一行：  # ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# 3. 删掉紧跟的 raise NotImplementedError(...)，写上你的答案

# 4. 运行看结果
py notebooks\practice\ch01_agent_loop\ex1_repeat_detect.py

# 5. 验收本章（确认你没把原来通过的东西改坏）
py scripts\run_all_checks.py 01

# 6. 忘了某个名字是什么（Agent？ToolRegistry？）
py -m notebooks.nb_explain explain Agent
```

> **没写的时候运行也不会报错** —— 会打印 `⬜ 还没写：…` 并正常退出（退出码 0）。
> 写完之后会打印验证结果和 `✅ 跑通了`。

## 每个文件长什么样

```
┌─ 文档串：题目原文 + 【已经给你了】什么 + 【怎么用】
│
├─ 环境          sys.path + setup_console()     ← 写好，不用改
├─ 给你的东西     导入 + 预先建好的对象          ← 写好，直接可用
│
├─ ↓↓↓ 这里是你唯一要写的地方 ↓↓↓               ← 唯一的空档（几行到十几行）
│
├─ ↑↑↑ 你的答案 ↑↑↑
├─ 验证 + main()                               ← 写好，不用改
└─ 运行入口
```

文件开头那两行已经帮你解决了两个坑：`sys.path`（否则 `import core.agent` 会失败）和
`setup_console()`（否则中文在 Windows 控制台乱码）。

---

## 全部 69 个练习

### 第 00 章 · 模型和代码之间传什么 —— `ch00_setup/`

| 文件 | 题目 |
|---|---|
| `ex1_multi_calls.py` | 让模型一次申请两个工具调用 |
| `ex2_broken_json.py` | 故意把 JSON 写坏，看程序怎么反应 |
| `ex3_time_budget.py` | 加一条总耗时保护 |
| `ex4_no_stop.py` | 去掉 `Final Answer:` 的判断，观察后果 |

### 第 01 章 · 最小 Agent 循环 —— `ch01_agent_loop/`

| 文件 | 题目 |
|---|---|
| `ex1_repeat_detect.py` | 给 `MiniAgent` 加「重复动作检测」 |
| `ex2_no_max_steps.py` | 去掉 `max_steps`，观察后果 |
| `ex3_time_budget.py` | 加一道「总耗时」护栏 |
| `ex4_friendly_error.py` | 让工具报错信息「像写给模型看的」 |
| `ex5_lying_model.py` | 注入一个会撒谎的模型 |

### 第 02 章 · 工具系统与 JSON Schema —— `ch02_tools/`

| 文件 | 题目 |
|---|---|
| `ex1_enum_guard.py` | 给校验器加 `enum` 约束并观察效果 |
| `ex2_drop_additional.py` | 故意拆掉 `additionalProperties` 防护 |
| `ex3_dos_guard.py` | 给 AST 白名单加 DoS 防护并验证 |
| `ex4_write_description.py` | 给 `count_words` 写一份好的 description |
| `ex5_injection_chain.py` | 模拟一次完整的注入攻击链 |

### 第 03 章 · ReAct 提示工程 —— `ch03_react_prompt/`

| 文件 | 题目 |
|---|---|
| `ex1_parse_custom_format.py` | 给解析器加一种新格式：`TOOL: name \| ARGS: {...}` |
| `ex2_silent_error.py` | 故意制造静默错误：把「协议违规」检测拆掉 |
| `ex3_model_compliance.py` | 测一测不同模型的「指令遵循能力」 |
| `ex4_thought_budget.py` | 给提示词加「思维预算」（Thought 最多 N 字） |
| `ex5_prompt_diff.py` | 实现提示词的差异对比工具 |

### 第 04 章 · 规划与任务分解 —— `ch04_planning/`

| 文件 | 题目 |
|---|---|
| `ex1_optional_step.py` | 给 Step 加 `optional` 字段：可选步骤失败不触发重规划 |
| `ex2_drop_dep_guard.py` | 拆掉护栏：把「依赖方向」校验去掉会怎样 |
| `ex3_compact_replan_prompt.py` | 让重规划的提示词更省 token |
| `ex4_parallel_steps.py` | 并行执行互不依赖的步骤 |
| `ex5_plan_mermaid.py` | 给 Plan 加一个 `to_mermaid()` 方法 |

### 第 05 章 · 记忆与上下文工程 —— `ch05_memory/`

| 文件 | 题目 |
|---|---|
| `ex1_pin_preemption.py` | 给钉住区加「优先级抢占」 |
| `ex2_summary_coverage.py` | 给摘要加一个「覆盖度自检」 |
| `ex3_pinning_overflow.py` | 破坏护栏：把「钉住」变成「什么都钉住」 |
| `ex4_density_eviction.py` | 换一种淘汰策略：按「重要性密度」淘汰 |
| `ex5_llm_summary.py` | 把规则摘要换成模型摘要（以及它失败时怎么办） |

### 第 06 章 · RAG 检索增强 —— `ch06_rag/`

| 文件 | 题目 |
|---|---|
| `ex1_my_corpus.py` | 换一份语料，亲手跑通「切块 → 建索引 → 检索」 |
| `ex2_mini_eval.py` | 做一份迷你评测集：先有数字，再做优化 |
| `ex3_break_refusal.py` | 拆掉拒答护栏，看模型会说什么 |
| `ex4_rerank.py` | 加一个重排（rerank）：BM25 召回 10 条，再精排出 3 条 |
| `ex5_hybrid_search.py` | 混合检索：BM25 + 字符级 Jaccard 加权融合 |

> ⚠️ ex4 / ex5 在本课的小语料上**不会涨分**（BM25 top-1 已经是 12/12）。
> 输出里会明确写出「这不是你写错了，瓶颈不在排序」。

### 第 07 章 · 反思与自我修正 —— `ch07_reflection/`

| 文件 | 题目 |
|---|---|
| `ex1_brakes_off.py` | 拆掉刹车：一个「永远不满意」的审查者有多贵 |
| `ex2_stricter_verifier.py` | 让验证器更严：结论里提到的商品必须出现在分项里 |
| `ex3_lesson_decay.py` | 给经验库加失效机制：教训也有寿命 |
| `ex4_repair_planner.py` | 把笼统批评「翻译」成具体修正（RepairPlanner） |
| `ex5_real_model.py` | 换一个真实模型：输出更脏，笼统的「再检查一遍」依然救不回来 |

### 第 08 章 · 多智能体协作 —— `ch08_multi_agent/`

| 文件 | 题目 |
|---|---|
| `ex1_round_limit.py` | 拆掉轮数上限，看账单怎么涨（必做） |
| `ex2_isolation_leak.py` | 让隔离「漏一点」，看哪几条断言变红（必做） |
| `ex3_compliance_node.py` | 加第四个专家（合规专家）：这一步真的需要模型吗？ |
| `ex4_trace_id.py` | 给 Envelope 加 `trace_id` 和 `elapsed_ms` |
| `ex5_task_design.py` | 设计一个「真的需要多智能体」的任务 |

### 第 09 章 · 工作流与状态机 —— `ch09_workflow/`

| 文件 | 题目 |
|---|---|
| `ex1_max_visits.py` | 把 max_visits 护栏拆掉，观察错误发生时的最大代价 |
| `ex2_review_note.py` | 在 human_review 里强制「修改意见必填」 |
| `ex3_consult_llm.py` | 把 handle_consult 换成模型，量一量代价 |
| `ex4_escalate.py` | 加一个「超时升级」节点 |
| `ex5_checkpoint_file.py` | 让检查点真的落盘（并亲眼看见「版本漂移」） |

### 第 10 章 · 评估与可观测性 —— `ch10_evaluation/`

| 文件 | 题目 |
|---|---|
| `ex1_business_case.py` | 给评估集加一条「你的业务」用例 |
| `ex2_break_guardrails.py` | 打破护栏，观察会发生什么 |
| `ex3_lost_regression.py` | 制造一次「未被发现的回归」 |
| `ex4_regex_scorer.py` | 把评分器换成「必须引用来源」 |
| `ex5_stability.py` | 给评估加上「稳定性」维度（进阶） |

### 第 11 章 · 安全护栏 —— `ch11_guardrails/`

| 文件 | 题目 |
|---|---|
| `ex1_break_policy.py` | 打破护栏，观察会发生什么 |
| `ex2_bypass_filter.py` | 让输入过滤失效 |
| `ex3_false_positive.py` | 制造一次误报事故 |
| `ex4_redaction_rule.py` | 给脱敏加一条规则 |
| `ex5_risk_score.py` | 把审计日志变成告警（进阶） |

### 第 12 章 · 成本与延迟优化 —— `ch12_cost_latency/`

| 文件 | 题目 |
|---|---|
| `ex1_break_cache_guard.py` | 打破缓存护栏，亲手做一次「假命中」事故 |
| `ex2_cost_assertion.py` | 让成本算错一次，并把它固定成一条断言 |
| `ex3_router_rule.py` | 给路由加一条规则，并用评估集证明它是安全的 |
| `ex4_streaming_roi.py` | 把流式的 TTFT 收益算成钱，并放进同一张 ROI 表 |
| `ex5_cache_ttl.py` | 给缓存加 TTL 与写失效（`invalidate_entities`） |

### 第 13 章 · 生产化部署 —— `ch13_production/`

| 文件 | 题目 |
|---|---|
| `ex1_memory_store.py` | 把检查点换成内存版，看「假崩溃」为什么没复现真实故障 |
| `ex2_idempotency_ttl.py` | 给幂等账本加 TTL，并想清楚 TTL 该设多长 |
| `ex3_break_rollback.py` | 破坏性实验：删掉恢复时的「倒回」，看工具调用怎么翻倍 |
| `ex4_overload_gate.py` | 把并发闸门的参数改一遍，并回答一个设计问题 |
| `ex5_breaker_probe.py` | 给熔断器补上「半开只放一个探测」，并自证它成立 |

---

## 这个目录的特点

| 特点 | 说明 |
|---|---|
| **随便改、随便删** | 它是你的草稿纸，不是课程材料 |
| **不会被覆盖** | `py scripts\build_notebooks.py` 只重新生成 `notebooks/*.ipynb`，不碰这里 |
| **不在检查范围内** | 项目自带的 5 层检查（272 项章节验收 / 339 项结构 / 45 项文档 / 92 个单元测试 / 一致性审计）只扫 `notebooks/*.ipynb` 和 `notebooks/nb_*.py`，**不递归进子目录** |
| **不依赖 Jupyter** | 全是普通 `.py`，VS Code 里直接运行即可 |

## 没有唯一答案的题怎么处理

有一类题没法「写一段代码就完事」（比如「这样改会花掉多少钱」「这一步真的需要模型吗」）。处理方式是：

- 给一段**可运行的小实验**，跑完把现象直接打印出来
- 留一个 `# 写下你的结论：` 的空位（填字符串或函数返回值）
- 结论留空时同样打印 `⬜ 还没写` 并退出 0，不会卡住你

## 题目来源

题目与提示来自各章课程原文（改这里不会影响课程）：

- `notebooks/NN_xxx.ipynb` 的「🏋️ 练习」节 ← 源文件是 `notebooks/nb*.py` 里的 `exercises()`
- `stages/stageNN_xxx/README.md` 的「## 5. 练习」节

> 想改题目本身，要改上面那两处（改完跑 `py scripts\build_notebooks.py`），
> 再手动同步这里对应的文件。目录名 `chNN_xxx` 与章节一一对应，
> 文件名里的 `exK_` 就是该章练习的序号。
