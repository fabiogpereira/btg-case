"""Confiança categórica derivada apenas de sinais objetivos da extração (H-17).

Confiança do CAMPO = quão seguro estamos de que o valor corresponde ao que o documento diz.
Ela não diz se o registro é válido: isso é papel das validações e do roteamento (H-16).

Regras (nesta ordem):
  LOW    valores divergentes para o mesmo campo, ou campo presente num tipo de evento em que não se aplica
  HIGH   valor único, ancorado por rótulo ou frase do domínio
  HIGH   declaração de pendência ancorada por rótulo (a extração do "A definir" é bem-sucedida)
  HIGH   valor derivado de um campo HIGH (ex.: moeda a partir do símbolo do valor bruto)
  MEDIUM valor único, encontrado só por padrão sem âncora (ex.: razão social "... S.A.")
Corroboração (o mesmo valor em mais de um lugar) é registrada como motivo, mas não altera o nível.
"""
from .models import DECLARED_PENDING, FOUND, HIGH, LOW, MEDIUM, ExtractedField


def score_field(f: ExtractedField, derived_from: ExtractedField | None = None) -> ExtractedField:
    if f.status not in (FOUND, DECLARED_PENDING):
        f.confidence, f.confidence_reasons = None, []
        return f
    reasons = []
    if f.distinct_values > 1:
        level = LOW
        reasons.append(f"CONFLICTING_VALUES:{f.distinct_values}")
    elif any(n.startswith("UNEXPECTED_FOR_EVENT_TYPE") for n in f.notes):
        level = LOW
        reasons.append("UNEXPECTED_FOR_EVENT_TYPE")
    elif f.status == DECLARED_PENDING:
        level = HIGH
        reasons.append("PENDING_DECLARATION_LABEL_ANCHORED")
    elif f.anchor == "derived":
        level = derived_from.confidence if derived_from else MEDIUM
        reasons.append("DERIVED_FROM_SOURCE_FIELD")
    elif f.anchor in ("label", "phrase"):
        level = HIGH
        reasons.append(f"{f.anchor.upper()}_ANCHORED")
    else:
        level = MEDIUM
        reasons.append("UNANCHORED_PATTERN")
    if f.corroborations:
        reasons.append(f"CORROBORATED:{f.corroborations}")
    f.confidence, f.confidence_reasons = level, reasons
    return f


def score_all(fields: dict, specific: dict):
    for name, f in fields.items():
        if name != "currency":
            score_field(f)
    score_field(fields["currency"], derived_from=fields["gross_amount_per_share"])
    for f in specific.values():
        score_field(f)
