# Fase 0: hallazgos con hardware

> Cuaderno de laboratorio de la ingeniería inversa con unos AirPods Pro 3 reales. "La spec" es el documento de investigación inicial del que partió el proyecto (no incluido). Las direcciones y claves del autor se han omitido.

Fecha: 2026-09-29. Capturas en `fixtures/*.jsonl` (una línea por anuncio visto, bytes sin el prefijo `4C 00`).

## 1. Pila Bluetooth

| Elemento | Valor |
|---|---|
| Distro / kernel | Arch Linux, 7.2.7-arch1-1 |
| BlueZ | 5.87 (`bluez`, `bluez-utils`) |
| Adaptador | hci0, USB (`usb:v1D6Bp0246`), roles central + peripheral |
| `btmon` / `btmgmt` | Disponibles, requieren root (sin sudo sin contraseña) |
| Python | 3.14.7, `dbus-python` y `gi` instalados; `bleak` y `dbus-next` no |
| Otros | `airpods-helper` 0.2.2 instalado, `airpods-daemon.service` activo (usuario); `blueman-applet` activo |

AirPods emparejados: `XX:XX:XX:XX:XX:XX` (dirección de los AirPods, omitida), dirección **pública**, bonded (BR/EDR).
Modalias `bluetooth:v004Cp2027d215C` → **product ID 0x2027** (la spec citaba `0x2720`: probablemente el mismo valor con los bytes invertidos). **[VERIFICAR]** contra el campo de modelo del anuncio 0x07.

Captura sin root: `tools/capture.py` usa D-Bus de BlueZ (`SetDiscoveryFilter` LE + `DuplicateData`). BlueZ solo señala `ManufacturerData` cuando cambia; los cambios de RSSI marcan cada anuncio recibido. Para verdad a nivel HCI: `sudo btmon -w fixtures/<caso>.btsnoop` en paralelo.

## 2. Primeras observaciones (estado de los AirPods sin anotar)

- Aparece un anuncio `0x07` **corto**, longitud `0x11` (17 bytes), no `0x19`:
  `07 11 06 35 f6 69 a4 e1 07 56 c2 09 65 0c 49 46 1e 0d 18` (dir. C8:09:83:9B:F9:FD, RSSI −49/−58).
  El byte 2 es `0x06`, no `0x01`/`0x00`; bytes 3+ cambian entre direcciones → parecen cifrados. No encaja con la tabla de la spec.
- Frecuencia muy baja: 1-2 eventos en 10-30 s.
- Muchos `0x12` (Find My / offline finding) y `0x10` (Nearby Info) de otros dispositivos alrededor.

## 3. Escenarios

| # | Escenario | Fichero | Resultado |
|---|---|---|---|
| 1 | Caja abierta, auriculares dentro | `1_caja_abierta_dentro.jsonl` | Formato largo `0x19`. Dos direcciones (una por auricular). Ver §4 |
| 2 | Derecho fuera, caja abierta | `2_derecho_fuera.jsonl` | Ver §5 |
| 3 | Ambos en oreja, caja abierta | `3_ambos_oreja_caja_abierta.jsonl` | Solo emite el derecho. Ver §6 |
| 4 | Caja cerrada en reposo (10 min) + otra habitación (3 min) | `4_cerrada_reposo.jsonl`, `4b_cerrada_otra_habitacion.jsonl` | Anuncio corto confirmado como de la caja. Ver §8 |
| 5 | Caja cerrada tras uso (22:36) | `5_cerrada_tras_uso.jsonl` | Formato largo hasta ~2 s después de cerrar; luego solo el corto. Ver §7 |
| 6 | Caja abierta, vacía | `6_caja_abierta_vacia.jsonl` | La batería de la caja no está disponible. Ver §9 |

## 4. Escenario 1: caja abierta, auriculares dentro

Anuncios completos (27 bytes), cada ~5-10 s por dirección, RSSI ≈ −50:

```
5E:1E:A0:3C:B3:7F  07 19 01 2720 15 aa b8 31 00 04 | e4cb9c679b6d2809e66d6a4f2e7be13b
41:F3:12:4D:44:FC  07 19 01 2720 75 aa b8 31 00 04 | b9e7dea9570419f052c2eb9042419947
```

