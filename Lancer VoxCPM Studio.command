#!/bin/bash
# ============================================================================
#  VoxCPM Studio - Lanceur macOS (Intel et Apple Silicon)
#  Double-cliquez sur ce fichier : tout s'installe automatiquement au premier
#  lancement (Python 3.12 via uv, dependances, moteur VoxCPM).
# ============================================================================
set -u
cd "$(dirname "$0")"

APP_TITLE="VoxCPM Studio"
UV_DIR="$HOME/.voxcpm-studio/uv"
VENV_DIR="$HOME/.voxcpm-studio/venv"
UV_BIN="$UV_DIR/uv"

say()   { printf '\033[1;34m[%s]\033[0m %s\n' "$APP_TITLE" "$1"; }
fail()  { printf '\033[1;31m[Erreur]\033[0m %s\n' "$1"; echo; echo "Fermez cette fenetre et reessayez."; read -r -p "(Entree pour fermer)"; exit 1; }

# --- 1/4 : uv (gestionnaire Python autonome, aucun droit admin requis) ------
if [ ! -x "$UV_BIN" ]; then
  if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
    say "uv deja installe : $UV_BIN"
  else
    say "1/4 - Installation de l'environnement Python (uv)..."
    mkdir -p "$UV_DIR"
    case "$(uname -m)" in
      arm64)  TARGET="aarch64-apple-darwin" ;;
      *)      TARGET="x86_64-apple-darwin"  ;;
    esac
    curl -fsSL "https://github.com/astral-sh/uv/releases/latest/download/uv-$TARGET.tar.gz" \
      | tar -xz -C "$UV_DIR" --strip-components=1 || fail "Telechargement de uv impossible (connexion Internet requise)."
    UV_BIN="$UV_DIR/uv"
  fi
else
  say "uv deja present."
fi

# --- 2/4 : environnement virtuel Python 3.12 --------------------------------
if [ ! -x "$VENV_DIR/bin/python" ]; then
  say "2/4 - Preparation de Python 3.12 (telecharge automatiquement si besoin)..."
  "$UV_BIN" venv --python 3.12 "$VENV_DIR" || fail "Creation de l'environnement Python impossible."
else
  say "Environnement Python deja pret."
fi

# --- 3/4 : moteur Python VoxCPM (PyTorch) — ignoré sur Mac Intel ------------
# Note : PyTorch ne publie plus de paquets pour Mac Intel (x86_64) depuis la
# version 2.5, alors que VoxCPM exige PyTorch >= 2.5. Sur Intel, on saute
# l'installation du moteur Python : le moteur C++ (étape 4) prend le relais.
PYENGINE_OK=0
if "$VENV_DIR/bin/python" -c 'import voxcpm' >/dev/null 2>&1; then
  say "Moteur Python VoxCPM deja installe."
  PYENGINE_OK=1
elif [ "$(uname -m)" = "x86_64" ]; then
  say "Mac Intel : moteur Python ignore (PyTorch >= 2.5 indisponible pour Intel)."
  echo "        -> Le moteur C++ (etape 4/4) sera utilise a la place."
  say "      - Installation des composants legers (interface native, export MP3)..."
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" lameenc \
    "pyobjc-framework-Cocoa>=9.2" "pyobjc-framework-WebKit>=9.2" \
    || say " (!) Optionnels non installes : export MP3 desactive et/ou interface via navigateur."
else
  say "3/4 - Installation des composants Python (2 a 5 minutes au premier lancement, puis instantane)..."
  "$UV_BIN" pip install --python "$VENV_DIR/bin/python" -r requirements.txt \
    || fail "Installation des dependances impossible."
  PYENGINE_OK=1
fi

# --- 4/4 : moteur C++ GGUF (llama.cpp-omni, sans PyTorch) -------------------
GGUF_NEEDED=1
if [ -x gguf/bin/voxcpm2-cli ] \
   && [ -f gguf/models/VoxCPM2-BaseLM-Q8_0.gguf ] \
   && [ -f gguf/models/VoxCPM2-Acoustic-F16.gguf ]; then
  say "Moteur C++ GGUF deja pret."
  GGUF_NEEDED=0
fi
if [ "$GGUF_NEEDED" = "1" ]; then
  say "4/4 - Preparation du moteur C++ GGUF (une seule fois ; compilation puis ~3,3 Go de poids)..."
  mkdir -p gguf/bin gguf/models

  if [ ! -d gguf/src/.git ]; then
    say "      - Recuperation des sources (llama.cpp-omni)..."
    rm -rf gguf/src
    git clone --depth 1 "https://github.com/tc-mb/llama.cpp-omni.git" gguf/src \
      || { echo "git clone impossible" > gguf/install_error.txt; \
           fail "Recuperation des sources du moteur C++ impossible (connexion Internet requise)."; }
  fi

  CMAKE="cmake"
  if ! command -v cmake >/dev/null 2>&1; then
    say "      - Installation de cmake (aucun droit admin requis)..."
    "$UV_BIN" pip install --python "$VENV_DIR/bin/python" cmake \
      || { echo "cmake indisponible" > gguf/install_error.txt; \
           fail "Installation de cmake impossible."; }
    CMAKE="$VENV_DIR/bin/cmake"
  fi

  CORES=$(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 2)
  say "      - Compilation du moteur (environ 5 a 20 minutes selon la machine)..."
  if ! ( cd gguf/src && "$CMAKE" -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=ON \
        && "$CMAKE" --build build --target voxcpm2-cli -j"$CORES" ); then
    echo "Echec de compilation de voxcpm2-cli" > gguf/install_error.txt
    fail "Compilation du moteur C++ impossible (Xcode Command Line Tools requis)."
  fi

  say "      - Installation du binaire..."
  cp gguf/src/build/bin/voxcpm2-cli gguf/bin/
  cp gguf/src/build/bin/lib*.0.dylib gguf/bin/ 2>/dev/null
  command -v install_name_tool >/dev/null 2>&1 \
    && install_name_tool -add_rpath @executable_path gguf/bin/voxcpm2-cli 2>/dev/null
  command -v xattr >/dev/null 2>&1 && xattr -c gguf/bin/voxcpm2-cli 2>/dev/null

  dl_gguf() {
    say "      - Telechargement du poids $1 (aucune action requise)..."
    curl -fL --retry 3 -C - -o "gguf/models/$1.part" \
      "https://huggingface.co/DennisHuang648/VoxCPM2-GGUF/resolve/main/$1" \
      || { rm -f "gguf/models/$1.part"; \
           echo "telechargement $1 impossible" > gguf/install_error.txt; \
           fail "Telechargement du poids $1 impossible (connexion Internet requise)."; }
    mv "gguf/models/$1.part" "gguf/models/$1"
  }
  dl_gguf VoxCPM2-BaseLM-Q8_0.gguf
  dl_gguf VoxCPM2-Acoustic-F16.gguf
fi

if [ "$PYENGINE_OK" = "0" ] && [ ! -x gguf/bin/voxcpm2-cli ]; then
  fail "Aucun moteur disponible : ni Python (Mac Intel), ni C++ (echec de l'etape 4/4)."
fi

say "Demarrage de VoxCPM Studio..."
echo "(Fermez la fenetre de l'application pour quitter.)"
echo
exec "$VENV_DIR/bin/python" desktop.py
