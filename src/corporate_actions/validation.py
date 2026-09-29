"""Validation engine: regras determinísticas sobre o registro candidato normalizado.

Separado da extração. Cada regra recebe o registro e devolve um ValidationResult com
rule_id, status (PASS / FAIL / NOT_EVALUATED), severidade, valores observados e mensagem.

- Regra sem o dado de que depende -> NOT_EVALUATED (nunca FAIL).
- Regra que não se aplica ao tipo de evento -> não executada; listada em `rules_not_applicable`.
- Só severidade ERROR bloqueia aprovação automática (routing.py).
"""
import datetime as dt
import re
from dataclasses import dataclass
from decimal import Inexact, localcontext

from .models import (DECLARED_PENDING, ERROR, FAIL, FOUND, NOT_EVALUATED, NOT_FOUND, PASS, WARNING, Classification,
                     ExtractedField, ValidationResult)
from .numeric import STRICT_CONTEXT, compare_calculated_to_declared, net_from_gross
from .reference import GoldenRecords
from .schema import CASH_EVENTS, REQUIRED, SHARE_EVENTS


@dataclass
class CandidateRecord:
    classification: Classification
    fields: dict[str, ExtractedField]
    event_specific_fields: dict[str, ExtractedField]

    @property
    def event_type(self):
        return self.classification.event_type

    def value(self, name):
        f = self.fields.get(name) or self.event_specific_fields.get(name)
        return f.value if f is not None and f.status == FOUND else None

    def status(self, name):
        f = self.fields.get(name) or self.event_specific_fields.get(name)
        return f.status if f is not None else None


def _missing(rule_id, severity, *deps, **observed):
    return ValidationResult(rule_id, NOT_EVALUATED, severity, f"missing dependency: {', '.join(deps)}", observed)


def _result(rule_id, ok, severity, message, **observed):
    return ValidationResult(rule_id, PASS if ok else FAIL, severity, message, observed)


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


# --- Referência ---------------------------------------------------------------------------

def reference_rules(rec: CandidateRecord, ref: dict) -> list[ValidationResult]:
    isin = rec.value("isin")
    if not isin:
        deps = [_missing("REF_ISIN_FOUND", ERROR, "isin")]
        return deps + [_missing(r, ERROR, "reference_row") for r in
                       ("REF_TICKER_CONSISTENT", "REF_CNPJ_CONSISTENT", "REF_SHARE_CLASS_CONSISTENT", "REF_ISSUER_ACTIVE")] + \
            [_missing("REF_ISSUER_NAME_CONSISTENT", WARNING, "reference_row")]
    row = ref["row"]
    out = [_result("REF_ISIN_FOUND", ref["found"], ERROR,
                   "ISIN found in golden records" if ref["found"] else "ISIN not found in golden records (exact match)",
                   isin=isin)]
    if not row:
        out += [_missing(r, ERROR, "reference_row") for r in
                ("REF_TICKER_CONSISTENT", "REF_CNPJ_CONSISTENT", "REF_SHARE_CLASS_CONSISTENT", "REF_ISSUER_ACTIVE")]
        out.append(_missing("REF_ISSUER_NAME_CONSISTENT", WARNING, "reference_row"))
        return out

    def compare(rule_id, field, golden_key, severity=ERROR, normalize=lambda x: x):
        value = rec.value(field)
        if value is None:
            return _missing(rule_id, severity, field, golden=row[golden_key])
        ok = normalize(value) == normalize(row[golden_key])
        return _result(rule_id, ok, severity, f"{field} {'matches' if ok else 'differs from'} golden {golden_key}",
                       extracted=value, golden=row[golden_key])

    out.append(compare("REF_TICKER_CONSISTENT", "ticker", "ticker"))
    out.append(compare("REF_CNPJ_CONSISTENT", "cnpj", "cnpj"))
    out.append(compare("REF_ISSUER_NAME_CONSISTENT", "issuer_name", "emissor", WARNING, _norm_name))
    out.append(compare("REF_SHARE_CLASS_CONSISTENT", "share_class", "classe"))
    out.append(_result("REF_ISSUER_ACTIVE", row["status"] == "ativo", ERROR, f"golden status = {row['status']}",
                       golden_status=row["status"]))
    return out


# --- Completude e classificação -------------------------------------------------------------

