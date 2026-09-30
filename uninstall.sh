#!/usr/bin/env bash
# Desinstala airpodsPopUpOnArchLinux. Con --purge borra también las claves, los ajustes y el estado.
# No revierte 'Experimental = true' de /etc/bluetooth/main.conf (puede usarlo otro software).
set -uo pipefail   # sin -e: si un paso falla, se sigue limpiando el resto

PLUGIN_ID="canoojson/airpods"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/airpods-linux"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/airpodsd.service"
PLUGIN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins/airpods"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/airpods-linux"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/airpods-linux"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/airpods-linux"
RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/airpods-linux"
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

ok() { printf '  ✔ %s\n' "$*"; }

# El servicio solo se toca si es el que instaló install.sh (ejecuta el venv de DATA_DIR).
ours_unit() { [ -f "$UNIT" ] && grep -q "$DATA_DIR/venv/bin/airpodsd" "$UNIT"; }
if ours_unit || { [ -L "$UNIT_DIR/default.target.wants/airpodsd.service" ] && [ ! -e "$UNIT" ]; }; then
  systemctl --user disable --now airpodsd.service >/dev/null 2>&1 || true
  rm -f "$UNIT"
  # Enlace de arranque colgando (si el fichero de la unidad ya no existía)
  [ -L "$UNIT_DIR/default.target.wants/airpodsd.service" ] && [ ! -e "$UNIT_DIR/default.target.wants/airpodsd.service" ] \
    && rm -f "$UNIT_DIR/default.target.wants/airpodsd.service"
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user reset-failed airpodsd.service >/dev/null 2>&1 || true
  ok "servicio airpodsd detenido y eliminado"
elif [ -f "$UNIT" ]; then
  echo "  ! $UNIT no apunta a esta instalación (¿instalación de desarrollo?); no se toca"
fi

# Cualquier airpodsd de esta instalación que siga vivo (p. ej. lanzado a mano)
if pkill -f "$DATA_DIR/venv/bin/airpodsd" 2>/dev/null; then ok "procesos airpodsd detenidos"; fi

for b in airpodsctl airpodsd; do
  if [ -L "$BIN_DIR/$b" ] && [[ "$(readlink "$BIN_DIR/$b")" == "$DATA_DIR/"* ]]; then rm -f "$BIN_DIR/$b"; fi
done
ok "comandos airpodsctl y airpodsd eliminados de $BIN_DIR"

if [ -e "$PLUGIN_DIR" ] && grep -q "^id = \"$PLUGIN_ID\"" "$PLUGIN_DIR/plugin.toml" 2>/dev/null; then
  command -v noctalia >/dev/null && noctalia msg plugins disable "$PLUGIN_ID" >/dev/null 2>&1
  if [ -L "$PLUGIN_DIR" ]; then rm -f "$PLUGIN_DIR"; else rm -rf "$PLUGIN_DIR"; fi
  ok "plugin de Noctalia eliminado (si tenías el widget en la barra, quítalo en Ajustes → Barra)"
fi

rm -rf "$DATA_DIR" "$RUNTIME_DIR" "$CACHE_DIR"
ok "programa, estado en memoria y logs eliminados"

if [ "$PURGE" = 1 ]; then
  rm -rf "$CONFIG_DIR" "$STATE_DIR"
  ok "claves, ajustes y último estado eliminados"
else
  kept=()
  [ -e "$CONFIG_DIR" ] && kept+=("$CONFIG_DIR (claves y ajustes)")
  [ -e "$STATE_DIR" ] && kept+=("$STATE_DIR (último estado)")
  if [ ${#kept[@]} -gt 0 ]; then
    echo "  Se conservan, para una reinstalación futura:"
    printf '    - %s\n' "${kept[@]}"
    echo "  Bórralos también con: $0 --purge"
  fi
fi
echo "  No se revierte 'Experimental = true' en /etc/bluetooth/main.conf."
