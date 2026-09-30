"""Versão pré-OCR (variante H) congelada: não muda durante o experimento de OCR (o OCR entra só pelo hook)."""
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-008_pre_ocr_ocr" / "FREEZE_PRE_OCR.json").read_text(encoding="utf-8"))


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Evolução a partir do E-009 (variante I: juiz com pontilhado em binding_v2.py, parâmetro judge_fn). O comportamento
# congelado da H é garantido por tests/test_e008_regression.py (replay dos registros oficiais da regressão do E-008).
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py",
             "src/corporate_actions/binding_v2.py"}


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_pre_ocr_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento pré-OCR"


def test_prompt_v3_is_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["prompt"]["version"], FREEZE["prompt"]["fingerprint"])
