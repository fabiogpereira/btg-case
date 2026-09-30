"""Orquestrador. Variantes do E-003 compartilham extração, normalização e validação:

A  Baseline A (inalterado):  ingest -> text layer -> candidates -> classify -> normalize -> confidence
                              -> validate -> route
B  + patch semântico determinístico: classificação com negação + qualificadores -> gates
C  + intérprete semântico por LLM (grounded, com function calling) -> gates

Em todas as variantes o orchestrator executa TODAS as validações obrigatórias; nada depende de
o LLM chamar ou não uma tool (D-002).
"""
import dataclasses
import json
from decimal import Decimal
import platform
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pypdf

from . import PIPELINE_VERSION
from .audit import DocumentAudit, new_run_id, utc_now
from .classification import classify
from .confidence import score_all
from .confidence_model import confidence_view, route_gated
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
VARIANT_VERSIONS = {"A": PIPELINE_VERSION, "B": PIPELINE_VERSION + "+semantic-patch/0.1",
                    "C": PIPELINE_VERSION + "+semantic-llm/0.1"}
VARIANT_SCHEMA = {"A": RECORD_SCHEMA_VERSION, "B": "semantic-record/0.1", "C": "semantic-record/0.1"}


@dataclass
class SemanticContext:
    """Dependências da variante C: provedor de LLM (qualquer um do registro) e cache opcional."""
    provider: object
    cache: object = None


def process_document(path: Path, golden: GoldenRecords, run_id: str, variant: str = "A",
                     semantic_ctx: SemanticContext | None = None) -> dict:
    audit = DocumentAudit(run_id, VARIANT_VERSIONS[variant])
    record = {"schema_version": VARIANT_SCHEMA[variant]}
    llm_info = None
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
                record["routing"] = route(False, [], {}, []) if variant == "A" else route_gated(False, [], {}, [], {})
            return record

        with audit.stage("extract_candidates"):
            extraction = extract_candidates(tl)
        negated, cls_semantic = [], None
        with audit.stage("classify"):
            if variant == "B":
                from .semantic_patch import classification_semantics, classify_negation_aware
                classification, negated = classify_negation_aware(extraction, tl)
                cls_semantic = classification_semantics(classification, extraction, tl, negated)
                if cls_semantic.confidence == "UNRESOLVED":      # o próprio aviso adia a natureza do evento
                    classification = dataclasses.replace(classification, event_type=None,
                                                         decision_rule=f"deferred({classification.decision_rule})")
            else:
                classification = classify(extraction)

        parsed = grounding = None
        if variant == "C":
            from .semantic_llm import decide_event_type, ground, interpret
            with audit.stage("semantic_llm") as st:
                parsed, attempts = interpret(semantic_ctx.provider, tl, golden, semantic_ctx.cache)
                grounding = ground(parsed, tl) if parsed else None
                final_type, cls_semantic = decide_event_type(classification, parsed, grounding)
                llm_info = _llm_audit(semantic_ctx, attempts, parsed, grounding)
                st.update(api_calls=llm_info["api_calls"], tool_calls=len(llm_info["tool_calls"]),
                          replayed=llm_info["replayed"])
            if final_type != classification.event_type:
                classification = dataclasses.replace(
                    classification, event_type=final_type,
                    decision_rule=f"semantic_llm(deterministic={classification.decision_rule}:{classification.event_type})")

        with audit.stage("normalize"):
            fields, specific = resolve_all(extraction, classification.event_type)
        with audit.stage("confidence"):
            score_all(fields, specific)

        semantic = None
        if variant == "B":
            from .semantic_patch import assess_fields
            with audit.stage("semantic_patch"):
                semantic = {"classification": cls_semantic,
                            "fields": assess_fields(fields, specific, tl), "blocking": [],
                            "negated_signals": negated}
        elif variant == "C":
            from .semantic_llm import merge_dates, merge_withholding
            with audit.stage("semantic_merge"):
                field_sem, blocking = {}, []
                if parsed is not None:
                    field_sem = merge_dates(fields, specific, grounding, tl)
                    wt = merge_withholding(fields, grounding, tl, classification.event_type)
                    if wt is not None:
                        field_sem["withholding_tax"] = wt
                else:
                    blocking.append("SEMANTIC_INTERPRETER_FAILED")
                semantic = {"classification": cls_semantic, "fields": field_sem, "blocking": blocking}

        with audit.stage("validate") as st:
            candidate = CandidateRecord(classification, fields, specific)
            validations, not_applicable, ref = validate(candidate, golden)
            st["rules_executed"] = len(validations)
        required = REQUIRED.get(classification.event_type, ALWAYS_REQUIRED)

        if variant == "C":
            llm_info["reference_divergence"] = _reference_divergence(parsed, llm_info, validations)
        with audit.stage("route"):
            if variant == "A":
                routing = route(True, validations, {**fields, **specific}, required)
            else:
                routing = route_gated(True, validations, {**fields, **specific}, required, semantic)

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
        if semantic is not None:
            record["semantic"] = semantic
            record["confidence_view"] = {"classification": semantic["classification"],
                                         "fields": confidence_view({**fields, **specific}, semantic["fields"], validations)}
        if llm_info is not None:
            record["llm"] = llm_info
        record["routing"] = routing
        return record
    except Exception as exc:
        if not audit.errors:   # exceção fora de um estágio
            audit.errors.append({"stage": None, "type": type(exc).__name__, "message": str(exc)})
        record["routing"] = {"decision": REVIEW_REQUIRED, "reason_codes": ["PROCESSING_ERROR"],
                             "explanations": [e["message"] for e in audit.errors]}
        if llm_info is not None:
            record["llm"] = llm_info
        return record
    finally:
        audit.finish()
        validators = [v.rule_id for v in record.get("validations", [])]
        extra = {}
        if variant != "A":
            extra["variant"] = variant
        record["audit"] = audit.to_dict(
            extraction_method=(record.get("extraction") or {}).get("method"),
            model=(llm_info["served_models"] or [None])[0] if llm_info else None,
            prompt_version=(llm_info or {}).get("prompt_version"),
            validators_executed=validators,
            final_decision=(record.get("routing") or {}).get("decision"),
            reason_codes=(record.get("routing") or {}).get("reason_codes"), **extra)


