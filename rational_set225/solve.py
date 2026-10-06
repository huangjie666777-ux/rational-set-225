"""Exact real solution set and sign table for simultaneous rational relations.

Each condition compares two rational-expression trees with a relation
(eq/ne/lt/le/gt/ge). The real axis is partitioned by the exact real zeros of
every left-minus-right numerator together with every forbidden point inherited
from the original trees (cancellation, nested division and zero exponents never
lift restrictions). Signs on the open intervals are decided by exact evaluation
at rational sample points; critical points are classified individually as
zero / positive / negative / undefined. No floating-point tolerance merges
roots and no float grid sampling replaces the exact solve.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Any

import sympy
from sympy import Poly, ZZ

from . import expr
from .expr import ExprError, X

MIN_CONDITIONS = 1
MAX_CONDITIONS = 6

RELATIONS = {"eq", "ne", "lt", "le", "gt", "ge"}


def validate_conditions(payload: Any) -> list[dict]:
    if not isinstance(payload, list):
        raise ExprError("conditions must be a list of condition objects")
    if not (MIN_CONDITIONS <= len(payload) <= MAX_CONDITIONS):
        raise ExprError(
            f"expected between {MIN_CONDITIONS} and {MAX_CONDITIONS} conditions")
    conditions = []
    for item in payload:
        if not isinstance(item, dict):
            raise ExprError("each condition must be an object")
        relation = item.get("relation")
        if not isinstance(relation, str) or relation not in RELATIONS:
            raise ExprError(
                "condition 'relation' must be one of eq, ne, lt, le, gt, ge")
        left = item.get("left")
        right = item.get("right")
        if left is None or right is None:
            raise ExprError("condition requires 'left' and 'right' expression trees")
        left_tree = expr.validate_expression(left)
        right_tree = expr.validate_expression(right)
        conditions.append({"left": left_tree, "right": right_tree,
                           "relation": relation})
    return conditions


@dataclass
class _Condition:
    relation: str
    diff: expr.RatFn
    num_factors: set
    forbidden_rationals: set
    forbidden_keys: set


def _fraction_str(fr: Fraction) -> str:
    return str(fr.numerator) if fr.denominator == 1 else f"{fr.numerator}/{fr.denominator}"


def _factor_keys(p: Poly) -> set:
    keys = set()
    _, mults = p.factor_list()
    for irreducible, _mult in mults:
        irreducible = irreducible.primitive()[1]
        if irreducible.LC() < 0:
            irreducible = -irreducible
        keys.add(expr._factor_key(irreducible))
    return keys


def _prepare(conditions: list[dict]) -> list[_Condition]:
    prepared = []
    for cond in conditions:
        diff_tree = {"type": "sub", "left": cond["left"], "right": cond["right"]}
        diff = expr.analyze(diff_tree)
        num_factors = set() if diff.num.is_zero else _factor_keys(diff.num)
        forbidden_rationals = set()
        forbidden_keys = set()
        for key in diff.restrictions:
            p = Poly(key, X, domain=ZZ)
            if p.total_degree() == 1:
                a, b = (int(c) for c in p.all_coeffs())
                forbidden_rationals.add(Fraction(-b, a))
            elif p.total_degree() >= 2:
                forbidden_keys.add(key)
        prepared.append(_Condition(cond["relation"], diff, num_factors,
                                   forbidden_rationals, forbidden_keys))
    return prepared


def _critical_points(prepared: list[_Condition]) -> list[dict]:
    factor_keys: set = set()
    for cond in prepared:
        factor_keys |= set(cond.diff.restrictions)
        factor_keys |= cond.num_factors
    polys = [Poly(key, X, domain=ZZ) for key in sorted(factor_keys)
             if Poly(key, X, domain=ZZ).total_degree() >= 1]
    if not polys:
        return []
    product = polys[0]
    for p in polys[1:]:
        product = product * p
    points = []
    for (a, b), _mult in sympy.intervals(product):
        a, b = Fraction(a), Fraction(b)
        if a == b:
            points.append({
                "desc": {"kind": "rational", "value": _fraction_str(a),
                         "approx": float(a)},
                "a": a, "b": b, "rational": a, "key": None,
            })
            continue
        owner = None
        for key in sorted(factor_keys):
            f = Poly(key, X, domain=ZZ)
            if f.total_degree() >= 2 and sympy.count_roots(f, a, b) == 1:
                owner = (key, f)
                break
        if owner is None:
            raise ExprError("internal error: cannot attribute algebraic root")
        key, f = owner
        index = int(sympy.count_roots(f, -sympy.oo, a))
        root = sympy.CRootOf(f.as_expr(), index)
        points.append({
            "desc": {"kind": "algebraic", "poly": str(f.as_expr().expand()),
                     "index": index, "root": str(root),
                     "approx": float(root.evalf(30))},
            "a": a, "b": b, "rational": None, "key": key,
        })
    return points


def _sign_at(poly: Poly, q: Fraction) -> int:
    return sympy.sign(poly.as_expr().subs(X, sympy.Rational(q.numerator,
                                                             q.denominator)))


def _status_name(sign_value: int) -> str:
    return {1: "positive", 0: "zero", -1: "negative"}[sign_value]


def _interval_status(cond: _Condition, sample: Fraction) -> str:
    if cond.diff.num.is_zero:
        return "zero"
    s = _sign_at(cond.diff.num, sample) * _sign_at(cond.diff.den, sample)
    return _status_name(s)


def _point_status(cond: _Condition, point: dict) -> str:
    rational = point["rational"]
    if rational is not None:
        if rational in cond.forbidden_rationals:
            return "undefined"
    elif point["key"] in cond.forbidden_keys:
        return "undefined"
    num = cond.diff.num
    if num.is_zero:
        return "zero"
    if rational is not None:
        s_num = _sign_at(num, rational)
        if s_num == 0:
            return "zero"
        return _status_name(s_num * _sign_at(cond.diff.den, rational))
    if point["key"] in cond.num_factors:
        return "zero"
    edge = point["a"]
    s = _sign_at(num, edge) * _sign_at(cond.diff.den, edge)
    return _status_name(s)


def _truth(status: str, relation: str) -> bool:
    if status == "undefined":
        return False
    return {
        "eq": status == "zero",
        "ne": status != "zero",
        "lt": status == "negative",
        "le": status in ("negative", "zero"),
        "gt": status == "positive",
        "ge": status in ("positive", "zero"),
    }[relation]


def solve_system(conditions: list[dict]) -> dict:
    prepared = _prepare(conditions)
    points = _critical_points(prepared)

    samples = []
    if points:
        samples.append(points[0]["a"] - 1)
        for left, right in zip(points, points[1:]):
            samples.append((left["b"] + right["a"]) / 2)
        samples.append(points[-1]["b"] + 1)
    else:
        samples.append(Fraction(0))

    intervals_out = []
    interval_flags = []
    for i, sample in enumerate(samples):
        statuses = [_interval_status(cond, sample) for cond in prepared]
        truths = [_truth(s, c.relation) for s, c in zip(statuses, prepared)]
        conjunction = all(truths)
        interval_flags.append(conjunction)
        left_desc = points[i - 1]["desc"] if i > 0 else None
        right_desc = points[i]["desc"] if i < len(points) else None
        intervals_out.append({
            "left": left_desc if left_desc else {"kind": "infinity", "sign": "negative"},
            "right": right_desc if right_desc else {"kind": "infinity", "sign": "positive"},
            "sample": _fraction_str(sample),
            "signs": statuses,
            "conditions": truths,
            "solution": conjunction,
        })

    points_out = []
    point_flags = []
    for point in points:
        statuses = [_point_status(cond, point) for cond in prepared]
        truths = [_truth(s, c.relation) for s, c in zip(statuses, prepared)]
        conjunction = all(truths)
        point_flags.append(conjunction)
        points_out.append({
            "point": point["desc"],
            "status": statuses,
            "conditions": truths,
            "solution": conjunction,
        })

    items = []
    for i in range(len(samples)):
        items.append(("interval", i))
        if i < len(points):
            items.append(("point", i))

    def flag(item):
        kind, idx = item
        return interval_flags[idx] if kind == "interval" else point_flags[idx]

    sol_intervals = []
    sol_points = []
    run = []

    def flush():
        if not run:
            return
        if len(run) == 1 and run[0][0] == "point":
            sol_points.append(points[run[0][1]]["desc"])
            return
        first, last = run[0], run[-1]
        if first[0] == "point":
            left = {"point": points[first[1]]["desc"], "open": False}
        elif first[1] == 0:
            left = {"kind": "infinity", "sign": "negative"}
        else:
            left = {"point": points[first[1] - 1]["desc"], "open": True}
        if last[0] == "point":
            right = {"point": points[last[1]]["desc"], "open": False}
        elif last[1] == len(samples) - 1:
            right = {"kind": "infinity", "sign": "positive"}
        else:
            right = {"point": points[last[1]]["desc"], "open": True}
        sol_intervals.append({"left": left, "right": right})

    for item in items:
        if flag(item):
            run.append(item)
        else:
            flush()
            run = []
    flush()

    if not sol_intervals and not sol_points:
        solution = {"kind": "empty", "intervals": [], "points": []}
    elif (len(sol_intervals) == 1 and not sol_points
          and sol_intervals[0]["left"].get("kind") == "infinity"
          and sol_intervals[0]["right"].get("kind") == "infinity"):
        solution = {"kind": "all", "intervals": sol_intervals, "points": []}
    else:
        solution = {"kind": "set", "intervals": sol_intervals, "points": sol_points}

    return {
        "conditions": [
            {
                "relation": cond.relation,
                "difference": {
                    "numerator": str(cond.diff.num.as_expr().expand()),
                    "denominator": str(cond.diff.den.as_expr().expand()),
                },
                "forbidden": cond.diff.points(),
            }
            for cond in prepared
        ],
        "sign_table": {
            "critical_points": [p["desc"] for p in points],
            "intervals": intervals_out,
            "points": points_out,
        },
        "solution": solution,
    }
