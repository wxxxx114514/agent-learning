"""notebooks —— 课程的 Jupyter Notebook 版本（13 章）+ notebooks/README.md 的生成。

零第三方依赖：`.ipynb` 本质上就是一个 JSON 文件（nbformat v4），
我们用标准库直接生成、执行、校验（见 notebook_lib.py 的详细说明）。

生成方式：
    py scripts\\build_notebooks.py            # 生成全部 13 章
    py scripts\\build_notebooks.py --chapters 01 02
    py scripts\\build_notebooks.py --list
"""
