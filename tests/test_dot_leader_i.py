"""Variante I (E-009): pontilhado de tabela não é fim de frase. Textos sintéticos próprios (nenhum texto do doc 07)."""
import pytest

from corporate_actions.binding_v2 import apply_best_binding, judge_dot_leader
from corporate_actions.extraction import extract_candidates
from corporate_actions.hardening import extra_candidates
from corporate_actions.ingestion import ingest, read_text_layer
from corporate_actions.normalization import resolve_field
from corporate_actions.profiles import DETERMINISTIC_PROFILE


@pytest.fixture(autouse=True)
def v2():
    token = DETERMINISTIC_PROFILE.set("v2")
    yield
    DETERMINISTIC_PROFILE.reset(token)


def bind(tmp_path, body, name, judge_fn=judge_dot_leader):
    p = tmp_path / "d.txt"
    p.write_text(body, encoding="utf-8")
    tl = read_text_layer(ingest(p))
    ex = extract_candidates(tl)
    extra_candidates(ex, tl)
    audit = apply_best_binding(ex, tl, judge_fn=judge_fn) if judge_fn else apply_best_binding(ex, tl)
    return resolve_field(name, ex, "DIVIDEND"), [a for a in audit if a["field"] == name]


def test_long_dot_leader_between_label_and_value(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento ....... 21/08/2027\n", "payment_date")
    assert f.value.isoformat() == "2027-08-21" and audit[0]["decision"] == "BOUND"


def test_five_dot_leader(tmp_path):
    f, _ = bind(tmp_path, "Data ex ..... 14/10/2026\n", "ex_date")
    assert f.value.isoformat() == "2026-10-14"


def test_spaced_dots_between_label_and_value(tmp_path):
    f, _ = bind(tmp_path, "Data-base . . . . . . 12/03/2027\n", "record_date")
    assert f.value.isoformat() == "2027-03-12"


def test_real_ellipsis_in_a_sentence_is_still_punctuation(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento... A diretoria confirmará 20/12/2026.\n", "payment_date")
    assert f.status == "not_found" and audit[0]["reason"] == "CROSSES_SENTENCE"


def test_normal_full_stop_is_still_punctuation(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento. Em 15/12/2026 haverá assembleia.\n", "payment_date")
    assert f.status == "not_found" and audit[0]["reason"] == "CROSSES_SENTENCE"


def test_table_with_several_fields_binds_each_value_to_its_own_label(tmp_path):
    body = ("Data-base .......... 22/06/2027\nData ex .......... 23/06/2027\nData de pagamento .......... 21/08/2027\n"
            "Valor bruto por ação .......... R$ 0,4000000000\n")
    got = {n: bind(tmp_path, body, n)[0].value for n in ("record_date", "ex_date", "payment_date", "gross_amount_per_share")}
    assert {k: str(v) for k, v in got.items()} == {"record_date": "2027-06-22", "ex_date": "2027-06-23",
                                                   "payment_date": "2027-08-21", "gross_amount_per_share": "0.4000000000"}


def test_same_table_on_one_line_still_never_crosses_another_field(tmp_path):
    body = "Data com .......... Data ex .......... 23/06/2027\n"
    f, audit = bind(tmp_path, body, "record_date")
    assert f.status == "not_found" and audit[0]["reason"] == "CROSSES_OTHER_FIELD_CUE"


def test_label_annotating_the_previous_value_is_still_rejected(tmp_path):
    f, _ = bind(tmp_path, "Posições registradas até 03.02.2027 (data com) ........ negócios ex desde 04.02.2027.\n", "record_date")
    assert f.value.isoformat() == "2027-02-03"          # nunca 04.02 (vem do "DATA (rótulo)")


def test_leader_with_residual_text_and_full_stop_stays_rejected(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento ......xyz. 21/08/2027\n", "payment_date")
    assert f.status == "not_found" and audit[0]["reason"] == "CROSSES_SENTENCE"      # conservador: resta "xyz. "


def test_variant_h_judge_rejects_the_same_dot_leader(tmp_path):
    f, audit = bind(tmp_path, "Data de pagamento ....... 21/08/2027\n", "payment_date", judge_fn=None)
    assert f.status == "not_found" and audit[0]["reason"] == "CROSSES_SENTENCE"      # comportamento congelado da H
