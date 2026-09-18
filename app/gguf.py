#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moteur de secours GGUF (llama.cpp-omni / voxcpm2-cli) — aucune dépendance Python.

Utilisé tel quel si `gguf/bin/voxcpm2-cli` + `gguf/models/*.gguf` sont présents,
sinon installé par le lanceur (compilation CMake sur Mac Intel).
"""
import os
import re
import subprocess
import sys

from .state import ROOT, STATE, log

GGUF_DIR = os.path.join(ROOT, "gguf")
BIN_NAME = "voxcpm2-cli.exe" if sys.platform == "win32" else "voxcpm2-cli"
REPO = "https://github.com/tc-mb/llama.cpp-omni"

GGUF_MODELS = [
    {"id": "gguf:VoxCPM2-BaseLM-Q8_0", "label": "VoxCPM2 GGUF Q8_0 (2B, 30 langues, 48 kHz)",
     "info": "Moteur C++ (llama.cpp-omni) — fonctionne sans PyTorch. Recommande.",
     "baselm": "VoxCPM2-BaseLM-Q8_0.gguf", "acoustic": "VoxCPM2-Acoustic-F16.gguf"},
    {"id": "gguf:VoxCPM2-BaseLM-F16", "label": "VoxCPM2 GGUF F16 (2B, precision totale)",
     "info": "Moteur C++ — plus lent et deux fois plus gros que Q8_0.",
     "baselm": "VoxCPM2-BaseLM-F16.gguf", "acoustic": "VoxCPM2-Acoustic-F16.gguf"},
    {"id": "gguf:VoxCPM-0.5B-BaseLM-Q8_0", "label": "VoxCPM-0.5B GGUF Q8_0 (leger, zh/en, 16 kHz)",
     "info": "Moteur C++ — le plus rapide ; qualite et langues limitees.",
     "baselm": "VoxCPM-0.5B-BaseLM-Q8_0.gguf", "acoustic": "VoxCPM-0.5B-Acoustic-F16.gguf"},
]


def cli_path():
    """Chemin du binaire, ou None s'il n'est pas installé."""
    p = os.path.join(GGUF_DIR, "bin", BIN_NAME)
    return p if os.path.isfile(p) and os.access(p, os.X_OK) else None


def installed_models():
    """Modèles GGUF complets (BaseLM + Acoustic présents), dans l'ordre de GGUF_MODELS."""
    mdir = os.path.join(GGUF_DIR, "models")
    out = []
    for m in GGUF_MODELS:
        if all(os.path.isfile(os.path.join(mdir, m[k])) for k in ("baselm", "acoustic")):
            out.append(m)
    return out


def available():
    return cli_path() is not None and bool(installed_models())


def status():
    """Infos pour /api/health : disponible, modèles installés, erreur d'installation."""
    err = None
    marker = os.path.join(GGUF_DIR, "install_error.txt")
    if os.path.isfile(marker):
        try:
            with open(marker, "r", encoding="utf-8", errors="replace") as f:
                err = f.read().strip()
        except OSError:
            err = "erreur d'installation illisible"
    return {
        "engine": "gguf",
        "available": available(),
        "cli": bool(cli_path()),
        "models": installed_models(),
        "gpu": gpu_status(),
        "error": err,
    }


def version_from_source():
    """Hash court du dépôt source (pour les logs), ou None."""
    head = os.path.join(GGUF_DIR, "src", ".git", "HEAD")
    try:
        with open(head) as f:
            ref = f.read().strip()
        path = os.path.join(GGUF_DIR, "src", ".git", ref.split(" ")[1])
        with open(path) as f:
            return f.read().strip()[:8]
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Synthèse
# ---------------------------------------------------------------------------
_LAST_LOG = []

# Résultat du dernier essai GPU pour cette session : None (inconnu), True (ok), False (échec).
# Un échec GPU (ops Metal non supportées sur certains GPU) est mémorisé pour ne pas
# retenter inutilement à chaque génération — le repli CPU est automatique.
_GPU_STATE = {"supported": None}


