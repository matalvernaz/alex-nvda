"""Extract one Intel cache component locally, keeping only its own segments and link tables."""

import argparse
from pathlib import Path
import struct

from .cache import IntelCache

MAXIMUM_COMPONENT_BYTES = 32 * 1024**2


def cache_slide_segment(cache, address, data):
	"""Decode only the rebase chains belonging to the component's data pages."""
	low, high, file_offset, path, mask, addition = cache.mapping(address, len(data))
	if not mask or not data:
		return
	with path.open("rb") as source:
		header = source.read(512)
		offset, count = struct.unpack_from("<II", header, 0x138)
		source.seek(offset)
		records = [struct.unpack("<6Q2I", source.read(56)) for _ in range(count)]
		slide_offset, slide_size = next((item[3], item[4]) for item in records if item[0] == low)
		if slide_size > 16 * 1024**2:
			raise ValueError("The cache slide table exceeds its memory limit")
		source.seek(slide_offset)
		slide = source.read(slide_size)
	version, page_size, starts_offset, starts_count, extras_offset, extras_count, delta_mask, value_add = struct.unpack_from("<6I2Q", slide)
	if version != 2 or page_size not in (4096, 16384) or not delta_mask:
		raise ValueError("Unsupported Intel cache slide table")
	if starts_offset + starts_count * 2 > len(slide) or extras_offset + extras_count * 2 > len(slide):
		raise ValueError("Truncated Intel cache slide table")
	shift = (delta_mask & -delta_mask).bit_length() - 3
	first_page = (address - low) // page_size
	last_page = (address + len(data) - 1 - low) // page_size
	if last_page >= starts_count:
		raise ValueError("Component exceeds its cache rebase pages")
	for page in range(first_page, last_page + 1):
		start = struct.unpack_from("<H", slide, starts_offset + page * 2)[0]
		if start == 0x4000:
			continue
		starts = []
		if start & 0x8000:
			extra = start & 0x3fff
			while True:
				if extra >= extras_count:
					raise ValueError("Invalid extra cache chain")
				value = struct.unpack_from("<H", slide, extras_offset + extra * 2)[0]
				starts.append((value & 0x3fff) * 4)
				extra += 1
				if value & 0x8000:
					break
		else:
			starts.append(start * 4)
		page_address = low + page * page_size
		for position in starts:
			while True:
				if position + 8 > page_size:
					raise ValueError("Cache rebase chain escaped its page")
				pointer_address = page_address + position
				value = struct.unpack("<Q", cache.read(pointer_address, 8))[0]
				delta = (value & delta_mask) >> shift
				decoded = value & ~delta_mask
				if decoded:
					decoded += value_add
				if address <= pointer_address and pointer_address + 8 <= address + len(data):
					struct.pack_into("<Q", data, pointer_address - address, decoded)
				if not delta:
					break
				position += delta


