import math
import pathlib
import pytest

from parser.vsdx_parser import parse_vsdx
from models.parsed import ParsedDocument

SAMPLES = pathlib.Path(__file__).parent.parent.parent / "samples"
VSDX_FILE = SAMPLES / "Кропачево-Дема Visio.vsdx"


@pytest.fixture(scope="module")
def doc() -> ParsedDocument:
    return parse_vsdx(str(VSDX_FILE))


def test_page_dimensions_positive(doc: ParsedDocument):
    assert doc.page_width > 0
    assert doc.page_height > 0


def test_shape_count(doc: ParsedDocument):
    assert len(doc.shapes) > 100, f"Expected >100 shapes, got {len(doc.shapes)}"


def test_coordinates_finite(doc: ParsedDocument):
    bad = [
        s.id
        for s in doc.shapes
        if not all(
            math.isfinite(v)
            for v in (s.x, s.y, s.width, s.height, s.rotation)
        )
    ]
    assert bad == [], f"Non-finite coords in shapes: {bad[:10]}"


def test_at_least_one_text(doc: ParsedDocument):
    texts = [s.text for s in doc.shapes if s.text]
    assert texts, "No shape has non-empty text"


def test_parent_ids_valid(doc: ParsedDocument):
    all_ids = {s.id for s in doc.shapes}
    bad = [
        s.id
        for s in doc.shapes
        if s.parent_id is not None and s.parent_id not in all_ids
    ]
    assert bad == [], f"parent_id references missing IDs: {bad[:10]}"


def test_shape_types_known(doc: ParsedDocument):
    known = {"Shape", "Group", "Foreign", "Connector"}
    unknown = {s.shape_type for s in doc.shapes} - known
    assert unknown == set(), f"Unexpected shape_type values: {unknown}"


def test_dimensions_non_negative(doc: ParsedDocument):
    bad = [s.id for s in doc.shapes if s.width < 0 or s.height < 0]
    assert bad == [], f"Negative width/height in: {bad[:10]}"
