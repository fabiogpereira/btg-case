"""Regressão comportamental da variante F (tags `e006-final`/`candidate-F`): reproduz exatamente os registros oficiais
do E-006 (três conjuntos) e do BT-002, por replay do cache — sem API. Garante que a G (E-007) não altera a F."""
import json

import pytest
from conftest import DOCS, GOLDEN, ROOT
from test_e003_regression import ReplayOnlyProvider, _strip

from corporate_actions.llm.cache import ResponseCache
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records

E6 = ROOT / "outputs" / "experiments" / "E-006_hardened"
B2 = ROOT / "outputs" / "experiments" / "BT-002_blind_F"
GOLD = load_golden_records(GOLDEN)
GOLD_B1 = load_golden_records(ROOT / "tests" / "blind_set" / "golden_records.csv")
GOLD_B2 = load_golden_records(ROOT / "tests" / "blind_set_v2" / "golden_records.csv")
CACHE = E6 / "llm_cache_run1"

CASES = ([(p, E6 / "original_F", CACHE, GOLD) for p in sorted(DOCS.glob("*.pdf"))]
         + [(p, E6 / "challenge_F", CACHE, GOLD) for p in sorted((ROOT / "tests" / "challenge_set" / "cases").glob("*.txt"))]
         + [(p, E6 / "blind_derived_F", CACHE, GOLD_B1) for p in sorted((ROOT / "tests" / "blind_set" / "documents").glob("*.txt"))]
         + [(p, B2 / "blind_F", B2 / "llm_cache_run1", GOLD_B2)
            for p in sorted((ROOT / "tests" / "blind_set_v2" / "documents").glob("*.txt"))])


@pytest.mark.parametrize("path, run, cache, golden", CASES, ids=lambda x: getattr(x, "stem", None))
def test_variant_f_reproduces_official_record(path, run, cache, golden):
    expected = json.loads((run / "records" / f"{path.stem}.json").read_text(encoding="utf-8"))
    got = to_jsonable(process_document(path, golden, "regression", "F", SemanticContext(ReplayOnlyProvider(), ResponseCache(cache))))
    assert _strip(got) == _strip(expected)
