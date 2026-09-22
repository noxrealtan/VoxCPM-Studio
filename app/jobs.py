#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Worker sériel : extraction des paramètres de requête, jobs, génération."""
import base64
import hashlib
import inspect
import os
import queue
import threading
import time
import traceback
import uuid
from datetime import datetime

from . import audio, engine
from .state import HISTORY_LIMIT, MAX_TEXT_CHARS, REFS_DIR, STATE, log
from .text import split_text


# ---------------------------------------------------------------------------
# Requête -> paramètres
# ---------------------------------------------------------------------------
def params_from_payload(payload):
    """Extrait et normalise les paramètres d'une requête de génération."""
    seed = payload.get("seed")
    if seed is not None and str(seed).strip() != "":
        try:
            seed = int(seed)
        except (TypeError, ValueError):
            seed = None
    else:
        seed = None
    return {
        "text": payload.get("text", ""),
        "control": payload.get("control", ""),
        "prompt_text": payload.get("prompt_text", ""),
        "cfg": float(payload.get("cfg", 2.0)),
        "timesteps": int(payload.get("timesteps", 10)),
        "seed": seed,
        "normalize": bool(payload.get("normalize", False)),
        "denoise": bool(payload.get("denoise", False)),
        "model_id": payload.get("model_id") or "openbmb/VoxCPM2",
        "device": payload.get("device") or "auto",
        "denoiser": bool(payload.get("denoiser", False)),
        "optimize": bool(payload.get("optimize", False)),
        "filename": payload.get("filename") or "",
        "mp3": bool(payload.get("mp3", False)),
    }


def _save_reference(payload, params):
    """Décode la référence audio base64 dans refs/ ; lève en cas d'illisibilité."""
    ref_b64 = "".join((payload.get("reference_b64") or "").split())
    if not ref_b64:
        return
    raw = base64.b64decode(ref_b64, validate=True)  # leve si corrompu (binascii.Error)
    ext = os.path.splitext(payload.get("reference_filename") or "ref.wav")[1].lstrip(".").lower()
    if ext not in ("wav", "mp3", "flac", "ogg", "m4a", "aiff", "aif"):
        ext = "wav"
    h = hashlib.sha1(raw).hexdigest()[:16]
    ref_path = os.path.join(REFS_DIR, "%s.%s" % (h, ext))
    if not os.path.exists(ref_path):
        with open(ref_path, "wb") as f:
            f.write(raw)
    params["ref_hash"] = h
    params["ref_ext"] = ext
    params["ref_path"] = ref_path


def filter_kwargs(func, kwargs):
    """Ne passe a generate() que les parametres reels supportes par la version installee."""
    try:
        sig = inspect.signature(func)
        supported = set(sig.parameters.keys())
    except (TypeError, ValueError):
        return dict(kwargs)
    return {k: v for k, v in kwargs.items() if k in supported}


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------
def new_job(payload):
    job_id = uuid.uuid4().hex[:12]
    try:
        params = params_from_payload(payload)
        _save_reference(payload, params)
    except Exception as e:
        params = params_from_payload({"text": payload.get("text", "")})
        params["ref_error"] = "Reference audio illisible: %s" % e

    job = {
        "id": job_id,
        "status": "queued" if "ref_error" not in params else "failed",
        "stage": "file_attente" if "ref_error" not in params else "",
        "error": params.get("ref_error"),
        "created": time.time(),
        "started": None,
        "finished": None,
        "chunk": 0,
        "chunks": 0,
        "request": params,
        "result": None,
    }
    with STATE.lock:
        STATE.jobs[job_id] = job
        STATE.job_order.append(job_id)
        while len(STATE.job_order) > HISTORY_LIMIT:
            old = STATE.job_order.pop(0)
            STATE.jobs.pop(old, None)
    if job["status"] != "failed":
        STATE.job_queue.put(job_id)
    return job