def completeness_rules(rec: CandidateRecord) -> list[ValidationResult]:
    if rec.event_type is None:
        return [_missing("REQUIRED_FIELDS_PRESENT", ERROR, "event_type"),
                _missing("REQUIRED_FIELDS_NOT_PENDING", ERROR, "event_type")]
    required = REQUIRED[rec.event_type]
    missing = [f for f in required if rec.status(f) == NOT_FOUND]
    pending = [f for f in required if rec.status(f) == DECLARED_PENDING]
    return [
        _result("REQUIRED_FIELDS_PRESENT", not missing, ERROR,
                "all required fields present" if not missing else f"required fields not found: {missing}",
                required=required, not_found=missing),
        _result("REQUIRED_FIELDS_NOT_PENDING", not pending, ERROR,
                "no required field pending" if not pending else f"required fields declared pending: {pending}",
                declared_pending=pending),
    ]


def classification_rules(rec: CandidateRecord) -> list[ValidationResult]:
    c = rec.classification
    out = [_result("CLASSIFICATION_DETERMINED", c.event_type is not None, ERROR,
                   f"event type {c.event_type} by rule {c.decision_rule}", decision_rule=c.decision_rule)]
    if c.event_type is None:
        out.append(_missing("CLASSIFICATION_TITLE_CONSISTENT", ERROR, "event_type"))
    elif not c.title or not c.title_event_types:
        out.append(_missing("CLASSIFICATION_TITLE_CONSISTENT", ERROR, "title_event_type", title=c.title))
    else:
        ok = c.event_type in c.title_event_types
        out.append(_result("CLASSIFICATION_TITLE_CONSISTENT", ok, ERROR,
                           "title consistent with content" if ok else
                           f"title suggests {c.title_event_types} but content classifies as {c.event_type}",
                           title=c.title, title_event_types=c.title_event_types, content_event_type=c.event_type))
    return out


# --- Datas (dia útil = seg–sex, D-006) --------------------------------------------------------

def _next_weekday(day: dt.date) -> dt.date:
    nxt = day + dt.timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += dt.timedelta(days=1)
    return nxt


def date_rules(rec: CandidateRecord) -> list[ValidationResult]:
    approval, record, ex = rec.value("approval_date"), rec.value("record_date"), rec.value("ex_date")
    settlement_field = "share_credit_date" if rec.status("share_credit_date") is not None else "payment_date"
    settlement = rec.value(settlement_field)
    out = []
    if approval and record:
        out.append(_result("DATE_APPROVAL_NOT_AFTER_RECORD", approval <= record, ERROR,
                           f"approval {approval} vs record {record}", approval_date=approval, record_date=record))
    else:
        out.append(_missing("DATE_APPROVAL_NOT_AFTER_RECORD", ERROR, *[n for n, v in
                            (("approval_date", approval), ("record_date", record)) if not v]))
    if record and ex:
        out.append(_result("DATE_RECORD_BEFORE_EX", record < ex, ERROR, f"record {record} vs ex {ex}",
                           record_date=record, ex_date=ex))
        expected = _next_weekday(record)
        out.append(_result("DATE_EX_NEXT_WEEKDAY_AFTER_RECORD", ex == expected, WARNING,
                           f"ex {ex}; next weekday after record is {expected} (no holiday calendar, D-006)",
                           record_date=record, ex_date=ex, expected_ex_date=expected))
    else:
        deps = [n for n, v in (("record_date", record), ("ex_date", ex)) if not v]
        out.append(_missing("DATE_RECORD_BEFORE_EX", ERROR, *deps))
        out.append(_missing("DATE_EX_NEXT_WEEKDAY_AFTER_RECORD", WARNING, *deps))
    if settlement and ex:
        out.append(_result("DATE_SETTLEMENT_NOT_BEFORE_EX", settlement >= ex, ERROR,
                           f"{settlement_field} {settlement} vs ex {ex}", settlement_field=settlement_field,
                           settlement_date=settlement, ex_date=ex))
    else:
        deps = [n for n, v in ((settlement_field, settlement), ("ex_date", ex)) if not v]
        out.append(_missing("DATE_SETTLEMENT_NOT_BEFORE_EX", ERROR, *deps,
                            settlement_field_status=rec.status(settlement_field)))
    return out


# --- Valores (D-007) -------------------------------------------------------------------------

