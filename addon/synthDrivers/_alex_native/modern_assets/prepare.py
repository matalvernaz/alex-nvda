"""Prepare local binding metadata for an extracted Intel shared-cache speech library."""

import argparse
import json
from pathlib import Path
import struct


def fingerprint(data):
	"""Identify the exact local component so metadata from another build is refused."""
	value = 14695981039346656037
	for byte in data:
		value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
	return value


def inspect_component(data):
	"""Read the symbol and section tables required to restore cached imports."""
	if data[:4] != b"\xcf\xfa\xed\xfe":
		raise ValueError("An extracted Intel 64-bit Mach-O is required")
	sections = []
	segments = []
	dependencies = []
	offset = 32
	symbol_offset = symbol_count = strings_offset = indirect_offset = 0
	for index in range(struct.unpack_from("<I", data, 16)[0]):
		command, size = struct.unpack_from("<II", data, offset)
		if size < 8 or offset + size > len(data):
			raise ValueError("Invalid Mach-O command bounds")
		if command == 2:
			symbol_offset, symbol_count, strings_offset, strings_size = struct.unpack_from("<4I", data, offset + 8)
		if command == 11:
			indirect_offset = struct.unpack_from("<I", data, offset + 56)[0]
		if command in (0xc, 0x80000018, 0x8000001f):
			name_offset = struct.unpack_from("<I", data, offset + 8)[0]
			dependencies.append(data[offset + name_offset:offset + size].split(b"\0", 1)[0].decode())
		if command == 25:
			name = data[offset + 8:offset + 24].rstrip(b"\0")
			address, length = struct.unpack_from("<QQ", data, offset + 24)
			if name != b"__LINKEDIT":
				segments.append((address, address + length))
			for section_index in range(struct.unpack_from("<I", data, offset + 64)[0]):
				position = offset + 72 + section_index * 80
				name = data[position:position + 16].rstrip(b"\0")
				address, length, file_offset = struct.unpack_from("<QQI", data, position + 32)
				flags, reserved_first, stride = struct.unpack_from("<III", data, position + 64)
				sections.append((name, address, length, file_offset, flags, reserved_first, stride))
		offset += size
	symbols = []
	queries = {}
	for index in range(symbol_count):
		name_offset, kind, section_index, description, value = struct.unpack_from("<IBBHQ", data, symbol_offset + 16 * index)
		position = strings_offset + name_offset
		name = data[position:data.index(0, position)].decode()
		symbols.append(name)
		ordinal = description >> 8
		if kind & 0xe == 0 and name and 0 < ordinal <= len(dependencies):
			queries.setdefault(dependencies[ordinal - 1], []).append(name)
	return sections, segments, symbols, indirect_offset, queries


def scan_component(data, decoded_references=None):
	"""Use instruction decoding to find imports moved to the cache's shared GOT."""
	sections, segments, symbols, indirect_offset, queries = inspect_component(data)
	bindings = {}
	references = set()
	if decoded_references is None:
		import capstone
		decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
		decoder.detail = True
		decoder.skipdata = True
	else:
		for target in decoded_references:
			if not any(low <= target < high for low, high in segments):
				references.add(target)
	for name, address, length, offset, flags, first_symbol, stride in sections:
		if flags & 255 == 8:
			if not stride:
				raise ValueError("A stub section has no instruction stride")
			for index in range(length // stride):
				symbol = struct.unpack_from("<I", data, indirect_offset + (first_symbol + index) * 4)[0]
				position = offset + index * stride
				if symbol & 0xc0000000:
					continue
				if data[position:position + 2] != b"\xff\x25":
					raise ValueError("Unsupported cached Intel stub")
				displacement = struct.unpack_from("<i", data, position + 2)[0]
				bindings[address + index * stride + 6 + displacement] = symbols[symbol]
		if decoded_references is not None or name not in (b"__text", b"__stubs"):
			continue
		for instruction in decoder.disasm(data[offset:offset + length], address):
			if not instruction.id:
				continue
			for operand in instruction.operands:
				if operand.type != capstone.x86.X86_OP_MEM or operand.mem.base != capstone.x86.X86_REG_RIP:
					continue
				target = instruction.address + instruction.size + operand.mem.disp
				if not any(low <= target < high for low, high in segments):
					references.add(target)
	return bindings, sorted(references - bindings.keys()), queries


def main():
	"""Generate scan inputs, or combine them with data resolved from the original cache."""
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("component", type=Path)
	parser.add_argument("--resolved", type=Path)
	parser.add_argument("--symbols", type=Path)
	arguments = parser.parse_args()
	data = arguments.component.read_bytes()
	prefix = str(arguments.component)
	if not arguments.resolved:
		bindings, references, queries = scan_component(data)
		Path(prefix + ".stubs.json").write_text(json.dumps(bindings, indent=2))
		Path(prefix + ".references.json").write_text(json.dumps(references, indent=2))
		Path(prefix + ".queries.json").write_text(json.dumps([{"image": image, "names": names} for image, names in queries.items()], indent=2))
		print("Wrote local cache queries beside " + prefix)
		return
	bindings = {int(address): name for address, name in json.loads(Path(prefix + ".stubs.json").read_text()).items()}
	for item in json.loads(arguments.resolved.read_text()):
		bindings[item["slot"]] = item["name"]
	lines = [f"# source {fingerprint(data):016x}\n"]
	lines.extend(f"{address:x} {name}\n" for address, name in sorted(bindings.items()))
	if arguments.symbols:
		for name, address in json.loads(arguments.symbols.read_text()).items():
			lines.append(f"@{address:x} {name}\n")
	Path(prefix + ".bindings").write_text("".join(lines))
	print(f"Wrote {len(bindings)} locally resolved import slots")


if __name__ == "__main__":
	main()
