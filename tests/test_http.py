"""Tests HTTP de bout en bout : serveur reel embarque, toutes les routes.

Les flux de generation GGUF ne tournent que si le moteur est installe
(skips automatiques en CI) : ils valident alors des fichiers audio reels.
"""
import base64
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from app import engine, gguf
from app import http_api
from app.state import MAX_TEXT_CHARS

GGUF_AVAILABLE = gguf.available()


class ServerTestCase(unittest.TestCase):
    """Un serveur HTTP reel sur un port libre, par classe de tests."""

    @classmethod
    def setUpClass(cls):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        http_api.jobs.start_worker()
        cls.httpd = http_api.ThreadingHTTPServer(("127.0.0.1", port), http_api.Handler)
        cls.httpd.daemon_threads = True
        cls.base = "http://127.0.0.1:%d" % port
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def req(self, method, path, obj=None, headers=None, auth=True):
        """Par defaut la requete porte le cookie de session, comme la webview."""
        data = json.dumps(obj).encode() if obj is not None else None
        h = {"Content-Type": "application/json"}
        if auth:
            h["Cookie"] = "%s=%s" % (http_api.COOKIE_NAME, http_api.SESSION_TOKEN)
        h.update(headers or {})
        r = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        try:
            resp = urllib.request.urlopen(r, timeout=60)
            body = resp.read()
            try:
                return resp.status, resp.headers, json.loads(body)
            except Exception:
                return resp.status, resp.headers, body
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                return e.code, e.headers, json.loads(body)
            except Exception:
                return e.code, e.headers, body


class RoutesTest(ServerTestCase):
    def test_index_serves_ui(self):
        s, h, body = self.req("GET", "/")
        self.assertEqual(s, 200)
        self.assertIn("text/html", h.get("Content-Type", ""))
        self.assertIn(b"VoxCPM", body)

    def test_favicon_is_204(self):
        s, _, _ = self.req("GET", "/favicon.ico")
        self.assertEqual(s, 204)

    def test_unknown_route_is_404_json(self):
        s, _, b = self.req("GET", "/api/inconnu")
        self.assertEqual(s, 404)
        self.assertIn("Route inconnue", b.get("error", ""))

    def test_unknown_job_and_audio_404(self):
        s, _, _ = self.req("GET", "/api/job/inconnu")
        self.assertEqual(s, 404)
        s, _, _ = self.req("GET", "/api/audio/inconnu")
        self.assertEqual(s, 404)

    def test_health_ok_with_gguf_section(self):
        s, _, b = self.req("GET", "/api/health")
        self.assertEqual(s, 200)
        self.assertTrue(b["ok"])
        self.assertIn("available", b["gguf"])

    def test_unsupported_method_rejected(self):
        s, _, _ = self.req("DELETE", "/api/health")
        self.assertGreaterEqual(s, 400)

    def test_empty_text_400(self):
        s, _, b = self.req("POST", "/api/generate_async", {"text": "  "})
        self.assertEqual(s, 400)
        self.assertIn("vide", b.get("error", ""))

    def test_too_long_text_400(self):
        s, _, b = self.req("POST", "/api/generate_async",
                           {"text": "x" * (MAX_TEXT_CHARS + 10)})
        self.assertEqual(s, 400)
        self.assertIn("trop long", b.get("error", ""))

    def test_native_engine_rejected_without_voxcpm_with_clear_message(self):
        s, _, b = self.req("POST", "/api/generate_async",
                           {"text": "test", "model_id": "openbmb/VoxCPM2"})
        try:
            import voxcpm  # noqa: F401
            have = True
        except Exception:
            have = False
        if have:
            self.assertEqual(s, 200)
        else:
            self.assertEqual(s, 400)
            self.assertIn("Moteur Python (voxcpm) indisponible", b.get("error", ""))

    def test_unknown_gguf_model_400(self):
        s, _, b = self.req("POST", "/api/generate_async",
                           {"text": "test", "model_id": "gguf:inexistant"})
        self.assertEqual(s, 400)
        self.assertIn("non installe", b.get("error", ""))

    def test_device_route(self):
        s, _, b = self.req("POST", "/api/device", {"device": "cpu"})
        self.assertEqual(s, 200)
        self.assertEqual(b["resolved"], "cpu")

    def test_reload_action_accepted(self):
        s, _, b = self.req("POST", "/api/generate", {"action": "reload"})
        self.assertEqual(s, 200)
        self.assertTrue(b.get("ok"))


