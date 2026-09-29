"""Normalização e resolução: candidatos brutos -> um campo por nome, com status explícito.

- Nunca completa valor ausente: sem candidato -> `not_found` (ou `not_applicable` pelo tipo).
- Nunca escolhe em silêncio entre valores divergentes: guarda as alternativas e conta
  `distinct_values` (a confiança cai para LOW em confidence.py).
- Preserva o rótulo original (`source_label`) e o texto cru (`raw`) ao lado do valor (D-010).
"""
import datetime as dt
import re
from decimal import Decimal

from .extraction import DATE_NUM, ExtractionResult
from .models import (BONUS_SHARES, DECLARED_PENDING, FOUND, NOT_APPLICABLE, NOT_FOUND, REVERSE_SPLIT, SPLIT,
                     Candidate, ExtractedField)
from .numeric import parse_br_decimal, parse_br_percent
from .schema import COMMON_FIELDS, EVENT_SPECIFIC_FIELDS, is_applicable

MONTHS = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7,
          "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
ANCHOR_RANK = {"label": 0, "phrase": 1, "pattern": 2, "derived": 3}


def parse_date(raw: str) -> dt.date:
    raw = raw.strip()
    if re.fullmatch(DATE_NUM, raw):
        day, month, year = raw.split("/")
        return dt.date(int(year), int(month), int(day))
    m = re.fullmatch(r"(\d{1,2})º?\s+de\s+(\w+)\s+de\s+(\d{4})", raw)
    if m and m.group(2).lower() in MONTHS:
        return dt.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
    raise ValueError(f"unparseable date: {raw!r}")


def _normalize(name: str, cand: Candidate, event_type: str | None):
    """Retorna o valor normalizado de um candidato; ValueError se não for interpretável."""
    raw = cand.raw
    if name in ("record_date", "ex_date", "payment_date", "approval_date", "share_credit_date"):
        return parse_date(raw)
    if name in ("gross_amount_per_share", "net_amount_per_share"):
        return parse_br_decimal(raw)
    if name == "tax_cost_per_share":
        return {"amount": parse_br_decimal(raw), "currency": "BRL"}
    if name == "withholding_tax":
        return {"rate": parse_br_percent(raw), "base": cand.attributes.get("base")}
    if name in ("isin", "ticker", "share_class", "cnpj"):
        return raw.strip().upper() if name != "cnpj" else raw.strip()
    if name == "issuer_name":
        return re.sub(r"\s+", " ", raw).strip()
    if name == "ratio":
        return _normalize_ratio(cand, event_type)
    raise ValueError(f"no normalizer for {name}")


def _normalize_ratio(cand: Candidate, event_type: str | None):
    a = cand.attributes
    form = a.get("form")
    if event_type in (REVERSE_SPLIT, SPLIT) and form in ("label_proporcao_colon", "phrase_existing_to_new"):
        return {"shares_before": Decimal(a["a"]), "shares_after": Decimal(a["b"])}
    if event_type == BONUS_SHARES and form == "phrase_bonus_new_per_held":
        value = {"shares_held": Decimal(a["held"]), "bonus_shares": Decimal(a["new"])}
        if a.get("pct"):
            value["percentage"] = parse_br_percent(a["pct"])
        return value
    raise ValueError(f"ratio form {form!r} not interpretable for event type {event_type!r}")


def _group_key(name: str, value):
    if name == "withholding_tax":
        return ("rate", value["rate"])
    if name == "ratio":
        return tuple(sorted((k, v) for k, v in value.items() if k != "percentage"))
    if name == "issuer_name":
        return value.casefold()
    if isinstance(value, dict):
        return tuple(sorted(value.items()))
    return value


def _merge_group(name: str, items):
    """Valor representativo de um grupo de candidatos equivalentes."""
    values = [v for _, v in items]
    if name == "withholding_tax":
        base = next((v["base"] for v in values if v["base"]), None)
        return {"rate": values[0]["rate"], "base": base}
    if name == "ratio":
        merged = dict(values[0])
        pct = next((v["percentage"] for v in values if "percentage" in v), None)
        if pct is not None:
            merged["percentage"] = pct
        return merged
    if name == "issuer_name":
        return next((v for v in values if any(ch.islower() for ch in v)), values[0])  # prefere a grafia mista
    return values[0]


