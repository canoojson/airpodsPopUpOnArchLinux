#!/usr/bin/env python3
"""Actualiza src/airpods_linux/locale/<idioma>.po con los textos marcados con _().

Recoge las llamadas _("...") del código (con el AST, así entran las cadenas partidas en
varias líneas) y los textos que se traducen al mostrarlos (etiquetas de ajustes,
preajustes del ecualizador...). Conserva las traducciones existentes y avisa de las
que faltan; las que ya no se usan se quitan.

Uso: tools/i18n_extract.py [idioma]   (por defecto en)
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "src" / "airpods_linux"
sys.path.insert(0, str(ROOT / "src"))

from airpods_linux.i18n import parse_po  # noqa: E402


def from_code() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(PKG.rglob("*.py")):
        tree = ast.parse(path.read_text(), str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                found.setdefault(node.args[0].value, f"{path.relative_to(ROOT)}:{node.lineno}")
    return found


def from_data() -> dict[str, str]:
    """Textos que viven en tablas y se pasan por _() al mostrarlos."""
    from airpods_linux import aap, alerts, cli, eq, update
    found = {}
    for s in aap.SETTINGS.values():
        found[s.label] = "aap.SETTINGS"
    for label, _gains in eq.PRESETS.values():
        found[label] = "eq.PRESETS"
    for name in alerts.NAMES.values():
        found[name] = "alerts.NAMES"
    for name in cli.SOURCES.values():
        found[name] = "cli.SOURCES"
    for hint in update.UPDATE_HINTS.values():
        found[hint] = "update.UPDATE_HINTS"
    return found


def quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def main() -> int:
    lang = sys.argv[1] if len(sys.argv) > 1 else "en"
    po = PKG / "locale" / f"{lang}.po"
    old = parse_po(po.read_text(encoding="utf-8")) if po.exists() else {}
    msgs = {**from_data(), **from_code()}
    out = [f"# Traducción de airpods-linux ({lang}). Generado por tools/i18n_extract.py:",
           "# edita solo las líneas msgstr; el texto original (msgid) está en el código.",
           'msgid ""', 'msgstr "Content-Type: text/plain; charset=UTF-8\\n"', ""]
    missing = []
    for msgid in sorted(msgs, key=str.lower):
        msgstr = old.get(msgid, "")
        if not msgstr:
            missing.append(msgid)
        out += [f"#: {msgs[msgid]}", f"msgid {quote(msgid)}", f"msgstr {quote(msgstr)}", ""]
    po.parent.mkdir(exist_ok=True)
    po.write_text("\n".join(out), encoding="utf-8")
    print(f"{po.relative_to(ROOT)}: {len(msgs)} textos, {len(missing)} sin traducir")
    for m in missing:
        print("  -", m)
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
