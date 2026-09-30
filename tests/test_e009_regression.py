"""Regressão comportamental da variante I (tag `candidate-pre-vision`): reproduz exatamente os registros oficiais da
regressão do E-009 nos quatro conjuntos, por replay — garante que a J (E-010) não altera a I."""
import json

import pytest
from conftest import ROOT
from test_e003_regression import _strip

from corporate_actions.llm.cache import ResponseCache
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records
from evaluation.e007 import DATASETS, ReplayProvider

E9 = ROOT / "outputs" / "experiments" / "E-009_ocr_vs_vision" / "regression"
CASES = [(name, p, golden, cache) for name, (docs, golden, cache, _) in DATASETS.items()
         for p in sorted(list(docs.glob("*.pdf")) + list(docs.glob("*.txt")))]
GOLD = {g: load_golden_records(g) for _, _, g, _ in CASES}


@pytest.mark.parametrize("name, path, golden, cache", CASES, ids=lambda x: getattr(x, "stem", None) if hasattr(x, "stem") else None)
def test_variant_i_reproduces_official_record(name, path, golden, cache):
    expected = json.loads((E9 / f"{name}_I" / "records" / f"{path.stem}.json").read_text(encoding="utf-8"))
    got = to_jsonable(process_document(path, GOLD[golden], "regression", "I", SemanticContext(ReplayProvider(), ResponseCache(cache))))
    assert _strip(got) == _strip(expected)
