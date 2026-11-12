"""Download, extract and test Alex before atomically making the installation available to NVDA."""

import array
import os
from pathlib import Path
import shutil
import subprocess
import time
import uuid
import wave

from . import apple, downloads, paths


class InstallationLock:
	"""Prevent two NVDA processes from writing to the same setup cache."""

	def __init__(self, root):
		self.path = Path(root) / "setup.lock"
		self.stream = None

	def __enter__(self):
		self.path.parent.mkdir(parents=True, exist_ok=True)
		self.stream = self.path.open("a+b")
		self.stream.seek(0)
		if not self.stream.read(1):
			self.stream.write(b"0")
			self.stream.flush()
		self.stream.seek(0)
		try:
			if os.name == "nt":
				import msvcrt
				msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
			else:
				import fcntl
				fcntl.flock(self.stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
		except OSError as error:
			self.stream.close()
			raise RuntimeError("Alex setup is already running in another NVDA process.") from error
		return self

	def __exit__(self, *arguments):
		self.stream.close()


def check_audio(path):
	"""An engine can return success with one silent sample; that is not a usable voice."""

	with wave.open(str(path), "rb") as audio:
		if audio.getsampwidth() != 2 or audio.getnchannels() != 1 or audio.getframerate() != 22050:
			raise ValueError("The speech test returned an unexpected audio format.")
		if audio.getnframes() < 2205:
			raise ValueError("Alex's speech test returned no usable audio. Setup has not changed your current voice.")
		samples = array.array("h", audio.readframes(audio.getnframes()))
		if not samples or max(abs(sample) for sample in samples) < 100:
			raise ValueError("Alex's speech test was silent. Setup has not changed your current voice.")


def probe(tree, root, cancel, command=None):
	"""Render a fixed sentence to a local file, without changing NVDA's current synthesizer."""

	logs = Path(root) / "logs"
	logs.mkdir(parents=True, exist_ok=True)
	audio = Path(tree) / "setup-test.wav"
	command = list(command) if command is not None else [str(paths.HOST_EXE)]
	command += ["--render", "--tree", str(tree), "--voice", "Alex", "--text", "Hello. Alex is ready to speak.", "--output", str(audio)]
	flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
	with (logs / "setup-test.log").open("wb") as log:
		process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log, creationflags=flags)
		try:
			deadline = time.monotonic() + 45
			while process.poll() is None:
				apple.check_cancelled(cancel)
				if time.monotonic() > deadline:
					raise TimeoutError("Alex did not finish the speech test. Please retry setup.")
				cancel.wait(0.1)
			if process.returncode != 0:
				raise RuntimeError("The Alex speech test failed. Its details are in " + str(logs / "setup-test.log"))
		finally:
			if process.poll() is None:
				process.kill()
			process.wait(timeout=5)
	check_audio(audio)
	audio.unlink()


def clear_downloads(root):
	"""Remove only setup's cache, never an installed engine or its voice data."""
	cache = Path(root) / "cache"
	if cache.is_symlink() or cache.resolve().parent != Path(root).resolve():
		raise ValueError("The Alex download cache is outside its data folder.")
	if cache.exists():
		shutil.rmtree(cache)


def install(root, progress, cancel, probe_command=None, keep_downloads=False, engine="legacy"):
	if engine == "modern":
		from . import modern_setup
		return modern_setup.install(root, progress, cancel, probe_command, keep_downloads)
	if engine != "legacy":
		raise ValueError("Choose Modern or Legacy for the Alex engine.")
	root = Path(root)
	root.mkdir(parents=True, exist_ok=True)
	with InstallationLock(root):
		progress("Reading Apple's voice catalog", 0, "Finding the macOS Alex download")
		voice = downloads.find_alex(cancel)
		cache = root / "cache"
		cache.mkdir(exist_ok=True)
		cached = 0
		for download in (downloads.LION, voice):
			for suffix in ("", ".partial"):
				file = cache / (download.filename + suffix)
				if file.is_file():
					cached += min(file.stat().st_size, download.size)
					break
		required = max(2 * 1024 ** 3, downloads.LION_SIZE + voice.size + 2 * 1024 ** 3 - cached)
		if shutil.disk_usage(root).free < required:
			raise OSError("Alex setup needs about 8 GB of free space for downloads and extraction. Free some space and retry.")
		engine_archive = downloads.fetch(downloads.LION, cache, progress, cancel)
		voice_archive = downloads.fetch(voice, cache, progress, cancel)
		staging = root / ("install-" + uuid.uuid4().hex)
		staging.mkdir()
		committed = False
		try:
			apple.extract_engine(engine_archive, staging, progress, cancel)
			version = apple.extract_alex(voice_archive, staging, progress, cancel)
			from .modern_setup import share_voice_bank
			bank_digest = share_voice_bank(root, staging, voice, cancel)
			if not paths.complete_tree(staging):
				raise RuntimeError("The downloaded installer is missing required speech components. Please retry setup.")
			progress("Testing Alex", 0, "Checking that the downloaded voice produces real speech")
			probe(staging, root, cancel, probe_command)
			apple.check_cancelled(cancel)
			state = {
				"format": 1,
				"directory": staging.name,
				"voice_version": version,
				"engine": "Mac OS X Lion 10.7",
				"voice_url": voice.url,
				"voice_digest": voice.digest,
				"voice_bank_sha256": bank_digest,
				"engine_sha256": downloads.LION_SHA256,
			}
			state = paths.publish_installation(root, "legacy", state)
			committed = True
		finally:
			if not committed:
				shutil.rmtree(staging)
		if not keep_downloads:
			for archive in (engine_archive, voice_archive):
				try:
					archive.unlink()
				except OSError:
					# A successful installation must remain successful if Windows temporarily locks a cached download.
					pass
		progress("Ready", 100, "Alex is installed. You can now select Alex as NVDA's synthesizer.")
		return state
