import json
import pathlib
import sys


def _read_version() -> str:
    if getattr(sys, "frozen", False):
        pkg = pathlib.Path(sys._MEIPASS) / "package.json"  # type: ignore[attr-defined]
    else:
        pkg = pathlib.Path(__file__).parent.parent / "package.json"
    try:
        return json.loads(pkg.read_text(encoding="utf-8")).get("version", "0.0.0")
    except Exception:
        return "0.0.0"

__version__ = _read_version()