def amount_rules(rec: CandidateRecord) -> list[ValidationResult]:
    gross, net, tax = rec.value("gross_amount_per_share"), rec.value("net_amount_per_share"), rec.value("withholding_tax")
    out = []
    if gross is None:
        out.append(_missing("AMOUNT_GROSS_POSITIVE", ERROR, "gross_amount_per_share"))
    else:
        out.append(_result("AMOUNT_GROSS_POSITIVE", gross > 0, ERROR, f"gross = {gross}", gross=gross))
    deps = [n for n, v in (("gross_amount_per_share", gross), ("net_amount_per_share", net), ("withholding_tax", tax)) if v is None]
    if deps:
        out.append(_missing("AMOUNT_NET_MATCHES_GROSS_AND_TAX", ERROR, *deps,
                            net_status=rec.status("net_amount_per_share")))
    elif tax["base"] not in (None, "GROSS_AMOUNT"):
        out.append(ValidationResult("AMOUNT_NET_MATCHES_GROSS_AND_TAX", NOT_EVALUATED, ERROR,
                                    f"tax base {tax['base']} is not the gross amount", {"tax_base": tax["base"]}))
    else:
        try:
            calculated = net_from_gross(gross, tax["rate"])
        except Inexact:
            out.append(ValidationResult("AMOUNT_NET_MATCHES_GROSS_AND_TAX", NOT_EVALUATED, ERROR,
                                        "gross × (1 − rate) not exactly representable; no rounding rule defined",
                                        {"gross": gross, "rate": tax["rate"], "reason": "ROUNDING_RULE_UNDEFINED"}))
            return out
        cmp = compare_calculated_to_declared(calculated, net)
        msg = {"PASS": "net = gross × (1 − rate), exact",
               "FAIL": "net differs from gross × (1 − rate) beyond declared precision",
               "NOT_EVALUATED": "difference below declared precision; rounding rule undefined"}[cmp.status]
        if tax["base"] is None:
            msg += " (tax base not stated; applied to gross)"
        out.append(ValidationResult("AMOUNT_NET_MATCHES_GROSS_AND_TAX", cmp.status, ERROR, msg, {
            "gross": gross, "rate": tax["rate"], "declared_value": cmp.declared_value,
            "calculated_value": cmp.calculated_value, "comparison_precision": cmp.comparison_precision,
            "rounding_rule": cmp.rounding_rule, "reason": cmp.reason}))
    return out


def ratio_rules(rec: CandidateRecord) -> list[ValidationResult]:
    ratio = rec.value("ratio")
    if ratio is None:
        out = [_missing("RATIO_POSITIVE", ERROR, "ratio")]
        if rec.event_type == "BONUS_SHARES":
            out.append(_missing("RATIO_PERCENTAGE_CONSISTENT", ERROR, "ratio"))
        return out
    out = [_result("RATIO_POSITIVE", all(v > 0 for v in ratio.values()), ERROR, f"ratio = {ratio}", ratio=ratio)]
    if rec.event_type == "BONUS_SHARES":
        if "percentage" not in ratio:
            out.append(_missing("RATIO_PERCENTAGE_CONSISTENT", ERROR, "ratio.percentage"))
        else:
            with localcontext(STRICT_CONTEXT):   # multiplicação cruzada: sem divisão, sem arredondamento
                ok = ratio["bonus_shares"] == ratio["percentage"] * ratio["shares_held"]
            out.append(_result("RATIO_PERCENTAGE_CONSISTENT", ok, ERROR,
                               "bonus_shares = percentage × shares_held" if ok else "stated percentage inconsistent with ratio",
                               ratio=ratio))
    return out


# --- Orquestração das regras -----------------------------------------------------------------

RULE_GROUPS = [
    ("reference", None),
    ("completeness", None),
    ("classification", None),
    ("dates", None),
    ("amounts", CASH_EVENTS),
    ("ratio", SHARE_EVENTS),
]


def validate(rec: CandidateRecord, golden: GoldenRecords):
    """Executa todas as regras obrigatórias. Retorna (resultados, grupos não aplicáveis, resultado do lookup)."""
    ref = golden.lookup_by_isin(rec.value("isin"))
    results, not_applicable = [], []
    for group, applies_to in RULE_GROUPS:
        if applies_to is not None and rec.event_type is not None and rec.event_type not in applies_to:
            not_applicable.append(group)
            continue
        if group == "reference":
            results += reference_rules(rec, ref)
        elif group == "completeness":
            results += completeness_rules(rec)
        elif group == "classification":
            results += classification_rules(rec)
        elif group == "dates":
            results += date_rules(rec)
        elif group == "amounts":
            results += amount_rules(rec)
        elif group == "ratio":
            results += ratio_rules(rec)
    return results, not_applicable, ref
