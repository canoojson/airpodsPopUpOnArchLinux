# airpodsPopUpOnArchLinux

Batería de tus **AirPods en Linux**, también **con la caja cerrada**, y un **popup estilo iOS** al abrir la caja con los auriculares dentro.

> **English:** Linux daemon + CLI that reads AirPods battery (left/right/case, 1 % precision, even with the lid closed) from Apple's BLE advertisements, and shows an iOS-like popup when you open the case. Works with any desktop (notification fallback); first-class integration for the Noctalia shell. Install: `curl -fsSL https://raw.githubusercontent.com/canoojson/airpodsPopUpOnArchLinux/main/install.sh | bash`

## Qué hace

- **Batería al 1 %** del auricular izquierdo, del derecho y de la caja, con su estado de carga, detección en oreja y estado de la tapa.
- **Con la caja cerrada:** la caja sigue anunciando su estado cifrado durante minutos; con las claves de tus AirPods se descifra y se ve la batería en vivo.
- **Popup al abrir la caja**, en ~1 s: panel flotante en [Noctalia](https://github.com/noctalia-dev/noctalia) o notificación de escritorio en cualquier otro entorno.
- **Último estado conocido** con su antigüedad cuando no hay datos frescos ("visto hace 5 min"), nunca un dato viejo presentado como actual.
- **Sin escaneo continuo:** usa el monitor pasivo de anuncios de BlueZ, que no interfiere con tus otros dispositivos Bluetooth.
- `airpodsctl` para la terminal y una API D-Bus para integrarlo en otros widgets.
- Todo local: no usa internet ni la cuenta de iCloud.

## Compatibilidad

| | Estado |
|---|---|
| **AirPods Pro 3** | ✅ Probado a fondo |
| Otros AirPods / Beats | ⚠️ Sin probar. El anuncio de los auriculares es común a todos los modelos y probablemente funcione; el de la caja cerrada se ha verificado solo con el Pro 3 |
| Distribución | Desarrollado en **Arch Linux**. Debería funcionar en cualquier distro con systemd y BlueZ reciente |
| Escritorio | Cualquiera (notificación). Integración completa con **Noctalia**; animación del popup con **Hyprland** |

¿Lo has probado con otro modelo? Abre un *issue* con la salida de `airpodsctl status --json`.

## Requisitos

### Obligatorios

| Requisito | Por qué | Arch | Debian / Ubuntu | Fedora |
|---|---|---|---|---|
| Adaptador **Bluetooth con BLE** (4.0+) | Leer los anuncios de los AirPods | — | — | — |
| **systemd** (sesión de usuario) | Servicio `airpodsd` | — | — | — |
| **BlueZ** reciente y `bluetoothctl` | Pila Bluetooth (probado con 5.87) | `bluez bluez-utils` | `bluez` | `bluez` |
| **Python ≥ 3.11** con `venv` | El programa | `python` | `python3 python3-venv` | `python3` |
| **dbus-python** | Hablar con BlueZ | `python-dbus` | `python3-dbus` | `python3-dbus` |
| **PyGObject** | Bucle de eventos | `python-gobject` | `python3-gi` | `python3-gobject` |
| `curl` | Solo para instalar con una línea | `curl` | `curl` | `curl` |

```sh
sudo pacman -S --needed bluez bluez-utils python python-dbus python-gobject curl   # Arch
sudo apt install bluez python3 python3-venv python3-dbus python3-gi curl         # Debian/Ubuntu
sudo systemctl enable --now bluetooth
```

La dependencia de Python restante (`cryptography`) se instala sola en un entorno aislado.

### Recomendados

- **`Experimental = true` en `/etc/bluetooth/main.conf`** (el instalador te lo ofrece). Activa el monitor pasivo de anuncios de BlueZ: el popup aparece en ~1 s y no se mantiene un escaneo abierto. Sin él, `airpodsd` escanea por ventanas y el popup puede tardar hasta ~8 s.
- Un **kernel reciente**: el monitor pasivo necesita soporte de *Advertisement Monitor* en el kernel. Si no lo hay, `airpodsd` vuelve solo al escaneo por ventanas.

### Opcionales

- **[Noctalia](https://github.com/noctalia-dev/noctalia) v5** con plugin API ≥ 30 (v5.0.1 o posterior; probado con 5.2.0): widget de barra, panel y el popup. Sin Noctalia, el popup es una notificación (`notify-send`, paquete `libnotify`).
- **Hyprland**: animación de deslizamiento del popup (ver abajo).
- **[airpods-helper](https://github.com/superninjv/airpods-helper)**: si está instalado, el panel de Noctalia muestra también el selector de modo de escucha (cancelación de ruido, adaptativo, ambiente).

## Instalación

**En una línea** (descarga la última release, o `main` si aún no hay):

```sh
curl -fsSL https://raw.githubusercontent.com/canoojson/airpodsPopUpOnArchLinux/main/install.sh | bash
```

**Desde un clon o un paquete descargado** de [Releases](https://github.com/canoojson/airpodsPopUpOnArchLinux/releases):

```sh
git clone https://github.com/canoojson/airpodsPopUpOnArchLinux.git
cd airpodsPopUpOnArchLinux
./install.sh
```

El instalador trabaja en tu usuario: no necesita `sudo`, salvo si aceptas activar `Experimental` en BlueZ.

1. Comprueba los requisitos y te dice qué paquetes faltan.
2. Instala el programa en `~/.local/share/airpods-linux` (entorno Python propio) y los comandos `airpodsctl` y `airpodsd` en `~/.local/bin`.
3. Te ofrece activar `Experimental = true` en BlueZ.
4. Instala y arranca el servicio de usuario `airpodsd`.
5. Si tienes Noctalia, instala y activa el plugin `canoojson/airpods`.

Opciones: `--no-service`, `--no-noctalia`, `--no-bluez`, `--ref <rama|etiqueta>`, `--uninstall [--purge]`.

## Primeros pasos

1. **Empareja** los AirPods con el equipo (con `bluetoothctl` o tu gestor de Bluetooth) y conéctalos.
2. **Pide sus claves** con la caja abierta cerca. Solo hace falta una vez:
   ```sh
   airpodsctl keys fetch
   ```
   Si usas **airpods-helper**, páralo durante este paso, porque ocupa el mismo canal: `systemctl --user stop airpods-daemon`, y luego `start`.
3. **Comprueba** que funciona:
   ```sh
   airpodsctl status
   ```
   ```
   AirPods Pro 3 · visto hace 0 s
     Izquierdo 100 %  ⚡  en la caja
     Derecho   100 %  ⚡  en la caja
     Caja       98 %  ⚡  tapa cerrada · en el cargador
   ```
4. **Abre la caja** con los auriculares dentro: aparece el popup.
5. En Noctalia, añade el widget **AirPods** a tu barra (Ajustes → Barra).

Sin claves también funciona, pero con la batería en saltos de 10 %, sin datos con la caja cerrada y distinguiendo tus AirPods de los ajenos solo por cercanía.

## Uso

```sh
airpodsctl status [--json] [--scan SEG]   # estado actual o último conocido (--scan 0: solo caché)
airpodsctl watch [--json]                  # muestra cada cambio en vivo
airpodsctl keys fetch [MAC] | show         # claves de proximidad
systemctl --user status airpodsd          # el servicio
journalctl --user -u airpodsd -f          # sus logs (aperturas y cierres de la caja)
```

### Popup animado en Hyprland

Noctalia no anima sus paneles flotantes, pero Hyprland sí puede. En tu configuración Lua de Hyprland (probado con 0.56):

```lua
hl.layer_rule({ match = { namespace = "^noctalia-panel$" }, animation = "slide" })
```

Con `hyprland.conf`, usa la regla `layerrule` equivalente (ver la wiki de Hyprland). Afecta a todos los paneles de Noctalia: cada uno se desliza desde su borde más cercano, y el popup, desde abajo.

### Integración con otros widgets

- **D-Bus** (bus de sesión): `io.github.AirpodsLinux`, objeto `/io/github/AirpodsLinux`, interfaz `io.github.AirpodsLinux1`.
  - `GetState() → s` (JSON)
  - Señales `StateChanged(s)`, `CaseOpened(s)` y `CaseClosed()`.
  ```sh
  busctl --user call io.github.AirpodsLinux /io/github/AirpodsLinux io.github.AirpodsLinux1 GetState
  ```
- **Fichero**: `$XDG_RUNTIME_DIR/airpods-linux/status.json`, con el mismo JSON y actualizado en cada cambio. Es útil para Waybar, eww, Quickshell…

Cada campo del JSON lleva `value`, `ts` (época Unix) y `source` (`ble-enc`, `ble-case` o `ble-clear`).

## Cómo funciona

Los AirPods anuncian por Bluetooth LE un mensaje *Proximity Pairing* de Apple con una parte en claro (batería en pasos de 10 %) y 16 bytes cifrados (batería al 1 %). La caja también anuncia su propio mensaje cifrado, incluso con la tapa cerrada. `airpodsctl keys fetch` pide a los AirPods, por el protocolo AAP (L2CAP 0x1001), su **IRK**, que sirve para reconocer sus direcciones aleatorias, y su **clave de cifrado**. Con ellas `airpodsd` identifica tus AirPods y descifra ambos anuncios. Detalles y capturas en [`docs/findings.md`](docs/findings.md).

## Privacidad y seguridad

- Las claves se guardan en `~/.config/airpods-linux/keys.json` con permisos `0600`. **No las compartas**: permiten reconocer tus AirPods.
- No hay conexión a internet ni telemetría. Los logs no incluyen claves ni ubicaciones.
- Solo se procesan los anuncios de *tus* AirPods; los de otras personas se descartan.

## Solución de problemas

| Síntoma | Solución |
|---|---|
| `keys fetch`: "no enviaron las claves" | Otro programa ocupa el canal AAP (p. ej. `airpods-daemon`); páralo y reintenta. Los AirPods deben estar **conectados** |
| El popup tarda varios segundos | Activa `Experimental = true` en BlueZ; en el log de `airpodsd` debe poner `modo de escaneo: pasivo` |
| La batería de la caja sale `--` | Con la caja abierta y vacía en el cargador, la caja deja de anunciarse: ciérrala o mete un auricular |
| No aparece el popup | Comprueba `journalctl --user -u airpodsd` ("caja abierta…") y que el plugin esté activo: `noctalia msg plugins list` |
| El widget dice "airpodsd no está en ejecución" | `systemctl --user enable --now airpodsd` |

## Desinstalar

```sh
~/.local/share/airpods-linux/src/uninstall.sh          # conserva claves y estado
~/.local/share/airpods-linux/src/uninstall.sh --purge  # lo borra todo
```

No revierte `Experimental = true` en BlueZ.

## Desarrollo

```sh
uv venv --system-site-packages .venv          # o: python -m venv --system-site-packages .venv
uv pip install --python .venv/bin/python -e . pytest
.venv/bin/python -m pytest                    # sin hardware: vectores sintéticos
```

- `src/airpods_linux/`: parser, cifrado, estado, escáner, daemon y CLI.
- `integrations/noctalia/airpods/`: el plugin de Noctalia.
- `tools/`: herramientas de captura de la fase de investigación.
- `fixtures/`: capturas reales, solo con anuncios propios.

Las releases se publican al subir una etiqueta `vX.Y.Z` (GitHub Actions).

## Licencia y créditos

[GPL-3.0-or-later](LICENSE). Si publicas una versión modificada, debe llevar su código fuente bajo la misma licencia y conservar los créditos. Si mejoras algo, se agradece un *pull request*.

La interpretación del protocolo se basa en la documentación de [LibrePods](https://github.com/kavishdevar/librepods) y otros proyectos; ver [CREDITS.md](CREDITS.md). No afiliado a Apple.
