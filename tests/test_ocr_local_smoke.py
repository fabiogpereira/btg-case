"""Fumaça do adaptador OCR real (E-008): PDF sintético gerado aqui -> PDFium -> Tesseract -> pipeline.
Exercita setup, artefatos e serialização (D-007) sem usar nenhum documento do case. Pulado se o Tesseract não existir."""
import io

import pytest
from conftest import GOLDEN

from corporate_actions.ingestion import DocumentInput
from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import process_document
from corporate_actions.reference import load_golden_records
from perception.ocr_local import DEFAULT_TESSDATA, DEFAULT_TESSERACT, TesseractOCR

pytestmark = pytest.mark.skipif(not DEFAULT_TESSERACT.exists() or not (DEFAULT_TESSDATA / "por.traineddata").exists(),
                                reason="Tesseract/modelo por não instalados (ver requirements-ocr.txt)")
LINES = ["AVISO AOS ACIONISTAS", "Companhia Exemplo S.A. comunica a distribuicao de dividendos.",
         "Valor bruto por acao R$ 0,2500000000", "Data-base: 12/01/2027", "Data ex: 13/01/2027"]


def synthetic_scan_pdf(path):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1654, 900), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=36)
    for i, line in enumerate(LINES):
        draw.text((80, 80 + i * 70), line, fill="black", font=font)
    img.save(path, "PDF", resolution=150)          # PDF só com imagem: sem camada de texto


def test_adapter_end_to_end_is_serializable_and_audited(tmp_path):
    pdf = tmp_path / "scan.pdf"
    synthetic_scan_pdf(pdf)
    ocr = TesseractOCR(artifacts_dir=tmp_path / "artifacts")
    rec = to_jsonable(process_document(pdf, load_golden_records(GOLDEN), "t", "H", text_fallback=ocr))
    fb = rec["document"]["text_fallback"]
    assert rec["document"]["text_layer"]["usable"] is False and fb["trigger"] == "NO_USABLE_TEXT_LAYER" and fb["usable"]
    assert rec["extraction"]["method"] == "OCR_LOCAL" and isinstance(fb["mean_word_confidence"], str)
    assert (tmp_path / "artifacts" / rec["document"]["sha256"] / "page-1.tsv").exists()
    assert "12/01/2027" in (tmp_path / "artifacts" / rec["document"]["sha256"] / "page-1.txt").read_text(encoding="utf-8")
