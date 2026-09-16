"""给 13 章的 README.md 加上"复习手册"定位说明。

背景
    课程现在有几种材料，读者不知道该先看哪个：

        notebooks/NN_xxx.ipynb          交互式 Notebook  ← 学新章节用它
        stages/stageNN_xxx/README.md    讲解文档         ← 复习/查阅用它
        py -m stages.stageNN_xxx.demo   命令行 demo      ← 看完整输出用它

    经过一轮重写，Notebook 已经改成"逐步推进"的讲法（先卡住 → 找工具 → 用一次），
    而 README 保留原来的章节式结构。两者内容一致，但**用途不同**。

    所以给每章 README 开头加一段定位说明，讲清"先看 Notebook，回来看这里查"。

用法：py scripts/add_readme_banner.py
可重复运行（已经有 banner 的会跳过）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ★ 必须调 setup_console()：Windows 控制台默认 GBK，打印 ✅ 这类字符会抛
#   UnicodeEncodeError（这不是理论 —— 这个脚本第一版就因为这个崩了）。
from core.console import setup_console  # noqa: E402

setup_console()

# 每章 -> (章号, 标题)。标题用于 banner 里的自检命令提示。
CHAPTERS: dict[str, tuple[str, str]] = {
    "stage01_agent_loop": ("01", "最小 Agent 循环"),
    "stage02_tools": ("02", "工具系统与 JSON Schema"),
    "stage03_react_prompt": ("03", "ReAct 提示工程"),
    "stage04_planning": ("04", "规划与任务分解"),
    "stage05_memory": ("05", "记忆与上下文工程"),
    "stage06_rag": ("06", "RAG 检索增强"),
    "stage07_reflection": ("07", "反思与自我修正"),
    "stage08_multi_agent": ("08", "多智能体协作"),
    "stage09_workflow": ("09", "工作流与状态机"),
    "stage10_evaluation": ("10", "评估与可观测性"),
    "stage11_guardrails": ("11", "安全护栏"),
    "stage12_cost_latency": ("12", "成本与延迟优化"),
    "stage13_production": ("13", "生产化部署"),
}

BANNER_MARK = "<!-- 材料定位 -->"

BANNER = """<!-- 材料定位 -->
> ## 📖 这份文档是**复习手册**，不是第一次学习用的
>
> 同一章有三种材料，**内容一致，用途不同**：
>
> | 材料 | 位置 | 什么时候用 |
> |---|---|---|
> | **① 交互式 Notebook** | `notebooks/{nb}.ipynb` | **第一次学** —— 一步步推导，每个代码单元都能单独运行 |
> | **② 本文件** | `stages/{dir}/README.md` | **复习 / 查阅** —— 结构化的原理与工程要点，方便搜索和跳读 |
> | **③ 命令行 demo** | `py -m stages.{dir}.demo` | **看完整输出** —— 或者用 `-s N` 只看某一节 |
>
> **建议路径**：先用 ① 学一遍（能看到每一步的真实输出），
> 之后忘了什么回来查 ②，想快速跑一遍用 ③。
>
> 学完的验收命令：`py scripts\\run_all_checks.py {ch}`

---
"""


def main() -> int:
    added = skipped = 0
    for dirname, (ch, title) in CHAPTERS.items():
        p = ROOT / "stages" / dirname / "README.md"
        if not p.exists():
            print(f"  跳过（不存在）：{dirname}/README.md")
            continue

        text = p.read_text(encoding="utf-8")
        if BANNER_MARK in text:
            print(f"  已有 banner，跳过：{dirname}")
            skipped += 1
            continue

        banner = BANNER.format(nb=f"{ch}_{dirname.split('_', 1)[1]}",
                               dir=dirname, ch=ch)

        # banner 插在第一个标题行之后（保留原来的 H1 标题在文档最上方）
        lines = text.split("\n")
        out: list[str] = []
        inserted = False
        for i, line in enumerate(lines):
            out.append(line)
            if not inserted and line.startswith("# "):
                out.append("")
                out.append(banner.rstrip("\n"))
                inserted = True
        if not inserted:                     # 万一开始不是 # 标题，就放最前面
            out = [banner.rstrip("\n")] + lines

        p.write_text("\n".join(out), encoding="utf-8")
        print(f"  ✅ 已加 banner：{dirname}/README.md  （第 {ch} 章 · {title}）")
        added += 1

    print()
    print(f"新增 {added} 个，跳过 {skipped} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main())
