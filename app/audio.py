#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Encodage et sauvegarde des fichiers audio générés."""
import io
import os
import re

from .state import OUTPUTS_DIR


def wav_bytes(numpy_wav, sample_rate):
    import numpy as np  # type: ignore
    import soundfile as sf  # type: ignore
    buf = io.BytesIO()
    sf.write(buf, numpy_wav, sample_rate, subtype="PCM_16", format="WAV")
    return buf.getvalue()


def mp3_bytes(numpy_wav, sample_rate):
    """Encode en MP3 via lameenc si disponible, sinon None."""
    try:
        import numpy as np  # type: ignore
        import lameenc  # type: ignore
    except Exception:
        return None
    try:
        pcm = (np.clip(numpy_wav, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        enc = lameenc.Encoder()
        enc.set_bit_rate(192)
        enc.set_in_sample_rate(sample_rate)
        enc.set_channels(1 if numpy_wav.ndim == 1 else 2)
        enc.set_quality(2)
        data = enc.encode(pcm) + enc.flush()
        return bytes(data) if data else None
    except Exception:
        return None


def unique_output_path(basename, ext, avoid_existing=False):
    """Construit un chemin outputs/<base>.<ext> sans collision (_2, _3…)."""
    base = re.sub(r"[^A-Za-z0-9._ \u00c0-\u017f-]", "_", basename).strip() or "generation"
    base = base[:80]
    path = os.path.join(OUTPUTS_DIR, "%s.%s" % (base, ext))
    n = 2
    while os.path.exists(path):
        path = os.path.join(OUTPUTS_DIR, "%s_%d.%s" % (base, n, ext))
        n += 1
    return path


def encode_mp3_file(wav_path, mp3_path):
    """Réencode un fichier WAV en MP3 via lameenc ; renvoie True en cas de succès."""
    import wave

    try:
        import lameenc  # type: ignore
    except Exception:
        return False
    try:
        with wave.open(wav_path, "rb") as w:
            sr = w.getframerate()
            channels = w.getnchannels()
            pcm = w.readframes(w.getnframes())
        enc = lameenc.Encoder()
        enc.set_bit_rate(192)
        enc.set_in_sample_rate(sr)
        enc.set_channels(channels)
        enc.set_quality(2)
        data = enc.encode(pcm) + enc.flush()
        if not data:
            return False
        with open(mp3_path, "wb") as f:
            f.write(bytes(data))
        return True
    except Exception:
        return False


def save_output(numpy_wav, sample_rate, basename, want_mp3):
    """Sauvegarde dans outputs/ ; renvoie (chemin, format_reel)."""
    base = re.sub(r"[^A-Za-z0-9._ \u00c0-\u017f-]", "_", basename).strip() or "generation"
    base = base[:80]
    if want_mp3:
        data = mp3_bytes(numpy_wav, sample_rate)
        if data:
            path = os.path.join(OUTPUTS_DIR, base + ".mp3")
            n = 2
            while os.path.exists(path):
                path = os.path.join(OUTPUTS_DIR, "%s_%d.mp3" % (base, n))
                n += 1
            with open(path, "wb") as f:
                f.write(data)
            return path, "mp3"
    path = os.path.join(OUTPUTS_DIR, base + ".wav")
    n = 2
    while os.path.exists(path):
        path = os.path.join(OUTPUTS_DIR, "%s_%d.wav" % (base, n))
        n += 1
    import soundfile as sf  # type: ignore
    sf.write(path, numpy_wav, sample_rate, subtype="PCM_16")
    return path, "wav"
