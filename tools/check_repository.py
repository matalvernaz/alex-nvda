"""Refuse tracked Apple components, test audio and generated binaries before publishing source."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {".py", ".c", ".h", ".cpp", ".md", ".txt", ".yml", ".yaml", ".ini", ".rc", ".manifest", ".exports"}
SPECIAL = {".gitignore", ".editorconfig", "LICENSE"}
FORBIDDEN_NAMES = {"pcmwave", "voicedescription", "macintalk", "speechdictionary", "stddictionary", "cartnames", "cartlite", "phonemesymbols", "homophoneseng", "tupleseng"}
MACHO = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def main():
	result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, stdout=subprocess.PIPE)
	files = result.stdout.decode("utf-8").split("\0")
	failures = []
	for name in filter(None, files):
		file = ROOT / name
		if file.name.lower() in FORBIDDEN_NAMES or (file.suffix not in ALLOWED and file.name not in SPECIAL):
			failures.append(name + ": not an approved source file")
			continue
		if file.is_symlink() or file.stat().st_size > 2 * 1024 * 1024:
			failures.append(name + ": a symlink or unexpectedly large source file")
			continue
		data = file.read_bytes()
		if data[:4] in MACHO or data[:2] == b"MZ":
			failures.append(name + ": contains a compiled executable")
			continue
		try:
			data.decode("utf-8")
		except UnicodeDecodeError:
			failures.append(name + ": is not UTF-8 source text")
	if failures:
		print("Refusing to publish:\n" + "\n".join(failures))
		return 1
	print("Source publication check passed: no Apple components, generated binaries or test audio.")
	return 0


if __name__ == "__main__":
	sys.exit(main())
