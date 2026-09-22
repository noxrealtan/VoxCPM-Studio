#!/bin/bash
# ============================================================================
#  Lance la suite de tests : environnement de l'app si present (tous les
#  flux, y compris generation GGUF), sinon python3 systeme (flux legers,
#  les tests lourds se desactivent tout seuls).
# ============================================================================
cd "$(dirname "$0")/.."
PY="$HOME/.voxcpm-studio/venv/bin/python"
[ -x "$PY" ] || PY=python3
echo "Python : $PY ($("$PY" --version 2>&1))"
exec "$PY" -m unittest discover -s tests -v
