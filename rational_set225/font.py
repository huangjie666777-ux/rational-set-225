"""Font access layer: metrics, MATH constants, glyph outlines, stretchy assemblies."""
from __future__ import annotations

from dataclasses import dataclass

from fontTools.ttLib import TTFont
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Transform


class FontError(Exception):
    pass


@dataclass
class AssemblyPart:
    glyph: str
    start_connector: float
    end_connector: float
    full_advance: float
    is_extender: bool


@dataclass
class Assembly:
    parts: list[AssemblyPart]
    min_connector: float


class MathFont:
    def __init__(self, path: str):
        self.font = TTFont(path)
        self.upem: int = self.font["head"].unitsPerEm
        self.cmap: dict[int, str] = self.font.getBestCmap()
        self.hmtx = self.font["hmtx"]
        self.glyph_set = self.font.getGlyphSet()
        math = self.font["MATH"].table
        self.constants = {}
        for k, v in math.MathConstants.__dict__.items():
            if isinstance(v, int):
                self.constants[k] = v
            elif hasattr(v, "Value"):
                self.constants[k] = v.Value
        self.variants = math.MathVariants
        italics = math.MathGlyphInfo.MathItalicsCorrectionInfo
        self.italics: dict[str, int] = {
            g: italics.ItalicsCorrection[i].Value
            for i, g in enumerate(italics.Coverage.glyphs)
        }
        self._path_cache: dict[str, str] = {}
        self._bounds_cache: dict[str, tuple[float, float, float, float]] = {}

    def constant(self, name: str) -> int:
        if name not in self.constants:
            raise FontError(f"MATH constant missing: {name}")
        return self.constants[name]

    def glyph_for(self, ch: str) -> str | None:
        return self.cmap.get(ord(ch))

    def advance(self, glyph: str) -> int:
        return self.hmtx[glyph][0]

    def italic_correction(self, glyph: str) -> int:
        return self.italics.get(glyph, 0)

    def bounds(self, glyph: str) -> tuple[float, float, float, float]:
        """Ink bounds (x_min, y_min, x_max, y_max) in font units, y up."""
        if glyph not in self._bounds_cache:
            pen = BoundsPen(self.glyph_set)
            try:
                self.glyph_set[glyph].draw(pen)
            except Exception as exc:
                raise FontError(f"cannot draw glyph {glyph}") from exc
            self._bounds_cache[glyph] = pen.bounds or (0.0, 0.0, 0.0, 0.0)
        return self._bounds_cache[glyph]

    def svg_path(self, glyph: str, scale: float) -> str:
        """Path data scaled and y-flipped for SVG (font y-up -> SVG y-down)."""
        key = f"{glyph}@{scale:.6f}"
        if key not in self._path_cache:
            pen = SVGPathPen(self.glyph_set)
            t = Transform(scale, 0, 0, -scale, 0, 0)
            tpen = TransformPen(pen, t)
            self.glyph_set[glyph].draw(tpen)
            self._path_cache[key] = pen.getCommands()
        return self._path_cache[key]

    def _glyph_span(self, glyph: str) -> float:
        y_min, y_max = self.bounds(glyph)[1], self.bounds(glyph)[3]
        return y_max - y_min

    def _vert_record(self, glyph: str):
        cov = self.variants.VertGlyphCoverage.glyphs
        for i, base in enumerate(cov):
            if base == glyph:
                return self.variants.VertGlyphConstruction[i]
        return None

    def _vert_variants(self, glyph: str) -> list[str]:
        rec = self._vert_record(glyph)
        if rec is None:
            return []
        return [v.VariantGlyph for v in rec.MathGlyphVariantRecord]

    def _vert_assembly(self, glyph: str) -> Assembly | None:
        rec = self._vert_record(glyph)
        if rec is None or rec.GlyphAssembly is None:
            return None
        parts = [
            AssemblyPart(
                glyph=p.glyph,
                start_connector=p.StartConnectorLength,
                end_connector=p.EndConnectorLength,
                full_advance=p.FullAdvance,
                is_extender=bool(p.PartFlags & 0x1),
            )
            for p in rec.GlyphAssembly.PartRecords
        ]
        return Assembly(parts=parts, min_connector=self.variants.MinConnectorOverlap)

    def stretch_vertical(self, glyph: str, target: float):
        """Pick a variant or assembly covering target font units of height.

        Returns (pieces, height): pieces is a list of (glyph, center_offset_up)
        relative to the vertical center of the construction.
        """
        best_glyph, best_h = glyph, self._glyph_span(glyph)
        for var_glyph in self._vert_variants(glyph):
            h = self._glyph_span(var_glyph)
            if h >= target:
                if best_h < target or h < best_h:
                    best_glyph, best_h = var_glyph, h
            elif h > best_h:
                best_glyph, best_h = var_glyph, h
        if best_h >= target:
            return [(best_glyph, 0.0)], best_h

        assembly = self._vert_assembly(glyph)
        if assembly is None:
            return [(best_glyph, 0.0)], best_h
        return self._build_assembly(assembly, target)

    def _build_assembly(self, assembly: Assembly, target: float):
        # Font lists parts bottom-to-top; reverse to top-to-bottom for layout.
        non_ext = [p for p in assembly.parts if not p.is_extender][::-1]
        extenders = [p for p in assembly.parts if p.is_extender]

        if extenders:
            ext = extenders[0]
            sequence: list[AssemblyPart] = []
            for i, part in enumerate(non_ext):
                sequence.append(part)
                if i < len(non_ext) - 1:
                    sequence.append(ext)
            if not sequence:
                sequence = [ext]

            def span_of(seq):
                total = 0.0
                for i, p in enumerate(seq):
                    total += p.full_advance
                    if i:
                        total -= assembly.min_connector
                return total

            guard = 0
            while span_of(sequence) < target and guard < 10000:
                mid = len(sequence) // 2
                idx = min(
                    range(len(sequence)),
                    key=lambda i: (abs(i - mid), 0 if sequence[i].is_extender else 1),
                )
                if sequence[idx].is_extender:
                    sequence.insert(idx, sequence[idx])
                else:
                    sequence.insert(idx, ext)
                guard += 1
            # FullAdvance totals overstate real ink coverage (connector
            # overlap and side bearings shrink the drawn span), so deep
            # content such as nested fractions could still stick out of the
            # assembled glyph. Grow the assembly until its actual ink spans
            # the target as well.
            guard = 0
            while self._sequence_ink_span(sequence, assembly) < target and guard < 10000:
                mid = len(sequence) // 2
                idx = min(
                    range(len(sequence)),
                    key=lambda i: (abs(i - mid), 0 if sequence[i].is_extender else 1),
                )
                if sequence[idx].is_extender:
                    sequence.insert(idx, sequence[idx])
                else:
                    sequence.insert(idx, ext)
                guard += 1
        else:
            sequence = non_ext

        total = 0.0
        for i, p in enumerate(sequence):
            total += p.full_advance
            if i:
                total -= assembly.min_connector
        total = max(total, target)

        pieces: list[tuple[str, float]] = []
        cursor = total / 2.0  # top edge in y-up coords relative to center
        for i, p in enumerate(sequence):
            adv = p.full_advance
            if i:
                cursor += assembly.min_connector
            center = cursor - adv / 2.0
            pieces.append((p.glyph, center))
            cursor -= adv
        return pieces, total

    def _sequence_ink_span(self, sequence, assembly: Assembly) -> float:
        """Actual drawn (ink) height of an assembly sequence, in font units."""
        total = 0.0
        for i, p in enumerate(sequence):
            total += p.full_advance
            if i:
                total -= assembly.min_connector
        cursor = total / 2.0
        top = bottom = None
        for i, p in enumerate(sequence):
            adv = p.full_advance
            if i:
                cursor += assembly.min_connector
            center = cursor - adv / 2.0
            cursor -= adv
            y_min, y_max = self.bounds(p.glyph)[1], self.bounds(p.glyph)[3]
            piece_top, piece_bottom = center + y_max, center + y_min
            top = piece_top if top is None else max(top, piece_top)
            bottom = piece_bottom if bottom is None else min(bottom, piece_bottom)
        if top is None:
            return 0.0
        return top - bottom
