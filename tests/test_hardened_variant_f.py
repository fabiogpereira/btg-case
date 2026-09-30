"""Variante F (E-006): endurecimento — offline, provedor falso, textos sintéticos (nenhum texto do blind set)."""
import datetime as dt
import json
from decimal import Decimal

import pytest
from conftest import GOLDEN

from corporate_actions import hardening as HD
from corporate_actions.extraction import extract_candidates
from corporate_actions.ingestion import ingest, read_text_layer
from corporate_actions.llm.base import LLMResponse, ToolCallRecord
from corporate_actions.llm.config import LLMConfig
from corporate_actions.models import (BONUS_SHARES, DIVIDEND, FOUND, JCP, NOT_FOUND, REVERSE_SPLIT, SPLIT,
                                      ExtractedField, to_jsonable)
from corporate_actions.normalization import parse_date, resolve_field
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.profiles import DETERMINISTIC_PROFILE
from corporate_actions.reference import load_golden_records

GOLD = load_golden_records(GOLDEN)
HEADER = "LOGÍSTICA ATLÂNTICO S.A.\nCompanhia Aberta | CNPJ/ME nº 77.888.999/0001-46\n"
CODES = "Código de negociação LGAT3 (ISIN BRLGATACNOR6)\n"


class Fake:
    name = "fake"

    def __init__(self, parsed):
        self.config = LLMConfig("fake", "fake-model", "low", 1000, "off", 10)
        self.parsed, self.calls = parsed, 0

    def structured_call(self, system, user_text, tools, output_schema, max_tool_rounds=3):
        self.calls += 1
        resp = LLMResponse("fake", "fake-model", "fake-model", json.dumps(self.parsed), self.parsed, "end_turn", 2)
        args = {"identifier": "BRLGATACNOR6", "identifier_type": "ISIN"}
        resp.tool_calls.append(ToolCallRecord("lookup_security", args, tools[0].handler(args), 10))
        return resp


def v3(event_type, evidence, dates=(), wt=None, material=()):
    return {"event": {"type": event_type, "evidence": list(evidence), "rationale": "r", "misleading_mentions": []},
            "dates": list(dates),
            "withholding_tax": wt or {"status": "NOT_STATED", "rate_as_written": "", "base": "NOT_STATED", "evidence": []},
            "material_qualifiers": list(material), "semantic_notes": [],
            "security_reference": {"identifier_checked": "BRLGATACNOR6", "found_in_reference": "YES"}}


def write(tmp_path, body, name="s.txt"):
    p = tmp_path / name
    p.write_text(HEADER + body + CODES, encoding="utf-8")
    return p


def cash_doc(tmp_path, tax="", payment="Data de pagamento: 30/10/2026", kind="dividendos", extra=""):
    return write(tmp_path, f"AVISO AOS ACIONISTAS — {kind.capitalize()}\n"
                           f"A Logística Atlântico S.A. comunica que o Conselho de Administração aprovou, em reunião "
                           f"realizada em 01/10/2026, a distribuição de {kind}. {tax}\n"
                           "Valor bruto por ação ON R$ 0,5000000000\nData-base: 13/10/2026\nData ex: 14/10/2026\n"
                           f"{payment}\n{extra}")


def run(path, variant="F", parsed=None):
    provider = Fake(parsed or v3("DIVIDEND", ["distribuição de dividendos"]))
    return to_jsonable(process_document(path, GOLD, "t", variant, SemanticContext(provider))), provider


@pytest.fixture
def v2():
    token = DETERMINISTIC_PROFILE.set("v2")
    yield
    DETERMINISTIC_PROFILE.reset(token)


def text_layer(tmp_path, body):
    return read_text_layer(ingest(write(tmp_path, body)))


# --- 1. Cobertura determinística -----------------------------------------------------------------

@pytest.mark.parametrize("raw, expected", [("15.10.2026", dt.date(2026, 10, 15)), ("15-10-2026", dt.date(2026, 10, 15)),
                                           ("5/1/2026", dt.date(2026, 1, 5)), ("05/01/2026", dt.date(2026, 1, 5)),
                                           ("1º de março de 2026", dt.date(2026, 3, 1))])
