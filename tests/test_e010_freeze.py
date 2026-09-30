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


@pytest.mark.parametrize("path", sorted(FREEZE["files"]))
def test_pre_integration_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento pré-integração"


def test_prompts_are_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["semantic_prompt"]["version"], FREEZE["semantic_prompt"]["fingerprint"])
    assert vision_fingerprint() == FREEZE["vision_prompt_fingerprint"]
