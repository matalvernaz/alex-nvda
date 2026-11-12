"""Fetch pinned open-source build tools. This never downloads any Apple components."""

import argparse
import hashlib
from pathlib import Path
import platform
import subprocess
import tarfile
import urllib.request
import zipfile

LLVM_VERSION = "20261104"
CAPSTONE_PIN = "accf4df62f1fba6f92cae692985d27063552601c"
LLVM_ASSETS = {
	("Linux", "aarch64"): ("ubuntu-22.04-aarch64.tar.xz", "595e95bdffabfc62559fe26e30bdfbccf277cbaed4902793555015ee47306b94"),
	("Linux", "x86_64"): ("ubuntu-22.04-x86_64.tar.xz", "919380403de87dca3c581c2053230cd298af5e891286628ba0613b7fed370926"),
	("Windows", "amd64"): ("x86_64.zip", "552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f"),
}


def prepare(destination):
	destination = Path(destination).resolve()
	destination.mkdir(parents=True, exist_ok=True)
	key = (platform.system(), platform.machine().lower())
	if key == ("Windows", "x86_64"):
		key = ("Windows", "amd64")
	suffix, expected = LLVM_ASSETS[key]
	name = "llvm-mingw-" + LLVM_VERSION + "-ucrt-" + suffix
	archive = destination / name
	if not archive.exists():
		partial = archive.with_suffix(archive.suffix + ".partial")
		url = "https://github.com/mstorsjo/llvm-mingw/releases/download/" + LLVM_VERSION + "/" + name
		with urllib.request.urlopen(url, timeout=60) as source, partial.open("wb") as target:
			while chunk := source.read(1024 * 1024):
				target.write(chunk)
		partial.replace(archive)
	digest = hashlib.sha256()
	with archive.open("rb") as source:
		while chunk := source.read(1024 * 1024):
			digest.update(chunk)
	if digest.hexdigest() != expected:
		raise ValueError("LLVM-MinGW failed its pinned SHA-256 integrity check: " + str(archive))
	toolchain = destination / name.removesuffix(".tar.xz").removesuffix(".zip")
	if not toolchain.is_dir():
		if suffix.endswith(".zip"):
			with zipfile.ZipFile(archive) as source:
				source.extractall(destination)
		else:
			with tarfile.open(archive) as source:
				source.extractall(destination, filter="data")
	capstone = destination / "capstone"
	if not capstone.exists():
		subprocess.run(["git", "clone", "--no-checkout", "https://github.com/capstone-engine/capstone.git", str(capstone)], check=True)
	subprocess.run(["git", "checkout", "--detach", CAPSTONE_PIN], cwd=capstone, check=True)
	return toolchain, capstone


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--destination", type=Path, default=Path("build/dependencies"))
	arguments = parser.parse_args()
	for directory in prepare(arguments.destination):
		print(directory)
