"""Escritura atómica de ficheros."""
import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, text: str, mode: int = 0o600) -> None:
    """Escribe `text` en `path` sin dejarlo nunca a medias.

    El temporal tiene un nombre único por llamada: airpodsd y airpodsctl escriben
    los mismos ficheros a la vez, y con un nombre fijo (p. ej. state.tmp) uno le
    movía el temporal al otro (FileNotFoundError en os.replace).
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
