"""Orquestrador. Variantes do E-003 compartilham extração, normalização e validação:

A  Baseline A (inalterado):  ingest -> text layer -> candidates -> classify -> normalize -> confidence
                              -> validate -> route
B  + patch semântico determinístico: classificação com negação + qualificadores -> gates
C  + intérprete semântico por LLM (grounded, com function calling) -> gates
D  hybrid_on_demand (E-004): B + detector de necessidade -> [LLM v2 só se preciso] -> fusão v2 -> gates
E  hybrid_qualifiers_v3 (E-005): igual à D, com prompt v3 e qualificadores v3 (material × notas, guarda de escopo)
F  candidate_hardened (E-006): E + perfil determinístico v2 + tratamento tributário + contradições + revogação
   + gate de cobertura material (hardening.py)

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
                    "C": PIPELINE_VERSION + "+semantic-llm/0.1",
                    "D": PIPELINE_VERSION + "+hybrid-on-demand/0.1",
                    "E": PIPELINE_VERSION + "+hybrid-qualifiers-v3/0.1",
                    "F": PIPELINE_VERSION + "+candidate-hardened/0.1"}
VARIANT_SCHEMA = {"A": RECORD_SCHEMA_VERSION, "B": "semantic-record/0.1", "C": "semantic-record/0.1",
                  "D": "semantic-record/0.2", "E": "semantic-record/0.3", "F": "semantic-record/0.4"}


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
    from .profiles import DETERMINISTIC_PROFILE
    profile_token = DETERMINISTIC_PROFILE.set("v2" if variant == "F" else "v1")
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
            if variant == "F":
                from .hardening import extra_candidates
                extra_candidates(extraction, tl)
        negated, cls_semantic = [], None
        with audit.stage("classify"):
            if variant in ("B", "D", "E", "F"):
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

        semantic = need = None
        if variant in ("D", "E", "F"):
            semantic_fn = {"D": _semantic_d, "E": _semantic_e, "F": _semantic_f}[variant]
            classification, fields, specific, semantic, llm_info, parsed, need = semantic_fn(
                extraction, tl, classification, cls_semantic, negated, fields, specific, golden, semantic_ctx, audit)
        elif variant == "B":
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

        if variant in ("C", "D", "E", "F") and llm_info is not None:
            llm_info["reference_divergence"] = _reference_divergence(parsed, llm_info, validations)
        if variant in ("D", "E", "F"):
            from .semantic_hybrid import llm_only_corroboration_blocks
            semantic["blocking"] += llm_only_corroboration_blocks(semantic["fields"], validations)
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
        if need is not None:
            record["semantic_need"] = need
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
        DETERMINISTIC_PROFILE.reset(profile_token)
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


def _semantic_d(extraction, tl, classification, cls_semantic, negated, fields, specific, golden, ctx, audit):
    """Variante D: patch B, detector de necessidade e, só se preciso, LLM v2 + fusão v2."""
    from . import semantic_hybrid as H
    from .semantic_llm_v2 import ground_v2, interpret
    from .semantic_patch import assess_fields
    with audit.stage("semantic_patch"):
        b_field_sem = assess_fields(fields, specific, tl)
    with audit.stage("semantic_need") as st:
        need = H.detect_need(extraction, tl, classification, cls_semantic, b_field_sem, negated, fields, specific)
        st.update(llm_required=need["llm_required"], triggers=need["llm_trigger_reasons"])
    b_quals = [q for a in b_field_sem.values() for q in H.project_b_qualifiers(a)]
    semantic = {"classification": cls_semantic, "fields": b_field_sem, "blocking": [], "negated_signals": negated,
                "resolutions": [], "qualifiers_v2": [H.evaluate_qualifier(q, (fields.get("withholding_tax").value or {}).get("base")
                                                                          if fields.get("withholding_tax") and fields["withholding_tax"].status == "found" else None)
                                                     for q in b_quals]}
    if not need["llm_required"]:
        audit.skip("semantic_llm", "NOT_REQUIRED")
        return classification, fields, specific, semantic, None, None, need
    with audit.stage("semantic_llm") as st:
        parsed, attempts = interpret(ctx.provider, tl, golden, ctx.cache)
        grounding = ground_v2(parsed, tl) if parsed else None
        llm_info = _llm_audit(ctx, attempts, parsed, grounding, prompt="v2")
        st.update(api_calls=llm_info["api_calls"], tool_calls=len(llm_info["tool_calls"]), replayed=llm_info["replayed"])
    if parsed is None:
        semantic["blocking"].append("SEMANTIC_INTERPRETER_FAILED")
        return classification, fields, specific, semantic, llm_info, None, need
    with audit.stage("semantic_merge"):
        final_type, cls_sem, cls_res = H.merge_classification(classification, cls_semantic, need, parsed, grounding, tl)
        if final_type != classification.event_type:
            classification = dataclasses.replace(
                classification, event_type=final_type,
                decision_rule=f"semantic_hybrid({cls_res['category']};deterministic={classification.decision_rule}:{classification.event_type})")
            fields, specific = resolve_all(extraction, final_type)
            score_all(fields, specific)
            b_field_sem = assess_fields(fields, specific, tl)
        required = REQUIRED.get(final_type, ALWAYS_REQUIRED)
        field_sem = dict(b_field_sem)
        llm_quals = [q for q in grounding["qualifiers"]]
        pre_quals = [H.evaluate_qualifier(q, None) | {"grounded": q["grounded"]} for q in llm_quals]
        date_sem, date_res = H.merge_dates(fields, specific, b_field_sem, grounding, pre_quals, tl, required)
        field_sem.update(date_sem)
        tax_sem, tax_res = H.merge_tax(fields, b_field_sem, grounding, llm_quals, tl)
        if tax_sem is not None:
            field_sem["withholding_tax"] = tax_sem
        evaluated, q_blocking = H.apply_qualifier_policy(llm_quals, field_sem, fields)
        semantic.update(classification=cls_sem, fields=field_sem, blocking=q_blocking,
                        resolutions=[cls_res] + date_res + [tax_res], qualifiers_v2=evaluated)
    return classification, fields, specific, semantic, llm_info, parsed, need


def _semantic_e(extraction, tl, classification, cls_semantic, negated, fields, specific, golden, ctx, audit):
    """Variante E: idêntica à D (patch B, detector, fusão v2, gates), com prompt v3 e qualificadores v3."""
    from . import qualifiers_v3 as Q
    from . import semantic_hybrid as H
    from .semantic_llm_v3 import ground_v3, interpret
    from .semantic_patch import assess_fields
    with audit.stage("semantic_patch"):
        b_field_sem = assess_fields(fields, specific, tl)
    with audit.stage("semantic_need") as st:
        need = H.detect_need(extraction, tl, classification, cls_semantic, b_field_sem, negated, fields, specific)
        st.update(llm_required=need["llm_required"], triggers=need["llm_trigger_reasons"])
    semantic = {"classification": cls_semantic, "fields": b_field_sem, "blocking": [], "negated_signals": negated,
                "resolutions": [], "material_qualifiers": [q for a in b_field_sem.values() for q in Q.project_b(a)],
                "semantic_notes": []}
    if not need["llm_required"]:
        audit.skip("semantic_llm", "NOT_REQUIRED")
        return classification, fields, specific, semantic, None, None, need
    with audit.stage("semantic_llm") as st:
        parsed, attempts = interpret(ctx.provider, tl, golden, ctx.cache)
        grounding = ground_v3(parsed, tl) if parsed else None
        llm_info = _llm_audit(ctx, attempts, parsed, grounding, prompt="v3")
        st.update(api_calls=llm_info["api_calls"], tool_calls=len(llm_info["tool_calls"]), replayed=llm_info["replayed"])
    if parsed is None:
        semantic["blocking"].append("SEMANTIC_INTERPRETER_FAILED")
        return classification, fields, specific, semantic, llm_info, None, need
    with audit.stage("semantic_merge"):
        final_type, cls_sem, cls_res = H.merge_classification(classification, cls_semantic, need, parsed, grounding, tl)
        if final_type != classification.event_type:
            classification = dataclasses.replace(
                classification, event_type=final_type,
                decision_rule=f"semantic_hybrid({cls_res['category']};deterministic={classification.decision_rule}:{classification.event_type})")
            fields, specific = resolve_all(extraction, final_type)
            score_all(fields, specific)
            b_field_sem = assess_fields(fields, specific, tl)
        required = REQUIRED.get(final_type, ALWAYS_REQUIRED)
        field_sem = dict(b_field_sem)
        spans = Q._field_spans(fields, specific)
        pre = [dict(q, blocks=Q.representation(q, fields, specific) is None) for q in grounding["material_qualifiers"]
               if q["grounded"] and not Q.scope_guard(q["span"], spans, tl.normalized_text)]
        date_sem, date_res = H.merge_dates(fields, specific, b_field_sem, grounding, Q.as_v2_like(pre), tl, required)
        field_sem.update(date_sem)
        tax_sem, tax_res = H.merge_tax(fields, b_field_sem, grounding, Q.as_v2_like(pre), tl)
        if tax_sem is not None:
            field_sem["withholding_tax"] = tax_sem
        material, notes, q_blocking = Q.evaluate(grounding, fields, specific, field_sem, tl.normalized_text)
        semantic.update(classification=cls_sem, fields=field_sem, blocking=q_blocking,
                        resolutions=[cls_res] + date_res + [tax_res], material_qualifiers=material, semantic_notes=notes)
    return classification, fields, specific, semantic, llm_info, parsed, need


def _semantic_f(extraction, tl, classification, cls_semantic, negated, fields, specific, golden, ctx, audit):
    """Variante F: E + endurecimento (hardening.py). O LLM, o prompt v3, o detector, a fusão v2 e os gates são os da E."""
    from . import hardening as HD
    from . import qualifiers_v3 as Q
    from . import semantic_hybrid as H
    from .semantic_llm_v3 import ground_v3, interpret
    from .semantic_patch import assess_fields
    text = tl.normalized_text

    def deterministic_layer(fields, specific, event_type):
        HD.extend_specific_v2(specific, extraction, event_type)
        issuer = HD.resolve_issuer_v2(fields, extraction, tl)
        b_sem = assess_fields(fields, specific, tl)
        fields["tax_treatment"] = HD.build_tax_treatment(fields, b_sem, tax_statements, event_type, tl)
        return issuer, b_sem

    with audit.stage("semantic_patch"):
        tax_statements = HD.detect_tax_statements(tl)
        revocations = HD.detect_revocation(tl)
        issuer_diag, b_field_sem = deterministic_layer(fields, specific, classification.event_type)
        pre_contra = HD.detect_contradictions(classification.event_type, fields)
    with audit.stage("semantic_need") as st:
        need = H.detect_need(extraction, tl, classification, cls_semantic, b_field_sem, negated, fields, specific)
        for c in pre_contra:
            need["signals"].append({"signal": "SEMANTIC_CONTRADICTION", "stage": "contradiction_detector",
                                    "triggers_llm": True, "detail": c})
        for r in revocations:
            need["signals"].append({"signal": "REVOCATION_LANGUAGE", "stage": "contradiction_detector",
                                    "triggers_llm": False, "detail": "evento revogado não é suportado: revisão, LLM não muda o desfecho"})
        need["llm_trigger_reasons"] = [s["signal"] for s in need["signals"] if s["triggers_llm"]]
        need["llm_required"] = bool(need["llm_trigger_reasons"]) and not revocations
        st.update(llm_required=need["llm_required"], triggers=need["llm_trigger_reasons"])
    semantic = {"classification": cls_semantic, "fields": b_field_sem, "blocking": [], "negated_signals": negated,
                "resolutions": [], "material_qualifiers": [q for a in b_field_sem.values() for q in Q.project_b(a)],
                "semantic_notes": [], "issuer_resolution": issuer_diag, "tax_statements": tax_statements,
                "revocation": revocations}
    llm_info = parsed = grounding = None
    material = semantic["material_qualifiers"]
    field_sem = b_field_sem
    if not need["llm_required"]:
        audit.skip("semantic_llm", "NOT_REQUIRED")
    else:
        with audit.stage("semantic_llm") as st:
            parsed, attempts = interpret(ctx.provider, tl, golden, ctx.cache)
            grounding = ground_v3(parsed, tl) if parsed else None
            llm_info = _llm_audit(ctx, attempts, parsed, grounding, prompt="v3")
            st.update(api_calls=llm_info["api_calls"], tool_calls=len(llm_info["tool_calls"]), replayed=llm_info["replayed"])
        if parsed is None:
            semantic["blocking"].append("SEMANTIC_INTERPRETER_FAILED")
        else:
            with audit.stage("semantic_merge"):
                final_type, cls_sem, cls_res = H.merge_classification(classification, cls_semantic, need, parsed, grounding, tl)
                if final_type != classification.event_type:
                    classification = dataclasses.replace(
                        classification, event_type=final_type,
                        decision_rule=f"semantic_hybrid({cls_res['category']};deterministic={classification.decision_rule}:{classification.event_type})")
                    fields, specific = resolve_all(extraction, final_type)
                    score_all(fields, specific)
                    issuer_diag, b_field_sem = deterministic_layer(fields, specific, final_type)
                required = REQUIRED.get(final_type, ALWAYS_REQUIRED)
                field_sem = dict(b_field_sem)
                spans = Q._field_spans(fields, specific)
                pre = [dict(q, blocks=Q.representation(q, fields, specific) is None) for q in grounding["material_qualifiers"]
                       if q["grounded"] and not Q.scope_guard(q["span"], spans, text)]
                date_sem, date_res = H.merge_dates(fields, specific, b_field_sem, grounding, Q.as_v2_like(pre), tl, required)
                field_sem.update(date_sem)
                tax_sem, tax_res = H.merge_tax(fields, b_field_sem, grounding, Q.as_v2_like(pre), tl)
                if tax_sem is not None:
                    field_sem["withholding_tax"] = tax_sem
                if fields["withholding_tax"].status == "found" and fields["tax_treatment"].status != "found":
                    fields["tax_treatment"] = HD.build_tax_treatment(fields, b_field_sem, tax_statements, final_type, tl)
                tt_res = HD.merge_llm_tax_treatment(fields, grounding, tl)
                material, notes, q_blocking = Q.evaluate(grounding, fields, specific, field_sem, text)
                semantic.update(classification=cls_sem, blocking=q_blocking, semantic_notes=notes,
                                resolutions=[cls_res] + date_res + [tax_res] + ([tt_res] if tt_res else []),
                                material_qualifiers=material, issuer_resolution=issuer_diag)
    with audit.stage("hardening_gates"):
        contradictions = HD.detect_contradictions(classification.event_type, fields)
        coverage, cov_blocking = HD.coverage_gate(classification.event_type, fields, specific, field_sem, grounding,
                                                  material, extraction, revocations, tax_statements, text)
        semantic["fields"] = field_sem
        semantic["contradictions"] = contradictions
        semantic["material_coverage"] = coverage
        semantic["event_status"] = "REVOCATION_DETECTED_UNSUPPORTED" if revocations else "ACTIVE_OR_NOT_STATED"
        semantic["blocking"] += [f"SEMANTIC_CONTRADICTION:{c['code']}" for c in contradictions]
        semantic["blocking"] += ["UNSUPPORTED_EVENT_REVOCATION"] if revocations else []
        semantic["blocking"] += cov_blocking
    return classification, fields, specific, semantic, llm_info, parsed, need


def _llm_audit(ctx: SemanticContext, attempts, parsed, grounding, prompt: str = "v1") -> dict:
    from .llm.registry import estimate_cost_usd
    if prompt == "v3":
        from .semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint
    elif prompt == "v2":
        from .semantic_llm_v2 import PROMPT_VERSION, prompt_fingerprint
    else:
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
    if variant in ("C", "D", "E", "F"):
        if variant in ("E", "F"):
            from .semantic_llm_v3 import PROMPT_VERSION, prompt_fingerprint
        elif variant == "D":
            from .semantic_llm_v2 import PROMPT_VERSION, prompt_fingerprint
        else:
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
    if variant in ("D", "E", "F"):
        needs = [r.get("semantic_need") for r in records if r.get("semantic_need")]
        summary["semantic_need"] = {
            "documents_assessed": len(needs), "llm_required": sum(n["llm_required"] for n in needs),
            "trigger_counts": dict(Counter(t for n in needs for t in n["llm_trigger_reasons"]))}
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
