"""Read Intel cache exports and pointer targets without mapping or loading Apple's libraries."""

import argparse
import json
from pathlib import Path
import struct


def unsigned_leb(data, offset):
	"""Read a bounded unsigned dyld variable-length integer."""
	value = 0
	shift = 0
	while offset < len(data) and shift < 70:
		byte = data[offset]
		offset += 1
		value |= (byte & 127) << shift
		if not byte & 128:
			return value, offset
		shift += 7
	raise ValueError("Invalid dyld integer")


class IntelCache:
	"""Read selected cache bytes and public exports with ordinary bounded file reads."""

	def __init__(self, primary):
		self.primary = primary
		self.mappings = []
		self.images = {}
		self.exports = {}
		self.dependencies = {}
		paths = [primary] + sorted(path for path in primary.parent.glob(primary.name + ".*") if path.suffix[1:].isdigit())
		for path in paths:
			with path.open("rb") as source:
				header = source.read(512)
				if not header.startswith(b"dyld_v"):
					raise ValueError("Invalid dyld cache header")
				offset, count = struct.unpack_from("<II", header, 0x138)
				source.seek(offset)
				entries = [struct.unpack("<6Q2I", source.read(56)) for _ in range(count)]
				for address, size, file_offset, slide_offset, slide_size, flags, maximum, initial in entries:
					mask = addition = 0
					if slide_size:
						source.seek(slide_offset)
						information = struct.unpack("<6I2Q", source.read(40))
						if information[0] != 2:
							raise ValueError("Only Intel slide-info version 2 is supported")
						mask, addition = information[-2:]
					self.mappings.append((address, address + size, file_offset, path, mask, addition))
		with primary.open("rb") as source:
			header = source.read(512)
			offset, count = struct.unpack_from("<QQ", header, 0x88)
			source.seek(offset)
			records = [struct.unpack("<16sQII", source.read(32)) for _ in range(count)]
			for identifier, address, size, path_offset in records:
				source.seek(path_offset)
				path = source.read(4096).split(b"\0", 1)[0].decode()
				self.images[path] = address

	def mapping(self, address, size):
		"""Find a cache mapping that contains the entire requested window."""
		for mapping in self.mappings:
			if mapping[0] <= address and address + size <= mapping[1]:
				return mapping
		raise ValueError(f"Unmapped cache address: {address:#x}, {size} bytes")

	def read(self, address, size):
		"""Read one window, never the entire cache or subcache."""
		low, high, offset, path, mask, addition = self.mapping(address, size)
		with path.open("rb") as source:
			source.seek(offset + address - low)
			data = source.read(size)
		if len(data) != size:
			raise ValueError("Truncated shared cache")
		return data

	def pointer(self, address):
		"""Remove chain metadata from a pointer in an Intel cache data mapping."""
		mapping = self.mapping(address, 8)
		value = struct.unpack("<Q", self.read(address, 8))[0]
		value &= ~mapping[4] & ((1 << 64) - 1)
		return value + mapping[5] if value else 0

	def load_exports(self, image):
		"""Index one public export trie, including re-export records."""
		if image in self.exports:
			return
		address = self.images[image]
		header = self.read(address, 32)
		count, command_size = struct.unpack_from("<II", header, 16)
		commands = self.read(address + 32, command_size)
		offset = 0
		link_address = link_file_offset = export_offset = export_size = 0
		dependencies = []
		for index in range(count):
			command, size = struct.unpack_from("<II", commands, offset)
			if size < 8 or offset + size > len(commands):
				raise ValueError("Invalid cached Mach-O command")
			if command == 25 and commands[offset + 8:offset + 24].rstrip(b"\0") == b"__LINKEDIT":
				link_address, virtual_size, link_file_offset = struct.unpack_from("<QQQ", commands, offset + 24)
			if command == 0x80000033:
				export_offset, export_size = struct.unpack_from("<II", commands, offset + 8)
			if command in (0x22, 0x80000022) and not export_size:
				export_offset, export_size = struct.unpack_from("<II", commands, offset + 40)
			if command in (0xc, 0x80000018, 0x8000001f):
				name_offset = struct.unpack_from("<I", commands, offset + 8)[0]
				name = commands[offset + name_offset:offset + size].split(b"\0", 1)[0].decode()
				dependencies.append(name)
			offset += size
		self.dependencies[image] = dependencies
		self.exports[image] = {}
		if not export_size:
			return
		data = self.read(link_address + export_offset - link_file_offset, export_size)
		pending = [(0, "")]
		visited = set()
		while pending:
			offset, prefix = pending.pop()
			if (offset, prefix) in visited or len(visited) > 1000000:
				raise ValueError("Invalid export trie cycle")
			visited.add((offset, prefix))
			terminal_size, cursor = unsigned_leb(data, offset)
			children = cursor + terminal_size
			if children >= len(data):
				raise ValueError("Export trie exceeds its bounds")
			if terminal_size:
				flags, position = unsigned_leb(data, cursor)
				value, position = unsigned_leb(data, position)
				if flags & 8:
					alias = data[position:data.index(0, position)].decode()
					self.exports[image][prefix] = (value, alias)
				else:
					self.exports[image][prefix] = value if flags & 3 == 2 else address + value
			count = data[children]
			position = children + 1
			for index in range(count):
				end = data.index(0, position)
				name = data[position:end].decode()
				target, position = unsigned_leb(data, end + 1)
				pending.append((target, prefix + name))

	def resolve(self, image, name, depth=0):
		"""Follow a public symbol's re-export chain to its actual cache address."""
		if depth > 16:
			raise ValueError("Cyclic cache re-export")
		self.load_exports(image)
		value = self.exports[image].get(name)
		if isinstance(value, tuple):
			ordinal, alias = value
			return self.resolve(self.dependencies[image][ordinal - 1], alias or name, depth + 1)
		if value is None:
			for dependency in self.dependencies[image]:
				result = self.resolve(dependency, name, depth + 1)
				if result is not None:
					return result
		return value


def main():
	"""Resolve only the data slots missing from a locally extracted component."""
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("cache", type=Path)
	parser.add_argument("slots", type=Path)
	parser.add_argument("queries", type=Path)
	parser.add_argument("output", type=Path)
	parser.add_argument("--symbols-output", type=Path)
	arguments = parser.parse_args()
	cache = IntelCache(arguments.cache)
	names = {}
	for query in json.loads(arguments.queries.read_text()):
		for name in query["names"]:
			address = cache.resolve(query["image"], name)
			if address:
				names[address] = name
	results = []
	for slot in json.loads(arguments.slots.read_text()):
		try:
			address = cache.pointer(slot)
		except ValueError:
			continue
		if address not in names:
			raise ValueError(f"Unresolved cache pointer at {slot:#x}: {address:#x}")
		results.append({"slot": slot, "address": address, "name": names[address]})
	arguments.output.write_text(json.dumps(results, indent=2))
	if arguments.symbols_output:
		arguments.symbols_output.write_text(json.dumps({name: address for address, name in names.items()}, indent=2))
	print(f"Resolved {len(results)} cache slots", flush=True)


if __name__ == "__main__":
	main()
