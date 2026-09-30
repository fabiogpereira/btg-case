"""OCR local (E-008, H1): PDF -> imagem (PDFium) -> Tesseract -> TextLayer. Só percepção.

Configuração baseline, sem otimização (seção 11 do pedido): 300 DPI, `--oem 1` (LSTM), `--psm 3` (layout automático),
idioma `por`, sem deskew/denoise, sem dicionário de emissores, sem pós-correção. O texto sai exatamente como o
Tesseract o produz; números nunca são "corrigidos".

Auditoria devolvida ao pipeline: motor e versão, modelo (SHA-256), renderizador, parâmetros, páginas, duração
(render e OCR), confiança por palavra (média, palavras de baixa confiança, tokens numéricos de baixa confiança) e os
artefatos brutos (TXT e TSV do Tesseract, SHA-256 da imagem renderizada). A identidade do documento continua sendo o
SHA-256 do PDF original (o pipeline não usa o hash da imagem).

Setup reproduzível: Tesseract 5.4.0.20240606 (UB-Mannheim, `winget install UB-Mannheim.TesseractOCR`), modelo
`por.traineddata` da tag 4.1.0 de github.com/tesseract-ocr/tessdata em `.ocr/tessdata/` (SHA-256 no FREEZE do
experimento), `pypdfium2` e `Pillow` (requirements-ocr.txt).
"""
import csv
import hashlib
import io
import re
import subprocess
import tempfile
import time
from pathlib import Path

from corporate_actions.ingestion import MIN_ALNUM_CHARS_PER_PAGE, TextLayer, normalize_whitespace

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
DEFAULT_TESSDATA = ROOT / ".ocr" / "tessdata"
LOW_CONFIDENCE = 60          # confiança de palavra (0–100) abaixo da qual a palavra é listada na auditoria


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class TesseractOCR:
    def __init__(self, tesseract: Path = DEFAULT_TESSERACT, tessdata: Path = DEFAULT_TESSDATA, lang: str = "por",
                 dpi: int = 300, oem: int = 1, psm: int = 3, artifacts_dir: Path | None = None):
        self.tesseract, self.tessdata, self.lang = Path(tesseract), Path(tessdata), lang
        self.dpi, self.oem, self.psm, self.artifacts_dir = dpi, oem, psm, artifacts_dir

    def describe(self) -> dict:
        import PIL
        import pypdfium2
        version = subprocess.run([str(self.tesseract), "--version"], capture_output=True, text=True).stdout.splitlines()[0]
        model = self.tessdata / f"{self.lang}.traineddata"
        return {"extraction_method": "OCR_LOCAL", "engine": "tesseract", "engine_version": version.split()[-1],
                "lang": self.lang, "model_sha256": _sha(model.read_bytes()), "oem": self.oem, "psm": self.psm,
                "dpi": self.dpi, "renderer": f"pypdfium2 {pypdfium2.version.PYPDFIUM_INFO}", "pillow": PIL.__version__,
                "preprocessing": None, "post_correction": None}

    def __call__(self, doc):
        import pypdfium2 as pdfium
        info = self.describe()
        t0 = time.perf_counter()
        pdf = pdfium.PdfDocument(io.BytesIO(doc.content))
        page_texts, pages_audit, words, render_ms, ocr_ms = [], [], [], 0, 0
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(len(pdf)):
                r0 = time.perf_counter()
                image = pdf[i].render(scale=self.dpi / 72).to_pil()
                png = Path(tmp) / f"page-{i + 1}.png"
                image.save(png)
                render_ms += int((time.perf_counter() - r0) * 1000)
                o0 = time.perf_counter()
                base = Path(tmp) / f"page-{i + 1}"
                subprocess.run([str(self.tesseract), str(png), str(base), "-l", self.lang, "--oem", str(self.oem),
                                "--psm", str(self.psm), "--tessdata-dir", str(self.tessdata), "txt", "tsv"],
                               check=True, capture_output=True)
                ocr_ms += int((time.perf_counter() - o0) * 1000)
                txt = base.with_suffix(".txt").read_text(encoding="utf-8")
                tsv = base.with_suffix(".tsv").read_text(encoding="utf-8")
                page_words = [(row["text"], float(row["conf"])) for row in csv.DictReader(io.StringIO(tsv), delimiter="\t",
                                                                                          quoting=csv.QUOTE_NONE)
                              if row.get("text", "").strip() and float(row["conf"]) >= 0]
                words += page_words
                page_texts.append(txt)
                artifact = {"page": i + 1, "image_px": list(image.size), "image_sha256": _sha(png.read_bytes()),
                            "text_sha256": _sha(txt.encode("utf-8")), "tsv_sha256": _sha(tsv.encode("utf-8"))}
                if self.artifacts_dir is not None:
                    out = self.artifacts_dir / doc.sha256
                    out.mkdir(parents=True, exist_ok=True)
                    (out / f"page-{i + 1}.txt").write_text(txt, encoding="utf-8")
                    (out / f"page-{i + 1}.tsv").write_text(tsv, encoding="utf-8")
                    artifact["raw_text_path"] = (out / f"page-{i + 1}.txt").relative_to(ROOT).as_posix()
                    artifact["raw_tsv_path"] = (out / f"page-{i + 1}.tsv").relative_to(ROOT).as_posix()
                pages_audit.append(artifact)
        offsets, parts, cursor = [], [], 0
        for text in page_texts:
            norm = normalize_whitespace(text)
            offsets.append(cursor)
            parts.append(norm)
            cursor += len(norm) + 1
        normalized = " ".join(parts)
        alnum = sum(ch.isalnum() for ch in normalized)
        usable = bool(page_texts) and alnum >= MIN_ALNUM_CHARS_PER_PAGE * len(page_texts)
        tl = TextLayer(usable=usable, pages=len(page_texts), alnum_chars=alnum, min_alnum_chars_per_page=MIN_ALNUM_CHARS_PER_PAGE,
                       page_texts=page_texts, normalized_text=normalized, page_offsets=offsets,
                       reason=None if usable else "OCR_TEXT_NOT_USABLE")
        confs = [c for _, c in words]
        low = [(w, c) for w, c in words if c < LOW_CONFIDENCE]
        audit = {**info, "pages": len(page_texts), "duration_ms": {"render": render_ms, "ocr": ocr_ms,
                                                                    "total": int((time.perf_counter() - t0) * 1000)},
                 "words": len(words), "mean_word_confidence": round(sum(confs) / len(confs), 1) if confs else None,
                 "low_confidence_words": len(low),
                 "low_confidence_numeric_tokens": [{"token": w, "conf": c} for w, c in low if re.search(r"\d", w)],
                 "page_artifacts": pages_audit}
        return tl, audit
