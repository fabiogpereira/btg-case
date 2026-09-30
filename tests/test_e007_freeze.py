"""E-007 congelado antes da regressão oficial da variante G: código, testes, prompt v3 e avaliador e007."""
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-007_pre_ocr" / "FREEZE.json").read_text(encoding="utf-8"))


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Evolução a partir do E-008 (ramo aditivo da variante H e hook opcional `text_fallback`). O comportamento congelado da
# G é garantido por tests/test_e007_regression.py (replay dos registros oficiais do E-007). Estado exato: tag `e007-final`.
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py",
             "tests/test_e006_freeze.py"}   # só a lista de módulos adicionados após o E-006 (binding_v2.py)


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_frozen_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento do E-007"


def test_prompt_v3_is_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["prompt"]["version"], FREEZE["prompt"]["fingerprint"])


def test_fixed_config_without_fallback():
    assert FREEZE["required_llm_config"]["LLM_FALLBACKS"] == "off"
