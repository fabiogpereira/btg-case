"""E-005 congelado antes do run oficial da variante E: código, prompt v3, avaliação, gabaritos e challenge set.
Mudança legítima exige novo freeze_version registrado no evaluation log."""
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-005_qualifiers_v3" / "FREEZE.json").read_text(encoding="utf-8"))


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Evolução a partir do E-006 (ramo aditivo da variante F; perfil v2 no parse_date). O comportamento congelado da E
# é garantido por tests/test_e005_regression.py (replay dos registros do E-005 e do BT-001). Estado exato: tag `candidate-E`.
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py", "src/corporate_actions/normalization.py"}


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_frozen_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento do E-005"


def test_prompt_v3_is_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["prompt"]["version"], FREEZE["prompt"]["fingerprint"])


def test_fixed_config_without_fallback():
    assert FREEZE["required_llm_config"]["LLM_FALLBACKS"] == "off"
