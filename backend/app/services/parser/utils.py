"""parser 包内共享的小工具。

`col_to_idx` 在 `excel_parser`（读 schema）与 `template_writer`（按 schema 写表头）两处
都要用，提升到公共模块避免跨模块依赖私有函数（带下划线前缀）。
"""
from __future__ import annotations


def col_to_idx(col_letter: str) -> int:
    """Excel 列字母（A、B、…、AA、AB、…）→ 1-based 列号。

    输入大小写不敏感。"AA" → 27, "AB" → 28。

    非字母输入直接 ValueError 而不是返回静默错误值：col_to_idx("") 返回 0、
    `col_to_idx("A1")` 返回负数会让调用方 `raw_row[idx]` 索引到错误列且不报错，
    schema yaml 拼错时定位极为困难。
    """
    if not col_letter or not col_letter.isalpha():
        raise ValueError(
            f"col_to_idx: 期望非空字母字符串，实际 {col_letter!r}"
        )
    result = 0
    for ch in col_letter.upper():
        result = result * 26 + (ord(ch) - ord("A") + 1)
    return result
