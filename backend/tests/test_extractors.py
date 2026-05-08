"""Unit tests for the extractor pipeline (coordinate_ruler, profile, speed_limits, stations)."""
import pytest

from extractors.coordinate_ruler import CoordinateMapping, extract_coordinate_ruler
from extractors.profile import extract_profile
from extractors.speed_limits import extract_speed_limits
from extractors.stations import extract_stations
from models.markup import HorizontalBand, StationPoint, WorkArea
from models.parsed import ParsedShape


# ── helpers ────────────────────────────────────────────────────────────────────

def _shape(
    id: str, x: float, y: float, w: float, h: float,
    text: str | None = None,
    line_color: str | None = None,
    fill_color: str | None = None,
) -> ParsedShape:
    return ParsedShape(
        id=id, text=text, x=x, y=y, width=w, height=h,
        rotation=0.0, shape_type="Shape", parent_id=None,
        line_color=line_color, fill_color=fill_color,
    )


def _band(type: str, y_top: float, y_bottom: float) -> HorizontalBand:
    return HorizontalBand(id="b1", type=type, y_top=y_top, y_bottom=y_bottom)  # type: ignore[arg-type]


def _wa(x_start: float = 0.0, x_end: float = 1000.0) -> WorkArea:
    return WorkArea(x_start=x_start, x_end=x_end)


# ── CoordinateMapping ──────────────────────────────────────────────────────────

class TestCoordinateMapping:
    def test_two_point_ascending(self):
        m = CoordinateMapping(points=[(0.0, 100), (1000.0, 200)], direction="ascending")
        assert m.x_to_network_coord(0.0) == pytest.approx(100_000)
        assert m.x_to_network_coord(500.0) == pytest.approx(150_000)
        assert m.x_to_network_coord(1000.0) == pytest.approx(200_000)

    def test_two_point_descending(self):
        m = CoordinateMapping(points=[(0.0, 200), (1000.0, 100)], direction="descending")
        assert m.x_to_network_coord(0.0) == pytest.approx(200_000)
        assert m.x_to_network_coord(1000.0) == pytest.approx(100_000)

    def test_extrapolation_left(self):
        m = CoordinateMapping(points=[(100.0, 10), (200.0, 20)], direction="ascending")
        result = m.x_to_network_coord(0.0)
        assert result == pytest.approx(0.0)

    def test_extrapolation_right(self):
        m = CoordinateMapping(points=[(0.0, 10), (100.0, 20)], direction="ascending")
        result = m.x_to_network_coord(200.0)
        assert result == pytest.approx(30_000)

    def test_single_point(self):
        m = CoordinateMapping(points=[(500.0, 150)], direction="ascending")
        assert m.x_to_network_coord(0.0) == pytest.approx(150_000)
        assert m.x_to_network_coord(999.0) == pytest.approx(150_000)

    def test_empty_points(self):
        m = CoordinateMapping(points=[], direction="ascending")
        assert m.x_to_network_coord(100.0) == 0.0


# ── extract_coordinate_ruler ───────────────────────────────────────────────────

