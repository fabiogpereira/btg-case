"""Variantes B (patch determinístico) e C (LLM), testadas offline, e regressão do A contra o E-002."""
import json
from pathlib import Path

import pytest
from conftest import DOCS, GOLDEN, ROOT

from corporate_actions.llm.base import LLMResponse, ToolCallRecord
from corporate_actions.llm.cache import ResponseCache
from corporate_actions.llm.config import LLMConfig
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records

GOLD = load_golden_records(GOLDEN)
CASES = ROOT / "tests" / "challenge_set" / "cases"
DOC = {p.name[:2]: p for p in DOCS.glob("*.pdf")}


def run(path, variant="A", ctx=None):
    return to_jsonable(process_document(path, GOLD, "t", variant, ctx))


def write(tmp_path, text, name="doc.txt"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# --- A: regressão -------------------------------------------------------------------------------

@pytest.mark.parametrize("path", sorted(DOCS.glob("*.pdf")), ids=lambda p: p.stem[:2])
def test_variant_a_reproduces_e002_records(path):
    e002 = ROOT / "outputs" / "experiments" / "E-002_baseline_a" / "records" / f"{path.stem}.json"
    expected = json.loads(e002.read_text(encoding="utf-8"))
    got = run(path, "A")
    expected.pop("audit"), got.pop("audit")
    assert got == expected


# --- B ------------------------------------------------------------------------------------------

def test_b_discards_negated_event_signal():
    rec = run(CASES / "CH-01.txt", "B")
    assert rec["classification"]["event_type"] == "DIVIDEND"
    assert rec["semantic"]["negated_signals"]


def test_b_interprets_threshold_tax_base_on_doc01():
    rec = run(DOC["01"], "B")
    assert rec["fields"]["withholding_tax"]["value"] == {"rate": "0.10", "base": "EXCESS_OVER_THRESHOLD"}
    assert rec["semantic"]["fields"]["withholding_tax"]["confidence"] == "HIGH"


def test_b_accepts_holder_exemption_without_changing_base():
    rec = run(DOC["02"], "B")
    sem = rec["semantic"]["fields"]["withholding_tax"]
    assert sem["confidence"] == "HIGH" and "INTERPRETED:HOLDER_LEVEL_EXEMPTION" in sem["reasons"]
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_b_uninterpretable_qualifier_blocks(tmp_path):
    text = (CASES / "CH-06.txt").read_text(encoding="utf-8").replace(
        "exceto para os acionistas que comprovarem ser imunes ou isentos até 20/08/2026",
        "desde que o acionista resida no país")
    rec = run(write(tmp_path, text), "B")
    assert rec["semantic"]["fields"]["withholding_tax"]["confidence"] == "LOW"
    assert "SEMANTIC_AMBIGUITY" in rec["routing"]["reason_codes"]


def test_b_deferred_event_nature_is_unresolved():
    rec = run(CASES / "CH-11.txt", "B")
    assert rec["classification"]["event_type"] is None
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


# --- C (provedor falso, sem rede) -------------------------------------------------------------------

class FakeProvider:
    name = "fake"

    def __init__(self, parsed, tool_args=None):
        self.config = LLMConfig("fake", "fake-model", "low", 1000, "off", 10)
        self.parsed, self.tool_args, self.calls = parsed, tool_args, 0

    def structured_call(self, system, user_text, tools, output_schema, max_tool_rounds=3):
        self.calls += 1
        resp = LLMResponse("fake", "fake-model", "fake-model", json.dumps(self.parsed), self.parsed, "end_turn", 1)
        if self.tool_args:
            result = tools[0].handler(self.tool_args)
            resp.tool_calls.append(ToolCallRecord(tools[0].name, self.tool_args, result, 100))
        return resp


def interp(event_type, evidence, dates=(), wt=None, found="YES", ident="BRAGCRACNOR2"):
    return {"event": {"type": event_type, "evidence": list(evidence), "misleading_mentions": [], "rationale": "r"},
            "dates": list(dates),
            "withholding_tax": wt or {"status": "NOT_STATED", "rate_as_written": "", "base": "NOT_STATED",
                                      "evidence": [], "qualifiers": []},
            "security_reference": {"identifier_checked": ident, "found_in_reference": found}}


def ctx(parsed, tool_args=None, cache=None):
    return SemanticContext(FakeProvider(parsed, tool_args), cache)


def test_c_llm_fixes_negation_but_disagreement_goes_to_review():
    parsed = interp("DIVIDEND", ["aprovou a distribuição de dividendos"])
    rec = run(CASES / "CH-01.txt", "C", ctx(parsed, {"identifier": "BRAGCRACNOR2", "identifier_type": "ISIN"}))
    assert rec["classification"]["event_type"] == "DIVIDEND"
    assert rec["semantic"]["classification"]["reasons"] == ["CLASSIFICATION_DISAGREEMENT"]
    assert "CLASSIFICATION_DISAGREEMENT" in rec["routing"]["reason_codes"]


def test_c_ungrounded_event_evidence_is_rejected():
    parsed = interp("DIVIDEND", ["trecho que não existe no documento"])
    rec = run(CASES / "CH-01.txt", "C", ctx(parsed))
    assert rec["classification"]["event_type"] == "JCP"          # permanece o determinístico
    assert rec["semantic"]["classification"]["confidence"] == "LOW"
    assert rec["llm"]["grounding"]["ungrounded"]
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_c_grounded_llm_only_date_mapping_fills_field_with_evidence():
    dates = [{"role": "record_date", "status": "FOUND", "value_as_written": "20/08/2026", "evidence": "Último dia com direito 20/08/2026"},
             {"role": "ex_date", "status": "FOUND", "value_as_written": "21/08/2026", "evidence": "Ações ex-direito a partir de 21/08/2026"},
             {"role": "payment_date", "status": "FOUND", "value_as_written": "04/09/2026", "evidence": "Crédito em conta 04/09/2026"}]
    parsed = interp("DIVIDEND", ["aprovou a distribuição de dividendos intermediários"], dates, ident="BRBMRDACNPR7")
    rec = run(CASES / "CH-07.txt", "C", ctx(parsed))
    f = rec["fields"]["ex_date"]
    assert f["value"] == "2026-08-21" and f["source_label"] == "Ações ex-direito a partir de"
    assert f["extraction_rules"] == ["llm.date_role_mapping"] and f["evidence"][0]["text"] == "Ações ex-direito a partir de 21/08/2026"
    assert rec["semantic"]["fields"]["ex_date"]["confidence"] == "MEDIUM"
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_c_llm_date_value_not_in_its_evidence_is_rejected():
    dates = [{"role": "ex_date", "status": "FOUND", "value_as_written": "22/08/2026", "evidence": "Ações ex-direito a partir de 21/08/2026"}]
    parsed = interp("DIVIDEND", ["aprovou a distribuição de dividendos intermediários"], dates, ident="BRBMRDACNPR7")
    rec = run(CASES / "CH-07.txt", "C", ctx(parsed))
    assert rec["fields"]["ex_date"]["status"] == "not_found"       # nada inventado
    assert rec["semantic"]["fields"]["ex_date"]["confidence"] == "LOW"


def test_c_interpreter_failure_blocks_but_mandatory_validations_still_run():
    rec = run(DOC["02"], "C", ctx(None))
    assert "SEMANTIC_INTERPRETER_FAILED" in rec["routing"]["reason_codes"]
    assert "REF_ISIN_FOUND" in rec["audit"]["validators_executed"]
    assert "AMOUNT_NET_MATCHES_GROSS_AND_TAX" in rec["audit"]["validators_executed"]


def test_c_validation_runs_even_without_any_tool_call():
    parsed = interp("JCP", ["Juros sobre o Capital Próprio (JCP)"], found="NOT_CHECKED", ident="")
    rec = run(DOC["02"], "C", ctx(parsed, tool_args=None))
    assert rec["llm"]["tool_calls"] == [] and rec["llm"]["reference_divergence"]["tool_called"] is False
    assert {v["rule_id"]: v["status"] for v in rec["validations"]}["REF_ISIN_FOUND"] == "PASS"


def test_c_reference_divergence_is_recorded_and_engine_prevails():
    parsed = interp("BONUS_SHARES", ["Bonificação em ações"], found="YES", ident="BRCNHZACNOR5")
    rec = run(DOC["08"], "C", ctx(parsed, {"identifier": "BRCNHZACNOR5", "identifier_type": "ISIN"}))
    div = rec["llm"]["reference_divergence"]
    assert div["divergent"] and div["engine_REF_ISIN_FOUND"] == "FAIL" and div["authority"] == "validation_engine"
    assert "REFERENCE_NOT_FOUND" in rec["routing"]["reason_codes"]


def test_c_tax_base_from_llm_requires_grounded_rate():
    wt = {"status": "STATED", "rate_as_written": "10%", "base": "EXCESS_OVER_THRESHOLD",
          "evidence": ["alíquota de 10% sobre a parcela que exceder R$ 50.000,00 mensais por beneficiário"],
          "qualifiers": [{"type": "THRESHOLD", "quote": "sobre a parcela que exceder R$ 50.000,00"}]}
    parsed = interp("DIVIDEND", ["aprovou a distribuição de dividendos"], wt=wt, ident="BRTIETACNOR3")
    rec = run(DOC["01"], "C", ctx(parsed))
    assert rec["fields"]["withholding_tax"]["value"] == {"rate": "0.10", "base": "EXCESS_OVER_THRESHOLD"}
    assert rec["semantic"]["fields"]["withholding_tax"]["confidence"] == "HIGH"


def test_c_cache_replays_without_calling_provider(tmp_path):
    parsed = interp("JCP", ["Juros sobre o Capital Próprio (JCP)"], ident="BRBMRDACNPR7")
    cache = ResponseCache(tmp_path / "cache")
    first = ctx(parsed, cache=cache)
    run(DOC["02"], "C", first)
    second = ctx(parsed, cache=cache)
    rec = run(DOC["02"], "C", second)
    assert first.provider.calls == 1 and second.provider.calls == 0 and rec["llm"]["replayed"] is True
    stored = json.loads(next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8"))
    assert "Juros sobre o Capital" not in json.dumps(stored.get("output_text") is None)   # não grava o prompt
    assert "system" not in stored and "user_text" not in stored
