"""Tests de app.audio : noms de sortie sans collision, encodage WAV/MP3."""
import os
import re
import unittest

from app import audio
from tests.util import AppTestCase


class UniqueOutputPathTest(AppTestCase):
    def test_unsafe_characters_sanitized(self):
        name = os.path.basename(audio.unique_output_path("mon fichier: spécial/ ça?", "wav"))
        self.assertFalse(re.search(r"[/:?]", name))
        self.assertTrue(name.endswith(".wav"))

    def test_long_name_truncated(self):
        name = os.path.basename(audio.unique_output_path("x" * 120, "wav"))
        self.assertLessEqual(len(name), 84)

    def test_collision_gets_suffix(self):
        open(os.path.join(audio.OUTPUTS_DIR, "col.wav"), "w").close()
        self.assertEqual(os.path.basename(audio.unique_output_path("col", "wav")), "col_2.wav")
        open(os.path.join(audio.OUTPUTS_DIR, "col_2.wav"), "w").close()
        self.assertEqual(os.path.basename(audio.unique_output_path("col", "wav")), "col_3.wav")


try:
    import lameenc    # noqa: F401
    import numpy      # noqa: F401
    import soundfile  # noqa: F401
    HAVE_AUDIO_DEPS = True
except ImportError:
    HAVE_AUDIO_DEPS = False


@unittest.skipUnless(HAVE_AUDIO_DEPS, "numpy/soundfile/lameenc absents sur cette machine")
class SaveOutputTest(AppTestCase):
    def test_wav_written(self):
        import numpy as np
        path, fmt = audio.save_output(np.zeros(4800, dtype="float32"), 48000, "test wav", False)
        self.assertEqual(fmt, "wav")
        self.assertGreater(os.path.getsize(path), 1000)

    def test_mp3_written(self):
        import numpy as np
        path, fmt = audio.save_output(np.zeros(4800, dtype="float32"), 48000, "test mp3", True)
        self.assertEqual(fmt, "mp3")
        self.assertGreater(os.path.getsize(path), 1000)

    def test_mp3_failure_falls_back_to_wav(self):
        import numpy as np
        original = audio.mp3_bytes
        audio.mp3_bytes = lambda *a, **k: None
        try:
            path, fmt = audio.save_output(np.zeros(4800, dtype="float32"), 48000,
                                          "test fallback", True)
            self.assertEqual(fmt, "wav")
        finally:
            audio.mp3_bytes = original
