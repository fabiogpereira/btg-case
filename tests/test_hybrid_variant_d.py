"""Variante D (E-004): detector de necessidade, qualificadores v2 e fusão v2 — offline, sem challenge set.

Os textos sintéticos aqui são próprios deste teste (não são casos do challenge set congelado).
"""
import json

import pytest
from conftest import DOCS, GOLDEN

from corporate_actions.llm.base import LLMResponse, ToolCallRecord
from corporate_actions.llm.config import LLMConfig
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records
from corporate_actions.semantic_hybrid import evaluate_qualifier

GOLD = load_golden_records(GOLDEN)
DOC = {p.name[:2]: p for p in DOCS.glob("*.pdf")}

HEADER = "LOGÍSTICA ATLÂNTICO S.A.\nCompanhia Aberta | CNPJ/ME nº 77.888.999/0001-46\n"
TAIL = "Código de negociação LGAT3 (ISIN BRLGATACNOR6)\nRio de Janeiro (RJ), 01 de outubro de 2026.\n"


class Fake:
    name = "fake"

    def __init__(self, parsed, call_tool=True):
        self.config = LLMConfig("fake", "fake-model", "low", 1000, "off", 10)
        self.parsed, self.call_tool, self.calls = parsed, call_tool, 0

    def structured_call(self, system, user_text, tools, output_schema, max_tool_rounds=3):
        self.calls += 1
        resp = LLMResponse("fake", "fake-model", "fake-model", json.dumps(self.parsed), self.parsed, "end_turn", 2)
        if self.call_tool:
            args = {"identifier": "BRLGATACNOR6", "identifier_type": "ISIN"}
            resp.tool_calls.append(ToolCallRecord("lookup_security", args, tools[0].handler(args), 50))
        return resp


def v2(event_type, evidence, dates=(), wt=None, quals=(), misleading=()):
    return {"event": {"type": event_type, "evidence": list(evidence), "rationale": "r",
                      "misleading_mentions": [{"quote": q, "why_not_the_event": "x"} for q in misleading]},
            "dates": list(dates),
            "withholding_tax": wt or {"status": "NOT_STATED", "rate_as_written": "", "base": "NOT_STATED", "evidence": []},
            "qualifiers": list(quals),
            "security_reference": {"identifier_checked": "BRLGATACNOR6", "found_in_reference": "YES"}}


def run(path, parsed=None, call_tool=True):
    provider = Fake(parsed, call_tool)
    rec = to_jsonable(process_document(path, GOLD, "t", "D", SemanticContext(provider)))
    return rec, provider


def txt(tmp_path, body):
    p = tmp_path / "n.txt"
    p.write_text(HEADER + body + TAIL, encoding="utf-8")
    return p


# --- detector de necessidade ---------------------------------------------------------------------

def test_clean_document_skips_llm():
    rec, provider = run(DOC["01"])
    assert rec["semantic_need"]["llm_required"] is False and provider.calls == 0 and "llm" not in rec
    assert rec["routing"]["decision"] == "AUTO_APPROVE"
    assert rec["fields"]["withholding_tax"]["value"]["base"] == "EXCESS_OVER_THRESHOLD"       # resolvido pelo B


def test_jcp_imputation_conflict_is_explained_without_llm():
    rec, provider = run(DOC["02"])
    signals = {s["signal"]: s for s in rec["semantic_need"]["signals"]}
    assert "EVENT_SIGNALS_CONFLICT_EXPLAINED" in signals and not signals["EVENT_SIGNALS_CONFLICT_EXPLAINED"]["triggers_llm"]
    assert provider.calls == 0


