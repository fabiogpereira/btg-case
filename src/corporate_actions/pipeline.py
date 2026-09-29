"""Orquestrador do Baseline A.

ingest -> text layer -> extract candidates -> classify -> normalize/resolve -> confidence
       -> validate (todas as regras obrigatórias) -> route -> registro + audit
"""
import json
import platform
from collections import Counter
from pathlib import Path

import pypdf

from . import PIPELINE_VERSION
from .audit import DocumentAudit, new_run_id, utc_now
from .classification import classify
from .confidence import score_all
from .extraction import extract_candidates
from .ingestion import MIN_ALNUM_CHARS_PER_PAGE, ingest, read_text_layer
from .models import to_jsonable
from .normalization import resolve_all
from .reference import GoldenRecords, load_golden_records
from .routing import REVIEW_REQUIRED, route
from .schema import ALWAYS_REQUIRED, REQUIRED
from .validation import CandidateRecord, validate

EXTRACTION_METHOD = "native_text_layer+deterministic_rules"
RECORD_SCHEMA_VERSION = "baseline-a-record/0.1"


def process_document(path: Path, golden: GoldenRecords, run_id: str) -> dict:
    audit = DocumentAudit(run_id, PIPELINE_VERSION)
    record = {"schema_version": RECORD_SCHEMA_VERSION}
    try:
        with audit.stage("ingest"):
            doc = ingest(path)
        record["document"] = {"sha256": doc.sha256, "file_name": doc.file_name, "size_bytes": doc.size_bytes}

        with audit.stage("text_layer"):
            tl = read_text_layer(doc)
        record["document"].update(pages=tl.pages, text_layer={
            "usable": tl.usable, "alnum_chars": tl.alnum_chars,
            "min_alnum_chars_per_page": tl.min_alnum_chars_per_page, "reason": tl.reason})

        if not tl.usable:
            for name in ("extract_candidates", "classify", "normalize", "confidence", "validate"):
                audit.skip(name, "NO_USABLE_TEXT_LAYER")
            record["extraction"] = {"method": None, "status": "NOT_POSSIBLE", "failure_mode": "NO_USABLE_TEXT_LAYER",
                                    "unsupported_fields": []}
            record.update(classification=None, fields={}, event_specific_fields={}, reference_check=None,
                          validations=[], rule_groups_not_applicable=[])
            with audit.stage("route"):
                record["routing"] = route(False, [], {}, [])
            return record

        with audit.stage("extract_candidates"):
            extraction = extract_candidates(tl)
        with audit.stage("classify"):
            classification = classify(extraction)
        with audit.stage("normalize"):
            fields, specific = resolve_all(extraction, classification.event_type)
        with audit.stage("confidence"):
            score_all(fields, specific)
        with audit.stage("validate") as st:
            candidate = CandidateRecord(classification, fields, specific)
            validations, not_applicable, ref = validate(candidate, golden)
            st["rules_executed"] = len(validations)
        required = REQUIRED.get(classification.event_type, ALWAYS_REQUIRED)
        with audit.stage("route"):
            routing = route(True, validations, {**fields, **specific}, required)

        record["extraction"] = {"method": EXTRACTION_METHOD, "status": "COMPLETED", "failure_mode": None,
                                "unsupported_fields": extraction.unsupported_fields, "title": extraction.title}
        record["classification"] = classification
        record["fields"] = fields
        record["event_specific_fields"] = specific
        record["reference_check"] = {"found": ref["found"], "matched_by": ref["matched_by"], "query": ref["query"],
                                     "golden_row": ref["row"]}
        record["validations"] = validations
        record["validation_summary"] = dict(Counter(v.status for v in validations))
        record["rule_groups_not_applicable"] = not_applicable
        record["routing"] = routing
        return record
    except Exception as exc:
        if not audit.errors:   # exceção fora de um estágio
            audit.errors.append({"stage": None, "type": type(exc).__name__, "message": str(exc)})
        record["routing"] = {"decision": REVIEW_REQUIRED, "reason_codes": ["PROCESSING_ERROR"],
                             "explanations": [e["message"] for e in audit.errors]}
        return record
    finally:
        audit.finish()
        validators = [v.rule_id for v in record.get("validations", [])]
        record["audit"] = audit.to_dict(
            extraction_method=(record.get("extraction") or {}).get("method"),
            model=None, prompt_version=None,       # Baseline A: sem LLM
            validators_executed=validators,
            final_decision=(record.get("routing") or {}).get("decision"),
            reason_codes=(record.get("routing") or {}).get("reason_codes"))


def _exceptions_report(run_id: str, records: list[dict]) -> str:
    lines = [f"# Relatório de exceções — run `{run_id}`", "",
             f"Pipeline `{PIPELINE_VERSION}`. Documentos processados: {len(records)}. "
             f"Aprovados automaticamente: {sum(r['routing']['decision'] == 'AUTO_APPROVE' for r in records)}. "
             f"Para revisão: {sum(r['routing']['decision'] != 'AUTO_APPROVE' for r in records)}.", "",
             "| Documento | SHA-256 | Decisão | Motivos | Regras com falha |", "|---|---|---|---|---|"]
    for r in records:
        if r["routing"]["decision"] == "AUTO_APPROVE":
            continue
        failed = [v["rule_id"] for v in r.get("validations", []) if v["status"] == "FAIL"]
        lines.append(f"| {r['document']['file_name']} | `{r['document']['sha256'][:12]}` | {r['routing']['decision']} "
                     f"| {', '.join(r['routing']['reason_codes'])} | {', '.join(failed) or '—'} |")
    lines += ["", "Detalhe de cada motivo em `records/<documento>.json` → `routing.explanations` e `validations`."]
    return "\n".join(lines) + "\n"


def run_batch(documents_dir: Path, golden_path: Path, out_dir: Path, run_id: str | None = None) -> dict:
    run_id = run_id or new_run_id()
    started = utc_now()
    golden = load_golden_records(golden_path)
    records_dir = out_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    records, outputs = [], []
    for path in sorted(documents_dir.glob("*.pdf")):
        record = to_jsonable(process_document(path, golden, run_id))
        target = records_dir / f"{path.stem}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append(record)
        outputs.append(str(target.relative_to(out_dir)).replace("\\", "/"))
    (out_dir / "exceptions_report.md").write_text(_exceptions_report(run_id, records), encoding="utf-8")
    manifest = {
        "run_id": run_id, "pipeline_version": PIPELINE_VERSION, "record_schema_version": RECORD_SCHEMA_VERSION,
        "started_at": started, "finished_at": utc_now(),
        "environment": {"python": platform.python_version(), "pypdf": pypdf.__version__},
        "config": {"min_alnum_chars_per_page": MIN_ALNUM_CHARS_PER_PAGE, "extraction_method": EXTRACTION_METHOD,
                   "llm": None, "ocr": None, "holiday_calendar": None},
        "golden_records": {"path": str(golden_path).replace("\\", "/"), "sha256": golden.sha256, "rows": len(golden.rows)},
        "inputs": [{"file_name": r["document"]["file_name"], "sha256": r["document"]["sha256"]} for r in records],
        "outputs": outputs + ["exceptions_report.md"],
        "summary": {"documents": len(records),
                    "decisions": dict(Counter(r["routing"]["decision"] for r in records)),
                    "without_usable_text_layer": sum(not r["document"].get("text_layer", {}).get("usable", False) for r in records),
                    "errors": sum(len(r["audit"]["errors"]) for r in records),
                    "total_duration_us": sum(r["audit"]["duration_us"] or 0 for r in records)},
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