def extract_component(cache, image, destination):
	"""Rebuild file offsets while retaining original cache virtual addresses."""
	address = cache.images[image]
	header = cache.read(address, 32)
	count, command_size = struct.unpack_from("<II", header, 16)
	if command_size > 1024**2:
		raise ValueError("The component has an oversized command table")
	commands = bytearray(cache.read(address + 32, command_size))
	offset = 0
	segments = []
	symbol_command = indirect_command = None
	link_address = link_file_offset = 0
	for index in range(count):
		command, size = struct.unpack_from("<II", commands, offset)
		if size < 8 or offset + size > len(commands):
			raise ValueError("Invalid cached component command")
		if command == 25:
			name = commands[offset + 8:offset + 24].rstrip(b"\0")
			segment_address, virtual_size, file_offset, file_size = struct.unpack_from("<4Q", commands, offset + 24)
			if name == b"__LINKEDIT":
				link_address, link_file_offset = segment_address, file_offset
				link_command = offset
			else:
				segments.append((offset, segment_address, virtual_size, file_size))
		elif command == 2:
			symbol_command = offset
		elif command == 11:
			indirect_command = offset
		elif command in (0x22, 0x80000022):
			commands[offset + 8:offset + size] = bytes(size - 8)
		elif command in (0x1d, 0x26, 0x29, 0x80000033, 0x80000034):
			commands[offset + 8:offset + size] = bytes(size - 8)
		offset += size
	if symbol_command is None or indirect_command is None or not link_address:
		raise ValueError("Required cached symbol tables are missing")

	output = bytearray()
	for command, segment_address, virtual_size, file_size in segments:
		if file_size > MAXIMUM_COMPONENT_BYTES or len(output) + file_size > MAXIMUM_COMPONENT_BYTES:
			raise ValueError("The selected speech component exceeds its memory limit")
		output.extend(bytes(-len(output) % 4096))
		file_offset = len(output)
		data = bytearray(cache.read(segment_address, file_size))
		cache_slide_segment(cache, segment_address, data)
		output.extend(data)
		struct.pack_into("<QQ", commands, command + 40, file_offset, file_size)
		section_count = struct.unpack_from("<I", commands, command + 64)[0]
		for index in range(section_count):
			position = command + 72 + index * 80
			section_address = struct.unpack_from("<Q", commands, position + 32)[0]
			flags = struct.unpack_from("<I", commands, position + 64)[0]
			if flags & 255 != 1:
				struct.pack_into("<I", commands, position + 48, file_offset + section_address - segment_address)
			struct.pack_into("<II", commands, position + 56, 0, 0)

	def append_table(original_offset, size):
		if size > MAXIMUM_COMPONENT_BYTES or len(output) + size > MAXIMUM_COMPONENT_BYTES:
			raise ValueError("A speech symbol table exceeds its memory limit")
		output.extend(bytes(-len(output) % 8))
		position = len(output)
		output.extend(cache.read(link_address + original_offset - link_file_offset, size))
		return position

	output.extend(bytes(-len(output) % 4096))
	link_start = len(output)
	symbol_offset, symbol_count, string_offset, string_size = struct.unpack_from("<4I", commands, symbol_command + 8)
	if symbol_count * 16 > MAXIMUM_COMPONENT_BYTES:
		raise ValueError("Too many cached symbols in the speech component")
	symbols = bytearray(cache.read(link_address + symbol_offset - link_file_offset, symbol_count * 16))
	strings = bytearray(b"\0")
	names = {0: 0}
	def copy_name(original):
		if original in names:
			return names[original]
		if original >= string_size:
			raise ValueError("Invalid cached symbol name")
		data = cache.read(link_address + string_offset - link_file_offset + original, min(4096, string_size - original))
		end = data.find(b"\0")
		if end < 0:
			raise ValueError("Cached symbol name is too long")
		position = len(strings)
		strings.extend(data[:end + 1])
		names[original] = position
		return position
	for index in range(symbol_count):
		position = index * 16
		original = struct.unpack_from("<I", symbols, position)[0]
		struct.pack_into("<I", symbols, position, copy_name(original))
		if symbols[position + 4] & 0xe == 0xa:
			alias = struct.unpack_from("<Q", symbols, position + 8)[0]
			struct.pack_into("<Q", symbols, position + 8, copy_name(alias))
	new_symbols = len(output)
	output.extend(symbols)
	new_strings = len(output)
	output.extend(strings)
	struct.pack_into("<4I", commands, symbol_command + 8, new_symbols, symbol_count, new_strings, len(strings))
	indirect_offset, indirect_count = struct.unpack_from("<II", commands, indirect_command + 56)
	new_indirect = append_table(indirect_offset, indirect_count * 4)
	struct.pack_into("<II", commands, indirect_command + 56, new_indirect, indirect_count)
	struct.pack_into("<4I", commands, indirect_command + 64, 0, 0, 0, 0)
	struct.pack_into("<QQ", commands, link_command + 40, link_start, len(output) - link_start)
	output[:32] = header
	output[32:32 + len(commands)] = commands
	Path(destination).parent.mkdir(parents=True, exist_ok=True)
	Path(destination).write_bytes(output)
	return len(output)


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("cache", type=Path)
	parser.add_argument("image")
	parser.add_argument("output", type=Path)
	arguments = parser.parse_args()
	print(extract_component(IntelCache(arguments.cache), arguments.image, arguments.output))


if __name__ == "__main__":
	main()
