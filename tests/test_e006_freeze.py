"""E-006 congelado antes do run oficial da variante F: código inteiro, testes, gabaritos dos três conjuntos, prompt v3,
avaliador (definição de segurança enhanced) e critérios de sucesso. Mudança legítima exige novo freeze_version
registrado no evaluation log."""
import csv
import hashlib
import json
from pathlib import Path

import pytest

from corporate_actions.semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint

ROOT = Path(__file__).resolve().parents[1]
FREEZE = json.loads((ROOT / "outputs" / "experiments" / "E-006_hardened" / "FREEZE.json").read_text(encoding="utf-8"))
BLIND = ROOT / "tests" / "blind_set"


def text_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


# Evolução a partir do E-007 (ramo aditivo da variante G). O comportamento congelado da F é garantido por
# tests/test_e006_regression.py (replay dos registros oficiais do E-006 e do BT-002). Estado exato: tag `candidate-F`.
EVOLVABLE = {"src/corporate_actions/pipeline.py", "src/corporate_actions/__main__.py"}
ADDED_AFTER_FREEZE = {"src/corporate_actions/identity.py", "src/corporate_actions/binding.py",   # G (E-007)
                      "src/corporate_actions/binding_v2.py",                                             # H (E-008)
                      "src/corporate_actions/uncertainty.py",                                            # J (E-010)
                      "src/corporate_actions/critical_fields.py"}                                        # K (E-011)


@pytest.mark.parametrize("path", sorted(set(FREEZE["files"]) - EVOLVABLE))
def test_frozen_file_unchanged(path):
    assert text_sha(ROOT / path) == FREEZE["files"][path], f"{path} mudou depois do congelamento do E-006"


def test_no_unfrozen_source_file():
    # Escopo = código da variante F (pipeline). Avaliadores novos (ex.: BT-002) podem ser acrescentados em
    # src/evaluation sem mudar a F; os avaliadores já congelados continuam protegidos pelo hash acima.
    current = {p.relative_to(ROOT).as_posix() for p in (ROOT / "src" / "corporate_actions").rglob("*.py")}
    assert current <= set(FREEZE["files"]) | ADDED_AFTER_FREEZE, f"arquivo de código fora do freeze: {sorted(current - set(FREEZE['files']))}"


def test_prompt_v3_is_frozen():
    assert (PROMPT_VERSION, prompt_fingerprint()) == (FREEZE["prompt"]["version"], FREEZE["prompt"]["fingerprint"])


def test_fixed_config_without_fallback():
    assert FREEZE["required_llm_config"]["LLM_FALLBACKS"] == "off"


def _blind_identifiers() -> set[str]:
    ids = set()
    with (BLIND / "golden_records.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ids |= {row["emissor"], row["isin"], row["ticker"], row["cnpj"]}
    gt = json.loads((BLIND / "ground_truth.json").read_text(encoding="utf-8"))
    for c in gt["cases"]:
        ids |= {v for k, v in c["issuer"].items() if isinstance(v, str)}
    return {i.casefold() for i in ids if i and len(i) >= 5}


def test_pipeline_code_contains_no_blind_derived_identifier():
    """Generalização (E-006): nenhuma regra pode citar razão social, ticker, ISIN ou CNPJ do blind-derived set."""
    ids = _blind_identifiers()
    for p in (ROOT / "src" / "corporate_actions").rglob("*.py"):
        text = p.read_text(encoding="utf-8").casefold()
        hits = sorted(i for i in ids if i in text)
        assert not hits, f"{p.name} cita identificadores do blind-derived set: {hits}"