def _llm_audit(ctx: SemanticContext, attempts, parsed, grounding) -> dict:
    from .llm.registry import estimate_cost_usd
    from .semantic_llm import PROMPT_VERSION, prompt_fingerprint
    cfg = ctx.provider.config
    usage = Counter()
    for a in attempts:
        usage.update(a.usage)
    served = sorted({a.served_model for a in attempts if a.served_model})
    cost = sum((estimate_cost_usd(a.served_model or cfg.model, a.usage) or Decimal(0) for a in attempts), Decimal(0))
    return {
        **cfg.public(), "prompt_version": PROMPT_VERSION, "prompt_fingerprint": prompt_fingerprint(),
        "served_models": served, "attempts": len(attempts), "api_calls": sum(a.api_calls for a in attempts),
        "replayed": all(a.replayed for a in attempts),
        "tool_calls": [dataclasses.asdict(t) for a in attempts for t in a.tool_calls],
        "usage": dict(usage), "estimated_cost_usd": cost,
        "latency_ms": sum(a.latency_ms for a in attempts),
        "errors": [e for a in attempts for e in a.errors],
        "refusals": [a.refusal for a in attempts if a.refusal is not None],
        "served_model_mismatch": any(a.served_model and a.served_model != cfg.model for a in attempts),
        # tentativas que não produziram JSON válido no schema (a última só conta se também falhou)
        "parse_or_schema_failures": len(attempts) - (1 if parsed is not None else 0),
        "request_ids": [r for a in attempts for r in a.request_ids],
        "interpretation": parsed,
        "grounding": None if grounding is None else {
            "event_grounded": grounding["event_grounded"], "total_quotes": grounding["total_quotes"],
            "grounded_quotes": grounding["grounded_quotes"], "ungrounded": grounding["ungrounded"]},
    }


def _reference_divergence(parsed, llm_info, validations) -> dict:
    """Compara a checagem de referência feita via tool pelo LLM com o validation engine (autoridade)."""
    engine = next((v.status for v in validations if v.rule_id == "REF_ISIN_FOUND"), None)
    tool_calls = [t for t in llm_info["tool_calls"] if t["name"] == "lookup_security"]
    tool_found = None
    if tool_calls and tool_calls[-1]["result"] is not None:
        tool_found = tool_calls[-1]["result"].get("found")
    reported = (parsed or {}).get("security_reference", {}).get("found_in_reference")
    engine_found = {"PASS": True, "FAIL": False}.get(engine)
    reported_found = {"YES": True, "NO": False}.get(reported)
    divergent = any(x is not None and engine_found is not None and x != engine_found for x in (tool_found, reported_found))
    return {"tool_called": bool(tool_calls), "tool_result_found": tool_found, "llm_reported": reported,
            "engine_REF_ISIN_FOUND": engine, "divergent": divergent, "authority": "validation_engine"}


