import socket

import pytest

pytest.importorskip("dbus")
from airpods_linux.daemon import graphical_env  # noqa: E402


def test_keeps_existing_wayland_display():
    env = graphical_env({"WAYLAND_DISPLAY": "wayland-9"}, manager_env={"WAYLAND_DISPLAY": "wayland-1"})
    assert env["WAYLAND_DISPLAY"] == "wayland-9"


def test_takes_graphical_vars_from_systemd_when_started_early():
    env = graphical_env({"PATH": "/usr/bin"},
                        manager_env={"WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "abc",
                                     "SECRET": "no"})
    assert env["WAYLAND_DISPLAY"] == "wayland-1" and env["HYPRLAND_INSTANCE_SIGNATURE"] == "abc"
    assert "SECRET" not in env and env["PATH"] == "/usr/bin"


def test_falls_back_to_wayland_socket(tmp_path):
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(tmp_path / "wayland-1"))
    (tmp_path / "wayland-1.lock").touch()
    try:
        env = graphical_env({}, manager_env={}, runtime_dir=str(tmp_path))
    finally:
        s.close()
    assert env["WAYLAND_DISPLAY"] == "wayland-1"
