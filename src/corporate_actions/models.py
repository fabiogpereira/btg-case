"""Estruturas de dados do pipeline e serialização para JSON."""
import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

from .numeric import to_plain_string

# Status de campo (CLAUDE.md §3.5)
FOUND = "found"
NOT_FOUND = "not_found"
NOT_APPLICABLE = "not_applicable"
DECLARED_PENDING = "declared_pending"

# Status de regra
PASS, FAIL, NOT_EVALUATED = "PASS", "FAIL", "NOT_EVALUATED"

# Severidade de regra: só ERROR bloqueia aprovação automática
ERROR, WARNING = "ERROR", "WARNING"

# Tipos de evento
DIVIDEND, JCP, BONUS_SHARES, REVERSE_SPLIT, SPLIT = "DIVIDEND", "JCP", "BONUS_SHARES", "REVERSE_SPLIT", "SPLIT"

# Confiança categórica (H-17)
HIGH, MEDIUM, LOW = "HIGH", "MEDIUM", "LOW"


@dataclass
class Evidence:
    text: str        # trecho literal (espaços normalizados)
    start: int       # offset no texto normalizado do documento
    end: int
    page: int


@dataclass
class Candidate:
    """Uma ocorrência bruta de um campo encontrada por uma regra de extração."""
    raw: str
    evidence: Evidence
    rule_id: str                   # qual regra do extrator encontrou (auditoria / medida de sobreajuste)
    anchor: str                    # "label" | "phrase" | "pattern"
    source_label: str | None = None
    pending: bool = False          # a fonte declara o valor como pendente
    attributes: dict = field(default_factory=dict)


@dataclass
class ExtractedField:
    status: str
    value: object = None
    raw: str | None = None
    source_label: str | None = None
    evidence: list[Evidence] = field(default_factory=list)
    extraction_rules: list[str] = field(default_factory=list)
    anchor: str | None = None
    distinct_values: int = 0
    alternatives: list = field(default_factory=list)   # outros valores encontrados (conflito)
    corroborations: int = 0
    notes: list[str] = field(default_factory=list)
    confidence: str | None = None
    confidence_reasons: list[str] = field(default_factory=list)


@dataclass
class Classification:
    event_type: str | None
    decision_rule: str             # single_type | precedence:<...> | ambiguous | no_signals
    signals: dict                  # tipo -> lista de Evidence
    title: str | None
    title_event_types: list[str]
    confidence: str | None = None
    confidence_reasons: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    rule_id: str
    status: str
    severity: str
    message: str
    observed: dict = field(default_factory=dict)


def to_jsonable(obj):
    """Serialização: Decimal -> string sem perder casas; date -> ISO; dataclass -> dict."""
    if isinstance(obj, Decimal):
        return to_plain_string(obj)
    if isinstance(obj, (dt.date, dt.datetime)):
        return obj.isoformat()
    if dataclasses.is_dataclass(obj):
        return {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, float):
        raise TypeError("float não é permitido em valores do pipeline (D-007)")
    return obj
