"""Ecualizador de 10 bandas para los AirPods, con un filter-chain de PipeWire.

airpodsd lanza `pipewire -c eq.conf`, un proceso aparte que crea el filtro. Es un
"smart filter" de WirePlumber (0.5 o posterior): WirePlumber lo mete solo delante de la
salida de los AirPods, así que la salida por defecto sigue siendo la de los AirPods y
el resto de airpodsd (el audio sigue a la oreja, bajar el volumen al hablar) no cambia.
Las ganancias se cambian en vivo con `pw-cli set-param`, sin cortes.
"""
import math

GAIN_MIN, GAIN_MAX = -12.0, 12.0
FILTER_NAME = "airpods_linux_eq"
# (tipo de filtro, frecuencia en Hz, Q): estantes en los extremos y picos en medio.
BANDS = [
    ("bq_lowshelf", 32, 0.707), ("bq_peaking", 64, 1.41), ("bq_peaking", 125, 1.41),
    ("bq_peaking", 250, 1.41), ("bq_peaking", 500, 1.41), ("bq_peaking", 1000, 1.41),
    ("bq_peaking", 2000, 1.41), ("bq_peaking", 4000, 1.41), ("bq_peaking", 8000, 1.41),
    ("bq_highshelf", 16000, 0.707),
]
FLAT = [0.0] * len(BANDS)
# Inspirados en los del ecualizador de Música de iOS.
PRESETS = {
    "flat": ("Plano", FLAT),
    "bass_boost": ("Más graves", [6, 5, 4, 2.5, 1, 0, 0, 0, 0, 0]),
    "bass_reduce": ("Menos graves", [-6, -5, -4, -2.5, -1, 0, 0, 0, 0, 0]),
    "treble_boost": ("Más agudos", [0, 0, 0, 0, 0, 1, 2.5, 4, 5, 6]),
    "treble_reduce": ("Menos agudos", [0, 0, 0, 0, 0, -1, -2.5, -4, -5, -6]),
    "vocal": ("Voces", [-2, -2, -1, 0, 2, 4, 4, 3, 1, 0]),
    "acoustic": ("Acústica", [4, 4, 3, 1, 2, 2, 3, 3, 2, 1]),
    "electronic": ("Electrónica", [4, 3.5, 1, 0, -2, 2, 1, 1.5, 4, 5]),
    "rock": ("Rock", [5, 4, 3, 1.5, -0.5, -1, 0.5, 2.5, 3.5, 4.5]),
    "loudness": ("Sonoridad", [6, 4, 0, 0, -2, 0, -1, -5, 5, 1]),
    "late_night": ("Nocturno", [-3, -2, -1, 0, 1, 2, 2, 1, 0, -1]),
    # Propio: el bombo del lofi. Golpe (64 Hz) y cuerpo (125 Hz) arriba, menos barro en
    # 250-500 Hz para que se separe del resto, y algo de ataque en 2-4 kHz.
    "lofi": ("Lofi", [2, 6, 4, -2, -1, 0, 1, 2, 0, 0]),
}
CUSTOM = "custom"

# Modo sencillo, como el de iOS: tres controles (graves, medios, agudos), cada uno con un
# peso por banda para que se solapen suavemente, como un control de tonos.
SIMPLE, ADVANCED = "simple", "advanced"
SIMPLE_CONTROLS = ("bass", "mid", "treble")
SIMPLE_WEIGHTS = {
    "bass": [1.0, 1.0, 0.8, 0.4, 0.1, 0, 0, 0, 0, 0],
    "mid": [0, 0, 0, 0.3, 0.8, 1.0, 0.8, 0.3, 0, 0],
    "treble": [0, 0, 0, 0, 0, 0, 0.2, 0.7, 1.0, 1.0],
}


def clamp(db: float) -> float:
    return round(min(GAIN_MAX, max(GAIN_MIN, float(db))), 1)


def gains_for(preset: str, custom: list | None) -> list[float]:
    """Ganancias de un preajuste, o las personalizadas (si son válidas)."""
    if preset == CUSTOM and isinstance(custom, list) and len(custom) == len(BANDS):
        try:
            return [clamp(g) for g in custom]
        except (TypeError, ValueError):
            pass
    return [float(g) for g in PRESETS.get(preset, PRESETS["flat"])[1]]


def simple_values(raw) -> list[float]:
    """[graves, medios, agudos] guardados, o planos si no son válidos."""
    if isinstance(raw, list) and len(raw) == len(SIMPLE_CONTROLS):
        try:
            return [clamp(v) for v in raw]
        except (TypeError, ValueError):
            pass
    return [0.0] * len(SIMPLE_CONTROLS)


def simple_gains(values: list[float]) -> list[float]:
    """Ganancias de las 10 bandas a partir de graves, medios y agudos."""
    return [clamp(sum(v * SIMPLE_WEIGHTS[c][i] for c, v in zip(SIMPLE_CONTROLS, values)))
            for i in range(len(BANDS))]


