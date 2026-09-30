"""Qualificadores v3 (E-005): o LLM separa material × nota; o código aplica guarda de escopo e política.

Política (sem score):
- semantic_notes (operational_instruction, legal_context, informational_context): registradas, NUNCA bloqueiam.
- material_qualifiers com citação localizada:
    1. guarda de escopo: se, removidos da citação os trechos de evidência rótulo+valor dos campos extraídos
       e as repetições entre parênteses, não sobra conteúdo, a citação é um rótulo de campo com seu valor,
       não um qualificador -> rebaixada para nota (SCOPE_GUARD);
    2. se o efeito JÁ está representado no registro -> não bloqueia:
         tax_base (material_condition)      <- withholding_tax.base == EXCESS_OVER_THRESHOLD
       (base plana GROSS_AMOUNT nunca "representa" uma condição sobre a base: bloqueia — seguro)
         beneficiary_tax_treatment          <- anotado em withholding_tax.notes (exceção por titular)
         effective_dates sobre data pendente <- campo declared_pending cuja evidência contém a citação
    3. senão -> bloqueia (efeito material não representado, ou `unresolved` com efeito potencial).
- citação não localizada -> descartada (nada inventado).
"""
import re

from .confidence_model import SemanticAssessment
from .models import DECLARED_PENDING, FOUND, LOW

DATE_FIELDS = {"record_date", "ex_date", "payment_date", "share_credit_date", "approval_date"}
TAX_AFFECTS = {"tax_base", "tax_rate", "beneficiary_tax_treatment"}


def _field_spans(fields: dict, specific: dict) -> list[tuple[int, int]]:
    return [(e.start, e.end) for f in {**fields, **specific}.values()
            if f.status in (FOUND, DECLARED_PENDING) for e in f.evidence]


def scope_guard(span, field_spans, text: str) -> str | None:
    """Rótulo de campo com o próprio valor não é qualificador. Genérico: o que resta da citação fora da
    evidência dos campos extraídos (descontadas repetições entre parênteses) não expressa nenhuma relação."""
    s, e = span
    rest = "".join(text[i] for i in range(s, e) if not any(fs <= i < fe for fs, fe in field_spans))
    rest = re.sub(r"\([^)]*\)", " ", rest)
    return None if re.search(r"\w", rest) else "SCOPE_GUARD_FIELD_LABEL_OR_VALUE"


def representation(q: dict, fields: dict, specific: dict) -> str | None:
    affects, target = q["affects"], q["target_field"]
    wt = fields.get("withholding_tax")
    base = wt.value.get("base") if wt is not None and wt.status == FOUND else None
    if affects == "tax_base":
        if q["kind"] == "material_condition" and base == "EXCESS_OVER_THRESHOLD":
            return "withholding_tax.base=EXCESS_OVER_THRESHOLD"
    if affects == "beneficiary_tax_treatment" and wt is not None and wt.status == FOUND:
        return "withholding_tax.notes (exceção por titular)"
    if affects == "effective_dates" and target in DATE_FIELDS:
        f = fields.get(target) or specific.get(target)
        if f is not None and f.status == DECLARED_PENDING and q["span"] and \
                any(e.start <= q["span"][0] and q["span"][1] <= e.end for e in f.evidence):
            return f"{target}=declared_pending"
    return None


def evaluate(grounding: dict, fields: dict, specific: dict, field_sem: dict, text: str):
    """Retorna (qualificadores materiais avaliados, notas, entradas de bloqueio no nível do registro).
    Bloqueios em campos (IR, datas) entram como semântica LOW no campo afetado."""
    spans = _field_spans(fields, specific)
    material, notes, blocking = [], [], []
    for n in grounding["semantic_notes"]:
        if n["grounded"]:
            notes.append({"kind": n["kind"], "note": n["note"], "quote": n["quote"], "blocks": False, "source": "llm"})
    for q in grounding["material_qualifiers"]:
        if not q["grounded"]:
            continue
        guard = scope_guard(q["span"], spans, text)
        if guard:
            notes.append({"kind": "scope_guard_rejected", "note": f"{guard}: {q['effect']}", "quote": q["quote"],
                          "blocks": False, "source": "llm", "rejected_as": q["kind"]})
            continue
        rep = representation(q, fields, specific)
        entry = {k: q[k] for k in ("kind", "affects", "target_field", "effect", "materiality_reason", "quote")}
        entry.update(represented=rep is not None, representation=rep, blocks=rep is None, source="llm")
        material.append(entry)
        if rep and q["affects"] == "beneficiary_tax_treatment":
            fields["withholding_tax"].notes.append(f"beneficiary exception: {q['quote']}")
        if not entry["blocks"]:
            continue
        code = f"MATERIAL_QUALIFIER_UNREPRESENTED:{q['affects']}"
        target = "withholding_tax" if q["affects"] in TAX_AFFECTS else q["target_field"]
        if target in fields or target in specific:
            prev = field_sem.get(target)
            field_sem[target] = SemanticAssessment(LOW, "llm", (prev.reasons if prev else []) + [code],
                                                   prev.qualifiers if prev else [])
        else:
            blocking.append(code)
    return material, notes, blocking


def project_b(assessment) -> list[dict]:
    """Qualificadores do patch B na visão v3 (auditoria dos documentos sem LLM)."""
    types = {q["type"] for q in assessment.qualifiers}
    out = []
    for q in assessment.qualifiers:
        if q["type"] == "EXCEPTION" and "HOLDER_EXEMPTION" in types:
            continue
        kind, affects = {"THRESHOLD": ("material_condition", "tax_base"),
                         "HOLDER_EXEMPTION": ("material_exception", "beneficiary_tax_treatment")}.get(q["type"], ("unresolved", None))
        out.append({"kind": kind, "affects": affects, "quote": q["cue"], "source": "deterministic_patch",
                    "blocks": assessment.confidence == LOW})
    return out


def as_v2_like(material: list[dict]) -> list[dict]:
    """Adapta para as funções de fusão v2 reutilizadas (merge_dates/merge_tax)."""
    m = {"tax_base": "tax_base", "tax_rate": "tax_rate", "beneficiary_tax_treatment": "tax_application",
         "effective_dates": "dates"}
    return [{"qualifier_type": q["kind"], "affects": m.get(q["affects"], q["affects"]), "effect": q["effect"],
             "quote": q["quote"], "blocks": q["blocks"]} for q in material]
