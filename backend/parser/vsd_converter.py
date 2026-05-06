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
    """Return path to soffice binary, or raise RuntimeError if not found."""
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


def convert_vsd_to_vsdx(vsd_path: str) -> str:
    """Convert a .vsd file to .vsdx using LibreOffice headless.

    Returns the path to the converted .vsdx inside a freshly-created tmpdir.
    The caller is responsible for deleting that tmpdir when done.
    """
    soffice = _find_soffice()
    tmpdir = tempfile.mkdtemp(prefix="vsd_convert_")
    logger.info("Converting %s → vsdx in %s", vsd_path, tmpdir)

    cmd = [soffice, "--headless", "--convert-to", "vsdx", "--outdir", tmpdir, vsd_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError("LibreOffice conversion timed out") from None

    if result.returncode != 0:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise RuntimeError(
            f"LibreOffice conversion failed (exit {result.returncode}):\n{result.stderr}"
        )

    basename = os.path.splitext(os.path.basename(vsd_path))[0]
    vsdx_path = os.path.join(tmpdir, basename + ".vsdx")

    if not os.path.isfile(vsdx_path):
        # LibreOffice sometimes lowercases the stem — search for it
        candidates = [f for f in os.listdir(tmpdir) if f.lower().endswith(".vsdx")]
        if not candidates:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise RuntimeError(
                f"Conversion appeared to succeed but no .vsdx found in {tmpdir}.\n"
                f"LibreOffice stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        vsdx_path = os.path.join(tmpdir, candidates[0])

    logger.info("Converted to %s", vsdx_path)
    return vsdx_path
