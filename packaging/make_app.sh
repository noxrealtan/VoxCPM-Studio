#!/bin/bash
# ============================================================================
#  Construit le bundle macOS « VoxCPM Studio.app » dans le dossier du projet.
#  L'app lance desktop.py avec le venv existant ; au premier lancement sans
#  venv, elle ouvre le lanceur d'installation (Lancer VoxCPM Studio.command).
# ============================================================================
set -eu
cd "$(dirname "$0")/.."

APP="VoxCPM Studio.app"
PLIST="$APP/Contents/Info.plist"
BIN="$APP/Contents/MacOS/VoxCPM Studio"
RES="$APP/Contents/Resources"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$RES"

cat > "$PLIST" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>VoxCPM Studio</string>
  <key>CFBundleDisplayName</key><string>VoxCPM Studio</string>
  <key>CFBundleIdentifier</key><string>local.voxcpm.studio</string>
  <key>CFBundleExecutable</key><string>VoxCPM Studio</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSHumanReadableCopyright</key><string>Moteur VoxCPM (Apache-2.0) — OpenBMB</string>
</dict>
</plist>
PLIST

cat > "$BIN" <<'SCRIPT'
#!/bin/bash
# Lanceur du bundle : venv existant -> app native directe ; sinon installeur.
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
VENV="$HOME/.voxcpm-studio/venv"
if [ ! -x "$VENV/bin/python" ]; then
  open "$ROOT/Lancer VoxCPM Studio.command"
  exit 0
fi
exec "$VENV/bin/python" "$ROOT/desktop.py"
SCRIPT
chmod +x "$BIN"

if command -v iconutil >/dev/null 2>&1 && command -v sips >/dev/null 2>&1; then
  ICONSET="$(mktemp -d)/VoxCPMStudio.iconset"
  python3 packaging/make_icon.py "$ICONSET"
  S="$(mktemp -d)"
  for sz in 16 32 128 256 512; do
    cp "$ICONSET/icon_${sz}x${sz}@2x.png" /tmp/_master.png 2>/dev/null || true
  done
  cp "$ICONSET/icon_512x512@2x.png" "$S/master.png"
  for sz in 16 32 128 256 512; do
    sips -z $sz $sz "$S/master.png" --out "$ICONSET/icon_${sz}x${sz}.png" >/dev/null
    sips -z $((sz*2)) $((sz*2)) "$S/master.png" --out "$ICONSET/icon_${sz}x${sz}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$RES/VoxCPMStudio.icns"
  /usr/libexec/PlistBuddy -c "Add :CFBundleIconFile string VoxCPMStudio" "$PLIST" 2>/dev/null || true
  rm -rf "$S" "$(dirname "$ICONSET")"
  echo "Icône générée."
else
  echo "sips/iconutil absents : icône générique."
fi

echo "Bundle créé : $APP"
