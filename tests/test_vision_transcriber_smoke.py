"""Fumaça do adaptador de vision (E-009) SEM API: PDF sintético + resposta gravada na chave exata da imagem (replay).
Exercita renderização, chave de cache, parsing, auditoria serializável (D-007) e a passagem pela pipeline."""
import hashlib
import io
import json
import re

from conftest import GOLDEN

from corporate_actions.models import to_jsonable
from corporate_actions.pipeline import process_document
from corporate_actions.reference import load_golden_records
from perception import vision_transcriber as V

LINES = ["AVISO AOS ACIONISTAS", "Companhia Exemplo S.A. comunica a distribuicao de dividendos.",
         "Valor bruto por acao .......... R$ 0,2500000000", "Data-base .......... 12/01/2027"]


def synthetic_scan_pdf(path):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1654, 900), "white")
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(LINES):
        draw.text((80, 80 + i * 70), line, fill="black", font=ImageFont.load_default(size=36))
    img.save(path, "PDF", resolution=150)


def png_key(pdf_path):
    import pypdfium2 as pdfium
    buf = io.BytesIO()
    pdfium.PdfDocument(str(pdf_path))[0].render(scale=V.DPI / 72).to_pil().save(buf, format="PNG")
    png_sha = hashlib.sha256(buf.getvalue()).hexdigest()
    return hashlib.sha256(f"{V.MODEL}|{V.prompt_fingerprint()}|{png_sha}".encode()).hexdigest()


def test_replayed_transcription_goes_through_the_pipeline(tmp_path):
    pdf = tmp_path / "scan.pdf"
    synthetic_scan_pdf(pdf)
    cache = tmp_path / "cache"
    cache.mkdir()
    body = {"lines": LINES, "uncertain": [{"token": "12/01/2027", "reason": "faint"}], "illegible_regions": 0}
    (cache / f"{png_key(pdf)}.json").write_text(json.dumps(
        {"id": "msg_fake", "request_id": None, "served_model": V.MODEL, "stop_reason": "end_turn",
         "usage": {"input_tokens": 100, "output_tokens": 50}, "latency_ms": 1, "estimated_cost_usd": "0.001750",
         "output_text": json.dumps(body)}), encoding="utf-8")
    vision = V.VisionTranscriber(cache_dir=cache, artifacts_dir=tmp_path / "artifacts", allow_api=False)
    rec = to_jsonable(process_document(pdf, load_golden_records(GOLDEN), "t", "I", text_fallback=vision))
    fb = rec["document"]["text_fallback"]
    assert vision.api_calls == 0 and fb["replayed_pages"] == 1 and fb["usable"]
    assert rec["extraction"]["method"] == "VISION_LLM" and fb["estimated_cost_usd"] == "0.001750"
    assert fb["uncertain_tokens"] == [{"token": "12/01/2027", "reason": "faint", "page": 1}]
    assert rec["fields"]["record_date"]["value"] == "2027-01-12"          # pontilhado + binding da I


def test_prompt_carries_no_reference_data():
    prompt = V.SYSTEM + V.INSTRUCTIONS + json.dumps(V.SCHEMA)
    assert not re.search(r"BR[A-Z]{4}ACN|[A-Z]{4}[34]\b|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|golden|referência|reference data", prompt)
