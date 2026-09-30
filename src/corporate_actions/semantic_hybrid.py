"""Variante D (E-004): determinístico (A + patch B) -> detector de necessidade -> [LLM v2 só se preciso]
-> grounding -> fusão v2 -> validações obrigatórias -> gates.

Três peças, todas determinísticas e auditáveis:
1. detect_need: sinais objetivos, com a etapa que os gerou, que justificam (ou não) chamar o LLM.
2. QUALIFIER_POLICY: o LLM descreve o qualificador (tipo, o que afeta); o código decide materialidade e bloqueio.
3. merge_v2: distingue acordo, determinístico sem suporte, heurística resolvida, conflito real,
   LLM não resolvido e LLM sem grounding — sem score agregado.
"""
import re

from .classification import classify
from .confidence_model import UNRESOLVED, SemanticAssessment
from .models import DECLARED_PENDING, DIVIDEND, FOUND, HIGH, JCP, LOW, MEDIUM, NOT_FOUND
from .schema import ALWAYS_REQUIRED, EVENT_SPECIFIC_FIELDS, REQUIRED
from .semantic_llm import _llm_field
from .semantic_patch import qualifier_window

DATE_ROLES = ["approval_date", "record_date", "ex_date", "payment_date", "share_credit_date"]
IMPUTATION_CONTEXT = r"(?i)\bimput(?:ad[oa]s?|a[çc][ãa]o|ar)\b"
CLOSING_DATE = r"\([A-Z]{2}\),\s*$"

# --- 1. Detector de necessidade ---------------------------------------------------------------

TRIGGERS = {
    "EVENT_SIGNALS_CONFLICT": "sinais de mais de um tipo de evento, sem explicação determinística conhecida",
    "CLASSIFICATION_UNSUPPORTED": "o determinístico não classifica o evento (sem sinais ou ambíguo) e o aviso não adia a natureza",
    "NEGATION_DECIDED_CLASSIFICATION": "a classificação depende da heurística de negação (sem ela, o tipo seria outro)",
    "REQUIRED_DATE_ROLE_UNMAPPED": "papel de data obrigatório não encontrado por rótulo, mas há datas no texto sem papel atribuído",
    "UNINTERPRETED_QUALIFIER": "qualificador que o código não sabe interpretar num campo emitido",
}


def _signal(name, stage, triggers, detail):
    return {"signal": name, "stage": stage, "triggers_llm": triggers, "detail": detail}


def _dividend_mentions_only_imputation(b_cls, text) -> bool:
    mentions = b_cls.signals.get(DIVIDEND, [])
    return bool(mentions) and all(
        re.search(IMPUTATION_CONTEXT, qualifier_window(text, m["evidence"].start, m["evidence"].end)) for m in mentions)


def _unassigned_date_mentions(extraction, fields, specific, text):
    used = [(e.start, e.end) for name in DATE_ROLES for f in [fields.get(name) or specific.get(name)]
            if f is not None and f.status in (FOUND, DECLARED_PENDING) for e in f.evidence]
    out = []
    for m in extraction.date_mentions:
        s, e = m.evidence.start, m.evidence.end
        if any(s < ue and e > us for us, ue in used) or re.search(CLOSING_DATE, text[max(0, s - 12):s]):
            continue
        out.append(m.raw)
    return out


