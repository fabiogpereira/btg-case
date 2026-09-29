"""Integridade do gabarito manual (tests/ground_truth).

Garante que o gabarito está ancorado nos documentos (evidência literal, identidade por hash)
e que as expectativas de validação são coerentes com os próprios valores do gabarito.
Não depende do pipeline.
"""
import csv
import datetime as dt
import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path

import pypdf
import pytest

ROOT = Path(__file__).resolve().parents[1]
GT_DIR = ROOT / "tests" / "ground_truth"
INDEX = json.loads((GT_DIR / "index.json").read_text(encoding="utf-8"))
DOCS_DIR = ROOT / INDEX["case_documents_dir"]
GOLDEN_PATH = ROOT / INDEX["golden_records_path"]

COMMON_FIELDS = {
    "issuer_name", "cnpj", "isin", "ticker", "share_class", "approval_date", "record_date", "ex_date",
    "payment_date", "gross_amount_per_share", "net_amount_per_share", "withholding_tax", "currency", "ratio",
}
FIELD_STATUSES = {"found", "not_found", "not_applicable", "declared_pending"}
RULE_STATUSES = {"PASS", "FAIL", "NOT_EVALUATED"}
ROUTING_STATUSES = {"DEFINED", "PROVISIONAL", "POLICY_DEPENDENT"}


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def load_gt(entry):
    return json.loads((GT_DIR / entry["ground_truth_file"]).read_text(encoding="utf-8"))


def source_text(gt) -> str:
    doc = gt["document"]
    if doc["text_layer"] == "native":
        reader = pypdf.PdfReader(DOCS_DIR / doc["file_name"])
        return norm(" ".join(page.extract_text() for page in reader.pages))
    return norm((GT_DIR / doc["transcription_file"]).read_text(encoding="utf-8"))


def all_fields(gt):
    truth = gt["document_truth"]
    return {**truth["fields"], **truth["event_specific_fields"]}


ENTRIES = INDEX["documents"]
IDS = [e["ground_truth_file"] for e in ENTRIES]


def test_index_covers_every_case_document_exactly_once():
    case_hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in DOCS_DIR.glob("*.pdf")}
    gt_hashes = [e["sha256"] for e in ENTRIES]
    assert len(gt_hashes) == len(set(gt_hashes))
    assert set(gt_hashes) == case_hashes


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_document_identity_is_sha256(entry):
    gt = load_gt(entry)
    assert gt["document"]["sha256"] == entry["sha256"]
    pdf = DOCS_DIR / gt["document"]["file_name"]
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == entry["sha256"]


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_structure_and_field_status_consistency(entry):
    gt = load_gt(entry)
    assert gt["ground_truth_version"] == INDEX["ground_truth_version"]
    assert set(gt["document_truth"]["fields"]) == COMMON_FIELDS
    for name, field in all_fields(gt).items():
        assert field["status"] in FIELD_STATUSES, name
        if field["status"] == "found":
            assert field["value"] is not None, name
        else:
            assert field["value"] is None, name
        if field["status"] in ("found", "declared_pending"):
            assert field["evidence"], f"{name}: campo presente sem evidência"
        else:
            assert not field["evidence"], f"{name}: campo ausente com evidência"
            assert field["source_label"] is None, name


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_every_quote_and_label_is_literal_in_source(entry):
    gt = load_gt(entry)
    text = source_text(gt)
    cls = gt["document_truth"]["classification"]
    quotes = list(cls["evidence"]) + list(cls["traps"]) + [cls["source_label"]]
    for name, field in all_fields(gt).items():
        quotes += field["evidence"]
        if field.get("source_label"):
            quotes.append(field["source_label"])
    missing = [q for q in quotes if norm(q) not in text]
    assert not missing, missing


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_numeric_values_are_decimal_strings(entry):
    gt = load_gt(entry)
    for name in ("gross_amount_per_share", "net_amount_per_share"):
        field = gt["document_truth"]["fields"][name]
        if field["status"] == "found":
            assert isinstance(field["value"], str)
            Decimal(field["value"])  # não lança
            # a precisão declarada na fonte é preservada
            declared_decimals = field["raw"].split(",")[1]
            assert field["value"].split(".")[1] == declared_decimals


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_rule_and_routing_vocabulary(entry):
    gt = load_gt(entry)
    for rule in gt["validation_truth"]["rules"]:
        assert rule["expected"] in RULE_STATUSES
    routing = gt["routing_expectation"]
    assert routing["expectation_status"] in ROUTING_STATUSES
    if routing["expectation_status"] == "POLICY_DEPENDENT":
        assert routing["decision"] is None
    else:
        assert routing["decision"] in {"AUTO_APPROVE", "REVIEW_REQUIRED", "REJECT"}


