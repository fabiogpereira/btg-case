"""Regressão comportamental da variante J (tag `candidate-pre-integration`): reproduz exatamente os registros oficiais da
regressão do E-010 nos quatro conjuntos, por replay — garante que a K (E-011) não altera a J."""
import json

import pytest
from conftest import ROOT
from test_e003_regression import _strip

from corporate_actions.llm.cache import ResponseCache
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records
from evaluation.e007 import DATASETS, ReplayProvider

E10 = ROOT / "outputs" / "experiments" / "E-010_vision_stability_uncertainty" / "regression"
CASES = [(name, p, golden, cache) for name, (docs, golden, cache, _) in DATASETS.items()
         for p in sorted(list(docs.glob("*.pdf")) + list(docs.glob("*.txt")))]
GOLD = {g: load_golden_records(g) for _, _, g, _ in CASES}


@pytest.mark.parametrize("name, path, golden, cache", CASES, ids=lambda x: getattr(x, "stem", None) if hasattr(x, "stem") else None)
def test_variant_j_reproduces_official_record(name, path, golden, cache):
    expected = json.loads((E10 / f"{name}_J" / "records" / f"{path.stem}.json").read_text(encoding="utf-8"))
    got = to_jsonable(process_document(path, GOLD[golden], "regression", "J", SemanticContext(ReplayProvider(), ResponseCache(cache))))
    assert _strip(got) == _strip(expected)


E10_ROOT = ROOT / "outputs" / "experiments" / "E-010_vision_stability_uncertainty"


@pytest.mark.parametrize("run, vision_cache", [("run1", ROOT / "outputs" / "experiments" / "E-009_ocr_vs_vision" / "vision_cache_run1"),
                                               ("run2", E10_ROOT / "vision_cache_run2")])
def test_variant_j_reproduces_doc07_vision_records(run, vision_cache, tmp_path):
    from conftest import DOCS, GOLDEN
    from perception.vision_transcriber import VisionTranscriber
    expected = json.loads((E10_ROOT / "policy_J" / run / "records" / "07_telecom_norte_jcp_SCAN.json").read_text(encoding="utf-8"))
    vision = VisionTranscriber(cache_dir=vision_cache, artifacts_dir=tmp_path, allow_api=False)
    got = to_jsonable(process_document(next(DOCS.glob("07_*.pdf")), load_golden_records(GOLDEN), "regression", "J",
                                       SemanticContext(ReplayProvider(), ResponseCache(tmp_path / "llm")), text_fallback=vision))
    strip = lambda r: {k: v for k, v in _strip(r).items() if k != "document"}      # document.* traz caminhos de artefato
    assert strip(got) == strip(expected) and vision.api_calls == 0
