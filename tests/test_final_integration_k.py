"""Solução final (E-011, variante K): roteamento de percepção, falha segura e política de incerteza integrada.
OCR e vision falsos (contam chamadas); aviso sintético próprio. Nenhum documento do case é lido como texto."""
from decimal import Decimal

from conftest import DOCS, GOLDEN

from corporate_actions import critical_fields as C
from corporate_actions import uncertainty as U
from corporate_actions.ingestion import MIN_ALNUM_CHARS_PER_PAGE, TextLayer, normalize_whitespace
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import SemanticContext, process_document
from corporate_actions.reference import load_golden_records
from perception.router import PerceptionRouter, _OfflineSemanticLLM

GOLD = load_golden_records(GOLDEN)
SCAN = next(DOCS.glob("07_*.pdf"))           # PDF sem camada de texto; o conteúdo vem das percepções falsas
NATIVE = next(DOCS.glob("01_*.pdf"))

HEAD = ("LOGÍSTICA ATLÂNTICO S.A.\nCompanhia Aberta | CNPJ/ME nº 77.888.999/0001-46\nAVISO AOS ACIONISTAS — Juros sobre o Capital Próprio\n"
        "A Logística Atlântico S.A. comunica que o Conselho de Administração aprovou, em reunião realizada em 01/10/2026, "
        "o pagamento de juros sobre o capital próprio.\nValor bruto por ação ON R$ 0,5000000000\nIRRF 15%\n"
        "Valor líquido por ação ON R$ 0,4250000000\nData-base: 13/10/2026\nData ex: 14/10/2026\n")
PAY = "Data de pagamento: 30/10/2026\n"
FULL = HEAD + PAY + "Código de negociação LGAT3 (ISIN BRLGATACNOR6)\n"
NO_TICKER = HEAD + PAY + "(ISIN BRLGATACNOR6)\n"


def layer(text):
    norm = normalize_whitespace(text)
    alnum = sum(c.isalnum() for c in norm)
    return TextLayer(usable=alnum >= MIN_ALNUM_CHARS_PER_PAGE, pages=1, alnum_chars=alnum,
                     min_alnum_chars_per_page=MIN_ALNUM_CHARS_PER_PAGE, page_texts=[text], normalized_text=norm,
                     page_offsets=[0], reason=None)


class FakeOCR:
    def __init__(self, text, fail=False, confidence=Decimal("90")):
        self.text, self.fail, self.confidence, self.calls = text, fail, confidence, 0

    def describe(self):
        return {"extraction_method": "OCR_LOCAL", "engine": "fake-ocr"}

    def __call__(self, doc):
        self.calls += 1
        if self.fail:
            raise RuntimeError("tesseract unavailable")
        return layer(self.text), {**self.describe(), "mean_word_confidence": self.confidence}


class FakeVision:
    def __init__(self, text=FULL, uncertain=(), fail=False):
        self.text, self.uncertain, self.fail, self.calls = text, list(uncertain), fail, 0

    def describe(self):
        return {"extraction_method": "VISION_LLM", "engine": "fake-vision", "model": "fake"}

    def __call__(self, doc):
        self.calls += 1
        if self.fail:
            raise TimeoutError("vision API timeout")
        return layer(self.text), {**self.describe(), "uncertain_tokens": [{"token": t, "reason": "t", "page": 1} for t in self.uncertain],
                                  "usage": {"input_tokens": 100, "output_tokens": 50}, "estimated_cost_usd": Decimal("0.0450")}


def run(ocr, vision, path=SCAN):
    router = PerceptionRouter(GOLD, ocr, vision)
    return to_jsonable(process_document(path, GOLD, "t", "K", SemanticContext(_OfflineSemanticLLM()), text_fallback=router))


def test_native_text_never_calls_ocr_or_vision():
    ocr, vision = FakeOCR(FULL), FakeVision()
    rec = run(ocr, vision, path=NATIVE)
    assert ocr.calls == vision.calls == 0
    assert rec["perception"]["path"] == "NATIVE_TEXT" and rec["extraction"]["method"] == "NATIVE_TEXT"
    assert rec["run_summary"]["ocr_called"] is False and rec["run_summary"]["vision_called"] is False


def test_complete_ocr_is_used_and_vision_is_not_called():
    ocr, vision = FakeOCR(FULL), FakeVision()
    rec = run(ocr, vision)
    assert ocr.calls == 1 and vision.calls == 0
    assert rec["perception"]["path"] == "OCR_LOCAL" and rec["perception"]["decision"]["ocr_probe_reasons"] == []
    assert rec["routing"]["decision"] == "AUTO_APPROVE"


