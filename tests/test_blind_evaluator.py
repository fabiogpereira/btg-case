"""Avaliador do blind test: mapeamentos pré-registrados, testados com dados sintéticos (sem processar o blind set)."""
from evaluation.blind import event_match, objective_rules, value_match


def f(status="present", value=None, **kw):
    return {"status": status, "value": value, "evidence": "x", **kw}


def got(value, status="found"):
    return {"status": status, "value": value}


def test_values_compare_numerically_and_map_formats():
    assert value_match("gross_amount_per_share", f(value="0.45"), got("0.4500000000"))
    assert not value_match("gross_amount_per_share", f(value="0.45"), got("0.4600000000"))
    assert value_match("record_date", f(value="2026-10-13"), got("2026-10-13"))
    assert value_match("withholding_tax", f(rate="0.15", base="NOT_STATED"), got({"rate": "0.150", "base": None}))
    assert not value_match("withholding_tax", f(rate="0.15", base="GROSS_AMOUNT"), got({"rate": "0.15", "base": None}))
    assert value_match("ratio", f(value={"from": "10", "to": "1"}), got({"shares_before": "10", "shares_after": "1"}))
    assert value_match("ratio", f(value={"held": "20", "new": "1"}), got({"shares_held": "20", "bonus_shares": "1", "percentage": "0.05"}))
    assert not value_match("record_date", f(value="2026-10-13"), got(None, "not_found"))


def test_event_type_mapping():
    assert event_match("JCP", "JCP") and not event_match("JCP", "DIVIDEND")
    assert event_match("UNRESOLVED", None) and event_match("OTHER", None) and not event_match("OTHER", "DIVIDEND")


def test_objective_rules_recomputed_from_ground_truth_values():
    case = {"issuer": {"in_reference_base": True}, "fields": {
        "approval_date": f(value="2026-10-01"), "record_date": f(value="2026-10-13"), "ex_date": f(value="2026-10-14"),
        "payment_date": f(value="2026-10-10"), "share_credit_date": f("not_applicable"),
        "gross_amount_per_share": f(value="0.20"), "net_amount_per_share": f(value="0.165"),
        "withholding_tax": f(rate="0.175", base="GROSS_AMOUNT"), "ratio": f("not_applicable")}}
    r = objective_rules(case)
    assert r["REF_ISIN_FOUND"] == "PASS" and r["DATE_SETTLEMENT_NOT_BEFORE_EX"] == "FAIL"
    assert r["AMOUNT_NET_MATCHES_GROSS_AND_TAX"] == "PASS" and r["DATE_RECORD_BEFORE_EX"] == "PASS"
