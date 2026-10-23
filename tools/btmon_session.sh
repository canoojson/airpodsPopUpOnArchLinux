#!/usr/bin/env bash
# Sesión guiada para cerrar los dos [VERIFICAR] que quedan en docs/findings.md.
#
#   tools/btmon_session.sh caja-cerrada [minutos]   cada cuánto anuncia la caja cerrada (por defecto 20 min)
#   tools/btmon_session.sh flags                    qué es el bit 0 de los flags de la caja
#
# Necesita sudo para btmon (solo escucha: no envía nada al adaptador). airpodsd debe
# estar en marcha: su monitor pasivo es el que hace que el controlador informe de los
# anuncios. Mejor sin estar escuchando música con los AirPods.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/fixtures"
# El Python de la instalación tiene cryptography (para descifrar); si no, el del sistema.
PY="${XDG_DATA_HOME:-$HOME/.local/share}/airpods-linux/venv/bin/python"
[ -x "$PY" ] || PY=python3
mode="${1:-}"

capture() {   # capture <nombre> <segundos>
  local file="$OUT/btmon_$1.btsnoop"
  echo "  Capturando $2 s en $file…"
  sudo timeout "$2" btmon -w "$file" >/dev/null 2>&1 || true
  sudo chown "$(id -u):$(id -g)" "$file"
  if [ "${3:-}" = decrypt ]; then
    "$PY" "$ROOT/tools/btsnoop_adverts.py" "$file" --decrypt
  else
    "$PY" "$ROOT/tools/btsnoop_adverts.py" "$file" --short
  fi
}

pause() { read -r -p "  $1 Pulsa Intro cuando esté. " _; }

case "$mode" in
  caja-cerrada)
    minutes="${2:-20}"
    echo "Caja cerrada: intervalos reales entre anuncios durante $minutes min."
    pause "Mete los dos auriculares en la caja, ciérrala y déjala junto al PC."
    capture caja_cerrada $((minutes * 60))
    echo "Apunta en docs/findings.md §8 la mediana, el máximo y los huecos de más de 60 s."
    ;;
  flags)
    echo "Flags de la caja: cuatro estados de 60 s cada uno."
    for step in "abierta_vacia:Saca los auriculares y deja la caja abierta, sin cargador." \
                "cerrada_vacia:Cierra la caja vacía." \
                "cerrada_vacia_cargador:Enchufa la caja cerrada y vacía al cargador." \
                "cerrada_dentro_cargador:Ábrela, mete los dos auriculares y ciérrala (sigue enchufada)."; do
      pause "${step#*:}"
      capture "flags_${step%%:*}" 60 decrypt
    done
    echo "Apunta en docs/findings.md §12 qué hace el bit 0 en cada estado."
    ;;
  *)
    sed -n '2,9p' "$0"
    exit 2
    ;;
esac
