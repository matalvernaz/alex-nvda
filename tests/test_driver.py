"""Check the Alex driver against Panthera's NVDA API model, without claiming Windows playback coverage."""

import importlib
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import nvda_stubs

# Load subprocess before installing the Windows CRT test double; Python uses its presence to detect Windows.
importlib.import_module("subprocess")

# Linux has no Windows CRT module. The executable path under test does not use the DLL-only CRT helpers.
sys.modules.setdefault("msvcrt", types.ModuleType("msvcrt"))
addon_handler = types.ModuleType("addonHandler")
addon_handler.initTranslation = lambda: None
sys.modules.setdefault("addonHandler", addon_handler)

alex = importlib.import_module("synthDrivers.alex")
from synthDrivers._alex_native import paths


class DriverTests(unittest.TestCase):
	def test_missing_setup_is_not_a_selectable_silent_voice(self):
		with tempfile.TemporaryDirectory() as directory, patch.object(paths, "data_root", return_value=Path(directory)):
			self.assertFalse(alex.SynthDriver.check())
			with self.assertRaises(RuntimeError):
				alex.SynthDriver()

	def test_only_alex_is_offered_and_cancel_always_stops_playback(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			installation = root / "install-test"
			for relative in paths.REQUIRED_FILES:
				file = installation / relative
				file.parent.mkdir(parents=True, exist_ok=True)
				file.write_bytes(b"synthetic fixture")
			(root / "current.json").write_text('{"format": 1, "directory": "install-test"}')
			host = root / "test-host.exe"
			host.write_bytes(b"synthetic fixture")
			with patch.object(paths, "data_root", return_value=root), patch.object(paths, "HOST_EXE", host):
				self.assertTrue(alex.SynthDriver.check())
				driver = alex.SynthDriver()
				try:
					self.assertIsInstance(driver._player, nvda_stubs.FakeWavePlayer)
					self.assertEqual(driver.name, "alex")
					self.assertEqual(driver.voice, "Alex")
					self.assertEqual(list(driver.availableVoices), ["Alex"])
					previous = driver._player.stops
					driver.cancel()
					self.assertGreater(driver._player.stops, previous)
				finally:
					driver.terminate()

	def test_engine_switch_cannot_change_the_host_of_an_existing_driver(self):
		with tempfile.TemporaryDirectory() as directory:
			root = Path(directory)
			for engine in ("modern", "legacy"):
				installation = root / ("install-" + engine)
				for relative in paths.required_files(engine):
					file = installation / relative
					file.parent.mkdir(parents=True, exist_ok=True)
					file.write_bytes(b"synthetic fixture")
				paths.publish_installation(root, engine, {"format": 1, "directory": installation.name})
			host = root / "synthetic-legacy-host.exe"
			host.write_bytes(b"synthetic fixture")
			with patch.object(paths, "data_root", return_value=root), patch.object(paths, "HOST_EXE", host):
				driver = alex.SynthDriver()
				try:
					paths.select_engine(root, "modern")
					self.assertEqual(driver.TREE.find_tree(), str(root / "install-legacy"))
					self.assertEqual(driver.TREE.HOST_EXE, str(host))
					self.assertEqual(driver.TREE.TEXT_ENCODING, "mac_roman")
				finally:
					driver.terminate()


if __name__ == "__main__":
	unittest.main()
