#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Moteur de secours GGUF (llama.cpp-omni / voxcpm2-cli) — aucune dépendance Python.

Utilisé tel quel si `gguf/bin/voxcpm2-cli` + `gguf/models/*.gguf` sont présents,
sinon installé par le lanceur (compilation CMake sur Mac Intel).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

from .state import ROOT, STATE, log

GGUF_DIR = os.path.join(ROOT, "gguf")
BIN_NAME = "voxcpm2-cli.exe" if sys.platform == "win32" else "voxcpm2-cli"
REPO = "https://github.com/tc-mb/llama.cpp-omni"

# Backend GPU du binaire : déduit de la plateforme (le CLI ne l'expose pas).
# macOS -> Metal (seul backend compilé pour ce binaire) ; ailleurs (Windows)
# Vulkan est le backend par défaut du projet amont (GGML_VULKAN=ON), avec
# repli CPU automatique si le GPU échoue ou n'a pas assez de VRAM.
GPU_BACKEND_NAME = "Metal" if sys.platform == "darwin" else "Vulkan"

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
    return {"backend": GPU_BACKEND_NAME,
            "attempted": _GPU_STATE["supported"] is not None,
            "supported": _GPU_STATE["supported"]}


def _wav_format(path):
    """Tag de format du WAV (octets du chunk fmt), ou None si pas RIFF/WAVE.

    1 = PCM classique (le seul que lit llama.cpp-omni) ; 0xFFFE = extensible
    (écrit par afconvert et certains logiciels d'enregistrement).
    """
    try:
        with open(path, "rb") as f:
            data = f.read(64 * 1024)
        if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
            return None
        i = 12
        while i + 8 <= len(data):
            size = int.from_bytes(data[i + 4:i + 8], "little")
            if data[i:i + 4] == b"fmt ":
                return int.from_bytes(data[i + 8:i + 10], "little")
            i += 8 + size + (size & 1)
    except OSError:
        pass
    return None


def _canonical_wav(src, dst):
    """Réécrit un WAV PCM 16 bits au format classique (tag 1, en-tête 44 octets).

    Accepte en entrée un en-tête « extensible » (0xFFFE, sous-format PCM) comme
    celui qu'écrit afconvert. Renvoie True si la réécriture a réussi.
    """
    try:
        with open(src, "rb") as f:
            data = f.read()
        if data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
            return False
        i, fmt, payload = 12, None, None
        while i + 8 <= len(data):
            size = int.from_bytes(data[i + 4:i + 8], "little")
            body = data[i + 8:i + 8 + size]
            if data[i:i + 4] == b"fmt " and fmt is None:
                fmt = body
            elif data[i:i + 4] == b"data" and payload is None:
                payload = body
            i += 8 + size + (size & 1)
        if fmt is None or payload is None or len(fmt) < 16:
            return False
        audio_format = int.from_bytes(fmt[0:2], "little")
        channels = int.from_bytes(fmt[2:4], "little")
        rate = int.from_bytes(fmt[4:8], "little")
        bits = int.from_bytes(fmt[14:16], "little")
        is_pcm16 = bits == 16 and channels > 0 and (
            audio_format == 1
            or (audio_format == 0xFFFE and len(fmt) >= 40 and fmt[24:26] == b"\x01\x00"))
        if not is_pcm16 or not payload:
            return False
        block = channels * 2
        head = (b"RIFF" + (36 + len(payload)).to_bytes(4, "little") + b"WAVE"
                + b"fmt " + (16).to_bytes(4, "little")
                + (1).to_bytes(2, "little") + channels.to_bytes(2, "little")
                + rate.to_bytes(4, "little") + (rate * block).to_bytes(4, "little")
                + block.to_bytes(2, "little") + (16).to_bytes(2, "little")
                + b"data" + len(payload).to_bytes(4, "little"))
        tmp = dst + ".canon"
        with open(tmp, "wb") as f:
            f.write(head)
            f.write(payload)
        os.replace(tmp, dst)
        return True
    except (OSError, IndexError):
        return False


