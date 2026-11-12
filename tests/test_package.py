"""Reject proprietary payloads accidentally staged beside the add-on code."""

import importlib.util
from pathlib import Path
import tempfile
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
specification = importlib.util.spec_from_file_location("alex_package", ROOT / "tools/package.py")
package = importlib.util.module_from_spec(specification)
specification.loader.exec_module(package)


class PackagingTests(unittest.TestCase):
	def test_rejects_voice_bank(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			(root / "PCMWave").write_bytes(b"synthetic test")
			with self.assertRaises(ValueError):
				package.approved_files(root)

	def test_rejects_renamed_macho(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			(root / "fake.py").write_bytes(b"\xcf\xfa\xed\xfe" + b"synthetic test")
			with self.assertRaises(ValueError):
				package.approved_files(root)

	def test_rejects_unbuilt_package(self):
		with tempfile.TemporaryDirectory() as directory:
			with self.assertRaises(ValueError):
				package.approved_files(Path(directory))

	def test_test_only_icu_dll_cannot_enter_the_package(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			file = root / package.MODERN_DIRECTORY / "icu.dll"
			file.parent.mkdir(parents=True)
			file.write_bytes(b"MZ synthetic open-source test runtime")
			with self.assertRaisesRegex(ValueError, "Unapproved.*icu.dll"):
				package.approved_files(root)

	def test_wrong_architecture_is_rejected_even_at_an_approved_filename(self):
		with tempfile.TemporaryDirectory() as directory:
			file = Path(directory) / "synthetic.exe"
			data = bytearray(256)
			data[:2] = b"MZ"
			struct.pack_into("<I", data, 0x3c, 128)
			data[128:134] = b"PE\0\0\x4c\x01"
			struct.pack_into("<H", data, 150, 0x20)
			file.write_bytes(data)
			package.check_host(file)
			with self.assertRaisesRegex(ValueError, "architecture"):
				package.check_host(file, machine=0x8664)


if __name__ == "__main__":
	unittest.main()