def test_v2_date_formats_normalize_to_iso(v2, raw, expected):
    assert parse_date(raw) == expected


@pytest.mark.parametrize("raw", ["15.10.2026", "15-10-2026", "5/1/2026"])
def test_v1_profile_is_unchanged_for_frozen_variants(raw):
    with pytest.raises(ValueError):
        parse_date(raw)


def ratio_of(tmp_path, body, event_type):
    tl = text_layer(tmp_path, body)
    ex = extract_candidates(tl)
    HD.extra_candidates(ex, tl)
    return resolve_field("ratio", ex, event_type)


@pytest.mark.parametrize("body, event_type, expected", [
    ("O grupamento será feito na proporção de 10 (dez) ações para 1 (uma) ação.", REVERSE_SPLIT,
     {"shares_before": Decimal(10), "shares_after": Decimal(1)}),
    ("Cada 1 ação ordinária será desdobrada em 5 ações.", SPLIT, {"shares_before": Decimal(1), "shares_after": Decimal(5)}),
    ("Cada uma ação existente dará origem a três novas ações.", SPLIT,
     {"shares_before": Decimal(1), "shares_after": Decimal(3)}),
    ("Cada 8 ações passarão a ser representadas por 1 ação.", REVERSE_SPLIT,
     {"shares_before": Decimal(8), "shares_after": Decimal(1)}),
    ("Fator de grupamento 4:1.", REVERSE_SPLIT, {"shares_before": Decimal(4), "shares_after": Decimal(1)}),
    ("Para cada 20 ações possuídas, os acionistas receberão 1 nova ação.", BONUS_SHARES,
     {"shares_held": Decimal(20), "bonus_shares": Decimal(1)}),
])
def test_ratio_forms_normalize_without_losing_direction(v2, tmp_path, body, event_type, expected):
    f = ratio_of(tmp_path, body, event_type)
    assert f.status == FOUND and f.value == expected


def test_ratio_direction_incompatible_with_event_type_is_a_contradiction():
    ratio = ExtractedField(status=FOUND, value={"shares_before": Decimal(10), "shares_after": Decimal(1)})
    assert [c["code"] for c in HD.detect_contradictions(SPLIT, {"ratio": ratio})] == ["EVENT_TYPE_VS_RATIO_DIRECTION"]
    assert HD.detect_contradictions(REVERSE_SPLIT, {"ratio": ratio}) == []


def issuer(tmp_path, header, body):
    p = tmp_path / "i.txt"
    p.write_text(header + body, encoding="utf-8")
    tl = read_text_layer(ingest(p))
    ex = extract_candidates(tl)
    fields = {"issuer_name": resolve_field("issuer_name", ex, DIVIDEND)}
    return HD.resolve_issuer_v2(fields, ex, tl), fields["issuer_name"]


def test_third_party_company_is_not_the_issuer(tmp_path):
    diag, f = issuer(tmp_path, HEADER, "O pagamento será processado pelo agente escriturador Banco Custódia Sul S.A. "
                                       "conforme contrato.\n")
    assert diag["decision"] in ("STRUCTURAL_PRIMARY", "V1_RESOLUTION")
    assert f.value.casefold() == "logística atlântico s.a."


def test_company_organ_prefix_is_an_alias_of_the_same_entity(tmp_path):
    diag, f = issuer(tmp_path, HEADER, "A Diretoria da Logística Atlântico S.A. comunica aos acionistas o que segue.\n")
    assert diag["decision"] == "STRUCTURAL_PRIMARY" and diag["aliases"]
    assert f.value.casefold() == "logística atlântico s.a." and f.distinct_values == 1


def test_two_structurally_primary_companies_stay_unresolved(tmp_path):
    diag, f = issuer(tmp_path, HEADER, "Mineração Serra Azul S.A. (a “Companhia”) comunica a distribuição a seguir.\n")
    assert diag["decision"] == "UNRESOLVED_MULTIPLE_STRUCTURAL"
    assert f.confidence == "LOW" and f.confidence_reasons == ["ISSUER_UNRESOLVED_MULTIPLE_STRUCTURAL_CANDIDATES"]


