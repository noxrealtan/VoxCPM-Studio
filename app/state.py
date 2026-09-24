#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Noyau partagé : chemins, constantes, état global (unique propriétaire), log."""
import os
import sys
import threading
from datetime import datetime

# App gelée (PyInstaller) : les ressources (web/) vivent dans le dossier
# temporaire d'exécution, les sorties à côté du .exe.
if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(sys.executable)
else:
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = (getattr(sys, "_MEIPASS", None) and
              os.path.join(sys._MEIPASS, "web")) or os.path.join(ROOT, "web")
OUTPUTS_DIR = os.path.join(ROOT, "outputs")
REFS_DIR = os.path.join(ROOT, "refs")
os.makedirs(OUTPUTS_DIR, exist_ok=True)
os.makedirs(REFS_DIR, exist_ok=True)

MAX_BODY = 200 * 1024 * 1024  # 200 MB (references audio en base64)
MAX_CHUNK_CHARS = 220         # decoupage des textes longs (reco officielle)
HISTORY_LIMIT = 200           # memoire vive des jobs (les fichiers, eux, restent sur disque)
MAX_TEXT_CHARS = 20000

APP_VERSION = "1.0.0"

MODELS = [
    {"id": "openbmb/VoxCPM2", "label": "VoxCPM2 (2B, 30 langues, 48 kHz)", "default": True,
     "info": "Recommande. Voice Design + clonage simple ou Hi-Fi."},
    {"id": "openbmb/VoxCPM1.5", "label": "VoxCPM1.5 (0.8B, zh/en, 44.1 kHz)", "default": False,
     "info": "Clonage par continuation uniquement (transcript requis)."},
    {"id": "openbmb/VoxCPM-0.5B", "label": "VoxCPM-0.5B (0.5B, zh/en, 16 kHz)", "default": False,
     "info": "Leger. Clonage par continuation uniquement (transcript requis)."},
]


class State:
    """Un seul objet pour tout l'état partagé entre HTTP et le worker."""

    def __init__(self):
        self.lock = threading.RLock()
        self.model = None              # instance voxcpm.VoxCPM
        self.model_id = None
        self.device_used = None
        self.denoiser_loaded = False
        self.optimize_used = False
        self.loading = False
        self.load_error = None
        self.jobs = {}                 # id -> job dict
        self.job_order = []            # ids, pour eviction
        self.job_queue = None          # queue.Queue, créée par jobs.start_worker()
        self.torch_info = None         # cache
        self.gguf_job = None           # job GGUF en cours (le CLI n'admet qu'une instance)
        self.gguf_free = threading.Event()  # signale la liberation du moteur C++
        self.gguf_free.set()
        self.gguf_backend = None       # "GPU (Metal)" ou "CPU" : backend du dernier run GGUF


STATE = State()


def log(msg):
    print("[%s] %s" % (datetime.now().strftime("%H:%M:%S"), msg), flush=True)
