#!/usr/bin/env bash
# Desinstala airpodsPopUpOnArchLinux. Con --purge borra también las claves y el estado guardado.
# No revierte 'Experimental = true' de /etc/bluetooth/main.conf (puede usarlo otro software).
set -euo pipefail

PLUGIN_ID="canoojson/airpods"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/airpods-linux"
BIN_DIR="$HOME/.local/bin"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/airpodsd.service"
PLUGIN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins/airpods"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

if [ -e "$UNIT" ]; then
  systemctl --user disable --now airpodsd.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "✔ servicio airpodsd eliminado"
fi

for b in airpodsctl airpodsd; do
  if [ -L "$BIN_DIR/$b" ] && [[ "$(readlink "$BIN_DIR/$b")" == "$DATA_DIR/"* ]]; then rm -f "$BIN_DIR/$b"; fi
done

if grep -q "^id = \"$PLUGIN_ID\"" "$PLUGIN_DIR/plugin.toml" 2>/dev/null; then
  command -v noctalia >/dev/null && noctalia msg plugins disable "$PLUGIN_ID" >/dev/null 2>&1 || true
  rm -rf "$PLUGIN_DIR"
  echo "✔ plugin de Noctalia eliminado"
fi

rm -rf "$DATA_DIR"
rm -rf "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/airpods-linux"
echo "✔ programa eliminado ($DATA_DIR)"

if [ "$PURGE" = 1 ]; then
  rm -rf "${XDG_CONFIG_HOME:-$HOME/.config}/airpods-linux" "${XDG_STATE_HOME:-$HOME/.local/state}/airpods-linux"
  echo "✔ claves y estado eliminados"
else
  echo "  Se conservan las claves (~/.config/airpods-linux) y el estado (~/.local/state/airpods-linux); usa --purge para borrarlos."
fi
