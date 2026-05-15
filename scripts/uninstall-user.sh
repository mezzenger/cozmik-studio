#!/usr/bin/env bash
set -euo pipefail

rm -f "${HOME}/.local/bin/cozmik-studio"
rm -f "${HOME}/.local/bin/cozmik-studio-mcp"
rm -f "${HOME}/.local/bin/streamdeck-studio"
rm -f "${HOME}/.local/bin/streamdeck-studio-mcp"
rm -f "${HOME}/.local/share/applications/dev.local.CozmikStudio.desktop"
rm -f "${HOME}/.local/share/applications/cozmik-studio.desktop"
rm -f "${HOME}/.local/share/applications/streamdeck-studio.desktop"
for size in 64 128 256 512; do
  rm -f "${HOME}/.local/share/icons/hicolor/${size}x${size}/apps/cozmik-studio.png"
done

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${HOME}/.local/share/applications" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -q -t -f "${HOME}/.local/share/icons/hicolor" >/dev/null 2>&1 || true
fi

echo "Removed Cozmik Studio user launcher files."
