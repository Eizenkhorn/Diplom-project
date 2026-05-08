"""Extract longitudinal profile segments from a marked horizontal band.

Two formats auto-detected:

  Format A (e.g. Ртищево-Кочетовка):
    Rectangle blocks, each containing two stacked text labels
    (|angle| ‰ on top, length m on bottom) plus an internal diagonal line.
    Slope SIGN is determined from the diagonal line's *rotation* field,
    not from the text label (which contains only the absolute value).

  Format B (e.g. Кропачёво-Дёма):
    Sawtooth of diagonal line segments separated by vertical dividers
    (width ≈ 0, height > 0).  Each segment has one angle-text label (modulus
    only); segment length is computed from coord_mapping pixel→metres.
    Slope sign is again taken from the diagonal line's rotation.

Slope-sign convention (Visio angle stored CCW in Y-up Visio space):
  rotation > 0  →  ascending  →  angle > 0  (in Konva right_y < left_y)
  rotation < 0  →  descending →  angle < 0  (in Konva right_y > left_y)
  |rotation| < 0.3°  →  undetermined  (warning emitted; positive assumed)
"""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from extractors.coordinate_ruler import CoordinateMapping
from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

# ── regexes ───────────────────────────────────────────────────────────────────

_ANGLE_RE = re.compile(r"^[+-]?\d+([.,]\d+)?$")
_LENGTH_RE = re.compile(r"^\d+$")

# ── thresholds ────────────────────────────────────────────────────────────────

# Diagonal-shape classification (for slope sign)
_DIAG_MIN_PX = 1.5              # min width AND height of a diagonal candidate
_NEARLY_HORIZ_H_W = 0.05        # height/width < this → skip (near-horizontal)
_NEARLY_VERT_W_H = 0.10         # width/height < this → skip (near-vertical)
_ROTATION_FLAT_DEG = 0.3        # |rotation| < this → treat as flat

# Format-B vertical separator thresholds
_SEP_MAX_W = 2.0                # separator: width ≤ this (px)
_SEP_MIN_H = 5.0                # separator: height ≥ this (px, absolute)
_SEP_MIN_H_REL = 0.15           # separator: height / band_height ≥ this (relative)
_SEP_DEDUP_DIST = 3.0           # merge separators closer than this (px)


# ── model ─────────────────────────────────────────────────────────────────────

class ProfileSegment(BaseModel):
    start: float   # metres from section start (cumulative)
    end: float
    angle: float   # gradient ‰; positive = uphill, negative = downhill


# ── tiny helpers ──────────────────────────────────────────────────────────────

def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


def _in_band_y(s: ParsedShape, band: HorizontalBand) -> bool:
    return band.y_top <= _cy(s) <= band.y_bottom


def _try_angle(text: str) -> Optional[float]:
    t = text.replace(",", ".").strip()
    if _ANGLE_RE.match(t):
        v = float(t)
        if -99.9 <= v <= 99.9:
            return v
    return None


def _try_length(text: str) -> Optional[int]:
    t = text.strip()
    if _LENGTH_RE.match(t):
        v = int(t)
        if 10 <= v <= 100_000:
            return v
    return None


# ── slope sign from diagonal shapes ──────────────────────────────────────────