def test_unmapped_required_date_triggers_llm_and_grounded_mapping_is_accepted():
    dates = [{"role": "record_date", "status": "FOUND", "value_as_written": "26/06/2026", "evidence": "Data-base do grupamento 26/06/2026"},
             {"role": "ex_date", "status": "FOUND", "value_as_written": "29/06/2026", "evidence": "Início da negociação grupada 29/06/2026"}]
    rec, provider = run(DOC["06"], v2("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], dates, quals=[
        {"qualifier_type": "legal_context", "affects": "none", "effect": "e",
         "quote": "sem modificação do valor do capital social"}]))
    assert rec["semantic_need"]["llm_trigger_reasons"] == ["REQUIRED_DATE_ROLE_UNMAPPED"]
    assert rec["fields"]["ex_date"]["value"] == "2026-06-29" and rec["fields"]["ex_date"]["source_label"] == "Início da negociação grupada"
    cats = {r["concept"]: r["category"] for r in rec["semantic"]["resolutions"]}
    assert cats["ex_date"] == "LLM_ONLY_GROUNDED" and cats["record_date"] == "AGREEMENT"
    assert rec["routing"]["decision"] == "AUTO_APPROVE"
    assert rec["llm"]["tool_calls"] and rec["llm"]["prompt_version"] == "semantic-interpreter/v2"


