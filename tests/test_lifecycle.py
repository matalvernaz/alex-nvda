"""A profile handover must retire callbacks, workers and NVDA settings registrations."""

import threading
import unittest
from unittest.mock import Mock, patch

from test_driver import alex
import nvda_stubs
from synthDriverHandler import SynthDriver as BaseDriver, synthDoneSpeaking


class LifecycleTests(unittest.TestCase):
	def driver(self):
		from types import SimpleNamespace
		from synthDrivers._alex_native import tree
		selection = SimpleNamespace(
			HOST_EXE="synthetic.exe", HOST_DLL="synthetic.dll", TEXT_ENCODING="utf-8",
			explain=lambda: (True, []), find_tree=lambda: "synthetic",
			engine_paths=lambda value: ("synthetic-mt", "synthetic-sd", "synthetic-voices"),
			read_voices=lambda *args, **kwargs: [("Alex", "Alex", "en_US")],
		)
		with patch.object(tree, "usable", return_value=True), patch.object(tree, "selected_tree", return_value=selection):
			driver = alex.SynthDriver()
		self.addCleanup(driver.terminate)
		return driver

	def test_profile_handover_runs_nvda_base_cleanup_once(self):
		with patch.object(BaseDriver, "terminate", create=True) as cleanup:
			driver = self.driver()
			driver.terminate()
			driver.terminate()
			cleanup.assert_called_once_with()

	def test_late_audio_completion_cannot_notify_after_profile_switch(self):
		entered, release = threading.Event(), threading.Event()
		class DelayedPlayer(nvda_stubs.FakeWavePlayer):
			def idle(self):
				entered.set()
				release.wait(3)
			def stop(self):
				super().stop()
				release.set()
		with patch.object(alex.SynthDriver, "_makePlayer", return_value=DelayedPlayer()):
			driver = self.driver()
		with patch.object(synthDoneSpeaking, "notify") as notify:
			driver._audioQueue.put(("done", None, None))
			self.assertTrue(entered.wait(1), "feeder did not start waiting for playback")
			driver.terminate()
			driver._feeder.join(1)
			notify.assert_not_called()
		self.assertFalse(driver._worker.is_alive())
		self.assertFalse(driver._feeder.is_alive())

	def test_profile_switch_closes_its_windows_cancel_event(self):
		kernel = Mock()
		kernel.CreateEventW.return_value = 0x100001234
		with patch("ctypes.WinDLL", return_value=kernel, create=True):
			driver = self.driver()
			driver.terminate()
		kernel.CloseHandle.assert_called_once_with(0x100001234)


if __name__ == "__main__":
	unittest.main()
