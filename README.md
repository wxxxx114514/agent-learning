# Agent 开发 · 逐步细致学习仓库

> **目标**：从零开始，**一步一步**把「AI Agent 开发」的知识与技术吃透。
>
> **特点**：**零第三方依赖**（纯 Python 标准库）+ **可离线复现**（内置 Mock 模型）+ **每步都能跑**。

---

## 🤖 人机分工声明

**起因**：我要学 Agent 开发，先让 AI 生成了一份材料，**但我看不懂** ——
它默认我已经掌握前置知识，直接给结论、给代码，我不知道那些符号从哪来。

所以**我用我自己的思路让 AI 重新写了一份**：代码是结论不是起点，
每个知识点必须在"我正好需要它"的那一刻才出现（规则见 [`TEACHING_CONTRACT.md`](TEACHING_CONTRACT.md)）。

| 环节 | 谁做的 |
|---|---|
| 第一版材料（大纲 + 讲解 + 代码） | AI 生成 |
| **判断"看不懂"、给出重写思路与讲法规则** | **我** |
| 内容取舍、返工要求、验收标准 | **我** |
| 重写后的讲解正文与代码措辞 | AI（DSH / DeepSeek Harness）执行 |

> **这份声明的作用是说明"材料为什么长这样"**，并标清哪些部分是我自己的判断。
> 本仓库为**个人学习留存**，不主张版权，也未授权他人使用。

---

## 📖 从这里开始

**第一次来请读 [`CHAPTERS.md`](CHAPTERS.md)** —— 按章节组织的导读，
由浅入深，每一章告诉你「学完能做什么」以及对应的材料在哪。

课程有**三种版本的材料，内容一致，用途不同**：

| 版本 | 位置 | 什么时候用 |
|---|---|---|
| **① Jupyter Notebook** | [`notebooks/`](notebooks/README.md) | **第一次学** —— 一步步推导，每格都能单独运行 |
| **② 讲解文档** | `stages/stageNN_xxx/README.md` | **复习 / 查阅** —— 结构化原理与工程要点，方便搜索 |
| **③ 可运行 demo** | `py -m stages.stageNN_xxx.demo` | **看完整输出** —— 或 `-s N` 只看某一节 |

> **别把 ② 当第一遍教材**：它是按主题整理的复习手册，
> 不像 Notebook 那样从"现在卡在哪"一步步推。学习路径见下面的「学习法」。

想直接动手，按下面三步走：

```powershell
# 1) 看环境（Python 3.10+ 即可，无需 pip 安装任何东西）
py scripts\check_env.py

# 2) 跑第一个 Agent（离线 Mock 模型，不需要 API Key）
py -m stages.stage01_agent_loop.demo

# 3) 跑全部自检，确认 13 章材料都就绪
py scripts\run_all_checks.py
```

> **想用 Notebook 版本？** 需要先装 Jupyter（第三方工具，课程本身零依赖）：
> `pip install jupyterlab`，然后 `jupyter lab notebooks/`。
> 详见 [`notebooks/README.md`](notebooks/README.md)。
> 用 VS Code 的话可以直接打开 `.ipynb`，不需要额外安装。

> Windows 上如果 `python` 命令指向微软商店占位符，请统一使用 `py`。

### 想接真实大模型？

```powershell
# 任选一个，设置环境变量后加 --real 即可（用标准库 urllib，零依赖）
$env:DEEPSEEK_API_KEY = "sk-xxx"
py -m stages.stage01_agent_loop.demo --real
```

支持 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `MOONSHOT_API_KEY` / `DASHSCOPE_API_KEY` /
`ZHIPU_API_KEY` / `SILICONFLOW_API_KEY`，以及自定义 `*_BASE_URL`（含 Ollama 本地服务）。

**没配 Key 也能学完全部课程** —— 因为内核逻辑与模型无关，这正是第 01 章的第一课。

---

## 🗺 学习路径（13 章）

```
                       ┌─────────────────────────────────────┐
   第一层：把 Agent 跑起来 │ 01 最小循环  02 工具系统  03 ReAct  │
                       └─────────────────────────────────────┘
                                      ↓
                       ┌─────────────────────────────────────┐
   第二层：让它变聪明     │ 04 规划  05 记忆  06 RAG  07 反思   │
                       └─────────────────────────────────────┘
                                      ↓
                       ┌─────────────────────────────────────┐
   第三层：让它可靠       │ 08 多智能体  09 工作流状态机        │
                       └─────────────────────────────────────┘
                                      ↓
                       ┌─────────────────────────────────────┐
   第四层：让它能上线     │ 10 评估可观测  11 安全护栏          │
                       │ 12 成本延迟    13 生产化部署        │
                       └─────────────────────────────────────┘
```

**为什么是这个顺序？** 因为每一层都在解决上一层**暴露出来的问题**：

