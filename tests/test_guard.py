"""Tests for scripts/guard_commit.py. Sensitive-looking values are built at runtime so this file
itself never contains a card number or key that the guard would (correctly) block."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("guard_commit", ROOT / "scripts" / "guard_commit.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def luhn_valid_number() -> str:
    body = "4" + "1" * 14
    for check in "0123456789":
        if guard.luhn_ok(body + check):
            return body + check
    raise AssertionError("unreachable")


def test_blocks_env_and_raw_dataset_paths():
    assert guard.check_path(".env")
    assert guard.check_path("data/raw/kaggle_transactions/notes.txt")
    assert guard.check_path("some/dir/cards_data.csv")
    assert guard.check_path("users_data_sample.csv")
    assert not guard.check_path(".env.example")
    assert not guard.check_path("src/tripwire/models.py")


def test_blocks_card_number_but_not_ordinary_numbers(tmp_path):
    bad = tmp_path / "notes.md"
    bad.write_text(f"leaked {luhn_valid_number()} here", encoding="utf-8")
    assert guard.check_content(bad)
    ok = tmp_path / "ok.md"
    ok.write_text("13,305,915 rows; merchant 59935; year 2019", encoding="utf-8")
    assert guard.check_content(ok) == []
    decimals = tmp_path / "model.json"
    decimals.write_text('{"x": 0.' + luhn_valid_number() + '}', encoding="utf-8")
    assert guard.check_content(decimals) == []
    timestamps = tmp_path / "ts.json"
    timestamps.write_text('{"time_us": 1790000000000000, "ms": 1790902415474, "gdelt": "20261002021500"}',
                          encoding="utf-8")
    assert guard.check_content(timestamps) == []
    hashes = tmp_path / "keys.jsonl"  # a Luhn-valid digit run inside a hex dedup key is not a card number
    hashes.write_text('{"key": "e15d68fbf4ae2a99b' + luhn_valid_number() + 'e"}', encoding="utf-8")
    assert guard.check_content(hashes) == []
    spaced = tmp_path / "spaced.md"  # but a real number in text, with separators, is still caught
    spaced.write_text("card: " + " ".join(luhn_valid_number()[i:i + 4] for i in range(0, 16, 4)), encoding="utf-8")
    assert guard.check_content(spaced)


def test_blocks_sensitive_csv_header(tmp_path):
    f = tmp_path / "sample.csv"
    f.write_text("id,client_id," + "cv" + "v\n1,2,3\n", encoding="utf-8")
    assert guard.check_content(f)


def test_blocks_secrets_but_allows_placeholders(tmp_path):
    secret = tmp_path / "config.py"
    secret.write_text("API_KEY = '" + "q8f3k2m9x7v1b4n6p0z5" + "'\n", encoding="utf-8")
    assert guard.check_content(secret)
    env_style = tmp_path / "settings.cfg"
    env_style.write_text("FINNHUB_API_KEY=" + "q8f3k2m9x7v1b4n6p0z5" + "\n", encoding="utf-8")
    assert guard.check_content(env_style)
    placeholder = tmp_path / "readme.md"
    placeholder.write_text("FINNHUB_API_KEY=your_finnhub_key_here\n", encoding="utf-8")
    assert guard.check_content(placeholder) == []


def test_blocks_private_key(tmp_path):
    f = tmp_path / "id"
    f.write_text("-----" + "BEGIN RSA PRIVATE KEY" + "-----\nabc\n", encoding="utf-8")
    assert guard.check_content(f)


def test_blocks_large_files(tmp_path):
    f = tmp_path / "big.bin"
    f.write_bytes(b"\x00" * (guard.MAX_BYTES + 1))
    assert guard.check_content(f)


def test_main_exit_code(tmp_path):
    good = tmp_path / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")
    assert guard.main([str(good)]) == 0
    assert guard.main([".env"]) == 1


def test_repository_files_pass_the_guard():
    tracked = [p for p in ROOT.rglob("*") if p.is_file() and not _ignored(p)]
    blocked = {str(p.relative_to(ROOT)): r for p in tracked if (r := guard.check_content(p))}
    assert blocked == {}


def _ignored(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    skip = {".venv", ".git", "var", "__pycache__", ".pytest_cache", ".ruff_cache", "node_modules"}
    return bool(set(parts) & skip) or (
        parts[:2] in {("data", "raw"), ("frontend", "dist"), ("models", "sentiment_entity"), ("models", "event_setfit")}
    ) or path.name == ".env" or path.suffix == ".egg-info" or any(p.endswith(".egg-info") for p in parts)
