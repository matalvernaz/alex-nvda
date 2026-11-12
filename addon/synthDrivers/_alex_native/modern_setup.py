"""Prepare MacinTalk 9.2.22 entirely on Windows from verified downloads obtained directly from Apple."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time
import uuid
import zipfile

from . import apple, downloads, installer, paths, pantherahfs
from .modern_assets import cache, export, extract, prepare, ridiff

ENGINE_DOWNLOAD = downloads.Download(
	"https://swcdn.apple.com/content/downloads/13/30/140-88558-A_TN3FIE7J63/p61cqj3ktmcqilz3q64ls4ekp1os9c8qbp/InstallAssistant.pkg",
	13654790295,
	"sha256",
	"ecc36bf172105f8c3325ceeb4e5ab8cc297260be806eac10b21b784ff40d8173",
	"modern-InstallAssistant.pkg",
	"the modern speech engine",
)
DICTIONARY = "SpeechDictionary.framework/Versions/A"
CACHE_NAME = "dyld_shared_cache_x86_64h"
CACHED_DICTIONARY = "/System/Library/PrivateFrameworks/SpeechDictionary.framework/Versions/A/SpeechDictionary"
ENGINE_SOURCE = "System/Library/Templates/Data/System/Library/Speech/Synthesizers/MacinTalk.SpeechSynthesizer"
RESOURCE_SOURCE = "System/Library/PrivateFrameworks/SpeechDictionary.framework/Versions/A/Resources"
VOICE = "Speech/Voices/Alex.SpeechVoice"


def hfs_partition(image):
	"""Read the GPT rather than assuming the HFS partition is the first partition."""
	image.seek(512)
	header = image.read(92)
	if header[:8] != b"EFI PART":
		def read_at(offset, size):
			image.seek(offset)
			return image.read(size)
		return pantherahfs.find_hfs(read_at, image.size, "SharedSupport.dmg")
	array, count, stride = struct.unpack_from("<QII", header, 72)
	if count > 256 or not 128 <= stride <= 1024:
		raise ValueError("Apple's installer has an unsupported partition map.")
	for index in range(count):
		image.seek(array * 512 + index * stride)
		entry = image.read(stride)
		first, last = struct.unpack_from("<QQ", entry, 32)
		if not first or last < first or (last + 1) * 512 > image.size:
			continue
		image.seek(first * 512 + 1024)
		if image.read(2) in (b"H+", b"HX"):
			return first * 512
	raise ValueError("Apple's installer is missing its HFS support image.")


@contextmanager
def open_update_archive(package):
	"""Seek through the stored nested images without making another large installer copy."""
	with Path(package).open("rb") as file:
		source = apple.Subrange(file, 0, Path(package).stat().st_size)
		inner = apple.xar_member(source, "SharedSupport.dmg")
		image = pantherahfs.UDIFReader(inner, inner.size, "SharedSupport.dmg")
		volume = pantherahfs.Volume(image, hfs_partition(image))
		directory = volume.entry("com_apple_MobileAsset_MacSoftwareUpdate")
		if directory is None:
			raise ValueError("Apple's installer is missing its software-update archive.")
		candidates = [entry for entry in volume.children(directory) if not entry[1] and entry[0].endswith(".zip") and entry[3] > 1024**3]
		if len(candidates) != 1:
			raise ValueError("Apple's installer has an unexpected software-update layout.")
		stream = pantherahfs.ExtentStream(volume, candidates[0])
		with zipfile.ZipFile(stream) as archive:
			yield archive


def extract_components(package, workspace, progress, cancel):
	"""Resume selected payload extraction and read cache forks straight from the full-image patch."""
	workspace = Path(workspace)
	workspace.mkdir(parents=True, exist_ok=True)
	state_file = workspace / "payloads.json"
	try:
		completed = json.loads(state_file.read_text()) if state_file.exists() else []
	except (ValueError, OSError):
		completed = []
	if not isinstance(completed, list):
		completed = []
	pattern = re.compile("^(?:" + re.escape(ENGINE_SOURCE) + "/|" + re.escape(RESOURCE_SOURCE) + "/)")
	check = lambda: apple.check_cancelled(cancel)
	with open_update_archive(package) as archive:
		members = sorted(name for name in archive.namelist() if re.fullmatch(r"AssetData/payloadv2/payload\.\d+", name))
		if not members:
			raise ValueError("Apple's installer is missing the speech payloads.")
		for index, name in enumerate(members):
			check()
			progress("Extracting the modern speech engine", index * 100 // len(members), f"Reading installer payload {index + 1} of {len(members)}")
			inventory = workspace / (Path(name).name + ".inventory.jsonl")
			if name in completed and saved_payload_valid(inventory, workspace, pattern, cancel):
				continue
			with archive.open(name) as source, inventory.open("w", encoding="utf-8") as listing:
				extract.extract_payload(source, workspace, pattern, listing, check_cancelled=check)
			if name not in completed:
				completed.append(name)
			installer_state(state_file, completed)
		cache_directory = workspace / "intel-cache"
		cache_state = workspace / "caches.json"
		cached = json.loads(cache_state.read_text()) if cache_state.exists() else []
		expected = {CACHE_NAME} | {CACHE_NAME + f".{index:02d}" for index in range(1, 6)}
		valid = isinstance(cached, list) and len(cached) == 6 and {item.get("name") for item in cached if isinstance(item, dict)} == expected
		if valid:
			progress("Checking extracted components", 0, "Verifying saved Intel cache files before resuming")
			for item in cached:
				file = cache_directory / item["name"]
				if file.is_symlink() or not file.is_file() or file.stat().st_size != item["size"] or apple.hash_file(file, "sha256", cancel) != item["sha256"]:
					valid = False
					break
		if not valid:
			with archive.open("AssetData/payloadv2/image_patches/cryptex-system-x86_64") as source:
				cached = ridiff.extract_caches(source, cache_directory, progress, check)
			if len(cached) != 6:
				raise ValueError("The installer did not contain the complete Intel cache family.")
			installer_state(cache_state, cached)
	return cache_directory / CACHE_NAME


def saved_payload_valid(inventory, workspace, pattern, cancel):
	"""A resume marker alone cannot prove that a previously extracted file survived intact."""
	try:
		with inventory.open(encoding="utf-8") as source:
			for line in source:
				item = json.loads(line)
				if item["type"] != ord("F") or not pattern.search(item["path"]):
					continue
				file = workspace / item["path"]
				if file.is_symlink() or not file.is_file() or file.stat().st_size != item["size"] or not item.get("sha256") or apple.hash_file(file, "sha256", cancel) != item["sha256"]:
					return False
	except (OSError, ValueError, KeyError, TypeError):
		return False
	return True


def installer_state(file, state):
	pending = file.with_suffix(file.suffix + ".pending")
	pending.write_text(json.dumps(state, indent=2), encoding="utf-8")
	pending.replace(file)


def run_decoder(command, root, cancel):
	"""Keep helper errors local and make setup cancellation stop the helper too."""
	logs = Path(root) / "logs"
	logs.mkdir(parents=True, exist_ok=True)
	with (logs / "modern-setup.log").open("ab") as log:
		process = subprocess.Popen(command, stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
		try:
			deadline = time.monotonic() + 120
			while process.poll() is None:
				apple.check_cancelled(cancel)
				if time.monotonic() > deadline:
					raise TimeoutError("The modern component decoder did not finish. Retry setup and check modern-setup.log.")
				cancel.wait(0.1)
			if process.returncode:
				raise RuntimeError("The modern component decoder failed. Details are in " + str(logs / "modern-setup.log"))
		finally:
			if process.poll() is None:
				process.kill()
			process.wait(timeout=5)


def prepare_dictionary(cache_path, destination, root, cancel, decoder_command=None):
	"""Generate component-specific bindings locally; no Apple-derived metadata ships with the add-on."""
	reader = cache.IntelCache(cache_path)
	component = Path(destination) / DICTIONARY / "SpeechDictionary"
	export.extract_component(reader, CACHED_DICTIONARY, component)
	references_file = component.with_suffix(".references.json")
	command = list(decoder_command) if decoder_command else [str(paths.MODERN_HOST_EXE)]
	run_decoder(command + ["--scan-cache-rip", str(component), str(references_file)], root, cancel)
	data = component.read_bytes()
	bindings, references, queries = prepare.scan_component(data, json.loads(references_file.read_text()))
	names = {}
	for library, symbols in queries.items():
		for name in symbols:
			apple.check_cancelled(cancel)
			address = reader.resolve(library, name)
			if address:
				names[address] = name
	for slot in references:
		try:
			address = reader.pointer(slot)
		except ValueError:
			continue
		if address not in names:
			raise ValueError("The modern dictionary has an unresolved import. Retry setup and keep the local logs.")
		bindings[slot] = names[address]
	lines = [f"# source {prepare.fingerprint(data):016x}\n"]
	lines.extend(f"{address:x} {name}\n" for address, name in sorted(bindings.items()))
	lines.extend(f"@{address:x} {name}\n" for address, name in names.items())
	component.with_suffix(".bindings").write_text("".join(lines), encoding="utf-8")
	references_file.unlink()


def share_voice_bank(root, staging, voice, cancel):
	"""Use a hard link only after checking that both copies really contain the same recordings."""
	bank = Path(staging) / VOICE / "Contents/Resources/PCMWave"
	digest = apple.hash_file(bank, "sha256", cancel)
	for state in paths.installed_engines(root).values():
		if state.get("voice_digest") != voice.digest:
			continue
		old = Path(root) / state["directory"] / VOICE / "Contents/Resources/PCMWave"
		if old.stat().st_size != bank.stat().st_size or apple.hash_file(old, "sha256", cancel) != digest:
			continue
		backup = bank.with_suffix(".copy")
		bank.replace(backup)
		try:
			os.link(old, bank)
		except OSError:
			backup.replace(bank)
		else:
			backup.unlink()
		break
	return digest


def install(root, progress, cancel, probe_command=None, keep_downloads=False, decoder_command=None):
	root = Path(root)
	root.mkdir(parents=True, exist_ok=True)
	with installer.InstallationLock(root):
		progress("Checking Windows support", 0, "Checking the modern engine's local runtime")
		runtime_command = list(decoder_command) if decoder_command else [str(paths.MODERN_HOST_EXE)]
		run_decoder(runtime_command + ["--modern-runtime-check"], root, cancel)
		progress("Reading Apple's voice catalog", 0, "Finding the macOS Alex download")
		voice = downloads.find_alex(cancel)
		cache_root = root / "cache"
		cache_root.mkdir(exist_ok=True)
		cached = sum(min((cache_root / item.filename).stat().st_size, item.size) for item in (ENGINE_DOWNLOAD, voice) if (cache_root / item.filename).is_file())
		required = max(6 * 1024**3, ENGINE_DOWNLOAD.size + voice.size + 6 * 1024**3 - cached)
		if shutil.disk_usage(root).free < required:
			raise OSError("Modern Alex setup needs about 22 GB of temporary free space. Free some space and retry; your current engine is unchanged.")
		package = downloads.fetch(ENGINE_DOWNLOAD, cache_root, progress, cancel)
		voice_archive = downloads.fetch(voice, cache_root, progress, cancel)
		workspace = cache_root / "modern-components"
		cache_path = extract_components(package, workspace, progress, cancel)
		staging = root / ("install-" + uuid.uuid4().hex)
		staging.mkdir()
		committed = False
		try:
			shutil.copytree(workspace / ENGINE_SOURCE, staging / "Speech/Synthesizers/MacinTalk.SpeechSynthesizer")
			shutil.copytree(workspace / RESOURCE_SOURCE, staging / DICTIONARY / "Resources")
			progress("Preparing the modern dictionary", 0, "Resolving the downloaded components on this computer")
			prepare_dictionary(cache_path, staging, root, cancel, decoder_command)
			version = apple.extract_alex(voice_archive, staging, progress, cancel)
			progress("Checking shared voice data", 0, "Keeping one copy of the recordings when possible")
			bank_digest = share_voice_bank(root, staging, voice, cancel)
			if not paths.complete_tree(staging, "modern"):
				raise ValueError("Required modern speech components are missing. Retry setup.")
			progress("Testing modern Alex", 0, "Checking that the downloaded engine produces real speech")
			installer.probe(staging, root, cancel, probe_command or [str(paths.MODERN_HOST_EXE)])
			apple.check_cancelled(cancel)
			state = dict(format=1, directory=staging.name, engine_key="modern", engine="MacinTalk 9.2.22 (macOS Sonoma 14.8.9)", voice_version=version, voice_url=voice.url, voice_digest=voice.digest, voice_bank_sha256=bank_digest, engine_sha256=ENGINE_DOWNLOAD.digest)
			state = paths.publish_installation(root, "modern", state)
			committed = True
		finally:
			if not committed:
				shutil.rmtree(staging)
		if not keep_downloads:
			for path in (workspace, package, voice_archive):
				try:
					if path.is_dir():
						shutil.rmtree(path)
					else:
						path.unlink(missing_ok=True)
				except OSError:
					# A temporary Windows file lock must not turn a tested installation into a reported failure.
					pass
		progress("Ready", 100, "Modern Alex is installed. You can keep or remove the Legacy engine in Alex settings.")
		return state
