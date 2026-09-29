"""Consulta ao golden records: chave exata, sem fuzzy match (D-008)."""
import hashlib

from conftest import GOLDEN


def test_golden_records_loaded_with_identity(golden):
    assert len(golden.rows) == 12
    assert golden.sha256 == hashlib.sha256(GOLDEN.read_bytes()).hexdigest()


def test_exact_isin_lookup_returns_row(golden):
    ref = golden.lookup_by_isin("BRTIETACNOR3")
    assert ref["found"] and ref["matched_by"] == "isin"
    assert ref["row"]["ticker"] == "TIET3" and ref["row"]["cnpj"] == "12.345.678/0001-90"


def test_lookup_normalizes_case_and_whitespace_only(golden):
    assert golden.lookup_by_isin("  brtietacnor3 ")["found"]


def test_issuer_outside_reference_is_not_found(golden):
    ref = golden.lookup_by_isin("BRCNHZACNOR5")  # doc 08
    assert not ref["found"] and ref["row"] is None


def test_one_character_perturbation_never_matches(golden):
    for row in golden.rows:
        isin = row["isin"]
        perturbed = isin[:-1] + ("0" if isin[-1] != "0" else "1")
        assert not golden.lookup_by_isin(perturbed)["found"]


def test_missing_isin_is_not_a_lookup(golden):
    ref = golden.lookup_by_isin(None)
    assert not ref["found"] and ref["query"] is None
