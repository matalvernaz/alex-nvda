"""Extract selected speech files from a local Apple OTA ZIP with bounded memory."""

import argparse
import hashlib
import io
import json
import lzma
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile

MAXIMUM_CHUNK_BYTES = 64 * 1024**2
COPY_BYTES = 64 * 1024
MORE_CHUNKS = 0x800000


def exact(source, size):
	"""Reject truncated structures before interpreting their contents."""
	data = source.read(size)
	if len(data) != size:
		raise ValueError(f"Truncated archive: expected {size} bytes, got {len(data)}")
	return data


class PayloadReader(io.RawIOBase):
	"""Keep only one PBZX chunk, including when skipping an unrelated large file."""

	def __init__(self, source):
		self.source = source
		if exact(source, 4) != b"pbzx":
			raise ValueError("The payload is not a PBZX archive")
		self.flags = struct.unpack(">Q", exact(source, 8))[0]
		self.chunk = b""
		self.position = 0

	def readable(self):
		return True

	def readinto(self, output):
		if self.position == len(self.chunk):
			if not self.flags & MORE_CHUNKS:
				return 0
			self.flags, size = struct.unpack(">QQ", exact(self.source, 16))
			if size > MAXIMUM_CHUNK_BYTES:
				raise ValueError("The PBZX compressed chunk exceeds the memory limit")
			compressed = exact(self.source, size)
			if compressed.startswith(b"\xfd7zXZ\0"):
				decoder = lzma.LZMADecompressor(memlimit=128 * 1024**2)
				self.chunk = decoder.decompress(compressed, max_length=MAXIMUM_CHUNK_BYTES + 1)
				if not decoder.eof or decoder.unused_data:
					raise ValueError("Invalid or oversized PBZX compressed chunk")
			else:
				self.chunk = compressed
			if len(self.chunk) > MAXIMUM_CHUNK_BYTES:
				raise ValueError("The PBZX uncompressed chunk exceeds the memory limit")
			self.position = 0
		count = min(len(output), len(self.chunk) - self.position)
		output[:count] = self.chunk[self.position:self.position + count]
		self.position += count
		return count


def header_fields(header):
	"""Decode Apple Archive field encodings without loading the file they describe."""
	fields = {}
	position = 0
	widths = {"1": 1, "2": 2, "4": 4, "8": 8, "A": 2, "B": 4, "C": 8, "S": 8, "T": 12, "H": 32}
	while position < len(header):
		if len(header) - position < 4:
			raise ValueError("Truncated Apple Archive field")
		name = header[position:position + 3].decode("ascii")
		encoding = chr(header[position + 3])
		position += 4
		if encoding == "P":
			if len(header) - position < 2:
				raise ValueError("Truncated Apple Archive string length")
			length = struct.unpack_from("<H", header, position)[0]
			position += 2
		else:
			if encoding not in widths:
				raise ValueError(f"Unsupported Apple Archive field: {name}{encoding}")
			length = widths[encoding]
		if length > len(header) - position:
			raise ValueError("Apple Archive field exceeds its header")
		value = header[position:position + length]
		position += length
		fields[name] = value if encoding in ("P", "H") else int.from_bytes(value, "little")
	return fields


def extract_payload(source, output, pattern, inventory, check_cancelled=None, report=None):
	"""Copy matching regular files and validate their stored SHA-256 when present."""
	stream = io.BufferedReader(PayloadReader(source), buffer_size=COPY_BYTES)
	count = 0
	while prefix := stream.read(6):
		if check_cancelled:
			check_cancelled()
		if len(prefix) != 6 or prefix[:4] not in (b"YAA1", b"AA01"):
			raise ValueError(f"Unsupported Apple Archive record: {prefix!r}")
		header_size = struct.unpack_from("<H", prefix, 4)[0]
		if header_size < 6:
			raise ValueError("Invalid Apple Archive header size")
		fields = header_fields(exact(stream, header_size - 6))
		name = fields.get("PAT", b"").decode("utf-8")
		kind = fields.get("TYP")
		if kind == ord("M"):
			raise ValueError("Nested Apple Archive metadata requires a dedicated reader")
		length = fields.get("DAT", 0) if kind == ord("F") else 0
		selected = kind == ord("F") and bool(pattern.search(name))
		file = None
		digest = hashlib.sha256()
		if selected:
			path = PurePosixPath(name)
			if path.is_absolute() or ".." in path.parts:
				raise ValueError("Unsafe path in Apple Archive")
			destination = output.joinpath(*path.parts)
			destination.parent.mkdir(parents=True, exist_ok=True)
			file = destination.open("wb")
		try:
			remaining = length
			while remaining:
				if check_cancelled:
					check_cancelled()
				block = exact(stream, min(remaining, COPY_BYTES))
				if file:
					file.write(block)
					digest.update(block)
				remaining -= len(block)
		finally:
			if file:
				file.close()
		if selected:
			if "SH2" in fields and digest.digest() != fields["SH2"]:
				raise ValueError(f"The extracted SHA-256 does not match: {name}")
			if report:
				report(f"Extracted {name} ({length} bytes)")
			count += 1
		inventory.write(json.dumps({"path": name, "size": length, "type": kind, "sha256": digest.hexdigest() if selected else None}) + "\n")
		remaining = fields.get("XAT", 0) + fields.get("YEC", 0)
		while remaining:
			if check_cancelled:
				check_cancelled()
			block = exact(stream, min(remaining, COPY_BYTES))
			remaining -= len(block)
	return count


def main():
	"""Process payloads sequentially and remember completed members for restart."""
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("archive", type=Path)
	parser.add_argument("output", type=Path)
	parser.add_argument("--pattern", default="SpeechDictionary|MacinTalk")
	arguments = parser.parse_args()
	arguments.output.mkdir(parents=True, exist_ok=True)
	pattern = re.compile(arguments.pattern)
	state = arguments.output / "extraction-progress.json"
	completed = json.loads(state.read_text()) if state.exists() else []
	with zipfile.ZipFile(arguments.archive) as archive:
		members = sorted(name for name in archive.namelist() if re.fullmatch(r"AssetData/payloadv2/payload\.\d+", name))
		for name in members:
			if name in completed:
				continue
			print("Reading " + name, flush=True)
			inventory_path = arguments.output / (PurePosixPath(name).name + ".inventory.jsonl")
			with archive.open(name) as source, inventory_path.open("w") as inventory:
				count = extract_payload(source, arguments.output, pattern, inventory)
			print(f"Completed {name}: {count} matching files", flush=True)
			completed.append(name)
			state.write_text(json.dumps(completed, indent=2))


if __name__ == "__main__":
	main()
