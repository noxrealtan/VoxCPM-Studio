# VoxCPM Studio — Analyse du dépôt & Exigences de l'application

> Application desktop **Windows & macOS** offrant une interface simple pour le moteur
> TTS open-source [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM) (VoxCPM2).
> Ce document est le résultat de l'analyse du dépôt (README + documentation API officielle).

---

## 1. Ce qu'est VoxCPM (analyse du dépôt)

| Élément | Détail |
|---|---|
| Nature | TTS **sans tokenizer** : diffusion autorégressive opérant dans l'espace latent d'AudioVAE V2 (pipeline LocEnc → TSLM → RALM → LocDiT) |
| Modèle courant | **VoxCPM2** — 2B paramètres, ~8 Go VRAM, sorties **48 kHz** |
| Langues | **30 langues** (dont le français), sans balise de langue ; dialectes chinois en bonus |
| Licence | **Apache-2.0** — usage commercial autorisé |
| Distribution | `pip install voxcpm` · poids téléchargés depuis HuggingFace (`openbmb/VoxCPM2`) ou ModelScope |

### Modes de génération (extraits de la doc officielle)
1. **TTS simple** — `model.generate(text=..., cfg_value=2.0, inference_timesteps=10)`.
2. **Voice Design** — décrire la voix en langage naturel, entre parenthèses, en tête du texte :
   `"(Une jeune femme, voix douce et chaleureuse)Bonjour et bienvenue !"`. Aucun audio requis.
3. **Clonage contrôlé (VoxCPM2 uniquement)** — `reference_wav_path` (timbre) + instruction de style optionnelle
   `"(plus vite, ton joyeux)..."`. Pas de transcript nécessaire.
4. **Clonage Hi-Fi (Ultimate)** — `prompt_wav_path` + `prompt_text` (transcript exact) + `reference_wav_path`
   pour fidélité maximale.
5. **Streaming** — `generate_streaming()` donne des morceaux audio incrémentaux.

### Paramètres clés de `generate()`
| Paramètre | Défaut | Rôle |
|---|---|---|
| `cfg_value` | 2.0 | Adhérence au conditionnement (1.0–3.0 ; 1.5–1.6 si ronflement) |
| `inference_timesteps` | 10 | Pas de diffusion — qualité vs vitesse (4–30) |
| `normalize` | False | Développe nombres, dates… |
| `denoise` | False | Débruite l'audio de référence (pipeline 16 kHz, peut altérer le timbre) |
| `retry_badcase` | True | Réessaie si audio anormalement court/long |
| `max_len` | 4096 | Longueur max en tokens |
| (retour) | — | `numpy.ndarray` float32 ; fréquence via `model.tts_model.sample_rate` |

### Contraintes matérielles et plateforme relevées
- Python **≥ 3.10 et < 3.13** ; PyTorch ≥ 2.5.
- GPU CUDA ≥ 12 conseillé (RTF ≈ 0.3 sur RTX 4090) ; **CPU / MPS macOS fonctionnels** (`device=auto` → cuda → mps → cpu) mais plus lents.
- L'option `optimize` (torch.compile) ne sert que sur CUDA → à désactiver sur macOS/Intel.
- Audio de référence : WAV/FLAC/MP3, **5 à 30 s**, propre.
- Textes longs : à découper en phrases (instabilité sinon) — l'UI doit le faire automatiquement.

### ⚠️ Contrainte découverte : Mac Intel
PyTorch a **cessé de publier des wheels macOS x86_64 après la 2.2.2** (fin 2024) — vérifié sur
PyPI — alors que `voxcpm` exige PyTorch ≥ 2.5. Conséquence : le moteur Python de VoxCPM
**ne peut pas tourner sur un Mac Intel**. Décisions prises :
- Le lanceur macOS détecte l'architecture `x86_64` et affiche un message clair avec les
  alternatives (Mac Apple Silicon, PC Windows, roues PyTorch communautaires
  `Morton-Li/PyTorch-MacOS-Builder`, ou le moteur C++ `llama.cpp-omni` du milieu VoxCPM
  qui tourne sur CPU/Metal) au lieu d'une erreur d'installation obsure.
