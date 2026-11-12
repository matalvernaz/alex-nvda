"""Expose only the verified, downloaded Alex installation to the shared speech driver."""

import os
from types import SimpleNamespace

from . import paths

HOST_EXE = str(paths.HOST_EXE)
HOST_DLL = str(paths.HOST_EXE.with_suffix(".dll"))


def config_dir():
	return str(paths.data_root())


def find_tree():
	tree = paths.active_installation()
	return str(tree) if tree is not None else None


def engine_paths(tree):
	return (
		os.path.join(tree, *paths.REQUIRED_FILES[0].split("/")),
		os.path.join(tree, *paths.REQUIRED_FILES[1].split("/")),
		os.path.join(tree, "Speech", "Voices"),
	)


def read_voices(voices_directory, playable_only=False):
	descriptor = os.path.join(voices_directory, "Alex.SpeechVoice", "Contents", "Resources", "VoiceDescription")
	if os.path.isfile(descriptor):
		return [("Alex", "Alex", "meow")]
	return []


def explain():
	tree = find_tree()
	engine = paths.selected_engine() or "legacy"
	ready = tree is not None and paths.host_executable(engine).is_file()
	return ready, ["Setup is complete." if ready else "Open NVDA Settings, Alex, then Download and set up Alex."]


def usable():
	return explain()[0]


def selected_tree():
	"""Freeze the engine for this driver so changing setup cannot mix two host processes."""
	installation = paths.active_installation()
	engine = paths.selected_engine() or "legacy"
	executable = str(paths.host_executable(engine))
	return SimpleNamespace(
		TEXT_ENCODING="utf-8" if engine == "modern" else "mac_roman",
		HOST_EXE=executable,
		HOST_DLL=str(paths.host_executable(engine).with_suffix(".dll")),
		config_dir=config_dir,
		find_tree=lambda: str(installation) if installation is not None else None,
		engine_paths=engine_paths,
		read_voices=read_voices,
		explain=lambda: (installation is not None and os.path.isfile(executable), ["Run Alex setup if required components are missing."]),
	)
