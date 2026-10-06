"""Rational-expression tree validation and exact algebra.

A tree is converted to a pair of integer-coefficient polynomials (N, D) in x,
together with explicit irreducible restriction factors coming from every
original denominator (and every zero-exponent power base). Cancelling factors
of N/D never removes a restriction, so 约分 cannot erase forbidden points.
All arithmetic is exact (SymPy over ZZ); no floating point is used to decide
identity or root equality.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import sympy
from sympy import Poly, Rational as SRational, ZZ

X = sympy.Symbol("x")

MAX_STEPS = 10
MIN_STEPS = 2
MAX_NODES = 200
MAX_DEPTH = 20
MAX_POLY_DEGREE = 12
MAX_EXP = 6
MAX_INT_DIGITS = 100

BIN_OPS = {"add", "sub", "mul", "div"}


class ExprError(ValueError):
    pass


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_int_digits(n: int) -> None:
    if len(str(abs(n))) > MAX_INT_DIGITS:
        raise ExprError(f"integer exceeds {MAX_INT_DIGITS} digits")


def validate_steps(payload: Any) -> list[dict]:
    if not isinstance(payload, list):
        raise ExprError("steps must be a list of expression trees")
    if not (MIN_STEPS <= len(payload) <= MAX_STEPS):
        raise ExprError(f"expected between {MIN_STEPS} and {MAX_STEPS} steps")
    return [validate_expression(raw) for raw in payload]


def validate_expression(raw: Any) -> dict:
    tree = _validate(raw)
    if count_nodes(tree) > MAX_NODES:
        raise ExprError(f"expression exceeds {MAX_NODES} nodes")
    return tree


def _validate(node: Any, depth: int = 1) -> dict:
    if depth > MAX_DEPTH:
        raise ExprError(f"expression is nested deeper than {MAX_DEPTH}")
    if not isinstance(node, dict):
        raise ExprError("expression node must be an object; code/strings rejected")
    ntype = node.get("type")
    if not isinstance(ntype, str):
        raise ExprError("node 'type' must be a string")

    if ntype == "num":
        n = node.get("n")
        d = node.get("d", 1)
        if not _is_int(n) or not _is_int(d):
            raise ExprError("num requires integers 'n' and 'd'")
        if d == 0:
            raise ExprError("num denominator must be non-zero")
        _check_int_digits(n)
        _check_int_digits(d)
        return {"type": "num", "n": n, "d": d}
    if ntype == "var":
        return {"type": "var"}
    if ntype in BIN_OPS:
        left = node.get("left")
        right = node.get("right")
        if left is None or right is None:
            raise ExprError(f"{ntype} requires 'left' and 'right'")
        return {"type": ntype,
                "left": _validate(left, depth + 1),
                "right": _validate(right, depth + 1)}
    if ntype == "pow":
        exp = node.get("exp")
        if not _is_int(exp) or not (0 <= exp <= MAX_EXP):
            raise ExprError(f"pow requires integer 'exp' in 0..{MAX_EXP}")
        if "base" not in node:
            raise ExprError("pow requires 'base'")
        return {"type": "pow", "base": _validate(node["base"], depth + 1),
                "exp": exp}
    raise ExprError(
        "unknown expression node " + repr(ntype)
        + "; allowed: num, var, add, sub, mul, div, pow")


def count_nodes(tree: dict) -> int:
    ntype = tree["type"]
    if ntype in ("num", "var"):
        return 1
    if ntype == "pow":
        return 1 + count_nodes(tree["base"])
    return 1 + count_nodes(tree["left"]) + count_nodes(tree["right"])


def _poly(expr) -> Poly:
    if isinstance(expr, Poly):
        return expr.as_poly(X, domain=ZZ)
    return Poly(sympy.expand(expr), X, domain=ZZ)


@dataclass
class RatFn:
    num: Poly
    den: Poly
    # canonical irreducible factor -> multiplicity, tracking real-domain
    # restrictions explicitly so cancellation never erases them
    restrictions: dict[tuple, int]

    def points(self) -> list:
        return restriction_points(self.restrictions)


def _factor_key(p: Poly) -> tuple:
    return tuple(int(c) for c in p.all_coeffs())


def _add_factors(store: dict, factors, extra=1) -> None:
    for f in factors:
        _, mults = f.factor_list()
        for irreducible, mult in mults:
            irreducible = irreducible.primitive()[1]
            if irreducible.LC() < 0:
                irreducible = -irreducible
            key = _factor_key(irreducible)
            store[key] = store.get(key, 0) + mult * extra


def _check_degree(n: Poly, d: Poly) -> None:
    if n.total_degree() > MAX_POLY_DEGREE or d.total_degree() > MAX_POLY_DEGREE:
        raise ExprError(
            f"intermediate numerator/denominator degree exceeds {MAX_POLY_DEGREE}")


def analyze(tree: dict) -> RatFn:
    return _analyze(tree)


def _analyze(t: dict) -> RatFn:
    ntype = t["type"]
    if ntype == "num":
    #  rational constant: reduce to lowest terms for size
        fr = SRational(t["n"], t["d"])
        n, d = fr.as_numer_denom()
        return RatFn(_poly(n), _poly(d), {})
    if ntype == "var":
        return RatFn(_poly(X), _poly(1), {})

    if ntype == "pow":
        b = _analyze(t["base"])
        e = t["exp"]
        if e == 0:
            if b.num.is_zero:
                raise ExprError("0 to the power 0 is undefined (zero base)")
            # base**0 == 1 wherever the base is defined; zeros of the base
            # numerator (including nested divisors) remain forbidden too.
            restr = dict(b.restrictions)
            _add_factors(restr, [b.num])
            return RatFn(_poly(1), _poly(1), restr)
        num = b.num ** e
        den = b.den ** e
        _check_degree(num, den)
        restr = {k: v * e for k, v in b.restrictions.items()}
        return RatFn(num, den, restr)

    a = _analyze(t["left"])
    b = _analyze(t["right"])
    n1, d1, r1 = a.num, a.den, a.restrictions
    n2, d2, r2 = b.num, b.den, b.restrictions

    restr = dict(r1)
    for k, v in r2.items():
        restr[k] = restr.get(k, 0) + v

    if ntype in ("add", "sub"):
        sgn = 1 if ntype == "add" else -1
        num = _poly(n1 * d2 + sgn * n2 * d1)
        den = _poly(d1 * d2)
    elif ntype == "mul":
        num = _poly(n1 * n2)
        den = _poly(d1 * d2)
    else:  # div
        if n2.is_zero:
            raise ExprError("division by an identically zero expression is undefined")
        num = _poly(n1 * d2)
        den = _poly(n2 * d1)
        _add_factors(restr, [n2])
    _add_factors(restr, [d1, d2])
    _check_degree(num, den)
    if den.is_zero:
        raise ExprError("identically zero denominator; expression is undefined everywhere")
    return RatFn(num, den, restr)


def restriction_points(restrictions: dict[tuple, int]) -> list:
    """Exact distinct real zeros of the restriction factors.

    Each restriction factor is kept primitive and (by construction) squarefree
    per distinct factor key; duplicates merge through the multiplicity map.
    Roots are thus deduplicated algebraically without floating tolerances.
    """
    points = []
    seen_linear: set[Fraction] = set()
    for key in sorted(restrictions):
        p = Poly(key, X, domain=ZZ)
        if p.total_degree() == 0:
            continue
        if p.total_degree() == 1:
            a, b = (int(c) for c in p.all_coeffs())
            root = Fraction(-b, a)
            if root in seen_linear:
                continue
            seen_linear.add(root)
            points.append({"kind": "rational", "value": _fraction_str(root),
                           "approx": float(root)})
            continue
        count = sympy.count_roots(p.as_expr())
        for j in range(count):
            root = sympy.CRootOf(p.as_expr(), j)
            points.append({"kind": "algebraic",
                           "poly": _poly_str(p),
                           "index": j,
                           "root": str(root),
                           "approx": float(root.evalf(30))})
    points.sort(key=lambda q: q["approx"])
    return points


def _fraction_str(fr: Fraction) -> str:
    return str(fr.numerator) if fr.denominator == 1 else f"{fr.numerator}/{fr.denominator}"


def _poly_str(p: Poly) -> str:
    return str(p.as_expr().expand())


def _point_id(pt: dict):
    v = pt["value"] if pt["kind"] == "rational" else None
    if v is not None:
        return ("r", Fraction(v) if "/" in v else Fraction(int(v)))
    return ("a", pt["poly"], pt["index"])


def compare_steps(prev: RatFn, cur: RatFn) -> dict:
    diff = _poly(prev.num * cur.den - cur.num * prev.den)
    identical_fns = diff.is_zero
    p_keys = {_point_id(q) for q in prev.points()}
    c_keys = {_point_id(q) for q in cur.points()}
    same_domain = p_keys == c_keys
    added = [q for q in cur.points() if _point_id(q) not in p_keys]
    removed = [q for q in prev.points() if _point_id(q) not in c_keys]
    if identical_fns and same_domain:
        verdict = "identical"
    elif identical_fns:
        verdict = "same_value_domain_changed"
    else:
        verdict = "not_identical"
    return {
        "verdict": verdict,
        "identical_on_common_domain": bool(identical_fns),
        "same_domain": bool(same_domain),
        "added_forbidden": added,
        "removed_forbidden": removed,
        "cross_product_difference": _poly_str(diff),
    }


def step_report(fn: RatFn) -> dict:
    return {
        "numerator": _poly_str(fn.num),
        "denominator": _poly_str(fn.den),
        "forbidden": fn.points(),
    }
