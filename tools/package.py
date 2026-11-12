"""Package only approved add-on code, its native host and notices, refusing Apple files."""

from pathlib import Path
import struct
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / "addon"
HOST = "synthDrivers/_alex_native/alex_host.exe"
ALLOWED_EXTENSIONS = {".py", ".ini", ".txt", ".html"}
APPLE_MAGIC = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def approved_files(addon=ADDON):
	files = []
	for path in sorted(Path(addon).rglob("*")):
		if path.is_dir() or "__pycache__" in path.parts:
			continue
		relative = path.relative_to(addon).as_posix()
		if path.is_symlink():
			raise ValueError("Cannot package a symlink: " + relative)
		if relative != HOST and path.suffix.lower() not in ALLOWED_EXTENSIONS:
			raise ValueError("Unapproved add-on file: " + relative)
		with path.open("rb") as stream:
			header = stream.read(4)
		if header in APPLE_MAGIC:
			raise ValueError("Apple Mach-O binary found: " + relative)
		if path.stat().st_size > 8 * 1024 * 1024:
			raise ValueError("Unexpectedly large add-on file: " + relative)
		files.append((relative, path))
	if not any(relative == HOST for relative, path in files):
		raise ValueError("Build the native Windows host before packaging.")
	return files


def check_host(path):
	with path.open("rb") as stream:
		if stream.read(2) != b"MZ":
			raise ValueError("The host is not a Windows executable.")
		stream.seek(0x3C)
		offset = struct.unpack("<I", stream.read(4))[0]
		stream.seek(offset)
		if stream.read(6) != b"PE\x00\x00\x4c\x01":
			raise ValueError("The host must be an i386 Windows executable.")
		stream.seek(offset + 22)
		characteristics = struct.unpack("<H", stream.read(2))[0]
		if not characteristics & 0x20:
			raise ValueError("The host must support the large address space Alex requires.")


def main():
	files = approved_files()
	check_host(ADDON / HOST)
	manifest = (ADDON / "manifest.ini").read_text(encoding="utf-8")
	version = next(line.split("=", 1)[1].strip() for line in manifest.splitlines() if line.startswith("version ="))
	output = ROOT / "dist" / ("alex-" + version + ".nvda-addon")
	output.parent.mkdir(exist_ok=True)
	notices = [ROOT / "LICENSE"]
	notices += [ROOT / "vendor/panthera/licenses" / name for name in ("Panthera-MIT.txt", "Glint-MIT.txt", "GCC-runtime-exception.txt", "GCC-GPL-3.0.txt", "libstdc++-notice.txt")]
	with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
		for relative, path in files:
			archive.write(path, relative)
		for path in notices:
			archive.write(path, "licenses/" + path.name)
	print(str(output) + ": " + str(output.stat().st_size) + " bytes; no Apple files included")


if __name__ == "__main__":
	main()
