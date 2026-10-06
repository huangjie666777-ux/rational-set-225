"""Exact real solution sets and sign tables for systems of rational relations.

Each condition compares two rational-expression trees (left/right) with one of
eq/ne/lt/le/gt/ge. The difference left-right is analyzed with the same exact
integer-polynomial machinery as /check, inheriting every forbidden point of
the original subexpressions. The real axis is partitioned by all difference
zeros and all forbidden points; signs on open intervals are decided by exact
evaluation at rational sample points (never by floating grids), and critical
points are judged individually, distinguishing "equality holds" from
"expression undefined". Multiplicity never fakes a sign change because signs
come from sampling, not from root parity guesses.
"""
from __future__ import annotations

from fractions import Fraction
from functools import cmp_to_key

import sympy

from . import expr
from .expr import ExprError

RELATIONS = ("eq", "ne", "lt", "le", "gt", "ge")
RELATION_SYMBOLS = {"eq": "=", "ne": "\u2260", "lt": "<", "le": "\u2264",
                    "gt": ">", "ge": "\u2265"}
MIN_CONDITIONS = 1
MAX_CONDITIONS = 6

SIGN_NAMES = {-1: "negative", 0: "zero", 1: "positive"}


def validate_conditions(payload) -> list[dict]:
    if not isinstance(payload, list):
        raise ExprError("conditions must be a list")
    if not (MIN_CONDITIONS <= len(payload) <= MAX_CONDITIONS):
        raise ExprError(
            f"expected between {MIN_CONDITIONS} and {MAX_CONDITIONS} conditions")
    specs = []
    for raw in payload:
        if not isinstance(raw, dict):
            raise ExprError("each condition must be an object")
        relation = raw.get("relation")
        if relation not in RELATIONS:
            raise ExprError(
                "relation must be one of: " + ", ".join(RELATIONS))
        if "left" not in raw or "right" not in raw:
            raise ExprError("each condition requires 'left' and 'right'")
        left = expr._validate(raw["left"])
        right = expr._validate(raw["right"])
        if (expr.count_nodes(left) > expr.MAX_NODES
                or expr.count_nodes(right) > expr.MAX_NODES):
            raise ExprError(f"expression exceeds {expr.MAX_NODES} nodes")
        specs.append({"left": left, "right": right, "relation": relation})
    return specs


class Condition:
    """One relation analyzed as an exact rational difference function."""

    def __init__(self, spec: dict):
        self.relation = spec["relation"]
        self.left = spec["left"]
        self.right = spec["right"]
        diff_tree = {"type": "sub", "left": self.left, "right": self.right}
        self.fn = expr.analyze(diff_tree)
        self.identically_zero = self.fn.num.is_zero
        self.zeros = expr.poly_real_points(self.fn.num)
        self.forbidden = self.fn.points()
        self.zero_keys = {expr.point_key(p) for p in self.zeros}
        self.forbidden_keys = {expr.point_key(p) for p in self.forbidden}


def analyze_conditions(specs: list[dict]) -> list[Condition]:
    return [Condition(spec) for spec in specs]


def condition_report(cond: Condition) -> dict:
    return {
        "relation": cond.relation,
        "difference": {"numerator": expr._poly_str(cond.fn.num),
                       "denominator": expr._poly_str(cond.fn.den)},
        "zeros": cond.zeros,
        "forbidden": cond.forbidden,
    }


# -- exact point ordering ----------------------------------------------------

def _alg_root(pt: dict):
    return sympy.CRootOf(sympy.sympify(pt["poly"]), pt["index"])


def _alg_rational_value(pt: dict, prec: int) -> sympy.Rational:
    return sympy.Rational(_alg_root(pt).evalf(prec))


def compare_value_point(value: Fraction, pt: dict) -> int:
    """Compare an exact rational against a critical point: -1/0/1."""
    if pt["kind"] == "rational":
        other = Fraction(pt["value"])
        return (value > other) - (value < other)
    # Irreducible factors of degree >= 2 have no rational roots, so a
    # rational can never equal an algebraic critical point.
    poly = sympy.sympify(pt["poly"])
    rat = sympy.Rational(value.numerator, value.denominator)
    count = sympy.count_roots(poly, -sympy.oo, rat)  # roots in (-oo, r]
    if count >= pt["index"] + 1:
        return 1  # the algebraic root is < value
    return -1


