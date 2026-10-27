"""Optional malware scan. Off by default; the admin block must be told if it is off."""
import shutil
import subprocess

from ..config import get_settings


def scan_file(path: str) -> str:
    """Return 'clean', 'infected', 'scan_error' or 'not_scanned'."""
    if not get_settings().clamav_enabled:
        return "not_scanned"
    exe = shutil.which("clamscan")
    if exe is None:
        return "scan_error"
    try:
        result = subprocess.run([exe, "--no-summary", path], capture_output=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return "scan_error"
    return {0: "clean", 1: "infected"}.get(result.returncode, "scan_error")
