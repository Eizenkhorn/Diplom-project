"""Extract longitudinal profile segments from a marked horizontal band."""
from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel

from models.markup import HorizontalBand, WorkArea
from models.parsed import ParsedShape

# Angle: optional sign + digits + optional decimal (e.g. -8.3, 0, 1.4, +2.0)
_ANGLE_RE = re.compile(r"^[+-]?\d+([.,]\d+)?$")
# Length: plain positive integer (no sign, no decimal)
_LENGTH_RE = re.compile(r"^\d+$")


class ProfileSegment(BaseModel):
    start: float   # metres from start of section (cumulative)
    end: float
    angle: float   # gradient in ‰; positive = uphill


def _cx(s: ParsedShape) -> float:
    return s.x + s.width / 2


def _cy(s: ParsedShape) -> float:
    return s.y + s.height / 2


def _in_band(s: ParsedShape, band: HorizontalBand, wa: WorkArea) -> bool:
    return (
        band.y_top <= _cy(s) <= band.y_bottom
        and wa.x_start <= _cx(s) <= wa.x_end
    )


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


def extract_profile(
    shapes: list[ParsedShape],
    band: HorizontalBand,
    work_area: WorkArea,
) -> tuple[list[ProfileSegment], list[str]]:
    """Parse the profile band into a list of ProfileSegment.

    Strategy:
    1. Collect all text shapes inside the band.
    2. Classify as angle (float ‰) or length (positive int m).
    3. Sort both lists by X center.
    4. Pair them: the i-th angle with the i-th length.
       Disambiguation for integers ≤ 100 that could be either:
       use Y position (top-half = angle, bottom-half = length).
    5. Build cumulative start/end.

    Returns (segments, warnings).
    """
    warnings: list[str] = []
    band_mid_y = (band.y_top + band.y_bottom) / 2

    text_shapes = [
        s for s in shapes
        if s.text is not None and _in_band(s, band, work_area)
    ]

    angles: list[tuple[float, float]] = []   # (cx, angle_value)
    lengths: list[tuple[float, int]] = []    # (cx, length_m)
    unclassified: list[str] = []

    for s in text_shapes:
        t = (s.text or "").strip()
        cx = _cx(s)
        cy = _cy(s)

        ang = _try_angle(t)
        if ang is not None and "." not in t.replace("-", "") and "+" not in t:
            # Pure integer — could be angle OR length
            v_int = int(float(t))
            if v_int > 100:
                # Can't be a realistic angle ‰
                length = _try_length(t)
                if length is not None:
                    lengths.append((cx, length))
                continue
            # Ambiguous: use Y position
            if cy <= band_mid_y:
                angles.append((cx, ang))
            else:
                length = _try_length(t)
                if length is not None:
                    lengths.append((cx, length))
                else:
                    angles.append((cx, ang))
            continue

        if ang is not None:
            angles.append((cx, ang))
            continue

        length = _try_length(t)
        if length is not None:
            lengths.append((cx, length))
            continue

        if t:
            unclassified.append(t)

    if unclassified:
        warnings.append(
            f"profile: {len(unclassified)} unclassified text(s): "
            + ", ".join(repr(u) for u in unclassified[:5])
        )

    angles.sort(key=lambda p: p[0])
    lengths.sort(key=lambda p: p[0])

    if not angles or not lengths:
        warnings.append(
            f"profile: found {len(angles)} angle(s) and {len(lengths)} length(s) — "
            "no segments produced"
        )
        return [], warnings

    if len(angles) != len(lengths):
        warnings.append(
            f"profile: angle count ({len(angles)}) ≠ length count ({len(lengths)}) — "
            "pairing by index; extra items ignored"
        )

    n = min(len(angles), len(lengths))
    segments: list[ProfileSegment] = []
    cursor = 0.0
    for i in range(n):
        _, angle = angles[i]
        _, length_m = lengths[i]
        seg = ProfileSegment(start=cursor, end=cursor + length_m, angle=angle)
        segments.append(seg)
        cursor += length_m

    return segments, warnings
