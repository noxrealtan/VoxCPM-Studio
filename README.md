# 🎙️ VoxCPM Studio

Application desktop **Windows & macOS** à interface simple pour le moteur TTS open-source
[VoxCPM](https://github.com/OpenBMB/VoxCPM) (VoxCPM2) : synthèse vocale multilingue (dont le
français), création de voix par description, et clonage vocal à partir d'un court extrait audio.

## 🚀 Démarrage (un seul double-clic)

1. Placez ce dossier où vous voulez (aucun droit administrateur requis).
2. Double-cliquez :
   - **macOS** : `Lancer VoxCPM Studio.command`
   - **Windows** : `Lancer VoxCPM Studio.bat`
3. Au premier lancement, tout s'installe automatiquement (Python 3.12 via `uv`, dépendances,
   moteur VoxCPM) — comptez **5 à 15 minutes** selon la connexion. Les fois suivantes : instantané.
4. L'application s'ouvre dans **sa propre fenêtre** (icône dans le Dock, ⌘Q pour quitter).
   Si la fenêtre native n'est pas disponible, l'interface s'ouvre dans le navigateur.
   Tapez un texte, cliquez **▶ Générer la voix**.

> 💡 **Mac** : après avoir exécuté le lanceur une fois, ouvrez `packaging/make_app.sh`
> (ou lancez-le) pour créer **VoxCPM Studio.app** — installable dans /Applications comme
> une vraie application (icône, Launchpad, Dock).

