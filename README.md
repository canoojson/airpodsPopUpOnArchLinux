# airpodsPopUpOnArchLinux

Batería de tus **AirPods en Linux**, también **con la caja cerrada**, y un **popup estilo iOS** al abrir la caja con los auriculares dentro.

> **English:** ⚠️ Read the *known audio conflicts* warning below before installing (Linux Wallpaper Engine, EasyEffects, airpods-helper). Linux daemon + CLI that reads AirPods battery (left/right/case, 1 % precision, even with the lid closed) from Apple's BLE advertisements, and shows an iOS-like popup when you open the case. Works with any desktop (notification fallback); first-class integration for the Noctalia shell. Install: `curl -fsSL https://raw.githubusercontent.com/canoojson/airpodsPopUpOnArchLinux/main/install.sh | bash`

> [!WARNING]
> ### ⚠️ LEE ESTO ANTES DE INSTALAR: conflictos de audio conocidos
>
> Hay programas de escritorio que, al **conectar o desconectar los AirPods**, pueden hacer que **el audio de todo el sistema se atasque** (el vídeo del navegador se queda "cargando", sin sonido) o que **el sonido no pase a los AirPods** hasta que cambias la salida a mano. **No son fallos de este proyecto, pero te afectarán igual**, así que antes de pensar que esto no funciona, revisa si usas alguno:
>
> | Si usas… | Qué pasa | Arreglo |
> |---|---|---|
> | 🖼️ **Linux Wallpaper Engine** (fondo animado), sobre todo con un script que lo pausa al taparlo | Aunque esté en silencio abre una salida de audio; si se congela, PipeWire lo espera al reconectar los AirPods y **se atasca todo el audio** | Regla de PipeWire que lo desconecta del audio ([detalles](#antes-de-instalar-conflictos-de-audio-conocidos)) |
> | 🎛️ **EasyEffects** con "Procesar todas las salidas" | Captura el audio de cada app y lo fija a su salida: **el sonido no pasa solo a los AirPods** | Desactivar esa opción (los efectos del micrófono no cambian) |
> | 🎧 **[airpods-helper](https://github.com/superninjv/airpods-helper)** | Pausa y reanuda la música por su cuenta, a la vez que este proyecto | `pause_media = false` y `resume_media = false` en su configuración |
>
> **El instalador detecta los dos primeros y te pregunta si quieres que los corrija.** Todos se explican paso a paso en [Antes de instalar](#antes-de-instalar-conflictos-de-audio-conocidos).

> [!NOTE]
> Solo se ha probado a fondo con **AirPods Pro 3** en **Arch Linux + Hyprland + Noctalia**. Si algo falla en tu equipo, abre un *issue* con la salida de `airpodsctl status --json` y `journalctl --user -u airpodsd -n 50`.

## Qué hace

- **Batería al 1 %** del auricular izquierdo, del derecho y de la caja, con su estado de carga, detección en oreja y estado de la tapa.
- **Con la caja cerrada:** la caja sigue anunciando su estado cifrado durante minutos; con las claves de tus AirPods se descifra y se ve la batería en vivo.
- **Popup al abrir la caja**, en ~1 s: panel flotante en [Noctalia](https://github.com/noctalia-dev/noctalia) o notificación de escritorio en cualquier otro entorno.
- **Último estado conocido** con su antigüedad cuando no hay datos frescos ("visto hace 5 min"), nunca un dato viejo presentado como actual.
- **Sin escaneo continuo:** usa el monitor pasivo de anuncios de BlueZ, que no interfiere con tus otros dispositivos Bluetooth.
- `airpodsctl` para la terminal y una API D-Bus para integrarlo en otros widgets.
- **Pausa al quitarte un auricular** (cualquiera, también con el otro en la caja) y reanuda al volver a ponértelo, como en iOS.
- **Ajustes (⚙) en el panel y el popup:** nombre del dispositivo y actualizaciones.
- **Actualizaciones** con un comando o un clic, con aviso automático opcional (desactivado salvo que lo actives).
- Todo local: no usa la cuenta de iCloud, y solo se conecta a internet si activas la comprobación de actualizaciones.

## Compatibilidad

| | Estado |
|---|---|
| **AirPods Pro 3** | ✅ Probado a fondo |
| Otros AirPods / Beats | ⚠️ Sin probar. El anuncio de los auriculares es común a todos los modelos y probablemente funcione; el de la caja cerrada se ha verificado solo con el Pro 3 |
| Distribución | Desarrollado en **Arch Linux**. Debería funcionar en cualquier distro con systemd y BlueZ reciente |
| Escritorio | Cualquiera (notificación). Integración completa con **Noctalia**; animación del popup con **Hyprland** |

Cada instalación reconoce **solo los AirPods de su usuario**: `airpodsctl keys fetch` localiza los AirPods emparejados en tu equipo (si hay varios, te pide elegir) y guarda sus claves. Las direcciones Bluetooth no se usan para identificarlos, porque rotan cada pocos minutos: se reconocen criptográficamente. Por ahora se sigue **un par de AirPods** por usuario.

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

## Antes de instalar: conflictos de audio conocidos

Estos problemas los provocan otros programas al cambiar de dispositivo de audio. Aparecen justo al usar AirPods (que se conectan y desconectan a menudo), así que conviene resolverlos. El instalador comprueba los dos primeros y, si los encuentra, **te explica el problema y te pregunta** si quieres que los corrija (siempre con copia de seguridad o en un fichero aparte fácil de borrar).

### 🖼️ Linux Wallpaper Engine: el audio se atasca al reconectar los AirPods

**Síntoma:** al desconectar y reconectar los AirPods, el vídeo del navegador sigue unos segundos **sin sonido** y se queda **"cargando"**. Se arregla solo al cambiar de ventana, mover una ventana de monitor, cerrar otra aplicación o reiniciar el navegador.

**Causa:** `linux-wallpaperengine` abre una salida de audio **aunque esté en silencio** (`--volume 0` y `--silent` no la cierran). Si el fondo está congelado, por ejemplo por un script que lo pausa con `SIGSTOP` cuando las ventanas lo tapan, al crearse la salida nueva de los AirPods PipeWire espera a ese cliente congelado y **todo el audio de esa salida se queda parado** hasta que el fondo vuelve a moverse.

**Arreglo** (es lo que hace el instalador): una regla de PipeWire que impide que el audio del fondo se conecte a ninguna salida. No afecta a otras aplicaciones y la app del fondo no la deshace al actualizarse o reescribir su lanzador.

```sh
mkdir -p ~/.config/pipewire/client.conf.d
cat > ~/.config/pipewire/client.conf.d/50-airpods-linux-wallpaperengine.conf <<'EOF'
stream.rules = [
    {
        matches = [ { application.name = "linux-wallpaperengine" } ]
        actions = { update-props = { node.autoconnect = false } }
    }
]
EOF
```

Reinicia el fondo (o la sesión) para que se aplique. **Deshacer:** borra ese fichero. Si usas un fondo que reacciona a la música, perderá esa función.

### 🎛️ EasyEffects: el sonido no pasa solo a los AirPods

**Síntoma:** conectas los AirPods y el navegador sigue sonando por la salida anterior hasta que cambias la salida a mano.

**Causa:** con **"Procesar todas las salidas"** activado, EasyEffects captura el audio de cada aplicación y lo fija a su salida virtual.

**Arreglo:** en EasyEffects, *Preferencias → "Procesar todas las salidas"* → desactivado. Si solo usas EasyEffects para el micrófono, sus efectos siguen igual. El instalador lo hace por ti si EasyEffects está cerrado (en su configuración es `processAllOutputs=false` en la sección `[EffectsPipelines]`); si está abierto, te pide que lo cambies en su ventana, porque lo sobrescribiría.

Relacionado: si una aplicación sigue "pegada" a una salida concreta, que WirePlumber deje de recordarla hace que todas sigan a la salida por defecto:

```sh
wpctl settings --save node.stream.restore-target false     # deshacer: wpctl settings --delete node.stream.restore-target
```

### 🎧 airpods-helper: pausas duplicadas

Si usas [airpods-helper](https://github.com/superninjv/airpods-helper), tiene su propia pausa al quitarte los auriculares (solo con los dos). Para que no actúen los dos programas a la vez, en `~/.config/airpods-helper/config.toml`:

```toml
[ear_detection]
pause_media = false
resume_media = false
```

y reinicia `airpods-daemon`. El resto de airpods-helper (modo de escucha, ecualizador) sigue funcionando y `airpodsd` usa sus avisos de oreja para pausar al instante.

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
6. **Busca conflictos de audio conocidos** (Linux Wallpaper Engine, EasyEffects) y, si los encuentra, te explica el problema y te pregunta si quieres que los corrija. Ver [Antes de instalar](#antes-de-instalar-conflictos-de-audio-conocidos).
7. **Te pregunta si quieres activar la comprobación automática de actualizaciones** (ver [Actualizaciones](#actualizaciones)). Si respondes que no, o si no hay terminal interactiva, queda desactivada.

Opciones: `--no-service`, `--no-noctalia`, `--no-bluez`, `--auto-update y|n` (responde de antemano a la pregunta de actualizaciones), `--ref <rama|etiqueta>`, `--uninstall [--purge]`.

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
5. En Noctalia, añade el widget **AirPods** a tu barra (Ajustes → Barra). Pulsa el widget para abrir el panel, y el ⚙ para los ajustes.

Sin claves también funciona, pero con la batería en saltos de 10 %, sin datos con la caja cerrada y distinguiendo tus AirPods de los ajenos solo por cercanía.

## Uso

```sh
airpodsctl status [--json] [--scan SEG]   # estado actual o último conocido (--scan 0: solo caché)
airpodsctl watch [--json]                  # muestra cada cambio en vivo
airpodsctl keys fetch [MAC] | show         # claves de proximidad
airpodsctl rename "Mis AirPods"            # nombre en este equipo ('' = el original)
airpodsctl update [--check]                # busca una versión nueva e instala (--check: solo mira)
airpodsctl config get | set <opción> true|false   # update_check, ear_pause, ear_resume
systemctl --user status airpodsd          # el servicio
journalctl --user -u airpodsd -f          # sus logs (aperturas y cierres de la caja)
```

### Pausa automática al quitarte un auricular

Con los AirPods conectados a este equipo, `airpodsd` pausa lo que esté sonando (Spotify, el navegador, mpv… cualquier reproductor MPRIS) en cuanto te quitas **un** auricular. Vale igual si llevas los dos puestos que si llevas uno y el otro está en la caja.

- **Reanuda** si te vuelves a poner ese mismo auricular en menos de 2 minutos, o si lo guardas en la caja mientras sigues con el otro puesto. No reanuda si mientras tanto te quitas también el otro, ni reproduce nada que hubieras pausado tú.
- Si los AirPods están conectados a otro dispositivo (tu móvil), no toca la reproducción del equipo.
- **Detección:** combina dos fuentes. Con [airpods-helper](https://github.com/superninjv/airpods-helper) en marcha es instantánea (sus avisos de oreja por AAP). Los anuncios BLE, que tardan unos segundos, cubren los casos en que airpods-helper no informa (por ejemplo, con un auricular en la caja) y el uso sin airpods-helper.
- Se activa y desactiva en el ⚙ o con `airpodsctl config set ear_pause|ear_resume true|false`.
- Si usas airpods-helper, desactiva su propia pausa para que no actúen los dos: en `~/.config/airpods-helper/config.toml`, sección `[ear_detection]`, pon `pause_media = false` y `resume_media = false`, y reinicia `airpods-daemon`.

### Ajustes (⚙)

El panel de la barra y el popup tienen un botón ⚙. El popup no toma el teclado, así que su ⚙ abre el panel directamente en los ajustes. Desde ahí puedes:

- **Cambiar el nombre** del dispositivo. Es el nombre en *este* equipo (BlueZ): lo ven el popup, el panel y tu gestor de Bluetooth. El nombre guardado en los propios AirPods, el que ve tu iPhone, no cambia.
- **Activar o desactivar** la pausa y la reanudación automáticas.
- **Activar o desactivar** la comprobación automática de actualizaciones.
- **Buscar actualizaciones** ahora e instalar la nueva versión con un clic si la hay.

### Popup animado en Hyprland

Noctalia no anima sus paneles flotantes, pero Hyprland sí puede. En tu configuración Lua de Hyprland (probado con 0.56):

```lua
hl.layer_rule({ match = { namespace = "^noctalia-panel$" }, animation = "slide" })
```

Con `hyprland.conf`, usa la regla `layerrule` equivalente (ver la wiki de Hyprland). Afecta a todos los paneles de Noctalia: cada uno se desliza desde su borde más cercano, y el popup, desde abajo.

### Integración con otros widgets

- **D-Bus** (bus de sesión): `io.github.AirpodsLinux`, objeto `/io/github/AirpodsLinux`, interfaz `io.github.AirpodsLinux1`.
  - `GetState() → s` (JSON), `Reload()` (relee la configuración), `CheckUpdates()` (busca versión nueva; el resultado aparece en el campo `update` del estado)
  - Señales `StateChanged(s)`, `CaseOpened(s)` y `CaseClosed()`.
  ```sh
  busctl --user call io.github.AirpodsLinux /io/github/AirpodsLinux io.github.AirpodsLinux1 GetState
  ```
- **Fichero**: `$XDG_RUNTIME_DIR/airpods-linux/status.json`, con el mismo JSON y actualizado en cada cambio. Es útil para Waybar, eww, Quickshell…

Cada campo del JSON lleva `value`, `ts` (época Unix) y `source` (`ble-enc`, `ble-case` o `ble-clear`).

## Actualizaciones

- **Manual, en cualquier momento:** `airpodsctl update`, o el botón del ⚙. Descarga el instalador de la última release y se reinstala conservando tus ajustes, tus claves y la configuración del plugin.
- **Comprobación automática (opcional, desactivada por defecto):** el instalador te pregunta si quieres activarla. Con ella activa, `airpodsd` consulta una vez al día `api.github.com` (la última release de este repositorio) y, si hay una versión nueva, te avisa **una sola vez** con una notificación y con un aviso en el panel. Nunca instala nada sin que lo pidas.
  ```sh
  airpodsctl config set update_check true    # activar
  airpodsctl config set update_check false   # desactivar
  ```
- Si lo instalaste desde un clon de git para desarrollar, `airpodsctl update` no toca nada: actualiza con `git pull`.
- También puedes volver a ejecutar el instalador de una línea: siempre instala la última versión.

## Cómo funciona

Los AirPods anuncian por Bluetooth LE un mensaje *Proximity Pairing* de Apple con una parte en claro (batería en pasos de 10 %) y 16 bytes cifrados (batería al 1 %). La caja también anuncia su propio mensaje cifrado, incluso con la tapa cerrada. `airpodsctl keys fetch` pide a los AirPods, por el protocolo AAP (L2CAP 0x1001), su **IRK**, que sirve para reconocer sus direcciones aleatorias, y su **clave de cifrado**. Con ellas `airpodsd` identifica tus AirPods y descifra ambos anuncios. Detalles y capturas en [`docs/findings.md`](docs/findings.md).

## Privacidad y seguridad

- Las claves se guardan en `~/.config/airpods-linux/keys.json` con permisos `0600`. **No las compartas**: permiten reconocer tus AirPods.
- Sin telemetría. La única conexión a internet es la consulta de actualizaciones: una petición diaria a `api.github.com` solo si la activas, o cuando la pides tú. No envía ningún dato tuyo, aparte de lo que lleva cualquier petición HTTP (tu IP y la versión instalada en el User-Agent).
- Los logs no incluyen claves ni ubicaciones.
- Solo se procesan los anuncios de *tus* AirPods; los de otras personas se descartan.

## Solución de problemas

| Síntoma | Solución |
|---|---|
| `keys fetch`: "no enviaron las claves" | Otro programa ocupa el canal AAP (p. ej. `airpods-daemon`); páralo y reintenta. Los AirPods deben estar **conectados** |
| El popup tarda varios segundos | Activa `Experimental = true` en BlueZ; en el log de `airpodsd` debe poner `modo de escaneo: pasivo` |
| La batería de la caja sale `--` | Con la caja abierta y vacía en el cargador, la caja deja de anunciarse: ciérrala o mete un auricular |
| No aparece el popup | Comprueba `journalctl --user -u airpodsd` ("caja abierta…") y que el plugin esté activo: `noctalia msg plugins list` |
| El widget dice "airpodsd no está en ejecución" | `systemctl --user enable --now airpodsd` |
| Al conectar o desconectar los AirPods el vídeo se queda "cargando" sin sonido | Casi seguro es Linux Wallpaper Engine u otra app congelada con audio abierto: ver [Antes de instalar](#antes-de-instalar-conflictos-de-audio-conocidos) |
| Al conectar los AirPods el sonido sigue saliendo por otro sitio | EasyEffects o WirePlumber fijando la salida: ver [Antes de instalar](#antes-de-instalar-conflictos-de-audio-conocidos) |

## Desinstalar

```sh
~/.local/share/airpods-linux/src/uninstall.sh          # conserva claves y estado
~/.local/share/airpods-linux/src/uninstall.sh --purge  # lo borra todo
```

Borra el servicio, los comandos, el plugin de Noctalia, el programa, los logs y el estado en memoria, y al final lista lo que conserva. No revierte `Experimental = true` en BlueZ.

Para **actualizar o reparar** no hace falta desinstalar: el instalador detecta la versión que tienes ("Actualizando de la versión X a la Y"), para el servicio, rehace el entorno desde cero y vuelve a arrancarlo. Si algo falla, el registro completo está en `~/.cache/airpods-linux/install.log`.

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