def detect_need(extraction, tl, b_cls, b_cls_sem, b_field_sem, negated, fields, specific) -> dict:
    text = tl.normalized_text
    signals = []
    deferred = b_cls_sem.confidence == UNRESOLVED

    if deferred:
        signals.append(_signal("EVENT_NATURE_DEFERRED", "semantic_patch", False,
                               "o próprio aviso adia a natureza do evento: revisão por determinístico; LLM não muda o desfecho"))
    rule = b_cls.decision_rule
    if rule.startswith("precedence") or rule == "ambiguous":
        if rule == "precedence:JCP_over_DIVIDEND" and _dividend_mentions_only_imputation(b_cls, text):
            signals.append(_signal("EVENT_SIGNALS_CONFLICT_EXPLAINED", "classify", False,
                                   "menções a dividendo só no contexto de imputação do JCP ao dividendo obrigatório"))
        else:
            signals.append(_signal("EVENT_SIGNALS_CONFLICT", "classify", True,
                                   {"decision_rule": rule, "types": sorted(b_cls.signals)}))
    if b_cls.event_type is None and not deferred:
        signals.append(_signal("CLASSIFICATION_UNSUPPORTED", "classify", True, {"decision_rule": rule}))
    a_type = classify(extraction).event_type
    if negated:
        if a_type != b_cls.event_type:
            signals.append(_signal("NEGATION_DECIDED_CLASSIFICATION", "classify", True,
                                   {"without_negation": a_type, "with_negation": b_cls.event_type,
                                    "negated": [n["evidence"] for n in negated]}))
        else:
            signals.append(_signal("NEGATION_NOT_DECISIVE", "classify", False, [n["evidence"] for n in negated]))

    required = REQUIRED.get(b_cls.event_type, ALWAYS_REQUIRED)
    missing_roles = [r for r in ("record_date", "ex_date", "payment_date")
                     if r in required and fields.get(r) is not None and fields[r].status == NOT_FOUND]
    if missing_roles:
        unassigned = _unassigned_date_mentions(extraction, fields, specific, text)
        if unassigned:
            signals.append(_signal("REQUIRED_DATE_ROLE_UNMAPPED", "extract_candidates", True,
                                   {"missing_roles": missing_roles, "unassigned_date_mentions": unassigned}))
        else:
            signals.append(_signal("REQUIRED_DATE_MISSING_NO_TEXT_EVIDENCE", "extract_candidates", False, missing_roles))

    for name, a in b_field_sem.items():
        f = fields.get(name) or specific.get(name)
        if f is not None and f.status == FOUND and a.confidence == LOW and \
                any(r.startswith("UNINTERPRETED_QUALIFIER") for r in a.reasons):
            signals.append(_signal("UNINTERPRETED_QUALIFIER", "semantic_patch", True, {"field": name, "reasons": a.reasons}))

    for name, f in {**fields, **specific}.items():
        if f.status == DECLARED_PENDING:
            signals.append(_signal("DECLARED_PENDING", "normalize", False, name))
        elif f.status == FOUND and f.distinct_values > 1:
            signals.append(_signal("EXTRACTION_CONFLICT_OUT_OF_LLM_SCOPE" if name not in DATE_ROLES else
                                   "DATE_EXTRACTION_CONFLICT", "normalize", False, name))
    wt = fields.get("withholding_tax")
    if wt is not None and wt.status == FOUND and wt.value.get("base") is None:
        signals.append(_signal("TAX_BASE_NOT_STATED", "normalize", False,
                               "base não literal; sem novo texto a interpretar (bruto×líquido valida a taxa)"))
    applicable_specific = EVENT_SPECIFIC_FIELDS.get(b_cls.event_type, [])
    for name in extraction.unsupported_fields:
        if name in applicable_specific and name not in required:
            signals.append(_signal("UNSUPPORTED_FIELD_NOT_REQUIRED", "extract_candidates", False, name))

    triggers = [s["signal"] for s in signals if s["triggers_llm"]]
    return {"llm_required": bool(triggers), "llm_trigger_reasons": triggers, "signals": signals}


# --- 2. Qualificadores v2 ------------------------------------------------------------------------

# (materialidade, bloqueia?) por tipo. O LLM descreve; esta tabela decide.
QUALIFIER_POLICY = {
    "tax_base_condition": ("MATERIAL", "UNLESS_BASE_REPRESENTED"),
    "tax_rate_condition": ("MATERIAL", "BLOCK"),
    "beneficiary_exception": ("MATERIAL_FOR_TAX_APPLICATION", "NO_BLOCK"),
    "event_eligibility_condition": ("MATERIAL", "BLOCK"),
    "legal_context": ("NOT_MATERIAL", "NO_BLOCK"),
    "timing_context": ("NOT_MATERIAL", "NO_BLOCK"),
    "informational_context": ("NOT_MATERIAL", "NO_BLOCK"),
    "other": ("UNKNOWN", "BLOCK"),
    "unresolved": ("UNKNOWN", "BLOCK"),
}
MATERIAL_AFFECTS = {"tax_base", "tax_rate", "event_eligibility", "event_nature", "amounts"}
B_TO_V2 = {"THRESHOLD": ("tax_base_condition", "tax_base"), "HOLDER_EXEMPTION": ("beneficiary_exception", "tax_application")}


def evaluate_qualifier(q: dict, tax_base: str | None) -> dict:
    """Aplica a política: materialidade, resolvido e se bloqueia. Tipo não material que declara afetar algo
    material é inconsistente e bloqueia (o LLM não consegue rebaixar um efeito material por rótulo)."""
    qtype, affects = q["qualifier_type"], q["affects"]
    materiality, rule = QUALIFIER_POLICY[qtype]
    if materiality == "NOT_MATERIAL" and affects in MATERIAL_AFFECTS:
        materiality, rule = "INCONSISTENT", "BLOCK"
    if rule == "UNLESS_BASE_REPRESENTED":
        resolved = tax_base == "EXCESS_OVER_THRESHOLD"
    else:
        resolved = rule == "NO_BLOCK"
    return {**{k: q[k] for k in ("qualifier_type", "affects", "effect", "quote") if k in q},
            "materiality": materiality, "resolved": resolved, "blocks": not resolved, "source": q.get("source", "llm")}


