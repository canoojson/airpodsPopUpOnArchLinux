import pytest

from airpods_linux import cli


@pytest.mark.parametrize("argv", [["--help"], ["status", "--help"], ["monitor", "--help"], ["mode", "--help"],
                                  ["feature", "--help"], ["history", "--help"], ["config", "--help"]])
def test_parser_builds(argv, capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(argv)
    assert e.value.code == 0
    assert "usage" in capsys.readouterr().out


def test_status_format_uses_daemon_state_without_scanning(monkeypatch, capsys):
    st = {"fields": {"left": {"value": {"level": 42, "charging": False}, "ts": 1, "source": "x"}}, "last_seen": 1}
    monkeypatch.setattr(cli, "daemon_state", lambda: st)
    monkeypatch.setattr(cli, "make_scanner", lambda *a, **k: pytest.fail("no debe escanear"))
    assert cli.main(["status", "--format", "{left}|{right}"]) == 0
    assert capsys.readouterr().out == "42|--\n"
