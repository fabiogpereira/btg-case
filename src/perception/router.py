"""Roteador de percepção da solução final (E-011). Usado como `text_fallback` da pipeline: só roda quando a camada de
texto nativa não é utilizável (a pipeline decide isso; o nome do arquivo nunca entra).

1. OCR local (Tesseract, configuração do E-008/E-009).
2. Sondagem determinística do texto do OCR: a MESMA pipeline congelada, sem LLM semântico (provedor offline), só para
   saber o que a leitura determinística recupera. Nada da sondagem vai para o registro final além do diagnóstico.
3. Vision é chamado SOMENTE se, após OCR + parsing, algum campo crítico obrigatório (`critical_fields`) ficou:
   - ausente                         -> REQUIRED_<CAMPO>_MISSING_AFTER_OCR
   - com valores divergentes          -> REQUIRED_MATERIAL_FIELD_UNRESOLVED:<campo>
   - identidade não resolvida         -> CRITICAL_IDENTIFIER_UNRESOLVED_AFTER_OCR:<motivo>
   - tipo de evento indeterminado     -> EVENT_TYPE_UNRESOLVED_AFTER_OCR
   - texto OCR inutilizável           -> OCR_TEXT_NOT_USABLE
   Confiança baixa do OCR, caracteres estranhos, "ser scan" ou "qualidade melhor" não chamam vision. Campo declarado
   pendente ("a definir") é leitura bem-sucedida, não ausência.
4. Vision gera uma percepção NOVA e COMPLETA; a pipeline usa OCR **ou** vision, nunca uma mistura campo a campo. O OCR
   continua registrado como evidência operacional (auditoria, artefatos), sem alimentar campos.
5. Falha técnica do vision (indisponível, timeout, saída malformada): a percepção fica sendo a do OCR, que já deixou
   campo obrigatório ausente -> revisão; a falha é registrada. Falha do OCR propaga para a pipeline -> PROCESSING_ERROR
   -> revisão. Nunca aprovação por fallback técnico.
"""
from corporate_actions.critical_fields import required_critical_fields


class _OfflineSemanticLLM:
    """Provedor que nunca chama rede: a sondagem mede só a leitura determinística."""
    name = "offline-probe"

    def __init__(self):
        from corporate_actions.llm.config import LLMConfig
        self.config = LLMConfig("offline", "none", "none", 0, "off", 1)

    def structured_call(self, *args, **kwargs):
        from corporate_actions.llm.base import LLMResponse
        resp = LLMResponse(self.name, "none", None, None, None, None, 0)
        resp.errors.append("offline probe: semantic LLM not called during perception routing")
        return resp


def completeness_reasons(probe: dict) -> list[str]:
    if (probe.get("extraction") or {}).get("status") != "COMPLETED":
        return ["OCR_TEXT_NOT_USABLE"]
    event_type = (probe.get("classification") or {}).get("event_type")
    if event_type is None:
        return ["EVENT_TYPE_UNRESOLVED_AFTER_OCR"]
    fields = {**(probe.get("fields") or {}), **(probe.get("event_specific_fields") or {})}
    reasons = []
    for name in required_critical_fields(event_type):
        f = fields.get(name)
        status = f["status"] if f else "ABSENT"
        if status in ("not_found", "ABSENT"):
            if name == "isin" and (probe.get("identity") or {}).get("status") == "RESOLVED":
                continue                        # ISIN dispensado pela identidade de nível 2 (E-007)
            reasons.append(f"REQUIRED_{name.upper()}_MISSING_AFTER_OCR")
        elif status == "found" and f.get("distinct_values", 1) > 1:
            reasons.append(f"REQUIRED_MATERIAL_FIELD_UNRESOLVED:{name}")
    identity = probe.get("identity") or {}
    if identity.get("status") == "UNRESOLVED":
        reasons.append(f"CRITICAL_IDENTIFIER_UNRESOLVED_AFTER_OCR:{identity.get('reason_code')}")
    return reasons


class PerceptionRouter:
    def __init__(self, golden, ocr, vision, variant: str = "K"):
        self.golden, self.ocr, self.vision, self.variant = golden, ocr, vision, variant

    def describe(self) -> dict:
        return {"policy": "native -> OCR local -> vision (secondary, only on missing/unresolved critical required field)",
                "ocr": self.ocr.describe(), "vision": self.vision.describe()}

    def __call__(self, doc):
        from corporate_actions.pipeline import SemanticContext, process_document
        from corporate_actions.models import to_jsonable
        ocr_tl, ocr_audit = self.ocr(doc)
        probe = to_jsonable(process_document(doc.path, self.golden, "perception-probe", self.variant,
                                             SemanticContext(_OfflineSemanticLLM()), text_fallback=lambda _d: (ocr_tl, ocr_audit)))
        reasons = completeness_reasons(probe)
        ocr_summary = {k: ocr_audit.get(k) for k in ("engine", "engine_version", "lang", "model_sha256", "oem", "psm", "dpi",
                                                     "duration_ms", "words", "mean_word_confidence", "low_confidence_words",
                                                     "page_artifacts")}
        ocr_summary["usable"] = ocr_tl.usable
        decision = {"ocr_probe_reasons": reasons, "ocr_probe_routing": probe["routing"]["reason_codes"]}
        if not reasons:
            return ocr_tl, {**ocr_audit, "extraction_method": "OCR_LOCAL", "perception_path": "OCR_LOCAL",
                            "vision_called": False, "perception_decision": decision}
        try:
            vis_tl, vis_audit = self.vision(doc)
            if not vis_tl.usable:
                raise ValueError("vision text not usable")
        except Exception as exc:                # falha técnica: fica o OCR (incompleto) -> revisão
            return ocr_tl, {**ocr_audit, "extraction_method": "OCR_LOCAL", "perception_path": "OCR_LOCAL",
                            "vision_called": True, "vision_error": f"{type(exc).__name__}: {exc}",
                            "perception_decision": {**decision, "vision_fallback_failed": True}}
        return vis_tl, {**vis_audit, "extraction_method": "VISION_FALLBACK", "perception_path": "VISION_FALLBACK",
                        "vision_called": True, "perception_decision": {**decision, "fallback_reasons": reasons},
                        "ocr_evidence": ocr_summary}