def _slope_sign(
    shapes: list[ParsedShape],
    x_left: float,
    x_right: float,
    band: HorizontalBand,
) -> tuple[int, bool]:
    """Return (sign, undetermined_flag).

    sign: +1 ascending, -1 descending, 0 unknown.

    Searches for diagonal line shapes (non-text, non-horizontal, non-vertical)
    whose bounding box overlaps [x_left, x_right] and whose centre-Y is inside
    the band.  Among candidates, picks the one with the longest bounding-box
    diagonal and reads its rotation.

    Rotation convention (Visio CCW in Y-up, stored as-is in ParsedShape):
        rotation > 0  →  ascending  →  sign = +1
        rotation < 0  →  descending →  sign = -1
    """
    candidates: list[ParsedShape] = []
    for s in shapes:
        if s.text is not None:
            continue
        if not _in_band_y(s, band):
            continue
        # Bounding-box must overlap the segment X range
        if s.x + s.width < x_left or s.x > x_right:
            continue
        # Must have meaningful extent in both axes
        if s.width < _DIAG_MIN_PX or s.height < _DIAG_MIN_PX:
            continue
        # Skip near-horizontal (baseline lines etc.)
        if s.height < s.width * _NEARLY_HORIZ_H_W:
            continue
        # Skip near-vertical (separators etc.)
        if s.width < s.height * _NEARLY_VERT_W_H:
            continue
        candidates.append(s)

    if not candidates:
        return 0, True

    # Longest candidate by bbox hypotenuse
    best = max(candidates, key=lambda s: s.width ** 2 + s.height ** 2)
    r = best.rotation

    # Normalise Visio angle to (−90, 90]
    r = ((r + 180.0) % 360.0) - 180.0
    if r > 90.0:
        r -= 180.0
    elif r < -90.0:
        r += 180.0

    if abs(r) < _ROTATION_FLAT_DEG:
        return 0, True

    return (1 if r > 0 else -1), False


# ── format detection ──────────────────────────────────────────────────────────

def _detect_format(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    wa: WorkArea,
) -> tuple[str, int, int]:
    """Return ('A'|'B', n_vertical_separators, n_rect_pairs).

    Format B is selected when there are ≥ 3 vertical separators AND fewer
    large-integer texts (explicit length values) than half the separator count.
    Large-integer texts (value > 100) are a strong indicator of Format A
    because Format B has no explicit length annotations.
    """
    band_h = band.y_bottom - band.y_top

    in_band = [
        s for s in shapes
        if _in_band_y(s, band)
        and wa.x_start <= _cx(s) <= wa.x_end
    ]

    n_sep = sum(
        1 for s in in_band
        if s.text is None
        and s.width <= _SEP_MAX_W
        and s.height >= _SEP_MIN_H
        and s.height >= band_h * _SEP_MIN_H_REL
    )

    # Definite length values: pure digits, value > 100 (cannot be a realistic angle ‰)
    n_lengths = sum(
        1 for s in in_band
        if s.text is not None
        and s.text.strip().isdigit()
        and int(s.text.strip()) > 100
    )

    is_b = n_sep >= 3 and n_lengths < max(1, n_sep) * 0.5
    return ("B" if is_b else "A"), n_sep, n_lengths


# ── Format A ──────────────────────────────────────────────────────────────────

