"""Regressão comportamental do E-003 (tag `e003-final`): A, B e C continuam produzindo exatamente os
registros oficiais do E-003. C é reproduzida por replay do cache gravado — nenhuma chamada de API.

Garante que a evolução do código (ex.: variante D no E-004) não altera o comportamento congelado.
"""
import json
from pathlib import Path

import pytest
from conftest import DOCS, GOLDEN, ROOT

from corporate_actions.llm.cache import ResponseCache
from corporate_actions.llm.config import LLMConfig
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records

E003 = ROOT / "outputs" / "experiments" / "E-003_semantic"
CHALLENGE = ROOT / "tests" / "challenge_set" / "cases"
GOLD = load_golden_records(GOLDEN)
FROZEN_CONFIG = LLMConfig("anthropic", "claude-opus-5", "medium", 8000, "off", 120)


class ReplayOnlyProvider:
    """Mesma configuração do run oficial; qualquer cache miss falha (não há rede)."""
    name = "replay-only"
    config = FROZEN_CONFIG

    def structured_call(self, *args, **kwargs):
        raise AssertionError("cache miss: o comportamento de C mudou em relação ao E-003")


def _strip(rec):
    rec = json.loads(json.dumps(rec))
    rec.pop("audit", None)
    if "llm" in rec:
        rec["llm"].pop("replayed", None)
    return rec


CASES = [(v, ds, p) for v in ("A", "B", "C") for ds, folder in (("original", DOCS), ("challenge", CHALLENGE))
         for p in sorted(list(folder.glob("*.pdf")) + list(folder.glob("*.txt")))]


@pytest.mark.parametrize("variant, dataset, path", CASES, ids=lambda x: getattr(x, "stem", x))
def test_variant_reproduces_e003_record(variant, dataset, path):
    official = E003 / f"{dataset}_{variant}" / "records" / f"{path.stem}.json"
    expected = json.loads(official.read_text(encoding="utf-8"))
    ctx = SemanticContext(ReplayOnlyProvider(), ResponseCache(E003 / "llm_cache_run1")) if variant == "C" else None
    got = to_jsonable(process_document(path, GOLD, "regression", variant, ctx))
    assert _strip(got) == _strip(expected)
