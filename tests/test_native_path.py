"""Chemin du moteur NATIF PyTorch, testé par doubles.

torch et les poids ne sont jamais présents en CI (et pas sur ce Mac) :
on valide donc l'orchestration complète de jobs.run_generation avec un
faux modèle, un faux numpy et une sortie WAV standard — exactement les
points de contact que le vrai VoxCPM doit satisfaire.
"""
import os
import sys
import unittest
from unittest import mock

from app import engine, jobs
from app.state import STATE
from tests.util import AppTestCase

# ---------------------------------------------------------------- faux numpy
# Le module numpy est importé DANS run_generation : un module factice dans
# sys.modules suffit, et les tests tournent alors sur toute machine.


class _FakeArr:
    def __init__(self, data):
        self.data = list(data)
        self.size = len(self.data)
        self.ndim = 1

    def __len__(self):
        return self.size

    def reshape(self, *_a):
        return self

    def __iter__(self):
        return iter(self.data)


def _install_fake_numpy():
    import types
    fake = types.ModuleType("numpy")
    fake.float32 = float
    fake.asarray = lambda seq, dtype=None: _FakeArr(seq)
    fake.concatenate = lambda seq: _FakeArr(
        [x for part in seq for x in part.data])
    sys.modules["numpy"] = fake


_UNSET = object()


class _FakeModel:
    """Faux VoxCPM : signature volontairement incomplète pour vérifier
    que filter_kwargs ne transmet que les paramètres réellement supportés,
    et sentinelle pour distinguer « non transmis » de « transmis None »."""

    def generate(self, text, cfg_value, inference_timesteps, normalize,
                 prompt_wav_path=_UNSET, prompt_text=_UNSET, seed=_UNSET):
        self.last_kwargs = {
            "text": text, "cfg_value": cfg_value,
            "inference_timesteps": inference_timesteps, "normalize": normalize,
        }
        if prompt_wav_path is not _UNSET:
            self.last_kwargs["prompt_wav_path"] = prompt_wav_path
        if prompt_text is not _UNSET:
            self.last_kwargs["prompt_text"] = prompt_text
        if seed is not _UNSET:
            self.last_kwargs["seed"] = seed
        return [0.1] * 4800  # 0,1 s à 48 kHz


def _make_job(model_id="openbmb/VoxCPM2", ref_path=None, prompt_text="",
              seed=None):
    return {
        "id": "test0001", "status": "running", "stage": "generation",
        "error": None, "created": 0.0, "started": 1.0, "finished": None,
        "chunk": 0, "chunks": 0,
        "request": {
            "text": "Bonjour le studio.", "control": "",
            "prompt_text": prompt_text, "cfg": 2.0, "timesteps": 10,
            "seed": seed, "normalize": False, "denoise": False,
            "model_id": model_id, "device": "auto", "denoiser": False,
            "optimize": False, "filename": "essai_natif", "mp3": False,
            **({"ref_path": ref_path} if ref_path else {}),
        },
        "result": None,
    }


def _fake_save_output(wav, sr, base, want_mp3):
    import wave
    path = os.path.join(os.environ["_VOXCPM_TEST_OUTPUTS"], base + ".wav")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(len(list(wav)) if hasattr(wav, "__iter__") else 4800))
    return path, "wav"


class NativePathTest(AppTestCase):
    def setUp(self):
        super().setUp()
        os.environ["_VOXCPM_TEST_OUTPUTS"] = os.path.join(self._tmp, "outputs")
        _install_fake_numpy()
        self.model = _FakeModel()
        # normalement posé par le vrai ensure_model (doublé ici)
        self._saved_device = STATE.device_used
        STATE.device_used = "cpu"
        self.addCleanup(setattr, STATE, "device_used", self._saved_device)
        patches = [
            mock.patch.object(engine, "ensure_model", return_value=self.model),
            mock.patch.object(engine, "model_sample_rate", return_value=48000),
            mock.patch.object(jobs.audio, "save_output", _fake_save_output),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_hifi_kwargs_and_result(self):
        job = _make_job(ref_path="/x/ref.wav", prompt_text="Bonjour le studio.", seed=42)
        jobs.split_text = lambda t: ["Premiere phrase.", "Deuxieme phrase."]
        try:
            jobs.run_generation(job)
        finally:
            del jobs.split_text
        self.assertEqual(job["chunks"], 2)
        # le seed est incrémenté par segment : dernier segment = 43
        self.assertEqual(self.model.last_kwargs.get("seed"), 43)
        res = job["result"]
        self.assertEqual(res["sample_rate"], 48000)
        self.assertEqual(res["chunks"], 2)
        self.assertEqual(res["output_format"], "wav")
        self.assertTrue(os.path.isfile(res["output_path"]))
        self.assertNotIn("gguf", res["device"])

    def test_design_mode_has_no_reference_kwargs(self):
        job = _make_job()
        jobs.split_text = lambda t: ["Une seule phrase."]
        try:
            jobs.run_generation(job)
        finally:
            del jobs.split_text
        kw = self.model.last_kwargs
        self.assertNotIn("prompt_wav_path", kw)
        self.assertNotIn("prompt_text", kw)

    def test_seed_none_not_sent(self):
        job = _make_job(seed=None)
        jobs.split_text = lambda t: ["Phrase."]
        try:
            jobs.run_generation(job)
        finally:
            del jobs.split_text
        self.assertNotIn("seed", self.model.last_kwargs)

    def test_unsupported_kwargs_are_filtered(self):
        # denoise / retry_badcase / reference_wav_path ne sont PAS dans la
        # signature du faux modèle : le vrai appel ne doit pas les transmettre.
        job = _make_job(seed=7)
        job["request"]["denoise"] = False
        jobs.split_text = lambda t: ["Phrase."]
        try:
            jobs.run_generation(job)  # lèverait TypeError si filtrage cassé
        finally:
            del jobs.split_text


class ResolveDeviceNativeTest(unittest.TestCase):
    def test_auto_is_never_gguf_for_native_models(self):
        """Régression : sans torch mais AVEC le moteur GGUF, un modèle natif
        recevait 'gguf (CPU)' comme device — invalide pour VoxCPM.from_pretrained."""
        with mock.patch.object(engine, "torch_info",
                               return_value={"torch": None, "cuda": False, "mps": False}), \
             mock.patch.object(engine.gguf, "available", return_value=True):
            self.assertEqual(engine.resolve_device("auto"), "cpu")

    def test_explicit_device_kept(self):
        self.assertEqual(engine.resolve_device("mps"), "mps")


if __name__ == "__main__":
    unittest.main()
