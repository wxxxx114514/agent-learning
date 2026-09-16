# 课程 Jupyter Notebook（13 章 + 课前准备）

> 这是 `.py` + Markdown 版本之外的**第三种学习形态**：交互式 Notebook。
> 三种版本内容一致、共享同一套 `core/` 框架和同一套 `run_checks()` 断言，
> **不会出现"文档说的和代码不一致"**。

---

## 为什么会有 Notebook 版本

| 版本 | 位置 | 最适合 |
|---|---|---|
| **Notebook** | `notebooks/NN_xxx.ipynb` | 边读边改、随手做实验、看每一步输出 |
| **讲解文档** | `stages/stageNN_xxx/README.md` | 通读原理、复习、查工程要点 |
| **可运行 demo** | `py -m stages.stageNN_xxx.demo` | 看完整输出、`--section` 逐节跑 |

Notebook 版本的**独有价值是交互性**：每章都有"改一个数字再跑一次"的单元，
以及"先把护栏拆掉，看它怎么出错"的对照实验。
读十遍"这样做不安全"，不如亲眼看到一次注入攻击真的成功。

---

## 打开方式

本课程**零第三方依赖**，但 Jupyter 本身是第三方工具，需要你按需安装：

```powershell
# 任选一种
pip install jupyterlab        # 功能最全
pip install notebook          # 经典界面
```

没有 Jupyter 也能用：

- **VS Code**：装了 Python 扩展后可直接打开 `.ipynb`（推荐，最省事）
- **PyCharm**：专业版自带 Notebook 支持
- 任何支持 nbformat v4 的编辑器

然后：

```powershell
jupyter lab notebooks/          # 在 notebooks 目录启动
```

---

## 章节列表

| 文件 | 章节 | 说明 |
|---|---|---|
| `00_setup.ipynb` | 课前准备 | 环境自检、三种版本怎么选、学习心态 |
| `01_agent_loop.ipynb` | 第 01 章 最小 Agent 循环 | Agent 的骨架：循环 + 工具 + 历史 |
| `02_tools.ipynb` | 第 02 章 工具系统与 JSON Schema | 模型输出不可信 → 校验放在执行之前 |
| `03_react_prompt.ipynb` | 第 03 章 ReAct 提示工程 | 格式契约的读者是解析器 |
| `04_planning.ipynb` | 第 04 章 规划与任务分解 | 计划是假设，执行是验证 |
| `05_memory.ipynb` | 第 05 章 记忆与上下文工程 | 有限预算下保留最高价值的信息 |
| `06_rag.ipynb` | 第 06 章 RAG 检索增强 | 检索质量决定上限 |
| `07_reflection.ipynb` | 第 07 章 反思与自我修正 | 没有具体修正的反思只是废话 |
| `08_multi_agent.ipynb` | 第 08 章 多智能体协作 | 分工、隔离、仲裁 |
| `09_workflow.ipynb` | 第 09 章 工作流与状态机 | 能用确定性代码解决的，绝不用模型 |
| `10_evaluation.ipynb` | 第 10 章 评估与可观测性 | 没有评估集的优化都是玄学 |
| `11_guardrails.ipynb` | 第 11 章 安全护栏 | 模型输出永远是不可信输入 |
| `12_cost_latency.ipynb` | 第 12 章 成本与延迟优化 | 先测量 → 再缓存 → 再减量 → 最后换模型 |
| `13_production.ipynb` | 第 13 章 生产化部署 | 有状态长任务 vs 无状态短连接 |

---

## 使用建议

1. **从 `00_setup.ipynb` 开始** —— 它会确认你的环境能跑通全部 13 章，
   免得学到第 7 章才发现环境有问题。
2. **从上往下依次运行**（`Shift+Enter`）。Notebook 的代码单元**共享变量**，
   后面的单元依赖前面的定义。如果你中途重启了内核（Kernel → Restart），
   请从该 Notebook 开头重新往下跑。
3. **每个代码单元都已经执行过**，输出是真实结果（不是编的）。
   你的输出如果和它不同，说明环境或版本有差异，值得留意。
4. **不要跳过"改一个数字"的单元** —— 那才是 Notebook 相比 README 的价值所在。

---

## 这些 Notebook 是怎么来的（工程细节）

`.ipynb` 本质上**就是一个 JSON 文件**（nbformat v4 规范）。
本课程坚持零第三方依赖，所以在没有 `nbformat` / `jupyter` 的机器上，
我们用标准库自己生成、自己执行、自己校验：

```powershell
py scripts\build_notebooks.py              # 生成全部 13 章（会真的执行每个代码单元）
py scripts\build_notebooks.py --chapters 01 02
py scripts\build_notebooks.py --list       # 列出章节与生成状态
py scripts\build_notebooks.py --check      # 只校验已生成的 .ipynb 是否合法
```

生成过程做三件事：

1. 把每章的代码单元**编译成一个 `.py` 脚本**（单元之间共享全局命名空间，
   这正是 Notebook 的语义）；
2. 用子进程跑一遍，**把真实输出嵌回**对应的代码单元 ——
   所以 Notebook 里不会出现"示例输出是手写的"这种情况；
3. 校验产物是否符合 nbformat v4（`source` 必须是**行列表**，
   这是手写 `.ipynb` 最容易错的地方）。

实现细节（包括踩过的两个真实的坑：**系统临时目录不可写**、
**stdout 缓冲导致输出与标记错位**）都写在 `notebook_lib.py` 的注释里 ——
那份注释本身就是一份"怎么用标准库做 Notebook 工具链"的教材。

> **反过来想**：这里也是 Agent 工程的一课 ——
> 搞清楚格式规范，比依赖某个库更可靠。当你需要让 Agent 产出结构化文件时，
> 能自己读懂并生成目标格式，比"找个库试试"强得多。

---

## 与其它材料的一致性

改动 `core/` 或某一章之后，请按顺序验证：

```powershell
py scripts\build_notebooks.py --check      # Notebook 是否仍合法
py scripts\check_structure.py              # 章节材料是否齐全
py scripts\run_all_checks.py               # 271 项验收标准是否仍通过
```
