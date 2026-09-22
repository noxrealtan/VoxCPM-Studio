"""Tests de app.engine : cycle de vie, resolution de modeles, device."""
import unittest

from app import engine, gguf
from app.state import STATE


class GgufModelIdTest(unittest.TestCase):
    def test_gguf_prefix_detected(self):
        self.assertTrue(engine.is_gguf_model("gguf:VoxCPM2-BaseLM-Q8_0"))
        self.assertFalse(engine.is_gguf_model("openbmb/VoxCPM2"))
        self.assertFalse(engine.is_gguf_model(""))
        self.assertFalse(engine.is_gguf_model(None))

    def test_find_model_exact_id(self):
        if not gguf.available():
            self.skipTest("moteur GGUF non installe")
        m = engine.find_gguf_model("gguf:VoxCPM2-BaseLM-Q8_0")
        self.assertIsNotNone(m)
        self.assertEqual(m["id"], "gguf:VoxCPM2-BaseLM-Q8_0")

    def test_find_model_unknown_returns_none(self):
        self.assertIsNone(engine.find_gguf_model("gguf:inexistant"))


class TorchInfoTest(unittest.TestCase):
    def test_info_shape(self):
        info = engine.torch_info()
        for key in ("torch", "cuda", "cuda_name", "mps"):
            self.assertIn(key, info)

    def test_resolve_device_explicit_is_kept(self):
        self.assertEqual(engine.resolve_device("cpu"), "cpu")
        self.assertEqual(engine.resolve_device("cuda"), "cuda")


class UnloadModelTest(unittest.TestCase):
    def test_unload_resets_state(self):
        engine.unload_model()
        self.assertIsNone(STATE.model_id)
        self.assertIsNone(STATE.load_error)
