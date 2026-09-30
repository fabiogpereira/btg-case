"""Variante E (E-005): qualificadores v3 — offline, provedor falso, sem challenge set."""
import json

from conftest import DOCS, GOLDEN

from corporate_actions.llm.base import LLMResponse, ToolCallRecord
from corporate_actions.llm.config import LLMConfig
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records

GOLD = load_golden_records(GOLDEN)
DOC = {p.name[:2]: p for p in DOCS.glob("*.pdf")}
DOC06_DATES = [{"role": "record_date", "status": "FOUND", "value_as_written": "26/06/2026", "evidence": "Data-base do grupamento 26/06/2026"},
               {"role": "ex_date", "status": "FOUND", "value_as_written": "29/06/2026", "evidence": "Início da negociação grupada 29/06/2026"}]
FRACTIONS = "As frações remanescentes após o período serão separadas, agrupadas em números inteiros e alienadas em leilão na B3"


class Fake:
    name = "fake"

    def __init__(self, parsed):
        self.config = LLMConfig("fake", "fake-model", "low", 1000, "off", 10)
        self.parsed, self.calls = parsed, 0

    def structured_call(self, system, user_text, tools, output_schema, max_tool_rounds=3):
        self.calls += 1
        resp = LLMResponse("fake", "fake-model", "fake-model", json.dumps(self.parsed), self.parsed, "end_turn", 2)
        args = {"identifier": "BRPQLTACNOR8", "identifier_type": "ISIN"}
        resp.tool_calls.append(ToolCallRecord("lookup_security", args, tools[0].handler(args), 10))
        return resp


def v3(event_type, evidence, dates=(), material=(), notes=(), wt=None):
    return {"event": {"type": event_type, "evidence": list(evidence), "rationale": "r", "misleading_mentions": []},
            "dates": list(dates),
            "withholding_tax": wt or {"status": "NOT_STATED", "rate_as_written": "", "base": "NOT_STATED", "evidence": []},
            "material_qualifiers": list(material), "semantic_notes": list(notes),
            "security_reference": {"identifier_checked": "BRPQLTACNOR8", "found_in_reference": "YES"}}


def mq(kind, affects, target, quote):
    return {"kind": kind, "affects": affects, "target_field": target, "effect": "e", "materiality_reason": "m", "quote": quote}


def run(path, parsed):
    provider = Fake(parsed)
    return to_jsonable(process_document(path, GOLD, "t", "E", SemanticContext(provider))), provider


