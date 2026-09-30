"""Integridade do challenge set sintético (E-003): identidade, evidência literal e separação do dataset original."""
import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CS = ROOT / "tests" / "challenge_set"
GT = json.loads((CS / "ground_truth.json").read_text(encoding="utf-8"))
CASES = GT["cases"]
ORIGINAL_DOCS = ROOT / "case" / "Case AI Dev - Envio" / "documents"


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def test_origin_is_recorded():
    assert "synthetic" in GT["origin"] and "not derived from any variant" in GT["origin"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_case_identity_and_evidence(case):
    path = CS / case["file"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == case["sha256"]
    text = norm(path.read_text(encoding="utf-8"))
    assert case["targets"] and case["categories"] and case["purpose"]
    for target in case["targets"]:
        assert target["evidence"], target
        for quote in target["evidence"]:
            assert norm(quote) in text, quote
    assert case["routing"]["expectation_status"] in {"DEFINED", "PROVISIONAL"}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["id"])
def test_file_names_carry_no_hint(case):
    assert re.fullmatch(r"cases/CH-\d{2}\.txt", case["file"])


def test_challenge_set_is_disjoint_from_original_dataset():
    original = {hashlib.sha256(p.read_bytes()).hexdigest() for p in ORIGINAL_DOCS.glob("*")}
    assert not original & {c["sha256"] for c in CASES}
    assert not list((CS / "cases").glob("*.pdf"))
