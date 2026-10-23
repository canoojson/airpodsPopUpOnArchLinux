"""Traducciones: lector de .po, elección de idioma y catálogo inglés completo."""
import importlib.util
import re
from pathlib import Path

from airpods_linux import i18n

ROOT = Path(__file__).resolve().parent.parent


def test_lee_po_con_lineas_partidas_y_escapes():
    po = 'msgid ""\nmsgstr "cabecera"\n\n# comentario\nmsgid "Hola "\n"mundo"\nmsgstr "Hello "\n"world"\n\n' \
         'msgid "a\\nb \\"c\\""\nmsgstr "x\\ny \\"z\\""\n\nmsgid "sin traducir"\nmsgstr ""\n'
    assert i18n.parse_po(po) == {"Hola mundo": "Hello world", 'a\nb "c"': 'x\ny "z"'}


def test_idioma_del_entorno():
    assert i18n.language({"LANG": "es_ES.UTF-8"}) == "es"
    assert i18n.language({"LANGUAGE": "en_GB:es", "LANG": "es_ES.UTF-8"}) == "en"
    assert i18n.language({"LC_ALL": "C", "LANG": "de_DE.UTF-8"}) == "de"
    assert i18n.language({}) == "en"


def test_castellano_original_e_ingles_por_defecto(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "es")
    assert i18n._("Izquierdo") == "Izquierdo"
    monkeypatch.setenv("LANGUAGE", "en")
    assert i18n._("Izquierdo") == "Left"
    monkeypatch.setenv("LANGUAGE", "de")          # sin catálogo propio: inglés
    assert i18n._("Izquierdo") == "Left"
    assert i18n._("texto que no está en el catálogo") == "texto que no está en el catálogo"


def test_cli_en_ingles(monkeypatch, capsys):
    from airpods_linux import cli
    monkeypatch.setenv("LANGUAGE", "en")
    assert cli.age(None, 0) == "never" and cli.age(100, 130) == "30 s ago"


def test_catalogo_ingles_completo():
    spec = importlib.util.spec_from_file_location("i18n_extract", ROOT / "tools" / "i18n_extract.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    msgs = {**mod.from_data(), **mod.from_code()}
    catalog = i18n.parse_po((ROOT / "src/airpods_linux/locale/en.po").read_text(encoding="utf-8"))
    missing = sorted(m for m in msgs if m not in catalog)
    assert not missing, f"faltan traducciones (tools/i18n_extract.py): {missing}"
    for msgid, msgstr in catalog.items():
        assert sorted(re.findall(r"\{[^}]*\}", msgid)) == sorted(re.findall(r"\{[^}]*\}", msgstr)), msgid


def test_traducciones_del_plugin_de_noctalia():
    """Noctalia carga siempre en.json y encima el idioma del usuario: es.json tiene que
    cubrir todas las claves, o el panel saldría en inglés a quien lo usa en castellano."""
    import json
    plugin = ROOT / "integrations/noctalia/airpods"
    keys = set()
    for f in list(plugin.glob("*.luau")) + list(plugin.glob("lib/*.luau")):
        keys |= set(re.findall(r'T\("([^"]*)"', f.read_text()))
    from airpods_linux.eq import PRESETS
    keys |= {label for label, _g in PRESETS.values()}   # llegan del daemon y se traducen en el panel
    en = json.loads((plugin / "translations/en.json").read_text())
    es = json.loads((plugin / "translations/es.json").read_text())
    assert not keys - en.keys(), sorted(keys - en.keys())
    assert es == {k: k for k in en}
    for k, v in en.items():
        assert sorted(re.findall(r"\{[^}]*\}", k)) == sorted(re.findall(r"\{[^}]*\}", v)), k
