"""Verify direct image-fork extraction using small, synthetic PBZX streams only."""

import hashlib
import io
import lzma
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from modern import ridiff


def pbzx(data):
	encoded = bytearray(b"pbzx" + struct.pack(">Q", 65536))
	for offset in range(0, len(data), 65536):
		block = data[offset:offset + 65536]
		compressed = lzma.compress(block)
		encoded.extend(struct.pack(">QQ", len(block), len(compressed)))
		encoded.extend(compressed)
	return bytes(encoded)


def synthetic_image(forks, flags=1):
	metadata = bytearray(struct.pack("<32s4Q", bytes(32), 4 * 1024**2, 24, len(forks), len(forks)))
	for index, data in enumerate(forks):
		metadata.extend(struct.pack("<QQ", index * 1024**2, len(data)))
	for index, data in enumerate(forks):
		chunks = (len(data) + 65535) // 65536
		metadata.extend(struct.pack("<5QBQ", len(data), len(data), 1, index, 1, 14, (chunks + 1) * 4))
		metadata.extend(bytes((chunks - 1) * 12 + 4))
	encoded_metadata = pbzx(metadata)
	controls = pbzx(struct.pack("<QQ", 0, sum(map(len, forks))))
	variant = pbzx(b"".join(forks))
	control_offset = 62 + len(encoded_metadata)
	variant_offset = control_offset + len(controls)
	header = struct.pack("<8sHQQIQQQQ", b"RIDIFF10", 1, flags, 1, 0, 62, control_offset, variant_offset, variant_offset + len(variant))
	return io.BytesIO(header + encoded_metadata + controls + variant)


class ImageForkTests(unittest.TestCase):
	def test_extracts_cache_fork_without_building_a_disk_image(self):
		cache = b"dyld_v1 x86_64h\0\0" + b"synthetic cache" * 10000
		with tempfile.TemporaryDirectory() as temporary, patch.object(ridiff, "MINIMUM_CACHE_BYTES", 1024):
			files = ridiff.extract_caches(synthetic_image([b"unrelated" * 100, cache]), temporary)
			self.assertEqual(len(files), 1)
			self.assertEqual(files[0]["sha256"], hashlib.sha256(cache).hexdigest())
			file = Path(temporary) / files[0]["name"]
			self.assertEqual(file.stat().st_size, len(cache))
			self.assertEqual(hashlib.sha256(file.read_bytes()).digest(), hashlib.sha256(cache).digest())

	def test_refuses_a_differential_image(self):
		with self.assertRaisesRegex(ValueError, "full Intel"):
			ridiff.full_image_forks(synthetic_image([b"synthetic"], flags=0))

	def test_oversized_pbzx_block_is_rejected_before_reading_data(self):
		source = io.BytesIO(b"pbzx" + struct.pack(">Q", 65 * 1024**2))
		with self.assertRaisesRegex(ValueError, "memory limit"):
			ridiff.ImageStream(source)

	def test_truncated_pbzx_block_is_rejected(self):
		data = pbzx(b"synthetic data")[:-2]
		with self.assertRaises(ValueError):
			io.BufferedReader(ridiff.ImageStream(io.BytesIO(data))).read()


if __name__ == "__main__":
	unittest.main()
