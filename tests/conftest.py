"""Los tests comprueban los textos originales (castellano), sea cual sea el idioma del equipo."""
import pytest


@pytest.fixture(autouse=True)
def idioma_castellano(monkeypatch):
    monkeypatch.setenv("LANGUAGE", "es")