def mode(cfg: dict) -> str:
    """Modo del ecualizador. Sin elegir, el sencillo, salvo que ya hubiera ajustes avanzados."""
    m = cfg.get("eq_mode")
    if m in (SIMPLE, ADVANCED):
        return m
    return ADVANCED if (cfg.get("eq_preset") or "flat") != "flat" else SIMPLE


def config_gains(cfg: dict) -> list[float]:
    """Ganancias de las 10 bandas según la configuración (modo, preajuste, ajustes)."""
    if mode(cfg) == SIMPLE:
        return simple_gains(simple_values(cfg.get("eq_simple")))
    return gains_for(cfg.get("eq_preset") or "flat", cfg.get("eq_gains"))


def preamp(gains: list[float]) -> float:
    """Ganancia lineal previa: baja tanto como la banda que más sube, para no saturar."""
    return round(10 ** (-max(0.0, max(gains)) / 20), 4)


def band_label(freq: int) -> str:
    return f"{freq // 1000} kHz" if freq >= 1000 else f"{freq} Hz"


def band_index(raw: str) -> int:
    """'3', '250', '1k' o '1kHz' -> índice de banda (0-9). ValueError si no existe."""
    s = raw.strip().lower().removesuffix("hz").strip()
    if s.endswith("k"):
        freq = int(float(s[:-1]) * 1000)
    else:
        n = int(s)
        if 0 <= n < len(BANDS):
            return n
        freq = n
    for i, (_kind, f, _q) in enumerate(BANDS):
        if f == freq:
            return i
    from .i18n import _
    raise ValueError(_("banda desconocida: {band} (posibles: {values})").format(
        band=raw, values=", ".join(band_label(f) for _k, f, _q in BANDS)))


def _num(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".") if not math.isclose(x, round(x)) else f"{x:.1f}"


def render_conf(target: str, gains: list[float]) -> str:
    """Configuración del proceso `pipewire -c` con el filtro delante de `target`."""
    # Preamplificación con "linear" (una entrada y una salida). Un "mixer" tiene 8 entradas y,
    # sin declarar las del grafo, PipeWire no lo arranca ("can't start graph") y sale silencio.
    nodes = [f'          {{ type = builtin name = pre label = linear control = {{ "Mult" = {_num(preamp(gains))} "Add" = 0.0 }} }}']
    links = ['          { output = "pre:Out" input = "b0:In" }']
    for i, ((kind, freq, q), g) in enumerate(zip(BANDS, gains)):
        nodes.append(f'          {{ type = builtin name = b{i} label = {kind} '
                     f'control = {{ "Freq" = {_num(freq)} "Q" = {_num(q)} "Gain" = {_num(g)} }} }}')
        if i:
            links.append(f'          {{ output = "b{i - 1}:Out" input = "b{i}:In" }}')
    return f"""# Generado por airpodsd: ecualizador de los AirPods. Se reescribe al cambiarlo.
context.properties = {{ log.level = 0 }}
context.spa-libs = {{
  audio.convert.* = audioconvert/libspa-audioconvert
  support.* = support/libspa-support
}}
context.modules = [
  {{ name = libpipewire-module-rt args = {{ }} flags = [ ifexists nofail ] }}
  {{ name = libpipewire-module-protocol-native }}
  {{ name = libpipewire-module-client-node }}
  {{ name = libpipewire-module-adapter }}
  {{ name = libpipewire-module-filter-chain
    args = {{
      node.description = "Ecualizador de los AirPods"
      media.name = "Ecualizador de los AirPods"
      filter.graph = {{
        nodes = [
{chr(10).join(nodes)}
        ]
        inputs = [ "pre:In" ]
        outputs = [ "b{len(BANDS) - 1}:Out" ]
        links = [
{chr(10).join(links)}
        ]
      }}
      audio.channels = 2
      audio.position = [ FL FR ]
      capture.props = {{
        node.name = "{FILTER_NAME}"
        media.class = Audio/Sink
        filter.smart = true
        filter.smart.name = "{FILTER_NAME}"
        filter.smart.target = {{ node.name = "{target}" }}
      }}
      playback.props = {{
        node.name = "{FILTER_NAME}.out"
        node.passive = true
      }}
    }}
  }}
]
"""


def props_param(gains: list[float]) -> str:
    """Argumento de `pw-cli set-param <id> Props` para cambiar las ganancias en vivo."""
    parts = [f'"pre:Mult" {_num(preamp(gains))}']
    parts += [f'"b{i}:Gain" {_num(g)}' for i, g in enumerate(gains)]
    return "{ params = [ " + " ".join(parts) + " ] }"


def find_node_id(dump: list, name: str = FILTER_NAME) -> int | None:
    """Id del nodo `name` en la salida de `pw-dump`."""
    for obj in dump or []:
        if (obj.get("type", "").endswith(":Node")
                and ((obj.get("info") or {}).get("props") or {}).get("node.name") == name):
            return obj.get("id")
    return None
