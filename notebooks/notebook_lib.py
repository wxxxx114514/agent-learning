"""notebook_lib —— 用**纯标准库**生成、执行并校验 Jupyter Notebook。

------------------------------------------------------------
为什么要自己写？
    课程有一个硬约束：**零第三方依赖**。但 Jupyter 生态（nbformat / nbclient /
    ipykernel）全是第三方包，而目标机器上连 `nbformat` 都没装。

    `.ipynb` 的本质其实非常简单：**就是一个 JSON 文件**（nbformat v4 规范）。
    所以我们完全可以用 `json` + `subprocess` 自己生成、自己执行、自己校验 ——
    顺便还能把"Notebook 文件到底是什么"这件事讲清楚。

    这本身也是 Agent 工程的一课：**搞清楚格式规范，比依赖某个库更可靠。**
------------------------------------------------------------

用法（见 scripts/build_notebooks.py）：
    nb = Notebook("第 01 章 · 最小 Agent 循环")
    nb.md("# 标题")
    nb.code("print('hello')")
    nb.save(Path("notebooks/01_xxx.ipynb"))
    ok, msg = nb.verify()          # 校验 JSON 合法性 + 执行所有代码单元
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# nbformat 的版本号。写死成 4.x —— Jupyter / VS Code / Colab 都认这个。
NBFORMAT_MAJOR = 4
NBFORMAT_MINOR = 5

# 代码单元的执行超时（秒）。Notebook 里的代码应该都很轻量；
# 超时通常意味着作者不小心把整个长 demo 塞进来了。
CELL_TIMEOUT = 90


def _source_lines(text: str) -> list[str]:
    """把一段文本切成 nbformat 要求的"行列表"。

    ★ nbformat 的 `source` 字段是 **list[str]**，每个元素是一行**且保留换行符**
      （最后一行除外）。这是手写 .ipynb 最容易错的地方：
      直接塞一个整字符串，Jupyter 打开会显示异常或直接报错。
    """
    text = textwrap.dedent(text).strip("\n")
    if not text:
        return []
    lines = text.split("\n")
    return [line + "\n" for line in lines[:-1]] + [lines[-1]]


@dataclass
class Notebook:
    """一个待生成的 Notebook。"""

    title: str
    cells: list[dict[str, Any]] = field(default_factory=list)
    kernel: str = "python3"

    # ---- 添加单元 -----------------------------------------------------
    def md(self, text: str) -> "Notebook":
        """加一个 Markdown 单元（讲解正文）。"""
        self.cells.append({
            "cell_type": "markdown",
            "metadata": {},
            "source": _source_lines(text),
        })
        return self

    def code(self, text: str, execute: bool = True) -> "Notebook":
        """加一个代码单元。

        execute=True  时，`verify()` 会真的运行它并把输出**嵌进 Notebook**
                      （这样读者不用运行就能看到结果，也能对照自己的输出）。
        execute=False 用于"故意会报错"的示例单元，或者需要外部 API Key 的单元。
        """
        self.cells.append({
            "cell_type": "code",
            "execution_count": None,
            "metadata": {"_execute": execute},
            "outputs": [],
            "source": _source_lines(text),
        })
        return self

    def raw(self, text: str) -> "Notebook":
        """加一个 Raw 单元（本课程基本用不到，留着备查）。"""
        self.cells.append({
            "cell_type": "raw",
            "metadata": {},
            "source": _source_lines(text),
        })
        return self

    # ---- 序列化 -------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """转成 nbformat v4 的 JSON 结构。

        注意 `metadata._execute` 是我们自己的私有标记，**必须在写出前删掉** ——
        否则会在 Jupyter 里显示成一堆莫名其妙的元数据（更严格的前端会报 schema 警告）。
        """
        clean_cells = []
        for cell in self.cells:
            c = json.loads(json.dumps(cell))       # 深拷贝，避免污染原对象
            if c["cell_type"] == "code":
                c["metadata"].pop("_execute", None)
            clean_cells.append(c)

        return {
            "cells": clean_cells,
            "metadata": {
                "kernelspec": {
                    "display_name": "Python 3",
                    "language": "python",
                    "name": self.kernel,
                },
                "language_info": {
                    "name": "python",
                    "file_extension": ".py",
                    "mimetype": "text/x-python",
                    "pygments_lexer": "ipython3",
                },
                "title": self.title,
            },
            "nbformat": NBFORMAT_MAJOR,
            "nbformat_minor": NBFORMAT_MINOR,
        }

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        # ensure_ascii=False：让中文在 .ipynb 里以可读形式存在（而不是 \uXXXX），
        # 这样用 git diff 看 Notebook 变更是人能读的。
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        return path

    # ---- 执行与校验 ---------------------------------------------------
    def verify(self, workdir: Path | None = None) -> tuple[bool, str]:
        """执行所有标记为 execute=True 的代码单元，把输出嵌回 Notebook。

        返回 (是否成功, 说明信息)。

        ★ 实现要点：把一个 Notebook 编译成**单个** Python 脚本，让所有单元
          共享同一个全局命名空间（这正是 Notebook 的语义：单元之间变量互通），
          然后用子进程跑一遍，再把输出按标记切回各个单元。

        ★★ 这里有一个非踩不可的坑：stdout 缓冲。
           最初的写法是"运行整段脚本，输出里插入标记，事后按标记切分"。
           实测**行不通** —— 子进程的 stdout 是块缓冲的，`print` 的内容
           会和标记的落盘顺序错开（常见现象：所有真实输出都堆到最后一个
           结束标记之后），切分结果全是空字符串。

           正确做法：在每个单元的边界**显式 flush**，并用一个 helper 打印标记：

               def _nb_mark(s):
                   sys.stdout.flush(); print(s); sys.stdout.flush()

           这样标记与输出就严格按真实执行顺序落盘，切分才准确。
           顺带一个好处：也能正确处理单元执行中途崩溃的情况
           （已 flush 的部分仍然保留）。
        """
        workdir = workdir or Path.cwd()
        exec_cells = [c for c in self.cells
                      if c["cell_type"] == "code" and c["metadata"].get("_execute", True)]
        if not exec_cells:
            return True, "无代码单元"

        # ★ 为什么不用 tempfile.TemporaryDirectory？
        #   系统临时目录在受限环境下可能不可写（本课程开发时就遇到过
        #   "PermissionError: ...\\Temp\\nbverify_xxx\\_all_cells.py"）。
        #   在**工作区内部**建临时目录最可靠，而且不依赖平台差异。
        #
        # ★★ 这里必须 resolve() 成绝对路径 —— 踩过这个坑：
        #   下面 subprocess.run(..., cwd=workdir) 会改变子进程的工作目录，
        #   如果我们传一个**相对路径**当脚本路径，子进程会把它按新 cwd
        #   再拼一次，于是变成 `.nbtmp13/.nbtmp13/.nbverify/_all_cells.py`
        #   这种不存在的路径，报 "can't open file"（exit 2）。
        #   传绝对路径就没这个问题。
        scratch = (Path(workdir) / ".nbverify").resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            script = scratch / "_all_cells.py"
            script.write_text(self._compile_exec_script(workdir), encoding="utf-8")

            try:
                proc = subprocess.run(
                    [sys.executable, str(script)],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=CELL_TIMEOUT, cwd=str(workdir),
                )
            except subprocess.TimeoutExpired:
                return False, f"执行超时（>{CELL_TIMEOUT}s）"

            stdout, stderr = proc.stdout or "", proc.stderr or ""
            if proc.returncode != 0:
                tail = "\n".join((stderr or stdout).strip().splitlines()[-12:])
                return False, f"执行失败 (exit {proc.returncode}):\n{tail}"

            self._distribute_outputs(stdout)
            return True, f"{len(exec_cells)} 个代码单元执行成功"
        finally:
            # 清理临时脚本，绝不在仓库里留垃圾
            try:
                for f in scratch.glob("*"):
                    f.unlink(missing_ok=True)
                scratch.rmdir()
            except OSError:
                pass

    # ---- 编译成一个可执行脚本 -----------------------------------------
    def _compile_exec_script(self, workdir: Path) -> str:
        """把 Notebook 编译成一个 .py 脚本，单元之间共享全局命名空间。

        每个单元的代码被放进独立的 `try/except`：
          · 这样我们可以精确定位"是哪个单元挂了"，报错信息比一整段 traceback 有用得多；
          · `SystemExit` 不受影响（它是 BaseException），有意退出仍会生效。
        """
        header = [
            "# 由 notebooks/notebook_lib.py 自动生成 —— 请勿手工编辑",
            "import sys as _nb_sys",
            "",
            "def _nb_mark(s):",
            "    _nb_sys.stdout.flush(); print(s); _nb_sys.stdout.flush()",
            "",
            f"_nb_sys.path.insert(0, r'{workdir.resolve()}')",
            "",
        ]
        body: list[str] = []
        for idx, cell in enumerate(self.cells):
            if cell["cell_type"] != "code" or not cell["metadata"].get("_execute", True):
                continue
            src = textwrap.dedent("".join(cell["source"]))
            body.append(f"_nb_mark('# ===CELL_BEGIN {idx}===')")
            body.append("try:")
            for line in src.split("\n"):
                body.append("    " + line if line.strip() else "")
            body.append("except Exception as _nb_e:")
            body.append("    import traceback as _nb_tb")
            body.append(f"    print('%%% 单元 {idx} 执行失败: ' "
                        f"+ type(_nb_e).__name__ + ': ' + str(_nb_e))")
            body.append("    _nb_tb.print_exc()")
            body.append("    raise SystemExit(1)")
            body.append(f"_nb_mark('# ===CELL_END {idx}===')")
            body.append("")
        return "\n".join(header + body)

    def _distribute_outputs(self, stdout: str) -> None:
        """把整段 stdout 按 BEGIN/END 标记切分，回填到各代码单元的 outputs。

        因为脚本里在每个单元边界都显式 flush 过（见 `_compile_exec_script`），
        标记与输出是**严格按执行顺序**落盘的，所以这里可以安全地
        用"BEGIN 之后、END 之前"作为每个单元的输出边界。
        """
        chunks: dict[int, list[str]] = {}
        current: int | None = None
        for line in stdout.splitlines(keepends=True):
            stripped = line.strip()
            if stripped.startswith("# ===CELL_BEGIN "):
                current = int(stripped.split()[2].rstrip("="))
                chunks.setdefault(current, [])
                continue
            if stripped.startswith("# ===CELL_END "):
                current = None
                continue
            if current is not None:
                chunks[current].append(line)

        exec_no = 0
        for idx, cell in enumerate(self.cells):
            if cell["cell_type"] != "code" or not cell["metadata"].get("_execute", True):
                continue
            exec_no += 1
            text = "".join(chunks.get(idx, [])).strip("\n")
            cell["execution_count"] = exec_no
            cell["outputs"] = ([{
                "name": "stdout",
                "output_type": "stream",
                "text": _source_lines(text),
            }] if text else [])


# ---------------------------------------------------------------------------
# 校验器：不依赖 Notebook 对象，直接读文件检查
# ---------------------------------------------------------------------------
def validate_ipynb(path: Path) -> tuple[bool, str]:
    """静态校验一个 .ipynb 文件是否是合法的 nbformat v4。

    检查项（每一条都对应一种"手写 .ipynb 常犯的错"）：
      1. 是合法 UTF-8 JSON
      2. 有 nbformat / nbformat_minor / cells / metadata
      3. nbformat == 4
      4. 每个 cell 有 cell_type 和 source
      5. source 是**行列表**（最常见的错误：直接写成一个字符串）
      6. code cell 必须有 outputs 和 execution_count
      7. cell_type 只能是 markdown / code / raw
    """
    if not path.exists():
        return False, "文件不存在"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"不是合法 JSON: {exc}"
    except UnicodeDecodeError as exc:
        return False, f"不是合法 UTF-8: {exc}"

    for key in ("nbformat", "nbformat_minor", "cells", "metadata"):
        if key not in data:
            return False, f"缺少顶层字段 {key}"
    if data["nbformat"] != NBFORMAT_MAJOR:
        return False, f"nbformat 应为 {NBFORMAT_MAJOR}，实际 {data['nbformat']}"
    if not isinstance(data["cells"], list) or not data["cells"]:
        return False, "cells 为空或不是列表"

    for i, cell in enumerate(data["cells"]):
        if "cell_type" not in cell:
            return False, f"第 {i} 个单元缺少 cell_type"
        if cell["cell_type"] not in ("markdown", "code", "raw"):
            return False, f"第 {i} 个单元 cell_type 非法: {cell['cell_type']}"
        if "source" not in cell:
            return False, f"第 {i} 个单元缺少 source"
        if isinstance(cell["source"], str):
            return False, (f"第 {i} 个单元的 source 是字符串，"
                           f"必须是行列表 list[str]（nbformat 规范要求）")
        if not isinstance(cell["source"], list):
            return False, f"第 {i} 个单元的 source 类型错误: {type(cell['source']).__name__}"
        if cell["cell_type"] == "code":
            if "outputs" not in cell:
                return False, f"第 {i} 个 code 单元缺少 outputs"
            if "execution_count" not in cell:
                return False, f"第 {i} 个 code 单元缺少 execution_count"

    n_md = sum(1 for c in data["cells"] if c["cell_type"] == "markdown")
    n_code = sum(1 for c in data["cells"] if c["cell_type"] == "code")
    return True, f"{n_md} 个讲解单元 / {n_code} 个代码单元"


def summarize(path: Path) -> dict[str, Any]:
    """返回一个 Notebook 的统计信息（用于生成目录页 / 报告）。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    cells = data["cells"]
    code = [c for c in cells if c["cell_type"] == "code"]
    return {
        "path": path,
        "cells": len(cells),
        "markdown": sum(1 for c in cells if c["cell_type"] == "markdown"),
        "code": len(code),
        "executed": sum(1 for c in code if c.get("execution_count") is not None),
        "with_output": sum(1 for c in code if c.get("outputs")),
        "title": data.get("metadata", {}).get("title", ""),
    }