- **Emiten los dos auriculares**, cada uno con su dirección aleatoria. Solo se diferencian en el byte de estado: `0x15` frente a `0x75` (bits 6 "este auricular en la caja" y 5 "primario").
- Modelo en bytes 3-4: `27 20` → **little-endian 0x2027**, coincide con el modalias. Los offsets de la spec (sin `4C 00`) son correctos con BlueZ.
- Byte 6 `aa`: L = R = 100 % (iPhone: 100/100 ✔). Byte 7 `b8`: ver §5, los nibbles están al revés que en la spec.
- Byte 8 `31`: contador de aperturas = 1, bit 3 = 0 con la tapa abierta. Bits altos `0x3` sin documentar.
- Byte 9 `00` (color), byte 10 `04` (idle).
- Los 16 bytes cifrados cambian entre anuncios del mismo auricular.
- Sigue apareciendo el anuncio corto `07 11 06 …` desde otra dirección (DC:DD:C1:F4:2A:20). Origen desconocido: ¿la caja o algún otro dispositivo Apple?

## 5. Escenario 2: auricular derecho fuera, caja abierta

Referencia iPhone: L 100 %, R 100 %, caja 85 %, caja sin cargar.

```
                         st  bat b7  b8
5E:1E:A0:3C:B3:7F  caso1 15  aa  b8  31
                   caso2 11  aa  a8  11     <- derecho (el que salió)
41:F3:12:4D:44:FC  caso1 75  aa  b8  31
                   caso2 71  aa  98  31     <- izquierdo (sigue en la caja)
```

**Byte 7: la spec tiene los nibbles al revés** (coincide con la implementación de LibrePods):
- Nibble **bajo** = batería de la caja: `0x8` → 80 % (iPhone 85 %, la resolución es de 10 %).
- Nibble **alto** = flags de carga. `0xB` = `1011`: bits 0 y 1 = los dos auriculares cargando, bit 2 = 0 (caja sin cargar ✔), bit 3 siempre 1 (desconocido). Al sacar el derecho se apaga su bit de carga, que es el 0 o el 1 según el punto de vista del emisor.

**Byte de estado (5):** el bit 2 ("ambos en la caja") se apaga en los dos emisores ✔. Los bits 5 y 6 solo aparecen en el izquierdo (41:F3…), así que marcan "este es el izquierdo/primario" y no "este auricular está en la caja". El bit 0 está siempre a 1. **[VERIFICAR]** con los casos 3 y 4.

**Byte 8:** en el derecho pasa de `0x31` a `0x11` al salir. El bit 5 parece "este auricular en la caja", y los bits 0-2 son el contador de aperturas (1).

## 6. Escenario 3: ambos en la oreja, caja abierta

`Connected: yes` en BlueZ, aunque sin audio sonando. **Solo emite 5E:1E… (derecho)**; el izquierdo deja de anunciarse.

```
5E:1E:A0:3C:B3:7F  07 19 01 2720 0b aa 8f 11 00 04
```

- Estado `0x0b` = `0000 1011`: se apagan los bits 2 y 4 (ninguno en la caja) ✔ y se encienden los bits 0, 1 y 3 (detección en oreja) ✔.
- Byte 7 `8f`: flags `1000` (nada carga) ✔; batería de la caja `0xF` = **no disponible** con los dos auriculares fuera ✔.
- Byte 10 = `04` (idle) aunque haya conexión clásica; no refleja el estado de conexión con *este* host.

## 7. Escenario 5: caja cerrada tras el uso

El usuario mete los dos auriculares y cierra la caja a las 22:36. Captura de 22:35:33 a 22:40:33.

| Hora | Emisor | Anuncio (cabecera) | Lectura |
|---|---|---|---|
| 22:35:33-52 | derecho | `0b aa 8f 11` | aún en oreja |
| 22:36:03-07 | ambos | `75/15 aa b8 32` | en la caja, tapa abierta, contador de aperturas = 2 |
| 22:36:10-12 | ambos | `75/15 aa b8 3a` | **tapa cerrada: bit 3 del byte 8 = 1** ✔ |
| 22:36:12 | | último anuncio largo | |
| 22:36:12-22:38:19 | | nada (~2 min) | |
| 22:38:19-22:40:25 | FC:CA:25:6F:9A:85 | corto `07 11 06 22a6dc…` | 13 eventos, RSSI −45…−60, payload constante |

