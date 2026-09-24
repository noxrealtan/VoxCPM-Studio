"""Tests de app.jobs : parametres, references audio, filtre de signature."""
import base64
import os
import unittest

from app import jobs
from app.state import MAX_TEXT_CHARS
from tests.util import AppTestCase


class ParamsFromPayloadTest(unittest.TestCase):
    def test_defaults(self):
        p = jobs.params_from_payload({"text": "Bonjour"})
        self.assertEqual(p["text"], "Bonjour")
        self.assertEqual(p["model_id"], "openbmb/VoxCPM2")
        self.assertEqual(p["device"], "auto")
        self.assertFalse(p["mp3"])
        self.assertIsNone(p["seed"])

    def test_seed_and_numbers_coerced(self):
        p = jobs.params_from_payload({"text": "x", "cfg": 1.8, "timesteps": "12",
                                      "seed": 42, "normalize": 1})
        self.assertEqual(p["cfg"], 1.8)
        self.assertEqual(p["timesteps"], 12)
        self.assertEqual(p["seed"], 42)
        self.assertTrue(p["normalize"])


class SaveReferenceTest(AppTestCase):
    def test_reference_saved_with_normalized_ext(self):
        ref = base64.b64encode(b"FAKE-AUDIO-BYTES").decode()
        params = {}
        jobs._save_reference({"reference_b64": ref, "reference_filename": "voix.M4A"}, params)
        self.assertEqual(params["ref_ext"], "m4a")
        self.assertTrue(os.path.isfile(os.path.join(jobs.REFS_DIR,
                                                    params["ref_hash"] + ".m4a")))

    def test_identical_content_deduplicated(self):
        ref = base64.b64encode(b"SAME-BYTES").decode()
        params = {}
        jobs._save_reference({"reference_b64": ref, "reference_filename": "a.wav"}, params)
        h1 = params["ref_hash"]
        jobs._save_reference({"reference_b64": ref, "reference_filename": "b.wav"}, params)
        self.assertEqual(params["ref_hash"], h1)
        self.assertEqual(len(os.listdir(jobs.REFS_DIR)), 1)

    def test_unknown_ext_defaults_to_wav(self):
        ref = base64.b64encode(b"zzz").decode()
        params = {}
        jobs._save_reference({"reference_b64": ref, "reference_filename": "x.exe"}, params)
        self.assertEqual(params["ref_ext"], "wav")

    def test_invalid_base64_raises(self):
        with self.assertRaises(Exception):
            jobs._save_reference({"reference_b64": "!!!", "reference_filename": "x.wav"}, {})


class FilterKwargsTest(unittest.TestCase):
    def test_only_supported_kwargs_kept(self):
        def f(a, b=1):
            pass
        self.assertEqual(jobs.filter_kwargs(f, {"a": 1, "b": 2, "c": 3}), {"a": 1, "b": 2})


class SiblingModulesBoundTest(unittest.TestCase):
    """Regression 2026-09-22 : jobs.py appelait audio.save_output sans importer
    audio -> NameError apres une generation native complete (chemin jamais
    exerce sur Mac Intel, ou seul le moteur GGUF tourne)."""

    def test_modules_used_as_attributes_are_imported(self):
        for mod in ("audio", "engine"):
            self.assertTrue(hasattr(jobs, mod), "app.jobs n'importe pas app.%s" % mod)

    def test_native_save_output_reachable(self):
        self.assertTrue(callable(jobs.audio.save_output))


class ParamsClampTest(unittest.TestCase):
    """S6 : bornes serveur sur cfg/timesteps (l'UI borne deja, l'API doit aussi)."""

    def test_cfg_bounded(self):
        self.assertEqual(jobs.params_from_payload({"text": "x", "cfg": 99})["cfg"], 6.0)
        self.assertEqual(jobs.params_from_payload({"text": "x", "cfg": -5})["cfg"], 1.0)

    def test_cfg_nan_becomes_default(self):
        self.assertEqual(jobs.params_from_payload({"text": "x", "cfg": float("nan")})["cfg"], 2.0)

    def test_cfg_garbage_becomes_default(self):
        self.assertEqual(jobs.params_from_payload({"text": "x", "cfg": "abc"})["cfg"], 2.0)

    def test_timesteps_bounded(self):
        self.assertEqual(jobs.params_from_payload({"text": "x", "timesteps": 1000})["timesteps"], 60)
        self.assertEqual(jobs.params_from_payload({"text": "x", "timesteps": -1})["timesteps"], 2)

    def test_timesteps_garbage_becomes_default(self):
        self.assertEqual(jobs.params_from_payload({"text": "x", "timesteps": None})["timesteps"], 10)


class GgufFreeEventTest(unittest.TestCase):
    """A2 : les jobs GGUF attendent l'Event gguf_free, plus de re-enfilement."""

    def test_event_exists_and_initially_set(self):
        from app.state import STATE
        self.assertIsInstance(STATE.gguf_free, __import__("threading").Event)
        self.assertTrue(STATE.gguf_free.is_set())