# --- 2. Tratamento tributário ---------------------------------------------------------------------

def statements(tmp_path, sentence):
    return HD.detect_tax_statements(text_layer(tmp_path, sentence + "\n"))


def test_distribution_level_exemption_is_detected(tmp_path):
    assert [s["kind"] for s in statements(tmp_path, "Os dividendos ora aprovados são isentos de Imposto de Renda.")] == ["EXEMPT"]


def test_holder_level_exemption_is_not_a_distribution_exemption(tmp_path):
    assert statements(tmp_path, "Haverá IRRF de 15%, ressalvados os acionistas imunes ou isentos.") == []


def test_no_withholding_declaration_is_detected(tmp_path):
    assert [s["kind"] for s in statements(tmp_path, "Não haverá retenção de imposto de renda na fonte.")] == \
        ["NO_WITHHOLDING_DECLARED"]


def test_exemption_is_represented_without_inventing_a_zero_rate(tmp_path):
    rec, provider = run(cash_doc(tmp_path, "Os dividendos ora aprovados são isentos de Imposto de Renda."))
    tt = rec["fields"]["tax_treatment"]
    assert tt["status"] == "found" and tt["value"]["kind"] == "EXEMPT" and tt["value"]["rate"] is None
    assert tt["evidence"] and "isentos" in tt["evidence"][0]["text"]
    assert rec["fields"]["withholding_tax"]["status"] == "not_found"
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_numeric_rate_is_represented_with_rate_and_base(tmp_path):
    rec, _ = run(cash_doc(tmp_path, "Haverá IRRF de 10% sobre a parcela que exceder R$ 50.000,00 por mês."))
    tt = rec["fields"]["tax_treatment"]["value"]
    assert tt["kind"] == "WITHHOLDING_AT_RATE" and tt["rate"] == "0.10" and tt["base"] == "EXCESS_OVER_THRESHOLD"


def test_llm_grounded_exemption_is_not_discarded_for_lacking_a_percentage(tmp_path):
    tl = text_layer(tmp_path, "Os valores distribuídos não sofrem incidência tributária na fonte.\n")
    fields = {"tax_treatment": ExtractedField(status=NOT_FOUND)}
    grounding = {"withholding": {"status": "STATED", "base": "EXEMPT", "rate_as_written": "",
                                 "evidence": ["não sofrem incidência tributária na fonte"]}}
    assert HD.merge_llm_tax_treatment(fields, grounding, tl)["result"] == "LLM_ONLY_GROUNDED"
    assert fields["tax_treatment"].value["kind"] == "EXEMPT" and fields["tax_treatment"].value["rate"] is None


def test_llm_exemption_with_ungrounded_quote_is_ignored(tmp_path):
    tl = text_layer(tmp_path, "Texto sem declaração tributária.\n")
    fields = {"tax_treatment": ExtractedField(status=NOT_FOUND)}
    grounding = {"withholding": {"status": "STATED", "base": "EXEMPT", "rate_as_written": "", "evidence": ["isento de IR"]}}
    assert HD.merge_llm_tax_treatment(fields, grounding, tl)["result"] == "LLM_UNGROUNDED"
    assert fields["tax_treatment"].status == NOT_FOUND


# --- 3. Contradições ------------------------------------------------------------------------------

def tt(kind, base=None, conditions=()):
    return {"tax_treatment": ExtractedField(status=FOUND, value={"kind": kind, "rate": Decimal("0.15") if "RATE" in kind else None,
                                                                 "base": base, "beneficiary_exceptions": [],
                                                                 "conditions": list(conditions)})}


def codes(event_type, fields):
    return [c["code"] for c in HD.detect_contradictions(event_type, fields)]


def test_flat_withholding_on_a_dividend_is_flagged_but_threshold_withholding_is_not():
    assert codes(DIVIDEND, tt("WITHHOLDING_AT_RATE", "GROSS_AMOUNT")) == ["EVENT_TYPE_VS_TAX_TREATMENT"]
    assert codes(DIVIDEND, tt("WITHHOLDING_AT_RATE", "EXCESS_OVER_THRESHOLD")) == []
    assert codes(DIVIDEND, tt("WITHHOLDING_AT_RATE", None, ["acima de R$ 50.000,00 por mês"])) == []
    assert codes(DIVIDEND, tt("EXEMPT")) == []


