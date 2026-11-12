"""Keep Unicode text intact and supply English emoji labels before the modern speech engine reads it."""

from functools import lru_cache
from pathlib import Path
import unicodedata


@lru_cache(maxsize=1)
def _emoji_trie():
	trie = {}
	with Path(__file__).with_name("emoji_names.txt").open(encoding="utf-8") as source:
		for line in source:
			if not line.strip() or line.startswith("#"):
				continue
			symbol, name = line.rstrip("\n").split("\t", 1)
			branch = trie
			for character in symbol:
				branch = branch.setdefault(character, {})
			branch[None] = name
	return trie


def encode_modern(text):
	"""Avoid MacRoman folding and match complete emoji sequences, including joined families and flags."""
	text = text.replace("\x00", " ")
	if text.isascii():
		return text.encode("utf-8")
	trie = _emoji_trie()
	text = text.replace("\ufe0f", "").replace("\ufe0e", "")
	output = []
	position = 0
	while position < len(text):
		branch = trie
		end = position
		matched = None
		matched_end = position
		while end < len(text) and text[end] in branch:
			branch = branch[text[end]]
			end += 1
			if None in branch:
				matched = branch[None]
				matched_end = end
		if matched is not None:
			output.append(" " + matched + " ")
			position = matched_end
			continue
		character = text[position]
		value = ord(character)
		if 0x1f000 <= value <= 0x1faff or 0x2600 <= value <= 0x27bf:
			output.append(" " + unicodedata.name(character, "emoji").lower().replace("_", " ") + " ")
		elif character != "\u200d" or not ((position > 0 and 0x1f000 <= ord(text[position - 1]) <= 0x1faff) or (position + 1 < len(text) and 0x1f000 <= ord(text[position + 1]) <= 0x1faff)):
			output.append(character)
		position += 1
	return "".join(output).encode("utf-8", "replace")
