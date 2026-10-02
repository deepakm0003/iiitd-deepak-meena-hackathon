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


def test_unimplemented_commands_say_which_part(tmp_path):
    result = run_cli("collect", tmp_path=tmp_path)
    assert result.returncode == 2 and "Part 1" in result.stderr
