"""Keep Apple data outside the add-on so NVDA updates cannot erase the downloaded voice."""

import json
from pathlib import Path

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


def data_root():
	import globalVars
	return Path(globalVars.appArgs.configPath) / "alex"


def complete_tree(tree):
	try:
		for relative in REQUIRED_FILES:
			file = Path(tree) / relative
			if not file.is_file() or file.stat().st_size == 0:
				return False
		return True
	except OSError:
		return False


def active_installation(root=None):
	root = Path(root) if root is not None else data_root()
	try:
		state = json.loads((root / "current.json").read_text(encoding="utf-8"))
		name = state["directory"]
		if state.get("format") != 1 or not isinstance(name, str):
			return None
		if not name.startswith("install-") or Path(name).name != name or "/" in name or "\\" in name:
			return None
		tree = root / name
		return tree if complete_tree(tree) else None
	except (OSError, ValueError, KeyError, TypeError, AttributeError):
		return None