def test_invocation_decisions_are_identical_to_d_on_original():
    for key, path in DOC.items():
        e, pe = run(path, v3("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], DOC06_DATES))
        assert (pe.calls == 1) == (key == "06"), key


def test_operational_fraction_procedure_is_a_note_and_does_not_block():
    rec, _ = run(DOC["06"], v3("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], DOC06_DATES,
                               notes=[{"kind": "operational_instruction", "note": "frações vendidas em leilão", "quote": FRACTIONS}]))
    assert rec["semantic"]["semantic_notes"][0]["kind"] == "operational_instruction"
    assert rec["semantic"]["material_qualifiers"] == []
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_real_unrepresented_material_qualifier_still_blocks():
    rec, _ = run(DOC["06"], v3("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], DOC06_DATES,
                               material=[mq("material_condition", "eligibility", "event", FRACTIONS)]))
    assert "MATERIAL_QUALIFIER_UNREPRESENTED:eligibility" in rec["routing"]["reason_codes"]


def test_unresolved_material_qualifier_blocks():
    rec, _ = run(DOC["06"], v3("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], DOC06_DATES,
                               material=[mq("unresolved", "ratio", "ratio", "sem modificação do valor do capital social")]))
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_scope_guard_rejects_field_label_with_value():
    rec, _ = run(DOC["06"], v3("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], DOC06_DATES,
                               material=[mq("material_condition", "ratio", "ratio", "Proporção 10:1 (dez para uma)")]))
    notes = rec["semantic"]["semantic_notes"]
    assert notes[0]["kind"] == "scope_guard_rejected" and notes[0]["note"].startswith("SCOPE_GUARD_FIELD_LABEL_OR_VALUE")
    assert rec["semantic"]["material_qualifiers"] == [] and rec["routing"]["decision"] == "AUTO_APPROVE"


def test_ungrounded_material_qualifier_is_discarded():
    rec, _ = run(DOC["06"], v3("REVERSE_SPLIT", ["Grupamento de ações (inplit)"], DOC06_DATES,
                               material=[mq("material_condition", "eligibility", "event", "trecho que não existe")]))
    assert rec["semantic"]["material_qualifiers"] == [] and rec["routing"]["decision"] == "AUTO_APPROVE"


def _synthetic(tmp_path, tax_sentence):
    text = ("LOGÍSTICA ATLÂNTICO S.A.\nCompanhia Aberta | CNPJ/ME nº 77.888.999/0001-46\nAVISO AOS ACIONISTAS — Dividendos\n"
            f"A Logística Atlântico S.A. aprovou a distribuição de dividendos. {tax_sentence}\n"
            "Valor bruto por ação ON R$ 0,5000000000\nFarão jus os acionistas posicionados em 13/10/2026, "
            "com negociação ex a partir de 14/10/2026 e pagamento em 30/10/2026.\n"
            "Código de negociação LGAT3 (ISIN BRLGATACNOR6)\nRio de Janeiro (RJ), 01 de outubro de 2026.\n")
    p = tmp_path / "s.txt"
    p.write_text(text, encoding="utf-8")
    return p


DATES = [{"role": "record_date", "status": "FOUND", "value_as_written": "13/10/2026", "evidence": "posicionados em 13/10/2026"},
         {"role": "ex_date", "status": "FOUND", "value_as_written": "14/10/2026", "evidence": "negociação ex a partir de 14/10/2026"},
         {"role": "payment_date", "status": "FOUND", "value_as_written": "30/10/2026", "evidence": "pagamento em 30/10/2026"}]


def test_represented_tax_base_condition_does_not_block(tmp_path):
    p = _synthetic(tmp_path, "Haverá IRRF de 10% sobre a parcela que exceder R$ 50.000,00 por mês.")
    wt = {"status": "STATED", "rate_as_written": "10%", "base": "EXCESS_OVER_THRESHOLD", "evidence": ["IRRF de 10%"]}
    rec, _ = run(p, v3("DIVIDEND", ["aprovou a distribuição de dividendos"], DATES, wt=wt,
                       material=[mq("material_condition", "tax_base", "withholding_tax", "sobre a parcela que exceder R$ 50.000,00")]))
    q = rec["semantic"]["material_qualifiers"][0]
    assert q["represented"] and q["representation"] == "withholding_tax.base=EXCESS_OVER_THRESHOLD" and not q["blocks"]
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_unrepresented_tax_base_condition_blocks(tmp_path):
    # redação que o patch B não reconhece: a base não fica representada e o LLM também não a informa
    p = _synthetic(tmp_path, "Haverá IRRF de 10% aplicável ao montante mensal que superar R$ 50.000,00.")
    wt = {"status": "STATED", "rate_as_written": "10%", "base": "NOT_STATED", "evidence": ["IRRF de 10%"]}
    rec, _ = run(p, v3("DIVIDEND", ["aprovou a distribuição de dividendos"], DATES, wt=wt,
                       material=[mq("material_condition", "tax_base", "withholding_tax", "montante mensal que superar R$ 50.000,00")]))
    assert "SEMANTIC_AMBIGUITY" in rec["routing"]["reason_codes"]


def test_beneficiary_exception_is_recorded_on_tax_field_without_blocking(tmp_path):
    p = _synthetic(tmp_path, "Haverá IRRF de 15% sobre o valor bruto, ressalvados os acionistas imunes ou isentos.")
    wt = {"status": "STATED", "rate_as_written": "15%", "base": "GROSS_AMOUNT", "evidence": ["IRRF de 15% sobre o valor bruto"]}
    rec, _ = run(p, v3("DIVIDEND", ["aprovou a distribuição de dividendos"], DATES, wt=wt,
                       material=[mq("material_exception", "beneficiary_tax_treatment", "withholding_tax",
                                    "ressalvados os acionistas imunes ou isentos")]))
    assert any("beneficiary exception" in n for n in rec["fields"]["withholding_tax"]["notes"])
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_scope_guard_keeps_relation_attached_to_a_field_value(tmp_path):
    p = _synthetic(tmp_path, "Haverá IRRF de 15% sobre o valor bruto.")
    rec, _ = run(p, v3("DIVIDEND", ["aprovou a distribuição de dividendos"], DATES,
                       material=[mq("material_condition", "amount", "gross_amount_per_share",
                                    "Valor bruto por ação ON R$ 0,5000000000 Farão jus os acionistas posicionados")]))
    assert rec["semantic"]["material_qualifiers"] and rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_flat_gross_base_never_represents_a_tax_base_condition(tmp_path):
    """Buraco de segurança fechado: redação de limite que o B não reconhece + LLM erra a base para GROSS_AMOUNT
    e ainda sinaliza a condição -> não pode ser aprovado com a base errada."""
    p = _synthetic(tmp_path, "Haverá IRRF de 10% aplicável ao montante mensal que superar R$ 50.000,00.")
    wt = {"status": "STATED", "rate_as_written": "10%", "base": "GROSS_AMOUNT", "evidence": ["IRRF de 10%"]}
    rec, _ = run(p, v3("DIVIDEND", ["aprovou a distribuição de dividendos"], DATES, wt=wt,
                       material=[mq("material_condition", "tax_base", "withholding_tax", "montante mensal que superar R$ 50.000,00")]))
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"
