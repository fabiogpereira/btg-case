"""Modelo de confiança em três dimensões (D-015) e roteamento por gates explícitos.

Por campo, quando aplicável:
- extraction  — o valor foi localizado e lido corretamente? (HIGH/MEDIUM/LOW; confidence.py)
- semantic    — o significado foi capturado por inteiro (papel, qualificadores, negação, condição)?
                HIGH | MEDIUM | LOW | UNRESOLVED | NOT_ASSESSED
- validation  — alguma regra determinística cruzou o valor com outro dado?
                CROSS_VALIDATED | CONTRADICTED | WARNED | UNVALIDATED

Não existe score agregado. O roteamento passa por gates independentes; qualquer gate BLOCK
envia o registro para revisão, com o motivo daquele gate.
"""
from dataclasses import dataclass, field

from .models import ERROR, FAIL, LOW, NOT_EVALUATED, PASS, WARNING

NOT_ASSESSED, UNRESOLVED = "NOT_ASSESSED", "UNRESOLVED"
BLOCKING_SEMANTIC = {LOW, UNRESOLVED}


@dataclass
class SemanticAssessment:
    confidence: str
    source: str                                   # deterministic_patch | llm | llm+deterministic
    reasons: list[str] = field(default_factory=list)
    qualifiers: list[dict] = field(default_factory=list)
    interpretation: dict | None = None


# Quais campos cada regra cruza (para a dimensão de validação)
RULE_FIELDS = {
    "REF_ISIN_FOUND": ["isin"], "REF_TICKER_CONSISTENT": ["ticker"], "REF_CNPJ_CONSISTENT": ["cnpj"],
    "REF_ISSUER_NAME_CONSISTENT": ["issuer_name"], "REF_SHARE_CLASS_CONSISTENT": ["share_class"],
    "DATE_APPROVAL_NOT_AFTER_RECORD": ["approval_date", "record_date"],
    "DATE_RECORD_BEFORE_EX": ["record_date", "ex_date"],
    "DATE_EX_NEXT_WEEKDAY_AFTER_RECORD": ["record_date", "ex_date"],
    "DATE_SETTLEMENT_NOT_BEFORE_EX": ["payment_date", "share_credit_date", "ex_date"],
    "AMOUNT_GROSS_POSITIVE": ["gross_amount_per_share"],
    "AMOUNT_NET_MATCHES_GROSS_AND_TAX": ["gross_amount_per_share", "net_amount_per_share", "withholding_tax"],
    "RATIO_POSITIVE": ["ratio"], "RATIO_PERCENTAGE_CONSISTENT": ["ratio"],
}


def validation_view(field_name: str, validations) -> str:
    related = [v for v in validations if field_name in RULE_FIELDS.get(v.rule_id, [])]
    if any(v.status == FAIL and v.severity == ERROR for v in related):
        return "CONTRADICTED"
    if any(v.status == FAIL and v.severity == WARNING for v in related):
        return "WARNED"
    if any(v.status == PASS for v in related):
        return "CROSS_VALIDATED"
    return "UNVALIDATED"


def confidence_view(fields: dict, semantic_fields: dict, validations) -> dict:
    view = {}
    for name, f in fields.items():
        if f.status not in ("found", "declared_pending"):
            continue
        sem = semantic_fields.get(name)
        view[name] = {"extraction": f.confidence, "semantic": sem.confidence if sem else NOT_ASSESSED,
                      "validation": validation_view(name, validations)}
    return view


# --- Gates ----------------------------------------------------------------------------------

REQUIRED_RULES = {"REQUIRED_FIELDS_PRESENT": "REQUIRED_FIELD_MISSING", "REQUIRED_FIELDS_NOT_PENDING": None}
REFERENCE_RULES = {"REF_ISIN_FOUND": "REFERENCE_NOT_FOUND", "REF_TICKER_CONSISTENT": "REFERENCE_MISMATCH",
                   "REF_CNPJ_CONSISTENT": "REFERENCE_MISMATCH", "REF_SHARE_CLASS_CONSISTENT": "REFERENCE_MISMATCH",
                   "REF_ISSUER_ACTIVE": "REFERENCE_INACTIVE"}