def project_b_qualifiers(assessment) -> list[dict]:
    """Qualificadores do patch B no mesmo modelo v2 (para saída uniforme)."""
    out = []
    types = {q["type"] for q in assessment.qualifiers}
    for q in assessment.qualifiers:
        if q["type"] == "EXCEPTION" and "HOLDER_EXEMPTION" in types:
            continue
        qtype, affects = B_TO_V2.get(q["type"], ("unresolved", "none"))
        out.append({"qualifier_type": qtype, "affects": affects, "effect": f"deterministic cue {q['type']}: {q['cue']}",
                    "quote": q["cue"], "source": "deterministic_patch"})
    return out


# --- 3. Fusão v2 --------------------------------------------------------------------------------

def _resolution(concept, category, **detail):
    return {"concept": concept, "category": category, **detail}


def _covered(spans, ev) -> bool:
    return any(s <= ev.start and ev.end <= e for s, e in spans)


def merge_classification(b_cls, b_cls_sem, need, parsed, grounding, tl):
    """Retorna (tipo final, avaliação semântica, resolução)."""
    triggers = set(need["llm_trigger_reasons"])
    if b_cls_sem.confidence == UNRESOLVED:                          # adiamento textual: prevalece
        llm_t = parsed["event"]["type"]
        cat = "AGREEMENT" if llm_t == "UNRESOLVED" else "TRUE_DISAGREEMENT"
        return None, b_cls_sem, _resolution("event_type", cat, deterministic="DEFERRED", llm=llm_t)
    if b_cls.event_type is None:
        det_status = "UNSUPPORTED"
    elif b_cls.decision_rule.startswith("precedence") or "NEGATION_DECIDED_CLASSIFICATION" in triggers:
        det_status = "HEURISTIC"
    else:
        det_status = "POSITIVE"
    llm_t = parsed["event"]["type"]
    base = {"deterministic": b_cls.event_type, "deterministic_status": det_status, "llm": llm_t,
            "rationale": parsed["event"]["rationale"]}
    if llm_t == "UNRESOLVED":
        return (b_cls.event_type if det_status == "POSITIVE" else None,
                SemanticAssessment(UNRESOLVED, "llm", ["LLM_EVENT_TYPE_UNRESOLVED"], interpretation=base),
                _resolution("event_type", "LLM_UNRESOLVED", **base))
    if not grounding["event_grounded"]:
        if det_status == "POSITIVE":
            return b_cls.event_type, b_cls_sem, _resolution("event_type", "LLM_UNGROUNDED_IGNORED", **base)
        return (b_cls.event_type, SemanticAssessment(LOW, "llm", ["LLM_EVENT_EVIDENCE_UNGROUNDED"], interpretation=base),
                _resolution("event_type", "LLM_UNGROUNDED", **base))
    if llm_t == b_cls.event_type:
        return llm_t, SemanticAssessment(HIGH, "llm+deterministic", ["AGREEMENT"], interpretation=base), \
            _resolution("event_type", "AGREEMENT", **base)
    if det_status == "UNSUPPORTED":
        return llm_t, SemanticAssessment(MEDIUM, "llm", ["DETERMINISTIC_UNSUPPORTED", "LLM_ONLY_GROUNDED"],
                                         interpretation=base), _resolution("event_type", "DETERMINISTIC_UNSUPPORTED", **base)
    if det_status == "HEURISTIC":
        # Aceita a leitura do LLM só se TODO sinal do tipo que a heurística escolheu foi explicado pelo LLM
        # como menção enganosa (negada / outro evento / o que o evento não afeta), com citação localizada.
        spans = [s for s in (locateq(tl, mm["quote"]) for mm in parsed["event"]["misleading_mentions"]) if s]
        losing = [m["evidence"] for m in b_cls.signals.get(b_cls.event_type, [])]
        if losing and all(_covered(spans, ev) for ev in losing):
            return llm_t, SemanticAssessment(MEDIUM, "llm", ["HEURISTIC_RESOLVED_BY_GROUNDED_LLM"], interpretation=base), \
                _resolution("event_type", "HEURISTIC_RESOLVED", **base, losing_signals_explained=len(losing))
    return b_cls.event_type, SemanticAssessment(LOW, "llm", ["CLASSIFICATION_DISAGREEMENT"], interpretation=base), \
        _resolution("event_type", "TRUE_DISAGREEMENT", **base)


