"""Build the modern x64 host serially without reading any Apple components."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vendor/panthera/tools/aac_experiment"))
import glint


def main():
	"""Compile serially so decoder and host compilation cannot compete for memory."""
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--glint-source", type=Path, required=True)
	parser.add_argument("--target", choices=("linux", "windows"), default="linux")
	parser.add_argument("--cc")
	parser.add_argument("--cxx")
	parser.add_argument("--checks", action="store_true")
	parser.add_argument("--capstone-source", type=Path)
	parser.add_argument("--llvm-root", type=Path)
	parser.add_argument("--windres", default="x86_64-w64-mingw32-windres")
	parser.add_argument("--make", default="make")
	arguments = parser.parse_args()
	windows = arguments.target == "windows"
	compiler = arguments.cc or ("x86_64-w64-mingw32-gcc" if windows else "x86_64-linux-gnu-gcc")
	if windows and not arguments.llvm_root:
		parser.error("Windows builds require --llvm-root pointing to the pinned LLVM-MinGW distribution")
	cxx = arguments.cxx or (str(arguments.llvm_root.resolve() / "bin/x86_64-w64-mingw32-clang++") if windows else "x86_64-linux-gnu-g++")
	output = ROOT / "build" / ("modern-windows" if windows else "modern")
	output.mkdir(parents=True, exist_ok=True)
	stage = output / "stage"
	if stage.exists():
		shutil.rmtree(stage)
	stage.mkdir()
	decoder = glint.prepare(arguments.glint_source.resolve(), stage, output)
	objects = []
	for name, source in [("decoder", decoder / "src/aac_decoder.cpp"), ("bridge", decoder / "glint_bridge.cpp")]:
		object_path = output / (name + ".o")
		subprocess.run([cxx, "-O2", "-D_USE_MATH_DEFINES", "-std=c++17", "-I" + str(decoder / "src"), "-c", str(source), "-o", str(object_path)], check=True)
		objects.append(str(object_path))
	source = ROOT / "modern" / ("checks.c" if arguments.checks else "host.c")
	binary = output / (("checks" if arguments.checks else "alex_modern_host") + (".exe" if windows else ""))
	if windows:
		if not arguments.capstone_source:
			parser.error("Windows setup requires --capstone-source pointing to Capstone 5.0.6")
		capstone = arguments.capstone_source.resolve()
		capstone_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=capstone, text=True).strip()
		if capstone_commit != "accf4df62f1fba6f92cae692985d27063552601c":
			parser.error("The Capstone checkout must be the pinned 5.0.6 source revision")
		subprocess.run([arguments.make, "-j1", "CAPSTONE_ARCHS=x86", "CAPSTONE_BUILD_CORE_ONLY=yes", "CAPSTONE_STATIC=yes", "CAPSTONE_SHARED=no", "CC=" + compiler, "AR=" + (arguments.llvm_root.resolve() / "bin/llvm-ar").as_posix(), "RANLIB=" + (arguments.llvm_root.resolve() / "bin/llvm-ranlib").as_posix()], cwd=capstone, check=True)
		objects.append(str(capstone / "capstone.lib"))
		object_path = output / "windows_cxx.o"
		subprocess.run([cxx, "-O1", "-std=c++17", "-c", str(ROOT / "modern/windows_cxx.cpp"), "-o", str(object_path)], check=True)
		objects.append(str(object_path))
		libraries = ["-lc++", "-lwinmm", "-lole32", "-lmfuuid"]
	else:
		libraries = ["-static-libstdc++", "-static-libgcc", "-lstdc++", "-lpthread", "-ldl", "-lm"]
	if windows:
		host_object = output / "host.o"
		subprocess.run([compiler, "-O1", "-g", "-fno-asynchronous-unwind-tables", "-fno-unwind-tables", "-maccumulate-outgoing-args", "-mno-red-zone", "-DTIGER_CACHE_SCAN", "-D_GNU_SOURCE", "-I" + str(capstone / "include"), "-I" + str(ROOT / "modern"), "-c", str(source), "-o", str(host_object)], check=True)
		resource = output / "manifest.o"
		subprocess.run([arguments.windres, "-i", "alex_host.rc", "-o", str(resource)], cwd=ROOT / "vendor/panthera/src", check=True)
		objects.append(str(resource))
		subprocess.run([cxx, str(host_object), *objects, "-o", str(binary), *libraries], check=True)
		for name in ("libc++.dll", "libunwind.dll"):
			shutil.copy2(arguments.llvm_root / "x86_64-w64-mingw32/bin" / name, output / name)
		notices = ROOT / "vendor/panthera/licenses"
		for source, name in ((arguments.llvm_root / "LICENSE.TXT", "LLVM-MinGW.txt"), (capstone / "LICENSE.TXT", "Capstone.txt"), (capstone / "LICENSE_LLVM.TXT", "Capstone-LLVM.txt")):
			(notices / name).write_text(source.read_text(encoding="utf-8").rstrip() + "\n", encoding="utf-8")
		if not arguments.checks:
			package = ROOT / "addon/synthDrivers/_alex_native/modern_runtime"
			package.mkdir(exist_ok=True)
			for name in ("alex_modern_host.exe", "libc++.dll", "libunwind.dll"):
				shutil.copy2(output / name, package / name)
	else:
		subprocess.run([compiler, "-O1", "-g", "-D_GNU_SOURCE", "-I" + str(ROOT / "modern"), str(source), *objects, "-o", str(binary), *libraries], check=True)
	print(binary)


if __name__ == "__main__":
	main()