def test_low_ocr_confidence_alone_does_not_call_vision():
    ocr, vision = FakeOCR(FULL, confidence=Decimal("41")), FakeVision()
    rec = run(ocr, vision)
    assert vision.calls == 0 and rec["perception"]["path"] == "OCR_LOCAL"


def test_missing_required_ticker_after_ocr_calls_vision_as_a_new_full_perception():
    ocr, vision = FakeOCR(NO_TICKER), FakeVision()
    rec = run(ocr, vision)
    assert vision.calls == 1 and rec["perception"]["path"] == "VISION_FALLBACK"
    assert rec["perception"]["decision"]["fallback_reasons"] == ["REQUIRED_TICKER_MISSING_AFTER_OCR"]
    assert rec["extraction"]["method"] == "VISION_FALLBACK" and rec["document"]["text_fallback"]["ocr_evidence"]["engine"] == "fake-ocr"
    assert rec["fields"]["ticker"]["value"] == "LGAT3" and rec["routing"]["decision"] == "AUTO_APPROVE"


def test_no_field_by_field_merge_between_ocr_and_vision():
    # o OCR leu a data de pagamento; o vision não. A pipeline usa SÓ o vision: a data fica ausente -> revisão
    ocr, vision = FakeOCR(NO_TICKER), FakeVision(text=HEAD + "Código de negociação LGAT3 (ISIN BRLGATACNOR6)\n")
    rec = run(ocr, vision)
    assert rec["perception"]["path"] == "VISION_FALLBACK" and rec["fields"]["payment_date"]["status"] == "not_found"
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_declared_pending_field_is_not_a_reason_to_call_vision():
    ocr, vision = FakeOCR(HEAD + "Data de pagamento: a definir\nCódigo de negociação LGAT3 (ISIN BRLGATACNOR6)\n"), FakeVision()
    rec = run(ocr, vision)
    assert vision.calls == 0 and rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_unresolved_identity_after_ocr_calls_vision():
    ocr, vision = FakeOCR(HEAD + PAY + "Código de negociação LGAT3 (ISIN BRLGATACNOR9)\n"), FakeVision()
    rec = run(ocr, vision)
    assert vision.calls == 1
    assert "CRITICAL_IDENTIFIER_UNRESOLVED_AFTER_OCR:REFERENCE_NOT_FOUND" in rec["perception"]["decision"]["fallback_reasons"]


def test_vision_failure_is_fail_safe():
    ocr, vision = FakeOCR(NO_TICKER), FakeVision(fail=True)
    rec = run(ocr, vision)
    assert rec["perception"]["path"] == "OCR_LOCAL" and rec["perception"]["vision_error"].startswith("TimeoutError")
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_unusable_vision_output_is_fail_safe():
    rec = run(FakeOCR(NO_TICKER), FakeVision(text="???"))
    assert rec["perception"]["path"] == "OCR_LOCAL" and rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_ocr_failure_is_fail_safe():
    rec = run(FakeOCR(FULL, fail=True), FakeVision())
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED" and rec["routing"]["reason_codes"] == ["PROCESSING_ERROR"]


def test_uncertainty_policy_applies_to_vision_fallback():
    rec = run(FakeOCR(NO_TICKER), FakeVision(uncertain=["30/10/2026"]))
    assert rec["perception_uncertainty"]["fields"]["payment_date"]["blocking_reason"] == "CRITICAL_FIELD_UNCERTAIN_UNCORROBORATED"
    assert rec["routing"]["decision"] == "REVIEW_REQUIRED"


def test_corroborated_uncertain_identifier_proceeds_with_audit_trail():
    rec = run(FakeOCR(NO_TICKER), FakeVision(uncertain=["BRLGATACNOR6"]))
    f = rec["perception_uncertainty"]["fields"]["isin"]
    assert f["corroboration_status"] == "EXACT_MATCH" and rec["routing"]["decision"] == "AUTO_APPROVE"


def test_run_summary_separates_perception_and_semantic_costs():
    s = run(FakeOCR(NO_TICKER), FakeVision())["run_summary"]
    assert s["perception_path"] == "VISION_FALLBACK" and s["vision_called"] and s["ocr_called"]
    assert s["estimated_cost_usd"] == {"perception": "0.0450", "semantic_llm": "0", "total": "0.0450"}
    assert s["semantic_llm_called"] is False and "total" in s["duration_ms"]


def test_single_definition_of_critical_fields():
    assert U.critical_fields is C.critical_fields
    assert "ticker" in C.required_critical_fields("JCP") and "ratio" in C.required_critical_fields("SPLIT")