def locateq(tl, quote):
    from .semantic_llm import locate
    return locate(tl.normalized_text, quote)


def merge_dates(fields, specific, b_field_sem, grounding, parsed_quals, tl, required):
    sem, res = {}, []
    llm_date_quals = [q for q in parsed_quals if q["affects"] == "dates" and q["blocks"]]
    for item in grounding["dates"]:
        role = item["role"]
        target = specific if role == "share_credit_date" else fields
        if role == "share_credit_date" and role not in specific:
            continue
        det = target.get(role)
        det_status = det.status if det is not None else NOT_FOUND
        if not item["grounded"]:
            res.append(_resolution(role, "LLM_UNGROUNDED_IGNORED" if det_status == FOUND else "LLM_UNGROUNDED",
                                   problem=item["problem"]))
            continue
        if item["status"] == "AMBIGUOUS":
            if det_status == FOUND:
                sem[role] = SemanticAssessment(MEDIUM, "llm+deterministic", ["LLM_UNRESOLVED_DETERMINISTIC_POSITIVE"])
            elif role in required:
                sem[role] = SemanticAssessment(UNRESOLVED, "llm", ["LLM_DATE_ROLE_AMBIGUOUS"])
            res.append(_resolution(role, "LLM_UNRESOLVED", deterministic=det_status))
            continue
        if item["status"] == "PENDING":
            if det_status == DECLARED_PENDING:
                cat, level = "AGREEMENT", HIGH
            elif det_status == NOT_FOUND:
                target[role] = _llm_field(tl, item["span"], item["value_as_written"], None,
                                          "llm.date_role_mapping.pending", "pending declaration located by LLM")
                cat, level = "DETERMINISTIC_UNSUPPORTED", MEDIUM
            else:
                cat, level = "TRUE_DISAGREEMENT", LOW
            sem[role] = SemanticAssessment(level, "llm+deterministic" if level == HIGH else "llm", [cat])
            res.append(_resolution(role, cat, deterministic=det_status, llm="PENDING"))
            continue
        if det_status == FOUND:
            if det.value == item["value"]:
                b = b_field_sem.get(role)
                if b is not None and b.confidence == LOW and not llm_date_quals:
                    sem[role] = SemanticAssessment(HIGH, "llm+deterministic",
                                                   ["AGREEMENT", "DETERMINISTIC_QUALIFIER_UNSUPPORTED_RESOLVED_BY_LLM"])
                    res.append(_resolution(role, "DETERMINISTIC_UNSUPPORTED", reason="uninterpreted qualifier resolved"))
                else:
                    sem[role] = SemanticAssessment(HIGH, "llm+deterministic", ["AGREEMENT"])
                    res.append(_resolution(role, "AGREEMENT"))
            else:
                det.alternatives.append({"value": item["value"], "source": "llm", "evidence": [item["evidence"]]})
                sem[role] = SemanticAssessment(LOW, "llm", ["TRUE_DISAGREEMENT"])
                res.append(_resolution(role, "TRUE_DISAGREEMENT", deterministic=str(det.value), llm=str(item["value"])))
        elif det_status == DECLARED_PENDING:
            sem[role] = SemanticAssessment(LOW, "llm", ["TRUE_DISAGREEMENT"])
            res.append(_resolution(role, "TRUE_DISAGREEMENT", deterministic="PENDING", llm=str(item["value"])))
        else:
            target[role] = _llm_field(tl, item["span"], item["value_as_written"], item["value"],
                                      "llm.date_role_mapping", "value located by LLM role mapping; literal quote grounded")
            sem[role] = SemanticAssessment(MEDIUM, "llm", ["DETERMINISTIC_UNSUPPORTED", "LLM_ONLY_GROUNDED"])
            res.append(_resolution(role, "LLM_ONLY_GROUNDED", llm=str(item["value"])))
    return sem, res