class TestExtractCoordinateRuler:
    def _km_shapes(self, kms: list[tuple[float, int]], band_y: float = 50.0) -> list[ParsedShape]:
        return [
            _shape(f"km{km}", cx - 5, band_y - 5, 10, 10, text=str(km))
            for cx, km in kms
        ]

    def test_ascending_ruler(self):
        shapes = self._km_shapes([(100, 10), (200, 20), (300, 30)])
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        mapping, log, warnings = extract_coordinate_ruler(shapes, band, wa)

        assert mapping.direction == "ascending"
        assert len(mapping.points) == 3
        assert not any("non-monotone" in w for w in warnings)

    def test_descending_ruler(self):
        shapes = self._km_shapes([(100, 300), (200, 200), (300, 100)])
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        mapping, log, warnings = extract_coordinate_ruler(shapes, band, wa)

        assert mapping.direction == "descending"
        assert len(mapping.points) == 3

    def test_too_few_labels_warns(self):
        shapes = self._km_shapes([(100, 10)])
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        mapping, log, warnings = extract_coordinate_ruler(shapes, band, wa)

        assert any("only 1" in w for w in warnings)

    def test_non_km_labels_ignored(self):
        shapes = self._km_shapes([(100, 10), (200, 20)])
        shapes.append(_shape("noise", 150, 45, 10, 10, text="км"))
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        mapping, _, _ = extract_coordinate_ruler(shapes, band, wa)
        assert len(mapping.points) == 2

    def test_shapes_outside_work_area_ignored(self):
        shapes = self._km_shapes([(100, 10), (200, 20), (600, 30)])  # 600 outside wa
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        mapping, _, _ = extract_coordinate_ruler(shapes, band, wa)
        assert len(mapping.points) == 2

    def test_shapes_outside_band_ignored(self):
        shapes = self._km_shapes([(100, 10), (200, 20)])
        shapes.append(_shape("outside", 300, 5, 10, 10, text="30"))  # y center = 10, outside band 40-70
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        mapping, _, _ = extract_coordinate_ruler(shapes, band, wa)
        assert len(mapping.points) == 2

    def test_duplicate_values_rejected(self):
        """Values appearing ≥2 times (speed-scale contamination) are rejected."""
        # km 10 appears twice → rejected; km 20 and 30 are unique → kept
        shapes = self._km_shapes([(100, 10), (200, 20), (300, 30)])
        shapes.append(_shape("dup", 50, 45, 10, 10, text="10"))  # second occurrence of 10
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        mapping, log, warnings = extract_coordinate_ruler(shapes, band, wa)

        assert log["rejected_duplicate_values"] == 1
        assert 10 in log["rejected_values_list"]
        # Only km 20 and 30 survive
        km_values = [km for _, km in mapping.points]
        assert 10 not in km_values
        assert len(mapping.points) == 2

    def test_km_hints_used_when_no_labels(self):
        """When no km labels are found, km hints should be used as anchors."""
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 1000)
        mapping, _, warnings = extract_coordinate_ruler([], band, wa, km_hint_start=100, km_hint_end=200)

        assert len(mapping.points) == 2
        assert any("hint" in w for w in warnings)

    def test_log_has_required_fields(self):
        shapes = self._km_shapes([(100, 10), (200, 20)])
        band = _band("coordinate_ruler", 40, 70)
        wa = _wa(0, 500)
        _, log, _ = extract_coordinate_ruler(shapes, band, wa)

        for field in ("shapes_in_band_y", "shapes_in_band_xy", "kilometer_candidates",
                      "unique_values", "rejected_duplicate_values", "found_kilometers",
                      "direction", "range"):
            assert field in log


# ── extract_profile ────────────────────────────────────────────────────────────

