#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Couche HTTP : routes JSON/statiques, aucun accès direct au moteur."""
import json
import os
import platform
import secrets
import socket
import sys
import threading
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl

from . import engine, gguf, jobs
from .state import (APP_VERSION, MAX_BODY, MAX_TEXT_CHARS, MODELS, OUTPUTS_DIR,
                    STATIC_DIR, STATE, log)

# S2 : jeton de session régénéré à chaque démarrage. Il n'est connu que de
# l'app (URL d'ouverture) ; l'API l'exige ensuite via un cookie HttpOnly
# SameSite=Strict, invisible au JS et jamais rejoué par un site tiers.
SESSION_TOKEN = secrets.token_urlsafe(32)
COOKIE_NAME = "voxcpm_token"


class Handler(BaseHTTPRequestHandler):
    server_version = "VoxCPMStudio/" + APP_VERSION
    _token_from_query = False

    def log_message(self, fmt, *args):  # logs compacts
        pass

    # -- garde CSRF / DNS rebinding / jeton de session ---------------------
    def _session_token(self, query):
        """Jeton de session fourni par : query (1re navigation) > en-tete > cookie."""
        q = dict(parse_qsl(query))
        self._token_from_query = "token" in q
        token = q.get("token") or self.headers.get("X-VoxCPM-Token")
        if not token:
            jar = SimpleCookie(self.headers.get("Cookie") or "")
            token = jar[COOKIE_NAME].value if COOKIE_NAME in jar else ""
        return token or ""

    def _safe_request(self, query=""):
        """Rejette toute requete dont Host n'est pas le serveur local, dont
        l'Origin (presente pour les POST navigateur) ne pointe pas dessus, ou
        qui ne presente pas le jeton de session de ce demarrage.
        Ferme : CSRF, DNS rebinding, et l'acces des autres processus locaux."""
        host = (self.headers.get("Host") or "").strip()
        if host != "127.0.0.1:%d" % self.server.server_address[1]:
            self._json({"error": "Requete refusee : hote non autorise."}, 403)
            return False
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin.rstrip("/") != "http://" + host:
            self._json({"error": "Requete refusee : origine non autorisee."}, 403)
            return False
        if not secrets.compare_digest(self._session_token(query), SESSION_TOKEN):
            self._json({"error": "Acces refuse : session non autorisee. "
                                 "Relancez l'application."}, 401)
            return False
        return True

    # -- utilitaires -------------------------------------------------------
    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("Corps de requete trop volumineux.")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8") or "{}")

    def _file(self, path, ctype):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "Fichier introuvable."}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        path = self.path.split("?")[0]
        query = self.path.split("?")[1] if "?" in self.path else ""
        if not self._safe_request(query):
            return
        if path in ("/", "/index.html"):
            if self._token_from_query:
                # 1re navigation avec le jeton : on pose le cookie puis on
                # redirige vers une URL propre (le jeton ne reste pas dans
                # l'historique du navigateur)
                self.send_response(302)
                self.send_header("Set-Cookie", "%s=%s; Path=/; HttpOnly; SameSite=Strict"
                                 % (COOKIE_NAME, SESSION_TOKEN))
                self.send_header("Location", path)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self._file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif path == "/api/health":
            self._health()
        elif path.startswith("/api/job/"):
            jid = path.rsplit("/", 1)[-1]
            with STATE.lock:
                job = STATE.jobs.get(jid)
            if not job:
                self._json({"error": "Job inconnu."}, 404)
            else:
                self._json(jobs.job_status(job))
        elif path.startswith("/api/audio/"):
            self._audio(path.rsplit("/", 1)[-1], "download=1" in query)
        else:
            self._json({"error": "Route inconnue."}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if not self._safe_request(self.path.split("?")[1] if "?" in self.path else ""):
            return
        try:
            payload = self._read_body()
        except Exception as e:
            self._json({"error": "Requete invalide: %s" % e}, 400)
            return
        if path in ("/api/generate", "/api/generate_async"):
            self._generate(payload)
        elif path == "/api/device":
            dev = (payload.get("device") or "auto").strip()
            self._json({"ok": True, "resolved": engine.resolve_device(dev),
                        "runtime": engine.torch_info()})
        else:
            self._json({"error": "Route inconnue."}, 404)

    # -- implémentation des routes ----------------------------------------
    def _health(self):
        with STATE.lock:
            model_state = {
                "model_id": STATE.model_id,
                "device": STATE.device_used,
                "loaded": STATE.model is not None,
                "loading": STATE.loading,
                "denoiser": STATE.denoiser_loaded,
                "error": STATE.load_error,
            }
            active = sum(1 for j in STATE.jobs.values() if j["status"] in ("queued", "running"))
        gguf_status = gguf.status()
        self._json({
            "ok": True,
            "version": APP_VERSION,
            "python": platform.python_version(),
            "platform": "%s %s" % (platform.system(), platform.machine()),
            "runtime": engine.torch_info(),
            "device_hint": engine.resolve_device("auto"),
            "model": model_state,
            "gguf": gguf_status,
            "jobs_active": active,
            "outputs_dir": OUTPUTS_DIR,
            "models": MODELS + gguf_status["models"],
        })

    def _generate(self, payload):
        # action speciale : recharger le modele
        if payload.get("action") == "reload":
            threading.Thread(target=engine.unload_model, daemon=True).start()
            self._json({"ok": True, "message": "Modele demande a ete decharge."})
            return
        text = (payload.get("text") or "").strip()
        if not text and not (payload.get("control") or "").strip():
            self._json({"error": "Le texte a synthetiser est vide."}, 400)
            return
        if len(text) > MAX_TEXT_CHARS:
            self._json({"error": "Texte trop long (%d caracteres maximum)." % MAX_TEXT_CHARS}, 400)
            return
        if engine.is_gguf_model(payload.get("model_id")):
            # moteur C++ : rien a pre-charger, mais le modele doit etre installe
            if not engine.find_gguf_model(payload.get("model_id")):
                self._json({"error": "Modele GGUF non installe (verifiez gguf/models/)."}, 400)
                return
            job = jobs.new_job(payload)
            self._json({"ok": True, "job_id": job["id"], "status": job["status"],
                        "error": job["error"]}, 200 if job["status"] != "failed" else 400)
            return
        try:
            from voxcpm import VoxCPM  # preflight du moteur natif
        except Exception:
            self._json({"error": "Moteur Python (voxcpm) indisponible sur cette machine — "
                                 "choisissez un modele GGUF dans le menu Moteur."}, 400)
            return
        job = jobs.new_job(payload)
        self._json({"ok": True, "job_id": job["id"], "status": job["status"],
                    "error": job["error"]}, 200 if job["status"] != "failed" else 400)

    def _audio(self, jid, download):
        with STATE.lock:
            job = STATE.jobs.get(jid)
        if not job or job["status"] != "done" or not job.get("result"):
            self._json({"error": "Audio indisponible."}, 404)
            return
        res = job["result"]
        out_path = res["output_path"]
        fmt = res.get("output_format", "wav")
        ctype = "audio/mpeg" if fmt == "mp3" else "audio/wav"
        try:
            with open(out_path, "rb") as f:
                body = f.read()
        except OSError:
            self._json({"error": "Fichier introuvable."}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if download:
            name = os.path.basename(out_path)
            self.send_header("Content-Disposition", 'attachment; filename="%s"' % name)
        self.end_headers()
        self.wfile.write(body)


# ---------------------------------------------------------------------------
# Demarrage
# ---------------------------------------------------------------------------
def start_server(port):
    """Démarre le serveur dans un thread (mode fenêtre native)."""
    jobs.start_worker()
    gguf.start_gpu_probe()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()


def server_url(port):
    """URL d'ouverture : porte le jeton de session (1re navigation seulement,
    le cookie prend le relais ensuite)."""
    return "http://127.0.0.1:%d/?token=%s" % (port, SESSION_TOKEN)


def wait_forever():
    """Bloque indéfiniment (mode navigateur sans fenêtre native)."""
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        log("Arret.")


def find_port(preferred):
    for p in range(preferred, preferred + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    raise RuntimeError("Aucun port libre autour de %d" % preferred)


def main():
    args = sys.argv[1:]
    port = 8808
    open_browser = True
    for i, a in enumerate(args):
        if a in ("--port", "-p") and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass
        elif a == "--no-browser":
            open_browser = False
    port = find_port(port)

    jobs.start_worker()
    gguf.start_gpu_probe()

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    url = server_url(port)
    log("VoxCPM Studio v%s - %s" % (APP_VERSION, url))
    log("Repertoire de sortie : %s" % OUTPUTS_DIR)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log("Arret.")