def _extract_format_a(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    wa: WorkArea,
) -> tuple[list[ProfileSegment], dict, list[str]]:
    """Pair angle+length texts, determine slope sign from diagonal rotation."""
    warnings: list[str] = []
    band_mid_y = (band.y_top + band.y_bottom) / 2

    shapes_in_y = [
        s for s in shapes
        if s.text is not None and _in_band_y(s, band)
    ]
    text_shapes = [
        s for s in shapes_in_y
        if wa.x_start <= _cx(s) <= wa.x_end
    ]

    angles: list[tuple[float, float]] = []   # (cx, |angle|)
    lengths: list[tuple[float, int]] = []    # (cx, length_m)
    unclassified: list[str] = []

    for s in text_shapes:
        t = (s.text or "").strip()
        cx = _cx(s)
        cy = _cy(s)

        ang = _try_angle(t)
        if ang is not None and "." not in t and "," not in t and "+" not in t.lstrip("-"):
            # Pure integer — ambiguous between angle and length
            v_int = abs(int(float(t)))
            if v_int > 100:
                lv = _try_length(t)
                if lv is not None:
                    lengths.append((cx, lv))
                continue
            # Small integer: Y-position disambiguates
            if cy <= band_mid_y:
                angles.append((cx, float(v_int)))
            else:
                lv = _try_length(t)
                if lv is not None:
                    lengths.append((cx, lv))
                else:
                    angles.append((cx, float(v_int)))
            continue

        if ang is not None:
            angles.append((cx, abs(ang)))
            continue

        lv = _try_length(t)
        if lv is not None:
            lengths.append((cx, lv))
            continue

        if t:
            unclassified.append(t)

    if unclassified:
        warnings.append(
            f"profile(A): {len(unclassified)} unclassified text(s): "
            + ", ".join(repr(u) for u in unclassified[:5])
        )

    angles.sort(key=lambda p: p[0])
    lengths.sort(key=lambda p: p[0])

    if not angles or not lengths:
        warnings.append(
            f"profile(A): found {len(angles)} angle(s) and {len(lengths)} length(s) — "
            "no segments produced"
        )
        return [], {
            "shapes_in_band_y": len(shapes_in_y),
            "shapes_in_band_xy": len(text_shapes),
            "angle_count": len(angles),
            "length_count": len(lengths),
            "unclassified_count": len(unclassified),
            "found_segments": 0,
            "total_length_meters": 0.0,
            "slope_sign_undetermined": 0,
        }, warnings

    if len(angles) != len(lengths):
        warnings.append(
            f"profile(A): angle count ({len(angles)}) ≠ length count ({len(lengths)}) — "
            "pairing by index; extra items ignored"
        )

    n = min(len(angles), len(lengths))

    # Compute non-overlapping X search bounds per pair
    angle_xs = [ax for ax, _ in angles[:n]]
    seg_bounds: list[tuple[float, float]] = []
    for i in range(n):
        lo = (angle_xs[i - 1] + angle_xs[i]) / 2.0 if i > 0 else wa.x_start
        hi = (angle_xs[i] + angle_xs[i + 1]) / 2.0 if i < n - 1 else wa.x_end
        seg_bounds.append((lo, hi))

    segments: list[ProfileSegment] = []
    cursor = 0.0
    n_undetermined = 0

    for i in range(n):
        _, angle_abs = angles[i]
        _, length_m = lengths[i]
        x_lo, x_hi = seg_bounds[i]

        sign, undet = _slope_sign(shapes, x_lo, x_hi, band)
        if undet:
            n_undetermined += 1
            warnings.append(
                f"profile(A): slope sign undetermined for segment {i + 1} "
                f"(|angle|={angle_abs}‰, x_range={x_lo:.0f}–{x_hi:.0f}px) — assuming positive"
            )
            sign = 1

        segments.append(ProfileSegment(
            start=cursor,
            end=cursor + length_m,
            angle=sign * angle_abs,
        ))
        cursor += length_m

    return segments, {
        "shapes_in_band_y": len(shapes_in_y),
        "shapes_in_band_xy": len(text_shapes),
        "angle_count": len(angles),
        "length_count": len(lengths),
        "unclassified_count": len(unclassified),
        "found_segments": len(segments),
        "total_length_meters": cursor,
        "slope_sign_undetermined": n_undetermined,
    }, warnings


# ── Format B ──────────────────────────────────────────────────────────────────

