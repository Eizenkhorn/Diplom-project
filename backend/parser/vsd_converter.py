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

    # Use a plain ASCII input name to avoid encoding problems with soffice
    input_copy = os.path.join(tmpdir, "input.vsd")
    shutil.copy2(vsd_path, input_copy)

    cmd = [soffice, "--headless", "--convert-to", "odg", "--outdir", tmpdir, input_copy]
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

    odg_path = os.path.join(tmpdir, "input.odg")
    if not os.path.isfile(odg_path):
        candidates = [f for f in os.listdir(tmpdir) if f.lower().endswith(".odg")]
        if not candidates:
            shutil.rmtree(tmpdir, ignore_errors=True)
            raise RuntimeError(
                f"Conversion appeared to succeed but no .odg found in {tmpdir}.\n"
                f"stdout: {result.stdout}\nstderr: {result.stderr}"
            )
        odg_path = os.path.join(tmpdir, candidates[0])

    logger.info("Converted to %s", odg_path)
    return odg_path
