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


@pytest.mark.parametrize("path", sorted(FREEZE["files"]))
def test_frozen_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento do E-003"


def test_prompt_is_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["prompt"]["version"], FREEZE["prompt"]["fingerprint"])


def test_experiment_requires_fixed_config_without_fallback():
    assert FREEZE["required_llm_config"]["LLM_FALLBACKS"] == "off"
