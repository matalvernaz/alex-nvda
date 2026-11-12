"""Keep accented text and complete emoji names when the modern engine receives NVDA speech."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "addon/synthDrivers"))
from _alex_native.unicode_text import encode_modern


class ModernTextTests(unittest.TestCase):
	def test_accents_and_non_latin_letters_survive(self):
		text = "Café résumé. Ελληνικά. 日本語."
		self.assertEqual(encode_modern(text), text.encode("utf-8"))

	def test_joined_emoji_is_one_name(self):
		result = encode_modern("Developer 👩‍💻.").decode()
		self.assertIn("woman technologist", result)
		self.assertNotIn("zero width joiner", result)
		self.assertNotIn("👩", result)

	def test_flags_keep_their_country_name(self):
		self.assertIn("Canada", encode_modern("🇨🇦").decode())

	def test_nul_cannot_truncate_an_utterance(self):
		self.assertEqual(encode_modern("first\0second"), b"first second")


if __name__ == "__main__":
	unittest.main()
