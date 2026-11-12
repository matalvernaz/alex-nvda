"""Build the separate Linux x86_64 prototype without reading any Apple components."""

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
	parser.add_argument("--cc", default="x86_64-linux-gnu-gcc")
	parser.add_argument("--cxx", default="x86_64-linux-gnu-g++")
	parser.add_argument("--checks", action="store_true")
	arguments = parser.parse_args()
	output = ROOT / "build/modern"
	output.mkdir(parents=True, exist_ok=True)
	stage = output / "stage"
	if stage.exists():
		shutil.rmtree(stage)
	stage.mkdir()
	decoder = glint.prepare(arguments.glint_source.resolve(), stage, output)
	objects = []
	for name, source in [("decoder", decoder / "src/aac_decoder.cpp"), ("bridge", decoder / "glint_bridge.cpp")]:
		object_path = output / (name + ".o")
		subprocess.run([arguments.cxx, "-O2", "-std=c++17", "-I" + str(decoder / "src"), "-c", str(source), "-o", str(object_path)], check=True)
		objects.append(str(object_path))
	source = ROOT / "modern" / ("checks.c" if arguments.checks else "host.c")
	binary = output / ("checks" if arguments.checks else "alex_modern_host")
	subprocess.run([arguments.cc, "-O1", "-g", "-D_GNU_SOURCE", "-I" + str(ROOT / "modern"), str(source), *objects, "-o", str(binary), "-static-libstdc++", "-static-libgcc", "-lstdc++", "-lpthread", "-ldl", "-lm"], check=True)
	print(binary)


if __name__ == "__main__":
	main()
