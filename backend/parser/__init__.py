import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor  # used for vsdx parallel path

from models.parsed import ParsedDocument
from parser.vsdx_parser import parse_vsdx
from parser.visio_converter import convert_vsd_to_odg, convert_to_background
from parser.odg_parser import parse_odg

logger = logging.getLogger(__name__)


def _try_convert_to_background(input_path: str) -> tuple[str, str]:
    """Like convert_to_background but returns ("", "") on failure."""
    try:
        return convert_to_background(input_path)
    except Exception as exc:
        logger.warning("Background image conversion failed (canvas will show blank): %s", exc)
        return "", ""


def parse_visio_file(file_path: str) -> tuple[ParsedDocument, str, list[str]]:
    """Parse a .vsd or .vsdx file and produce a background image for the canvas.

    For .vsdx: parses geometry (Python-only) and converts to background image in parallel.
    For .vsd:  runs ODG and background conversions sequentially to avoid LibreOffice
               profile lock conflicts from two simultaneous soffice instances.

    Returns (doc, bg_image_path, tmpdirs_to_keep).
    bg_image_path may be "" if background conversion failed.
    tmpdirs_to_keep must persist as long as the session lives (they hold the image file).

    NOTE: No coordinate rescaling is applied. KonvaImage renders at width=page_width,
    height=page_height, so the background stretches to fill the canvas exactly and
    bboxes (in page-pixel space) align with the image regardless of image resolution.
    """
    ext = file_path.rsplit(".", 1)[-1].lower()

    if ext == "vsdx":
        with ThreadPoolExecutor(max_workers=2) as pool:
            doc_fut = pool.submit(parse_vsdx, file_path)
            bg_fut = pool.submit(_try_convert_to_background, file_path)
        doc = doc_fut.result()
        bg_path, bg_tmpdir = bg_fut.result()

    elif ext == "vsd":
        # Two sequential soffice calls: running them in parallel causes both to hang
        # because LibreOffice locks its shared user-profile directory.
        odg_path = convert_vsd_to_odg(file_path)
        odg_tmpdir = os.path.dirname(odg_path)
        try:
            doc = parse_odg(odg_path)
        finally:
            shutil.rmtree(odg_tmpdir, ignore_errors=True)
        bg_path, bg_tmpdir = _try_convert_to_background(file_path)

    else:
        raise ValueError(f"Unsupported file format: .{ext}")

    tmpdirs = [bg_tmpdir] if bg_tmpdir else []
    return doc, bg_path, tmpdirs