def test_jcp_declared_exempt_at_distribution_level_is_flagged():
    assert codes(JCP, tt("EXEMPT")) == ["EVENT_TYPE_VS_TAX_TREATMENT"]
    assert codes(JCP, tt("WITHHOLDING_AT_RATE", "GROSS_AMOUNT")) == []


def test_exemption_and_numeric_rate_in_the_same_notice_conflict():
    fields = tt("EXEMPT") | {"withholding_tax": ExtractedField(status=FOUND, value={"rate": Decimal("0.15"), "base": None})}
    assert "TAX_TREATMENT_INTERNAL_CONFLICT" in codes(DIVIDEND, fields)


def test_persisting_contradiction_routes_to_review_after_llm(tmp_path):
    p = cash_doc(tmp_path, "Haverá retenção de Imposto de Renda na fonte à alíquota de 15% sobre o valor bruto.")
    rec, provider = run(p, parsed=v3("DIVIDEND", ["distribuição de dividendos"]))
    assert provider.calls == 1
    assert "SEMANTIC_CONTRADICTION" in rec["semantic_need"]["llm_trigger_reasons"]
    assert "SEMANTIC_CONTRADICTION:EVENT_TYPE_VS_TAX_TREATMENT" in rec["routing"]["reason_codes"]
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


# --- 4. Revogação ---------------------------------------------------------------------------------

@pytest.mark.parametrize("sentence, detected", [
    ("Fica revogada a distribuição de dividendos aprovada em 01/09/2026.", True),
    ("O aviso de juros sobre capital próprio divulgado anteriormente fica sem efeito.", True),
    ("A assembleia aprovou o cancelamento de 1.000 ações mantidas em tesouraria.", False),
    ("O contrato de prestação de serviços foi cancelado pelo fornecedor.", False),
])
def test_revocation_detection(tmp_path, sentence, detected):
    assert bool(HD.detect_revocation(text_layer(tmp_path, sentence + "\n"))) is detected


def test_revoked_event_is_never_an_approvable_live_event(tmp_path):
    p = cash_doc(tmp_path, extra="Por deliberação posterior, fica revogada a distribuição de dividendos acima descrita.\n")
    rec, provider = run(p)
    assert "UNSUPPORTED_EVENT_REVOCATION" in rec["routing"]["reason_codes"]
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"
    assert rec["semantic"]["event_status"] == "REVOCATION_DETECTED_UNSUPPORTED"
    assert provider.calls == 0          # desfecho já é revisão: o LLM não muda nada


# --- 5. Gate de cobertura material ----------------------------------------------------------------

def test_labeled_dotted_payment_date_is_parsed_and_covered(tmp_path):
    rec, provider = run(cash_doc(tmp_path, payment="Data de pagamento: 30.10.2026"))
    assert rec["fields"]["payment_date"]["value"] == "2026-10-30" and provider.calls == 0
    cov = [i for i in rec["semantic"]["material_coverage"] if i["expected_target"] == "payment_date"]
    assert cov and all(i["representation_status"] == "REPRESENTED" for i in cov)
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_same_document_under_e_does_not_parse_the_dotted_date(tmp_path):
    rec, _ = run(cash_doc(tmp_path, payment="Data de pagamento: 30.10.2026"), variant="E")
    assert rec["fields"]["payment_date"]["status"] == "not_found"


PAY_SENTENCE = "O pagamento será realizado em 30.10.2026."
PAY_ROLE = {"role": "payment_date", "status": "FOUND", "value_as_written": "30.10.2026", "evidence": PAY_SENTENCE[:-1]}


def test_unlabeled_dotted_payment_date_mapped_by_llm_is_represented(tmp_path):
    rec, provider = run(cash_doc(tmp_path, payment=PAY_SENTENCE),
                        parsed=v3("DIVIDEND", ["distribuição de dividendos"], [PAY_ROLE]))
    assert provider.calls == 1 and rec["fields"]["payment_date"]["value"] == "2026-10-30"
    assert not any(i["blocks"] for i in rec["semantic"]["material_coverage"])


