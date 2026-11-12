"""Exercise failed, resumed and cancelled setup without downloading or storing any Apple data."""

import hashlib
import io
import json
from pathlib import Path
import plistlib
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "addon/synthDrivers"))
from _alex_native import apple, downloads, installer, paths, setup


class Response(io.BytesIO):
	def __init__(self, data, status=200, headers=None):
		super().__init__(data)
		self.status = status
		self.headers = headers or {}


class DownloadTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.root = Path(self.temporary.name)
		self.cancel = threading.Event()
		self.payload = b"A synthetic download. Not an Apple file."
		self.download = downloads.Download("https://mesu.apple.com/test", len(self.payload), "sha256", hashlib.sha256(self.payload).hexdigest(), "test.zip")

	def tearDown(self):
		self.temporary.cleanup()

	def test_resumes_only_the_expected_range(self):
		partial = self.root / "test.zip.partial"
		partial.write_bytes(self.payload[:10])
		def opener(url, headers):
			self.assertEqual(headers["Range"], "bytes=10-")
			return Response(self.payload[10:], 206, {"Content-Range": f"bytes 10-{len(self.payload) - 1}/{len(self.payload)}"})
		result = downloads.fetch(self.download, self.root, lambda *values: None, self.cancel, opener)
		self.assertEqual(result.read_bytes(), self.payload)
		self.assertFalse(partial.exists())

	def test_restarts_when_server_ignores_resume(self):
		(self.root / "test.zip.partial").write_bytes(b"incorrect partial")
		result = downloads.fetch(self.download, self.root, lambda *values: None, self.cancel, lambda *arguments: Response(self.payload))
		self.assertEqual(result.read_bytes(), self.payload)

	def test_rejects_wrong_content_range_without_appending(self):
		partial = self.root / "test.zip.partial"
		partial.write_bytes(self.payload[:10])
		with self.assertRaises(ValueError):
			downloads.fetch(self.download, self.root, lambda *values: None, self.cancel, lambda *arguments: Response(b"bad", 206, {"Content-Range": "bytes 0-2/3"}))
		self.assertEqual(partial.read_bytes(), self.payload[:10])

	def test_does_not_accept_corrupt_download(self):
		with patch.object(self.cancel, "wait"):
			with self.assertRaises(OSError):
				downloads.fetch(self.download, self.root, lambda *values: None, self.cancel, lambda *arguments: Response(b"X" * len(self.payload)))
		self.assertFalse((self.root / "test.zip").exists())

	def test_cancel_keeps_partial_download(self):
		def report(*arguments):
			self.cancel.set()
		with self.assertRaises(apple.Cancelled):
			downloads.fetch(self.download, self.root, report, self.cancel, lambda *arguments: Response(self.payload))
		self.assertEqual((self.root / "test.zip.partial").read_bytes(), self.payload)

	def test_refuses_non_apple_and_insecure_addresses(self):
		for address in ("http://mesu.apple.com/test", "https://apple.com.evil.test/file", "https://example.com/file", "https://user:password@mesu.apple.com/test", "https://mesu.apple.com:8443/file"):
			with self.subTest(address=address), self.assertRaises(ValueError):
				downloads.apple_url(address)

	def test_refuses_redirect_to_another_provider(self):
		with self.assertRaises(ValueError):
			downloads.AppleRedirects().redirect_request(None, None, 302, "", {}, "https://github.com/test")

	def test_catalog_selects_verified_macos_alex(self):
		asset = {"VoiceId": "com.apple.speech.synthesis.voice.Alex", "Platform": "macOS", "_MeasurementAlgorithm": "SHA-1", "_Measurement": b"1" * 20, "_DownloadSize": 123, "__BaseURL": "https://mesu.apple.com/", "__RelativePath": "alex.zip", "_ContentVersion": 1}
		with patch.object(downloads, "open_apple", return_value=Response(plistlib.dumps({"Assets": [asset]}))):
			voice = downloads.find_alex(self.cancel)
		self.assertEqual(voice.size, 123)
		self.assertEqual(voice.algorithm, "sha1")
		asset["Platform"] = "iOS"
		with patch.object(downloads, "open_apple", return_value=Response(plistlib.dumps({"Assets": [asset]}))):
			with self.assertRaises(ValueError):
				downloads.find_alex(self.cancel)


