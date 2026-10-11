"""Conexión AAP persistente de airpodsd, integrada en el bucle de GLib.

El connect() de L2CAP bloquea varios segundos, así que se hace en un hilo; después
el socket pasa a no bloqueante y se lee con un watch de GLib. Todo lo demás
(callbacks incluidos) corre en el hilo principal.

Solo puede haber un cliente AAP por equipo: si airpods-helper tiene el canal, la
conexión falla y airpodsd sigue sin AAP (lo decide el daemon antes de llamar a start).
"""
import logging
import socket
import threading
from typing import Callable

from gi.repository import GLib

from .aap import (HANDSHAKE, HANDSHAKE_ACK, KEY_REQUEST, OP_FEATURES_ACK, PSM, REQUEST_NOTIFICATIONS,
                  SET_FEATURES, opcode)

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 8
STEP_TIMEOUT_MS = 1500   # si un ACK no llega, se sigue igualmente


class AapClient:
    def __init__(self, address: str, on_packet: Callable[[bytes], None],
                 on_state: Callable[[bool], None]):
        self.address = address
        self.on_packet = on_packet
        self.on_state = on_state
        self.sock: socket.socket | None = None
        self.connecting = False
        self._watch = None
        self._gen = 0   # invalida conexiones en curso si se llama a stop()
        self._step = None   # inicio: "handshake" -> "features" -> "ready"

    @property
    def connected(self) -> bool:
        return self.sock is not None

    def start(self) -> None:
        if self.connecting or self.sock:
            return
        self.connecting = True
        gen = self._gen

        def worker():
            s = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET, socket.BTPROTO_L2CAP)
            s.settimeout(CONNECT_TIMEOUT_S)
            try:
                s.connect((self.address, PSM))
            except OSError as e:
                s.close()
                GLib.idle_add(self._failed, gen, str(e))
                return
            GLib.idle_add(self._established, gen, s)

        threading.Thread(target=worker, daemon=True).start()

    def _failed(self, gen: int, err: str) -> bool:
        if gen == self._gen:
            self.connecting = False
            log.info("AAP: no se pudo conectar (%s)", err)
        return False

    def _established(self, gen: int, s: socket.socket) -> bool:
        if gen != self._gen:
            s.close()
            return False
        self.connecting = False
        s.setblocking(False)
        self.sock = s
        self._watch = GLib.io_add_watch(s.fileno(), GLib.PRIORITY_DEFAULT,
                                        GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self._readable)
        log.info("AAP: conectado a %s", self.address)
        self._advance("handshake")
        self.on_state(True)
        return False

    def _advance(self, step: str) -> None:
        """Inicio por pasos, cada uno tras el ACK del anterior (o tras STEP_TIMEOUT_MS)."""
        self._step = step
        if step == "handshake":
            self.send(HANDSHAKE)
        elif step == "features":
            self.send(SET_FEATURES)
        else:
            for pkt in (REQUEST_NOTIFICATIONS, KEY_REQUEST):
                self.send(pkt)
            return
        GLib.timeout_add(STEP_TIMEOUT_MS, self._step_timeout, self._gen, step)

    def _step_timeout(self, gen: int, step: str) -> bool:
        if gen == self._gen and self.sock and self._step == step:
            log.info("AAP: sin respuesta al paso %s, sigo", step)
            self._advance("features" if step == "handshake" else "ready")
        return False

    def _init_ack(self, pkt: bytes) -> None:
        if self._step == "handshake" and pkt[:4] == HANDSHAKE_ACK:
            self._advance("features")
        elif self._step == "features" and opcode(pkt) == OP_FEATURES_ACK:
            self._advance("ready")

    def _readable(self, _fd, cond) -> bool:
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            self._close("el otro extremo cerró la conexión")
            return False
        while self.sock:
            try:
                pkt = self.sock.recv(2048)
            except (BlockingIOError, InterruptedError):
                break
            except OSError as e:
                self._close(str(e))
                return False
            if not pkt:
                self._close("conexión cerrada")
                return False
            if self._step != "ready":
                self._init_ack(pkt)
            try:
                self.on_packet(pkt)
            except Exception:  # un paquete raro no debe tumbar la conexión
                log.exception("AAP: error procesando %s", pkt.hex())
        return True

    def send(self, pkt: bytes) -> bool:
        if not self.sock:
            return False
        try:
            self.sock.send(pkt)
            return True
        except OSError as e:
            log.warning("AAP: no se pudo enviar %s: %s", pkt.hex(), e)
            return False

    def request_keys(self) -> bool:
        return self.send(KEY_REQUEST)

    def _close(self, reason: str) -> None:
        if self._watch:
            GLib.source_remove(self._watch)
            self._watch = None
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
            self._step = None
            log.info("AAP: desconectado (%s)", reason)
            self.on_state(False)

    def stop(self) -> None:
        self._gen += 1
        self.connecting = False
        self._close("detenido")
