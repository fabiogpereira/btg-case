"""Recusa sem fallback, métricas de function calling e consistência entre execuções, e ensaio offline do E-003."""
import json
import re

from conftest import DOCS, GOLDEN, ROOT
from test_semantic_variants import FakeProvider, interp

from corporate_actions.llm.base import LLMResponse
from corporate_actions.llm.config import llm_config_from_env
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document, run_batch
from corporate_actions.reference import load_golden_records
from evaluation.llm_metrics import consistency, expected_ids_challenge, expected_ids_original, function_calling
from evaluation.variants import compare, render

GOLD = load_golden_records(GOLDEN)
CHALLENGE = ROOT / "tests" / "challenge_set" / "cases"


def test_fallback_is_off_by_default(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACKS", raising=False)
    assert llm_config_from_env().fallbacks == "off"


class RefusingProvider(FakeProvider):
    def structured_call(self, system, user_text, tools, output_schema, max_tool_rounds=3):
        self.calls += 1
        resp = LLMResponse("fake", "fake-model", "fake-model", None, None, "refusal", 1)
        resp.refusal, resp.errors = {"category": "test", "explanation": None}, ["stop_reason:refusal"]
        return resp


def test_refusal_is_recorded_as_result_without_retry_or_fallback():
    provider = RefusingProvider(None)
    rec = to_jsonable(process_document(next(DOCS.glob("02_*.pdf")), GOLD, "t", "C", SemanticContext(provider)))
    assert provider.calls == 1
    assert rec["llm"]["refusals"] == [{"category": "test", "explanation": None}]
    assert "SEMANTIC_INTERPRETER_FAILED" in rec["routing"]["reason_codes"]
    assert rec["audit"]["validators_executed"]            # validações obrigatórias executadas mesmo assim


def _fake_run(tmp_path, name, calls_by_doc):
    d = tmp_path / name / "records"
    d.mkdir(parents=True)
    for sha, calls in calls_by_doc.items():
        rec = {"document": {"sha256": sha, "file_name": sha}, "llm": {"tool_calls": calls}}
        (d / f"{sha}.json").write_text(json.dumps(rec), encoding="utf-8")
    return tmp_path / name


def call(ident, kind="ISIN", name="lookup_security"):
    return {"name": name, "arguments": {"identifier": ident, "identifier_type": kind}, "result": {}, "latency_us": 1}


def test_function_calling_classification(tmp_path):
    expected = {"a": {"isin": "BRAAAACNOR1", "ticker": "AAAA3"}, "b": {"isin": "BRBBBBACNOR2", "ticker": "BBBB3"},
                "c": {"isin": "BRCCCCACNOR3", "ticker": "CCCC3"}, "d": {"isin": "BRDDDDACNOR4", "ticker": "DDDD4"}}
    run = _fake_run(tmp_path, "r", {
        "a": [call("BRAAAACNOR1")],                              # correta
        "b": [call("BBBB3", "TICKER"), call("BRBBBBACNOR2")],     # correta + desnecessária (repetida)
        "c": [call("BRXXXXACNOR9")],                              # argumento incorreto (e esperada ausente)
        "d": []})                                                 # esperada ausente
    m = function_calling(run, expected)
    assert (m["total_tool_calls"], m["documents_with_tool_call"], m["correct_calls"]) == (4, 3, 2)
    assert (m["unnecessary_calls"], m["incorrect_arguments"], m["expected_calls_missing"]) == (1, 1, 2)


def test_expected_identifiers_come_from_ground_truth_and_case_text():
    orig = expected_ids_original()
    assert len(orig) == 7 and all(v["isin"] and v["ticker"] for v in orig.values())   # doc 07 (sem texto) fora
    ch = expected_ids_challenge()
    assert len(ch) == 11 and all(v["isin"] and v["ticker"] for v in ch.values())


class EchoProvider(FakeProvider):
    """Chama a tool com o ISIN do texto e devolve uma interpretação mínima; `flip` muda o tipo (simula instabilidade)."""
    def __init__(self, flip=False):
        super().__init__(None)
        self.flip = flip

    def structured_call(self, system, user_text, tools, output_schema, max_tool_rounds=3):
        isin = re.search(r"ISIN ([A-Z]{2}[A-Z0-9]{9}\d)", user_text).group(1)
        self.parsed = interp("UNRESOLVED" if self.flip else "DIVIDEND", ["AVISO AOS ACIONISTAS"], ident=isin)
        self.tool_args = {"identifier": isin, "identifier_type": "ISIN"}
        return super().structured_call(system, user_text, tools, output_schema, max_tool_rounds)


def test_offline_dry_run_of_the_full_e003_protocol(tmp_path):
    runs = {}
    for ds, docs in (("original", DOCS), ("challenge", CHALLENGE)):
        runs[(ds, "A")] = tmp_path / f"{ds}_A"
        run_batch(docs, GOLDEN, runs[(ds, "A")], "a", "A")
        for rep, flip in ((1, False), (2, ds == "challenge")):
            runs[(ds, f"C{rep}")] = tmp_path / f"{ds}_C{rep}"
            run_batch(docs, GOLDEN, runs[(ds, f"C{rep}")], f"c{rep}", "C", SemanticContext(EchoProvider(flip)))
    result = compare({"A": runs[("original", "A")], "C": runs[("original", "C1")]},
                     {"A": runs[("challenge", "A")], "C": runs[("challenge", "C1")]},
                     {"original": runs[("original", "C2")], "challenge": runs[("challenge", "C2")]})
    for ds in ("original", "challenge"):
        llm = result["llm"]["C"][ds]
        assert llm["protocol_fixed_config"] is True
        assert llm["function_calling"]["correct_calls"] == llm["function_calling"]["documents_expected"]
        assert llm["function_calling"]["expected_calls_missing"] == 0
    assert result["llm"]["C"]["original"]["run_to_run_consistency"]["event_type"]["consistent"] == 7
    ch = result["llm"]["C"]["challenge"]["run_to_run_consistency"]
    assert ch["event_type"]["consistent"] == 0 and len(ch["inconsistent_documents"]) == 11
    report = render(result)
    assert "Function calling (original)" in report and "Consistência entre as duas execuções (challenge" in report


def test_consistency_identical_runs(tmp_path):
    r1, r2 = tmp_path / "r1", tmp_path / "r2"
    ctx = SemanticContext(EchoProvider())
    run_batch(DOCS, GOLDEN, r1, "x", "C", ctx)
    run_batch(DOCS, GOLDEN, r2, "y", "C", SemanticContext(EchoProvider()))
    c = consistency(r1, r2)
    assert c["documents_compared"] == 7 and not c["inconsistent_documents"]