class InstallationTests(unittest.TestCase):
	def setUp(self):
		self.temporary = tempfile.TemporaryDirectory()
		self.root = Path(self.temporary.name)
		self.cancel = threading.Event()

	def tearDown(self):
		self.temporary.cleanup()

	def make_tree(self, tree):
		for relative in paths.REQUIRED_FILES:
			file = tree / relative
			file.parent.mkdir(parents=True, exist_ok=True)
			file.write_bytes(b"synthetic test placeholder")

	def test_failed_speech_test_preserves_current_installation(self):
		old = self.root / "install-old"
		self.make_tree(old)
		pointer = self.root / "current.json"
		original = json.dumps({"format": 1, "directory": old.name})
		pointer.write_text(original)
		with patch.object(downloads, "find_alex", return_value=downloads.LION), patch.object(downloads, "fetch", return_value=self.root / "dummy"), patch.object(apple, "extract_engine", side_effect=lambda archive, tree, *arguments: self.make_tree(tree)), patch.object(apple, "extract_alex", return_value="test"), patch.object(installer, "probe", side_effect=ValueError("silent")), patch.object(installer.shutil, "disk_usage", return_value=type("Space", (), {"free": 100 * 1024 ** 3})()):
			with self.assertRaises(ValueError):
				installer.install(self.root, lambda *arguments: None, self.cancel)
		self.assertEqual(pointer.read_text(), original)
		self.assertEqual(paths.active_installation(self.root), old)
		self.assertEqual(list(self.root.glob("install-*")), [old])

	def test_bad_pointer_cannot_escape_data_folder(self):
		for name in ("../elsewhere", "install-../elsewhere", "install-..\\elsewhere", "/install-outside"):
			(self.root / "current.json").write_text(json.dumps({"format": 1, "directory": name}))
			self.assertIsNone(paths.active_installation(self.root))

	def test_incomplete_installation_is_not_offered(self):
		(self.root / "current.json").write_text('{"format": 1, "directory": "install-test"}')
		(self.root / "install-test").mkdir()
		self.assertIsNone(paths.active_installation(self.root))

	def test_second_process_cannot_take_setup_lock(self):
		with installer.InstallationLock(self.root):
			with self.assertRaises(RuntimeError):
				with installer.InstallationLock(self.root):
					pass

	def test_silent_success_is_rejected(self):
		path = self.root / "silent.wav"
		with wave.open(str(path), "wb") as audio:
			audio.setnchannels(1)
			audio.setsampwidth(2)
			audio.setframerate(22050)
			audio.writeframes(b"\x00\x00")
		with self.assertRaises(ValueError):
			installer.check_audio(path)

	def test_zip_cannot_write_unlisted_paths(self):
		archive = self.root / "test.zip"
		with zipfile.ZipFile(archive, "w") as output:
			output.writestr("../../escaped", b"malicious")
			output.writestr("AssetData/Info.plist", plistlib.dumps({"CFBundleIdentifier": "com.apple.speech.synthesis.voice.Alex", "CFBundleVersion": "synthetic"}))
			for name in ("PCMWave", "VoiceDescription", "PitchCoeffs.plist"):
				output.writestr("AssetData/" + name, b"synthetic fixture")
		self.assertEqual(apple.extract_alex(archive, self.root / "tree", lambda *arguments: None, self.cancel), "synthetic")
		self.assertFalse((self.root / "escaped").exists())

	def test_subrange_cannot_read_outside_member(self):
		stream = apple.Subrange(io.BytesIO(b"beforememberafter"), 6, 6)
		self.assertEqual(stream.read(), b"member")
		self.assertEqual(stream.read(), b"")
		stream.seek(-3, io.SEEK_END)
		self.assertEqual(stream.read(20), b"ber")

	def test_controller_reports_failure_instead_of_ready(self):
		controller = setup.SetupController()
		states = []
		controller.subscribe(states.append)
		with patch.object(installer, "install", side_effect=ValueError("test failure")):
			controller.start(self.root)
			controller._thread.join(2)
		self.assertTrue(controller.state.error)
		self.assertFalse(controller.state.running)
		self.assertIn("test failure", controller.state.detail)


if __name__ == "__main__":
	unittest.main()