class TestExtractProfile:
    def test_basic_two_segments(self):
        band = _band("profile", 100, 200)
        wa = _wa(0, 1000)
        shapes = [
            _shape("a1", 95, 110, 10, 10, text="-8.3"),   # angle, top half
            _shape("l1", 95, 170, 10, 10, text="840"),     # length, bottom half
            _shape("a2", 195, 110, 10, 10, text="-0.1"),
            _shape("l2", 195, 170, 10, 10, text="210"),
        ]
        segs, log, warnings = extract_profile(shapes, band, wa)

        assert len(segs) == 2
        assert segs[0].angle == pytest.approx(-8.3)
        assert segs[0].start == pytest.approx(0.0)
        assert segs[0].end == pytest.approx(840.0)
        assert segs[1].angle == pytest.approx(-0.1)
        assert segs[1].start == pytest.approx(840.0)
        assert segs[1].end == pytest.approx(1050.0)

    def test_no_shapes_returns_empty(self):
        band = _band("profile", 100, 200)
        wa = _wa(0, 1000)
        segs, log, warnings = extract_profile([], band, wa)
        assert segs == []
        assert warnings

    def test_angle_length_mismatch_warns(self):
        band = _band("profile", 100, 200)
        wa = _wa(0, 1000)
        shapes = [
            _shape("a1", 95, 110, 10, 10, text="-8.3"),
            _shape("a2", 195, 110, 10, 10, text="-0.1"),
            _shape("l1", 95, 170, 10, 10, text="840"),
        ]
        segs, log, warnings = extract_profile(shapes, band, wa)
        assert len(segs) == 1
        assert any("angle count" in w for w in warnings)

    def test_comma_decimal_angle(self):
        """Regression: '2,5' (European decimal comma) must not crash."""
        band = _band("profile", 100, 200)
        wa = _wa(0, 1000)
        shapes = [
            _shape("a1", 95, 110, 10, 10, text="2,5"),   # angle with comma separator
            _shape("l1", 95, 170, 10, 10, text="1200"),
        ]
        segs, log, warnings = extract_profile(shapes, band, wa)
        assert len(segs) == 1
        assert segs[0].angle == pytest.approx(2.5)
        assert segs[0].end == pytest.approx(1200.0)

    def test_large_integer_treated_as_length(self):
        band = _band("profile", 100, 200)
        wa = _wa(0, 1000)
        shapes = [
            _shape("a1", 95, 110, 10, 10, text="5"),
            _shape("l1", 95, 170, 10, 10, text="1500"),
        ]
        segs, _, _ = extract_profile(shapes, band, wa)
        assert len(segs) == 1
        assert segs[0].end == pytest.approx(1500.0)

    def test_log_has_required_fields(self):
        band = _band("profile", 100, 200)
        wa = _wa(0, 1000)
        shapes = [
            _shape("a1", 95, 110, 10, 10, text="-5"),
            _shape("l1", 95, 170, 10, 10, text="500"),
        ]
        _, log, _ = extract_profile(shapes, band, wa)
        for field in ("shapes_in_band_y", "shapes_in_band_xy", "angle_count",
                      "length_count", "found_segments", "total_length_meters"):
            assert field in log


# ── extract_speed_limits ───────────────────────────────────────────────────────

class TestExtractSpeedLimits:
    def _scale_shapes(self, band: HorizontalBand, wa: WorkArea) -> list[ParsedShape]:
        # Speed scale labels in left margin.
        # Red test lines are placed at y=291 height=0 → cy=291.
        # s40 must be within ±3px of cy=291: y=286, h=10 → cy=291 ✓
        return [
            _shape("s0",  wa.x_start + 5, 375, 20, 10, text="0"),   # cy=380
            _shape("s40", wa.x_start + 5, 286, 20, 10, text="40"),  # cy=291
            _shape("s80", wa.x_start + 5, 215, 20, 10, text="80"),  # cy=220
        ]

    def test_no_shapes_returns_empty(self):
        band = _band("speed_limits", 200, 400)
        wa = _wa(0, 2000)
        segs, log, warnings = extract_speed_limits([], band, wa,
            CoordinateMapping(points=[(0, 0), (2000, 200)], direction="ascending"))
        assert segs == []

    def test_red_line_extracted(self):
        band = _band("speed_limits", 200, 400)
        wa = _wa(0, 2000)
        coord = CoordinateMapping(
            points=[(0.0, 1800), (2000.0, 1600)], direction="descending"
        )
        scale = self._scale_shapes(band, wa)
        # Red horizontal line: height=0 (degenerate), cy=291 → snaps to s40 (cy=291, dist=0)
        red_line = _shape("rl", 100, 291, 500, 0, line_color="#ff0000")
        segs, log, warnings = extract_speed_limits(scale + [red_line], band, wa, coord)

        assert len(segs) == 1
        assert segs[0].limit == 40
        assert log["used_color_filter"] is True

    def test_adjacent_same_speed_merged(self):
        band = _band("speed_limits", 200, 400)
        wa = _wa(0, 2000)
        coord = CoordinateMapping(
            points=[(0.0, 0), (2000.0, 2000)], direction="ascending"
        )
        scale = self._scale_shapes(band, wa)
        # Two adjacent red lines: height=0, cy=291 → snap to s40; x-ranges touch → merged
        r1 = _shape("r1", 100, 291, 300, 0, line_color="#cc0000")
        r2 = _shape("r2", 400, 291, 300, 0, line_color="#cc0000")
        segs, log, _ = extract_speed_limits(scale + [r1, r2], band, wa, coord)

        assert len(segs) == 1
        assert segs[0].limit == 40

    def test_fallback_to_all_lines_when_no_red(self):
        band = _band("speed_limits", 200, 400)
        wa = _wa(0, 2000)
        coord = CoordinateMapping(
            points=[(0.0, 0), (2000.0, 2000)], direction="ascending"
        )
        scale = self._scale_shapes(band, wa)
        grey_line = _shape("gl", 100, 289, 500, 4, line_color="#888888")
        segs, log, warnings = extract_speed_limits(scale + [grey_line], band, wa, coord)

        assert log["used_color_filter"] is False
        assert any("no red-colored" in w for w in warnings)

    def test_broadened_red_tolerance(self):
        """Colors with R=140, G=90, B=90 must be treated as red."""
        band = _band("speed_limits", 200, 400)
        wa = _wa(0, 2000)
        coord = CoordinateMapping(
            points=[(0.0, 0), (2000.0, 2000)], direction="ascending"
        )
        scale = self._scale_shapes(band, wa)
        # Borderline red: R=140, G=90, B=90 → hex #8c5a5a; height=0 so classified horizontal
        borderline_red = _shape("br", 100, 291, 500, 0, line_color="#8c5a5a")
        segs, log, _ = extract_speed_limits(scale + [borderline_red], band, wa, coord)
        assert log["used_color_filter"] is True

    def test_log_has_required_fields(self):
        band = _band("speed_limits", 200, 400)
        wa = _wa(0, 2000)
        coord = CoordinateMapping(points=[(0, 0), (2000, 200)], direction="ascending")
        _, log, _ = extract_speed_limits([], band, wa, coord)
        for field in ("shapes_in_band", "scale_labels_raw", "scale_labels_deduped",
                      "scale_speeds", "candidate_line_shapes", "red_lines",
                      "used_color_filter", "found_segments"):
            assert field in log