def run_generation(job):
    req = job["request"]
    text = req["text"].strip()
    if not text:
        raise ValueError("Le texte est vide.")
    if len(text) > MAX_TEXT_CHARS:
        raise ValueError("Texte trop long (max %d caracteres)." % MAX_TEXT_CHARS)

    ref_path = req.get("ref_path")
    prompt_text = req["prompt_text"].strip()
    control = req["control"].strip()
    is_legacy = req["model_id"] in ("openbmb/VoxCPM1.5", "openbmb/VoxCPM-0.5B")

    # Construction du texte final (Voice Design / style : instruction entre parentheses)
    gen_text = text
    if control and not prompt_text:
        gen_text = "(%s)%s" % (control, text)

    # Mode de clonage
    if ref_path and prompt_text:
        mode = "hifi"
    elif ref_path:
        mode = "reference"
    else:
        mode = "design"
    if mode in ("reference", "hifi") and is_legacy and mode == "reference":
        raise ValueError(
            "Ce modele (VoxCPM 1.x) ne supporte pas le clonage par simple reference. "
            "Fournissez le transcript de l'audio (mode Hi-Fi) ou choisissez VoxCPM2."
        )

    model = engine.ensure_model(
        req["model_id"], req["device"], req["denoiser"] or req["denoise"],
        req["optimize"],
        progress_cb=lambda stage: job.update({"stage": stage}),
    )
    job["stage"] = "generation"

    chunks = split_text(gen_text)
    job["chunks"] = len(chunks)
    log("Job %s : %d segment(s) a generer." % (job["id"], len(chunks)))

    import numpy as np  # type: ignore
    pieces = []
    gen_kwargs_base = {
        "cfg_value": req["cfg"],
        "inference_timesteps": req["timesteps"],
        "normalize": req["normalize"],
        "denoise": req["denoise"] and STATE.denoiser_loaded,
        "retry_badcase": True,
    }
    if mode in ("hifi", "reference"):
        gen_kwargs_base["reference_wav_path"] = ref_path
    if mode == "hifi":
        gen_kwargs_base["prompt_wav_path"] = ref_path
        gen_kwargs_base["prompt_text"] = prompt_text

    for i, chunk in enumerate(chunks):
        job["chunk"] = i + 1
        kwargs = dict(gen_kwargs_base)
        if req["seed"] is not None:
            kwargs["seed"] = req["seed"] + i
        kwargs = filter_kwargs(model.generate, kwargs)
        log("Job %s : segment %d/%d (%d car.)" % (job["id"], i + 1, len(chunks), len(chunk)))
        wav = model.generate(text=chunk, **kwargs)
        arr = wav
        if hasattr(arr, "detach"):
            arr = arr.detach()
        if hasattr(arr, "cpu"):
            arr = arr.cpu()
        arr = np.asarray(arr, dtype=np.float32).reshape(-1)
        if arr.size == 0:
            raise RuntimeError("Le modele n'a produit aucun audio (reessayez ou ajustez CFG/qualite).")
        pieces.append(arr)

    full = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
    sr = engine.model_sample_rate(model)
    duration = round(float(len(full)) / sr, 2)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = req["filename"].strip() or ("voxcpm_%s" % ts)
    out_path, out_fmt = audio.save_output(full, sr, base, req["mp3"])

    job["result"] = {
        "job_id": job["id"],
        "sample_rate": sr,
        "duration": duration,
        "chunks": len(chunks),
        "device": STATE.device_used,
        "model_id": req["model_id"],
        "output_path": out_path,
        "output_format": out_fmt,
        "audio_url": "/api/audio/%s" % job["id"],
        "download_url": "/api/audio/%s?download=1" % job["id"],
    }
    log("Job %s termine : %.1f s d'audio -> %s" % (job["id"], duration, out_path))


def worker_loop():
    while True:
        job_id = STATE.job_queue.get()
        with STATE.lock:
            job = STATE.jobs.get(job_id)
            if not job:
                continue
            wants_gguf = engine.is_gguf_model(job["request"]["model_id"])
            if wants_gguf and STATE.gguf_job is not None:
                # le moteur C++ n'admet qu'une instance : reenfiler jusqu'a liberte
                STATE.job_queue.put(job_id)
                continue
        job["status"] = "running"
        job["started"] = time.time()
        try:
            if wants_gguf:
                with STATE.lock:
                    STATE.gguf_job = job
                engine.run_gguf_generation(job)
            else:
                run_generation(job)
            job["status"] = "done"
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            log("Job %s echec : %s" % (job["id"], e))
            traceback.print_exc()
        finally:
            job["finished"] = time.time()
            # eviter la croissance memoire : liberer la reference audio temporaire
            job["request"].pop("ref_path", None)
            with STATE.lock:
                if STATE.gguf_job is job:
                    STATE.gguf_job = None


def start_worker():
    """Crée la file et démarre le worker (appelé une fois au démarrage du serveur)."""
    if STATE.job_queue is None:
        STATE.job_queue = queue.Queue()
        threading.Thread(target=worker_loop, daemon=True).start()


def job_status(job):
    d = {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "chunk": job["chunk"],
        "chunks": job["chunks"],
        "error": job["error"],
        "elapsed": round((job["finished"] or time.time()) - (job["started"] or job["created"]), 1),
    }
    if job["status"] == "done":
        d["result"] = job["result"]
    return d
