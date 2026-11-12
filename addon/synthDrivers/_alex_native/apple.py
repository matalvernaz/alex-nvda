"""Read Apple's installer and voice archives without installing macOS or executing their scripts."""

import hashlib
import io
from pathlib import Path
import plistlib
import struct
import xml.etree.ElementTree as ElementTree
import zipfile
import zlib

from . import pantheradiscs
from . import pantherahfs


class Cancelled(Exception):

	"""Setup stopped at the user's request."""


def check_cancelled(cancel):
	if cancel.is_set():
		raise Cancelled("Setup cancelled. Download again to continue.")


class Subrange(io.RawIOBase):
	"""Keep a nested disk image seekable without writing another multi-gigabyte copy."""

	def __init__(self, source, offset, size):
		self.source = source
		self.offset = offset
		self.size = size
		self.position = 0

	def readable(self):
		return True

	def seekable(self):
		return True

	def tell(self):
		return self.position

	def seek(self, offset, whence=io.SEEK_SET):
		if whence == io.SEEK_CUR:
			offset += self.position
		elif whence == io.SEEK_END:
			offset += self.size
		elif whence != io.SEEK_SET:
			raise ValueError("Invalid seek direction")
		if offset < 0:
			raise ValueError("Cannot seek before the image")
		self.position = offset
		return offset

	def read(self, size=-1):
		remaining = max(0, self.size - self.position)
		if size is None or size < 0:
			size = remaining
		size = min(size, remaining)
		self.source.seek(self.offset + self.position)
		data = self.source.read(size)
		self.position += len(data)
		return data

	def readinto(self, buffer):
		data = self.read(len(buffer))
		buffer[:len(data)] = data
		return len(data)


def xar_member(source, wanted):
	"""Open a stored XAR member, checking its bounds before the disk reader sees it."""

	source.seek(0)
	header = source.read(28)
	if len(header) != 28 or header[:4] != b"xar!":
		raise ValueError("Apple's installer package has an unexpected header.")
	header_size, version, compressed_size, expanded_size, checksum = struct.unpack(
		">HHQQI", header[4:]
	)
	if header_size < 28 or compressed_size > 8 * 1024 * 1024 or expanded_size > 32 * 1024 * 1024:
		raise ValueError("Apple's installer directory is unexpectedly large.")
	source.seek(header_size)
	decoder = zlib.decompressobj()
	directory = decoder.decompress(source.read(compressed_size), expanded_size + 1)
	if len(directory) != expanded_size or not decoder.eof:
		raise ValueError("Apple's installer directory is incomplete.")
	root = ElementTree.fromstring(directory)
	for member in root.iter("file"):
		if member.findtext("name") != wanted:
			continue
		data = member.find("data")
		if data is None:
			continue
		encoding = data.find("encoding")
		if encoding is None or encoding.get("style") != "application/octet-stream":
			raise ValueError("Apple changed the installer's disk-image compression.")
		offset = header_size + compressed_size + int(data.findtext("offset"))
		size = int(data.findtext("length"))
		if offset < 0 or size < 512 or offset + size > source.size:
			raise ValueError("Apple's installer contains an invalid disk-image offset.")
		return Subrange(source, offset, size)
	raise ValueError("Apple's installer does not contain " + wanted)


def open_installer(path):
	"""Unwrap Apple's downloadable DMG, package and inner installer image in place."""

	source, base = pantherahfs.open_image(str(path))
	outer = pantherahfs.Volume(source, base)
	package = outer.entry("InstallMacOSX.pkg")
	if package is None:
		raise ValueError("This download is not the expected Apple Lion installer.")
	stream = pantherahfs.ExtentStream(outer, package)
	inner = xar_member(stream, "InstallESD.dmg")
	image = pantherahfs.UDIFReader(inner, inner.size, "InstallESD.dmg")
	def read_at(offset, size):
		image.seek(offset)
		return image.read(size)
	base = pantherahfs.find_hfs(read_at, image.size, "InstallESD.dmg")
	return pantherahfs.Volume(image, base), source


def extract_engine(path, destination, progress, cancel):
	"""Copy only the engine, runtimes and dictionary, leaving all installer scripts untouched."""

	check_cancelled(cancel)
	volume, outer_source = open_installer(path)
	generation = next(value for value in pantheradiscs.GENERATIONS if value.key == "lion")
	class Installer:
		usable = True
		problem = None
		def __init__(self):
			self.generation = generation
		def volume(self):
			return volume
	def report(percent, message):
		check_cancelled(cancel)
		progress("Extracting the speech engine", percent, "Preparing the components Alex needs")
	# The upstream reader also copies small built-in voices. Only Alex is exposed by our driver.
	try:
		pantheradiscs.extract(Installer(), str(destination), report, voices=False)
	finally:
		# The nested readers can outlive this call through Python class cycles. Close the actual file now so Windows can delete the download after setup.
		stream = outer_source
		while stream is not None:
			inner = getattr(stream, "f", None)
			if hasattr(stream, "close"):
				stream.close()
			stream = inner
	check_cancelled(cancel)


def extract_alex(path, destination, progress, cancel):
	"""Turn the flat MobileAsset files into the voice bundle the engine expects."""

	bundle = Path(destination) / "Speech/Voices/Alex.SpeechVoice"
	mapping = {
		"AssetData/Info.plist": ("Contents/Info.plist", 1024 * 1024),
		"AssetData/VoiceDescription": ("Contents/Resources/VoiceDescription", 65536),
		"AssetData/PitchCoeffs.plist": ("Contents/Resources/PitchCoeffs.plist", 1024 * 1024),
		"AssetData/PCMWave": ("Contents/Resources/PCMWave", 2 * 1024 * 1024 * 1024),
	}
	with zipfile.ZipFile(path) as archive:
		for member, (relative_path, maximum_size) in mapping.items():
			check_cancelled(cancel)
			matches = [entry for entry in archive.infolist() if entry.filename == member]
			if len(matches) != 1 or not 0 < matches[0].file_size <= maximum_size:
				raise ValueError("The Alex download is missing a required file or contains an invalid size: " + member)
			entry = matches[0]
			output = bundle / relative_path
			output.parent.mkdir(parents=True, exist_ok=True)
			copied = 0
			with archive.open(entry) as source, output.open("wb") as target:
				while chunk := source.read(1024 * 1024):
					check_cancelled(cancel)
					target.write(chunk)
					copied += len(chunk)
					progress("Extracting Alex", copied * 100 // entry.file_size, "Unpacking the voice recordings")
			if copied != entry.file_size:
				raise ValueError("The Alex download is incomplete.")
	with (bundle / "Contents/Info.plist").open("rb") as stream:
		information = plistlib.load(stream)
	if information.get("CFBundleIdentifier") != "com.apple.speech.synthesis.voice.Alex":
		raise ValueError("Apple's download does not identify itself as Alex.")
	return information.get("CFBundleVersion", "unknown")


def hash_file(path, algorithm, cancel, progress=None):
	"""Hash in chunks so checking a large download can be interrupted too."""

	digest = hashlib.new(algorithm)
	size = Path(path).stat().st_size
	completed = 0
	with open(path, "rb") as source:
		while chunk := source.read(1024 * 1024):
			check_cancelled(cancel)
			digest.update(chunk)
			completed += len(chunk)
			if progress is not None:
				progress("Checking the download", completed * 100 // max(1, size), Path(path).name)
	return digest.hexdigest()
