"""Comprobación periódica de versiones nuevas en GitHub."""
import logging
import threading
import time

from gi.repository import GLib

from .. import config as config_mod
from .. import update as update_mod
from ..desktop import notify

log = logging.getLogger("airpodsd")

INTERVAL_S = 24 * 3600


class UpdateChecker:
    def __init__(self, daemon):
        self.d = daemon
        self.info = {"checked": None, "latest": None, "available": False, "error": None}
        self._checking = False

    def schedule(self) -> None:
        # Primera comprobación al minuto de arrancar (con la red ya lista) y luego cada día.
        GLib.timeout_add_seconds(60, lambda: (self._periodic(), False)[1])
        GLib.timeout_add_seconds(INTERVAL_S, self._periodic)

    def state(self) -> dict:
        return {**self.info, "enabled": bool(self.d.config.get("update_check")),
                "managed": update_mod.managed_install(), "install": update_mod.install_kind()}

    def _periodic(self) -> bool:
        if self.d.config.get("update_check"):
            self.check()
        return True

    def check(self, manual: bool = False) -> None:
        """Consulta GitHub en un hilo (no bloquea el bucle BLE) y avisa una vez por versión."""
        if self._checking:
            return
        self._checking = True

        def worker():
            info = update_mod.check()
            GLib.idle_add(self._checked, info, manual)

        threading.Thread(target=worker, daemon=True).start()

    def _checked(self, info: dict, manual: bool) -> bool:
        self._checking = False
        config = self.d.config
        self.info = {"checked": time.time(), "latest": info["latest"],
                     "available": info["available"], "error": info["error"]}
        if info["error"]:
            log.warning("no se pudo comprobar si hay actualizaciones: %s", info["error"])
        elif info["available"]:
            log.info("versión nueva disponible: %s (instalada %s)", info["latest"], info["current"])
            if not manual and config.get("notified_version") != info["latest"]:
                config["notified_version"] = info["latest"]
                config_mod.save(config)
                notify(f"AirPods Linux {info['latest']} disponible",
                       "Actualiza con: airpodsctl update (o desde el ⚙ del panel)",
                       icon="software-update-available")
        self.d.changed()
        return False