def _recompute_rules(gt, golden):
    """Recalcula, a partir dos valores do próprio gabarito, as regras puramente objetivas."""
    fields = all_fields(gt)

    def v(name):
        f = fields.get(name)
        return f["value"] if f and f["status"] == "found" else None

    def d(name):
        return dt.date.fromisoformat(v(name)) if v(name) else None

    out = {}
    ref = golden.get(v("isin"))
    out["REF_ISIN_FOUND"] = "PASS" if ref else "FAIL"
    if ref:
        out["REF_TICKER_CONSISTENT"] = "PASS" if ref["ticker"] == v("ticker") else "FAIL"
        out["REF_CNPJ_CONSISTENT"] = "PASS" if ref["cnpj"] == v("cnpj") else "FAIL"
        out["REF_ISSUER_NAME_CONSISTENT"] = (
            "PASS" if norm(ref["emissor"]).casefold() == norm(v("issuer_name")).casefold() else "FAIL")
        out["REF_SHARE_CLASS_CONSISTENT"] = (
            ("PASS" if ref["classe"] == v("share_class") else "FAIL") if v("share_class") else "NOT_EVALUATED")
    approval, record, ex = d("approval_date"), d("record_date"), d("ex_date")
    settlement = d("payment_date") or d("share_credit_date")
    out["DATE_APPROVAL_NOT_AFTER_RECORD"] = "PASS" if approval <= record else "FAIL"
    out["DATE_RECORD_BEFORE_EX"] = "PASS" if record < ex else "FAIL"
    nxt = record + dt.timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += dt.timedelta(days=1)
    out["DATE_EX_NEXT_WEEKDAY_AFTER_RECORD"] = "PASS" if ex == nxt else "FAIL"
    out["DATE_SETTLEMENT_NOT_BEFORE_EX"] = ("PASS" if settlement >= ex else "FAIL") if settlement else "NOT_EVALUATED"
    if v("gross_amount_per_share") and v("net_amount_per_share"):
        rate = Decimal(v("withholding_tax")["rate"])
        calc = Decimal(v("gross_amount_per_share")) * (1 - rate)
        out["AMOUNT_NET_MATCHES_GROSS_AND_TAX"] = "PASS" if calc == Decimal(v("net_amount_per_share")) else "FAIL"
    ratio = v("ratio")
    if ratio and "percentage" in ratio:
        ok = Decimal(ratio["bonus_shares"]) == Decimal(ratio["percentage"]) * Decimal(ratio["shares_held"])
        out["RATIO_PERCENTAGE_CONSISTENT"] = "PASS" if ok else "FAIL"
    return out


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_validation_truth_matches_values(entry):
    gt = load_gt(entry)
    golden = {r["isin"]: r for r in csv.DictReader(GOLDEN_PATH.open(encoding="utf-8"))}
    expected = {r["rule_id"]: r["expected"] for r in gt["validation_truth"]["rules"]}
    recomputed = _recompute_rules(gt, golden)
    mismatches = {k: (expected[k], c) for k, c in recomputed.items() if k in expected and expected[k] != c}
    assert not mismatches
    assert gt["validation_truth"]["reference"]["golden_match"] == (recomputed["REF_ISIN_FOUND"] == "PASS")


def test_ground_truth_never_uses_filename_hints():
    """D-004: nenhuma evidência pode ser o próprio nome do arquivo."""
    for entry in ENTRIES:
        gt = load_gt(entry)
        stem = Path(gt["document"]["file_name"]).stem
        for field in all_fields(gt).values():
            for quote in field["evidence"]:
                assert stem not in quote
