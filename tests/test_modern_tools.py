"""Check streaming extraction and cache metadata parsing with synthetic data only."""

import hashlib
import io
import lzma
from pathlib import Path
import re
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modern import cache_symbols, extract_payloads, prepare_cached


def archive_entry(path, contents, digest=None):
	header = b"TYP1F"
	encoded = path.encode()
	header += b"PATP" + struct.pack("<H", len(encoded)) + encoded
	header += b"DATB" + struct.pack("<I", len(contents))
	if digest is not None:
		header += b"SH2H" + digest
	return b"YAA1" + struct.pack("<H", len(header) + 6) + header + contents


def payload(data, compressed=True):
	encoded = lzma.compress(data) if compressed else data
	return io.BytesIO(b"pbzx" + struct.pack(">Q", extract_payloads.MORE_CHUNKS) + struct.pack(">QQ", 0, len(encoded)) + encoded)


class ModernExtractionTests(unittest.TestCase):
	def test_selective_extraction_verifies_hash_and_skips_unrelated_file(self):
		wanted = b"synthetic speech fixture"
		data = archive_entry("unrelated/file", b"ignore me")
		data += archive_entry("SpeechDictionary/test", wanted, hashlib.sha256(wanted).digest())
		with tempfile.TemporaryDirectory() as temporary:
			output = Path(temporary)
			inventory = io.StringIO()
			count = extract_payloads.extract_payload(payload(data), output, re.compile("SpeechDictionary"), inventory)
			self.assertEqual(count, 1)
			self.assertEqual((output / "SpeechDictionary/test").read_bytes(), wanted)
			self.assertFalse((output / "unrelated").exists())
			self.assertEqual(len(inventory.getvalue().splitlines()), 2)

	def test_refuses_selected_path_outside_destination(self):
		data = archive_entry("../SpeechDictionary", b"unsafe")
		with tempfile.TemporaryDirectory() as temporary:
			with self.assertRaisesRegex(ValueError, "Unsafe path"):
				extract_payloads.extract_payload(payload(data), Path(temporary), re.compile("SpeechDictionary"), io.StringIO())

	def test_refuses_a_corrupt_selected_file(self):
		data = archive_entry("SpeechDictionary", b"corrupt", b"0" * 32)
		with tempfile.TemporaryDirectory() as temporary:
			with self.assertRaisesRegex(ValueError, "SHA-256"):
				extract_payloads.extract_payload(payload(data), Path(temporary), re.compile("SpeechDictionary"), io.StringIO())

	def test_raw_pbzx_chunk_does_not_require_a_decoder(self):
		reader = io.BufferedReader(extract_payloads.PayloadReader(payload(b"raw bytes", compressed=False)))
		self.assertEqual(reader.read(), b"raw bytes")

	def test_refuses_oversized_compressed_chunk_before_reading_it(self):
		data = b"pbzx" + struct.pack(">Q", extract_payloads.MORE_CHUNKS)
		data += struct.pack(">QQ", 0, extract_payloads.MAXIMUM_CHUNK_BYTES + 1)
		with self.assertRaisesRegex(ValueError, "memory limit"):
			io.BufferedReader(extract_payloads.PayloadReader(io.BytesIO(data))).read()

	def test_refuses_truncated_archive_header(self):
		with tempfile.TemporaryDirectory() as temporary:
			with self.assertRaisesRegex(ValueError, "Unsupported Apple Archive"):
				extract_payloads.extract_payload(payload(b"YAA1"), Path(temporary), re.compile("."), io.StringIO())


class CacheMetadataTests(unittest.TestCase):
	def test_rejects_truncated_and_unbounded_variable_integer(self):
		for data in (b"", b"\x80", b"\x80" * 12):
			with self.assertRaises(ValueError):
				cache_symbols.unsigned_leb(data, 0)
		self.assertEqual(cache_symbols.unsigned_leb(b"\xe5\x8e\x26", 0), (624485, 3))

	def test_decodes_strings_and_numeric_archive_fields(self):
		fields = extract_payloads.header_fields(b"TYP1FPATP\x03\0abcDATB\x05\0\0\0")
		self.assertEqual(fields, {"TYP": ord("F"), "PAT": b"abc", "DAT": 5})
		with self.assertRaises(ValueError):
			extract_payloads.header_fields(b"PATP\xff\xffx")

	def test_component_fingerprint_changes_with_its_contents(self):
		self.assertEqual(prepare_cached.fingerprint(b""), 14695981039346656037)
		self.assertNotEqual(prepare_cached.fingerprint(b"first"), prepare_cached.fingerprint(b"second"))


if __name__ == "__main__":
	unittest.main()