> 🪟 **Windows** : la même application existe en **`.exe` autonome**. Sur un PC avec Python
> (3.10+), lancez `packaging/build_exe.bat` : il produit `dist\VoxCPMStudio.exe` — fenêtre
> native WebView2, icône, interface embarquée, **aucun Python requis sur la machine cible**.
> Le bundle n'embarque pas le moteur Python (torch exclu) : sans PyTorch, l'app utilise le
> moteur GGUF (`gguf\`) et refuse proprement les modèles natifs.
> **Sans PC sous la main** : pousser le dépôt déclenche `.github/workflows/windows.yml`,
> qui construit le `.exe`, le teste (démarrage, health, UI, rejet natif 400, gguf absent)
> et le publie en **artifact téléchargeable** (onglet Actions du dépôt).

> 🖥️ macOS : si le fichier `.command` est bloqué (Gatekeeper), faites un clic droit → **Ouvrir**.
> Le modèle (~5 Go) est téléchargé depuis HuggingFace lors de la **première génération**.

## ⚠️ Mac Intel : à lire avant de lancer

PyTorch ne publie plus de paquets pour Mac **Intel** depuis la version 2.5, et VoxCPM exige
PyTorch ≥ 2.5 : le moteur Python ne peut donc **pas** s'installer sur un iMac/MacBook Intel.
Ce n'est pas bloquant : le lanceur installe alors automatiquement le **moteur C++ GGUF**
(`llama.cpp-omni`, sans PyTorch) et l'application l'utilise à la place. Sur Intel, le premier
lancement comprend une compilation (~5–20 min) et ~3,3 Go de poids à télécharger ;
génération testée à environ **2× la durée audio** en RTF (ex. : 30 s de voix ≈ 1 min).

**GPU** : le moteur tente d'abord **Metal** (le GPU du Mac, AMD inclus, y accède via Metal),
puis retombe automatiquement sur CPU si le GPU échoue — l'échec est mémorisé et le statut
dans l'interface l'indique clairement. Mesuré sur un iMac Intel 2017 (Radeon Pro 575) :
le Metal de ce GPU trop ancien ne supporte pas les opérations nécessaires ; l'application
fonctionne donc sur CPU. Sur Apple Silicon, le même chemin GPU doit fonctionner nativement.

- ✅ **Fonctionne** : Mac Apple Silicon (M1–M4) · Mac **Intel** via le moteur C++ GGUF
  · PC Windows (GPU NVIDIA fortement conseillé, CPU possible mais lent) · Linux.
- Les modèles du menu **« Moteur C++ GGUF »** apparaissent dès que les poids sont installés ;
  la génération via ce moteur n'utilise pas PyTorch du tout.

## ✨ Fonctionnalités

- **Texte → voix** en français et 29 autres langues, sorties 48 kHz.
- **Presets de voix** (douce, posée, narrateur, joyeuse, info, enfant…) ou description libre :
  le *Voice Design* crée une voix à partir d'une simple phrase descriptive.
- **Clonage vocal** : glissez-déposez un extrait (WAV/MP3/FLAC/M4A, 5–30 s).
  - *Clonage simple* : le timbre est repris, sans transcript.
  - *Mode Hi-Fi* : ajoutez le transcript exact pour une fidélité maximale.
- Réglages : modèle (VoxCPM2 / 1.5 / 0.5B), appareil (auto/CPU/MPS/CUDA), CFG, qualité, seed.
- Fichier de sortie WAV ou MP3 nommé librement, dossier `outputs/`.
- Découpage automatique des textes longs (recommandation officielle du projet), file de
  génération non bloquante, lecteur intégré et historique.

## ⚙️ Conseils de qualité

| Symptôme | Solution |
|---|---|
| Son ronflant / buzzy | Baisser **CFG** vers 1.5–1.6 |
| Rendu trop plat | Augmenter la **Qualité** (étapes) vers 15–20 |
| Nombres mal lus | Cocher **Normaliser le texte** |
| Voix aléatoire à chaque fois | Normal : sans audio de référence, la timbre change. Utilisez le clonage |
| Très court texte mou | Écrire au moins une phrase complète |

## 🧯 Dépannage

- **« Backend injoignable »** : la fenêtre du lanceur doit rester ouverte pendant l'utilisation.
- **Génération très lente** : vous êtes probablement sur CPU. Sur un PC avec GPU NVIDIA,
  tout est automatique ; sur Mac, `auto` utilise le GPU (MPS) quand il est disponible.
- **Erreur au chargement du modèle** : vérifiez l'espace disque (~8 Go) et la connexion ;
  le bouton « Décharger le modèle » permet de repartir proprement.
- Les audios de référence déposés sont copiés dans `refs/`, les générations dans `outputs/`.

## 🗂️ Contenu du dossier

| Fichier | Rôle |
|---|---|
| `Lancer VoxCPM Studio.command` / `.bat` | Lanceurs auto-installants (macOS / Windows) |
| `server.py` | Point d'entrée du backend en mode navigateur (code détaillé dans `app/`) |
| `desktop.py` | Point d'entrée de l'application de bureau (fenêtre native macOS/Windows + serveur embarqué) |
| `app/` | Modules du backend : `state` (état partagé), `engine` (moteurs VoxCPM), `text` (découpage), `audio` (WAV/MP3), `jobs` (file de génération), `gguf` (moteur C++ llama.cpp-omni), `http_api` (routes HTTP) |
| `web/index.html` | Interface (un seul fichier, sans build) |
| `requirements.txt` | Dépendances Python (`voxcpm==2.0.3`, soundfile, numpy, lameenc) |
| `gguf/` | Moteur C++ de secours, sans PyTorch (créé au premier lancement sur Mac Intel) : `gguf/src/` (sources), `gguf/bin/` (binaire + dylibs), `gguf/models/` (poids GGUF ~3,3 Go, installés par le lanceur) |
| `packaging/` | Bundle macOS `VoxCPM Studio.app` (`make_app.sh`) et **`.exe` Windows** (`build_exe.bat`, `png_to_ico.ps1`) + icône |
| `EXIGENCES.md` | Analyse du dépôt VoxCPM et exigences de l'application |

Licence : le moteur VoxCPM et ses poids sont sous **Apache-2.0** (usage commercial autorisé).
À utiliser de façon responsable : ne pas cloner une voix pour usurper l'identité de quelqu'un,
et signaler les contenus générés par IA.
