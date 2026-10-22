"""The cloud-server scripts (docs/SERVER.md) parse, and pass shellcheck where it is installed
(GitHub's runners have it)."""

import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPTS = sorted((Path(__file__).resolve().parents[1] / "scripts" / "server").glob("*.sh"))
BASH = shutil.which("bash")


@pytest.mark.skipif(BASH is None, reason="no bash")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_server_scripts_parse(script):
    done = subprocess.run([BASH, "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="no shellcheck")
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_server_scripts_pass_shellcheck(script):
    done = subprocess.run(["shellcheck", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stdout


def test_the_dashboard_cache_folder_can_be_set(monkeypatch):
    import importlib

    from trading_os import remote_data

    monkeypatch.setenv("TRADING_OS_CACHE", "/srv/cache")
    try:
        assert Path("/srv/cache") == importlib.reload(remote_data).CACHE
    finally:
        monkeypatch.delenv("TRADING_OS_CACHE")
        importlib.reload(remote_data)