| 章 | 上一章暴露的问题 | 本章的解法 |
|---|---|---|
| 01 | 模型没手没眼，只能瞎猜 | 给它一个循环和工具 |
| 02 | 裸调工具会崩、会被注入 | 工具规格 + Schema 校验 + 沙箱 |
| 03 | 模型乱调工具、格式写崩 | ReAct 提示工程 + 健壮解析 + 回灌纠错 |
| 04 | 复杂任务一步做完就崩 | 规划与任务分解 + 重规划 |
| 05 | 历史无限增长，窗口爆掉 | 记忆分层与上下文压缩 |
| 06 | 它不知道你的私有知识 | RAG 检索增强 |
| 07 | 它错了自己不知道 | 反思与自我修正 |
| 08 | 单 Agent 什么都干不好 | 多智能体分工协作 |
| 09 | 协作太随机、不可控 | 工作流与状态机 |
| 10 | 改了提示词不知变好还是变坏 | 评估与可观测性 |
| 11 | 它会被诱导着干坏事 | 安全护栏 |
| 12 | 太贵、太慢 | 成本与延迟优化 |
| 13 | 本地能跑 ≠ 线上能跑 | 生产化部署 |

> **不要跳章** —— 跳章会让你在后面"知其然不知其所以然"。
>
> 详见 [`ROADMAP.md`](ROADMAP.md)（含每章**验收标准**，做到才算学会）。

---

## 📂 目录结构

```
agent-learning/
├─ CHAPTERS.md               # ★ 分章节导读（由浅入深，建议从这里开始）
├─ README.md                 # 本文件：总览
├─ ROADMAP.md                # 13 章路线图 + 每章验收标准
├─ NOTES.md                  # 学习笔记（边学边记，含复盘模板）
├─ core/                     # 我们自己的「迷你 Agent 框架」（手写，不黑盒）
│   ├─ llm.py                # 统一模型接口（依赖倒置）
│   ├─ mock_llm.py           # 离线 Mock 模型（脚本化 / 规则化 / 4 种捣乱模型：抽风、格式崩、幻觉工具、死循环）
│   ├─ real_llm.py           # 真实模型适配器（OpenAI 兼容协议，urllib 实现）
│   ├─ message.py            # 消息 / 会话数据结构
│   ├─ parser.py             # 模型文本 → 思考 + 工具调用（分级降级解析）
│   ├─ tool.py               # 工具规格、JSON Schema 校验、注册表、内置工具
│   ├─ prompts.py            # 提示词构建器（ReAct / Function Calling）
│   ├─ agent.py              # Agent 主循环（本框架的心脏）
│   ├─ console.py            # 教学输出工具（UTF-8 修复 + 排版原语）
│   └─ errors.py             # 统一异常体系（错误分类决定恢复策略）
├─ stages/                   # 13 章课程代码（每章可独立运行）
│   ├─ stage01_agent_loop/   # README.md 讲解 + demo.py 可运行演示
│   ├─ stage02_tools/
│   ├─ …
│   └─ stage13_production/
├─ notebooks/                # 13 章 Jupyter Notebook（交互式版本）
│   ├─ README.md             #  Notebook 使用说明 + 生成原理
│   ├─ notebook_lib.py       #  纯标准库的 .ipynb 生成/执行/校验工具
│   ├─ nb_blocks.py          #  共享排版积木（保证 13 章风格一致）
│   ├─ nb_explain.py         #  explain() 查询工具（随时查任意 API）
│   ├─ nb_lint.py            #  自包含检查：找出"单独跑会 NameError"的单元
│   ├─ nb0_foundation.py     #  第 00 章内容定义
│   ├─ nb1_ch01.py …         #  第 01~13 章内容定义（一章一个文件）
│   └─ NN_xxx.ipynb          #  生成产物（可直接打开）
├─ tests/                    # 框架级单元测试（92 个，不联网）
└─ scripts/                  # 环境检查、一键自检、Notebook 生成
    ├─ check_env.py          # 环境自检（Python 版本 / 编码 / API Key）
    ├─ run_all_checks.py     # 一键跑遍 13 章的验收标准
    ├─ check_structure.py    # 结构校验（文件齐全？契约方法在不在？产物是否过期？）
    ├─ check_docs.py         # 文档校验（链接有效？命令能跑？Notebook 合法？）
    ├─ audit_consistency.py  # 一致性审计（找出文档里和现状不符的描述）
    ├─ build_notebooks.py    # 生成 13 章 Notebook（会真的执行每个代码单元）
    ├─ rebuild_all.py        # 出问题时一键重新生成
    └─ add_readme_banner.py  # 给各章 README 加「复习手册」定位说明（可重复运行）
```

---

## 🔁 学习法：学新章节用 Notebook，复习用 README

**第一步：打开 Notebook 学一遍**（能看到每一步的真实输出）

