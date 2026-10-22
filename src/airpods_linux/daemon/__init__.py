"""airpodsd: daemon de usuario. Vigila los anuncios, guarda el estado, lo expone
por D-Bus (bus de sesión, ver service.py) y muestra un popup al abrir la caja con los
auriculares dentro.

Con los AirPods conectados y sin airpods-helper, airpodsd abre su propia conexión AAP:
batería al 1 % y oreja al instante, modos de escucha y demás ajustes, y las claves de
proximidad sin tener que ejecutar airpodsctl keys fetch.
"""
from ..desktop import graphical_env, spawn  # noqa: F401  (los tests las importan de aquí)
from .core import Daemon, main  # noqa: F401
