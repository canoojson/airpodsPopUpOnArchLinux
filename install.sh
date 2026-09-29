#!/usr/bin/env bash
# Instalador de airpodsPopUpOnArchLinux (usuario, sin root salvo para activar BlueZ Experimental).
#
#   curl -fsSL https://raw.githubusercontent.com/canoojson/airpodsPopUpOnArchLinux/main/install.sh | bash
#   ./install.sh [opciones]            # desde un clon o un paquete descargado
#
# Opciones:
#   --no-service     no instala ni arranca el servicio systemd airpodsd
#   --no-noctalia    no instala el plugin de Noctalia
#   --no-bluez       no ofrece activar Experimental en /etc/bluetooth/main.conf
#   --ref REF        rama o etiqueta a descargar si no se ejecuta desde un clon (por defecto: última release)
#   --uninstall      desinstala (ver uninstall.sh; --purge borra también claves y estado)
set -euo pipefail

REPO="canoojson/airpodsPopUpOnArchLinux"
PLUGIN_ID="canoojson/airpods"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/airpods-linux"
BIN_DIR="$HOME/.local/bin"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
NOCTALIA_PLUGINS="${XDG_DATA_HOME:-$HOME/.local/share}/noctalia/plugins"
BLUEZ_CONF=/etc/bluetooth/main.conf

WITH_SERVICE=1 WITH_NOCTALIA=1 WITH_BLUEZ=1 REF="" UNINSTALL=0 UNINSTALL_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --no-service) WITH_SERVICE=0 ;;
    --no-noctalia) WITH_NOCTALIA=0 ;;
    --no-bluez) WITH_BLUEZ=0 ;;
    --ref) REF="${2:?--ref necesita un valor}"; shift ;;
    --uninstall) UNINSTALL=1 ;;
    --purge) UNINSTALL_ARGS+=(--purge) ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "Opción desconocida: $1" >&2; exit 2 ;;
  esac
  shift
done

