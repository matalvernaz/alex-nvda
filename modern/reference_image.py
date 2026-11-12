"""Create an Intel reference image on macOS using a local Apple recovery patch."""

import argparse
import ctypes
from pathlib import Path
import shutil


class RawImage(ctypes.Structure):
	"""Describe the private patch call used only by the macOS reference tool."""

	_fields_ = [
		("reserved_first", ctypes.c_int64),
		("reserved_second", ctypes.c_int64),
		("input", ctypes.c_char_p),
		("output", ctypes.c_char_p),
		("patch", ctypes.c_char_p),
		("options", ctypes.c_uint32),
		("threads", ctypes.c_uint32),
		("verbose", ctypes.c_uint32),
	]


def main():
	"""Use one patch worker and refuse to overwrite an existing image."""
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("patch", type=Path)
	parser.add_argument("output", type=Path)
	arguments = parser.parse_args()
	if not arguments.patch.is_file():
		parser.error("The local Apple patch does not exist")
	if arguments.output.exists():
		parser.error("The output already exists; choose another path")
	if shutil.disk_usage(arguments.output.parent).free < 6 * 1024**3:
		parser.error("At least 6 GB of free space is needed for this reference image")
	library = ctypes.CDLL("/usr/lib/libParallelCompression.dylib")
	patch = library.RawImagePatch
	patch.argtypes = [ctypes.POINTER(RawImage)]
	patch.restype = ctypes.c_int32
	request = RawImage(0, 0, b"", str(arguments.output.resolve()).encode(), str(arguments.patch.resolve()).encode(), 0, 1, 0)
	arguments.output.touch(exist_ok=False)
	result = patch(ctypes.byref(request))
	if result:
		raise RuntimeError(f"Apple's image patcher failed with status {result}")
	print(f"Created {arguments.output}: {arguments.output.stat().st_size} bytes", flush=True)


if __name__ == "__main__":
	main()
