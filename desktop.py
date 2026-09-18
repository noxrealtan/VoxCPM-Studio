#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VoxCPM Studio - application de bureau (point d'entree).

Lance le serveur local embarque puis ouvre une fenetre native (macOS).
En cas d'indisponibilite de la couche graphique, bascule sur le navigateur.
Le code est reparti en modules :

    app/state.py     - chemins, constantes, objet d'etat global unique
    app/engine.py    - moteurs VoxCPM (Python PyTorch et C++ GGUF)
    app/text.py      - decoupage des textes longs
    app/audio.py     - encodage WAV/MP3 et sauvegarde dans outputs/
    app/jobs.py      - file de generation sequentielle (worker)
    app/gguf.py      - adaptateur du moteur C++ (voxcpm2-cli, llama.cpp-omni)
    app/http_api.py  - routes HTTP
    app/desktop.py   - fenetre native macOS (PyObjC) et Windows (pywebview/WebView2)
"""
import os
import sys


def main():
    from app import desktop, http_api
    from app.state import log

    args = sys.argv[1:]
    port = 8808
    for i, a in enumerate(args):
        if a in ("--port", "-p") and i + 1 < len(args):
            try:
                port = int(args[i + 1])
            except ValueError:
                pass

    port = http_api.find_port(port)
    http_api.start_server(port)

    browser_mode = ("--browser" in args
                    or os.environ.get("VOXCPM_BROWSER") == "1")
    if browser_mode:
        desktop.run_browser(port)
        http_api.wait_forever()
    elif desktop.desktop_available():
        desktop.run_desktop(port)
    else:
        log("Couche graphique indisponible : ouverture dans le navigateur.")
        desktop.run_browser(port)
        http_api.wait_forever()


if __name__ == "__main__":
    main()
