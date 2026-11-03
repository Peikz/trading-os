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


def test_the_api_gets_git_credentials_from_the_environment_only():
    compose = yaml.safe_load((DEPLOY / "docker-compose.yml").read_text(encoding="utf-8"))
    env = compose["services"]["api"]["environment"]
    assert env["GIT_CONFIG_KEY_0"] == "credential.helper"
    # The helper reads the token from the environment ($$ escapes Compose's interpolation)
    assert "$${GH_TOKEN}" in env["GIT_CONFIG_VALUE_0"]
    assert env["GIT_AUTHOR_EMAIL"].endswith(".invalid")


class ComposeLoader(yaml.SafeLoader):
    """Compose's `!reset` (the CI override clears Tailscale's settings) reads as None."""


ComposeLoader.add_constructor("!reset", lambda loader, node: None)


def load(name: str) -> dict:
    return yaml.load((DEPLOY / name).read_text(encoding="utf-8"), Loader=ComposeLoader)


def env_example() -> dict:
    env = (DEPLOY / ".env.example").read_text(encoding="utf-8")
    return dict(
        line.split("=", 1) for line in env.splitlines() if line and not line.startswith("#")
    )


def test_the_alerts_service_is_off_by_default_and_has_no_port():
    alerts = load("docker-compose.yml")["services"]["alerts"]
    assert "ports" not in alerts and "network_mode" not in alerts
    env = alerts["environment"]
    assert env["ALERTS_ENABLED"] == "${ALERTS_ENABLED:-false}"
    assert env_example()["ALERTS_ENABLED"] == "false"
    for key in ("ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY", "NTFY_TOPIC"):
        assert env[key] == "${" + key + ":-}"  # from deploy/.env only, never a value here
        assert env_example()[key] == "REPLACE-ME"
    assert "$${GH_TOKEN}" in env["GIT_CONFIG_VALUE_0"]
    assert env["GIT_AUTHOR_EMAIL"].endswith(".invalid")
    assert "scripts/alert_server.py" in alerts["command"]


def test_the_image_carries_the_alert_scripts():
    dockerfile = (DEPLOY / "api.Dockerfile").read_text(encoding="utf-8")
    assert "COPY scripts/alert_watch.py scripts/alert_server.py ./scripts/" in dockerfile


def test_data_sync_takes_the_same_git_lock_as_the_python_writers():
    from trading_os import gitlock

    script = (DEPLOY / "data-sync.sh").read_text(encoding="utf-8")
    assert f"flock -w 600 /data/.git/{gitlock.LOCK_NAME}" in script


def test_the_ci_override_publishes_nothing_and_keeps_caddy_on_the_shared_namespace():
    base, ci = load("docker-compose.yml"), load("docker-compose.ci.yml")
    assert all("ports" not in s for s in ci["services"].values())
    assert set(ci["services"]) <= set(base["services"])
    assert "network_mode" not in ci["services"].get("caddy", {})  # still service:tailscale


def test_the_env_example_holds_no_real_values():
    keep = {"TS_HOSTNAME", "DATA_DIR", "PULL_EVERY", "ALERTS_ENABLED"}
    for key, value in env_example().items():
        assert value.endswith("REPLACE-ME") or key in keep, key
