"""Ingestão: bytes do documento, identidade por SHA-256 e extração da camada de texto nativa.

O nome do arquivo é guardado apenas como metadado de auditoria (D-004); nada aqui o interpreta.
"""
import hashlib
import io
import re
from dataclasses import dataclass
from pathlib import Path

import pypdf

# Uma página com camada de texto utilizável tem pelo menos isto de caracteres alfanuméricos.
# Os avisos nativos do lote têm ~1.000–1.500; o escaneado tem 0. Limiar deliberadamente baixo:
# o objetivo é separar "tem texto" de "não tem", não julgar qualidade (limitação: H-03).
MIN_ALNUM_CHARS_PER_PAGE = 100


@dataclass
class DocumentInput:
    path: Path
    file_name: str
    sha256: str
    size_bytes: int
    content: bytes


@dataclass
class TextLayer:
    usable: bool
    pages: int
    alnum_chars: int
    min_alnum_chars_per_page: int
    page_texts: list[str]          # texto cru por página (pypdf)
    normalized_text: str           # páginas unidas, espaços colapsados — base de toda evidência
    page_offsets: list[int]        # offset inicial de cada página em normalized_text
    reason: str | None             # ex.: NO_USABLE_TEXT_LAYER

    def page_of(self, offset: int) -> int:
        page = 1
        for i, start in enumerate(self.page_offsets):
            if offset >= start:
                page = i + 1
        return page


def normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ingest(path: Path) -> DocumentInput:
    content = path.read_bytes()
    return DocumentInput(path=path, file_name=path.name, sha256=hashlib.sha256(content).hexdigest(),
                         size_bytes=len(content), content=content)


def read_text_layer(doc: DocumentInput) -> TextLayer:
    if doc.path.suffix.lower() == ".txt":
        # Casos sintéticos do challenge set (E-003): texto puro, uma "página". Medem interpretação, não parsing de PDF.
        page_texts = [doc.content.decode("utf-8")]
    else:
        reader = pypdf.PdfReader(io.BytesIO(doc.content))
        page_texts = [page.extract_text() or "" for page in reader.pages]
    offsets, parts, cursor = [], [], 0
    for text in page_texts:
        norm = normalize_whitespace(text)
        offsets.append(cursor)
        parts.append(norm)
        cursor += len(norm) + 1
    normalized = " ".join(parts)
    alnum = sum(ch.isalnum() for ch in normalized)
    pages = len(page_texts)
    usable = pages > 0 and alnum >= MIN_ALNUM_CHARS_PER_PAGE * pages
    return TextLayer(usable=usable, pages=pages, alnum_chars=alnum, min_alnum_chars_per_page=MIN_ALNUM_CHARS_PER_PAGE,
                     page_texts=page_texts, normalized_text=normalized, page_offsets=offsets,
                     reason=None if usable else "NO_USABLE_TEXT_LAYER")
