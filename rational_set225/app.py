"""HTTP delivery: FastAPI app exposing POST /render, /check and /solve."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .font import MathFont, FontError
from .layout import Layout
from . import expr
from . import solve
from .nodes import ValidationError, validate_font_size, validate_tree
from .typeset import typeset, typeset_condition
from .svg import render_svg

FONT_PATH = Path(__file__).resolve().parent.parent / "fonts" / "STIXTwoMath-Regular.otf"

app = FastAPI(title="Math Formula Typesetter")
_font = MathFont(str(FONT_PATH))


class RenderRequest(BaseModel):
    formula: Any
    font_size: Any


class CheckRequest(BaseModel):
    steps: Any
    font_size: Any


class SolveRequest(BaseModel):
    conditions: Any
    font_size: Any


@app.exception_handler(ValidationError)
async def validation_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(FontError)
async def font_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(expr.ExprError)
async def expr_handler(request, exc):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post("/render")
async def render(req: RenderRequest):
    size = validate_font_size(req.font_size)
    tree = validate_tree(req.formula, lambda ch: _font.glyph_for(ch) is not None)
    box = Layout(_font, size).layout(tree)
    svg, width, height, baseline = render_svg(box, _font)
    return {"svg": svg, "width": width, "height": height, "baseline": baseline}


@app.post("/check")
async def check(req: CheckRequest):
    size = validate_font_size(req.font_size)
    trees = expr.validate_steps(req.steps)
    reports = []
    fns = []
    for tree in trees:
        fn = expr.analyze(tree)
        fns.append(fn)
        layout_tree = validate_tree(
            typeset(tree), lambda ch: _font.glyph_for(ch) is not None)
        box = Layout(_font, size).layout(layout_tree)
        svg, width, height, baseline = render_svg(box, _font)
        report = expr.step_report(fn)
        report["svg"] = svg
        report["width"] = width
        report["height"] = height
        report["baseline"] = baseline
        reports.append(report)
    comparisons = [expr.compare_steps(fns[i], fns[i + 1])
                   for i in range(len(fns) - 1)]
    return {"steps": reports, "comparisons": comparisons}


@app.post("/solve")
async def solve_endpoint(req: SolveRequest):
    size = validate_font_size(req.font_size)
    conditions = solve.validate_conditions(req.conditions)
    result = solve.solve_system(conditions)
    for cond, report in zip(conditions, result["conditions"]):
        layout_tree = validate_tree(
            typeset_condition(cond), lambda ch: _font.glyph_for(ch) is not None)
        box = Layout(_font, size).layout(layout_tree)
        svg, width, height, baseline = render_svg(box, _font)
        report["svg"] = svg
        report["width"] = width
        report["height"] = height
        report["baseline"] = baseline
    return result
