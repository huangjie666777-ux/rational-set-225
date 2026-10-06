"""Recursive formula layout. All coordinates are in output units (same unit as
font_size), y measured UP from each box's own baseline, x from its left edge."""
from __future__ import annotations

from dataclasses import dataclass, field

from .font import MathFont
from .nodes import DELIMS


@dataclass
class Box:
    width: float
    height: float  # above baseline
    depth: float   # below baseline
    items: list = field(default_factory=list)
    italic_correction: float = 0.0

    def shifted(self, dx: float, dy: float) -> "Box":
        return Box(self.width, self.height, self.depth,
                   [shift_item(it, dx, dy) for it in self.items], self.italic_correction)


def shift_item(item, dx, dy):
    kind = item[0]
    if kind == "glyph":
        _, name, x, y, scale = item
        return ("glyph", name, x + dx, y + dy, scale)
    _, x, y_top, w, h = item
    return ("rect", x + dx, y_top + dy, w, h)


class Layout:
    def __init__(self, font: MathFont, font_size: float):
        self.font = font
        self.font_size = font_size

    def const(self, name: str, size: float) -> float:
        return self.font.constant(name) * size / self.font.upem

    def layout(self, node: dict, size: float | None = None, level: int = 0) -> Box:
        if size is None:
            size = self.font_size
        handler = getattr(self, f"_layout_{node['type']}")
        return handler(node, size, level)

    # -- leaves and rows -------------------------------------------------

    def _layout_text(self, node, size, level) -> Box:
        k = size / self.font.upem
        x = 0.0
        items = []
        x_min = y_min = 0.0
        x_max = y_max = 0.0
        last_glyph = None
        for ch in node["value"]:
            glyph = self.font.glyph_for(ch)
            items.append(("glyph", glyph, x, 0.0, k))
            bx0, by0, bx1, by1 = self.font.bounds(glyph)
            x_min = min(x_min, x + bx0 * k)
            x_max = max(x_max, x + bx1 * k)
            y_min = min(y_min, by0 * k)
            y_max = max(y_max, by1 * k)
            x += self.font.advance(glyph) * k
            last_glyph = glyph
        ic = self.font.italic_correction(last_glyph) * k if last_glyph else 0.0
        return Box(width=x, height=y_max, depth=-y_min, items=items,
                   italic_correction=ic)

    def _layout_row(self, node, size, level) -> Box:
        x = 0.0
        items = []
        height = depth = 0.0
        last_ic = 0.0
        for child in node["children"]:
            box = self.layout(child, size, level)
            items.extend(shift_item(it, x, 0.0) for it in box.items)
            x += box.width
            height = max(height, box.height)
            depth = max(depth, box.depth)
            last_ic = box.italic_correction
        return Box(width=x, height=height, depth=depth, items=items,
                   italic_correction=last_ic)

    # -- fraction ---------------------------------------------------------

    def _layout_frac(self, node, size, level) -> Box:
        num = self.layout(node["num"], size, level)
        den = self.layout(node["den"], size, level)
        axis = self.const("AxisHeight", size)
        rule_t = self.const("FractionRuleThickness", size)
        num_shift = self.const("FractionNumeratorShiftUp", size)
        den_shift = self.const("FractionDenominatorShiftDown", size)
        num_gap = self.const("FractionNumeratorGapMin", size)
        den_gap = self.const("FractionDenominatorGapMin", size)

        rule_top = axis + rule_t / 2.0
        rule_bottom = axis - rule_t / 2.0
        # Numerator baseline sits num_shift above the baseline.
        num_y = num_shift
        shortfall = (rule_top + num_gap) - (num_y - num.depth)
        if shortfall > 0:
            num_y += shortfall
        # Denominator baseline sits den_shift below the baseline.
        den_y = -den_shift
        shortfall = (den_y + den.height) - (rule_bottom - den_gap)
        if shortfall > 0:
            den_y -= shortfall

        pad = rule_t
        width = max(num.width, den.width) + 2 * pad
        num_x = (width - num.width) / 2.0
        den_x = (width - den.width) / 2.0
        items = [shift_item(it, num_x, num_y) for it in num.items]
        items += [shift_item(it, den_x, den_y) for it in den.items]
        items.append(("rect", 0.0, rule_top, width, rule_t))
        return Box(width=width, height=num_y + num.height,
                   depth=-den_y + den.depth, items=items)

    # -- scripts ----------------------------------------------------------

    def _script_size(self, size: float, level: int) -> float:
        pct = (self.font.constant("ScriptPercentScaleDown") if level == 0
               else self.font.constant("ScriptScriptPercentScaleDown"))
        return size * pct / 100.0

    def _layout_scripts(self, node, size, level) -> Box:
        base = self.layout(node["base"], size, level)
        script_size = self._script_size(size, level)
        sup = self.layout(node["sup"], script_size, level + 1) if node.get("sup") else None
        sub = self.layout(node["sub"], script_size, level + 1) if node.get("sub") else None

        sup_y = sub_y = 0.0
        if sup is not None:
            sup_y = max(
                self.const("SuperscriptShiftUp", size),
                base.height - self.const("SuperscriptBaselineDropMax", size),
                sup.depth + self.const("SuperscriptBottomMin", size),
            )
        if sub is not None:
            sub_y = max(
                self.const("SubscriptShiftDown", size),
                sub.height - self.const("SubscriptTopMax", size),
            )
        if sup is not None and sub is not None:
            gap = (sup_y - sup.depth) - (sub.height - sub_y)
            min_gap = self.const("SubSuperscriptGapMin", size)
            if gap < min_gap:
                sub_y += min_gap - gap
            sup_bottom_max = self.const("SuperscriptBottomMaxWithSubscript", size)
            if sup_y - sup.depth < sup_bottom_max:
                sup_y += sup_bottom_max - (sup_y - sup.depth)

        items = list(base.items)
        tail = 0.0
        if sup is not None:
            sup_x = base.width + base.italic_correction
            items += [shift_item(it, sup_x, sup_y) for it in sup.items]
            tail = max(tail, base.italic_correction + sup.width)
        if sub is not None:
            items += [shift_item(it, base.width, -sub_y) for it in sub.items]
            tail = max(tail, sub.width)
        space = self.const("SpaceAfterScript", size)
        height = max(base.height, (sup_y + sup.height) if sup else 0.0)
        depth = max(base.depth, (sub_y + sub.depth) if sub else 0.0)
        return Box(width=base.width + tail + space, height=height, depth=depth,
                   items=items)

    # -- radical ------------------------------------------------------------

    def _layout_sqrt(self, node, size, level) -> Box:
        rad = self.layout(node["radicand"], size, level)
        k = size / self.font.upem
        rule_t = self.const("RadicalRuleThickness", size)
        gap = self.const("RadicalVerticalGap", size)
        extra = self.const("RadicalExtraAscender", size)

        target_units = (rad.height + rad.depth + 2 * gap + rule_t) / k
        radical_glyph = self.font.glyph_for("\u221a")
        pieces, covered_units = self.font.stretch_vertical(radical_glyph, target_units)
        covered = covered_units * k
        surd_width = max(self.font.advance(g) for g, _ in pieces) * k

        bar_top = rad.height + gap + rule_t  # top of surd aligns with top of the bar
        # The radical spans from the bar down past the radicand plus gap.
        content_bottom = -rad.depth - gap
        target_center = (bar_top + content_bottom) / 2.0
        center_y = self._fit_pieces(pieces, k, target_center, bar_top, content_bottom)
        items = []
        for glyph, off_units in pieces:
            items.append(("glyph", glyph, 0.0, center_y + off_units * k, k))
        items += [shift_item(it, surd_width, 0.0) for it in rad.items]
        items.append(("rect", surd_width, bar_top, rad.width, rule_t))

        height = bar_top + extra
        depth = max(rad.depth + gap, -self._pieces_bottom(pieces, k, center_y))
        return Box(width=surd_width + rad.width, height=height, depth=depth,
                   items=items)

    def _pieces_bounds(self, pieces, k, center_y):
        top = bottom = None
        for glyph, off_units in pieces:
            _, by0, _, by1 = self.font.bounds(glyph)
            cy = center_y + off_units * k
            b = cy + by0 * k
            t = cy + by1 * k
            bottom = b if bottom is None else min(bottom, b)
            top = t if top is None else max(top, t)
        return top, bottom

    def _pieces_bottom(self, pieces, k, center_y):
        return self._pieces_bounds(pieces, k, center_y)[1]

    def _fit_pieces(self, pieces, k, center_y, top_need, bottom_need):
        """Center a stretchy assembly, nudging so its ink covers both ends."""
        top, bottom = self._pieces_bounds(pieces, k, center_y)
        if bottom > bottom_need:
            center_y -= bottom - bottom_need
        top, bottom = self._pieces_bounds(pieces, k, center_y)
        if top < top_need:
            center_y += top_need - top
        return center_y

    # -- delimiters ---------------------------------------------------------

    def _layout_paren(self, node, size, level) -> Box:
        inner = self.layout(node["child"], size, level)
        k = size / self.font.upem
        target_units = (inner.height + inner.depth) / k

        items = []
        x = 0.0
        covered_max = 0.0
        center_y = (inner.height - inner.depth) / 2.0
        pieces_by_side = []
        for side in ("left", "right"):
            glyph = DELIMS[node[side]]
            pieces, covered_units = self.font.stretch_vertical(
                self._delim_base_glyph(glyph), target_units)
            covered_max = max(covered_max, covered_units * k)
            width = max(self.font.advance(g) for g, _ in pieces) * k
            pieces_by_side.append(pieces)
            x += width
            if side == "left":
                inner_x = x
                x += inner.width
        # Clamp so the delimiter ink truly covers the full content extent.
        center_y = self._fit_pieces_all(pieces_by_side, k, center_y,
                                        inner.height, -inner.depth)
        x = 0.0
        side_index = 0
        for side in ("left", "right"):
            glyph = DELIMS[node[side]]
            width = max(self.font.advance(g) for g, _ in pieces_by_side[side_index]) * k
            for g, off_units in pieces_by_side[side_index]:
                items.append(("glyph", g, x, center_y + off_units * k, k))
            x += width
            if side == "left":
                x += inner.width
            side_index += 1
        items += [shift_item(it, inner_x, 0.0) for it in inner.items]
        height = max(inner.height, center_y + covered_max / 2.0)
        depth = max(inner.depth, -(center_y - covered_max / 2.0))
        return Box(width=x, height=height, depth=depth, items=items)

    def _fit_pieces_all(self, sides, k, center_y, top_need, bottom_need):
        def bounds(cy):
            top = bottom = None
            for pieces in sides:
                t, b = self._pieces_bounds(pieces, k, cy)
                top = t if top is None else max(top, t)
                bottom = b if bottom is None else min(bottom, b)
            return top, bottom
        top, bottom = bounds(center_y)
        if bottom > bottom_need:
            center_y -= bottom - bottom_need
        top, bottom = bounds(center_y)
        if top < top_need:
            center_y += top_need - top
        return center_y

    def _delim_base_glyph(self, glyph_name: str) -> str:
        # DELIMS maps char -> glyph name; verify against the font cmap.
        return glyph_name
