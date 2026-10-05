import json
import os
import subprocess
import sys


def run_cli(*args, tmp_path):
    env = {**os.environ, "TRIPWIRE_DATABASE_URL": f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"}
    return subprocess.run([sys.executable, "-m", "tripwire", *args], capture_output=True, text=True, env=env)


def test_health_command_succeeds(tmp_path):
    result = run_cli("health", tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["config"]["ok"] and report["store"]["ok"] and report["queue"]["ok"]
    assert "Tripwire health: OK" in result.stderr


def test_health_never_prints_secret_values(tmp_path):
    env_key = "q8f3k2m9x7v1b4n6" + "p0z5"
    env = {**os.environ, "FINNHUB_API_KEY": env_key,
           "TRIPWIRE_DATABASE_URL": f"sqlite:///{(tmp_path / 'cli.db').as_posix()}"}
    result = subprocess.run([sys.executable, "-m", "tripwire", "health"], capture_output=True, text=True, env=env)
    assert env_key not in result.stdout + result.stderr
    assert json.loads(result.stdout)["secrets"]["FINNHUB_API_KEY"] == "set"


def test_collect_once_in_replay_mode_needs_no_network_or_keys(tmp_path):
    result = run_cli("collect", tmp_path=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "replay" in result.stdout


def test_demo_command_is_documented(tmp_path):
    result = run_cli("demo", "--help", tmp_path=tmp_path)
    assert result.returncode == 0 and "snapshot" in result.stdout and "--no-analyze" in result.stdout
