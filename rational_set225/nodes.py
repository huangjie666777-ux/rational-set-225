"""Formula tree validation. Produces a normalized copy; never mutates input."""
from __future__ import annotations

import math
from typing import Any

MAX_DEPTH = 64
MAX_NODES = 5000
MAX_FONT_SIZE = 1000.0

NODE_TYPES = {"text", "row", "frac", "scripts", "sqrt", "paren"}
DELIMS = {"(": "parenleft", ")": "parenright", "[": "bracketleft", "]": "bracketright",
          "{": "braceleft", "}": "braceright", "|": "bar"}


class ValidationError(Exception):
    pass


def validate_font_size(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError("font_size must be a number")
    size = float(value)
    if not math.isfinite(size) or size <= 0:
        raise ValidationError("font_size must be finite and positive")
    if size > MAX_FONT_SIZE:
        raise ValidationError(f"font_size exceeds limit {MAX_FONT_SIZE}")
    return size


def validate_tree(tree: Any, glyph_coverage) -> dict:
    """Validate and normalize a formula tree. Returns a fresh dict."""
    counter = [0]
    node = _validate(tree, 0, counter, glyph_coverage)
    return node


def _validate(node: Any, depth: int, counter: list[int], has_glyph) -> dict:
    if depth > MAX_DEPTH:
        raise ValidationError("formula tree is too deep")
    counter[0] += 1
    if counter[0] > MAX_NODES:
        raise ValidationError("formula tree has too many nodes")
    if not isinstance(node, dict):
        raise ValidationError("node must be an object")
    ntype = node.get("type")
    if not isinstance(ntype, str) or ntype not in NODE_TYPES:
        raise ValidationError(f"unknown node type: {ntype!r}")

    def child(key, required=True):
        if key not in node:
            if required:
                raise ValidationError(f"{ntype} node missing '{key}'")
            return None
        return _validate(node[key], depth + 1, counter, has_glyph)

    if ntype == "text":
        value = node.get("value")
        if not isinstance(value, str) or not value:
            raise ValidationError("text node requires a non-empty string 'value'")
        for ch in value:
            if not has_glyph(ch):
                raise ValidationError(f"no glyph for character {ch!r}")
        return {"type": "text", "value": value}
    if ntype == "row":
        children = node.get("children")
        if not isinstance(children, list) or not children:
            raise ValidationError("row node requires a non-empty 'children' list")
        return {"type": "row",
                "children": [_validate(c, depth + 1, counter, has_glyph) for c in children]}
    if ntype == "frac":
        return {"type": "frac", "num": child("num"), "den": child("den")}
    if ntype == "scripts":
        sup = child("sup", required=False)
        sub = child("sub", required=False)
        if sup is None and sub is None:
            raise ValidationError("scripts node requires 'sup' and/or 'sub'")
        out = {"type": "scripts", "base": child("base")}
        out["sup"] = sup
        out["sub"] = sub
        return out
    if ntype == "sqrt":
        return {"type": "sqrt", "radicand": child("radicand")}
    if ntype == "paren":
        left = node.get("left", "(")
        right = node.get("right", ")")
        for d in (left, right):
            if not isinstance(d, str) or d not in DELIMS:
                raise ValidationError(f"unsupported delimiter {d!r}")
        return {"type": "paren", "child": child("child"), "left": left, "right": right}
    raise ValidationError(f"unknown node type: {ntype!r}")
