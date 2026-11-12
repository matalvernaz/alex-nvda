"""Read full-image RIDIFF streams and extract Intel caches without rebuilding an APFS image."""

import hashlib
import io
from pathlib import Path
import struct

from .extract import exact

COPY_BYTES = 1024 * 1024
MINIMUM_CACHE_BYTES = 128 * COPY_BYTES


class ImageStream(io.RawIOBase):
	"""Decode nominal-size PBZX blocks, including the one-MiB variant used by image patches."""

	def __init__(self, source):
		self.source = source
		if exact(source, 4) != b"pbzx":
			raise ValueError("Invalid image PBZX stream")
		self.nominal = struct.unpack(">Q", exact(source, 8))[0]
		if not 0 < self.nominal <= 64 * COPY_BYTES:
			raise ValueError("The image PBZX block exceeds its memory limit")
		self.chunk = b""
		self.position = 0
		self.finished = False

	def readable(self):
		return True

	def readinto(self, output):
		if self.position == len(self.chunk):
			if self.finished:
				return 0
			import lzma
			header = self.source.read(16)
			if not header:
				self.finished = True
				return 0
			if len(header) != 16:
				raise ValueError("Truncated image PBZX block")
			expanded, compressed = struct.unpack(">QQ", header)
			if not 0 < expanded <= self.nominal or compressed > 64 * COPY_BYTES:
				raise ValueError("The image PBZX block exceeds its memory limit")
			data = exact(self.source, compressed)
			if data.startswith(b"\xfd7zXZ\0"):
				decoder = lzma.LZMADecompressor(memlimit=128 * COPY_BYTES)
				self.chunk = decoder.decompress(data, max_length=expanded + 1)
				if not decoder.eof or decoder.unused_data:
					raise ValueError("Invalid compressed image PBZX block")
			else:
				self.chunk = data
			if len(self.chunk) != expanded:
				raise ValueError("The image PBZX block has an incorrect expanded size")
			self.position = 0
			self.finished = expanded < self.nominal
		count = min(len(output), len(self.chunk) - self.position)
		output[:count] = self.chunk[self.position:self.position + count]
		self.position += count
		return count


def full_image_forks(source):
	"""Refuse differential patches, then index their bounded metadata without Apple code."""
	source.seek(0)
	header = exact(source, 62)
	magic, variants, flags, controls_count, excess, metadata_offset, controls_offset, variant_offset, patch_size = struct.unpack("<8sHQQIQQQQ", header)
	if magic != b"RIDIFF10" or variants != 1 or flags != 1 or controls_count != 1:
		raise ValueError("A full Intel system-image patch is required")
	if not 62 <= metadata_offset < controls_offset < variant_offset < patch_size:
		raise ValueError("Invalid system-image patch offsets")
	source.seek(metadata_offset)
	metadata = io.BufferedReader(ImageStream(source)).read(16 * COPY_BYTES + 1)
	if len(metadata) > 16 * COPY_BYTES or len(metadata) < 64:
		raise ValueError("The system-image metadata exceeds its memory limit")
	source.seek(controls_offset)
	controls = io.BufferedReader(ImageStream(source)).read(17)
	if len(controls) != 16:
		raise ValueError("The system-image control stream has an unexpected size")
	offset, stream_size = struct.unpack("<QQ", controls)
	if offset or not 0 < stream_size <= 16 * 1024**3:
		raise ValueError("The system image requires an existing source image")
	digest, image_size, compression, extent_count, fork_count = struct.unpack_from("<32s4Q", metadata)
	if extent_count > 65536 or fork_count > 65536:
		raise ValueError("The system image has too many extents")
	position = 64 + extent_count * 16
	forks = []
	for index in range(fork_count):
		if position + 49 > len(metadata):
			raise ValueError("Truncated system-image fork")
		size, compressed, variant, extent, count, algorithm, table_size = struct.unpack_from("<5QBQ", metadata, position)
		if algorithm != 14 or variant != 1 or extent + count > extent_count:
			raise ValueError("Unsupported full-image fork format")
		chunks = table_size // 4 - 1
		if table_size % 4 or chunks != (size + 65535) // 65536 or chunks < 1:
			raise ValueError("Invalid image fork chunk table")
		position += 49 + (chunks - 1) * 12 + 4
		if position > len(metadata):
			raise ValueError("Truncated image fork chunk table")
		forks.append(size)
	if position != len(metadata) or sum(forks) > stream_size:
		raise ValueError("Inconsistent system-image fork sizes")
	return variant_offset, forks


def extract_caches(source, output, progress=None, check_cancelled=None):
	"""Copy cache forks directly; rebuilding their original APFS compression is unnecessary."""
	output = Path(output)
	output.mkdir(parents=True, exist_ok=True)
	variant_offset, forks = full_image_forks(source)
	source.seek(variant_offset)
	stream = io.BufferedReader(ImageStream(source), buffer_size=COPY_BYTES)
	processed = 0
	total = sum(forks)
	files = []
	for index, size in enumerate(forks):
		if check_cancelled:
			check_cancelled()
		prefix = exact(stream, min(512, size))
		architecture = prefix[:16].rstrip(b"\0").split()
		selected = size >= MINIMUM_CACHE_BYTES and architecture == [b"dyld_v1", b"x86_64h"]
		file = None
		if selected:
			if size > 2 * 1024**3 or len(files) >= 8:
				raise ValueError("The Intel cache family exceeds its setup limit")
			name = "dyld_shared_cache_x86_64h" + (f".{len(files):02d}" if files else "")
			file = (output / (name + ".partial")).open("wb")
			file.write(prefix)
			digest = hashlib.sha256(prefix)
		try:
			remaining = size - len(prefix)
			while remaining:
				if check_cancelled:
					check_cancelled()
				block = exact(stream, min(COPY_BYTES, remaining))
				if file:
					file.write(block)
					digest.update(block)
				remaining -= len(block)
				processed += len(block)
				if progress:
					progress("Preparing the modern dictionary", processed * 100 // max(1, total), "Reading Apple's Intel cache files")
		finally:
			if file:
				file.close()
		if selected:
			partial = output / (name + ".partial")
			partial.replace(output / name)
			files.append({"name": name, "size": size, "sha256": digest.hexdigest()})
	return files