@unittest.skipUnless(GGUF_AVAILABLE, "moteur GGUF non installe sur cette machine")
class GenerationFlowsTest(ServerTestCase):
    @staticmethod
    def wait_job(base, jid, timeout=300):
        t0 = time.time()
        cookie = {"Cookie": "%s=%s" % (http_api.COOKIE_NAME, http_api.SESSION_TOKEN)}
        while time.time() - t0 < timeout:
            try:
                r = urllib.request.Request(base + "/api/job/" + jid, headers=cookie)
                j = json.loads(urllib.request.urlopen(r, timeout=30).read())
            except Exception:
                time.sleep(3)
                continue
            if j.get("status") in ("done", "failed"):
                return j
            time.sleep(2)
        return {"status": "timeout"}

    def launch(self, payload):
        s, _, j = self.req("POST", "/api/generate_async", payload)
        self.assertEqual(s, 200, j)
        jid = j["job_id"]
        self.assertIn(j["status"], ("queued", "running"))
        return self.wait_job(self.base, jid)

    def test_text_only_generation_produces_valid_wav(self):
        j = self.launch({"text": "Verification de la suite de tests.",
                         "model_id": "gguf:VoxCPM2-BaseLM-Q8_0", "timesteps": 4,
                         "filename": "suite_txt"})
        self.assertEqual(j["status"], "done", j.get("error"))
        r = j["result"]
        self.assertEqual(r["output_format"], "wav")
        self.assertGreater(r["duration"] or 0, 0)
        s, h, audio_bytes = self.req("GET", r["audio_url"])
        self.assertEqual(s, 200)
        self.assertIn("audio/wav", h.get("Content-Type", ""))
        self.assertGreater(len(audio_bytes), 10000)
        s, h, _ = self.req("GET", r["download_url"])
        self.assertIn("attachment", h.get("Content-Disposition", ""))

    def test_mp3_export_produces_mp3(self):
        j = self.launch({"text": "Export MP3 de la suite.",
                         "model_id": "gguf:VoxCPM2-BaseLM-Q8_0", "timesteps": 4,
                         "mp3": True, "filename": "suite_mp3"})
        self.assertEqual(j["status"], "done", j.get("error"))
        self.assertEqual(j["result"]["output_format"], "mp3")

    def test_voice_design_flow(self):
        j = self.launch({"text": "Voix de test de la suite.",
                         "model_id": "gguf:VoxCPM2-BaseLM-Q8_0", "timesteps": 4,
                         "control": "une voix posée", "filename": "suite_design"})
        self.assertEqual(j["status"], "done", j.get("error"))

    def test_reference_cloning_flow(self):
        wav = self._canonical_reference_wav()
        j = self.launch({"text": "Clonage de la suite.",
                         "model_id": "gguf:VoxCPM2-BaseLM-Q8_0", "timesteps": 4,
                         "reference_b64": base64.b64encode(wav).decode(),
                         "reference_filename": "ref.wav", "filename": "suite_ref"})
        self.assertEqual(j["status"], "done", j.get("error"))

    def test_hifi_cloning_flow(self):
        wav = self._canonical_reference_wav()
        j = self.launch({"text": "Clonage hifi de la suite.",
                         "model_id": "gguf:VoxCPM2-BaseLM-Q8_0", "timesteps": 4,
                         "reference_b64": base64.b64encode(wav).decode(),
                         "reference_filename": "ref.wav",
                         "prompt_text": "Transcript de la reference.",
                         "filename": "suite_hifi"})
        self.assertEqual(j["status"], "done", j.get("error"))

    def test_multi_segment_reports_total_duration(self):
        text = ("Voici la premiere phrase de ce long texte de verification. "
                "Ensuite vient une deuxieme phrase assez longue pour changer de "
                "segment. Puis une troisieme phrase qui continue l'effort de "
                "decoupage automatique. Et enfin une quatrieme phrase pour boucler.")
        self.assertGreater(len(text), 220)
        j = self.launch({"text": text, "model_id": "gguf:VoxCPM2-BaseLM-Q8_0",
                         "timesteps": 4, "filename": "suite_multi"})
        self.assertEqual(j["status"], "done", j.get("error"))
        r = j["result"]
        self.assertGreaterEqual(r["chunks"], 2)
        import os
        size = os.path.getsize(r["output_path"])
        self.assertGreater(r["duration"] or 0, 6)
        self.assertGreater(size, 200000)

    def _canonical_reference_wav(self):
        """Reference PCM classique synthetisee (1 s de silence)."""
        import io
        import struct
        import wave
        rate = 24000
        payload = b"\x00\x00" * rate
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(payload)
        return buf.getvalue()