def _ensure_wav(ref_path):
    """Renvoie (chemin WAV à utiliser, fichier temporaire à supprimer ou None).

    Le CLI llama.cpp-omni ne lit que le WAV PCM classique (tag 1) : une
    référence MP3/M4A/FLAC/OGG est décodée à la volée (ffmpeg si présent,
    sinon afconvert sur macOS) et tout WAV « extensible » (0xFFFE) est
    réécrit en en-tête classique. Lève une erreur claire en cas d'échec.
    """
    fmt = _wav_format(ref_path)
    if fmt == 1:
        return ref_path, None
    ext = (os.path.splitext(ref_path)[1].lstrip(".") or "audio").upper()
    fd, tmp = tempfile.mkstemp(prefix="voxcpm_ref_", suffix=".wav")
    os.close(fd)
    try:
        decoded = False
        if fmt == 0xFFFE:
            # En-tête extensible PCM 16 bits : réécriture possible sans décodeur
            decoded = _canonical_wav(ref_path, tmp)
        if not decoded:
            ffmpeg = shutil.which("ffmpeg")
            if ffmpeg:
                cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", ref_path,
                       "-c:a", "pcm_s16le", tmp]
            elif os.access("/usr/bin/afconvert", os.X_OK):
                cmd = ["/usr/bin/afconvert", "-f", "WAVE", "-d", "LEI16",
                       ref_path, tmp]
            else:
                raise RuntimeError(
                    "Le moteur GGUF ne lit que des fichiers WAV : la référence %s "
                    "doit être convertie, mais ni ffmpeg ni afconvert ne sont "
                    "disponibles. Fournissez un WAV ou installez ffmpeg." % ext
                )
            proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            if proc.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
                raise RuntimeError("Conversion de la référence %s en WAV impossible : %s"
                                   % (ext, " | ".join(tail) or "erreur inconnue"))
        if _wav_format(tmp) != 1 and not _canonical_wav(tmp, tmp):
            raise RuntimeError(
                "La référence %s est dans un format WAV non supporté par le moteur "
                "GGUF : convertissez-la en WAV PCM 16 bits." % ext
            )
        return tmp, tmp
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def generate(model_def, text, control, ref_path, prompt_text, cfg, timesteps, seed,
             out_path, use_gpu=True, progress_cb=None):
    """Synthétise via le CLI voxcpm2-cli et renvoie (sample_rate, duree_s, backend).

    Les références non-WAV (MP3/M4A/FLAC) sont transcodées à la volée : le CLI
    ne lit que le WAV. use_gpu=True tente Metal (GPU, y compris AMD via Metal)
    puis retombe sur CPU automatiquement si le GPU échoue ; l'échec est
    mémorisé pour la session.
    """
    tmp_ref = None
    try:
        if ref_path:
            ref_path, tmp_ref = _ensure_wav(ref_path)
        return _generate(model_def, text, control, ref_path, prompt_text, cfg,
                         timesteps, seed, out_path, use_gpu, progress_cb)
    finally:
        if tmp_ref:
            try:
                os.remove(tmp_ref)
            except OSError:
                pass


def _generate(model_def, text, control, ref_path, prompt_text, cfg, timesteps, seed,
              out_path, use_gpu=True, progress_cb=None):
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
        log("GGUF : tentative GPU (%s)..." % GPU_BACKEND_NAME)
        code, ok = _run_cli(base_cmd, out_path, gpu=True)
        if ok:
            _GPU_STATE["supported"] = True
            STATE.gguf_backend = "GPU (%s)" % GPU_BACKEND_NAME
        else:
            _GPU_STATE["supported"] = False
            log("GGUF : le GPU a echoue (pilote/VRAM insuffisante ?) -> repli CPU automatique.")
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
