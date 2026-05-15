#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${HOME}/.local/bin"
APP_DIR="${HOME}/.local/share/applications"
LAUNCHER="${BIN_DIR}/cozmik-studio"
MCP_LAUNCHER="${BIN_DIR}/cozmik-studio-mcp"
DESKTOP="${APP_DIR}/dev.local.CozmikStudio.desktop"

mkdir -p "${BIN_DIR}" "${APP_DIR}"

cat > "${LAUNCHER}" <<EOF
#!/usr/bin/env bash
cd "${ROOT_DIR}"
exec python3 -m streamdeck_studio "\$@"
EOF
chmod +x "${LAUNCHER}"

cat > "${MCP_LAUNCHER}" <<EOF
#!/usr/bin/env bash
cd "${ROOT_DIR}"
exec python3 -m streamdeck_studio.mcp_server "\$@"
EOF
chmod +x "${MCP_LAUNCHER}"

sed "s|Exec=cozmik-studio|Exec=${LAUNCHER}|" \
  "${ROOT_DIR}/packaging/applications/dev.local.CozmikStudio.desktop" > "${DESKTOP}"

for size in 64 128 256 512; do
  icon_dir="${HOME}/.local/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "${icon_dir}"
  cp "${ROOT_DIR}/streamdeck_studio/resources/branding/cozmik-studio-${size}.png" "${icon_dir}/cozmik-studio.png"
done

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APP_DIR}" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Installed ${LAUNCHER}"
echo "Installed ${MCP_LAUNCHER}"
echo "Installed ${DESKTOP}"
echo "Installed hicolor app icons"
