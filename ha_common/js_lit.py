"""Render Python values as compact JS literals for the tagged HTML data blocks.

Shared by the gas and grocery updaters (each previously carried its own copy).
The blocks are JS object literals with bare keys — deliberately NOT JSON — so
they diff cleanly against the hand-written originals in the HTML.

Usage::

    from ha_common.js_lit import js_lit

    js_lit({"regular": 5.653, "asOf": "2026-05-22"})
    js_lit(record, float_digits=4)   # grocery uses 4-digit floats
"""
from __future__ import annotations

import json


def js_lit(v, *, float_digits: int = 3) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(round(v, float_digits))
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[ " + ", ".join(js_lit(x, float_digits=float_digits) for x in v) + " ]"
    if isinstance(v, dict):
        return "{ " + ", ".join(
            f"{k}:{js_lit(val, float_digits=float_digits)}" for k, val in v.items()
        ) + " }"
    raise TypeError(f"unsupported type {type(v)}")