Conclusiones:
- **Tras cerrar la tapa llegan entre 2 y 3 anuncios largos en ~2 s, con el bit de tapa cerrada y las baterías.** Es el "último estado conocido" que hay que capturar.
- Después ya no hay batería legible. El anuncio corto `07 11` (17 bytes, byte 2 = `0x06`, resto opaco y constante para cada dirección) aparece ~2 min más tarde con RSSI de "muy cerca". Confirmado en §8 que viene de la caja cerrada. El del escenario 1 (DC:DD…) **también era de nuestra caja**: se descifra con nuestra clave (§11).
- BlueZ se quedó en `Connected: no` al cerrar.
- El contador de aperturas (bits 0-2 del byte 8) subió de 1 a 2 al volver a meter los auriculares.

## 8. Escenario 4: caja cerrada en reposo, y prueba de alejamiento

Captura de 10 min (22:40:40-22:50:40) sin tocar la caja, y luego 3 min con la caja en otra habitación (22:50:5x-22:53:5x).

| Hora | Dirección | Payload corto | RSSI |
|---|---|---|---|
| 22:38:19-22:41:15 | FC:CA:25:6F:9A:85 | `07 11 06 22a6dc…` | −44…−60 |
| 22:41-22:45 | — | nada | |
| 22:45:00-22:50:01 | CB:C9:60:F3:4E:2C | `07 11 06 da3519…` | −44…−64 |
| 22:51:15-22:52:23 (otra habitación) | CB:C9:60:F3:4E:2C | `07 11 06 da3519…` | **−76…−85** |

- **La prueba de alejamiento confirma que el anuncio corto es de la caja:** la misma dirección y el mismo payload bajan ~25 dB al llevarla a otra habitación. Los Momentum 4 (conectados por BR/EDR, dirección pública) no aparecen en ninguna captura de `0x004C`.
- La caja cerrada **sigue emitiendo al menos 17 min después de cerrarla**, de forma intermitente: huecos de 10-75 s y un silencio de ~4 min. **[VERIFICAR]** con `btmon`, porque BlueZ solo avisa cuando cambian el RSSI o los datos.
- La dirección y el payload rotan juntos (22:41→22:45). El payload corto no lleva batería legible. Sirve para saber que la caja está "presente/cerca" y poco más, y para asociarlo a nuestros AirPods hace falta el IRK.

## 9. Escenario 6: caja abierta sin auriculares

```
6A:F1:C9:0E:05:48  07 19 01 2720 01 aa 8f 11 00 04     (un auricular, fuera, no en oreja)
CB:C9:60:F3:4E:2C  07 11 06 0b74673c…                  (corto, RSSI −37…−43, hasta 22:56:21)
```

- Con la caja vacía, **la batería de la caja no se puede leer** (`0xF`). Parece que la batería de la caja solo llega a través del anuncio de un auricular que esté dentro.
- Solo emite un auricular (el primario), con estado `0x01`: fuera de la caja y no en la oreja.
- La dirección del anuncio corto es **la misma** que en el escenario 4, pero el **payload ha cambiado** (`da3519…` → `0b7467…`). Así que el payload corto no depende solo de la rotación de dirección: cambia también con el estado (tapa y/o auriculares). Esto refuerza la hipótesis de que lo emite **la propia caja**. **[VERIFICAR]**

## 9b. Escenario 7: caja abierta y vacía, enchufada al cargador

El usuario enchufa la caja a las **23:02:40** (hora anotada por él). El iPhone la muestra cargando.

```
23:02:35  D9:3E:90:6F:65:6E  07 11 06 2186257f…   (corto, caja)
23:02:37  D9:3E:90:6F:65:6E  07 11 06 c3591ef2…   <- cambia
23:02:40  D9:3E:90:6F:65:6E  07 11 06 34c83769…   <- cambia al enchufar
23:02:40-23:03:15  estable
23:03:16  D9:3E:90:6F:65:6E  07 11 06 806eec78…   <- cambia de nuevo sin acción del usuario
6A:F1:C9:0E:05:48  07 19 01 2720 01 aa 8f 11 00 04   (auricular, sin cambios en todo momento)
```

