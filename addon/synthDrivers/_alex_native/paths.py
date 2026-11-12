"""Keep Apple data outside the add-on so NVDA updates cannot erase the downloaded voice."""

import json
from pathlib import Path
import shutil

REQUIRED_FILES = (
	"Speech/Synthesizers/MacinTalk.SpeechSynthesizer/Contents/MacOS/MacinTalk",
	"SpeechDictionary.framework/Versions/A/SpeechDictionary",
	"SpeechDictionary.framework/Versions/A/Resources/CartLiteEng",
	"SpeechDictionary.framework/Versions/A/Resources/CartNamesEng",
	"SpeechDictionary.framework/Versions/A/Resources/PrefixDictionaryEng",
	"SpeechDictionary.framework/Versions/A/Resources/HomophonesEng",
	"libstdc++.6.0.9.dylib",
	"libc++abi.dylib",
	"Speech/Voices/Alex.SpeechVoice/Contents/Info.plist",
	"Speech/Voices/Alex.SpeechVoice/Contents/Resources/VoiceDescription",
	"Speech/Voices/Alex.SpeechVoice/Contents/Resources/PitchCoeffs.plist",
	"Speech/Voices/Alex.SpeechVoice/Contents/Resources/PCMWave",
)
HOST_EXE = Path(__file__).with_name("alex_host.exe")
MODERN_HOST_EXE = Path(__file__).with_name("modern_runtime") / "alex_modern_host.exe"
ENGINE_NAMES = {"modern": "Modern", "legacy": "Legacy (Lion)"}


def required_files(engine="legacy"):
	if engine not in ENGINE_NAMES:
		raise ValueError("Choose Modern or Legacy for the Alex engine.")
	if engine == "legacy":
		return REQUIRED_FILES
	return tuple(file for file in REQUIRED_FILES if not file.endswith(".dylib")) + (
		"SpeechDictionary.framework/Versions/A/SpeechDictionary.bindings",
		"SpeechDictionary.framework/Versions/A/Resources/TuplesEng",
		"SpeechDictionary.framework/Versions/A/Resources/PhonemeSymbolsEng",
		"SpeechDictionary.framework/Versions/A/Resources/SLCharClasses.re2h",
	)


def host_executable(engine):
	return MODERN_HOST_EXE if engine == "modern" else HOST_EXE


def data_root():
	import globalVars
	return Path(globalVars.appArgs.configPath) / "alex"


def complete_tree(tree, engine="legacy"):
	try:
		for relative in required_files(engine):
			file = Path(tree) / relative
			if not file.is_file() or file.stat().st_size == 0:
				return False
		return True
	except OSError:
		return False


def _managed_tree(root, state):
	"""A downloaded manifest can only name a direct, owned installation directory."""
	if not isinstance(state, dict) or state.get("format") != 1:
		raise ValueError("The Alex installation record is invalid. Run setup again.")
	name = state.get("directory")
	if not isinstance(name, str) or not name.startswith("install-") or Path(name).name != name or "/" in name or "\\" in name:
		raise ValueError("The Alex installation record has an unsafe directory.")
	tree = root / name
	if tree.is_symlink() or tree.resolve().parent != root.resolve():
		raise ValueError("The Alex installation directory is outside its data folder.")
	return tree


def _read_state(file):
	return json.loads(file.read_text(encoding="utf-8"))


def _write_state(file, state):
	pending = file.with_suffix(file.suffix + ".pending")
	pending.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
	pending.replace(file)


def selected_engine(root=None):
	root = Path(root) if root is not None else data_root()
	try:
		state = _read_state(root / "current.json")
		engine = state.get("engine_key", "legacy")
		return engine if engine in ENGINE_NAMES else None
	except (OSError, ValueError, TypeError, AttributeError):
		return None


def installed_engines(root=None):
	root = Path(root) if root is not None else data_root()
	result = {}
	for engine in ENGINE_NAMES:
		file = root / (engine + ".json")
		if not file.exists() and selected_engine(root) == engine:
			file = root / "current.json"
		try:
			state = _read_state(file)
			tree = _managed_tree(root, state)
			if complete_tree(tree, engine):
				result[engine] = state
		except (OSError, ValueError, TypeError, AttributeError):
			continue
	return result


def publish_installation(root, engine, state):
	"""Record the tested engine while retaining the previous engine for switching back."""
	root = Path(root)
	tree = _managed_tree(root, state)
	if not complete_tree(tree, engine):
		raise ValueError("Required Alex components are missing. Run setup again.")
	previous = installed_engines(root)
	for key, installed in previous.items():
		if not (root / (key + ".json")).exists():
			_write_state(root / (key + ".json"), installed)
	state = dict(state, engine_key=engine)
	engine_file = root / (engine + ".json")
	old_record = _read_state(engine_file) if engine_file.exists() else None
	_write_state(root / (engine + ".json"), state)
	try:
		_write_state(root / "current.json", state)
	except OSError:
		if old_record is None:
			engine_file.unlink(missing_ok=True)
		else:
			_write_state(engine_file, old_record)
		raise
	# Repairs replace only this engine's previous installation after the new one is selected.
	old = previous.get(engine)
	if old and old["directory"] != state["directory"] and not any(item["directory"] == old["directory"] for key, item in previous.items() if key != engine):
		try:
			shutil.rmtree(_managed_tree(root, old))
		except OSError:
			# A temporary file lock must not turn a successful setup into a failure.
			pass
	return state


def select_engine(root, engine):
	root = Path(root)
	installed = installed_engines(root)
	if engine not in installed:
		raise ValueError("This Alex engine is not installed. Download it first.")
	_write_state(root / "current.json", dict(installed[engine], engine_key=engine))


def remove_engine(root, engine):
	"""Retire only the requested engine; shared hard-linked voice data survives in the other tree."""
	root = Path(root)
	if engine not in ENGINE_NAMES:
		raise ValueError("Unknown Alex engine.")
	file = root / (engine + ".json")
	if not file.exists() and selected_engine(root) == engine:
		file = root / "current.json"
	if not file.exists():
		return
	state = _read_state(file)
	tree = _managed_tree(root, state)
	if selected_engine(root) == engine:
		others = installed_engines(root)
		others.pop(engine, None)
		if others:
			select_engine(root, next(iter(others)))
		else:
			(root / "current.json").unlink(missing_ok=True)
	(root / (engine + ".json")).unlink(missing_ok=True)
	if tree.exists():
		shutil.rmtree(tree)


def active_installation(root=None):
	root = Path(root) if root is not None else data_root()
	try:
		state = _read_state(root / "current.json")
		engine = state.get("engine_key", "legacy")
		tree = _managed_tree(root, state)
		return tree if engine in ENGINE_NAMES and complete_tree(tree, engine) else None
	except (OSError, ValueError, KeyError, TypeError, AttributeError):
		return None
