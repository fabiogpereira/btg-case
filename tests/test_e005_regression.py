"""Regressão comportamental da variante E (tags `e005-final`/`candidate-E`): reproduz exatamente os registros
oficiais do E-005 (execução 1) e do BT-001 (execução completa), por replay do cache — sem API."""
import json

import pytest
from conftest import DOCS, GOLDEN, ROOT
from test_e003_regression import ReplayOnlyProvider, _strip

from corporate_actions.llm.cache import ResponseCache
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records

E005 = ROOT / "outputs" / "experiments" / "E-005_qualifiers_v3"
BT = ROOT / "outputs" / "experiments" / "BT-001_blind_E"
BLIND_DOCS = ROOT / "tests" / "blind_set" / "documents"
GOLD = load_golden_records(GOLDEN)
GOLD_BLIND = load_golden_records(ROOT / "tests" / "blind_set" / "golden_records.csv")

CASES = ([("original", p, E005 / "original_E", E005 / "llm_cache_run1", GOLD) for p in sorted(DOCS.glob("*.pdf"))]
         + [("challenge", p, E005 / "challenge_E", E005 / "llm_cache_run1", GOLD)
            for p in sorted((ROOT / "tests" / "challenge_set" / "cases").glob("*.txt"))]
         + [("blind", p, BT / "blind_E_run2", BT / "llm_cache_run2", GOLD_BLIND) for p in sorted(BLIND_DOCS.glob("*.txt"))])


@pytest.mark.parametrize("dataset, path, run, cache, golden", CASES, ids=lambda x: getattr(x, "stem", None))
def test_variant_e_reproduces_official_record(dataset, path, run, cache, golden):
    expected = json.loads((run / "records" / f"{path.stem}.json").read_text(encoding="utf-8"))
    got = to_jsonable(process_document(path, golden, "regression", "E", SemanticContext(ReplayOnlyProvider(), ResponseCache(cache))))
    assert _strip(got) == _strip(expected)
