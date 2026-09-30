"""E-004 congelado antes do run oficial da variante D: código, prompt v2, avaliação, gabaritos e challenge set.
Mudança legítima exige novo freeze_version registrado no evaluation log."""
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm_v2 import PROMPT_VERSION, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-004_hybrid" / "FREEZE.json").read_text(encoding="utf-8"))


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Arquivos que podem evoluir depois do E-004 (ramo aditivo da variante E no E-005). O comportamento
# congelado é garantido por tests/test_e004_regression.py (D reproduz os registros oficiais por replay)
# e test_e003_regression.py. O estado exato do E-004 está na tag git `e004-final`.
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py",
             "src/corporate_actions/normalization.py"}  # E-006: parse_date ganhou perfil v2 (v1 inalterado)


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_frozen_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento do E-004"


def test_prompt_v2_is_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["prompt"]["version"], FREEZE["prompt"]["fingerprint"])


def test_fixed_config_without_fallback():
    assert FREEZE["required_llm_config"]["LLM_FALLBACKS"] == "off"
