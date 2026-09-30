"""Hook `text_fallback` (E-008): só roda sem camada nativa utilizável; identidade = SHA-256 do PDF; auditoria no registro.
Fallback falso (sem Tesseract), com texto sintético."""
from conftest import DOCS, GOLDEN

from corporate_actions.ingestion import MIN_ALNUM_CHARS_PER_PAGE, TextLayer, normalize_whitespace
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import process_document
from corporate_actions.reference import load_golden_records

GOLD = load_golden_records(GOLDEN)
SCAN = next(DOCS.glob("07_*.pdf"))
NATIVE = next(DOCS.glob("01_*.pdf"))


class FakeFallback:
    def __init__(self, text):
        self.text, self.calls = text, 0

    def __call__(self, doc):
        self.calls += 1
        norm = normalize_whitespace(self.text)
        alnum = sum(c.isalnum() for c in norm)
        tl = TextLayer(usable=alnum >= MIN_ALNUM_CHARS_PER_PAGE, pages=1, alnum_chars=alnum,
                       min_alnum_chars_per_page=MIN_ALNUM_CHARS_PER_PAGE, page_texts=[self.text], normalized_text=norm,
                       page_offsets=[0], reason=None)
        return tl, {"extraction_method": "OCR_LOCAL", "engine": "fake"}


TEXT = ("AVISO AOS ACIONISTAS\nA Companhia Exemplo S.A. comunica a distribuição de dividendos aos acionistas.\n"
        "Valor bruto por ação R$ 0,1000000000\nData-base: 10/01/2027\nData ex: 11/01/2027\nData de pagamento: 20/01/2027\n")


def test_fallback_never_runs_when_native_text_is_usable():
    fb = FakeFallback(TEXT)
    rec = to_jsonable(process_document(NATIVE, GOLD, "t", "H", text_fallback=fb))
    assert fb.calls == 0 and "text_fallback" not in rec["document"]
    assert rec["extraction"]["method"] == "native_text_layer+deterministic_rules"


def test_fallback_text_goes_through_the_same_pipeline_and_keeps_pdf_identity():
    fb = FakeFallback(TEXT)
    rec = to_jsonable(process_document(SCAN, GOLD, "t", "H", text_fallback=fb))
    assert fb.calls == 1
    assert rec["document"]["text_fallback"]["trigger"] == "NO_USABLE_TEXT_LAYER" and rec["document"]["text_fallback"]["usable"]
    assert rec["document"]["text_layer"]["usable"] is False          # a camada nativa continua registrada como inutilizável
    assert rec["extraction"]["method"] == "OCR_LOCAL" and rec["audit"]["extraction_method"] == "OCR_LOCAL"
    assert rec["document"]["sha256"] == "cf4af08dd23f507ae72b852d86827bbee6c3fe2d0e31f96e70bc74ea4238c45f"
    assert rec["classification"]["event_type"] == "DIVIDEND"


def test_unusable_fallback_text_keeps_no_usable_text_layer():
    rec = to_jsonable(process_document(SCAN, GOLD, "t", "H", text_fallback=FakeFallback("ilegível")))
    assert rec["routing"]["reason_codes"] == ["NO_USABLE_TEXT_LAYER"] and rec["document"]["text_fallback"]["usable"] is False
