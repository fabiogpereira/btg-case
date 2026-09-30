"""E-003 congelado: código (A, B, C, avaliação), gabaritos, challenge set e prompt não podem mudar
depois do congelamento. Mudança legítima exige novo freeze_version, registrado no evaluation log."""
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm import PROMPT_VERSION, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-003_semantic" / "FREEZE.json").read_text(encoding="utf-8"))


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Arquivos que podem evoluir depois do E-003 (ramo aditivo da variante D no E-004). O comportamento
# congelado deles é garantido por tests/test_e003_regression.py (A, B e C reproduzem os registros
# oficiais; C por replay do cache). O estado exato do E-003 está na tag git `e003-final`.
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py"}


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_frozen_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento do E-003"


def test_prompt_is_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["prompt"]["version"], FREEZE["prompt"]["fingerprint"])


def test_experiment_requires_fixed_config_without_fallback():
    assert FREEZE["required_llm_config"]["LLM_FALLBACKS"] == "off"
