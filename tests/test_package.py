"""Reject proprietary payloads accidentally staged beside the add-on code."""

import importlib.util
from pathlib import Path
import tempfile
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


if __name__ == "__main__":
	unittest.main()
