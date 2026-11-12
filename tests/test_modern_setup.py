"""Failures in the modern installer must leave the user's working engine alone."""

from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alex_native import downloads, installer, modern_setup, paths


class ModernSetupTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.addCleanup(self.temporary.cleanup)
		self.root = Path(self.temporary.name)
		self.cancel = threading.Event()
		self.legacy = self.root / "install-existing"
		self.make_tree(self.legacy, "legacy")
		self.pointer = self.root / "current.json"
		self.original = json.dumps({"format": 1, "directory": self.legacy.name})
		self.pointer.write_text(self.original)

	def make_tree(self, tree, engine):
		for relative in paths.required_files(engine):
			file = tree / relative
			file.parent.mkdir(parents=True, exist_ok=True)
			file.write_bytes(b"small synthetic fixture, not Apple data")

	def test_missing_windows_runtime_fails_before_any_large_download(self):
		with patch.object(modern_setup, "run_decoder", side_effect=OSError("unsupported Windows")), patch.object(downloads, "find_alex") as catalog:
			with self.assertRaises(OSError):
				modern_setup.install(self.root, lambda *arguments: None, self.cancel)
		catalog.assert_not_called()
		self.assertEqual(self.pointer.read_text(), self.original)

	def test_failed_modern_speech_does_not_publish_or_remove_legacy(self):
		def extracted(package, workspace, *arguments):
			for relative in (modern_setup.ENGINE_SOURCE, modern_setup.RESOURCE_SOURCE):
				(Path(workspace) / relative).mkdir(parents=True)
			return Path(workspace) / "synthetic-cache"
		with ExitStack() as stack:
			stack.enter_context(patch.object(modern_setup, "run_decoder"))
			stack.enter_context(patch.object(downloads, "find_alex", return_value=downloads.LION))
			stack.enter_context(patch.object(downloads, "fetch", return_value=self.root / "synthetic-download"))
			stack.enter_context(patch.object(modern_setup, "extract_components", side_effect=extracted))
			stack.enter_context(patch.object(modern_setup, "prepare_dictionary", side_effect=lambda cache, tree, *arguments: self.make_tree(tree, "modern")))
			stack.enter_context(patch.object(modern_setup.apple, "extract_alex", return_value="synthetic"))
			stack.enter_context(patch.object(installer, "probe", side_effect=ValueError("silent speech")))
			stack.enter_context(patch.object(modern_setup.shutil, "disk_usage", return_value=type("Space", (), {"free": 100 * 1024**3})()))
			with self.assertRaisesRegex(ValueError, "silent"):
				modern_setup.install(self.root, lambda *arguments: None, self.cancel)
		self.assertEqual(self.pointer.read_text(), self.original)
		self.assertEqual(paths.active_installation(self.root), self.legacy)
		self.assertEqual(list(self.root.glob("install-*")), [self.legacy])


if __name__ == "__main__":
	unittest.main()