def _date_corroborations(value: dt.date, evidence_spans, extraction: ExtractionResult) -> int:
    count = 0
    for mention in extraction.date_mentions:
        if any(mention.evidence.start < end and mention.evidence.end > start for start, end in evidence_spans):
            continue
        try:
            if parse_date(mention.raw) == value:
                count += 1
        except ValueError:
            pass
    return count


def resolve_field(name: str, extraction: ExtractionResult, event_type: str | None) -> ExtractedField:
    cands = sorted(extraction.candidates.get(name, []), key=lambda c: (ANCHOR_RANK[c.anchor], c.evidence.start))
    notes, valued, pending = [], [], [c for c in cands if c.pending]
    for c in cands:
        if c.pending:
            continue
        try:
            valued.append((c, _normalize(name, c, event_type)))
        except ValueError as exc:
            notes.append(f"NORMALIZATION_FAILED[{c.rule_id}]: {exc}")

    if not valued and not pending:
        status = NOT_FOUND if is_applicable(name, event_type) else NOT_APPLICABLE
        return ExtractedField(status=status, notes=notes)

    if not valued:  # só declaração de pendência
        best = pending[0]
        return ExtractedField(status=DECLARED_PENDING, raw=best.raw, source_label=best.source_label,
                              evidence=[c.evidence for c in pending], extraction_rules=sorted({c.rule_id for c in pending}),
                              anchor=best.anchor, distinct_values=1, notes=notes)

    groups: dict = {}
    for c, v in valued:
        groups.setdefault(_group_key(name, v), []).append((c, v))
    ordered = list(groups.values())            # ordem de inserção = melhor âncora primeiro
    chosen = ordered[0]
    best = chosen[0][0]
    value = _merge_group(name, chosen)
    distinct = len(ordered) + (1 if pending else 0)   # valor + declaração de pendência também é conflito
    alternatives = [{"value": _merge_group(name, g), "evidence": [c.evidence for c, _ in g]} for g in ordered[1:]]
    if pending:
        alternatives.append({"value": None, "declared_pending": True, "evidence": [c.evidence for c in pending]})
    if not is_applicable(name, event_type):
        notes.append(f"UNEXPECTED_FOR_EVENT_TYPE:{event_type}")
    evidence = [c.evidence for c, _ in chosen]
    corroborations = len(chosen) - 1
    if isinstance(value, dt.date):
        corroborations += _date_corroborations(value, [(e.start, e.end) for e in evidence], extraction)
    return ExtractedField(status=FOUND, value=value, raw=best.raw,
                          source_label=next((c.source_label for c, _ in chosen if c.source_label), None),
                          evidence=evidence, extraction_rules=sorted({c.rule_id for c, _ in chosen}),
                          anchor=best.anchor, distinct_values=distinct, alternatives=alternatives,
                          corroborations=corroborations, notes=notes)


def derive_currency(gross: ExtractedField, event_type: str | None) -> ExtractedField:
    """Moeda do evento em dinheiro = símbolo que acompanha o valor bruto. Não é inventada."""
    if gross.status == FOUND and gross.evidence and "R$" in gross.evidence[0].text:
        return ExtractedField(status=FOUND, value="BRL", raw="R$", evidence=[gross.evidence[0]],
                              extraction_rules=["currency.derived_from_gross_symbol"], anchor="derived",
                              distinct_values=1, notes=["derived from gross_amount_per_share evidence"])
    return ExtractedField(status=NOT_FOUND if is_applicable("currency", event_type) else NOT_APPLICABLE)


def resolve_all(extraction: ExtractionResult, event_type: str | None):
    fields = {name: resolve_field(name, extraction, event_type) for name in COMMON_FIELDS if name != "currency"}
    fields["currency"] = derive_currency(fields["gross_amount_per_share"], event_type)
    fields = {name: fields[name] for name in COMMON_FIELDS}
    specific = {}
    for name in EVENT_SPECIFIC_FIELDS.get(event_type, []):
        if name in extraction.unsupported_fields:
            continue   # não suportado pelo extrator: listado em extraction.unsupported_fields, não "not_found"
        specific[name] = resolve_field(name, extraction, event_type)
    return fields, specific
