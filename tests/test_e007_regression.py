"""Regressão comportamental da variante G (tag `e007-final`): reproduz exatamente os registros oficiais da regressão
do E-007 nos quatro conjuntos, por replay (mesmo provedor sem rede do E-007) — garante que a H não altera a G."""
import json

import pytest
from conftest import ROOT
from test_e003_regression import _strip

from corporate_actions.llm.cache import ResponseCache
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records
from evaluation.e007 import DATASETS, ReplayProvider

E7 = ROOT / "outputs" / "experiments" / "E-007_pre_ocr"
CASES = [(name, p, golden, cache) for name, (docs, golden, cache, _) in DATASETS.items()
         for p in sorted(list(docs.glob("*.pdf")) + list(docs.glob("*.txt")))]
GOLD = {g: load_golden_records(g) for _, _, g, _ in CASES}


@pytest.mark.parametrize("name, path, golden, cache", CASES, ids=lambda x: getattr(x, "stem", None) if hasattr(x, "stem") else None)
def test_variant_g_reproduces_official_record(name, path, golden, cache):
    expected = json.loads((E7 / f"{name}_G" / "records" / f"{path.stem}.json").read_text(encoding="utf-8"))
    got = to_jsonable(process_document(path, GOLD[golden], "regression", "G", SemanticContext(ReplayProvider(), ResponseCache(cache))))
    assert _strip(got) == _strip(expected)
