"""Tests de app.text.split_text (decoupage recommande par le projet VoxCPM)."""
import unittest

from app.text import split_text


class SplitTextTest(unittest.TestCase):
    def test_empty_returns_no_chunk(self):
        self.assertEqual(split_text(""), [])
        self.assertEqual(split_text("   \n  "), [])

    def test_short_text_single_chunk(self):
        chunks = split_text("Bonjour tout le monde.")
        self.assertEqual(len(chunks), 1)
        self.assertTrue(chunks[0].startswith("Bonjour"))

    def test_long_text_split_and_within_limit(self):
        text = "Premiere phrase ici. Deuxieme phrase la. " * 40
        chunks = split_text(text, max_chars=200)
        self.assertGreaterEqual(len(chunks), 3)
        self.assertTrue(all(len(c) <= 200 for c in chunks))

    def test_french_punctuation_is_separator(self):
        chunks = split_text("Un ? Deux ! Trois ; quatre… cinq", max_chars=8)
        self.assertGreaterEqual(len(chunks), 4)

    def test_monster_word_hard_cut(self):
        chunks = split_text("mot" * 300, max_chars=200)
        self.assertGreaterEqual(len(chunks), 2)
        self.assertTrue(all(len(c) <= 320 for c in chunks))

    def test_content_preserved(self):
        text = "Phrase un. Phrase deux. Phrase trois."
        joined = " ".join(split_text(text, max_chars=20))
        for word in ("Phrase", "un.", "deux.", "trois."):
            self.assertIn(word, joined)
