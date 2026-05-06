from models.parsed import ParsedDocument
from parser.vsdx_parser import parse_vsdx
from parser.vsd_converter import convert_vsd_to_odg
from parser.odg_parser import parse_odg


def parse_visio_file(file_path: str) -> tuple[ParsedDocument, str | None]:
    """Parse a .vsd or .vsdx file.

    Returns (parsed_doc, tmpdir_to_cleanup).
    tmpdir_to_cleanup is non-None only for .vsd — the caller must delete it
    (via shutil.rmtree) after the ParsedDocument is no longer needed.
    """
    ext = file_path.rsplit(".", 1)[-1].lower()

    if ext == "vsdx":
        return parse_vsdx(file_path), None

    if ext == "vsd":
        import os
        odg_path = convert_vsd_to_odg(file_path)
        tmpdir = os.path.dirname(odg_path)
        doc = parse_odg(odg_path)
        return doc, tmpdir

    raise ValueError(f"Unsupported file format: .{ext}")
