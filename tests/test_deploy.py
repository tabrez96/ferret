import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
COMPOSE = (ROOT / "docker-compose.yml").read_text()


def test_web_not_published():
    assert "8000:8000" not in COMPOSE
    web = COMPOSE.split("\n  worker:")[0]
    assert "ports:" not in web


def test_caddy_service():
    for expected in (
        "caddy:",
        "image: caddy:2",
        '"443:443"',
        "./Caddyfile:/etc/caddy/Caddyfile:ro",
    ):
        assert expected in COMPOSE


def test_master_key_outside_data_volume():
    top = COMPOSE.split("\nsecrets:\n")[1]
    assert "file: ./secrets/" in top.split("ferret_master_key:")[1].splitlines()[1]
    volume_lines = re.findall(r"^\s+- (\S+:\S+)$", COMPOSE, flags=re.M)
    assert volume_lines
    assert not any(line.startswith("./secrets") for line in volume_lines)
    key_files = re.findall(r"FERRET_MASTER_KEY_FILE: (\S+)", COMPOSE)
    assert key_files
    assert all(p.startswith("/run/secrets/") and not p.startswith("/app/data") for p in key_files)


def test_caddyfile_proxies_web():
    caddyfile = (ROOT / "Caddyfile").read_text()
    assert "{$FERRET_DOMAIN}" in caddyfile
    assert "reverse_proxy web:8000" in caddyfile


def test_dockerfile_python_315():
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert dockerfile.count("python:3.15-slim") == 2
    assert "3.14" not in dockerfile
