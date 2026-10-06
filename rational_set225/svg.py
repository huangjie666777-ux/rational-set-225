"""Render a laid-out Box to a self-contained SVG (glyph outlines only)."""
from __future__ import annotations

from xml.sax.saxutils import escape

from .font import MathFont
from .layout import Box


def _fmt(v: float) -> str:
    s = f"{v:.3f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def render_svg(box: Box, font: MathFont) -> tuple[str, float, float, float]:
    """Return (svg, width, height, baseline_from_top) in output units."""
    x_min = y_min = 0.0
    x_max = y_max = 0.0
    first = True
    for item in box.items:
        if item[0] == "glyph":
            _, name, x, y, scale = item
            bx0, by0, bx1, by1 = font.bounds(name)
            ix0, ix1 = x + bx0 * scale, x + bx1 * scale
            iy0, iy1 = y + by0 * scale, y + by1 * scale
        else:
            _, x, y_top, w, h = item
            ix0, ix1 = x, x + w
            iy0, iy1 = y_top - h, y_top
        if first:
            x_min, x_max, y_min, y_max = ix0, ix1, iy0, iy1
            first = False
        else:
            x_min, x_max = min(x_min, ix0), max(x_max, ix1)
            y_min, y_max = min(y_min, iy0), max(y_max, iy1)

    width = x_max - x_min
    height = y_max - y_min
    baseline = y_max  # distance from top of the viewBox down to the baseline

    parts = []
    for item in box.items:
        if item[0] == "glyph":
            _, name, x, y, scale = item
            d = font.svg_path(name, scale)
            tx = x - x_min
            ty = y_max - y
            parts.append(f'<path d="{d}" transform="translate({_fmt(tx)} {_fmt(ty)})"/>')
        else:
            _, x, y_top, w, h = item
            rx = x - x_min
            ry = y_max - y_top
            parts.append(
                f'<rect x="{_fmt(rx)}" y="{_fmt(ry)}" '
                f'width="{_fmt(w)}" height="{_fmt(h)}"/>'
            )
    body = "".join(parts)
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(width)}" height="{_fmt(height)}" '
        f'viewBox="0 0 {_fmt(width)} {_fmt(height)}">'
        f'<g fill="black">{body}</g></svg>'
    )
    return svg, width, height, baseline