def _extract_format_b(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    wa: WorkArea,
    coord_mapping: CoordinateMapping,
) -> tuple[list[ProfileSegment], dict, list[str]]:
    """Vertical-divider segments; length from coord_mapping; sign from rotation."""
    warnings: list[str] = []
    band_h = band.y_bottom - band.y_top

    in_band_wa = [
        s for s in shapes
        if _in_band_y(s, band) and wa.x_start <= _cx(s) <= wa.x_end
    ]

    # Vertical separators: narrow, tall, no text
    raw_seps = sorted(
        [
            s for s in in_band_wa
            if s.text is None
            and s.width <= _SEP_MAX_W
            and s.height >= _SEP_MIN_H
            and s.height >= band_h * _SEP_MIN_H_REL
        ],
        key=_cx,
    )

    # Build segment X boundaries, de-duplicating close separators
    boundaries: list[float] = [wa.x_start]
    for sep in raw_seps:
        cx = _cx(sep)
        if cx - boundaries[-1] > _SEP_DEDUP_DIST:
            boundaries.append(cx)
    if boundaries[-1] < wa.x_end - _SEP_DEDUP_DIST:
        boundaries.append(wa.x_end)

    n_shapes_y = len([s for s in shapes if _in_band_y(s, band)])

    if len(boundaries) < 2:
        warnings.append(
            f"profile(B): only {len(boundaries)} boundary found "
            f"({len(raw_seps)} raw separators) — no segments produced"
        )
        return [], {
            "shapes_in_band_y": n_shapes_y,
            "shapes_in_band_xy": len(in_band_wa),
            "angle_count": 0,
            "length_count": 0,
            "unclassified_count": 0,
            "vertical_dividers": len(raw_seps),
            "found_segments": 0,
            "total_length_meters": 0.0,
            "slope_sign_undetermined": 0,
        }, warnings

    # Collect all angle texts in the band+WA
    angle_texts: list[tuple[float, float]] = []  # (cx, |angle|)
    for s in in_band_wa:
        if s.text is None:
            continue
        ang = _try_angle(s.text)
        if ang is not None:
            angle_texts.append((_cx(s), abs(ang)))

    segments: list[ProfileSegment] = []
    cursor = 0.0
    n_undetermined = 0
    n_no_text = 0

    for i in range(len(boundaries) - 1):
        x_left = boundaries[i]
        x_right = boundaries[i + 1]
        seg_cx = (x_left + x_right) / 2.0

        # Find the angle text whose cx is nearest to segment centre and within segment
        angle_abs = 0.0
        if angle_texts:
            best = min(angle_texts, key=lambda p: abs(p[0] - seg_cx))
            if abs(best[0] - seg_cx) <= (x_right - x_left) * 0.6:
                angle_abs = best[1]
            else:
                n_no_text += 1
                warnings.append(
                    f"profile(B): no angle text in segment {i + 1} "
                    f"(x={x_left:.0f}–{x_right:.0f}px)"
                )
        else:
            n_no_text += 1

        # Slope sign from diagonal shapes in this segment
        sign, undet = _slope_sign(shapes, x_left, x_right, band)
        if undet:
            n_undetermined += 1
            warnings.append(
                f"profile(B): slope sign undetermined for segment {i + 1} "
                f"(x={x_left:.0f}–{x_right:.0f}px) — assuming positive"
            )
            sign = 1

        # Length from coordinate mapping (absolute value: handles descending rulers)
        net_left = coord_mapping.x_to_network_coord(x_left)
        net_right = coord_mapping.x_to_network_coord(x_right)
        length_m = abs(net_right - net_left)

        if length_m < 1.0:
            warnings.append(
                f"profile(B): segment {i + 1} has near-zero length "
                f"({length_m:.2f}m) — skipped"
            )
            continue

        segments.append(ProfileSegment(
            start=cursor,
            end=cursor + length_m,
            angle=sign * angle_abs,
        ))
        cursor += length_m

    return segments, {
        "shapes_in_band_y": n_shapes_y,
        "shapes_in_band_xy": len(in_band_wa),
        "angle_count": len(angle_texts),
        "length_count": 0,           # no explicit length texts in Format B
        "unclassified_count": 0,
        "vertical_dividers": len(raw_seps),
        "found_segments": len(segments),
        "total_length_meters": cursor,
        "slope_sign_undetermined": n_undetermined,
        "segments_without_angle_text": n_no_text,
    }, warnings


# ── public API ────────────────────────────────────────────────────────────────

def extract_profile(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
    coord_mapping: Optional[CoordinateMapping] = None,
) -> tuple[list[ProfileSegment], dict, list[str]]:
    """Parse the profile band into a list of ProfileSegment.

    Auto-detects Format A (explicit length texts, slope sign from rotation) or
    Format B (vertical dividers, lengths from coord_mapping, slope sign from rotation).

    Returns (segments, log_dict, warnings).
    """
    warnings: list[str] = []

    fmt, n_sep, n_lengths = _detect_format(shapes, band, work_area)

    if fmt == "B" and coord_mapping is None:
        warnings.append(
            "profile: Format B detected but no coord_mapping provided — "
            "falling back to Format A"
        )
        fmt = "A"

    if fmt == "A":
        segs, inner, w = _extract_format_a(shapes, band, work_area)
    else:
        segs, inner, w = _extract_format_b(shapes, band, work_area, coord_mapping)  # type: ignore[arg-type]

    warnings.extend(w)

    log = {
        "format_detected": fmt,
        "vertical_dividers": n_sep,
        "rectangles_with_two_texts": n_lengths,
        **inner,
        "total_length_km": round(inner.get("total_length_meters", 0.0) / 1000.0, 2),
    }

    return segs, log, warnings