- Le moteur reste la voie principale pour Apple Silicon, Windows et Linux.

---

## 2. Exigences de l'application (VoxCPM Studio)

### R1 — Simplicité maximale
- **Un seul double-clic** : le lanceur installe tout ce qui manque (Python 3.12 embarqué via `uv`,
  dépendances pip), puis démarre l'app et ouvre l'interface. Aucune ligne de commande à connaître.
- Interface web locale en un seul fichier, sans build ni npm.

### R2 — Fonctionnalités (par ordre de priorité)
1. Zone de texte + bouton **Générer** (TTS simple, français supporté nativement).
2. **Presets de voix** (Design) : voix masculine/féminine, calme/joyeuse, narration, dialectes… —
   insèrent l'instruction entre parenthèses au bon format ; champ libre possible.
3. **Clonage** : glisser-déposer ou choix d'un fichier audio (WAV/MP3/FLAC/M4A), mode
   *Clonage simple* (référence) ou *Hi-Fi* (référence + transcript) selon VoxCPM2.
4. Enregistrement de la voix : fichier WAV/MP3 nommé par l'utilisateur, dossier de sortie configurable.
5. Réglages : modèle (VoxCPM2 / 1.5 / 0.5B), appareil (auto/cpu/mps/cuda), vitesse de voix,
   qualité (pas de diffusion), CFG, seed reproductible, normalisation du texte.
6. **File d'attente** : générer plusieurs textes d'affilée sans blocage de l'UI.
7. Lecteur audio intégré + historique des dernières générations.

### R3 — Robustesse
- Découpage automatique des textes longs en phrases, concaténation des morceaux (recommandation officielle).
- Vérification "santé" du backend (`/api/health`) : état de chargement du modèle, appareil, infos système.
- Chargement paresseux du modèle au premier clic sur « Générer » (le modèle pèse ~5 Go).
- Écriture WAV/MP3 via soundfile + fallback lameenc pour le MP3.
- CORS local, serveur lié à 127.0.0.1 uniquement.

### R4 — Multiplateforme
- **macOS** : `Lancer VoxCPM Studio.command` (bash) — installe `uv` dans `~/.local/bin` si absent,
  crée un venv Python 3.12 dédié (`~/.voxcpm-studio/venv`), installe `voxcpm` + dépendances, démarre.
  Conçu pour Intel **et** Apple Silicon ; device `auto` choisit MPS si disponible.
- **Windows** : `Lancer VoxCPM Studio.bat` (cmd, pas de PowerShell imposé) — télécharge `uv.exe`
  si absent, venv Python 3.12, mêmes étapes ; sur PC avec GPU NVIDIA, l'utilisateur peut activer CUDA
  via une variable d'environnement documentée.
- L'application s'ouvre en **fenêtre native** (WebView2 via pywebview, Alt+F4 avec
  confirmation si une génération est en cours) ; repli navigateur automatique. Un `.exe`
  autonome peut être produit avec `packaging/build_exe.bat` (PyInstaller, à exécuter sur le PC).