def _exceptions_report(run_id: str, records: list[dict], version: str) -> str:
    lines = [f"# Relatório de exceções — run `{run_id}`", "",
             f"Pipeline `{version}`. Documentos processados: {len(records)}. "
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


def run_batch(documents_dir: Path, golden_path: Path, out_dir: Path, run_id: str | None = None, variant: str = "A",
              semantic_ctx: SemanticContext | None = None) -> dict:
    run_id = run_id or new_run_id()
    started = utc_now()
    golden = load_golden_records(golden_path)
    records_dir = out_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    records, outputs = [], []
    paths = sorted(list(documents_dir.glob("*.pdf")) + list(documents_dir.glob("*.txt")))
    for path in paths:
        record = to_jsonable(process_document(path, golden, run_id, variant, semantic_ctx))
        target = records_dir / f"{path.stem}.json"
        target.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        records.append(record)
        outputs.append(str(target.relative_to(out_dir)).replace("\\", "/"))
    version = VARIANT_VERSIONS[variant]
    (out_dir / "exceptions_report.md").write_text(_exceptions_report(run_id, records, version), encoding="utf-8")
    config = {"min_alnum_chars_per_page": MIN_ALNUM_CHARS_PER_PAGE, "extraction_method": EXTRACTION_METHOD,
              "llm": None, "ocr": None, "holiday_calendar": None}
    summary = {"documents": len(records),
               "decisions": dict(Counter(r["routing"]["decision"] for r in records)),
               "without_usable_text_layer": sum(not r["document"].get("text_layer", {}).get("usable", False) for r in records),
               "errors": sum(len(r["audit"]["errors"]) for r in records),
               "total_duration_us": sum(r["audit"]["duration_us"] or 0 for r in records)}
    if variant != "A":
        config["variant"] = variant
    if variant == "C":
        from .semantic_llm import PROMPT_VERSION, prompt_fingerprint
        config["llm"] = {**semantic_ctx.provider.config.public(), "prompt_version": PROMPT_VERSION,
                         "prompt_fingerprint": prompt_fingerprint()}
        llms = [r["llm"] for r in records if "llm" in r]
        summary["llm"] = {
            "documents_with_llm": len(llms), "api_calls": sum(x["api_calls"] for x in llms),
            "tool_calls": sum(len(x["tool_calls"]) for x in llms),
            "input_tokens": sum(x["usage"].get("input_tokens", 0) for x in llms),
            "output_tokens": sum(x["usage"].get("output_tokens", 0) for x in llms),
            "estimated_cost_usd": str(sum((Decimal(x["estimated_cost_usd"]) for x in llms), Decimal(0))),
            "llm_latency_ms": sum(x["latency_ms"] for x in llms),
            "parse_or_schema_failures": sum(x["parse_or_schema_failures"] for x in llms),
            "errors": sum(len(x["errors"]) for x in llms),
            "refusals": sum(len(x.get("refusals", [])) for x in llms),
            "served_model_mismatches": sum(bool(x.get("served_model_mismatch")) for x in llms),
            "reference_divergences": sum(bool((x.get("reference_divergence") or {}).get("divergent")) for x in llms),
            "served_models": sorted({m for x in llms for m in x["served_models"]}),
            "replayed_documents": sum(x["replayed"] for x in llms)}
    manifest = {
        "run_id": run_id, "pipeline_version": version, "record_schema_version": VARIANT_SCHEMA[variant],
        "started_at": started, "finished_at": utc_now(),
        "environment": {"python": platform.python_version(), "pypdf": pypdf.__version__},
        "config": config,
        "golden_records": {"path": str(golden_path).replace("\\", "/"), "sha256": golden.sha256, "rows": len(golden.rows)},
        "inputs": [{"file_name": r["document"]["file_name"], "sha256": r["document"]["sha256"]} for r in records],
        "outputs": outputs + ["exceptions_report.md"],
        "summary": summary,
    }
    (out_dir / "run_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest
