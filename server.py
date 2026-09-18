#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VoxCPM Studio - backend local (point d'entree).

Sert l'interface web (index.html) et pilote le moteur VoxCPM (pip package `voxcpm`).
Ecoute uniquement sur 127.0.0.1. Le code est reparti en modules :

    app/state.py     - chemins, constantes, objet d'etat global unique
    app/engine.py    - detection runtime + cycle de vie du modele
    app/text.py      - decoupage des textes longs
    app/audio.py     - encodage WAV/MP3 et sauvegarde dans outputs/
    app/jobs.py      - file de generation sequentielle (worker)
    app/http_api.py  - routes HTTP + demarrage du serveur
"""
from app.http_api import main

if __name__ == "__main__":
    main()
