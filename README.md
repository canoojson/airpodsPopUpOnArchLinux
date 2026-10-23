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
> | 🔈 **PipeWire** (todos) | El audio de los AirPods acaba sonando **"a llamada"** (calidad baja) hasta desconectarlos | Regla de WirePlumber: AAC en calidad máxima constante |
> | 🎧 **[airpods-helper](https://github.com/superninjv/airpods-helper)** | Pausa y reanuda la música por su cuenta, a la vez que este proyecto | `pause_media = false` y `resume_media = false` en su configuración |
>
> **El instalador detecta los tres primeros y te pregunta si quieres que los corrija.** Todos se explican paso a paso en [Antes de instalar](#antes-de-instalar-conflictos-de-audio-conocidos).

> [!NOTE]
> Solo se ha probado a fondo con **AirPods Pro 3** en **Arch Linux + Hyprland + Noctalia**. Si algo falla en tu equipo, abre un *issue* con la salida de `airpodsctl report` y `journalctl --user -u airpodsd -n 50`.

## Qué hace

- **Batería al 1 %** del auricular izquierdo, del derecho y de la caja, con su estado de carga, detección en oreja y estado de la tapa.
- **Con la caja cerrada:** la caja sigue anunciando su estado cifrado durante minutos; con las claves de tus AirPods se descifra y se ve la batería en vivo.
- **Popup al abrir la caja**, en ~1 s: panel flotante en [Noctalia](https://github.com/noctalia-dev/noctalia) o notificación de escritorio en cualquier otro entorno.
- **Último estado conocido** con su antigüedad cuando no hay datos frescos ("visto hace 5 min"), nunca un dato viejo presentado como actual.
- **Sin escaneo continuo:** usa el monitor pasivo de anuncios de BlueZ, que no interfiere con tus otros dispositivos Bluetooth.
- `airpodsctl` para la terminal y una API D-Bus para integrarlo en otros widgets.
- **El audio pasa a los AirPods solo cuando te los pones**: aunque se conecten al abrir la caja, el sonido sigue por donde estaba hasta que te pones uno, y vuelve al quitártelos.
- **Cambio entre el iPhone y el PC**: al dar play en uno, los AirPods pasan a él y el otro se pausa.
- **Pausa al quitarte un auricular** (cualquiera, también con el otro en la caja) y reanuda al volver a ponértelo, como en iOS.
- **Modo de escucha y ajustes de los AirPods** (cancelación de ruido, adaptativo, ambiente, detección de conversación…) con su propia conexión AAP, sin depender de airpods-helper. Al hablar, baja el volumen como iOS.
- **Aviso de batería baja** al 20 % y al 10 %, y **historial** con gráfica de las últimas 24 h y el tiempo restante estimado.
- **Barras de estado**: salida para Waybar, Polybar y similares (`airpodsctl status --waybar`, `airpodsctl monitor`), y **extensiones para GNOME Shell y KDE Plasma**.
- **Ecualizador** de 10 bandas solo para los AirPods, con preajustes como los de iOS.
- **El iPhone y el PC a la vez** con AirPlay, si tienes UxPlay como receptor.
- **Ajustes (⚙) en el panel y el popup:** nombre del dispositivo, comportamiento y actualizaciones.
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

¿Lo has probado con otro modelo? Ejecuta `airpodsctl report`, abre la caja cerca del equipo mientras escucha y pega el resultado en un *issue*. El informe no incluye direcciones MAC, nombres de dispositivos, rutas de tu usuario ni la parte cifrada de los anuncios; aun así, revísalo antes de publicarlo.

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
- **[airpods-helper](https://github.com/superninjv/airpods-helper)**: ya no hace falta. `airpodsd` habla AAP por su cuenta; si airpods-helper está en marcha, le deja el canal AAP y el panel usa airpods-cli para el modo de escucha, como antes.

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

### 🔈 PipeWire: los AirPods suenan "a llamada"

**Síntoma:** el perfil sigue siendo de música (A2DP, AAC), pero de repente todo suena con calidad de llamada telefónica, y se arregla al desconectar y reconectar los AirPods.

**Causa:** en su modo por defecto, el codificador AAC de PipeWire baja el bitrate cuando el enlace Bluetooth tiene un problema puntual (una reconexión, interferencias, los AirPods conectados también al iPhone...) y puede no volver a subirlo.

**Arreglo** (es lo que hace el instalador): AAC en calidad máxima constante (VBR) para los auriculares de Apple, como hace el iPhone. Si el enlace va muy mal puede haber algún corte, en lugar de bajar la calidad.

```sh
mkdir -p ~/.config/wireplumber/wireplumber.conf.d
cat > ~/.config/wireplumber/wireplumber.conf.d/51-airpods-linux-aac.conf <<'EOF'
# airpods-linux: AAC de los AirPods (y demás auriculares de Apple) en VBR de máxima calidad.
# Con el modo por defecto (CBR) PipeWire baja el bitrate cuando el enlace Bluetooth
# tiene un problema puntual y puede no volver a subirlo: el audio suena "a llamada"
# hasta reconectar. En VBR no baja la calidad (como el iPhone). Bórralo para deshacerlo.
monitor.bluez.rules = [
  {
    matches = [ { device.name = "~bluez_card.*", device.vendor.id = "bluetooth:004c" } ]
    actions = { update-props = { bluez5.a2dp.aac.bitratemode = 5 } }
  }
]
EOF
systemctl --user restart wireplumber
```

**Deshacer:** borra ese fichero y reinicia WirePlumber.

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

**Arch Linux (AUR)**: `yay -S airpods-linux` (o `airpods-linux-git` para seguir `main`). Después, en tu usuario:

```sh
systemctl --user enable --now airpodsd
ln -s /usr/share/airpods-linux/noctalia/airpods ~/.local/share/noctalia/plugins/airpods   # si usas Noctalia
```

Con el paquete, las actualizaciones llegan por tu gestor de paquetes (`airpodsctl update` te lo recuerda). No lo mezcles con el instalador de abajo: este se niega a ejecutarse si detecta el paquete.

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
2. **Las claves**: con los AirPods conectados, `airpodsd` las obtiene solo por su conexión AAP la primera vez. Si usas **airpods-helper** (que ocupa ese canal), pídelas a mano una vez, con airpods-helper parado:
   ```sh
   systemctl --user stop airpods-daemon && airpodsctl keys fetch; systemctl --user start airpods-daemon
   ```
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
airpodsctl status --format '{left}% {right}%' | --waybar   # una línea para barras de estado
airpodsctl monitor [--format …|--waybar]   # una línea por cada cambio (barras con exec continuo)
airpodsctl watch [--json]                  # escanea por su cuenta y muestra cada cambio
airpodsctl mode [off|noise|transparency|adaptive]   # modo de escucha (sin argumento: el actual)
airpodsctl feature [ajuste] [valor]        # ajustes de los AirPods por AAP (sin argumentos: lista)
airpodsctl history [--hours 24]            # gráfica de batería y tiempo restante estimado
airpodsctl keys fetch [MAC] | show         # claves de proximidad
airpodsctl rename "Mis AirPods"            # nombre en este equipo ('' = el original)
airpodsctl update [--check]                # busca una versión nueva e instala (--check: solo mira)
airpodsctl config get | set <opción> true|false   # ver la tabla de opciones más abajo
airpodsctl eq [on|off|preset P|set BANDA dB|reset]   # ecualizador de los AirPods
airpodsctl airplay [0-150]                 # volumen del iPhone por AirPlay (UxPlay), aparte del resto
airpodsctl report [--scan 20] [-o FICHERO]  # informe anonimizado para abrir un issue
systemctl --user status airpodsd          # el servicio
journalctl --user -u airpodsd -f          # sus logs (aperturas y cierres de la caja)
```

Opciones de `airpodsctl config set` (todas menos `aap` también en el ⚙):

| Opción | Por defecto | Qué hace |
|---|---|---|
| `audio_follow_ear` | sí | El audio pasa a los AirPods solo al ponértelos |
| `ear_pause` / `ear_resume` | sí | Pausa al quitarte un auricular y reanuda al volver a ponértelo |
| `low_battery_alert` | sí | Aviso al 20 % y al 10 % |
| `aap` | sí | Conexión AAP propia (modos de escucha, ajustes, batería al instante) si airpods-helper no la usa. Solo por terminal |
| `conversation_duck` | sí | Bajar el volumen mientras hablas (con la detección de conversación activada) |
| `airplay_hint` | sí | Con UxPlay, recordar que por AirPlay suenan el iPhone y el PC a la vez |
| `update_check` | no | Buscar actualizaciones una vez al día |

### Modo de escucha y ajustes de los AirPods

Con los AirPods conectados a este equipo, `airpodsd` abre su propia conexión **AAP**, el protocolo que usa el iPhone. Con ella:

- **Modo de escucha**: cancelación de ruido, adaptativo, sonido ambiente o desactivado. Desde el panel de Noctalia o con `airpodsctl mode noise`. El panel solo ofrece los modos que tiene tu modelo, y los AirPods ignoran el cambio si no llevas ningún auricular puesto.
- **Detección de conversación**: interruptor en el panel o `airpodsctl feature conversational_awareness on`. Al empezar a hablar, los AirPods dejan pasar el sonido ambiente y `airpodsd` baja el volumen de los AirPods al 30 %. Al terminar, lo devuelve a su nivel, salvo que lo hayas cambiado a mano mientras tanto. **En llamadas** (Discord, Teams, el navegador… cualquier aplicación grabando de un micrófono), `airpodsd` la desactiva mientras dura y la vuelve a activar al colgar, como hace el iPhone: si no, los AirPods pasarían a sonido ambiente cada vez que hablas.
- **Otros ajustes** (`airpodsctl feature` los lista): nivel del modo adaptativo, cancelación con un solo auricular, volumen deslizando en el tallo, micrófono y volumen de los avisos sonoros.
- **Batería al 1 % y oreja al instante** mientras están conectados, sin esperar a los anuncios BLE.
- **Las claves de proximidad** se obtienen solas la primera vez.

Solo puede haber un programa con la conexión AAP. Si [airpods-helper](https://github.com/superninjv/airpods-helper) está en marcha, `airpodsd` se aparta y todo sigue como antes (el panel usa airpods-cli para el modo de escucha). Para que la use `airpodsd`: `systemctl --user disable --now airpods-daemon`. Para no usarla nunca: `airpodsctl config set aap false`.

> [!NOTE]
> Los formatos de AAP siguen la documentación de LibrePods. Los modos de escucha y la detección de conversación son los mismos que maneja airpods-helper; si algún ajuste no responde en tu modelo, abre un *issue* con la salida de `journalctl --user -u airpodsd` (con `airpodsd -v` se ven los paquetes sin interpretar).

### Ecualizador

Ecualizador de 10 bandas (de 32 Hz a 16 kHz, ±12 dB) que **solo afecta a los AirPods**: los altavoces y demás salidas suenan igual. Tiene un modo **sencillo** como el de iOS (graves, medios y agudos) y uno **avanzado** con preajustes como los de Música en iOS (más graves, menos graves, voces, acústica, electrónica, rock, sonoridad, nocturno…), uno **Lofi** para que se note el bombo, y ajuste por banda.

- En el panel de Noctalia: fila **Ecualizador** → interruptor, preajuste y una barra por banda.
- En la terminal:
  ```
  airpodsctl eq                      # estado y gráfica de las bandas
  airpodsctl eq on | off
  airpodsctl eq simple 6 -1 1       # modo sencillo: graves, medios y agudos
  airpodsctl eq preset lofi          # modo avanzado; sin nombre: lista de preajustes
  airpodsctl eq set 4k -3            # banda por índice (0-9) o frecuencia; pasa a "Personalizado"
  airpodsctl eq reset                # vuelve a plano
  ```

Funciona con un *filter-chain* de PipeWire que `airpodsd` lanza solo con los AirPods conectados y el ecualizador activado. Es un *smart filter* de WirePlumber (hace falta **WirePlumber 0.5** o posterior), que se coloca solo delante de la salida de los AirPods: la salida por defecto sigue siendo la de los AirPods y lo demás (el audio sigue a la oreja, bajar el volumen al hablar) no cambia. Los cambios se aplican al momento, sin cortes. Al subir una banda, el volumen general baja lo mismo para que no sature.

### Aviso de batería baja

Una notificación al bajar del **20 %** y otra, urgente, al bajar del **10 %**, una sola vez por carga. Para los auriculares solo avisa si están conectados a este equipo y fuera de la caja (si los usas con el móvil, avisa el móvil). Para la caja avisa siempre que la vea sin cargar. Se desactiva en el ⚙ o con `airpodsctl config set low_battery_alert false`.

### Historial de batería

`airpodsd` guarda la batería en `~/.local/state/airpods-linux/history.jsonl` cuando cambia, y como mínimo cada 10 minutos mientras recibe datos. Conserva 30 días. El panel de Noctalia muestra la gráfica de las últimas 24 h y, cuando hay suficientes datos de la sesión actual, **cuánto te queda** al ritmo de descarga actual. En la terminal:

```
$ airpodsctl history
Últimas 24 h (cada columna ≈ 30 min)
  Izquierdo  ████▇▇▆▆▅▅▄▄           ███████▇▇▆ 62 %
  Derecho    ████▇▇▆▆▅▄▄▃           ███████▇▇▆ 60 %
  Caja       ▆▆▆▆▆▆▆▆▆▆▆▆▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅▅ 71 %
  Al ritmo actual, al izquierdo le quedan unas 3 h 10 min
```

### Waybar y otras barras

`airpodsctl status --waybar` imprime el JSON de un módulo `custom` de Waybar (texto, *tooltip* con las tres baterías, `percentage` y clases `low`, `charging`, `stale`, `connected`). `airpodsctl monitor --waybar` hace lo mismo de forma continua, escuchando a `airpodsd` por D-Bus, así que se actualiza al instante sin sondear:

```jsonc
"custom/airpods": {
    "exec": "airpodsctl monitor --waybar --format '{left}% {right}%'",
    "return-type": "json",
    "format": "󰋋 {}",
    "on-click": "airpodsctl mode noise"
}
```

Para Polybar, i3blocks, yambar… usa `--format` sin `--waybar`: `airpodsctl monitor --format '{name} {min}%'`. Marcadores: `{left}` `{right}` `{case}` `{min}` (el auricular más bajo de los puestos), `{left_chg}` `{right_chg}` `{case_chg}` (⚡ si cargan), `{name}`, `{mode}` y `{ago}`.

### Pausa automática al quitarte un auricular

Con los AirPods conectados a este equipo, `airpodsd` pausa lo que esté sonando (Spotify, el navegador, mpv… cualquier reproductor MPRIS) en cuanto te quitas **un** auricular. Vale igual si llevas los dos puestos que si llevas uno y el otro está en la caja.

- **Reanuda** si te vuelves a poner ese mismo auricular en menos de 2 minutos, o si lo guardas en la caja mientras sigues con el otro puesto. No reanuda si mientras tanto te quitas también el otro, ni reproduce nada que hubieras pausado tú.
- Si los AirPods están conectados a otro dispositivo (tu móvil), no toca la reproducción del equipo.
- **Detección:** combina dos fuentes. Por AAP (la conexión propia de `airpodsd` o la de [airpods-helper](https://github.com/superninjv/airpods-helper)) es instantánea. Los anuncios BLE, que tardan unos segundos, cubren los casos en que AAP no informa (por ejemplo, con un auricular en la caja) y el uso sin conexión.
- Se activa y desactiva en el ⚙ o con `airpodsctl config set ear_pause|ear_resume true|false`.
- Si usas airpods-helper, desactiva su propia pausa para que no actúen los dos: en `~/.config/airpods-helper/config.toml`, sección `[ear_detection]`, pon `pause_media = false` y `resume_media = false`, y reinicia `airpods-daemon`.

### El audio sigue a tus orejas

Al abrir la caja, los AirPods se conectan solos al último dispositivo (es cosa de los AirPods, igual que con el iPhone) y Linux les manda el sonido aunque sigan en la caja. `airpodsd` lo corrige como iOS:

- Si se conectan **sin ningún auricular puesto**, el sonido vuelve a la salida que estabas usando (altavoces, HDMI…).
- Al **ponerte el primero**, el sonido pasa a los AirPods.
- Al **quitarte el último** o guardarlo en la caja, vuelve a la salida anterior.

Solo actúa en esos momentos, así que si eliges otra salida a mano, se respeta. Cambia la salida por defecto con `pactl` (paquete `libpulse`, que instala `pipewire-pulse`; sin él esta función se desactiva sola): las aplicaciones la siguen salvo que tengan una salida fijada (ver [conflictos de audio](#antes-de-instalar-conflictos-de-audio-conocidos)). Se desactiva en el ⚙ o con `airpodsctl config set audio_follow_ear false`.

### Cambiar entre el iPhone y el PC

Los AirPods solo mandan el audio a un dispositivo a la vez. `airpodsd` hace el cambio como iOS entre dispositivos de Apple:

- **Le das a play en el iPhone** y este se lleva los AirPods: el PC pausa lo que sonaba por ellos (y el sonido no salta a los altavoces). Al volver, dale a play: no se reanuda solo.
- **Le das a play en el PC** con los AirPods puestos pero conectados a otro dispositivo: `airpodsd` los conecta a este equipo.

#### El iPhone y el PC a la vez (AirPlay con UxPlay)

Si tienes [UxPlay](https://github.com/FDH2/UxPlay) como receptor AirPlay en el PC, puedes oír los dos a la vez: en el iPhone, manda el audio por AirPlay al PC. Los AirPods se quedan conectados al PC, que mezcla el sonido del iPhone con el suyo.

- Mientras suena el iPhone por AirPlay, el panel muestra qué suena y un **control de volumen solo para el iPhone**, sin tocar el del resto. También desde la terminal: `airpodsctl airplay 60`.
- Si el iPhone se lleva los AirPods con el PC sonando y UxPlay en marcha, `airpodsd` te recuerda esta opción con una notificación, como mucho una vez al día. Se desactiva en el ⚙ o con `airpodsctl config set airplay_hint false`.
- `airpodsd` reconoce UxPlay por su interfaz MPRIS (`org.mpris.MediaPlayer2.uxplay`) y su flujo de audio en PipeWire. Sin UxPlay, todo esto no aparece.

### Ajustes (⚙)

El panel de la barra y el popup tienen un botón ⚙. El popup no toma el teclado, así que su ⚙ abre el panel directamente en los ajustes. Desde ahí puedes:

- **Cambiar el nombre** del dispositivo. Es el nombre en *este* equipo (BlueZ): lo ven el popup, el panel y tu gestor de Bluetooth. El nombre guardado en los propios AirPods, el que ve tu iPhone, no cambia.
- **Activar o desactivar** que el audio pase a los AirPods solo al ponértelos.
- **Activar o desactivar** la pausa y la reanudación automáticas, el aviso de batería baja, y la bajada de volumen al hablar.
- **Ajustes de los propios AirPods** (con la conexión AAP de `airpodsd`): cancelación con un solo auricular y volumen deslizando en el tallo.
- **Activar o desactivar** la comprobación automática de actualizaciones.
- **Buscar actualizaciones** ahora e instalar la nueva versión con un clic si la hay.

### Popup animado en Hyprland

Noctalia no anima sus paneles flotantes, pero Hyprland sí puede. En tu configuración Lua de Hyprland (probado con 0.56):

```lua
hl.layer_rule({ match = { namespace = "^noctalia-panel$" }, animation = "slide" })
```

Con `hyprland.conf`, usa la regla `layerrule` equivalente (ver la wiki de Hyprland). Afecta a todos los paneles de Noctalia: cada uno se desliza desde su borde más cercano, y el popup, desde abajo.

### GNOME Shell y KDE Plasma

`install.sh` instala también, si detecta el escritorio, un indicador para la barra con la batería del auricular más bajo. Al pulsarlo se ven las tres baterías, el modo de escucha, la detección de conversación y un botón para conectar los AirPods. Los dos son clientes de `airpodsd`, que tiene que estar en marcha.

- **GNOME Shell** 45 o posterior: extensión `airpods-linux@canoojson.github.io`. GNOME carga las extensiones nuevas al iniciar sesión: tras instalar, cierra sesión y entra de nuevo, o actívala con `gnome-extensions enable airpods-linux@canoojson.github.io`.
- **KDE Plasma 6**: plasmoide `io.github.airpodslinux`. Añádelo al panel con clic derecho → *Añadir o gestionar elementos gráficos* → *AirPods*.

Para no instalarlos: `./install.sh --no-gnome --no-kde`. El popup al abrir la caja sigue siendo una notificación de escritorio en estos entornos.

### Integración con otros widgets

- **D-Bus** (bus de sesión): `io.github.AirpodsLinux`, objeto `/io/github/AirpodsLinux`, interfaz `io.github.AirpodsLinux1`.
  - `GetState() → s` (JSON), `Reload()` (relee la configuración), `CheckUpdates()` (busca versión nueva; el resultado aparece en el campo `update` del estado)
  - `SetSetting(s nombre, s valor)` (ajuste de los AirPods por AAP; nombres en `airpodsctl feature`) y `FetchKeys() → b` (pide las claves por la conexión AAP)
  - Señales `StateChanged(s)`, `CaseOpened(s)` y `CaseClosed()`.
  ```sh
  busctl --user call io.github.AirpodsLinux /io/github/AirpodsLinux io.github.AirpodsLinux1 GetState
  ```
- **Fichero**: `$XDG_RUNTIME_DIR/airpods-linux/status.json`, con el mismo JSON y actualizado en cada cambio. Es útil para Waybar, eww, Quickshell…

Cada campo del JSON lleva `value`, `ts` (época Unix) y `source` (`ble-enc`, `ble-case`, `ble-clear` o `aap`). Además: `aap` (conexión, quién la tiene, ajustes de los AirPods y modos disponibles), `history` (series de 24 h y minutos restantes estimados) y `alerts`.

## Actualizaciones

- **Manual, en cualquier momento:** `airpodsctl update`, o el botón del ⚙. Descarga el instalador de la última release y se reinstala conservando tus ajustes, tus claves y la configuración del plugin.
- **Comprobación automática (opcional, desactivada por defecto):** el instalador te pregunta si quieres activarla. Con ella activa, `airpodsd` consulta una vez al día `api.github.com` (la última release de este repositorio) y, si hay una versión nueva, te avisa **una sola vez** con una notificación y con un aviso en el panel. Nunca instala nada sin que lo pidas.
  ```sh
  airpodsctl config set update_check true    # activar
  airpodsctl config set update_check false   # desactivar
  ```
- Si lo instalaste desde un clon de git para desarrollar, `airpodsctl update` no toca nada: actualiza con `git pull`. Con el paquete de AUR, actualiza con tu gestor de paquetes.
- También puedes volver a ejecutar el instalador de una línea: siempre instala la última versión.

## Cómo funciona

Los AirPods anuncian por Bluetooth LE un mensaje *Proximity Pairing* de Apple con una parte en claro (batería en pasos de 10 %) y 16 bytes cifrados (batería al 1 %). La caja también anuncia su propio mensaje cifrado, incluso con la tapa cerrada. `airpodsctl keys fetch` pide a los AirPods, por el protocolo AAP (L2CAP 0x1001), su **IRK**, que sirve para reconocer sus direcciones aleatorias, y su **clave de cifrado**. Con ellas `airpodsd` identifica tus AirPods y descifra ambos anuncios. Con los AirPods conectados, esa misma conexión AAP queda abierta para leer la batería y la oreja al instante y cambiar el modo de escucha y otros ajustes. Detalles y capturas en [`docs/findings.md`](docs/findings.md).

## Privacidad y seguridad

- Las claves se guardan en `~/.config/airpods-linux/keys.json` con permisos `0600`. **No las compartas**: permiten reconocer tus AirPods.
- Sin telemetría. La única conexión a internet es la consulta de actualizaciones: una petición diaria a `api.github.com` solo si la activas, o cuando la pides tú. No envía ningún dato tuyo, aparte de lo que lleva cualquier petición HTTP (tu IP y la versión instalada en el User-Agent).
- Los logs no incluyen claves ni ubicaciones.
- Solo se procesan los anuncios de *tus* AirPods; los de otras personas se descartan.

## Solución de problemas

| Síntoma | Solución |
|---|---|
| `keys fetch`: "no enviaron las claves" | Otro programa ocupa el canal AAP (p. ej. `airpods-daemon`); páralo y reintenta. Los AirPods deben estar **conectados** |
| `airpodsctl mode`: "sin conexión AAP" | Los AirPods no están conectados a este equipo, o airpods-helper tiene el canal (entonces usa `airpods-cli`). En el log: `AAP: conectado a …` |
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

- `src/airpods_linux/`: parser, cifrado, estado, escáner, daemon (`daemon/`, un controlador por área) y CLI.
- `integrations/`: el plugin de Noctalia, la extensión de GNOME Shell y el plasmoide de KDE Plasma.
- `tools/`: herramientas de captura de la fase de investigación y `i18n_extract.py`.
- `fixtures/`: capturas reales, solo con anuncios propios. `tests/test_fixtures_replay.py` las reproduce por el mismo camino que `airpodsd`, sin claves, también en CI.
- `packaging/aur/`: los PKGBUILD de `airpods-linux` y `airpods-linux-git`.

**Idiomas:** el texto original está en castellano; con cualquier otro idioma se usa el inglés. Los textos de Python se marcan con `_()` y se traducen en `src/airpods_linux/locale/en.po` (`tools/i18n_extract.py` lo actualiza y dice qué falta). Los del panel de Noctalia van con `T()` y se traducen en `integrations/noctalia/airpods/translations/en.json`; `es.json` repite las claves, porque Noctalia carga siempre `en.json`. Los logs de `airpodsd` no se traducen.

Las releases se publican al subir una etiqueta `vX.Y.Z` (GitHub Actions). Si el repositorio tiene el secreto `AUR_SSH_PRIVATE_KEY`, el mismo workflow actualiza el paquete de AUR.

## Licencia y créditos

[GPL-3.0-or-later](LICENSE). Si publicas una versión modificada, debe llevar su código fuente bajo la misma licencia y conservar los créditos. Si mejoras algo, se agradece un *pull request*.

La interpretación del protocolo se basa en la documentación de [LibrePods](https://github.com/kavishdevar/librepods) y otros proyectos; ver [CREDITS.md](CREDITS.md). No afiliado a Apple.
