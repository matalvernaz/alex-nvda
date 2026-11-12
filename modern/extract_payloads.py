"""Expose the add-on's installer reader as a standalone development tool."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alex_native.modern_assets import extract as implementation

if __name__ == "__main__":
	implementation.main()
else:
	sys.modules[__name__] = implementation
