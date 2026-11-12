"""Keep large uncompressed installer spans from being copied into memory."""

import io
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alex_native import pantherahfs


class BoundedSource(io.BytesIO):
	def read(self, size=-1):
		if size < 0 or size > 8192:
			raise AssertionError("The reader tried to materialize an entire installer span")
		return b"A" * size


class DiskStreamingTests(unittest.TestCase):
	def reader(self, kind):
		reader = pantherahfs.UDIFReader.__new__(pantherahfs.UDIFReader)
		reader.f = BoundedSource()
		reader.pos = 0
		reader.size = 16 * 1024**2
		reader.chunks = [(kind, 0, reader.size, 0, reader.size)]
		reader._cache_i = -1
		reader._cache = b""
		return reader


	def test_raw_span_reads_only_the_requested_bytes(self):
		reader = self.reader(pantherahfs.RAW)
		reader.seek(reader.size - 17)
		self.assertEqual(reader.read(17), b"A" * 17)
		self.assertEqual(len(reader._cache), 0)


	def test_zero_span_does_not_allocate_the_whole_span(self):
		reader = self.reader(pantherahfs.ZERO)
		reader.seek(reader.size - 17)
		self.assertEqual(reader.read(17), b"\0" * 17)
		self.assertEqual(len(reader._cache), 0)


if __name__ == "__main__":
	unittest.main()
