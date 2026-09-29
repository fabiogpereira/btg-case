"""Roteamento básico: AUTO_APPROVE somente sem nenhum motivo bloqueante.

Motivos bloqueantes:
- extração impossível (sem camada de texto utilizável) — falha de extração, não "é scan" (D-011);
- regra de severidade ERROR com status FAIL;
- conferência bruto/líquido inconclusiva por falta de regra de arredondamento (D-007);
- campo obrigatório com confiança LOW.
O Baseline A nunca emite REJECT (D-008: ausência na referência não prova invalidade).
"""
from .models import ERROR, FAIL, LOW, NOT_EVALUATED

AUTO_APPROVE, REVIEW_REQUIRED = "AUTO_APPROVE", "REVIEW_REQUIRED"

RULE_REASON = {
    "REF_ISIN_FOUND": "REFERENCE_NOT_FOUND",
    "REF_TICKER_CONSISTENT": "REFERENCE_MISMATCH",
    "REF_CNPJ_CONSISTENT": "REFERENCE_MISMATCH",
    "REF_SHARE_CLASS_CONSISTENT": "REFERENCE_MISMATCH",
    "REF_ISSUER_ACTIVE": "REFERENCE_INACTIVE",
    "REQUIRED_FIELDS_PRESENT": "REQUIRED_FIELD_MISSING",
    "CLASSIFICATION_DETERMINED": "CLASSIFICATION_UNDETERMINED",
    "CLASSIFICATION_TITLE_CONSISTENT": "CLASSIFICATION_TITLE_CONFLICT",
    "DATE_APPROVAL_NOT_AFTER_RECORD": "DATE_INCONSISTENCY",
    "DATE_RECORD_BEFORE_EX": "DATE_INCONSISTENCY",
    "DATE_SETTLEMENT_NOT_BEFORE_EX": "DATE_INCONSISTENCY",
    "AMOUNT_GROSS_POSITIVE": "AMOUNT_INCONSISTENCY",
    "AMOUNT_NET_MATCHES_GROSS_AND_TAX": "AMOUNT_INCONSISTENCY",
    "RATIO_POSITIVE": "RATIO_INCONSISTENCY",
    "RATIO_PERCENTAGE_CONSISTENT": "RATIO_INCONSISTENCY",
}


def route(text_layer_usable: bool, validations, fields, required_fields) -> dict:
    if not text_layer_usable:
        return {"decision": REVIEW_REQUIRED, "reason_codes": ["NO_USABLE_TEXT_LAYER"],
                "explanations": ["Sem camada de texto utilizável e sem fallback de extração no Baseline A."]}
    reasons, explanations = [], []

    def add(code, why):
        if code not in reasons:
            reasons.append(code)
        explanations.append(why)

    for v in validations:
        if v.severity == ERROR and v.status == FAIL:
            if v.rule_id == "REQUIRED_FIELDS_NOT_PENDING":
                pending = v.observed.get("declared_pending", [])
                code = "PAYMENT_DATE_PENDING" if "payment_date" in pending else "REQUIRED_FIELD_PENDING"
            else:
                code = RULE_REASON.get(v.rule_id, "VALIDATION_FAILED")
            add(code, f"{v.rule_id}: {v.message}")
        elif v.rule_id == "AMOUNT_NET_MATCHES_GROSS_AND_TAX" and v.status == NOT_EVALUATED \
                and v.observed.get("reason") == "ROUNDING_RULE_UNDEFINED":
            add("AMOUNT_CHECK_INCONCLUSIVE", f"{v.rule_id}: {v.message}")
    for name in required_fields:
        f = fields.get(name)
        if f is not None and f.confidence == LOW:
            add("LOW_EXTRACTION_CONFIDENCE", f"{name}: {', '.join(f.confidence_reasons)}")
    decision = REVIEW_REQUIRED if reasons else AUTO_APPROVE
    return {"decision": decision, "reason_codes": reasons, "explanations": explanations}
