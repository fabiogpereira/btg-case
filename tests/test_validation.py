"""Validation engine: PASS / FAIL / NOT_EVALUATED, sem confundir ausência com falha."""
import datetime as dt
from decimal import Decimal

from conftest import MISSING, NA, PENDING, make_record

from corporate_actions.validation import validate


def results(rec, golden):
    out, not_applicable, _ = validate(rec, golden)
    return {v.rule_id: v for v in out}, not_applicable


def test_clean_jcp_record_passes_everything(golden):
    res, _ = results(make_record(), golden)
    assert {v.status for v in res.values()} == {"PASS"}


def test_net_check_records_decimal_audit_fields(golden):
    res, _ = results(make_record(), golden)
    obs = res["AMOUNT_NET_MATCHES_GROSS_AND_TAX"].observed
    assert obs["declared_value"] == Decimal("0.1434196500")
    assert obs["calculated_value"] == Decimal("0.1434196500")
    assert obs["comparison_precision"] == 10 and obs["rounding_rule"] is None


def test_net_inconsistency_fails(golden):
    res, _ = results(make_record(net_amount_per_share=Decimal("0.1434196600")), golden)
    assert res["AMOUNT_NET_MATCHES_GROSS_AND_TAX"].status == "FAIL"


def test_payment_before_ex_fails_but_other_date_rules_pass(golden):  # padrão do doc 05
    res, _ = results(make_record(payment_date=dt.date(2026, 6, 10)), golden)
    assert res["DATE_SETTLEMENT_NOT_BEFORE_EX"].status == "FAIL"
    assert res["DATE_RECORD_BEFORE_EX"].status == "PASS"


def test_declared_pending_is_not_missing_and_dependent_rules_are_not_evaluated(golden):  # padrão do doc 04 (D-005)
    res, _ = results(make_record(payment_date=PENDING), golden)
    assert res["REQUIRED_FIELDS_PRESENT"].status == "PASS"
    assert res["REQUIRED_FIELDS_NOT_PENDING"].status == "FAIL"
    assert res["REQUIRED_FIELDS_NOT_PENDING"].observed["declared_pending"] == ["payment_date"]
    assert res["DATE_SETTLEMENT_NOT_BEFORE_EX"].status == "NOT_EVALUATED"


def test_not_found_required_field_fails_completeness_but_never_fails_dependent_rules(golden):
    res, _ = results(make_record(ex_date=MISSING), golden)
    assert res["REQUIRED_FIELDS_PRESENT"].status == "FAIL"
    for rule in ("DATE_RECORD_BEFORE_EX", "DATE_EX_NEXT_WEEKDAY_AFTER_RECORD", "DATE_SETTLEMENT_NOT_BEFORE_EX"):
        assert res[rule].status == "NOT_EVALUATED", rule
        assert "ex_date" in res[rule].message


def test_not_applicable_net_for_dividend_is_not_evaluated_not_failed(golden):
    rec = make_record(event_type="DIVIDEND", net_amount_per_share=NA, withholding_tax=MISSING)
    res, _ = results(rec, golden)
    assert res["AMOUNT_NET_MATCHES_GROSS_AND_TAX"].status == "NOT_EVALUATED"
    assert res["REQUIRED_FIELDS_PRESENT"].status == "PASS"   # líquido e IR não são obrigatórios em dividendo


def test_reference_not_found_makes_dependent_reference_rules_not_evaluated(golden):
    res, _ = results(make_record(isin="BRCNHZACNOR5"), golden)
    assert res["REF_ISIN_FOUND"].status == "FAIL"
    for rule in ("REF_TICKER_CONSISTENT", "REF_CNPJ_CONSISTENT", "REF_SHARE_CLASS_CONSISTENT", "REF_ISSUER_ACTIVE"):
        assert res[rule].status == "NOT_EVALUATED", rule


def test_reference_mismatch_is_detected(golden):
    res, _ = results(make_record(ticker="BMRD3"), golden)
    assert res["REF_TICKER_CONSISTENT"].status == "FAIL"


def test_share_class_not_stated_is_not_evaluated(golden):
    res, _ = results(make_record(share_class=MISSING), golden)
    assert res["REF_SHARE_CLASS_CONSISTENT"].status == "NOT_EVALUATED"


def test_title_conflict_fails_classification_consistency(golden):  # padrão do doc 03
    res, _ = results(make_record(title_types=["DIVIDEND"]), golden)
    assert res["CLASSIFICATION_TITLE_CONSISTENT"].status == "FAIL"


def test_share_event_skips_cash_rules_and_checks_ratio(golden):
    ratio = {"shares_held": Decimal("20"), "bonus_shares": Decimal("1"), "percentage": Decimal("0.05")}
    rec = make_record(event_type="BONUS_SHARES", payment_date=NA, gross_amount_per_share=NA, net_amount_per_share=NA,
                      withholding_tax=NA, currency=NA, ratio=ratio, share_credit_date=dt.date(2026, 6, 26))
    res, not_applicable = results(rec, golden)
    assert "amounts" in not_applicable and "AMOUNT_NET_MATCHES_GROSS_AND_TAX" not in res
    assert res["RATIO_PERCENTAGE_CONSISTENT"].status == "PASS"
    assert res["DATE_SETTLEMENT_NOT_BEFORE_EX"].observed["settlement_field"] == "share_credit_date"


def test_inconsistent_bonus_percentage_fails(golden):
    ratio = {"shares_held": Decimal("20"), "bonus_shares": Decimal("1"), "percentage": Decimal("0.10")}
    rec = make_record(event_type="BONUS_SHARES", ratio=ratio, payment_date=NA, gross_amount_per_share=NA,
                      net_amount_per_share=NA, withholding_tax=NA, currency=NA)
    res, _ = results(rec, golden)
    assert res["RATIO_PERCENTAGE_CONSISTENT"].status == "FAIL"


def test_unknown_event_type_never_fails_type_dependent_rules(golden):
    res, _ = results(make_record(event_type=None, title_types=[]), golden)
    assert res["CLASSIFICATION_DETERMINED"].status == "FAIL"
    assert res["REQUIRED_FIELDS_PRESENT"].status == "NOT_EVALUATED"
    assert res["CLASSIFICATION_TITLE_CONSISTENT"].status == "NOT_EVALUATED"


def test_ex_date_weekday_rule_is_only_a_warning(golden):  # D-006: sem calendário de feriados
    res, _ = results(make_record(ex_date=dt.date(2026, 6, 18)), golden)
    rule = res["DATE_EX_NEXT_WEEKDAY_AFTER_RECORD"]
    assert rule.status == "FAIL" and rule.severity == "WARNING"