```
notebooks/00_setup.ipynb            ← 从这一章开始（讲模型和代码之间传什么）
notebooks/NN_xxx.ipynb              ← 第 NN 章
```

每个 Notebook 的结构都是「先卡住 → 所以我需要一个…… → 它的用法 → 立刻用一次」，
而且**每个代码单元都能单独运行**（复制出去也不报 NameError）。

**第二步：动手改。** Notebook 里标了 `# ← 试着改这里` 的单元，
改个数字/参数再跑一次 —— 这是 Notebook 相比文档唯一的价值。

**第三步：验收。**

```powershell
py scripts\run_all_checks.py NN     # 这一章的教学标准是否满足
```

**复习时再看 `README.md`** —— 它是结构化整理的原理与工程要点，方便搜索和跳读，
但讲法是章节式的，不如 Notebook 那样一步步推导。

> 每章都有一句**「一句话本质」**。学完能自己复述出来，才算真懂。

### 常用命令

```powershell
py scripts\run_all_checks.py              # 跑全部 13 章的验收标准
py scripts\run_all_checks.py 01 02 03     # 只跑指定章
py scripts\run_all_checks.py --quiet      # 只打印失败项
py scripts\run_all_checks.py --list       # 列出已安装章节
py -m stages.stage05_memory.demo --list   # 列出某一章的所有小节
py -m stages.stage05_memory.demo -s 3     # 只看第 3 节
py -m stages.stage05_memory.demo --check  # 只跑某一章的自检
py scripts\build_notebooks.py --list      # 列出 Notebook 生成状态
```

> **提示**：想看某一章的完整讲解输出，直接 `py -m stages.stageNN_xxx.demo`；
> 加 `--section N` 可以只看其中一小节，避免一次刷屏。

---

## ✅ 为什么这份材料值得信任

- **每章都有可执行的验收标准**，不是空头勾选框。`scripts/run_all_checks.py`
  会自动跑遍全部 13 章的断言（**272 项检查，全部通过**）；另有 339 项结构检查、
  45 项文档与 Notebook 检查、**92 个框架单元测试**（含"把每个代码单元丢进
  独立子进程真跑一遍"这一条硬测试）。
- **三种形态内容一致**：Jupyter Notebook、讲解文档、可运行 demo 共享同一套
  `core/` 框架与同一套断言。**14 个 Notebook 共 571 个讲解单元 + 145 个代码单元，
  每个代码单元都真的执行过、且都能单独运行**（`notebooks/nb_lint.py` 机器校验，
  未声明依赖合计 0）。
- **一致性有专人盯**：`scripts/audit_consistency.py` 会扫出过期路径、对不上的
  统计数字、旧流程指示等（**总数 / 每章项数 / 测试数 / Notebook 数**这几类
  是机器在守；措辞类的前后一致仍需人工复核）。
- **尽量避免手写输出**：README 里的示例输出是从实际运行中复制的。
  各章自检项数已逐章核对；整体数字由 `scripts/audit_consistency.py` 校验，
  跑它即可发现过期统计。
- **零第三方依赖**，任何装了 Python 3.10+ 的机器都能跑，不需要联网。
- **离线可复现**：内置 Mock 模型让每个实验都是确定性的，同一个输入永远同一个输出。
- **不做假绿**：自检器会明确报出材料不完整的章节，而不是把它们从清单里跳过。
  （这个设计来自一次真实的踩坑 —— 见 `scripts/run_all_checks.py` 里 `discover()` 的注释。）

### 四层验证

```powershell
py scripts\check_structure.py            # ① 结构：文件齐全？能 import？契约方法在不在？
py -m unittest discover -s tests -t .    # ② 框架：core/ 内核有没有坏？
py scripts\run_all_checks.py             # ③ 课程：每一章的验收标准是否真的通过？
py scripts\check_docs.py                 # ④ 文档：链接有效？命令能跑？材料与 Notebook 齐全？
```

四层各管一段：**结构**坏了会让动态检查整个崩掉；**框架**坏了所有章节一起错；
**课程**坏了说明某一章的教学目标没达成；**文档**坏了读者会点到 404 或复制到跑不通的命令。
分开跑，排查成本低得多。

Notebook 是**生成产物**，改完内容定义后要重新生成：

```powershell
py scripts\build_notebooks.py            # 会真的执行每个代码单元，把真实输出嵌进去
py scripts\build_notebooks.py --check    # 只校验产物是否仍是合法 nbformat v4
```


---

## 进度追踪

见 [`CHAPTERS.md`](CHAPTERS.md) 顶部的进度表，或 [`ROADMAP.md`](ROADMAP.md) 末尾的清单。

## 附录

- 附录 A · 框架对照（LangGraph / MCP / 各家产品 → 你手写过的对应物）
- 附录 B · 常见误区速查
- 附录 C · 术语表（中英对照）

以上见 [`ROADMAP.md`](ROADMAP.md) 末尾。