def compare_points(a: dict, b: dict) -> int:
    if a["kind"] == "rational":
        return compare_value_point(Fraction(a["value"]), b)
    if b["kind"] == "rational":
        return -compare_value_point(Fraction(b["value"]), a)
    if a["poly"] == b["poly"]:
        return (a["index"] > b["index"]) - (a["index"] < b["index"])
    # Distinct irreducible factors never share a root; refine until separated.
    for prec in (30, 60, 120, 240, 480, 960):
        va = _alg_rational_value(a, prec)
        vb = _alg_rational_value(b, prec)
        gap = sympy.Rational(10) ** (-(prec - 10))
        if va - vb > gap:
            return 1
        if vb - va > gap:
            return -1
    raise ExprError("could not separate algebraic roots")


def _bound_rational(pt: dict, prec: int, upper: bool) -> Fraction:
    if pt["kind"] == "rational":
        return Fraction(pt["value"])
    value = _alg_rational_value(pt, prec)
    delta = sympy.Rational(10) ** (-(prec - 15))
    bound = value + delta if upper else value - delta
    return Fraction(bound.numerator, bound.denominator)


def rational_between(lo: dict, hi: dict) -> Fraction:
    """A rational strictly between two critical points, verified exactly."""
    for prec in (30, 60, 120, 240, 480, 960):
        upper_lo = _bound_rational(lo, prec, upper=True)
        lower_hi = _bound_rational(hi, prec, upper=False)
        if upper_lo < lower_hi:
            mid = (upper_lo + lower_hi) / 2
            for candidate in (mid.limit_denominator(10 ** 6), mid):
                if (compare_value_point(candidate, lo) > 0
                        and compare_value_point(candidate, hi) < 0):
                    return candidate
    raise ExprError("could not isolate a rational sample point")


def rational_below(pt: dict) -> Fraction:
    if pt["kind"] == "rational":
        return Fraction(pt["value"]) - 1
    for prec in (30, 60, 120, 240, 480, 960):
        candidate = _bound_rational(pt, prec, upper=False)
        if compare_value_point(candidate, pt) < 0:
            simple = candidate.limit_denominator(10 ** 6)
            if compare_value_point(simple, pt) < 0:
                return simple
            return candidate
    raise ExprError("could not bound an algebraic root")


def rational_above(pt: dict) -> Fraction:
    if pt["kind"] == "rational":
        return Fraction(pt["value"]) + 1
    for prec in (30, 60, 120, 240, 480, 960):
        candidate = _bound_rational(pt, prec, upper=True)
        if compare_value_point(candidate, pt) > 0:
            simple = candidate.limit_denominator(10 ** 6)
            if compare_value_point(simple, pt) > 0:
                return simple
            return candidate
    raise ExprError("could not bound an algebraic root")


# -- sign evaluation -----------------------------------------------------------

def _poly_sign_at(poly, value: Fraction) -> int:
    rat = sympy.Rational(value.numerator, value.denominator)
    result = sympy.Rational(poly.as_expr().subs(expr.X, rat))
    return int(sympy.sign(result))


def _difference_sign_at(cond: Condition, sample: Fraction) -> int:
    if cond.identically_zero:
        return 0
    return _poly_sign_at(cond.fn.num, sample) * _poly_sign_at(cond.fn.den, sample)


def _relation_holds(relation: str, sign: int) -> bool:
    if relation == "eq":
        return sign == 0
    if relation == "ne":
        return sign != 0
    if relation == "lt":
        return sign < 0
    if relation == "le":
        return sign <= 0
    if relation == "gt":
        return sign > 0
    return sign >= 0  # ge


# -- system solving --------------------------------------------------------------

