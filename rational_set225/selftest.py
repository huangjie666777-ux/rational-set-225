"""Self-test: layout correctness, validation rejections, determinism."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .font import MathFont
from .layout import Layout
from . import expr
from . import solve
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

    # raised-content parentheses cover the full content height/depth
    raised = {"type": "scripts",
              "base": {"type": "text", "value": "x"},
              "sup": {"type": "text", "value": "2"}}
    (_, _, ph, _), pbox = render({"type": "paren", "child": raised})
    assert pbox.height >= raised_height_check(raised)

    # stacked fractions inside a radical: the stretch assembly ink must reach
    # both the bar and the bottom of the deep radicand (no protruding content)
    deep_frac = {"type": "frac", "num": {"type": "text", "value": "1"},
                 "den": {"type": "text", "value": "x+2"}}
    for _ in range(4):
        deep_frac = {"type": "frac", "num": deep_frac, "den": deep_frac}
    sqrt_node = {"type": "sqrt", "radicand": deep_frac}
    lay = Layout(font, SIZE)
    rad_inner = lay.layout(validate_tree(deep_frac, lambda ch: font.glyph_for(ch)))
    sqrt_box = lay.layout(validate_tree(sqrt_node, lambda ch: font.glyph_for(ch)))
    gap = font.constant("RadicalVerticalGap") * SIZE / font.upem
    rule_t = font.constant("RadicalRuleThickness") * SIZE / font.upem
    ink_top = ink_bottom = None
    for it in sqrt_box.items:
        if it[0] != "glyph":
            continue
        b = font.bounds(it[1])
        top = it[3] + b[3] * it[4]
        bottom = it[3] + b[1] * it[4]
        ink_top = top if ink_top is None else max(ink_top, top)
        ink_bottom = bottom if ink_bottom is None else min(ink_bottom, bottom)
    assert ink_top >= rad_inner.height + gap + rule_t - 1e-6
    assert ink_bottom <= -rad_inner.depth - gap + 1e-6

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

    def cond(left, relation, right):
        return {"left": left, "right": right, "relation": relation}

    def run(conditions):
        return solve.solve_system(solve.validate_conditions(conditions))

    def sol_summary(result):
        sol = result["solution"]
        out = []
        for iv in sol["intervals"]:
            def end(e):
                if e.get("kind") == "infinity":
                    return "-inf" if e["sign"] == "negative" else "+inf"
                bracket = "(" if e["open"] else "["
                return bracket + (e["point"]["value"] if e["point"]["kind"] == "rational"
                                  else e["point"]["root"])
            out.append((end(iv["left"]), end(iv["right"])))
        for p in sol["points"]:
            out.append(p["value"] if p["kind"] == "rational" else p["root"])
        return sol["kind"], out

    # (x-1)/(x-2) > 0: (-inf,1) U (2,+inf); x=2 undefined, x=1 excluded
    res = run([cond(binop("div", binop("sub", x, num(1)),
                          binop("sub", x, num(2))), "gt", num(0))])
    kind, out = sol_summary(res)
    assert kind == "set" and out == [("-inf", "(1"), ("(2", "+inf")]
    pts = res["sign_table"]["points"]
    assert [p["status"] for p in pts] == [["zero"], ["undefined"]]

    # (x-1)^2 = 0: double root, no sign change, isolated point {1}
    res = run([cond(pw(binop("sub", x, num(1)), 2), "eq", num(0))])
    kind, out = sol_summary(res)
    assert kind == "set" and out == ["1"]
    iv_signs = [iv["signs"] for iv in res["sign_table"]["intervals"]]
    assert iv_signs == [["positive"], ["positive"]]  # no spurious sign change

    # x^2 - 2 <= 0: closed algebraic endpoints
    res = run([cond(binop("sub", pw(x, 2), num(2)), "le", num(0))])
    sol = res["solution"]
    assert sol["kind"] == "set" and len(sol["intervals"]) == 1
    iv = sol["intervals"][0]
    assert iv["left"]["open"] is False and iv["right"]["open"] is False
    assert iv["left"]["point"]["kind"] == "algebraic"
    assert iv["left"]["point"]["approx"] < 0 < iv["right"]["point"]["approx"]

    # x^2 + 1 < 0: empty; x^2 + 1 > 0: all reals
    assert run([cond(binop("add", pw(x, 2), num(1)), "lt", num(0))])["solution"]["kind"] == "empty"
    assert run([cond(binop("add", pw(x, 2), num(1)), "gt", num(0))])["solution"]["kind"] == "all"

    # x/x = 1: cancellation does not lift the forbidden point 0
    res = run([cond(binop("div", x, x), "eq", num(1))])
    kind, out = sol_summary(res)
    assert out == [("-inf", "(0"), ("(0", "+inf")]
    assert res["sign_table"]["points"][0]["status"] == ["undefined"]

    # conjunction: x >= 0 and x < 1 gives [0, 1)
    res = run([cond(x, "ge", num(0)), cond(x, "lt", num(1))])
    kind, out = sol_summary(res)
    assert out == [("[0", "(1")]

    # conjunction of contradictions is empty
    res = run([cond(x, "gt", num(1)), cond(x, "lt", num(0))])
    assert res["solution"]["kind"] == "empty"

    # (x-1)^0 = 1 keeps the base restriction x=1
    res = run([cond(pw(binop("sub", x, num(1)), 0), "eq", num(1))])
    kind, out = sol_summary(res)
    assert out == [("-inf", "(1"), ("(1", "+inf")]

    # condition SVG carries the relation symbol and typesets both sides
    node = validate_tree(typeset_condition(
        {"left": binop("div", num(1), x), "right": num(2), "relation": "le"}),
        lambda ch: font.glyph_for(ch) is not None)
    box = Layout(font, SIZE).layout(node)
    svg, w, h, b = render_svg(box, font)
    assert w > 0 and "<path" in svg

    # HTTP /solve end to end
    resp = client.post("/solve", json={
        "font_size": SIZE,
        "conditions": [cond(binop("div", binop("sub", x, num(1)),
                                  binop("sub", x, num(2))), "gt", num(0))]})
    assert resp.status_code == 200
    data = resp.json()
    assert data["conditions"][0]["svg"].startswith("<svg")
    assert data["solution"]["kind"] == "set"
    assert len(data["sign_table"]["intervals"]) == 3

    # rejections: 0 or 7 conditions, bad relation, string expressions
    good = cond(x, "ge", num(0))
    for bad in ([], [good] * 7, [cond(x, "approx", num(0))],
                [{"left": "x+1", "right": num(0), "relation": "ge"}],
                [{"left": x, "relation": "ge"}]):
        resp = client.post("/solve", json={"font_size": SIZE, "conditions": bad})
        assert resp.status_code == 422, bad


if __name__ == "__main__":
    main()