if [ -t 1 ]; then B=$'\e[1m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' N=$'\e[0m'; else B="" G="" Y="" R="" N=""; fi
step() { printf '%s==>%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '  %s✔%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
die()  { printf '%sError:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
# Pregunta s/N también con `curl | bash` (stdin es el script: se lee de /dev/tty).
ask() {
  local reply=""
  { exec 3</dev/tty; } 2>/dev/null || return 1
  printf '  %s [s/N] ' "$1"
  read -r reply <&3 || true
  exec 3<&-
  [[ "$reply" =~ ^[sSyY] ]]
}

SRC=""
TMP=""
cleanup() { [ -n "$TMP" ] && rm -rf "$TMP"; }
trap cleanup EXIT

script_dir() {
  local src="${BASH_SOURCE[0]:-}"
  [ -n "$src" ] && [ -f "$src" ] && cd "$(dirname "$src")" && pwd
}

if [ "$UNINSTALL" = 1 ]; then
  dir="$(script_dir || true)"
  if [ -n "$dir" ] && [ -x "$dir/uninstall.sh" ]; then exec "$dir/uninstall.sh" "${UNINSTALL_ARGS[@]}"; fi
  [ -x "$DATA_DIR/src/uninstall.sh" ] && exec "$DATA_DIR/src/uninstall.sh" "${UNINSTALL_ARGS[@]}"
  die "no encuentro uninstall.sh"
fi

# ---------------------------------------------------------------------------
step "Comprobando requisitos"
missing=()
pkg_hint=""
if command -v pacman >/dev/null; then pkg_hint="sudo pacman -S --needed"
elif command -v apt-get >/dev/null; then pkg_hint="sudo apt install"
elif command -v dnf >/dev/null; then pkg_hint="sudo dnf install"; fi

command -v python3 >/dev/null || die "falta python3 (>= 3.11)"
python3 - <<'EOF' || die "se necesita Python >= 3.11 (tienes $(python3 -V 2>&1))"
import sys; sys.exit(sys.version_info < (3, 11))
EOF
ok "$(python3 -V)"

python3 -c 'import venv, ensurepip' 2>/dev/null || missing+=("venv:python3-venv (Debian/Ubuntu)")
python3 -c 'import dbus' 2>/dev/null || missing+=("dbus-python:python-dbus (Arch) · python3-dbus (Debian/Ubuntu/Fedora)")
python3 -c 'import gi; gi.require_version("GLib", "2.0"); from gi.repository import GLib' 2>/dev/null \
  || missing+=("PyGObject:python-gobject (Arch) · python3-gi (Debian/Ubuntu) · python3-gobject (Fedora)")
command -v bluetoothctl >/dev/null || missing+=("bluetoothctl:bluez-utils (Arch) · bluez (Debian/Ubuntu/Fedora)")
if [ ${#missing[@]} -gt 0 ]; then
  for m in "${missing[@]}"; do warn "falta ${m%%:*} → paquete ${m#*:}"; done
  [ -n "$pkg_hint" ] && echo "  Instálalos con: $pkg_hint <paquetes>"
  die "faltan dependencias del sistema"
fi
ok "dbus-python, PyGObject y bluetoothctl"

if systemctl is-active --quiet bluetooth 2>/dev/null; then
  ok "servicio bluetooth activo ($(bluetoothctl --version 2>/dev/null | head -1))"
else
  warn "el servicio bluetooth no está activo: sudo systemctl enable --now bluetooth"
fi
if [ "$WITH_SERVICE" = 1 ] && ! systemctl --user show-environment >/dev/null 2>&1; then
  warn "systemd --user no disponible: se instala sin servicio"
  WITH_SERVICE=0
fi

# ---------------------------------------------------------------------------
step "Obteniendo el código"
dir="$(script_dir || true)"
if [ -n "$dir" ] && [ -f "$dir/pyproject.toml" ] && [ -d "$dir/src/airpods_linux" ]; then
  SRC="$dir"
  ok "desde $SRC"
else
  command -v curl >/dev/null || die "falta curl"
  TMP="$(mktemp -d)"
  if [ -n "$REF" ]; then
    url="https://github.com/$REPO/archive/$REF.tar.gz"
  else
    url="https://github.com/$REPO/releases/latest/download/airpods-linux.tar.gz"
  fi
  if ! curl -fsSL "$url" -o "$TMP/src.tar.gz"; then
    warn "no hay release publicada; uso la rama main"
    curl -fsSL "https://github.com/$REPO/archive/main.tar.gz" -o "$TMP/src.tar.gz" || die "no se pudo descargar $REPO"
  fi
  mkdir "$TMP/src"
  tar -xzf "$TMP/src.tar.gz" -C "$TMP/src" --strip-components=1
  SRC="$TMP/src"
  ok "descargado"
fi

# ---------------------------------------------------------------------------
step "Instalando en $DATA_DIR"
mkdir -p "$DATA_DIR"
if [ "$SRC" != "$DATA_DIR/src" ]; then
  rm -rf "$DATA_DIR/src.new"
  mkdir -p "$DATA_DIR/src.new"
  (cd "$SRC" && tar --exclude=.git --exclude=.venv --exclude='__pycache__' -cf - .) | tar -xf - -C "$DATA_DIR/src.new"
  rm -rf "$DATA_DIR/src"
  mv "$DATA_DIR/src.new" "$DATA_DIR/src"
fi
# --system-site-packages: dbus-python y PyGObject vienen del sistema.
[ -x "$DATA_DIR/venv/bin/python" ] || python3 -m venv --system-site-packages "$DATA_DIR/venv"
"$DATA_DIR/venv/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade "$DATA_DIR/src" \
  || die "pip no pudo instalar el paquete"
ok "entorno Python listo"

mkdir -p "$BIN_DIR"
for b in airpodsctl airpodsd; do ln -sf "$DATA_DIR/venv/bin/$b" "$BIN_DIR/$b"; done
ok "comandos en $BIN_DIR: airpodsctl, airpodsd"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR no está en tu PATH; añádelo a tu shell" ;; esac

# ---------------------------------------------------------------------------
if [ "$WITH_BLUEZ" = 1 ]; then
  step "BlueZ: monitor pasivo de anuncios"
  if grep -Eq '^[[:space:]]*Experimental[[:space:]]*=[[:space:]]*true' "$BLUEZ_CONF" 2>/dev/null; then
    ok "Experimental = true ya está activo"
  else
    warn "sin 'Experimental = true' en $BLUEZ_CONF airpodsd escanea por ventanas: el popup puede tardar hasta ~8 s"
    if ask "¿Activarlo ahora con sudo? (reinicia bluetooth: tus dispositivos se desconectarán unos segundos)"; then
      if grep -Eq '^[[:space:]]*#?[[:space:]]*Experimental[[:space:]]*=' "$BLUEZ_CONF"; then
        sudo sed -i -E 's/^[[:space:]]*#?[[:space:]]*Experimental[[:space:]]*=.*/Experimental = true/' "$BLUEZ_CONF"
      else
        sudo sed -i '/^\[General\]/a Experimental = true' "$BLUEZ_CONF"
      fi
      sudo systemctl restart bluetooth && ok "activado y bluetooth reiniciado"
    else
      echo "  Hazlo más tarde con:"
      echo "    sudo sed -i 's/^#Experimental = false/Experimental = true/' $BLUEZ_CONF && sudo systemctl restart bluetooth"
    fi
  fi
fi

# ---------------------------------------------------------------------------
if [ "$WITH_SERVICE" = 1 ]; then
  step "Servicio systemd de usuario"
  mkdir -p "$UNIT_DIR"
  sed "s|@AIRPODSD@|$DATA_DIR/venv/bin/airpodsd|" "$DATA_DIR/src/contrib/airpodsd.service.in" > "$UNIT_DIR/airpodsd.service"
  systemctl --user daemon-reload
  systemctl --user enable airpodsd.service >/dev/null 2>&1
  systemctl --user restart airpodsd.service
  sleep 1
  if systemctl --user is-active --quiet airpodsd; then ok "airpodsd activo (journalctl --user -u airpodsd -f)"
  else warn "airpodsd no arrancó: journalctl --user -u airpodsd -e"; fi
fi

# ---------------------------------------------------------------------------
if [ "$WITH_NOCTALIA" = 1 ] && command -v noctalia >/dev/null; then
  step "Plugin de Noctalia ($PLUGIN_ID)"
  dest="$NOCTALIA_PLUGINS/airpods"
  if [ -L "$dest" ] && [ "$(readlink -f "$dest")" != "$(readlink -f "$DATA_DIR/src/integrations/noctalia/airpods")" ]; then
    warn "$dest ya apunta a $(readlink "$dest") (instalación de desarrollo); no lo toco"
  else
    if [ -e "$dest" ] && ! grep -q "^id = \"$PLUGIN_ID\"" "$dest/plugin.toml" 2>/dev/null; then
      mv "$dest" "$dest.backup-$(date +%s)"
      warn "había otro plugin en $dest; movido a $dest.backup-*"
    fi
    mkdir -p "$NOCTALIA_PLUGINS"
    rm -rf "$dest"
    cp -r "$DATA_DIR/src/integrations/noctalia/airpods" "$dest"
    ok "copiado en $dest"
  fi
  if noctalia msg plugins enable "$PLUGIN_ID" >/dev/null 2>&1; then
    ok "activado. Añade el widget 'AirPods' a tu barra desde Ajustes → Barra"
  else
    warn "Noctalia no está en ejecución; actívalo luego con: noctalia msg plugins enable $PLUGIN_ID"
  fi
  if command -v hyprctl >/dev/null; then
    echo "  Opcional (Hyprland): animación de deslizamiento para el popup, en tu config Lua:"
    echo "    hl.layer_rule({ match = { namespace = \"^noctalia-panel\$\" }, animation = \"slide\" })"
  fi
elif [ "$WITH_NOCTALIA" = 1 ]; then
  warn "Noctalia no está instalado: el aviso al abrir la caja será una notificación de escritorio"
fi

# ---------------------------------------------------------------------------
step "Listo. Último paso: las claves de tus AirPods"
cat <<EOF
  1. Empareja los AirPods con este equipo (bluetoothctl o el gestor de Bluetooth) y conéctalos.
  2. Con la caja abierta cerca, ejecuta:   airpodsctl keys fetch
     (si tienes airpods-helper activo:  systemctl --user stop airpods-daemon  antes, y start después)
  3. Comprueba:                           airpodsctl status
  Sin claves funciona igual, pero con batería al 10 % y sin datos con la caja cerrada.
EOF
