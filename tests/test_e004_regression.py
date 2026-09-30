"""Regressão comportamental do E-004 (tag `e004-final`): a variante D continua produzindo exatamente os
registros oficiais da execução 1 do E-004, por replay do cache gravado — nenhuma chamada de API."""
import json

import pytest
from conftest import DOCS, GOLDEN, ROOT
from test_e003_regression import ReplayOnlyProvider, _strip

from corporate_actions.llm.cache import ResponseCache
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records

E004 = ROOT / "outputs" / "experiments" / "E-004_hybrid"
CHALLENGE = ROOT / "tests" / "challenge_set" / "cases"
GOLD = load_golden_records(GOLDEN)

CASES = [(ds, p) for ds, folder in (("original", DOCS), ("challenge", CHALLENGE))
         for p in sorted(list(folder.glob("*.pdf")) + list(folder.glob("*.txt")))]


@pytest.mark.parametrize("dataset, path", CASES, ids=lambda x: getattr(x, "stem", x))
def test_variant_d_reproduces_e004_record(dataset, path):
    expected = json.loads((E004 / f"{dataset}_D" / "records" / f"{path.stem}.json").read_text(encoding="utf-8"))
    ctx = SemanticContext(ReplayOnlyProvider(), ResponseCache(E004 / "llm_cache_run1"))
    got = to_jsonable(process_document(path, GOLD, "regression", "D", ctx))
    assert _strip(got) == _strip(expected)
