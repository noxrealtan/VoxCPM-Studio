#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cycle de vie du modèle : détection runtime, device, chargement/déchargement."""
import gc
import os
import shutil
import time
import traceback

from . import audio, gguf
from .state import MAX_TEXT_CHARS, STATE, log


def is_gguf_model(model_id):
    return bool(model_id) and str(model_id).startswith("gguf:")


def find_gguf_model(model_id):
    short = model_id.split(":", 1)[1]
    for m in gguf.installed_models():
        if m["id"] == model_id or m["id"].endswith(":" + short):
            return m
    return None


def torch_info(force=False):
    with STATE.lock:
        if STATE.torch_info is not None and not force:
            return STATE.torch_info
    info = {"torch": None, "cuda": False, "cuda_name": None, "mps": False}
    try:
        import torch  # type: ignore
        info["torch"] = torch.__version__
        info["cuda"] = bool(getattr(torch.backends, "cuda", None) and torch.cuda.is_available())
        if info["cuda"]:
            try:
                info["cuda_name"] = torch.cuda.get_device_name(0)
            except Exception:
                pass
        try:
            info["mps"] = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
        except Exception:
            info["mps"] = False
    except Exception as e:
        info["error"] = str(e)
    with STATE.lock:
        STATE.torch_info = info
    return info


def resolve_device(requested):
    """device=auto -> cuda, mps, cpu (meme ordre que la doc VoxCPM).
    Sur Mac Intel, torch_info() est vide : le device auto devient le moteur GGUF."""
    if requested and requested not in ("auto", ""):
        return requested
    ti = torch_info()
    if ti.get("cuda"):
        return "cuda"
    if ti.get("mps"):
        return "mps"
    if ti.get("torch") is None and gguf.available():
        return "gguf (CPU)"
    return "cpu"


def unload_model():
    with STATE.lock:
        if STATE.model is not None:
            log("Dechargement du modele...")
            STATE.model = None
            gc.collect()
            try:
                import torch  # type: ignore
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass
        STATE.model_id = None
        STATE.denoiser_loaded = False
        STATE.load_error = None


def ensure_model(model_id, device_req, denoiser, optimize, progress_cb=None):
    """Charge le modele si necessaire (ou le recharge si la config change)."""
    with STATE.lock:
        same = (
            STATE.model is not None
            and STATE.model_id == model_id
            and STATE.denoiser_loaded == bool(denoiser)
            and STATE.optimize_used == bool(optimize)
        )
        if same:
            return STATE.model
        if STATE.loading:
            # attendre la fin du chargement en cours
            while STATE.loading:
                time.sleep(0.2)
            if STATE.model is not None and STATE.model_id == model_id:
                return STATE.model
    with STATE.lock:
        STATE.loading = True
        STATE.load_error = None
    try:
        unload_model()
        device = resolve_device(device_req)
        if progress_cb:
            progress_cb("chargement_modele")
        log("Chargement du modele %s (device=%s, denoiser=%s, optimize=%s)..."
            % (model_id, device, denoiser, optimize))
        from voxcpm import VoxCPM  # type: ignore
        model = VoxCPM.from_pretrained(
            hf_model_id=model_id,
            load_denoiser=bool(denoiser),
            optimize=bool(optimize),
            device=device,
        )
        with STATE.lock:
            STATE.model = model
            STATE.model_id = model_id
            STATE.device_used = device
            STATE.denoiser_loaded = bool(denoiser)
            STATE.optimize_used = bool(optimize)
        log("Modele pret (device=%s, sample_rate=%s)."
            % (device, getattr(getattr(model, "tts_model", None), "sample_rate", "?")))
        return model
    except Exception as e:
        err = "Echec du chargement du modele: %s" % e
        log(err)
        traceback.print_exc()
        with STATE.lock:
            STATE.load_error = err
        raise
    finally:
        with STATE.lock:
            STATE.loading = False


def model_sample_rate(model):
    return int(getattr(getattr(model, "tts_model", None), "sample_rate", 48000))


def run_gguf_generation(job):
    """Synthèse via le moteur C++ (llama.cpp-omni) : aucune dépendance Python."""
    req = job["request"]
    text = req["text"].strip()
    if not text:
        raise ValueError("Le texte est vide.")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("Texte trop long (max %d caracteres)." % MAX_TEXT_CHARS)
    if req["denoise"]:
        raise ValueError("La suppression de bruit n'est pas disponible avec le moteur GGUF.")

    model_def = find_gguf_model(req["model_id"])
    if not model_def:
        raise ValueError("Modele GGUF non installe (verifiez gguf/models/).")

    ref_path = req.get("ref_path")
    prompt_text = req["prompt_text"].strip()
    control = req["control"].strip()
    is_legacy = "0.5B" in req["model_id"]
    if ref_path and not prompt_text and is_legacy:
        raise ValueError(
            "Ce modele ne supporte pas le clonage par simple reference. "
            "Activez le mode Hi-Fi avec le transcript de l'audio."
        )

    from .text import split_text
    chunks = split_text("(%s)%s" % (control, text) if control and not prompt_text else text)
    job["chunks"] = len(chunks)
    job["stage"] = "generation"

    # GPU (Metal, y compris AMD) tenté en premier ; repli CPU automatique.
    # L'utilisateur peut forcer le CPU avec device=cpu.
    use_gpu = req.get("device") != "cpu"
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = req["filename"].strip() or ("voxcpm_%s" % ts)
    final_path = None
    try:
        for i, chunk in enumerate(chunks):
            job["chunk"] = i + 1
            out_path = audio.unique_output_path(base, "wav", final_path is not None)
            sr, duration, backend = gguf.generate(
                model_def, chunk, control if not prompt_text else "",
                ref_path, prompt_text,
                req["cfg"], req["timesteps"],
                None if req["seed"] is None else req["seed"] + i,
                out_path, use_gpu=use_gpu,
            )
            if final_path is None:
                final_path = out_path
            else:
                if final_path.endswith(".wav"):
                    _concat_wav(final_path, out_path)
                    os.remove(out_path)
                else:
                    final_path = None
                    break
        if final_path is None:
            raise RuntimeError("La concatenation multi-segments n'est pas supportee pour ce format.")

        final_fmt = "wav"
        if req["mp3"]:
            mp3_path = audio.unique_output_path(base, "mp3", True)
            if audio.encode_mp3_file(final_path, mp3_path):
                os.remove(final_path)
                final_path, final_fmt = mp3_path, "mp3"

        job["result"] = {
            "job_id": job["id"],
            "sample_rate": sr,
            "duration": duration,
            "chunks": len(chunks),
            "device": backend,
            "model_id": req["model_id"],
            "output_path": final_path,
            "output_format": final_fmt,
            "audio_url": "/api/audio/%s" % job["id"],
            "download_url": "/api/audio/%s?download=1" % job["id"],
        }
        log("Job %s termine (GGUF) : %s s d'audio -> %s" % (job["id"], duration, final_path))
    finally:
        with STATE.lock:
            STATE.gguf_job = None


def _concat_wav(target, extra):
    """Concatene un WAV PCM 16 bits mono a la suite d'un autre (entete reecrite)."""
    import wave

    with wave.open(target, "rb") as w:
        params = w.getparams()
        data_a = w.readframes(w.getnframes())
    with wave.open(extra, "rb") as w:
        data_b = w.readframes(w.getnframes())
    with wave.open(target, "wb") as w:
        w.setnchannels(params.nchannels)
        w.setsampwidth(params.sampwidth)
        w.setframerate(params.framerate)
        w.writeframes(data_a + data_b)
