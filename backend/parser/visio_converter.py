import logging
import os
import shutil
import subprocess
import tempfile

logger = logging.getLogger(__name__)

_WINDOWS_PATHS = [
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]
_LINUX_PATHS = ["/usr/bin/soffice", "/usr/local/bin/soffice"]


def _find_soffice() -> str:
    env_path = os.environ.get("LIBREOFFICE_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path

    which = shutil.which("soffice")
    if which:
        return which

    for candidate in _WINDOWS_PATHS + _LINUX_PATHS:
        if os.path.isfile(candidate):
            return candidate

    raise RuntimeError(
        "LibreOffice not found. Install it or set LIBREOFFICE_PATH env var."
    )


_CREATE_NO_WINDOW = 0x08000000  # Windows: don't allocate a console window for soffice


def _run_soffice(cmd: list[str], tmpdir: str, timeout: int = 120) -> None:
    """Run a soffice command, raising RuntimeError on failure.

    stdout/stderr are discarded (piping them causes soffice's child process to
    keep the inherited handles open on Windows, making subprocess.run hang).
    stdin is NOT redirected — LibreOffice headless hangs when stdin is a closed
    pipe (DEVNULL).  CREATE_NO_WINDOW prevents a console window from appearing.
    """
    import sys
    kwargs: dict = dict(
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
    )
    if sys.platform == "win32":
        kwargs["creationflags"] = _CREATE_NO_WINDOW

    try:
        result = subprocess.run(cmd, **kwargs)
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"LibreOffice timed out after {timeout}s") from None

    if result.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(f"LibreOffice exited with code {result.returncode}")


def convert_vsd_to_odg(vsd_path: str) -> str:
    """Convert a .vsd file to .odg using LibreOffice headless.

    The input is copied to an ASCII filename inside a new tmpdir to avoid
    encoding issues when passing Cyrillic paths to soffice on Windows.
    Returns the path to 'input.odg' inside that tmpdir.
    The caller is responsible for deleting the tmpdir when done.
    """
    soffice = _find_soffice()
    tmpdir = tempfile.mkdtemp(prefix="vsd_convert_")
    logger.info("Converting %s → odg in %s", vsd_path, tmpdir)

    input_copy = os.path.join(tmpdir, "input.vsd")
    shutil.copy2(vsd_path, input_copy)

    _run_soffice(
        [soffice, "--headless", "--convert-to", "odg", "--outdir", tmpdir, input_copy],
        tmpdir,
    )

    odg_path = os.path.join(tmpdir, "input.odg")
    if not os.path.isfile(odg_path):
        candidates = [f for f in os.listdir(tmpdir) if f.lower().endswith(".odg")]
        if not candidates:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise RuntimeError(f"No .odg produced in {tmpdir} after conversion")
        odg_path = os.path.join(tmpdir, candidates[0])

    logger.info("Converted to %s", odg_path)
    return odg_path


def _convert_to_format(input_path: str, fmt: str) -> tuple[str, str]:
    """Convert input file to the given format (e.g. 'svg' or 'png').

    Returns (output_path, output_tmpdir).
    """
    soffice = _find_soffice()
    out_tmpdir = tempfile.mkdtemp(prefix=f"{fmt}_convert_")
    ext = input_path.rsplit(".", 1)[-1].lower()
    input_copy = os.path.join(out_tmpdir, f"input.{ext}")
    shutil.copy2(input_path, input_copy)
    logger.info("Converting %s → %s in %s", input_path, fmt, out_tmpdir)

    _run_soffice(
        [soffice, "--headless", "--convert-to", fmt, "--outdir", out_tmpdir, input_copy],
        out_tmpdir,
    )

    out_path = os.path.join(out_tmpdir, f"input.{fmt}")
    if not os.path.isfile(out_path):
        candidates = [f for f in os.listdir(out_tmpdir) if f.lower().endswith(f".{fmt}")]
        if not candidates:
            shutil.rmtree(out_tmpdir, ignore_errors=True)
            raise RuntimeError(f"No .{fmt} file produced in {out_tmpdir}")
        out_path = os.path.join(out_tmpdir, candidates[0])

    logger.info("Produced %s", out_path)
    return out_path, out_tmpdir


def convert_to_background(input_path: str) -> tuple[str, str]:
    """Convert .vsd or .vsdx to a background image for the canvas.

    Tries SVG first (vector, resolution-independent); falls back to PNG
    if SVG export is unavailable on this LibreOffice installation.
    Returns (image_path, image_tmpdir).
    """
    try:
        return _convert_to_format(input_path, "svg")
    except RuntimeError as svg_err:
        logger.warning("SVG export failed (%s), falling back to PNG", svg_err)
    return _convert_to_format(input_path, "png")
