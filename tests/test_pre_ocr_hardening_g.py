"""Variante G (E-007): identidade hierárquica sem ISIN e binding conservador rótulo/valor.
Offline, textos sintéticos escritos para demonstrar os invariantes (nenhuma frase dos conjuntos BT)."""
import dataclasses
from decimal import Decimal

import pytest
from conftest import GOLDEN, found, make_record
from test_hardened_variant_f import Fake, v3

from corporate_actions import identity as ID
from corporate_actions.binding import apply_safe_binding, line_breaks
from corporate_actions.extraction import extract_candidates
from corporate_actions.hardening import extra_candidates
from corporate_actions.ingestion import ingest, read_text_layer
from corporate_actions.models import LOW, NOT_FOUND, ExtractedField, to_jsonable
from corporate_actions.normalization import resolve_field
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.profiles import DETERMINISTIC_PROFILE
from corporate_actions.reference import GoldenRecords, load_golden_records
from corporate_actions.validation import validate

GOLD = load_golden_records(GOLDEN)
MISSING = ExtractedField(status=NOT_FOUND)


# --- Identidade -------------------------------------------------------------------------------------

def ident(**overrides):
    rec = make_record(**overrides)
    return ID.resolve_identity(rec, GOLD), rec


def test_level1_isin_exact():
    r, _ = ident()
    assert r["identity_method"] == "ISIN_EXACT" and r["matched_reference"]["ticker"] == "BMRD4"


def test_level2_ticker_and_cnpj_exact_waives_isin_requirement():
    r, rec = ident(isin=MISSING)
    assert r["identity_method"] == "TICKER_AND_CNPJ_EXACT" and r["identifiers_used"] == {"ticker": "BMRD4", "cnpj": "60.111.222/0001-55"}
    results = ID.apply_identity(validate(rec, GOLD)[0], r, rec)
    by = {v.rule_id: v for v in results}
    assert by["REF_IDENTITY_RESOLVED"].status == "PASS"
    assert by["REQUIRED_FIELDS_PRESENT"].status == "PASS" and by["REQUIRED_FIELDS_PRESENT"].observed["isin_waived_by"] == "TICKER_AND_CNPJ_EXACT"
    assert by["REF_TICKER_CONSISTENT"].status == by["REF_CNPJ_CONSISTENT"].status == by["REF_ISSUER_ACTIVE"].status == "PASS"
    assert by["REF_ISIN_FOUND"].status == "NOT_EVALUATED"


def test_level2_ticker_and_issuer_exact_when_no_cnpj():
    r, _ = ident(isin=MISSING, cnpj=MISSING)
    assert r["identity_method"] == "TICKER_AND_ISSUER_EXACT"


def test_correct_ticker_with_wrong_cnpj_is_a_conflict():
    r, _ = ident(isin=MISSING, cnpj=found("99.999.999/0001-99"))
    assert r["status"] == "UNRESOLVED" and r["reason_code"] == "IDENTITY_CONFLICT"
    assert r["conflicts"] == ["TICKER_BELONGS_TO_DIFFERENT_CNPJ"]


def test_similar_but_not_exact_issuer_name_is_never_accepted():
    r, _ = ident(isin=MISSING, cnpj=MISSING, issuer_name=found("Banco Meridional S.A."))
    assert r["status"] == "UNRESOLVED" and r["conflicts"] == ["TICKER_BELONGS_TO_DIFFERENT_ISSUER"]


def test_ambiguous_ticker_in_reference_is_unresolved():
    rows = GOLD.rows + [dict(GOLD.rows[1], isin="BRXXXXACNPR1")]      # mesma ação listada duas vezes na base
    r = ID.resolve_identity(make_record(isin=MISSING), GoldenRecords(GOLD.path, "x", rows))
    assert r["status"] == "UNRESOLVED" and r["reason_code"] == "AMBIGUOUS_REFERENCE"


def test_ambiguous_issuer_in_document_is_unresolved():
    issuer = dataclasses.replace(found("Banco Meridional do Brasil S.A."), confidence=LOW)
    r, _ = ident(isin=MISSING, cnpj=MISSING, issuer_name=issuer)
    assert r["status"] == "UNRESOLVED" and r["conflicts"] == ["ISSUER_NAME_NOT_UNIQUE_IN_DOCUMENT"]