### R5 — Hors périmètre (v1)
- Fine-tuning SFT/LoRA (scripts d'entraînement du dépôt) — GUI ultérieure possible.
- Serving vLLM-Omni / Nano-vLLM (production multi-utilisateurs).
- Build d'installateurs signés (.dmg/.msi) — les lanceurs scripts suffisent et restent légers.

### R6 — Ajout v1.1 : moteur C++ de secours (Mac Intel)
- Contrainte : PyTorch ne publie plus de wheels macOS Intel depuis la 2.5, exigence de VoxCPM.
- Réponse : intégration de `voxcpm2-cli` (llama.cpp-omni, C++/ggml, sans PyTorch) avec les
  poids GGUF VoxCPM2 (Apache-2.0, DennisHuang648/VoxCPM2-GGUF) — compilé au premier lancement
  par le lanceur macOS, aucune dépendance Python. Modèles `gguf:*` proposés dans l'UI.
- Prouvé sur cette machine (iMac Intel, CPU) : compilation, synthèse 0.5B et VoxCPM2,
  clonage par référence, repli MP3→WAV.
- GPU : tentative Metal automatique (GPU AMD/Intel/Nvidia du Mac via Metal) avec repli CPU
  mémorisé — sur la Radeon Pro 575 de l'iMac testé, le backend Metal de ggml aborte sur des
  ops non supportées (RMS_NORM/MUL_MAT) ; le repli a été prouvé de bout en bout.

### R7 — Ajout v1.2 : application de bureau native (macOS et Windows)
- `desktop.py` : serveur local embarqué + fenêtre native (PyObjC + WKWebView), Dock,
  ⌘Q, confirmation à la fermeture si une génération est en cours ; repli navigateur
  automatique (ou `--browser`) si la couche graphique est indisponible.
- `packaging/make_app.sh` : bundle « VoxCPM Studio.app » (icône générée, Info.plist)
  installable dans /Applications ; le bundle lance desktop.py via le venv existant
  et délègue au lanceur d'installation au premier usage.
- **Ajout v1.3 (Windows)** : fenêtre native via pywebview/WebView2 (même flux `desktop.py`,
  fermeture annulable si un job tourne), `pywebview` dans requirements (balise `sys_platform`),
  `.bat` relancé sur `desktop.py`, recherche de `voxcpm2-cli.exe` dans `gguf/bin/`, et
  `packaging/build_exe.bat` → `dist/VoxCPMStudio.exe` (PyInstaller --onefile, interface et
  icône embarquées, `web/` résolu via `sys._MEIPASS`, sorties à côté du `.exe`).
  *Non exécutable depuis macOS : à valider sur un PC Windows.*
- **CI Windows (v1.3)** : `.github/workflows/windows.yml` — un job `windows-latest` qui
  construit le .exe (`packaging/build_exe.bat`), le fume-teste (`packaging/smoke_test.ps1`,
  mode headless `VOXCPM_BROWSER=1`) et publie `dist/VoxCPMStudio.exe` en artifact.
  En CI (sans poids ni voxcpm2-cli) le test n'affirme que ce qui y est vrai : démarrage,
  health, UI servie, rejet 400 du natif avec message clair, `gguf.available=false`.
  Défauts racine corrigés à cette occasion : `pause` bloquant en CI (désormais hors CI
  uniquement), exclusions torch/voxcpm/numpy et collecte `clr_loader`/`pythonnet` du bundle.

---

## 3. Architecture retenue

```
Lanceur (.command / .bat)
   └─ uv + venv Python 3.12  (créé au premier lancement, réutilisé ensuite)
        └─ server.py  (point d'entrée → package app/, stdlib http.server)
             ├─ app/http_api.py : sert index.html (UI mono-fichier)
             │     POST /api/generate      → voxcpm.VoxCPM.generate (thread dédié)
             │     POST /api/generate_async→ job en file, /api/job/<id> pour l'état
             │     GET  /api/health        → version, device, modèle chargé
             ├─ app/jobs.py    : file de génération séquentielle (worker)
             ├─ app/engine.py  : détection runtime + cycle de vie du modèle
             ├─ app/text.py    : découpage des textes longs
             ├─ app/audio.py   : encodage WAV/MP3, sauvegarde dans outputs/
             └─ app/state.py   : chemins, constantes, état global unique
```

Pourquoi ce choix : zéro dépendance de build (pas d'Electron, pas de npm), l'UI reste un simple
fichier HTML consultable dans n'importe quel navigateur, et le backend isole le moteur lourd
dans un worker threadé pour que l'interface reste réactive.
