import sys
from pathlib import Path


def resource_path(relative):
    """Path of a bundled file (like the icon). Works when running from source AND
    from the packaged .exe: PyInstaller unpacks its files into a temporary folder
    whose location is stored in sys._MEIPASS."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parent.parent
    return root / relative