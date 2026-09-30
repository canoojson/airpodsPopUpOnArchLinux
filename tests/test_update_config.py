import pytest

from airpods_linux import config
from airpods_linux.update import is_newer, version_tuple


@pytest.mark.parametrize("latest,current,newer", [
    ("0.1.3", "0.1.2", True), ("0.2.0", "0.1.9", True), ("1.0.0", "0.9.9", True),
    ("0.1.2", "0.1.2", False), ("0.1.1", "0.1.2", False), ("v0.1.10", "0.1.9", True),
])
def test_is_newer(latest, current, newer):
    assert is_newer(latest, current) is newer


def test_version_tuple_tolerates_garbage():
    assert version_tuple("v1.2.3-rc1") == (1, 2, 3) and version_tuple("dev") == (0,)


def test_config_defaults_and_set(tmp_path):
    p = tmp_path / "config.json"
    assert config.load(p)["update_check"] is False and not config.exists(p)
    config.set_value("update_check", "sí", p)
    assert config.load(p)["update_check"] is True
    assert (p.stat().st_mode & 0o777) == 0o600
    with pytest.raises(ValueError):
        config.set_value("update_check", "quizá", p)
    with pytest.raises(KeyError):
        config.set_value("desconocida", "1", p)
