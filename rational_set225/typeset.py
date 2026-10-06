"""Convert a validated rational-expression tree into the existing layout tree.

The original expression is shown faithfully (no substitution of reduced
results): fractions, multiplication/division and powers are preserved and
parentheses are inserted only where precedence or a unary minus requires them.
"""
from __future__ import annotations

MINUS = "\u2212"
CDOT = "\u00b7"


def _text(s: str) -> dict:
    return {"type": "text", "value": s}


def _row(items: list[dict]) -> dict:
    return {"type": "row", "children": items}


def _paren(child: dict) -> dict:
    return {"type": "paren", "child": child}


def _num_text(n: int) -> dict:
    return _text((MINUS if n < 0 else "") + str(abs(n)))


# precedence: add/sub=1, mul=2, div(frac)=3, pow=3, atom=4
def _precedence(t: dict) -> int:
    ntype = t["type"]
    if ntype in ("add", "sub"):
        return 1
    if ntype == "mul":
        return 2
    if ntype in ("div", "pow"):
        return 3
    return 4


def _is_negative_const(t: dict) -> bool:
    return t["type"] == "num" and t["n"] < 0


def typeset(t: dict) -> dict:
    return _build(t, outer=0)


def _build(t: dict, outer: int) -> dict:
    ntype = t["type"]
    if ntype == "var":
        return _text("x")
    if ntype == "num":
        if t["d"] == 1:
            node = _num_text(t["n"])
        else:
            node = {"type": "frac", "num": _num_text(t["n"]),
                    "den": _num_text(t["d"])}
        if _is_negative_const(t) and outer > 0:
            return _paren(node)
        return node
    if ntype == "pow":
        base = t["base"]
        base_node = _build_base_power(base)
        return {"type": "scripts", "base": base_node,
                "sup": _text(str(t["exp"]))}
    if ntype == "div":
        num = _build_frac_operand(t["left"])
        den = _build_frac_operand(t["right"])
        node = {"type": "frac", "num": num, "den": den}
        return _paren(node) if outer > 3 else node
    if ntype in ("add", "sub", "mul"):
        return _build_chain(t, ntype)
    raise ValueError(ntype)


def _build_base_power(base: dict) -> dict:
    if base["type"] in ("var", "num") and not _is_negative_const(base):
        return _build(base, 0)
    return _paren(_build(base, 0))


def _build_frac_operand(child: dict) -> dict:
    # A fraction rule already separates sums; only unary negative constants
    # need parentheses to avoid ambiguity inside the numerator/denominator.
    node = _build(child, 0)
    return _paren(node) if _is_negative_const(child) else node


def _build_chain(t: dict, kind: str) -> dict:
    left = t["left"]
    right = t["right"]
    if kind == "mul":
        op_prec = 2
        sep = f" {CDOT} "
    else:
        op_prec = 1
        sep = " + " if kind == "add" else f" {MINUS} "

    left_node = _build(left, 0)
    if _precedence(left) < op_prec or _is_negative_const(left):
        left_node = _paren(left_node)
    right_node = _build(right, 0)
    if _needs_right_paren(kind, right) or _is_negative_const(right):
        right_node = _paren(right_node)
    node = _row([left_node, _text(sep), right_node])
    return node


def _needs_right_paren(kind: str, right: dict) -> bool:
    if kind == "mul":
        return _precedence(right) < 2
    return kind == "sub" and right["type"] in ("add", "sub")