- **El payload corto de la caja cambia justo al enchufarla, sin cambiar de dirección.** El anuncio del auricular no cambia (caja `0xF`, sin flags de carga).
- Por tanto, **la caja emite su propio estado (probablemente batería y carga) cifrado en el anuncio corto**, y de ahí lo saca el iPhone. En reposo el payload se mantenía constante durante minutos, así que los cambios corresponden a eventos.
- El iPhone pasó de 85 % a 86 % durante la carga (según recuerda el usuario, sin hora exacta). Descifrado (§11): el cambio de las 23:03:16 **no** es la batería (sigue en 85 %); es un contador.
- Vía a investigar: las claves de proximidad que LibrePods obtiene por AAP (IRK + clave de cifrado) podrían servir para descifrar este anuncio. Si fuera así, habría batería de la caja con la tapa cerrada.

## 10. Conclusiones para el diseño

1. **Offsets** (bytes de BlueZ sin `4C 00`): los de la spec son válidos, con estas correcciones:
   - Modelo en bytes 3-4, **little-endian**: `0x2027` = AirPods Pro 3 (coincide con el modalias).
   - Byte 7: **nibble bajo = batería de la caja, nibble alto = flags de carga** (la spec los tenía al revés).
   - Byte 8: bits 0-2 = contador de aperturas, bit 3 = tapa cerrada, bit 5 ≈ "este auricular en la caja", bit 4 siempre a 1.
   - Byte 5: bit 2 = ambos en la caja, bit 4 = alguno en la caja, bits 0/1/3 = oreja. El significado exacto de los bits 5-6 (primario/izquierdo) sigue pendiente.
2. **Con la caja cerrada no hay batería en vivo.** Hay que guardar el último anuncio largo (llega ~2 s después de cerrar, con el bit de tapa) como "último estado conocido" con timestamp.
3. **Presencia con la caja cerrada:** el anuncio corto `07 11 06 …` dura ≥17 min, con RSSI útil para saber si la caja está cerca. No lleva batería. Para atribuirlo a *nuestra* caja hace falta el IRK (no se puede asociar por la dirección, que rota) o una heurística (proximidad temporal con el último anuncio largo + RSSI).
4. **Batería de la caja:** solo se conoce si hay al menos un auricular dentro; si no, hay que mostrar la última conocida.
5. **Identificación:** cada auricular emite con su propia dirección, que rota. Sin el IRK, filtrar por modelo `0x2027` + RSSI. Hay AirPods ajenos cerca (DC:DD… con RSSI −72…−84), así que el filtro es necesario.
6. **Pendiente:** capturas con `btmon` (root) para medir intervalos reales; leer el IRK desde `/var/lib/bluetooth/` (root) si los AirPods tienen claves LE; confirmar el bit de "caja cargando" con la caja en el cargador.

## 11. Spike AAP: claves de proximidad y descifrado ✅

`airpodsctl keys fetch` (antes `tools/aap_keys.py`) abre L2CAP PSM `0x1001`, envía el handshake y la petición `04 00 04 00 30 00 05 00`. Tras varios paquetes de estado (opcodes 0x2b, 0x0c, 0x02, 0x1d, 0x09…, 0x53) llega la respuesta `0x31` con **IRK** (tipo 0x01) y **ENC_KEY** (tipo 0x04), de 16 bytes cada una. Se guardan en `~/.config/airpods-linux/keys.json` (0600, fuera del repo).

- **`airpods-daemon` (airpods-helper) bloquea el canal:** con él activo se abre el socket pero no hay respuesta. Hubo que pararlo unos segundos. Las claves no cambian, así que basta con pedirlas una vez.
- `tools/decrypt_fixtures.py`: AES-128-ECB de los 16 bytes finales con la ENC_KEY tal cual. Las direcciones de los auriculares se resuelven con la **IRK invertida** (byte order little-endian).

### Anuncio largo (auriculares), descifrado

```
04 e4 e4 55 d3 2f 51 e2 8f 60 00 01 64 a7 8e a4
   │  │  └ caja: 0x55 = 85 % (iPhone 85 % ✔), bit 7 = cargando, 0xff = no disponible
   │  └ auricular 2 ┐ bit 7 = cargando, bits 0-6 = %, 0x7f/0xff = no disponible
   └ auricular 1 ┘  orden según primario (como LibrePods)
```

Batería con **resolución de 1 %**, frente a 10 % en la parte en claro.

### Anuncio corto (caja) ‒ ¡también se descifra con la misma ENC_KEY!

