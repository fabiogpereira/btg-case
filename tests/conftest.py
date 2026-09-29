import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from corporate_actions.models import (DECLARED_PENDING, FOUND, HIGH, NOT_APPLICABLE, NOT_FOUND, Classification,
                                      ExtractedField)
from corporate_actions.reference import load_golden_records
from corporate_actions.schema import COMMON_FIELDS
from corporate_actions.validation import CandidateRecord

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "case" / "Case AI Dev - Envio"
DOCS = CASE / "documents"
GOLDEN = CASE / "golden_records" / "golden records.csv"


@pytest.fixture(scope="session")
def golden():
    return load_golden_records(GOLDEN)


def found(value):
    return ExtractedField(status=FOUND, value=value, confidence=HIGH, anchor="label", distinct_values=1)


def make_record(event_type="JCP", title_types=None, **overrides) -> CandidateRecord:
    """Registro candidato sintético, válido por padrão (espelha o doc 02). Overrides: nome=valor | ExtractedField."""
    base = {
        "issuer_name": found("Banco Meridional do Brasil S.A."), "cnpj": found("60.111.222/0001-55"),
        "isin": found("BRBMRDACNPR7"), "ticker": found("BMRD4"), "share_class": found("PN"),
        "approval_date": found(dt.date(2026, 6, 2)), "record_date": found(dt.date(2026, 6, 16)),
        "ex_date": found(dt.date(2026, 6, 17)), "payment_date": found(dt.date(2026, 8, 14)),
        "gross_amount_per_share": found(Decimal("0.1738420000")),
        "net_amount_per_share": found(Decimal("0.1434196500")),
        "withholding_tax": found({"rate": Decimal("0.175"), "base": "GROSS_AMOUNT"}),
        "currency": found("BRL"), "ratio": ExtractedField(status=NOT_APPLICABLE),
    }
    specific = {}
    for name, value in overrides.items():
        target = base if name in COMMON_FIELDS else specific
        target[name] = value if isinstance(value, ExtractedField) else found(value)
    title_types = [event_type] if title_types is None else title_types
    cls = Classification(event_type, "single_type", {}, "título", title_types, HIGH, [])
    return CandidateRecord(cls, base, specific)


PENDING = ExtractedField(status=DECLARED_PENDING, raw="A definir", confidence=HIGH, anchor="label", distinct_values=1)
MISSING = ExtractedField(status=NOT_FOUND)
NA = ExtractedField(status=NOT_APPLICABLE)
