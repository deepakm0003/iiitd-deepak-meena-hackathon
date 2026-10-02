"""Pre-commit guard: refuse to commit secrets, raw third-party data or card/PII-like content.

Usage: python scripts/guard_commit.py FILE [FILE ...]   (pre-commit passes the staged files)
Exit code 1 with a reason per file if anything is blocked. Standard library only.
"""

import re
import sys
from datetime import datetime
from pathlib import Path, PurePosixPath

MAX_BYTES = 5 * 1024 * 1024

BLOCKED_NAMES = re.compile(
    r"(^|/)(users_data|cards_data|transactions_data|train_fraud_labels)[^/]*$|(^|/)\.env$",
    re.IGNORECASE,
)
BLOCKED_DIRS = ("data/raw/", "var/")
TABULAR = {".csv", ".tsv", ".json", ".jsonl"}
SENSITIVE_HEADER = re.compile(r"\b(card_number|cvv|cvc)\b", re.IGNORECASE)

CARD_LIKE = re.compile(r"(?<![\d.])(?:\d[ -]?){12,18}\d(?![\d.])")  # not part of a decimal number
PRIVATE_KEY = re.compile("-----" + r"BEGIN [A-Z ]*PRIVATE KEY" + "-----")
SECRET_ASSIGN = re.compile(
    r"(?i)(?<![a-z0-9])(api[_-]?key|secret|token|password)\b[\"']?\s*[:=]\s*[\"']?([A-Za-z0-9_\-]{16,})"
)
PLACEHOLDER = re.compile(r"(?i)(your|example|changeme|placeholder|xxxx|dummy|test)")


def luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def is_timestamp(digits: str) -> bool:
    """GDELT-style YYYYMMDDHHMMSS stamps are 14 digits and common in our data; they are not card numbers."""
    if len(digits) != 14:
        return False
    try:
        datetime.strptime(digits, "%Y%m%d%H%M%S")
    except ValueError:
        return False
    return True


def check_path(path: str) -> list[str]:
    posix = PurePosixPath(path.replace("\\", "/")).as_posix()
    reasons = []
    if BLOCKED_NAMES.search(posix):
        reasons.append("raw dataset or .env file")
    if any(posix.startswith(d) or f"/{d}" in posix for d in BLOCKED_DIRS):
        reasons.append("file under a git-ignored data directory")
    return reasons


def check_content(path: Path) -> list[str]:
    reasons = []
    try:
        size = path.stat().st_size
    except OSError:
        return reasons  # deleted in this commit
    if size > MAX_BYTES:
        return [f"file larger than {MAX_BYTES // (1024 * 1024)} MB"]
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        return reasons  # binary; size check is enough
    text = raw.decode("utf-8", errors="replace")
    if path.suffix.lower() in TABULAR and SENSITIVE_HEADER.search(text.splitlines()[0] if text else ""):
        reasons.append("tabular file with card_number/cvv columns")
    for match in CARD_LIKE.finditer(text):
        digits = re.sub(r"\D", "", match.group())
        # Payment card numbers start with 2-6 (Mastercard 2/5, Amex 3, Visa 4, Discover 6); epoch
        # timestamps in ms/us start with 1 and would otherwise trip the Luhn check by chance.
        plausible = 13 <= len(digits) <= 19 and digits[0] in "23456" and not is_timestamp(digits)
        if plausible and luhn_ok(digits):
            reasons.append("contains a card-number-like value (passes Luhn check)")
            break
    if PRIVATE_KEY.search(text):
        reasons.append("contains a private key")
    for match in SECRET_ASSIGN.finditer(text):
        if not PLACEHOLDER.search(match.group(2)):
            reasons.append(f"possible secret assigned to '{match.group(1)}'")
            break
    return reasons


def main(argv: list[str]) -> int:
    blocked = 0
    for name in argv:
        reasons = check_path(name) + check_content(Path(name))
        for reason in reasons:
            print(f"BLOCKED {name}: {reason}")
        blocked += bool(reasons)
    if blocked:
        print(f"\n{blocked} file(s) blocked. Unstage them (git restore --staged <file>) and fix before committing.")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
