"""Variante H (E-008): seleção do melhor par rótulo -> valor com rótulos repetidos. Textos sintéticos próprios."""
from decimal import Decimal

import pytest
from conftest import GOLDEN
from test_hardened_variant_f import Fake, v3

from corporate_actions.binding import apply_safe_binding
from corporate_actions.binding_v2 import apply_best_binding
from corporate_actions.confidence import score_field
from corporate_actions.extraction import extract_candidates
from corporate_actions.hardening import extra_candidates
from corporate_actions.ingestion import ingest, read_text_layer
from corporate_actions.models import LOW, to_jsonable
from corporate_actions.normalization import resolve_field
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.profiles import DETERMINISTIC_PROFILE
from corporate_actions.reference import load_golden_records

GOLD = load_golden_records(GOLDEN)


@pytest.fixture(autouse=True)
def v2():
    token = DETERMINISTIC_PROFILE.set("v2")
    yield
    DETERMINISTIC_PROFILE.reset(token)


def bind(tmp_path, body, name, binder=apply_best_binding, event_type="DIVIDEND"):
    p = tmp_path / "h.txt"
    p.write_text(body, encoding="utf-8")
    tl = read_text_layer(ingest(p))
    ex = extract_candidates(tl)
    extra_candidates(ex, tl)
    audit = binder(ex, tl)
    return resolve_field(name, ex, event_type), [a for a in audit if a["field"] == name]


REPEATED = "Os direitos seguem a data com informada. Data com: 05/05/2027\n"


def test_repeated_label_far_invalid_and_near_valid_picks_the_near_one(tmp_path):
    f, audit = bind(tmp_path, REPEATED, "record_date")
    assert f.value.isoformat() == "2027-05-05"
    assert [(a["decision"], a["reason"]) for a in audit] == [("REJECTED", "CROSSES_SENTENCE"), ("BOUND", None)]


def test_same_text_under_binding_v1_loses_the_correct_value(tmp_path):
    f, _ = bind(tmp_path, REPEATED, "record_date", binder=apply_safe_binding)
    assert f.status == "not_found"          # defeito do E-007 que a H corrige


def test_two_valid_labels_for_the_same_value_keep_the_nearest(tmp_path):
    f, audit = bind(tmp_path, "Data-base (data-base): 12/03/2027\n", "record_date")
    assert f.value.isoformat() == "2027-03-12" and f.distinct_values == 1
    assert sorted(a["decision"] for a in audit) == ["BOUND", "SUPERSEDED"]
    bound = next(a for a in audit if a["decision"] == "BOUND")
    assert bound["gap_chars"] < next(a for a in audit if a["decision"] == "SUPERSEDED")["gap_chars"]


def test_two_equally_plausible_different_values_stay_ambiguous(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento: 10/06/2027\nProventos de junho\nData de pagamento: 17/06/2027\n", "payment_date")
    score_field(f)
    assert f.distinct_values == 2 and f.confidence == LOW          # sem vencedor claro -> não resolvido
    assert [a["decision"] for a in audit] == ["BOUND", "BOUND"]


def test_label_before_value(tmp_path):
    f, audit = bind(tmp_path, "Data ex: 14/10/2026\n", "ex_date")
    assert f.value.isoformat() == "2026-10-14" and audit[0]["decision"] == "BOUND"


def test_label_after_value_binds_to_that_value_only(tmp_path):
    f, audit = bind(tmp_path, "Posições registradas até 03.02.2027 (data com); negócios ex desde 04.02.2027.\n", "record_date")
    assert f.value.isoformat() == "2027-02-03"
    assert {a["reason"] for a in audit} == {"LABEL_ANNOTATES_PRECEDING_VALUE", "VALUE_FOLLOWED_BY_PARENTHETICAL_LABEL"}


def test_other_label_between_label_and_value(tmp_path):
    f, audit = bind(tmp_path, "Data com\nData ex 14/10/2026\n", "record_date")
    assert f.status == "not_found" and audit[0]["reason"] == "CROSSES_OTHER_FIELD_CUE"


def test_candidates_on_different_lines_choose_the_structurally_closest(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento\n(conforme cronograma)\nData de pagamento\n30/06/2027\n", "payment_date")
    assert f.value.isoformat() == "2027-06-30" and f.distinct_values == 1
    bound = next(a for a in audit if a["decision"] == "BOUND")
    assert bound["evidence"].startswith("Data de pagamento 30/06/2027") and bound["crosses_line"] is True


def test_pending_declaration_is_kept(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento: a definir\n", "payment_date")
    assert f.status == "declared_pending" and audit[0]["rule_id"].endswith(".pending")


def test_repeated_money_label_prefers_the_valid_near_binding(tmp_path):
    f, audit = bind(tmp_path, "O conselho fixou o valor bruto. Valor bruto por ação: R$ 1,2000000000\n", "gross_amount_per_share")
    assert f.value == Decimal("1.2000000000")
    assert [a["decision"] for a in audit] == ["REJECTED", "BOUND"]


def test_ambiguity_routes_to_review_end_to_end(tmp_path):
    p = tmp_path / "amb.txt"
    p.write_text("LOGÍSTICA ATLÂNTICO S.A.\nCompanhia Aberta | CNPJ/ME nº 77.888.999/0001-46\nAVISO AOS ACIONISTAS — Dividendos\n"
                 "A Logística Atlântico S.A. comunica que o Conselho de Administração aprovou, em reunião realizada em "
                 "01/10/2026, a distribuição de dividendos.\nValor bruto por ação ON R$ 0,5000000000\nData-base: 13/10/2026\n"
                 "Data ex: 14/10/2026\nData de pagamento: 30/10/2026\nParcela complementar\nData de pagamento: 06/11/2026\n"
                 "Código de negociação LGAT3 (ISIN BRLGATACNOR6)\n", encoding="utf-8")
    rec = to_jsonable(process_document(p, GOLD, "t", "H", SemanticContext(Fake(v3("DIVIDEND", ["distribuição de dividendos"])))))
    assert rec["fields"]["payment_date"]["distinct_values"] == 2
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED" and "LOW_EXTRACTION_CONFIDENCE" in rec["routing"]["reason_codes"]
    assert rec["schema_version"] == "semantic-record/0.6"
