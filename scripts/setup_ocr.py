"""Prepara `.ocr/tessdata/` para o OCR local (modelo português fixado + configs do Tesseract instalado).

Pré-requisito: Tesseract 5.x instalado (Windows: `winget install --id UB-Mannheim.TesseractOCR -e`;
Linux: `apt install tesseract-ocr`; macOS: `brew install tesseract`).

    python scripts/setup_ocr.py [--tesseract-tessdata DIR]

Baixa `por.traineddata` da tag 4.1.0 de github.com/tesseract-ocr/tessdata e confere o SHA-256 usado nos
experimentos (FREEZE_OCR_H1.json). Copia `configs/` (necessário para a saída TSV) do tessdata do Tesseract.
"""
import argparse
import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".ocr" / "tessdata"
POR_URL = "https://github.com/tesseract-ocr/tessdata/raw/4.1.0/por.traineddata"
POR_SHA256 = "016c6a371bb1e4c48fe521908cf3ba3d751fade0ab846ad5d4086b563f5c528c"
CANDIDATES = [Path(r"C:\Program Files\Tesseract-OCR\tessdata"), Path("/usr/share/tesseract-ocr/5/tessdata"),
              Path("/usr/share/tesseract-ocr/4.00/tessdata"), Path("/opt/homebrew/share/tessdata"), Path("/usr/local/share/tessdata")]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tesseract-tessdata", type=Path, default=None)
    a = p.parse_args()
    source = a.tesseract_tessdata or next((c for c in CANDIDATES if (c / "configs").is_dir()), None)
    if source is None or not (source / "configs").is_dir():
        sys.exit("tessdata do Tesseract não encontrado; informe --tesseract-tessdata DIR")
    TARGET.mkdir(parents=True, exist_ok=True)
    model = TARGET / "por.traineddata"
    if not model.exists():
        urllib.request.urlretrieve(POR_URL, model)
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    if digest != POR_SHA256:
        model.unlink()
        sys.exit(f"SHA-256 inesperado para por.traineddata ({digest}); arquivo removido")
    shutil.copytree(source / "configs", TARGET / "configs", dirs_exist_ok=True)
    print(f"ok: {model} (sha256 {digest[:12]}…), configs de {source}")


if __name__ == "__main__":
    main()