def test_unlabeled_payment_date_not_mapped_by_anyone_blocks(tmp_path):
    rec, provider = run(cash_doc(tmp_path, payment=PAY_SENTENCE))       # LLM não mapeia a data
    item = next(i for i in rec["semantic"]["material_coverage"] if i["expected_target"] == "payment_date")
    assert item["source"] == "deterministic" and item["representation_status"] == "NOT_REPRESENTED"
    assert "MATERIAL_INFORMATION_NOT_REPRESENTED" in rec["routing"]["reason_codes"]


def bonus_doc(tmp_path, credit_line):
    return write(tmp_path, "AVISO AOS ACIONISTAS — Bonificação em ações\n"
                           "A Logística Atlântico S.A. comunica que a Assembleia Geral aprovou, em 01/10/2026, "
                           "a bonificação em ações. Para cada 10 ações possuídas, os acionistas receberão 1 nova ação.\n"
                           f"Data-base: 13/10/2026\nData ex: 14/10/2026\n{credit_line}\n")


def test_share_credit_date_with_qualified_label_is_extracted(tmp_path):
    rec, _ = run(bonus_doc(tmp_path, "Data de crédito das novas ações: 21/10/2026"))
    assert rec["event_specific_fields"]["share_credit_date"]["value"] == "2026-10-21"
    assert not any(i["blocks"] for i in rec["semantic"]["material_coverage"])


def test_stated_settlement_date_that_is_not_represented_blocks_approval(tmp_path):
    # redação sem rótulo que o extrator reconheça: a data é material e não pode sumir do registro
    rec, _ = run(bonus_doc(tmp_path, "As ações bonificadas serão creditadas aos acionistas em 21/10/2026."))
    assert rec["event_specific_fields"]["share_credit_date"]["status"] == "not_found"
    item = next(i for i in rec["semantic"]["material_coverage"] if i["expected_target"] == "share_credit_date")
    assert item["representation_status"] == "NOT_REPRESENTED" and item["blocks"] and "21/10/2026" in item["evidence"]
    assert "MATERIAL_INFORMATION_NOT_REPRESENTED" in rec["routing"]["reason_codes"]


def test_past_settlement_of_a_previous_event_is_justified_not_blocking(tmp_path):
    p = cash_doc(tmp_path, extra="Os dividendos do exercício anterior já foram integralmente pagos em 15/05/2026.\n")
    rec, _ = run(p)
    item = next(i for i in rec["semantic"]["material_coverage"] if "15/05/2026" in i["evidence"])
    assert item["representation_status"] == "NON_MATERIAL_JUSTIFIED" and item["justification"].startswith("past-tense")
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_settlement_cue_does_not_claim_a_date_whose_nearest_cue_is_another_role(tmp_path):
    p = cash_doc(tmp_path, extra="Os dividendos serão pagos com base na posição acionária do dia 13 de outubro de 2026.\n")
    rec, _ = run(p)
    assert not [i for i in rec["semantic"]["material_coverage"] if "13 de outubro" in i["evidence"]]
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_coverage_items_are_auditable():
    items, blocking = HD.coverage_gate(DIVIDEND, {"tax_treatment": ExtractedField(status=NOT_FOUND)}, {}, {}, None, [],
                                       extract_candidates.__globals__["ExtractionResult"](),
                                       [], [{"kind": "EXEMPT", "evidence": "isento de IR", "cue": "isento"}], "isento de IR")
    assert blocking == ["MATERIAL_INFORMATION_NOT_REPRESENTED"]
    assert set(items[0]) == {"category", "source", "evidence", "expected_target", "representation_status",
                             "justification", "blocks"}


# --- 6. Registro ----------------------------------------------------------------------------------

def test_f_record_carries_hardening_sections(tmp_path):
    rec, _ = run(cash_doc(tmp_path))
    assert rec["schema_version"] == "semantic-record/0.4"
    for key in ("material_coverage", "contradictions", "event_status", "issuer_resolution", "tax_statements", "revocation"):
        assert key in rec["semantic"]
