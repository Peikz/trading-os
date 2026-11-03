"""The deploy kit (deploy/): Tailscale is the only way in, and no real values are committed."""

import re
from pathlib import Path

import yaml

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"


def test_no_service_publishes_a_port_and_caddy_is_on_the_tailnet():
    compose = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert {"api", "web", "caddy", "tailscale", "data-sync"} <= set(services)
    assert all("ports" not in s for s in services.values())
    assert services["caddy"]["network_mode"] == "service:tailscale"


def test_the_env_example_holds_placeholders_only():
    env = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1) for line in env.splitlines() if line and not line.startswith("#")
    )
    assert values["TS_AUTHKEY"].endswith("REPLACE-ME")
    assert values["GH_TOKEN"].endswith("REPLACE-ME")


def test_the_caddyfile_proxies_the_api_and_serves_the_app():
    caddy = (DEPLOY / "Caddyfile").read_text(encoding="utf-8")
    assert "reverse_proxy api:8000" in caddy
    assert re.search(r"try_files \{path\} /index.html", caddy)
