"""Base de referência (golden records): consulta determinística por chave exata.

Sem fuzzy match (D-008): identidade errada é o pior erro possível; não encontrado -> revisão.
A função `lookup_by_isin` tem formato de tool (entrada simples, saída estruturada) para
poder ser exposta ao LLM via function calling em experimentos futuros (D-002).
"""
import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GoldenRecords:
    path: Path
    sha256: str
    rows: list[dict]

    def lookup_by_isin(self, isin: str | None) -> dict:
        if not isin:
            return {"found": False, "matched_by": None, "row": None, "query": isin}
        key = isin.strip().upper()
        row = next((r for r in self.rows if r["isin"] == key), None)
        return {"found": row is not None, "matched_by": "isin" if row else None, "row": row, "query": key}


def load_golden_records(path: Path) -> GoldenRecords:
    content = path.read_bytes()
    text = content.decode("utf-8-sig")
    rows = [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(text.splitlines())]
    return GoldenRecords(path=path, sha256=hashlib.sha256(content).hexdigest(), rows=rows)
