"""Ecualizador: preajustes, configuración del filter-chain y cambios en vivo."""
import pytest

from airpods_linux import eq


def test_preajustes_validos():
    for key, (label, gains) in eq.PRESETS.items():
        assert label and len(gains) == len(eq.BANDS), key
        assert all(eq.GAIN_MIN <= g <= eq.GAIN_MAX for g in gains), key


def test_ganancias_personalizadas_y_por_defecto():
    custom = [1, 2, 3, 4, 5, 6, 7, 8, 9, 20]
    assert eq.gains_for("custom", custom)[-1] == eq.GAIN_MAX
    assert eq.gains_for("custom", None) == eq.FLAT          # sin ganancias guardadas: plano
    assert eq.gains_for("custom", [1, 2]) == eq.FLAT        # mal formadas
    assert eq.gains_for("no-existe", None) == eq.FLAT
    assert eq.gains_for("bass_boost", None)[0] == 6


def test_preamp_evita_saturar():
    assert eq.preamp(eq.FLAT) == 1.0
    assert eq.preamp([-3] * 10) == 1.0
    assert eq.preamp([0, 6, 0, 0, 0, 0, 0, 0, 0, 0]) == pytest.approx(0.5012, abs=1e-4)


@pytest.mark.parametrize("raw,idx", [("0", 0), ("9", 9), ("250", 3), ("1k", 5), ("4kHz", 7), ("16k", 9)])
def test_bandas_por_indice_o_frecuencia(raw, idx):
    assert eq.band_index(raw) == idx


def test_banda_desconocida():
    with pytest.raises(ValueError):
        eq.band_index("300")


def test_configuracion_smart_filter():
    conf = eq.render_conf("bluez_output.70_AE_2A_E2_8F_60.1", eq.gains_for("bass_boost", None))
    assert 'filter.smart.target = { node.name = "bluez_output.70_AE_2A_E2_8F_60.1" }' in conf
    assert "filter.smart = true" in conf and 'node.name = "airpods_linux_eq"' in conf
    assert conf.count("label = bq_") == len(eq.BANDS)
    assert '{ output = "b8:Out" input = "b9:In" }' in conf
    assert '"Gain" = 6.0' in conf and 'label = linear control = { "Mult" = 0.5012' in conf
    assert 'inputs = [ "pre:In" ]' in conf and 'outputs = [ "b9:Out" ]' in conf
    assert "mixer" not in conf   # sin entradas declaradas, el mixer no arranca y deja el audio en silencio
    assert conf.count("{") == conf.count("}") and conf.count("[") == conf.count("]")


def test_parametros_en_vivo():
    p = eq.props_param([1.5] + [0] * 9)
    assert p.startswith("{ params = [ ") and p.endswith(" ] }")
    assert '"b0:Gain" 1.5' in p and '"b9:Gain" 0.0' in p and '"pre:Mult" 0.8414' in p


def test_id_del_nodo_en_pw_dump():
    dump = [{"id": 5, "type": "PipeWire:Interface:Port", "info": {"props": {"node.name": "airpods_linux_eq"}}},
            {"id": 7, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": "airpods_linux_eq.out"}}},
            {"id": 9, "type": "PipeWire:Interface:Node", "info": {"props": {"node.name": "airpods_linux_eq"}}}]
    assert eq.find_node_id(dump) == 9
    assert eq.find_node_id([]) is None