def test_ticker_alone_is_not_sufficient():
    r, _ = ident(isin=MISSING, cnpj=MISSING, issuer_name=MISSING)
    assert r["status"] == "UNRESOLVED" and r["reason_code"] == "IDENTITY_INSUFFICIENT_IDENTIFIERS"


def test_no_identifiers_at_all():
    r, _ = ident(isin=MISSING, ticker=MISSING)
    assert r["reason_code"] == "IDENTITY_INSUFFICIENT_IDENTIFIERS"


def test_isin_present_but_absent_from_reference_does_not_fall_back_to_ticker():
    r, _ = ident(isin=found("BRZZZZACNOR9"))
    assert r["status"] == "UNRESOLVED" and r["reason_code"] == "REFERENCE_NOT_FOUND"


def test_ticker_with_divergent_values_in_document_is_a_conflict():
    ticker = dataclasses.replace(found("BMRD4"), distinct_values=2)
    r, _ = ident(isin=MISSING, ticker=ticker)
    assert r["reason_code"] == "IDENTITY_CONFLICT"


def test_unresolved_identity_blocks_routing():
    routing = {"decision": "AUTO_APPROVE", "reason_codes": [], "explanations": [],
               "gates": [{"gate": "REFERENCE_VALIDATION", "status": "PASS", "reason_codes": [], "explanations": []}]}
    r, rec = ident(isin=MISSING, cnpj=found("99.999.999/0001-99"))
    out = ID.gate_identity(routing, ID.apply_identity(validate(rec, GOLD)[0], r, rec))
    assert out["decision"] == "REVIEW_REQUIRED" and "IDENTITY_CONFLICT" in out["reason_codes"]


# --- Binding ----------------------------------------------------------------------------------------

@pytest.fixture
def v2():
    token = DETERMINISTIC_PROFILE.set("v2")
    yield
    DETERMINISTIC_PROFILE.reset(token)


def bind(tmp_path, body, name="record_date", event_type="DIVIDEND"):
    p = tmp_path / "b.txt"
    p.write_text(body, encoding="utf-8")
    tl = read_text_layer(ingest(p))
    ex = extract_candidates(tl)
    extra_candidates(ex, tl)
    audit = apply_safe_binding(ex, tl)
    return resolve_field(name, ex, event_type), audit, ex


def test_label_and_value_on_same_line(v2, tmp_path):
    f, audit, _ = bind(tmp_path, "Data-base: 13/10/2026\n")
    assert f.value.isoformat() == "2026-10-13" and audit[0]["decision"] == "BOUND"


def test_label_delimiter_value(v2, tmp_path):
    f, _, _ = bind(tmp_path, "Data de pagamento – 30.10.2026\n", "payment_date")
    assert f.value.isoformat() == "2026-10-30"


def test_value_in_next_table_cell_is_accepted(v2, tmp_path):
    f, _, _ = bind(tmp_path, "Data de pagamento\n30/10/2026\n", "payment_date")
    assert f.value.isoformat() == "2026-10-30"


def test_label_followed_by_another_label_does_not_take_its_value(v2, tmp_path):
    f, audit, ex = bind(tmp_path, "Data com\nData ex 14/10/2026\n")
    assert f.status == "not_found"
    assert any(a["decision"] == "REJECTED" and a["reason"] == "CROSSES_OTHER_FIELD_CUE" for a in audit)
    assert resolve_field("ex_date", ex, "DIVIDEND").value.isoformat() == "2026-10-14"


def test_two_close_dates_each_bound_to_its_own_label(v2, tmp_path):
    f, _, ex = bind(tmp_path, "Data-base 13/10/2026 e data ex 14/10/2026.\n")
    assert f.value.isoformat() == "2026-10-13"
    assert resolve_field("ex_date", ex, "DIVIDEND").value.isoformat() == "2026-10-14"


def test_label_after_value_binds_backwards_never_forwards(v2, tmp_path):
    f, audit, _ = bind(tmp_path, "Participam os acionistas registrados em 05.03.2027 (data com); negociação ex desde 08.03.2027.\n")
    assert f.value.isoformat() == "2027-03-05"
    assert {a["reason"] for a in audit} >= {"LABEL_ANNOTATES_PRECEDING_VALUE", "VALUE_FOLLOWED_BY_PARENTHETICAL_LABEL"}


def test_dates_separated_by_a_partir_de_are_not_bound(v2, tmp_path):
    f, audit, _ = bind(tmp_path, "Posição de referência (data-base) – a partir de 16/11/2026 negociação sem direitos.\n")
    assert f.status == "not_found"
    assert audit[0]["reason"] == "CROSSES_OTHER_FIELD_CUE"


