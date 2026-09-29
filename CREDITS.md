# Créditos

**airpodsPopUpOnArchLinux** © 2026 canoojson. Distribuido bajo la [GPL-3.0-or-later](LICENSE).

Si redistribuyes una versión modificada, la GPL te obliga a publicar su código con la misma licencia y a conservar este aviso. Además, te pedimos (aunque no es una obligación legal) que propongas tus mejoras al proyecto original con un *pull request*: https://github.com/canoojson/airpodsPopUpOnArchLinux

## Descripción del protocolo

Este proyecto no contiene código de terceros. La interpretación de los protocolos de Apple se basa en la documentación pública de estos proyectos, a los que damos crédito:

- **LibrePods** (Kavish Devar y colaboradores, GPL-3.0) — https://github.com/kavishdevar/librepods
  Formato del anuncio *Proximity Pairing*, secuencia AAP para pedir las claves de proximidad (IRK y clave de cifrado), descifrado AES de la parte cifrada del anuncio y lógica de auricular primario y detección en oreja.
- **furiousMAC/continuity** — https://github.com/furiousMAC/continuity — documentación de los mensajes Continuity de Apple.
- Celosia y Cunche, *Discontinued Privacy: Personal Data Leaks in Apple Bluetooth-Low-Energy Continuity Protocols* (PoPETs 2020).

El formato cifrado del anuncio de la caja (`07 11 06 …`), la reutilización de la clave de cifrado para descifrarlo y el significado de sus flags se documentaron en este proyecto (ver `docs/findings.md`).

AirPods, AirPods Pro y Apple son marcas de Apple Inc. Este proyecto no está afiliado ni respaldado por Apple.
