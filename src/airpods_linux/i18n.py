"""Traducciones de los textos que ve el usuario (airpodsctl, notificaciones, errores).

El texto original está en castellano y es el msgid; las traducciones viven en
locale/<idioma>.po y se leen tal cual (sin compilar a .mo, sin paso de build).
Idioma: el de LANGUAGE / LC_ALL / LC_MESSAGES / LANG. Con un idioma español se usa el
original; con cualquier otro, inglés (o el catálogo de ese idioma, si existe).
Los mensajes del log de airpodsd no se traducen.
"""
import ast
import os
from functools import lru_cache
from pathlib import Path

LOCALE_DIR = Path(__file__).with_name("locale")
FALLBACK = "en"


def parse_po(text: str) -> dict[str, str]:
    """msgid -> msgstr de un .po (sin plurales ni contextos, que no se usan)."""
    out: dict[str, str] = {}
    msgid = msgstr = None
    current = None

    def flush():
        if msgid and msgstr:
            out[msgid] = msgstr

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid, msgstr, current = ast.literal_eval(line[6:]), None, "id"
        elif line.startswith("msgstr "):
            msgstr, current = ast.literal_eval(line[7:]), "str"
        elif line.startswith('"'):
            part = ast.literal_eval(line)
            if current == "id":
                msgid += part
            elif current == "str":
                msgstr = (msgstr or "") + part
    flush()
    return out


def language(env: dict | None = None) -> str:
    env = os.environ if env is None else env
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = env.get(var)
        if value:
            # LANGUAGE puede ser una lista (es_ES:en); "C"/"POSIX" no dicen nada.
            lang = value.split(":")[0].split(".")[0].split("_")[0].lower()
            if lang not in ("c", "posix", ""):
                return lang
    return FALLBACK


@lru_cache(maxsize=None)
def catalog(lang: str) -> dict[str, str]:
    if lang == "es":
        return {}
    for name in (lang, FALLBACK):
        try:
            return parse_po((LOCALE_DIR / f"{name}.po").read_text(encoding="utf-8"))
        except OSError:
            continue
    return {}


def _(text: str) -> str:
    return catalog(language()).get(text, text)