DETERMINISTIC_RULES = {"CLASSIFICATION_DETERMINED": "CLASSIFICATION_UNDETERMINED",
                       "CLASSIFICATION_TITLE_CONSISTENT": "CLASSIFICATION_TITLE_CONFLICT",
                       "DATE_APPROVAL_NOT_AFTER_RECORD": "DATE_INCONSISTENCY", "DATE_RECORD_BEFORE_EX": "DATE_INCONSISTENCY",
                       "DATE_SETTLEMENT_NOT_BEFORE_EX": "DATE_INCONSISTENCY",
                       "AMOUNT_GROSS_POSITIVE": "AMOUNT_INCONSISTENCY", "AMOUNT_NET_MATCHES_GROSS_AND_TAX": "AMOUNT_INCONSISTENCY",
                       "RATIO_POSITIVE": "RATIO_INCONSISTENCY", "RATIO_PERCENTAGE_CONSISTENT": "RATIO_INCONSISTENCY"}


def route_gated(text_layer_usable: bool, validations, fields: dict, required_fields, semantic: dict,
                blocking_errors: list[str] | None = None) -> dict:
    gates = []

    def gate(name, blocks: list[tuple[str, str]]):
        gates.append({"gate": name, "status": "BLOCK" if blocks else "PASS",
                      "reason_codes": sorted({c for c, _ in blocks}), "explanations": [e for _, e in blocks]})

    if not text_layer_usable:
        gate("EXTRACTION_POSSIBLE", [("NO_USABLE_TEXT_LAYER", "sem camada de texto utilizável")])
        return _decide(gates)
    gate("EXTRACTION_POSSIBLE", [])

    by_rule = {v.rule_id: v for v in validations}
    req = []
    for rule_id, code in REQUIRED_RULES.items():
        v = by_rule.get(rule_id)
        if v and v.status == FAIL:
            if rule_id == "REQUIRED_FIELDS_NOT_PENDING":
                code = "PAYMENT_DATE_PENDING" if "payment_date" in v.observed.get("declared_pending", []) \
                    else "REQUIRED_FIELD_PENDING"
            req.append((code, f"{rule_id}: {v.message}"))
    for name in required_fields:
        f = fields.get(name)
        if f is not None and f.confidence == LOW:
            req.append(("LOW_EXTRACTION_CONFIDENCE", f"{name}: {', '.join(f.confidence_reasons)}"))
    gate("REQUIRED_INFORMATION", req)

    sem = []
    cls = semantic.get("classification")
    if cls is not None and cls.confidence in BLOCKING_SEMANTIC:
        code = "CLASSIFICATION_DISAGREEMENT" if "CLASSIFICATION_DISAGREEMENT" in cls.reasons else "SEMANTIC_AMBIGUITY"
        sem.append((code, f"classification: {', '.join(cls.reasons)}"))
    for name, a in semantic.get("fields", {}).items():
        f = fields.get(name)
        if f is not None and f.status in ("found", "declared_pending") and a.confidence in BLOCKING_SEMANTIC:
            sem.append(("SEMANTIC_AMBIGUITY", f"{name}: {', '.join(a.reasons)}"))
    for reason in semantic.get("blocking", []):
        sem.append((reason, reason))
    gate("SEMANTIC_INTERPRETATION", sem)

    det = [(code, f"{r}: {by_rule[r].message}") for r, code in DETERMINISTIC_RULES.items()
           if r in by_rule and by_rule[r].status == FAIL and by_rule[r].severity == ERROR]
    net = by_rule.get("AMOUNT_NET_MATCHES_GROSS_AND_TAX")
    if net and net.status == NOT_EVALUATED and net.observed.get("reason") == "ROUNDING_RULE_UNDEFINED":
        det.append(("AMOUNT_CHECK_INCONCLUSIVE", net.message))
    gate("DETERMINISTIC_VALIDATION", det)

    ref = [(code, f"{r}: {by_rule[r].message}") for r, code in REFERENCE_RULES.items()
           if r in by_rule and by_rule[r].status == FAIL and by_rule[r].severity == ERROR]
    gate("REFERENCE_VALIDATION", ref)

    gate("BLOCKING_ERRORS", [(e, e) for e in (blocking_errors or [])])
    return _decide(gates)


def _decide(gates):
    blocked = [g for g in gates if g["status"] == "BLOCK"]
    reasons = []
    for g in blocked:
        for c in g["reason_codes"]:
            if c not in reasons:
                reasons.append(c)
    return {"decision": "REVIEW_REQUIRED" if blocked else "AUTO_APPROVE", "reason_codes": reasons,
            "explanations": [e for g in blocked for e in g["explanations"]], "gates": gates}