def test_llm_only_value_must_be_corroborated_by_every_rule():
    dates = [{"role": "ex_date", "status": "FOUND", "value_as_written": "28/07/2026",
              "evidence": "Período de ajuste de frações 29/06/2026 a 28/07/2026"}]
    rec, _ = run(DOC["06"], v2("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], dates))
    assert "LLM_ONLY_VALUE_NOT_CORROBORATED:ex_date" in rec["routing"]["reason_codes"]


def test_true_date_disagreement_goes_to_review():
    dates = [{"role": "record_date", "status": "FOUND", "value_as_written": "29/06/2026", "evidence": "Início da negociação grupada 29/06/2026"}]
    rec, _ = run(DOC["06"], v2("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], dates))
    assert {r["concept"]: r["category"] for r in rec["semantic"]["resolutions"]}["record_date"] == "TRUE_DISAGREEMENT"
    assert "SEMANTIC_AMBIGUITY" in rec["routing"]["reason_codes"]


def test_negation_decided_classification_triggers_llm(tmp_path):
    p = txt(tmp_path, "AVISO AOS ACIONISTAS — Dividendos\nA Logística Atlântico S.A. aprovou a distribuição de dividendos. "
                      "Não se trata de juros sobre o capital próprio.\nValor bruto por ação ON R$ 0,1000000000\n"
                      "Data-base (“data com”) 13/10/2026\nData “ex” 14/10/2026\nData de pagamento 30/10/2026\n")
    rec, provider = run(p, v2("DIVIDEND", ["aprovou a distribuição de dividendos"]))
    assert "NEGATION_DECIDED_CLASSIFICATION" in rec["semantic_need"]["llm_trigger_reasons"]
    assert {r["concept"]: r["category"] for r in rec["semantic"]["resolutions"]}["event_type"] == "AGREEMENT"
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def _conflict_text(tmp_path):
    return txt(tmp_path, "AVISO AOS ACIONISTAS — Proventos\nA Logística Atlântico S.A. aprovou a distribuição de dividendos. "
                         "Os juros sobre o capital próprio do ano anterior já foram pagos.\nValor bruto por ação ON R$ 0,1000000000\n"
                         "Data-base (“data com”) 13/10/2026\nData “ex” 14/10/2026\nData de pagamento 30/10/2026\n")


def test_heuristic_is_overridden_only_when_losing_signals_are_explained(tmp_path):
    p = _conflict_text(tmp_path)
    explained, _ = run(p, v2("DIVIDEND", ["aprovou a distribuição de dividendos"],
                             misleading=["Os juros sobre o capital próprio do ano anterior já foram pagos"]))
    assert explained["classification"]["event_type"] == "DIVIDEND"
    assert {r["concept"]: r["category"] for r in explained["semantic"]["resolutions"]}["event_type"] == "HEURISTIC_RESOLVED"
    unexplained, _ = run(p, v2("DIVIDEND", ["aprovou a distribuição de dividendos"]))
    assert "CLASSIFICATION_DISAGREEMENT" in unexplained["routing"]["reason_codes"]


def test_unsupported_classification_accepts_grounded_llm(tmp_path):
    p = txt(tmp_path, "AVISO AOS ACIONISTAS\nA Logística Atlântico S.A. aprovou a remuneração dos acionistas sob a forma de "
                      "juros calculados sobre o patrimônio líquido.\nValor bruto por ação ON R$ 0,1000000000\n"
                      "IRRF na fonte 17,5%\nValor líquido por ação ON R$ 0,0825000000\n"
                      "Data-base (“data com”) 13/10/2026\nData “ex” 14/10/2026\nData de pagamento 30/10/2026\n")
    wt = {"status": "STATED", "rate_as_written": "17,5%", "base": "NOT_STATED", "evidence": ["IRRF na fonte 17,5%"]}
    rec, _ = run(p, v2("JCP", ["juros calculados sobre o patrimônio líquido"], wt=wt))
    assert "CLASSIFICATION_UNSUPPORTED" in rec["semantic_need"]["llm_trigger_reasons"]
    assert rec["classification"]["event_type"] == "JCP" and rec["routing"]["decision"] == "AUTO_APPROVE"


def test_deferred_nature_does_not_call_llm_and_is_reviewed(tmp_path):
    p = txt(tmp_path, "AVISO AOS ACIONISTAS — Proventos\nA Logística Atlântico S.A. aprovou R$ 0,10 por ação, cuja natureza, "
                      "dividendos ou juros sobre o capital próprio, será definida pelo Conselho.\nValor bruto por ação ON R$ 0,1000000000\n"
                      "Data-base (“data com”) 13/10/2026\nData “ex” 14/10/2026\n")
    rec, provider = run(p)
    assert provider.calls == 0 and rec["classification"]["event_type"] is None
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_llm_unresolved_never_auto_approves(tmp_path):
    p = _conflict_text(tmp_path)
    rec, _ = run(p, v2("UNRESOLVED", []))
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_interpreter_failure_blocks_and_validations_still_run():
    rec, _ = run(DOC["06"], None)
    assert "SEMANTIC_INTERPRETER_FAILED" in rec["routing"]["reason_codes"] and rec["audit"]["validators_executed"]


# --- qualificadores v2 --------------------------------------------------------------------------------

@pytest.mark.parametrize("qtype, affects, base, blocks", [
    ("legal_context", "none", None, False),
    ("timing_context", "dates", None, False),
    ("beneficiary_exception", "tax_application", None, False),
    ("tax_base_condition", "tax_base", "EXCESS_OVER_THRESHOLD", False),
    ("tax_base_condition", "tax_base", "GROSS_AMOUNT", True),          # base não representa a condição
    ("tax_rate_condition", "tax_rate", None, True),
    ("event_eligibility_condition", "event_eligibility", None, True),
    ("legal_context", "tax_rate", None, True),                         # rótulo não material com efeito material
    ("other", "amounts", None, True),
    ("unresolved", "none", None, True),
])
def test_qualifier_policy(qtype, affects, base, blocks):
    e = evaluate_qualifier({"qualifier_type": qtype, "affects": affects, "effect": "e", "quote": "q"}, base)
    assert e["blocks"] is blocks


def test_ungrounded_qualifier_is_discarded():
    dates = [{"role": "ex_date", "status": "FOUND", "value_as_written": "29/06/2026", "evidence": "Início da negociação grupada 29/06/2026"}]
    rec, _ = run(DOC["06"], v2("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], dates, quals=[
        {"qualifier_type": "event_eligibility_condition", "affects": "event_eligibility", "effect": "e", "quote": "texto inexistente"}]))
    assert rec["semantic"]["qualifiers_v2"] == [] and rec["routing"]["decision"] == "AUTO_APPROVE"
    assert rec["llm"]["grounding"]["ungrounded"]