class LegacyModelGuardTest(unittest.TestCase):
    def test_legacy_reference_cloning_rejected(self):
        import asyncio
        from app import jobs as jobs_mod
        from app.state import STATE
        if not GGUF_AVAILABLE:
            self.skipTest("moteur GGUF non installe")
        legacy = [m["id"] for m in gguf.installed_models() if "0.5B" in m["id"]]
        if not legacy:
            self.skipTest("modele legacy 0.5B non installe")
        job = {"id": "test", "request": {"text": "x", "model_id": legacy[0],
                                         "ref_path": "/tmp/ref.wav", "prompt_text": "",
                                         "control": "", "denoise": False,
                                         "cfg": 2.0, "timesteps": 10, "seed": None,
                                         "filename": "", "mp3": False}}
        STATE.gguf_job = None
        with self.assertRaises(ValueError):
            engine.run_gguf_generation(job)


if __name__ == "__main__":
    unittest.main()


class OriginHostGuardTest(ServerTestCase):
    """S1+S3 : Host exige = serveur local ; Origin presente doit correspondre."""

    def test_bad_host_rejected(self):
        code, _, body = self.req("GET", "/api/health", headers={"Host": "evil.example.com"})
        self.assertEqual(code, 403)
        self.assertIn("hote", body["error"])

    def test_wrong_port_host_rejected(self):
        code, _, body = self.req("GET", "/api/health",
                                  headers={"Host": "127.0.0.1:9999"})
        self.assertEqual(code, 403)

    def test_cross_origin_post_rejected(self):
        code, _, body = self.req("POST", "/api/generate_async",
                                 {"text": "x"}, headers={"Origin": "https://evil.example.com"})
        self.assertEqual(code, 403)
        self.assertIn("origine", body["error"])

    def test_matching_origin_accepted(self):
        code, _, body = self.req("POST", "/api/device", {"device": "auto"},
                                 headers={"Origin": self.base})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_normal_request_without_origin_ok(self):
        code, _, body = self.req("GET", "/api/health")
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])


class SessionTokenTest(ServerTestCase):
    """S2 : l'API exige le jeton de session pose au demarrage — ferme l'acces
    des autres processus locaux et des sessions navigateur hors app."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a):
            return None

    def test_api_without_token_401(self):
        code, _, body = self.req("GET", "/api/health", auth=False)
        self.assertEqual(code, 401)
        self.assertIn("session", body["error"].lower())

    def test_post_without_token_401(self):
        code, _, _ = self.req("POST", "/api/device", {"device": "auto"}, auth=False)
        self.assertEqual(code, 401)

    def test_wrong_cookie_401(self):
        code, _, _ = self.req("GET", "/api/health", auth=False,
                              headers={"Cookie": http_api.COOKIE_NAME + "=mauvais"})
        self.assertEqual(code, 401)

    def test_header_token_accepted(self):
        code, _, body = self.req("GET", "/api/health", auth=False,
                                 headers={"X-VoxCPM-Token": http_api.SESSION_TOKEN})
        self.assertEqual(code, 200)
        self.assertTrue(body["ok"])

    def test_root_without_token_401(self):
        code, _, _ = self.req("GET", "/", auth=False)
        self.assertEqual(code, 401)

    def test_query_token_sets_cookie_then_redirects(self):
        opener = urllib.request.build_opener(self._NoRedirect)
        r = urllib.request.Request(self.base + "/?token=" + http_api.SESSION_TOKEN)
        try:
            resp = opener.open(r, timeout=10)
            code, headers = resp.status, resp.headers
        except urllib.error.HTTPError as e:
            code, headers = e.code, e.headers
        self.assertEqual(code, 302)
        sc = headers.get("Set-Cookie") or ""
        self.assertIn(http_api.COOKIE_NAME, sc)
        self.assertIn("HttpOnly", sc)
        self.assertIn("SameSite=Strict", sc)
        self.assertEqual(headers.get("Location"), "/")

    def test_wrong_query_token_401(self):
        code, _, _ = self.req("GET", "/?token=mauvais", auth=False)
        self.assertEqual(code, 401)