# ── extract_stations ───────────────────────────────────────────────────────────

class TestExtractStations:
    def test_basic_stations_sorted_ascending(self):
        coord = CoordinateMapping(
            points=[(0.0, 100), (1000.0, 200)], direction="ascending"
        )
        pts = [
            StationPoint(id="s1", x=700.0, name="Б"),
            StationPoint(id="s2", x=200.0, name="А"),
        ]
        stations, log, warnings = extract_stations(pts, coord)

        assert len(stations) == 2
        assert stations[0]["name"] == "А"
        assert stations[1]["name"] == "Б"

    def test_stations_sorted_descending(self):
        coord = CoordinateMapping(
            points=[(0.0, 200), (1000.0, 100)], direction="descending"
        )
        pts = [
            StationPoint(id="s1", x=200.0, name="А"),   # km≈180
            StationPoint(id="s2", x=800.0, name="Б"),   # km≈120
        ]
        stations, log, warnings = extract_stations(pts, coord)

        assert stations[0]["name"] == "А"   # higher coordinate = first for descending
        assert stations[1]["name"] == "Б"

    def test_empty_stations_warns(self):
        coord = CoordinateMapping(
            points=[(0.0, 100), (1000.0, 200)], direction="ascending"
        )
        stations, log, warnings = extract_stations([], coord)
        assert stations == []
        assert any("no station" in w for w in warnings)

    def test_graphical_fields_present(self):
        coord = CoordinateMapping(
            points=[(0.0, 1000), (1000.0, 2000)], direction="ascending"
        )
        pts = [StationPoint(id="s1", x=500.0, name="Тест")]
        stations, log, _ = extract_stations(pts, coord)

        g = stations[0]["graphical"]
        assert "coordinate" in g
        assert "fontSize" in g
        assert g["coordinate"] == stations[0]["coordinate"]

    def test_log_has_count(self):
        coord = CoordinateMapping(
            points=[(0.0, 100), (1000.0, 200)], direction="ascending"
        )
        pts = [StationPoint(id="s1", x=500.0, name="X")]
        _, log, _ = extract_stations(pts, coord)
        assert log["count"] == 1
        assert "coordinates" in log
