"""Tests des helpers WAV du moteur GGUF (format, canonisation, transcodage)."""
import os
import subprocess
import tempfile
import unittest

from app import gguf
from app.gguf import _canonical_wav, _ensure_wav, _wav_format, _wav_sample_rate

GGUF_AVAILABLE = gguf.available()

GUID_PCM = bytes.fromhex("0100000000001000800000aa00389b71")


def _synth_wave(path, tag, rate=48000, channels=1):
    """Ecrit un WAV minimaliste avec le format tag demande."""
    payload = b"\x00\x01" * (rate // 10 * channels)
    if tag == 0xFFFE:
        fmt = (tag.to_bytes(2, "little") + channels.to_bytes(2, "little")
               + rate.to_bytes(4, "little") + (rate * channels * 2).to_bytes(4, "little")
               + (channels * 2).to_bytes(2, "little") + (16).to_bytes(2, "little")
               + (22).to_bytes(2, "little") + (16).to_bytes(2, "little")
               + (3).to_bytes(4, "little") + GUID_PCM)
    else:
        fmt = (tag.to_bytes(2, "little") + channels.to_bytes(2, "little")
               + rate.to_bytes(4, "little") + (rate * channels * 2).to_bytes(4, "little")
               + (channels * 2).to_bytes(2, "little") + (16).to_bytes(2, "little"))
    head = (b"RIFF" + (36 + len(payload)).to_bytes(4, "little") + b"WAVE"
            + b"fmt " + len(fmt).to_bytes(4, "little") + fmt
            + b"data" + len(payload).to_bytes(4, "little"))
    with open(path, "wb") as f:
        f.write(head + payload)


class WavFormatTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="voxcpm_wav_")

    def test_pcm_tag1_detected(self):
        p = os.path.join(self.dir, "pcm.wav")
        _synth_wave(p, 1)
        self.assertEqual(_wav_format(p), 1)
        self.assertEqual(_wav_sample_rate(p), 48000)

    def test_extensible_tag_detected(self):
        p = os.path.join(self.dir, "ext.wav")
        _synth_wave(p, 0xFFFE)
        self.assertEqual(_wav_format(p), 0xFFFE)

    def test_float_tag_detected(self):
        p = os.path.join(self.dir, "float.wav")
        _synth_wave(p, 3)
        self.assertEqual(_wav_format(p), 3)

    def test_non_wav_file_rejected(self):
        self.assertIsNone(_wav_format(__file__))


class CanonicalWavTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="voxcpm_wav_")

    def test_extensible_rewritten_to_pcm(self):
        src = os.path.join(self.dir, "ext.wav")
        _synth_wave(src, 0xFFFE)
        dst = os.path.join(self.dir, "canon.wav")
        self.assertTrue(_canonical_wav(src, dst))
        self.assertEqual(_wav_format(dst), 1)
        self.assertEqual(_wav_sample_rate(dst), 48000)
        with open(src, "rb") as f:
            tail = f.read()[-9600:]
        with open(dst, "rb") as f:
            self.assertEqual(f.read()[-9600:], tail)

    def test_float_wav_refused(self):
        src = os.path.join(self.dir, "float.wav")
        _synth_wave(src, 3)
        self.assertFalse(_canonical_wav(src, os.path.join(self.dir, "out.wav")))


class EnsureWavTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="voxcpm_wav_")
        self.afconvert = os.access("/usr/bin/afconvert", os.X_OK)

    def test_pcm_wav_passthrough(self):
        src = os.path.join(self.dir, "pcm.wav")
        _synth_wave(src, 1)
        out, tmp = _ensure_wav(src)
        self.assertEqual(out, src)
        self.assertIsNone(tmp)

    def test_extensible_wav_canonicalized(self):
        if not self.afconvert:
            self.skipTest("afconvert indisponible")
        src = os.path.join(self.dir, "in.wav")
        _synth_wave(src, 1)
        ext = os.path.join(self.dir, "ext.wav")
        subprocess.run(["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16", src, ext], check=True)
        out, tmp = _ensure_wav(ext)
        self.assertEqual(_wav_format(out), 1)
        if tmp:
            os.remove(tmp)

    def test_m4a_decoded_to_pcm(self):
        if not self.afconvert:
            self.skipTest("afconvert indisponible")
        src = os.path.join(self.dir, "in.wav")
        _synth_wave(src, 1)
        m4a = os.path.join(self.dir, "ref.m4a")
        subprocess.run(["/usr/bin/afconvert", "-f", "m4af", "-d", "aac", src, m4a], check=True)
        out, tmp = _ensure_wav(m4a)
        self.assertEqual(_wav_format(out), 1)
        if tmp:
            self.assertGreater(os.path.getsize(tmp), 1000)
            os.remove(tmp)


class ModelsStatusTest(unittest.TestCase):
    def test_status_shape(self):
        st = gguf.status()
        self.assertIsInstance(st["available"], bool)
        self.assertIsInstance(st["models"], list)
        self.assertIn("gpu", st)

    def test_cli_path_shape(self):
        p = gguf.cli_path()
        self.assertTrue(p is None or os.path.isfile(p))

    def test_gpu_backend_name_per_platform(self):
        """macOS -> Metal ; ailleurs (Windows) -> Vulkan (backend amont)."""
        import sys as _sys
        expected = "Metal" if _sys.platform == "darwin" else "Vulkan"
        self.assertEqual(gguf.GPU_BACKEND_NAME, expected)
        self.assertEqual(gguf.gpu_status()["backend"], expected)
        self.assertIn("attempted", gguf.gpu_status())
        self.assertIn("supported", gguf.gpu_status())


@unittest.skipUnless(GGUF_AVAILABLE, "moteur GGUF non installe sur cette machine")
class InstalledModelsTest(unittest.TestCase):
    def test_models_listed_with_required_keys(self):
        models = gguf.installed_models()
        self.assertGreaterEqual(len(models), 1)
        for m in models:
            self.assertIn("id", m)
            self.assertIn("baselm", m)
            self.assertIn("acoustic", m)

    def test_status_reports_available(self):
        self.assertTrue(gguf.status()["available"])
