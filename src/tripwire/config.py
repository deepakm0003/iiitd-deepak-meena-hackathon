"""Load and validate the YAML configs, including assumption-id cross references."""

from pathlib import Path
from typing import Any

import yaml

from tripwire.provenance import ASSUMPTION_ID
from tripwire.settings import CONFIG_DIR

CONFIG_FILES = (
    "settings.yaml",
    "taxonomy.yaml",
    "credibility.yaml",
    "impact_weights.yaml",
    "shocks.yaml",
    "universe.yaml",
    "universe_seed.yaml",
    "sources.yaml",
    "edgar_items.yaml",
    "assumptions_register.yaml",
)


def load_yaml(name: str, config_dir: Path = CONFIG_DIR) -> dict[str, Any]:
    with open(config_dir / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def assumption_ids(config_dir: Path = CONFIG_DIR) -> set[str]:
    return {a["id"] for a in load_yaml("assumptions_register.yaml", config_dir).get("assumptions", [])}


def validate_configs(config_dir: Path = CONFIG_DIR) -> list[str]:
    """Return a list of problems; empty means every config parses and is internally consistent."""
    problems: list[str] = []
    loaded: dict[str, dict[str, Any]] = {}
    for name in CONFIG_FILES:
        try:
            loaded[name] = load_yaml(name, config_dir)
        except (OSError, yaml.YAMLError) as exc:
            problems.append(f"{name}: cannot load ({exc})")
    if problems:
        return problems

    register = loaded["assumptions_register.yaml"].get("assumptions", [])
    ids = [a.get("id", "") for a in register]
    if len(ids) != len(set(ids)):
        problems.append("assumptions_register.yaml: duplicate ids")
    problems += [f"assumptions_register.yaml: bad id {i!r}" for i in ids if not ASSUMPTION_ID.match(i)]

    for name, data in loaded.items():
        ref = data.get("assumption_id")
        if ref and ref not in ids:
            problems.append(f"{name}: references unknown assumption {ref}")

    weights = loaded["impact_weights.yaml"].get("weights", {})
    if abs(sum(weights.values()) - 1.0) > 1e-9:
        problems.append(f"impact_weights.yaml: weights sum to {sum(weights.values())}, expected 1.0")

    classes = loaded["taxonomy.yaml"].get("classes", [])
    if len(classes) < 5:
        problems.append("taxonomy.yaml: expected at least the five case-study classes")
    for cls in classes:
        priors = [cls.get("severity_prior", -1), *cls.get("subtypes", {}).values()]
        if not all(0.0 <= p <= 1.0 for p in priors):
            problems.append(f"taxonomy.yaml: priors for {cls.get('name')} must be in [0, 1]")
    return problems