# ---------------------------------------------------------------------------
# 版本新鲜度：生成产物是不是比源码旧？
# ---------------------------------------------------------------------------
def is_stale(ipynb: Path, source: Path) -> tuple[bool, str]:
    """判断一个 .ipynb 是不是比它的生成源码旧（= 该重新生成了）。

    ★ 为什么需要这个检查？
        同一个 Notebook 有两个"来源"：**生成器**和**你的编辑器**。

        如果我改了 `nb1_ch01.py` 并重新生成了 `.ipynb`，而你正好在 VS Code 里
        开着那个 `.ipynb`（尤其开了自动保存），切换窗口时就可能把
        **编辑器缓冲区里的旧内容写回磁盘**，静默覆盖掉刚生成的新版。

        这种覆盖特别阴险：文件还在、能打开、能跑，只是内容退回了旧版。
        没有检查的话，你可能几小时后才发现"之前讲的那个问题怎么又出现了"。

        有了它，任何一次 `check_structure.py` 都会把过期产物标红。

    返回 (是否过期, 说明)
    """
    if not ipynb.exists():
        return True, "产物不存在"
    if not source.exists():
        return False, "（源码不在，跳过）"
    t_out = ipynb.stat().st_mtime
    t_src = source.stat().st_mtime
    if t_src > t_out + 1:            # 1 秒容差，避免文件系统时间精度抖动
        return True, f"源码比产物新 {t_src - t_out:.0f} 秒 —— 需要重新生成"
    return False, ""


def stale_notebooks(root: Path | None = None) -> list[tuple[str, str]]:
    """用 build_notebooks 的注册表，列出所有"产物比源码旧"的 Notebook。

    返回 [(文件名, 说明)]。这个函数不抛异常 —— 检查工具本身不该把主流程搞崩。
    """
    import sys
    from pathlib import Path as _P

    root = root or _P(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from scripts.build_notebooks import REGISTRY
    except Exception:
        return []

    out: list[tuple[str, str]] = []
    for _ch, (_title, filename, module_name, _factory) in REGISTRY.items():
        source = root / "notebooks" / f"{module_name}.py"
        stale, why = is_stale(root / "notebooks" / filename, source)
        if stale and why != "（源码不在，跳过）":
            out.append((filename, why))
    return out
