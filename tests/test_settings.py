"""Exercise progress and engine selection in the settings page without NVDA or Apple data."""

import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon/synthDrivers"))
from _alex_native import paths, setup


class SettingsTests(unittest.TestCase):
	def setUp(self):
		modules = {name: MagicMock() for name in ("addonHandler", "globalPluginHandler", "globalVars", "gui", "gui.settingsDialogs", "synthDriverHandler", "ui", "wx")}
		modules["synthDrivers"] = types.ModuleType("synthDrivers")
		modules["synthDrivers._alex_native"] = sys.modules["_alex_native"]
		modules["globalPluginHandler"].GlobalPlugin = object
		modules["gui.settingsDialogs"].SettingsPanel = object
		with patch.dict(sys.modules, modules):
			spec = importlib.util.spec_from_file_location("alex_settings_test", ROOT / "addon/globalPlugins/alexSetup/__init__.py")
			self.module = importlib.util.module_from_spec(spec)
			spec.loader.exec_module(self.module)
		self.panel = self.module.AlexSettingsPanel()
		self.panel._alive = True
		self.panel._announced_stage = None
		self.panel._announced_percent = -1
		self.panel.engine_keys = ["modern", "legacy"]
		for name in ("status", "progress", "download", "engine", "keep_downloads", "remove_data", "clear_downloads", "cancel_download", "use_alex"):
			setattr(self.panel, name, MagicMock())
		self.panel.engine.GetSelection.return_value = 0
		self.addCleanup(patch.stopall)
		patch.object(paths, "installed_engines", return_value={"legacy": {}}).start()
		patch.object(paths, "selected_engine", return_value="legacy").start()

	def test_download_progress_keeps_setup_state_and_disables_data_changes(self):
		self.panel._show_state(setup.SetupState("Downloading Alex", 40, "40 MB", True))
		self.panel.progress.SetValue.assert_called_once_with(40)
		self.panel.remove_data.Enable.assert_called_once_with(False)
		self.panel.cancel_download.Enable.assert_called_once_with(True)
		self.module.ui.message.assert_called_once_with("Downloading Alex: 40%")

	def test_new_engine_does_not_show_old_installations_ready_status(self):
		self.panel._show_state(setup.SetupState("Ready", 100, "Previously installed"))
		self.assertIn("Not installed", self.panel.status.ChangeValue.call_args.args[0])
		self.panel.use_alex.Enable.assert_called_once_with(False)

	def test_cleanup_is_not_offered_a_download_cancel_button(self):
		self.panel._show_state(setup.SetupState("Removing data", running=True))
		self.panel.cancel_download.Enable.assert_called_once_with(False)


if __name__ == "__main__":
	unittest.main()
