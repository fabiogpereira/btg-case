"""Versão pré-integração (variante J) congelada antes da 2ª execução do vision (E-010)."""
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint
from perception.vision_transcriber import prompt_fingerprint as vision_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-010_vision_stability_uncertainty" / "FREEZE_PRE_INTEGRATION.json").read_text(encoding="utf-8"))


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Evolução a partir do E-011 (variante K: roteador de percepção, seções perception/run_summary; definição de campo
# crítico centralizada em critical_fields.py, importada por uncertainty.py sem mudança de comportamento). O comportamento
# congelado da J é garantido por tests/test_e010_regression.py. Estado exato: tag `candidate-pre-integration`.
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py", "src/corporate_actions/uncertainty.py",
             "tests/test_e006_freeze.py"}


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_pre_integration_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento pré-integração"


def test_prompts_are_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["semantic_prompt"]["version"], FREEZE["semantic_prompt"]["fingerprint"])
    assert vision_fingerprint() == FREEZE["vision_prompt_fingerprint"]
