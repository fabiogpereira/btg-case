"""Versão pré-vision (variante I) e prompt de transcrição congelados antes da comparação OCR local × vision."""
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint
from perception.vision_transcriber import prompt_fingerprint as vision_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-009_ocr_vs_vision" / "FREEZE_PRE_VISION.json").read_text(encoding="utf-8"))


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Evolução a partir do E-010 (variante J: gate de incerteza em uncertainty.py; ramo aditivo em pipeline.py). O comportamento
# congelado da I é garantido por tests/test_e009_regression.py. Estado exato: tag `candidate-pre-vision`.
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py", "tests/test_e006_freeze.py",
             "tests/test_e008_freeze.py"}


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_pre_vision_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento pré-vision"


def test_prompts_are_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["semantic_prompt"]["version"], FREEZE["semantic_prompt"]["fingerprint"])
    assert vision_fingerprint() == FREEZE["vision_prompt_fingerprint"]
