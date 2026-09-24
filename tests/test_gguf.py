"""Tests des helpers WAV du moteur GGUF (format, canonisation, transcodage, sonde GPU)."""
import os
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

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
        """Metal sous macOS ; Vulkan ailleurs (convention amont, sans dossier bin)."""
        import sys as _sys
        expected = "Metal" if _sys.platform == "darwin" else "Vulkan"
        self.assertEqual(gguf.GPU_BACKEND_NAME, expected)
        self.assertEqual(gguf.gpu_status()["backend"], expected)
        self.assertIn("attempted", gguf.gpu_status())
        self.assertIn("supported", gguf.gpu_status())

    def test_detect_backend_from_libs(self):
        """Le backend compilé se lit dans les dylibs/DLL de gguf/bin."""
        import tempfile as _tempfile
        for lib, expected in (("libggml-metal.0.dylib", "Metal"),
                              ("ggml-vulkan.dll", "Vulkan"),
                              ("libggml-cuda.so", "CUDA")):
            with _tempfile.TemporaryDirectory() as tmp:
                open(os.path.join(tmp, lib), "wb").close()
                self.assertEqual(gguf.detect_backend(tmp), expected)
        with _tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(gguf.detect_backend(tmp))
        self.assertIsNone(gguf.detect_backend("/chemin/inexistant"))


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


class _InlineThread:
    """Remplace threading.Thread pour executer la cible de façon déterministe."""

    def __init__(self, target, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


class GpuProbeTest(unittest.TestCase):
    """Sonde GPU au démarrage : règles de déclenchement, verdicts, concurrence.

    Tout est doublé (CLI, processus) : ces tests ne dépendent ni du binaire
    ni d'un GPU et tournent en CI comme sur toute machine.
    """

    MODEL = {"id": "gguf:VoxCPM-0.5B-BaseLM-Q8_0",
             "baselm": "a.gguf", "acoustic": "b.gguf"}

    def setUp(self):
        self._saved = (gguf._GPU_STATE["supported"], gguf._PROBE_STATE["phase"])
        gguf._GPU_STATE["supported"] = None
        gguf._PROBE_STATE["phase"] = "idle"
        self.addCleanup(self._restore)

    def _restore(self):
        gguf._GPU_STATE["supported"], gguf._PROBE_STATE["phase"] = self._saved

    def test_status_exposes_probe_phase(self):
        gguf._PROBE_STATE["phase"] = "running"
        self.assertEqual(gguf.gpu_status()["probe"], "running")

    def test_noop_when_verdict_already_known(self):
        gguf._GPU_STATE["supported"] = False
        with mock.patch("app.gguf.sys.platform", "win32"):
            gguf.start_gpu_probe()
        self.assertEqual(gguf._PROBE_STATE["phase"], "idle")

    def test_noop_without_cli_or_models(self):
        with mock.patch("app.gguf.sys.platform", "win32"), \
             mock.patch.object(gguf, "cli_path", return_value=None):
            gguf.start_gpu_probe()
        self.assertEqual(gguf._PROBE_STATE["phase"], "idle")
        with mock.patch("app.gguf.sys.platform", "win32"), \
             mock.patch.object(gguf, "installed_models", return_value=[]):
            gguf.start_gpu_probe()
        self.assertEqual(gguf._PROBE_STATE["phase"], "idle")

    def test_probe_starts_and_completes_on_windows(self):
        # La CI n'a ni binaire ni modeles : la sonde ne doit tourner que si
        # les deux existent — on les simule donc explicitement ici.
        with mock.patch("app.gguf.sys.platform", "win32"), \
             mock.patch.object(gguf.threading, "Thread", _InlineThread), \
             mock.patch.object(gguf, "cli_path", return_value="/fake/cli"), \
             mock.patch.object(gguf, "installed_models", return_value=[self.MODEL]), \
             mock.patch.object(gguf, "_run_probe_cli", return_value=True) as run:
            gguf.start_gpu_probe()
        run.assert_called_once()
        self.assertEqual(gguf._GPU_STATE["supported"], True)
        self.assertEqual(gguf._PROBE_STATE["phase"], "done")
        self.assertEqual(gguf.STATE.gguf_backend, "GPU (%s)" % gguf.GPU_BACKEND_NAME)

    def test_probe_failure_records_cpu(self):
        with mock.patch.object(gguf, "_run_probe_cli", return_value=False):
            gguf._probe_worker(self.MODEL)
        self.assertEqual(gguf._GPU_STATE["supported"], False)
        self.assertEqual(gguf._PROBE_STATE["phase"], "done")
        self.assertEqual(gguf.STATE.gguf_backend, "CPU")

    def test_probe_timeout_counts_as_unavailable(self):
        with mock.patch.object(gguf.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(cmd="cli", timeout=60)):
            self.assertFalse(gguf._run_probe_cli(self.MODEL, "/tmp/x.wav", 60))

    def test_probe_cleans_temp_file(self):
        fd, out = tempfile.mkstemp(prefix="voxcpm_probe_test_", suffix=".wav")
        os.close(fd)
        os.remove(out)
        with mock.patch.object(gguf.tempfile, "mkstemp", return_value=(fd, out)), \
             mock.patch.object(gguf, "_run_probe_cli", return_value=True):
            gguf._probe_worker(self.MODEL)
        self.assertFalse(os.path.exists(out))

    def test_generate_waits_for_running_probe(self):
        done = {"finished": False}

        def fake_run_cli(cmd, out_path, gpu=False):
            return 0, True

        def gen():
            gguf._generate(self.MODEL, "Bonjour", "", None, "", 2.0, 4, None,
                           "/tmp/out.wav", use_gpu=False)
            done["finished"] = True

        gguf._PROBE_STATE["phase"] = "running"
        with mock.patch.object(gguf, "cli_path", return_value="/fake/cli"), \
             mock.patch.object(gguf, "_run_cli", fake_run_cli):
            t = threading.Thread(target=gen)
            t.start()
            t.join(0.4)
            self.assertFalse(done["finished"],
                             "_generate n'a pas attendu la fin de la sonde")
            gguf._PROBE_STATE["phase"] = "done"
            t.join(2)
            self.assertTrue(done["finished"])

    def test_generate_after_failed_probe_goes_straight_to_cpu(self):
        gguf._GPU_STATE["supported"] = False
        calls = []

        def fake_run_cli(cmd, out_path, gpu=False):
            calls.append(gpu)
            return 0, True

        with mock.patch.object(gguf, "cli_path", return_value="/fake/cli"), \
             mock.patch.object(gguf, "_run_cli", fake_run_cli):
            gguf._generate(self.MODEL, "Bonjour", "", None, "", 2.0, 4, None,
                           "/tmp/out.wav", use_gpu=True)
        self.assertEqual(calls, [False],
                         "une tentative GPU ne doit pas être relancée après un échec connu")
