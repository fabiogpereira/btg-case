"""Identidade do documento, camada de texto, not_applicable / declared_pending e invariantes de segurança."""
import hashlib
import json
import shutil

import pytest
from conftest import DOCS, GOLDEN, ROOT

from corporate_actions.ingestion import ingest, read_text_layer
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import process_document, run_batch
from corporate_actions.reference import load_golden_records

GT_INDEX = json.loads((ROOT / "tests" / "ground_truth" / "index.json").read_text(encoding="utf-8"))
PDFS = sorted(DOCS.glob("*.pdf"))


def by_hash(sha):
    return next(p for p in PDFS if hashlib.sha256(p.read_bytes()).hexdigest() == sha)


def gt_for(path):
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    entry = next(e for e in GT_INDEX["documents"] if e["sha256"] == sha)
    return json.loads((ROOT / "tests" / "ground_truth" / entry["ground_truth_file"]).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    out = tmp_path_factory.mktemp("run")
    run_batch(DOCS, GOLDEN, out, run_id="test-run")
    return {json.loads(p.read_text(encoding="utf-8"))["document"]["sha256"]: json.loads(p.read_text(encoding="utf-8"))
            for p in (out / "records").glob("*.json")}, json.loads((out / "run_manifest.json").read_text(encoding="utf-8"))


# --- Identidade (D-004) ------------------------------------------------------------------------

@pytest.mark.parametrize("path", PDFS, ids=lambda p: p.stem[:2])
def test_document_identity_is_content_sha256(path):
    assert ingest(path).sha256 == hashlib.sha256(path.read_bytes()).hexdigest()


def _without_run_specific(record):
    rec = json.loads(json.dumps(record))
    rec["document"].pop("file_name")
    rec.pop("audit")
    return rec


@pytest.mark.parametrize("path", PDFS, ids=lambda p: p.stem[:2])
def test_renaming_the_file_does_not_change_any_result(path, tmp_path):
    """H-21 / D-004: o nome do arquivo não influencia extração, validação nem roteamento."""
    golden = load_golden_records(GOLDEN)
    anonymous = tmp_path / (hashlib.sha256(path.read_bytes()).hexdigest()[:16] + ".pdf")
    shutil.copy(path, anonymous)
    original = to_jsonable(process_document(path, golden, "r"))
    renamed = to_jsonable(process_document(anonymous, golden, "r"))
    assert _without_run_specific(original) == _without_run_specific(renamed)


# --- Camada de texto (D-011) ---------------------------------------------------------------------

@pytest.mark.parametrize("entry", GT_INDEX["documents"], ids=lambda e: e["ground_truth_file"])
def test_text_layer_detection_matches_ground_truth(entry):
    path = by_hash(entry["sha256"])
    expected = gt_for(path)["document"]["text_layer"] == "native"
    assert read_text_layer(ingest(path)).usable is expected


def test_document_without_text_layer_is_an_explicit_failure_mode(batch):
    records, _ = batch
    no_text = [r for r in records.values() if not r["document"]["text_layer"]["usable"]]
    assert len(no_text) == 1
    rec = no_text[0]
    assert rec["extraction"] == {"method": None, "status": "NOT_POSSIBLE", "failure_mode": "NO_USABLE_TEXT_LAYER",
                                 "unsupported_fields": []}
    assert rec["fields"] == {}                       # nenhuma afirmação sobre o conteúdo
    assert rec["routing"]["reason_codes"] == ["NO_USABLE_TEXT_LAYER"]
    assert [s["status"] for s in rec["audit"]["stages"] if s["stage"] == "validate"] == ["skipped"]


# --- not_applicable / declared_pending --------------------------------------------------------

def test_declared_pending_payment_is_captured_with_evidence(batch):
    records, _ = batch
    pending = [(r, r["fields"]["payment_date"]) for r in records.values()
               if r["fields"].get("payment_date", {}).get("status") == "declared_pending"]
    assert len(pending) == 1
    rec, field = pending[0]
    assert field["value"] is None and field["evidence"] and field["confidence"] == "HIGH"
    assert "PAYMENT_DATE_PENDING" in rec["routing"]["reason_codes"]


def test_non_cash_events_mark_cash_fields_not_applicable(batch):
    records, _ = batch
    share_events = [r for r in records.values()
                    if (r.get("classification") or {}).get("event_type") in ("BONUS_SHARES", "REVERSE_SPLIT")]
    assert share_events
    for rec in share_events:
        for name in ("currency", "gross_amount_per_share", "payment_date"):
            assert rec["fields"][name]["status"] == "not_applicable", (rec["document"]["file_name"], name)


# --- Invariantes de segurança -----------------------------------------------------------------

def test_no_value_is_invented_where_the_document_has_none(batch):
    """Todo campo que o gabarito diz ausente/pendente/não aplicável não pode sair com valor."""
    records, _ = batch
    invented = []
    for sha, rec in records.items():
        gt = gt_for(by_hash(sha))
        got = {**rec["fields"], **rec["event_specific_fields"]}
        truth = {**gt["document_truth"]["fields"], **gt["document_truth"]["event_specific_fields"]}
        for name, exp in truth.items():
            if exp["status"] != "found" and got.get(name, {}).get("status") == "found":
                invented.append((rec["document"]["file_name"], name, got[name]["value"]))
    assert not invented


def test_every_found_value_has_literal_evidence_in_document(batch):
    records, _ = batch
    for sha, rec in records.items():
        if not rec["document"]["text_layer"]["usable"]:
            continue
        text = read_text_layer(ingest(by_hash(sha))).normalized_text
        for name, f in {**rec["fields"], **rec["event_specific_fields"]}.items():
            if f["status"] in ("found", "declared_pending"):
                assert f["evidence"], name
                for ev in f["evidence"]:
                    assert text[ev["start"]:ev["end"]] == ev["text"], name


def test_batch_runs_without_errors_and_audits_every_document(batch):
    records, manifest = batch
    assert manifest["summary"]["documents"] == len(PDFS) and manifest["summary"]["errors"] == 0
    for rec in records.values():
        audit = rec["audit"]
        assert audit["run_id"] == "test-run" and audit["pipeline_version"]
        assert audit["model"] is None and audit["prompt_version"] is None
        assert audit["final_decision"] == rec["routing"]["decision"]
        assert all(s["duration_us"] is not None for s in audit["stages"])
