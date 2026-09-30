"""Variante J (E-010): política de incerteza crítica da percepção. Aviso sintético + percepção falsa que declara tokens
incertos; ponta a ponta pela pipeline J (extração, validação, identidade, roteamento). Nenhum texto do doc 07."""
from dataclasses import replace

import pytest
from conftest import DOCS, GOLDEN

from corporate_actions.ingestion import MIN_ALNUM_CHARS_PER_PAGE, TextLayer, normalize_whitespace
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import process_document
from corporate_actions.reference import GoldenRecords, load_golden_records

GOLD = load_golden_records(GOLDEN)
SCAN = next(DOCS.glob("07_*.pdf"))          # só fornece um PDF sem camada de texto; o texto vem da percepção falsa
ROW = next(r for r in GOLD.rows if r["ticker"] == "LGAT3")
GOLD_TWO_CLASSES = GoldenRecords(GOLD.path, "x", GOLD.rows + [dict(ROW, isin="BRLGATACNPR4", ticker="LGAT4", classe="PN")])

HEADER = "LOGÍSTICA ATLÂNTICO S.A.\nCompanhia Aberta | CNPJ/ME nº 77.888.999/0001-46\nAVISO AOS ACIONISTAS — Juros sobre o Capital Próprio\n"
BODY = ("A Logística Atlântico S.A. comunica que o Conselho de Administração aprovou, em reunião realizada em 01/10/2026, "
        "o pagamento de juros sobre o capital próprio.\nValor bruto por ação ON R$ 0,5000000000\nIRRF 15%\n"
        "Valor líquido por ação ON R$ 0,4250000000\nData-base: 13/10/2026\nData ex: 14/10/2026\nData de pagamento: 30/10/2026\n")
CODES = "Código de negociação LGAT3 (ISIN BRLGATACNOR6)\n"


class FakePerception:
    def __init__(self, text, uncertain=None):
        self.text, self.uncertain = text, uncertain

    def __call__(self, doc):
        norm = normalize_whitespace(self.text)
        alnum = sum(c.isalnum() for c in norm)
        tl = TextLayer(usable=alnum >= MIN_ALNUM_CHARS_PER_PAGE, pages=1, alnum_chars=alnum, min_alnum_chars_per_page=MIN_ALNUM_CHARS_PER_PAGE,
                       page_texts=[self.text], normalized_text=norm, page_offsets=[0], reason=None)
        audit = {"extraction_method": "VISION_LLM", "engine": "fake"}
        if self.uncertain is not None:
            audit["uncertain_tokens"] = [{"token": t, "reason": "test", "page": 1} for t in self.uncertain]
        return tl, audit


def run(uncertain, text=HEADER + BODY + CODES, golden=GOLD, variant="J"):
    return to_jsonable(process_document(SCAN, golden, "t", variant, text_fallback=FakePerception(text, uncertain)))


def fields(rec):
    return rec["perception_uncertainty"]["fields"]


def test_baseline_without_uncertainty_is_approved():
    rec = run([])
    assert rec["routing"]["decision"] == "AUTO_APPROVE" and rec["perception_uncertainty"]["blocking"] == []


def test_uncertain_isin_corroborated_by_reference_and_another_identifier_can_proceed():
    rec = run(["BRLGATACNOR6"])
    f = fields(rec)["isin"]
    assert f["vision_uncertain"] and f["critical_field"] and f["corroboration_attempted"]
    assert f["corroboration_status"] == "EXACT_MATCH" and f["corroboration_source"].startswith("golden_records row via ticker")
    assert f["blocking_reason"] is None and rec["routing"]["decision"] == "AUTO_APPROVE"


def test_uncertain_ticker_corroborated_through_the_isin_row():
    f = fields(run(["LGAT3"]))["ticker"]
    assert f["corroboration_status"] == "EXACT_MATCH" and f["corroboration_source"] == "golden_records row via isin=BRLGATACNOR6"


def test_critical_uncertain_date_without_independent_source_goes_to_review():
    rec = run(["30/10/2026"])
    f = fields(rec)["payment_date"]
    assert f["corroboration_status"] == "NO_INDEPENDENT_SOURCE" and f["blocking_reason"] == "CRITICAL_FIELD_UNCERTAIN_UNCORROBORATED"
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"
    assert "CRITICAL_FIELD_UNCERTAIN_UNCORROBORATED" in rec["routing"]["reason_codes"]


def test_non_critical_uncertainty_does_not_block():
    rec = run(["Aberta"])
    assert rec["routing"]["decision"] == "AUTO_APPROVE"
    assert [t["token"] for t in rec["perception_uncertainty"]["non_critical_uncertain_tokens"]] == ["Aberta"]


def test_single_uncertain_amount_is_corroborated_by_the_arithmetic_of_the_other_two():
    f = fields(run(["0,4250000000"]))["net_amount_per_share"]
    assert f["corroboration_status"] == "EXACT_MATCH" and f["corroboration_source"].startswith("arithmetic")


def test_two_uncertain_amounts_have_no_independent_source():
    rec = run(["0,5000000000", "0,4250000000"])
    assert fields(rec)["gross_amount_per_share"]["corroboration_status"] == "NO_INDEPENDENT_SOURCE"
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_circular_corroboration_is_rejected():
    # sem ISIN no aviso; a identidade de nível 2 encontra a linha PELO PRÓPRIO ticker, e o CNPJ tem duas linhas (ON e PN):
    # nada independente confirma qual classe foi lida
    rec = run(["LGAT3"], text=HEADER + BODY + "Código de negociação LGAT3\n", golden=GOLD_TWO_CLASSES)
    assert rec["identity"]["identity_method"] == "TICKER_AND_CNPJ_EXACT"
    f = fields(rec)["ticker"]
    assert f["corroboration_status"] == "NO_INDEPENDENT_SOURCE" and rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_conflicting_corroboration_goes_to_review():
    rec = run(["LGAT4"], text=HEADER + BODY + "Código de negociação LGAT4 (ISIN BRLGATACNOR6)\n", golden=GOLD_TWO_CLASSES)
    f = fields(rec)["ticker"]
    assert f["corroboration_status"] == "CONFLICT" and f["reference_value"] == "LGAT3"
    assert "CRITICAL_FIELD_UNCERTAIN_CONFLICT" in rec["routing"]["reason_codes"]


def test_uncertain_event_type_evidence_goes_to_review():
    rec = run(["juros"])
    assert rec["perception_uncertainty"]["event_type"]["blocking_reason"] == "CRITICAL_FIELD_UNCERTAIN_UNCORROBORATED"
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_filler_is_ignored_and_unlocated_numeric_token_blocks():
    rec = run([",,,,,,"])
    assert rec["routing"]["decision"] == "AUTO_APPROVE" and rec["perception_uncertainty"]["ignored_non_alphanumeric_tokens"]
    rec = run(["0,4260000000"])
    assert "UNCERTAIN_TOKEN_UNLOCATED" in rec["routing"]["reason_codes"]


def test_perception_without_uncertainty_channel_is_not_assessed():
    rec = run(None)                                   # ex.: OCR local, que não declara tokens incertos
    assert "perception_uncertainty" not in rec and rec["routing"]["decision"] == "AUTO_APPROVE"


@pytest.mark.parametrize("variant", ["I"])
def test_variant_i_ignores_uncertainty(variant):
    assert run(["30/10/2026"], variant=variant)["routing"]["decision"] == "AUTO_APPROVE"   # o problema do E-009