def merge_tax(fields, b_field_sem, grounding, quals, tl):
    """Retorna (avaliação do IR ou None, resolução)."""
    wt = grounding["withholding"]
    det = fields.get("withholding_tax")
    det_found = det is not None and det.status == FOUND
    tax_quals = [q for q in quals if q["affects"] in ("tax_base", "tax_rate", "tax_application")
                 or q["qualifier_type"].startswith("tax_") or q["qualifier_type"] == "beneficiary_exception"]
    if wt["status"] == "AMBIGUOUS":
        return (SemanticAssessment(LOW, "llm", ["LLM_TAX_AMBIGUOUS"], tax_quals) if det_found else None,
                _resolution("withholding_tax", "LLM_UNRESOLVED"))
    if wt["status"] == "NOT_STATED":
        if det_found:
            return SemanticAssessment(LOW, "llm", ["TRUE_DISAGREEMENT_LLM_NOT_STATED"], tax_quals), \
                _resolution("withholding_tax", "TRUE_DISAGREEMENT")
        return None, _resolution("withholding_tax", "AGREEMENT", note="not stated")
    if not wt["grounded"] or wt["rate"] is None:
        cat = "LLM_UNGROUNDED_IGNORED" if det_found else "LLM_UNGROUNDED"
        return (b_field_sem.get("withholding_tax") if det_found else None), _resolution("withholding_tax", cat)
    llm_base = None if wt["base"] == "NOT_STATED" else wt["base"]
    if det_found:
        if det.value["rate"] != wt["rate"]:
            return SemanticAssessment(LOW, "llm", ["TRUE_DISAGREEMENT_RATE"], tax_quals), \
                _resolution("withholding_tax", "TRUE_DISAGREEMENT", deterministic=str(det.value["rate"]), llm=str(wt["rate"]))
        det_base = det.value["base"]
        if det_base is not None and llm_base is not None and det_base != llm_base:
            return SemanticAssessment(LOW, "llm", ["TRUE_DISAGREEMENT_BASE"], tax_quals), \
                _resolution("withholding_tax", "TRUE_DISAGREEMENT", deterministic=det_base, llm=llm_base)
        if det_base is None and llm_base is not None:
            det.value = {"rate": det.value["rate"], "base": llm_base}
            det.notes.append(f"semantic_hybrid: base interpreted by LLM as {llm_base}")
            category, level = "DETERMINISTIC_UNSUPPORTED", MEDIUM
        else:
            category, level = "AGREEMENT", HIGH
        b = b_field_sem.get("withholding_tax")
        if b is not None and b.confidence == LOW:
            category, level = "DETERMINISTIC_UNSUPPORTED", MEDIUM       # B não interpretou o qualificador; o LLM sim
    else:
        span = locateq(tl, wt["evidence"][0])
        fields["withholding_tax"] = _llm_field(tl, span, wt["rate_as_written"], {"rate": wt["rate"], "base": llm_base},
                                               "llm.withholding_semantics", "rate and base located by LLM; literal quote grounded")
        category, level = "LLM_ONLY_GROUNDED", MEDIUM
    return SemanticAssessment(level, "llm" if level == MEDIUM else "llm+deterministic", [category], tax_quals), \
        _resolution("withholding_tax", category)


def apply_qualifier_policy(parsed_quals_grounded, field_sem, fields) -> tuple[list[dict], list[str]]:
    """Avalia os qualificadores do LLM. Bloqueios materiais não resolvidos viram LOW no campo afetado
    ou entradas em `blocking` (elegibilidade/natureza do evento)."""
    wt = fields.get("withholding_tax")
    base = wt.value.get("base") if wt is not None and wt.status == FOUND else None
    evaluated, blocking = [], []
    for q in parsed_quals_grounded:
        if not q["grounded"]:
            continue                                                  # sem evidência: descartado
        e = evaluate_qualifier(q, base)
        evaluated.append(e)
        if not e["blocks"]:
            continue
        if e["affects"] in ("tax_base", "tax_rate", "tax_application") or e["qualifier_type"].startswith("tax_"):
            prev = field_sem.get("withholding_tax")
            field_sem["withholding_tax"] = SemanticAssessment(
                LOW, "llm", (prev.reasons if prev else []) + [f"MATERIAL_QUALIFIER_UNRESOLVED:{e['qualifier_type']}"],
                prev.qualifiers if prev else [])
        else:
            blocking.append(f"MATERIAL_QUALIFIER_UNRESOLVED:{e['qualifier_type']}")
    return evaluated, blocking


def llm_only_corroboration_blocks(field_sem: dict, validations) -> list[str]:
    """Política LLM-only: um valor que só o LLM sustenta precisa passar em TODAS as regras que o cruzam,
    inclusive as de severidade WARNING; qualquer FAIL (ERROR ou WARNING) bloqueia."""
    from .confidence_model import validation_view
    out = []
    for name, a in field_sem.items():
        if "LLM_ONLY_GROUNDED" in a.reasons and validation_view(name, validations) in ("CONTRADICTED", "WARNED"):
            out.append(f"LLM_ONLY_VALUE_NOT_CORROBORATED:{name}")
    return out
