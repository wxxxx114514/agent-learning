r"""第 02 章 · 练习 1 / 5 · 给校验器加 `enum` 约束并观察效果

【要做什么】
  给校验器加 `enum` 约束并观察效果。

  给 `lookup_order` 加一个可选参数 `format`，取值只能是 `text` 或 `json`。

  然后分别传 `json`、`xml`、`JSON`，看校验器返回什么。

  思考：为什么 `JSON`（大写）应该被拒绝？

【已经给你了】
  · `ORDER_SCHEMA`        —— `lookup_order` 的 JSON Schema，`format` 那一格留给你填
  · `validate_schema`     —— 本章的 JSON Schema 子集校验器（返回错误列表，空列表 = 通过）
  · `reg`                 —— 已经注册好 `lookup_order` 的 ToolRegistry
  · `lookup_order`        —— 工具函数本身（注意它已经能接受 `format` 参数）
  · `try_call(fmt)`       —— 帮你走一遍「校验 -> 执行」，返回 (ok, 文本)

【怎么用】
  1. 找到下面标 TODO 的地方，删掉 raise，写上你的答案
  2. 运行：py notebooks\practice\ch02_tools\ex1_enum_guard.py
  3. 验收本章：py scripts\run_all_checks.py 02
"""

# ── 环境（不用改）──────────────────────────────────────────
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))   # ← 注意是 3

from core.console import setup_console  # noqa: E402

setup_console()

# ── 给你的东西（不用改）────────────────────────────────────
import json                                                   # noqa: E402

from core.tool import ToolRegistry, ToolSpec, validate_schema # noqa: E402

ORDER_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {"type": "string", "pattern": "(?i)^[a-z]{0,2}\\d{3,}$"},
        # TODO ① ── 在这里加一个可选参数 format：类型 string，取值只能是 "text" 或 "json"
        #   提示：{"type": "string", "enum": ["text", "json"], "description": "返回格式"}
        # ↓↓↓ 在下面这一行里加上你的答案 ↓↓↓
    },
    "required": ["order_id"],
    "additionalProperties": False,
}


def lookup_order(order_id: str, format: str = "text"):
    """查订单。参数 order_id 形如 A1001；format 取 text / json。"""
    table = {"A1001": {"status": "已发货", "carrier": "顺丰", "tracking": "SF1234567890"}}
    key = order_id.upper()
    if key not in table:
        raise ValueError(f"订单 {key} 不存在。已知示例：{sorted(table)}")
    data = {"order_id": key, **table[key]}
    if format == "json":
        return json.dumps(data, ensure_ascii=False)
    return "，".join(f"{k}={v}" for k, v in data.items())


reg = ToolRegistry()
try:
    reg.register(ToolSpec(name="lookup_order", description="根据订单号查询订单状态。",
                          parameters=ORDER_SCHEMA, func=lookup_order))
except ValueError as exc:                 # 你还没给 format 加 schema 时不会走到这里
    print("注册失败：", exc)


def try_call(fmt: str):
    """传一个 format 值，返回 (是否通过校验, 校验错误 或 工具结果)。"""
    errors = validate_schema({"order_id": "A1001", "format": fmt}, ORDER_SCHEMA)
    if errors:
        return False, " / ".join(errors)
    r = reg.execute("lookup_order", {"order_id": "A1001", "format": fmt})
    return r.ok, (r.content if r.ok else r.error)


# ===========================================================================
# ↓↓↓ 这里是你唯一要写的地方 ↓↓↓
# ===========================================================================
def why_reject_uppercase() -> str:
    """TODO ② ── 写下你的结论：为什么 `JSON`（大写）应该被拒绝？

    提示（想清楚再写，这里没有标准答案，但要说清代价）：
      · `enum` 是**精确匹配**：`"JSON" != "json"`
      · 如果为了"方便"在校验前统一转小写，会发生什么？
        —— 校验通过的值和函数真正收到的值**不是同一个**了
      · 再想一层：如果拿它当字典的键、文件名、SQL 片段用，大小写混淆会有什么后果？

    返回你的一句话结论（写 20 个字以上，不许返回空串）。
    """
    # ↓↓↓ 把下面这行删掉，写上你的答案 ↓↓↓
    raise NotImplementedError("练习 1 · TODO ②  why_reject_uppercase 还没有写")
    # ↑↑↑ 你的答案 ↑↑↑


# ===========================================================================
# ↑↑↑ 你的答案 ↑↑↑    下面是验证，不用改
# ===========================================================================
def main() -> int:
    print("=" * 68)
    print("  第 02 章 · 练习 1 · enum 精确匹配")
    print("=" * 68)

    fmt_schema = ORDER_SCHEMA.get("properties", {}).get("format")
    if not fmt_schema:
        print("\n⬜ 还没写：练习 1 · TODO ①  给 ORDER_SCHEMA 加一个 format 参数还没有写")
        return 0
    if fmt_schema.get("enum") != ["text", "json"]:
        print(f"\n❌ format 的 enum 应该是 ['text', 'json']，现在是 {fmt_schema.get('enum')!r}")
        return 1

    print(f"\n  format 的 schema = {fmt_schema}")
    print("\n  三种取值分别走一遍「校验 -> 执行」：")
    for fmt in ("json", "xml", "JSON"):
        passed, detail = try_call(fmt)
        mark = "通过" if passed else "拦住"
        print(f"    format={fmt!r:<8} [{mark}]  {detail[:78]}")

    ok_json, _ = try_call("json")
    bad_xml, err_xml = try_call("xml")
    bad_upper, err_upper = try_call("JSON")
    if not ok_json:
        print("\n❌ 'json' 应该通过校验")
        return 1
    if bad_xml or not ("必须" in err_xml or "enum" in err_xml):
        print("\n❌ 'xml' 应该被 enum 拦住，并给出可读的错误信息")
        print(f"   现在返回：{err_xml[:90]}")
        return 1
    if bad_upper:
        print("\n❌ 'JSON' 也应该被拦住 —— enum 是精确匹配，不认大小写变体")
        return 1

    try:
        conclusion = why_reject_uppercase()
    except NotImplementedError as exc:
        print(f"\n⬜ 还没写：{exc}")
        return 0
    except Exception as exc:
        print(f"\n❌ 报错了：{type(exc).__name__}: {exc}")
        return 1

    print(f"\n  你的结论（{len(str(conclusion))} 字）：")
    for line in str(conclusion).splitlines():
        print("      " + line)
    if len(str(conclusion).strip()) < 20:
        print("\n❌ 结论太短了 —— 把「精确匹配」和「转小写之后校验值与实际值不一致」说清楚")
        return 1

    print("\n✅ 跑通了")
    print("   ★ 要点：enum 是**精确匹配**。想允许大小写，要么把两种写法都列进 enum，")
    print("     要么在**校验之前**统一规范化 —— 但校验过的值必须就是函数收到的值。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
