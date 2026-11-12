"""Expose only the verified, downloaded Alex installation to the shared speech driver."""

import os

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
	ready = tree is not None and os.path.isfile(HOST_EXE)
	return ready, ["Setup is complete." if ready else "Open NVDA Settings, Alex, then Download and set up Alex."]


def usable():
	return explain()[0]