def gpu_status():
    return {"attempted": _GPU_STATE["supported"] is not None,
            "supported": _GPU_STATE["supported"]}


def generate(model_def, text, control, ref_path, prompt_text, cfg, timesteps, seed,
             out_path, use_gpu=True, progress_cb=None):
    """Synthétise via le CLI voxcpm2-cli et renvoie (sample_rate, duree_s, backend).

    use_gpu=True tente Metal (GPU, y compris AMD via Metal) puis retombe sur CPU
    automatiquement si le GPU échoue ; l'échec est mémorisé pour la session.
    """
    cli = cli_path()
    if not cli:
        raise RuntimeError("Le moteur GGUF n'est pas installe (gguf/bin/%s absent)." % BIN_NAME)

    # Voice design : description entre parentheses au debut du texte (reco officielle)
    full_text = "(%s)%s" % (control, text) if control else text

    mdir = os.path.join(GGUF_DIR, "models")
    base_cmd = [
        cli,
        "-t", full_text,
        "-o", out_path,
        "--cfg", "%.2f" % cfg,
        "--timesteps", str(int(timesteps)),
        os.path.join(mdir, model_def["baselm"]),
        os.path.join(mdir, model_def["acoustic"]),
    ]
    if ref_path and prompt_text:
        base_cmd += ["--prompt-wav", ref_path, "--prompt-text", prompt_text]
    elif ref_path:
        base_cmd += ["-r", ref_path]
    if seed is not None:
        base_cmd += ["--seed", str(int(seed))]

    if progress_cb:
        progress_cb("generation")

    try_gpu = use_gpu and _GPU_STATE["supported"] is not False
    if try_gpu:
        log("GGUF : tentative GPU (Metal)...")
        code, ok = _run_cli(base_cmd, out_path, gpu=True)
        if ok:
            _GPU_STATE["supported"] = True
            STATE.gguf_backend = "GPU (Metal)"
        else:
            _GPU_STATE["supported"] = False
            log("GGUF : le GPU a echoue (ops Metal non supportees ?) -> repli CPU automatique.")
    else:
        STATE.gguf_backend = "CPU"

    if not try_gpu or _GPU_STATE["supported"] is False:
        code, ok = _run_cli(base_cmd, out_path, gpu=False)
        if not ok:
            tail = "\n".join(_LAST_LOG[-8:])
            raise RuntimeError("Echec du moteur GGUF (code %s) :\n%s" % (code, tail))
        STATE.gguf_backend = "CPU"

    m = re.search(r"Audio:\s*([\d.]+)s", "\n".join(_LAST_LOG))
    duration = round(float(m.group(1)), 2) if m else None
    # 0.5B = 16 kHz, VoxCPM2 = 48 kHz (fiches HF) ; on relit l'entete reelle du WAV
    sr = _wav_sample_rate(out_path) or (16000 if "0.5B" in model_def["id"] else 48000)
    return sr, duration, STATE.gguf_backend


def _run_cli(cmd, out_path, gpu=False):
    """Exécute le CLI ; renvoie (code_retour, succes). gpu=False ajoute --cpu."""
    run_cmd = list(cmd)
    if not gpu:
        run_cmd.append("--cpu")
    log("GGUF : %s" % " ".join(run_cmd))
    _LAST_LOG.clear()
    proc = subprocess.Popen(run_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, errors="replace")
    for line in proc.stdout:
        line = line.rstrip()
        if line:
            _LAST_LOG.append(line)
            if len(_LAST_LOG) > 200:
                _LAST_LOG.pop(0)
    code = proc.wait()
    return code, (code == 0 and os.path.isfile(out_path))


def _wav_sample_rate(path):
    """Lit le taux d'échantillonnage dans l'entete WAV (octets 24-27, little-endian)."""
    try:
        with open(path, "rb") as f:
            header = f.read(44)
        if len(header) >= 28 and header[0:4] == b"RIFF" and header[8:12] == b"WAVE":
            return int.from_bytes(header[24:28], "little")
    except OSError:
        pass
    return None
