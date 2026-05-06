from models.parsed import ParsedDocument
from parser.vsdx_parser import parse_vsdx
from parser.vsd_converter import convert_vsd_to_vsdx


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
        vsdx_path = convert_vsd_to_vsdx(file_path)
        import os
        tmpdir = os.path.dirname(vsdx_path)
        doc = parse_vsdx(vsdx_path)
        return doc, tmpdir

    raise ValueError(f"Unsupported file format: .{ext}")
