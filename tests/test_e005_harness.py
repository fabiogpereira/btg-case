"""Harness do E-005 exercitado sobre os artefatos congelados da D (E-004) e sobre um registro E sintético."""
from conftest import ROOT

from evaluation.e005 import _expected_routing, qualifier_metrics, qualifiers_of, stability

E004 = ROOT / "outputs" / "experiments" / "E-004_hybrid"


def test_d_qualifier_metrics_reproduce_known_e004_failure_modes():
    exp = _expected_routing()
    orig = qualifier_metrics(E004 / "original_D", "D", exp)
    assert "06_petroquimica_litoral_grupamento.pdf" in orig["false_qualifier_blocks"]
    ch = qualifier_metrics(E004 / "challenge_D", "D", exp)
    assert "CH-07.txt" in ch["false_qualifier_blocks"]
    assert "CH-11.txt" not in ch["false_qualifier_blocks"]           # bloqueio justificado (revisão esperada)


def test_d_stability_detects_ch07_routing_change():
    s = stability(E004 / "challenge_D", E004 / "challenge_D_run2", "D")
    assert "CH-07.txt" in [u["document"] for u in s["unstable"]]


def test_e_view_separates_material_from_notes():
    rec = {"routing": {"decision": "AUTO_APPROVE"}, "semantic": {
        "material_qualifiers": [{"kind": "material_condition", "affects": "tax_base", "target_field": "withholding_tax",
                                 "blocks": False, "source": "llm", "quote": "q"}],
        "semantic_notes": [{"kind": "operational_instruction", "quote": "n", "source": "llm"},
                           {"kind": "scope_guard_rejected", "quote": "l", "source": "llm"}]}}
    q = qualifiers_of(rec, "E")
    assert len(q["material"]) == 1 and len(q["non_material"]) == 2 and not q["blocking"] and len(q["scope_guard_rejected"]) == 1
