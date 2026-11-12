"""Build the modern Windows host using verified open-source build dependencies."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

from modern_dependencies import prepare

ROOT = Path(__file__).resolve().parents[1]


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--dependency-root", type=Path, default=ROOT / "build/dependencies")
	parser.add_argument("--glint-source", type=Path, required=True)
	parser.add_argument("--checks", action="store_true")
	arguments = parser.parse_args()
	llvm, capstone = prepare(arguments.dependency_root)
	command = [sys.executable, str(ROOT / "modern/build.py"), "--target", "windows", "--llvm-root", str(llvm), "--capstone-source", str(capstone), "--glint-source", str(arguments.glint_source)]
	if os.name == "nt":
		command += ["--cc", "gcc", "--windres", "windres"]
	if arguments.checks:
		command.append("--checks")
	subprocess.run(command, check=True)
