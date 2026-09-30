"""Blind set v2 (BT-002) congelado antes de qualquer processamento pela variante F: bytes exatos (SHA-256)."""
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((ROOT / "tests" / "blind_set_v2" / "MANIFEST.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", sorted(MANIFEST["files"]))
def test_blind_v2_file_unchanged(path):
    assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == MANIFEST["files"][path], f"{path} mudou após o freeze"


def test_documents_folder_holds_only_documents():
    docs = ROOT / "tests" / "blind_set_v2" / "documents"
    assert sorted(p.suffix for p in docs.iterdir()) == [".txt"] * MANIFEST["cases"]
