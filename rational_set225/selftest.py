"""Self-test: layout correctness, validation rejections, determinism."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .font import MathFont
from .layout import Layout
from . import expr, solve
from .nodes import ValidationError, validate_font_size, validate_tree
from .typeset import typeset, typeset_condition
from .svg import render_svg

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "STIXTwoMath-Regular.otf"
font = MathFont(str(FONT_PATH))
SIZE = 48.0


def render(tree, size=SIZE):
    node = validate_tree(tree, lambda ch: font.glyph_for(ch) is not None)
    box = Layout(font, size).layout(node)
    return render_svg(box, font), box


def expect_error(tree, size=SIZE):
    try:
        if not (isinstance(size, (int, float)) and size > 0):
            validate_font_size(size)
        validate_tree(tree, lambda ch: font.glyph_for(ch) is not None)
    except ValidationError:
        return
    raise AssertionError(f"expected ValidationError for {tree!r}")


def main():
    # text
    (svg, w, h, b), box = render({"type": "text", "value": "xy+1"})
    assert w > 0 and h > 0 and b > 0 and "<path" in svg

    # row aligns on baseline
    (svg, w, h, b), _ = render({"type": "row", "children": [
        {"type": "text", "value": "a"}, {"type": "text", "value": "g"}]})
    assert h > 0 and b > 0

    # fraction
    frac = {"type": "frac", "num": {"type": "text", "value": "1"},
            "den": {"type": "text", "value": "x+2"}}
    (svg, w, h, b), _ = render(frac)
    assert "<rect" in svg and h > SIZE

    # scripts: sup only, sub only, both
    for extra in ({"sup": {"type": "text", "value": "2"}},
                  {"sub": {"type": "text", "value": "i"}},
                  {"sup": {"type": "text", "value": "2"},
                   "sub": {"type": "text", "value": "i"}}):
        node = {"type": "scripts", "base": {"type": "text", "value": "x"}, **extra}
        (svg, w, h, b), _ = render(node)
        assert w > 0

    # sqrt with nested frac; parens around tall content stretch
    nested = {"type": "paren", "child": {"type": "sqrt", "radicand": frac}}
    (svg, w, h, b), _ = render(nested)
    assert h > SIZE * 1.5

    # very tall content triggers assembly (many extender parts)
    tall = frac
    for _ in range(6):
        tall = {"type": "frac", "num": tall, "den": tall}
    (svg, w, h, b), _ = render({"type": "paren", "child": tall})
    assert svg.count("<path") > 10

    # determinism
    s1, _ = render(nested)
    s2, _ = render(nested)
    assert s1 == s2

    # input tree not mutated
    tree = {"type": "frac", "num": {"type": "text", "value": "a"},
            "den": {"type": "text", "value": "b"}}
    snapshot = copy.deepcopy(tree)
    render(tree)
    assert tree == snapshot

    # rejections
    expect_error({"type": "nope"})
    expect_error({"type": "text", "value": ""})
    expect_error({"type": "text", "value": "\u4e2d"})  # CJK not in font
    expect_error({"type": "frac", "num": {"type": "text", "value": "a"}})
    expect_error({"type": "scripts", "base": {"type": "text", "value": "x"}})
    expect_error({"type": "row", "children": []})
    deep = {"type": "text", "value": "x"}
    for _ in range(80):
        deep = {"type": "sqrt", "radicand": deep}
    expect_error(deep)
    for bad in (0, -1, float("inf"), float("nan"), 1e9, "12"):
        try:
            validate_font_size(bad)
        except ValidationError:
            pass
        else:
            raise AssertionError(f"font_size {bad!r} accepted")

    # non-string type and delimiters no longer crash with a 500
    from fastapi.testclient import TestClient
    from .app import app
    client = TestClient(app)
    for bad_formula in (
        {"type": [], "value": "x"},
        {"type": "paren", "left": [], "child": {"type": "text", "value": "x"}},
    ):
        resp = client.post("/render", json={"font_size": 48, "formula": bad_formula})
        assert resp.status_code == 422, bad_formula

    # radical covers deep radicand content below the baseline
    deep_rad = {"type": "sqrt", "radicand":
                {"type": "frac", "num": {"type": "text", "value": "1"},
                 "den": {"type": "text", "value": "x+2"}}}
    (_, w, h, b), rad_box = render(deep_rad)
    assert rad_box.depth > 0
    # some glyph piece reaches the lower part of the box (below baseline)
    glyph_bottom = min(it[3] + font.bounds(it[1])[1] * (48.0 / font.upem)
                       for it in rad_box.items if it[0] == "glyph")
    assert glyph_bottom <= -rad_box.depth + 48.0 / font.upem * 200

    # multi-level denominators: assembled radical ink must fully cover the
    # radicand (regression: nested fractions protruded below the surd)
    deep_frac = {"type": "text", "value": "x+2"}
    for _ in range(4):
        deep_frac = {"type": "frac", "num": {"type": "text", "value": "1"},
                     "den": deep_frac}
    lay = Layout(font, SIZE)
    inner_box = lay.layout(
        validate_tree(deep_frac, lambda ch: font.glyph_for(ch) is not None))
    (_, _, _, _), sqrt_box = render({"type": "sqrt", "radicand": deep_frac})
    k = SIZE / font.upem
    gap = lay.const("RadicalVerticalGap", SIZE)
    rule_t = lay.const("RadicalRuleThickness", SIZE)
    bar_top = inner_box.height + gap + rule_t
    content_bottom = -inner_box.depth - gap
    surd = [it for it in sqrt_box.items if it[0] == "glyph" and it[2] == 0.0]
    surd_top = max(it[3] + font.bounds(it[1])[3] * k for it in surd)
    surd_bottom = min(it[3] + font.bounds(it[1])[1] * k for it in surd)
    assert surd_top >= bar_top - 1e-6
    assert surd_bottom <= content_bottom + 1e-6

    # raised-content parentheses cover the full content height/depth
    raised = {"type": "scripts",
              "base": {"type": "text", "value": "x"},
              "sup": {"type": "text", "value": "2"}}
    (_, _, ph, _), pbox = render({"type": "paren", "child": raised})
    assert pbox.height >= raised_height_check(raised)

    _selftest_algebra(client)
    _selftest_solve(client)
    print("selftest OK")


def raised_height_check(node):
    _, box = render(node)
    return box.height


def _selftest_algebra(client):
    x = {"type": "var"}

    def num(v, d=1):
        return {"type": "num", "n": v, "d": d}

    def binop(op, l, r):
        return {"type": op, "left": l, "right": r}

    def pw(base, e):
        return {"type": "pow", "base": base, "exp": e}

    # 约分 keeps the forbidden point; cancellation changes domain only
    steps = [binop("div", x, x), num(1)]
    fn0 = expr.analyze(steps[0])
    assert [p["value"] for p in fn0.points()] == ["0"]
    cmp = expr.compare_steps(fn0, expr.analyze(steps[1]))
    assert cmp["verdict"] == "same_value_domain_changed"
    assert cmp["cross_product_difference"] == "0"

    # 通分 preserves both restrictions
    common = binop("add",
                   binop("div", num(1), x),
                   binop("div", num(1), binop("add", x, num(1))))
    points = [p["value"] for p in expr.analyze(common).points()]
    assert points == ["-1", "0"]

    # exact algebraic roots, no float-tolerance duplication
    irr = binop("div", num(1), binop("sub", pw(x, 2), num(2)))
    pts = expr.analyze(irr).points()
    assert len(pts) == 2 and all(p["kind"] == "algebraic" for p in pts)
    assert pts[0]["approx"] < 0 < pts[1]["approx"]
    # the same factor twice (e.g. squared) does not duplicate roots
    squared = binop("div", num(1),
                    binop("mul", binop("sub", pw(x, 2), num(2)),
                           binop("sub", pw(x, 2), num(2))))
    assert len(expr.analyze(squared).points()) == 2

    # nested division and zero-power restrictions survive
    assert [p["value"] for p in expr.analyze(pw(binop("add", x, num(1)), 0)).points()] == ["-1"]
    assert [p["value"] for p in expr.analyze(pw(binop("div", num(1), x), 0)).points()] == ["0"]

    # identically zero divisors rejected
    for bad in (binop("div", num(1), num(0)),
                binop("div", num(1), binop("sub", x, x))):
        try:
            expr.analyze(bad)
        except expr.ExprError:
            pass
        else:
            raise AssertionError("zero divisor accepted")

    # non-identity carries a cross-product difference polynomial
    cmp = expr.compare_steps(expr.analyze(binop("add", x, num(1))),
                             expr.analyze(binop("add", x, num(2))))
    assert cmp["verdict"] == "not_identical"
    assert cmp["cross_product_difference"] == "-1"

    # typesetting keeps the original structure and renders
    tree = binop("div", binop("sub", pw(x, 2), num(1)),
                 binop("add", x, num(1)))
    laid = validate_tree(typeset(tree), lambda ch: font.glyph_for(ch) is not None)
    box = Layout(font, SIZE).layout(laid)
    svg, w, h, base = render_svg(box, font)
    assert w > 0 and h > 0 and "<rect" in svg

    # HTTP /check end to end
    resp = client.post("/check", json={"font_size": SIZE, "steps": steps})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["steps"]) == 2
    assert all(s["svg"].startswith("<svg") for s in data["steps"])
    assert data["comparisons"][0]["verdict"] == "same_value_domain_changed"

    # code / expression strings rejected
    for bad_steps in (["x+1", "x+2"],
                      [{"type": "num", "n": "__import__('os')", "d": 1}, num(1)]):
        resp = client.post("/check", json={"font_size": SIZE, "steps": bad_steps})
        assert resp.status_code == 422


def _selftest_solve(client):
    x = {"type": "var"}

    def num(v, d=1):
        return {"type": "num", "n": v, "d": d}

    def binop(op, l, r):
        return {"type": op, "left": l, "right": r}

    def pw(base, e):
        return {"type": "pow", "base": base, "exp": e}

    def cond(l, r, rel):
        return {"left": l, "right": r, "relation": rel}

    def run(conditions):
        specs = solve.validate_conditions(conditions)
        conds = solve.analyze_conditions(specs)
        return solve.solve_system(conds)

    # (x-1)/(x-2) > 0 -> (-inf, 1) u (2, +inf), both ends open
    res = run([cond(binop("div", binop("sub", x, num(1)),
                          binop("sub", x, num(2))), num(0), "gt")])
    parts = res["solution_set"]["parts"]
    assert res["solution_set"]["kind"] == "set" and len(parts) == 2
    assert parts[0]["lower"]["kind"] == "infinity"
    assert parts[0]["upper"]["point"]["value"] == "1"
    assert not parts[0]["upper"]["closed"]
    assert parts[1]["lower"]["point"]["value"] == "2"
    assert not parts[1]["lower"]["closed"]
    assert parts[1]["upper"]["kind"] == "infinity"
    # critical point 2 is undefined, not "equality fails"
    rows = {r["point"].get("value"): r for r in res["sign_table"]["points"]}
    assert rows["2"]["differences"] == ["undefined"]
    assert rows["2"]["defined"] == [False]
    assert rows["1"]["differences"] == ["zero"]

    # (x-1)(x-2) <= 0 and x != 3/2 -> [1, 3/2) u (3/2, 2]
    prod = binop("mul", binop("sub", x, num(1)), binop("sub", x, num(2)))
    res = run([cond(prod, num(0), "le"),
               cond(x, num(3, 2), "ne")])
    parts = res["solution_set"]["parts"]
    assert len(parts) == 2
    assert parts[0]["lower"]["closed"] and parts[0]["lower"]["point"]["value"] == "1"
    assert parts[0]["upper"]["point"]["value"] == "3/2"
    assert not parts[0]["upper"]["closed"]
    assert not parts[1]["lower"]["closed"]
    assert parts[1]["upper"]["closed"] and parts[1]["upper"]["point"]["value"] == "2"

    # (x-1)^2 <= 0 -> isolated point x = 1; even multiplicity must not
    # fake a sign change on either side
    res = run([cond(pw(binop("sub", x, num(1)), 2), num(0), "le")])
    sol = res["solution_set"]
    assert sol["kind"] == "set" and len(sol["parts"]) == 1
    assert sol["parts"][0] == {"type": "point", "point":
                               {"kind": "rational", "value": "1", "approx": 1.0}}
    signs = [row["differences"][0] for row in res["sign_table"]["intervals"]]
    assert signs == ["positive", "positive"]

    # x^2 + 1 <= 0 -> empty set, stated explicitly
    res = run([cond(binop("add", pw(x, 2), num(1)), num(0), "le")])
    assert res["solution_set"] == {"kind": "empty", "parts": []}

    # x - x == 0 -> the whole real axis
    res = run([cond(binop("sub", x, x), num(0), "eq")])
    assert res["solution_set"]["kind"] == "all"

    # 1/(x-1) == 1/(x-1): identity, but x = 1 stays undefined
    inv = binop("div", num(1), binop("sub", x, num(1)))
    res = run([cond(inv, inv, "eq")])
    parts = res["solution_set"]["parts"]
    assert len(parts) == 2
    assert parts[0]["upper"]["point"]["value"] == "1"
    assert parts[1]["lower"]["point"]["value"] == "1"
    assert res["sign_table"]["points"][0]["defined"] == [False]

    # x^2 - 2 >= 0 -> algebraic endpoints, exact CRootOf, no float merging
    res = run([cond(binop("sub", pw(x, 2), num(2)), num(0), "ge")])
    parts = res["solution_set"]["parts"]
    assert len(parts) == 2
    lo = parts[0]["upper"]["point"]
    hi = parts[1]["lower"]["point"]
    assert lo["kind"] == "algebraic" and hi["kind"] == "algebraic"
    assert parts[0]["upper"]["closed"] and parts[1]["lower"]["closed"]
    assert lo["approx"] < 0 < hi["approx"]
    assert lo["poly"] == hi["poly"] and lo["index"] != hi["index"]

    # forbidden points inherited through cancellation: x/x - 1 >= 0 holds
    # everywhere except x = 0, where the original expression is undefined
    res = run([cond(binop("div", x, x), num(1), "ge")])
    parts = res["solution_set"]["parts"]
    assert len(parts) == 2
    assert res["sign_table"]["points"][0]["defined"] == [False]

    # HTTP end to end, including per-condition SVG with the relation symbol
    resp = client.post("/solve", json={
        "font_size": SIZE,
        "conditions": [cond(binop("div", binop("sub", x, num(1)),
                                  binop("sub", x, num(2))), num(0), "gt")]})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["conditions"]) == 1
    assert data["conditions"][0]["svg"].startswith("<svg")
    assert data["conditions"][0]["width"] > 0
    assert data["solution_set"]["kind"] == "set"
    assert len(data["sign_table"]["intervals"]) == 3

    # rejections: bad relation, wrong count, string expressions
    for bad in (
        {"font_size": SIZE, "conditions": []},
        {"font_size": SIZE,
         "conditions": [cond(x, x, "eq")] * 7},
        {"font_size": SIZE, "conditions": [cond(x, x, "approx")]},
        {"font_size": SIZE, "conditions": [{"left": "x+1", "right": x,
                                            "relation": "eq"}]},
    ):
        resp = client.post("/solve", json=bad)
        assert resp.status_code == 422, bad


if __name__ == "__main__":
    main()