```
29 20 08 55 e4 e4 5a 86 00 00 00 00 6a 02 00 00     caja cerrada, auriculares dentro
29 20 01 55 ff ff 5a 86 00 00 00 00 fa 04 00 00     caja abierta, vacía
29 20 02 d5 ff ff 5a 86 00 00 00 00 8e 06 00 00     caja vacía, enchufada
│     │  │  └──┴ auriculares (100 % cargando / no disponible)
│     │  └ caja: bit 7 = cargando, bits 0-6 = %  → 0xd5 = 85 % cargando ✔
│     └ flags de estado: 00 abierta+dentro, 08 cerrada+dentro, 01 abierta vacía, 09 ¿cerrada vacía?, 02 ¿vacía en carga?  [VERIFICAR]
└ constante 0x2029 (¿ID de modelo de la caja?)
```

- **Esto resuelve la prioridad nº 1: batería de caja y auriculares con la caja cerrada, en vivo**, cada 10-60 s durante ≥17 min (y quizá indefinidamente).
- Las direcciones del anuncio corto **no** se resuelven con la IRK de los auriculares (la caja tiene su propia IRK). Para identificarlo sirve el propio descifrado: si con nuestra ENC_KEY sale la cabecera `29 20 … 5a 86`, es nuestra caja.
- Bytes 12-13: contador o nonce (cambia sin cambio de estado, p. ej. a las 23:03:16).
- El DC:DD… del escenario 1 era nuestra caja, con la tapa abierta (flags `00`).
- **Licencia:** LibrePods es GPLv3. Aquí solo se ha usado la *descripción del protocolo*; el código es propio.

## 12. Escenario 8: caja vacía en carga, se cierra la tapa (23:22-23:24)

Durante ~10 min con la caja abierta, vacía y en carga (97-98 %) **no hubo ningún anuncio de la caja**: parece que deja de anunciarse en ese estado. Al cerrar la tapa vuelve a emitir de inmediato, y con frecuencia alta (varios por segundo al principio).

Secuencia descifrada (misma dirección C2:99:1E:FC:71:CB):

| Hora | flags | Caja | Auriculares |
|---|---|---|---|
| 23:22:59 | `0x0a` | 98 % ⚡ | — |
| 23:23:02 | `0x03` | 98 % ⚡ | — |
| 23:23:05 | `0x03` | 98 % | R 100 % ⚡ |
| 23:23:05-24:23 | `0x0b` | 98 % ⚡ | L 100 % ⚡, R 100 % ⚡ |

Hipótesis sobre los flags, con todas las observaciones (`00` abierta+dentro, `08` cerrada+dentro, `01` abierta vacía, `02`/`03` abierta en carga, `0a`/`0b` cerrada en carga, `09` ¿cerrada?): **bit 3 = tapa cerrada** (encaja con todos los casos) y **bit 1 = en el cargador** (encaja con `02`/`03`/`0a`/`0b`). El bit 0 sigue sin explicación. El usuario confirma que metió los auriculares. La secuencia completa sería: cierra la tapa (`0a`), la abre (`03`), mete el derecho y luego el izquierdo, y la vuelve a cerrar (`0b`). Con esto:

| bit | Significado | Evidencia |
|---|---|---|
| 3 | tapa cerrada | `08`, `09`, `0a`, `0b` cerrada; `00`-`03` abierta |
| 1 | en el cargador | `02`, `03`, `0a`, `0b` enchufada; `00`, `01`, `08` sin enchufar; `09` a las 23:02:35, 5 s antes de enchufar |
| 0 | desconocido | aparece con y sin auriculares, con y sin cargador |

`airpodsctl status` con la caja cerrada: `L 100 % ⚡ en la caja · R 100 % ⚡ en la caja · Caja 98 % ⚡ tapa cerrada`, en 10 s.

## 13. El bit 0x20 del byte 8 no es "este auricular en la caja"

Captura `9_cerrar_abrir_tras_uso.jsonl` (2026-09-30): con los **dos** auriculares en la caja, el byte 8 vale `0x51` (tapa abierta) y `0x59` (cerrada). El bit 3 (tapa) se comporta bien, pero el bit `0x20` vale **0**, cuando en las capturas del primer día valía 1 (`0x31`/`0x3a`). Los bits 4-6 cambian entre sesiones y no sirven para saber si el emisor está dentro.

Regla adoptada: el bit de tapa de un anuncio de auricular solo se usa si el estado indica **ambos en la caja** (byte 5, bit 2). Con uno fuera (p. ej. en la oreja, que anuncia "abierta" aunque la caja esté cerrada) manda el anuncio cifrado de la caja (flags, bit 3).