def solve_system(conds: list[Condition]) -> dict:
    merged = {}
    for cond in conds:
        for pt in cond.zeros + cond.forbidden:
            merged.setdefault(expr.point_key(pt), pt)
    points = sorted(merged.values(), key=cmp_to_key(compare_points))
    point_keys = [expr.point_key(p) for p in points]

    samples = []
    for j in range(len(points) + 1):
        if j == 0 and not points:
            samples.append(Fraction(0))
        elif j == 0:
            samples.append(rational_below(points[0]))
        elif j == len(points):
            samples.append(rational_above(points[-1]))
        else:
            samples.append(rational_between(points[j - 1], points[j]))

    interval_signs = [
        [_difference_sign_at(cond, sample) for cond in conds]
        for sample in samples
    ]

    intervals = []
    intervals_ok = []
    for j, sample in enumerate(samples):
        signs = interval_signs[j]
        satisfied = [_relation_holds(c.relation, s)
                     for c, s in zip(conds, signs)]
        intervals.append({
            "lower": _interval_endpoint(points, j - 1, lower=True),
            "upper": _interval_endpoint(points, j, lower=False),
            "sample": _sample_str(sample),
            "differences": [SIGN_NAMES[s] for s in signs],
            "satisfied": satisfied,
            "all_satisfied": all(satisfied),
        })
        intervals_ok.append(all(satisfied))

    point_rows = []
    points_ok = []
    for j, pt in enumerate(points):
        key = point_keys[j]
        signs = []
        defined = []
        satisfied = []
        for i, cond in enumerate(conds):
            if key in cond.forbidden_keys:
                signs.append("undefined")
                defined.append(False)
                satisfied.append(False)
                continue
            defined.append(True)
            if cond.identically_zero or key in cond.zero_keys:
                sign = 0
            else:
                # Defined and non-zero here: the sign is locally constant,
                # so the adjacent open interval carries the same sign.
                sign = interval_signs[j][i]
            signs.append(SIGN_NAMES[sign])
            satisfied.append(_relation_holds(cond.relation, sign))
        point_rows.append({
            "point": pt,
            "differences": signs,
            "defined": defined,
            "satisfied": satisfied,
            "all_satisfied": all(satisfied),
        })
        points_ok.append(all(satisfied))

    return {
        "sign_table": {"critical_points": points,
                       "intervals": intervals,
                       "points": point_rows},
        "solution_set": _solution_set(points, intervals_ok, points_ok),
    }


def _sample_str(sample: Fraction) -> str:
    return (str(sample.numerator) if sample.denominator == 1
            else f"{sample.numerator}/{sample.denominator}")


def _interval_endpoint(points: list, index: int, lower: bool) -> dict:
    if index < 0 or index >= len(points):
        return {"kind": "infinity",
                "sign": "negative" if lower else "positive"}
    return {"kind": "point", "closed": False, "point": points[index]}


def _solution_set(points: list, intervals_ok: list, points_ok: list) -> dict:
    # Atoms along the axis: interval0, point0, interval1, ..., point_{n-1},
    # interval_n. Maximal runs of satisfied atoms merge into one part.
    atoms = []
    for j in range(len(points)):
        atoms.append(("interval", j))
        atoms.append(("point", j))
    atoms.append(("interval", len(points)))

    parts = []
    run = None
    for kind, idx in atoms:
        ok = intervals_ok[idx] if kind == "interval" else points_ok[idx]
        if ok:
            run = [kind, idx, kind, idx] if run is None else [run[0], run[1], kind, idx]
        elif run is not None:
            parts.append(_emit_part(run, points))
            run = None
    if run is not None:
        parts.append(_emit_part(run, points))

    if not parts:
        return {"kind": "empty", "parts": []}
    if (len(parts) == 1 and parts[0]["type"] == "interval"
            and parts[0]["lower"]["kind"] == "infinity"
            and parts[0]["upper"]["kind"] == "infinity"):
        return {"kind": "all", "parts": parts}
    return {"kind": "set", "parts": parts}


def _emit_part(run, points: list) -> dict:
    start_kind, start_idx, end_kind, end_idx = run
    if start_kind == "point" and end_kind == "point" and start_idx == end_idx:
        return {"type": "point", "point": points[start_idx]}
    if start_kind == "point":
        lower = {"kind": "point", "closed": True, "point": points[start_idx]}
    else:
        lower = _interval_endpoint(points, start_idx - 1, lower=True)
    if end_kind == "point":
        upper = {"kind": "point", "closed": True, "point": points[end_idx]}
    else:
        upper = _interval_endpoint(points, end_idx, lower=False)
    return {"type": "interval", "lower": lower, "upper": upper}
