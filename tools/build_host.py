"""Cross-compile Panthera's MIT host and pinned Glint decoder without any Apple input."""

import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "vendor/panthera"
sys.path.insert(0, str(UPSTREAM / "tools/aac_experiment"))
import glint


def main():
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--glint-source", type=Path, required=True)
	parser.add_argument("--target", choices=("windows", "linux"), default="windows")
	parser.add_argument("--cc")
	parser.add_argument("--cxx")
	parser.add_argument("--windres", default="i686-w64-mingw32-windres")
	arguments = parser.parse_args()
	output = ROOT / "build" / arguments.target
	output.mkdir(parents=True, exist_ok=True)
	stage = output / "stage"
	if stage.exists():
		shutil.rmtree(stage)
	stage.mkdir()
	host = stage / "host"
	shutil.copytree(UPSTREAM / "src", host)
	decoder = glint.prepare(arguments.glint_source, stage, host)
	if arguments.target == "windows":
		compiler = "i686-w64-mingw32-gcc"
		cxx = "i686-w64-mingw32-g++"
		flags = ["-D_WIN32_WINNT=0x0601", "-DTIGER_AAC_FALLBACK"]
		libraries = ["-static", "-Wl,--large-address-aware", "-lwinmm", "-lole32", "-lmfuuid"]
		binary = output / "alex_host.exe"
	else:
		compiler = "i686-linux-gnu-gcc"
		cxx = "i686-linux-gnu-g++"
		flags = ["-D_GNU_SOURCE", "-DTIGER_AAC_GLINT"]
		libraries = ["-static-libstdc++", "-static-libgcc", "-lstdc++", "-lpthread", "-ldl", "-lm"]
		binary = output / "alex_host"
	compiler = arguments.cc or compiler
	cxx = arguments.cxx or cxx
	common = ["-O2", "-fno-strict-aliasing", "-msse2", "-mfpmath=sse", "-mstackrealign", "-D_USE_MATH_DEFINES"]
	objects = []
	for name, source in [("decoder", decoder / "src/aac_decoder.cpp"), ("bridge", decoder / "glint_bridge.cpp")]:
		object_path = output / (name + ".o")
		subprocess.run([cxx, *common, "-std=c++17", "-I" + str(decoder / "src"), "-c", str(source), "-o", str(object_path)], check=True)
		objects.append(str(object_path))
	if arguments.target == "windows":
		resource = output / "manifest.o"
		subprocess.run([arguments.windres, "-i", "alex_host.rc", "-o", str(resource)], cwd=host, check=True)
		objects.append(str(resource))
	command = [compiler, *common, *flags, str(host / "tiger_host.c"), *objects, "-o", str(binary), "-lstdc++", *libraries]
	subprocess.run(command, check=True)
	if arguments.target == "windows":
		shutil.copy2(binary, ROOT / "addon/synthDrivers/_alex_native/alex_host.exe")
	print(binary)


if __name__ == "__main__":
	main()
