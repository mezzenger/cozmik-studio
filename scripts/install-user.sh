#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
LAUNCHER="${BIN_DIR}/streamdeck-studio"
DESKTOP="${APP_DIR}/streamdeck-studio.desktop"

mkdir -p "${BIN_DIR}" "${APP_DIR}"

cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
cd "${ROOT_DIR}"
exec python3 -m streamdeck_studio "\$@"
EOF
chmod +x "${LAUNCHER}"

sed "s|Exec=streamdeck-studio|Exec=${LAUNCHER}|" \
  "${ROOT_DIR}/packaging/applications/streamdeck-studio.desktop" > "${DESKTOP}"

echo "Installed ${LAUNCHER}"
echo "Installed ${DESKTOP}"
