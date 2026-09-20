# 练习工作区

**每章一个文件，题目和提示都已经抄在里面了 —— 不用再翻课程原文。**

| 文件 | 对应章节 |
|---|---|
| [`ex00_setup.py`](ex00_setup.py) | 00 · 模型和代码之间传什么 |
| [`ex01_agent_loop.py`](ex01_agent_loop.py) | 01 · 最小 Agent 循环 |
| [`ex02_tools.py`](ex02_tools.py) | 02 · 工具系统与 JSON Schema |
| [`ex03_react_prompt.py`](ex03_react_prompt.py) | 03 · ReAct 提示工程 |
| [`ex04_planning.py`](ex04_planning.py) | 04 · 规划与任务分解 |
| [`ex05_memory.py`](ex05_memory.py) | 05 · 记忆与上下文工程 |
| [`ex06_rag.py`](ex06_rag.py) | 06 · RAG 检索增强 |
| [`ex07_reflection.py`](ex07_reflection.py) | 07 · 反思与自我修正 |
| [`ex08_multi_agent.py`](ex08_multi_agent.py) | 08 · 多智能体协作 |
| [`ex09_workflow.py`](ex09_workflow.py) | 09 · 工作流与状态机 |
| [`ex10_evaluation.py`](ex10_evaluation.py) | 10 · 评估与可观测性 |
| [`ex11_guardrails.py`](ex11_guardrails.py) | 11 · 安全护栏 |
| [`ex12_cost_latency.py`](ex12_cost_latency.py) | 12 · 成本与延迟优化 |
| [`ex13_production.py`](ex13_production.py) | 13 · 生产化部署 |

共 14 个文件 / 69 个练习。

## 怎么用

```powershell
# 1. 打开对应章节的文件，在【我的代码】区域下面写

# 2. 运行看结果
py notebooks\practice\ex01_agent_loop.py

# 3. 验收本章（确认你没把原来通过的东西改坏）
py scripts\run_all_checks.py 01

# 4. 忘了某个名字是什么（Agent？ToolRegistry？）
py -m notebooks.nb_explain explain Agent
```

每个文件开头已经帮你做好了两件事，你不用管：

```python
sys.path.insert(0, ...)      # 让 import core.agent 之类能用
setup_console()              # Windows 控制台默认 GBK，这一步让中文不乱码
```

## 这个目录的特点

- **随便改、随便删**：它是你的草稿纸，不是课程材料
- **不会被覆盖**：`py scripts\build_notebooks.py` 只重新生成 `notebooks/*.ipynb`，不碰这里
- **不在检查范围内**：项目自带的 5 层检查（章节约 272 项验收 / 339 项结构 / 45 项文档 / 92 个测试 / 一致性审计）都只扫 `notebooks/*.ipynb` 和 `notebooks/nb_*.py`，**不递归进子目录** —— 所以你在里面写什么都不影响那 5 层检查的结果
- 写错了也不用清理，`git status` 里会正常显示为你的改动

## 题目来源

题目与提示是从各章 Notebook 源文件的 `exercises()` 里**自动提取**的，与课程原文逐字一致：

- `notebooks/NN_xxx.ipynb` 的「🏋️ 练习」节
- `stages/stageNN_xxx/README.md` 的「## 5. 练习」节

> 如果你觉得某道题不好或想加题，改上面那两处（改完跑 `py scripts\build_notebooks.py`），
> 然后手动把这里对应的段落也改一下即可。