def test_closer_wrong_value_is_rejected_even_if_the_right_one_is_farther(v2, tmp_path):
    f, audit, _ = bind(tmp_path, "Valor bruto (o valor líquido de R$ 0,85 vem depois do imposto): R$ 1,00 por ação\n",
                       "gross_amount_per_share")
    assert f.status == "not_found"                         # nunca 0,85; revisão se obrigatório
    assert audit[0]["raw"] == "0,85" and audit[0]["decision"] == "REJECTED"


def test_label_across_sentence_is_not_bound(v2, tmp_path):
    f, audit, _ = bind(tmp_path, "Data de pagamento. Em 15/12/2026 haverá assembleia.\n", "payment_date")
    assert f.status == "not_found" and audit[0]["reason"] == "CROSSES_SENTENCE"


def test_label_cell_wrapping_across_lines_is_bound_and_audited(v2, tmp_path):
    f, audit, _ = bind(tmp_path, "Valor bruto por ação\npreferencial\n(PN)\nR$ 0,5500000000\nData-base\n12/01/2027\n",
                       "gross_amount_per_share")
    assert f.value == Decimal("0.5500000000")
    gross = next(a for a in audit if a["field"] == "gross_amount_per_share")
    assert gross["decision"] == "BOUND" and gross["crosses_line"] is True


def test_label_across_lines_still_rejected_when_another_field_is_crossed(v2, tmp_path):
    f, audit, _ = bind(tmp_path, "Data de pagamento\nData-base\n20/12/2026\n", "payment_date")
    assert f.status == "not_found"
    assert next(a for a in audit if a["field"] == "payment_date")["reason"] == "CROSSES_OTHER_FIELD_CUE"


def test_line_break_positions_point_to_spaces_of_the_normalized_text(tmp_path):
    p = tmp_path / "lb.txt"
    p.write_text("Linha  um\nLinha dois \n\n fim", encoding="utf-8")
    tl = read_text_layer(ingest(p))
    breaks = line_breaks(tl)
    assert all(tl.normalized_text[b] == " " for b in breaks if b < len(tl.normalized_text))
    assert [tl.normalized_text[:b].split()[-1] for b in sorted(breaks) if b < len(tl.normalized_text)] == ["um", "dois"]


# --- Ponta a ponta (G × F) ----------------------------------------------------------------------------

HEADER = "LOGÍSTICA ATLÂNTICO S.A.\nCompanhia Aberta | CNPJ/ME nº {cnpj}\nAVISO AOS ACIONISTAS — Dividendos\n"
BODY = ("A Logística Atlântico S.A. comunica que o Conselho de Administração aprovou, em reunião realizada em "
        "01/10/2026, a distribuição de dividendos.\nValor bruto por ação ON R$ 0,5000000000\nData-base: 13/10/2026\n"
        "Data ex: 14/10/2026\nData de pagamento: 30/10/2026\nCódigo de negociação LGAT3\n")


def run_doc(tmp_path, variant, cnpj="77.888.999/0001-46"):
    p = tmp_path / "n.txt"
    p.write_text(HEADER.format(cnpj=cnpj) + BODY, encoding="utf-8")
    return to_jsonable(process_document(p, GOLD, "t", variant, SemanticContext(Fake(v3("DIVIDEND", ["distribuição de dividendos"])))))


def test_without_isin_g_approves_on_exact_ticker_and_cnpj_while_f_reviews(tmp_path):
    g, f = run_doc(tmp_path, "G"), run_doc(tmp_path, "F")
    assert f["routing"]["decision"] == "REVIEW_REQUIRED" and "REQUIRED_FIELD_MISSING" in f["routing"]["reason_codes"]
    assert g["routing"]["decision"] == "AUTO_APPROVE"
    assert g["identity"]["identity_method"] == "TICKER_AND_CNPJ_EXACT" and g["identity"]["matched_reference"]["isin"] == "BRLGATACNOR6"
    assert g["schema_version"] == "semantic-record/0.5" and g["binding"]


def test_without_isin_wrong_cnpj_goes_to_review_in_g(tmp_path):
    g = run_doc(tmp_path, "G", cnpj="12.121.212/0001-21")
    assert g["routing"]["decision"] == "REVIEW_REQUIRED" and "IDENTITY_CONFLICT" in g["routing"]["reason_codes"]
