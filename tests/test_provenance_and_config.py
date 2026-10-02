import re
from pathlib import Path

import pytest

from tripwire.config import assumption_ids, load_yaml, validate_configs
from tripwire.provenance import Provenance, Tagged
from tripwire.settings import CONFIG_DIR, ROOT


def test_assumption_requires_register_id():
    with pytest.raises(ValueError):
        Tagged[float](value=0.45, provenance=Provenance.ASSUMPTION, source="LGD")
    tagged = Tagged[float](value=0.45, provenance=Provenance.ASSUMPTION, source="LGD", assumption_id="A-05")
    assert tagged.assumption_id == "A-05"


def test_measured_requires_sample_size():
    with pytest.raises(ValueError):
        Tagged[float](value=0.71, provenance=Provenance.MEASURED, source="macro-F1")
    assert Tagged[float](value=0.71, provenance=Provenance.MEASURED, source="macro-F1", n=150).n == 150


def test_shipped_configs_are_valid():
    assert validate_configs() == []


def test_case_study_event_classes_present():
    names = {c["name"] for c in load_yaml("taxonomy.yaml")["classes"]}
    assert {"Geopolitical", "Macroeconomic", "Credit Event", "Merger/Acquisition", "Product Launch"} <= names


def test_every_assumption_id_mentioned_in_configs_exists():
    known = assumption_ids()
    mentioned = set()
    for path in Path(CONFIG_DIR).glob("*.yaml"):
        if path.name != "assumptions_register.yaml":
            mentioned |= set(re.findall(r"\bA-\d{2,}\b", path.read_text(encoding="utf-8")))
    assert mentioned <= known, mentioned - known


def test_validation_catches_bad_weights(tmp_path):
    for path in Path(CONFIG_DIR).glob("*.yaml"):
        (tmp_path / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    bad = (tmp_path / "impact_weights.yaml").read_text(encoding="utf-8").replace("S_severity: 0.25", "S_severity: 0.5")
    (tmp_path / "impact_weights.yaml").write_text(bad, encoding="utf-8")
    assert any("weights sum" in p for p in validate_configs(tmp_path))


def test_root_points_at_repo():
    assert (ROOT / "pyproject.toml").exists()
