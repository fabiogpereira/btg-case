"""Identidade do ativo por política hierárquica (E-007, variante G). Precisão antes de cobertura.

Nível 1 — `ISIN_EXACT`: ISIN extraído com correspondência exata e única na base. ISIN presente é autoritativo:
          ISIN presente e ausente da base NÃO cai para o nível 2 (REFERENCE_NOT_FOUND, revisão).
Nível 2 — só quando o documento não traz ISIN: ticker exato, com linha única na base, E identidade do emissor exata
          na MESMA linha:
          - `TICKER_AND_CNPJ_EXACT`: CNPJ extraído == CNPJ da linha (preferido);
          - `TICKER_AND_ISSUER_EXACT`: sem CNPJ no documento, razão social normalizada pelo pipeline == `emissor`
            (igualdade exata após espaços/caixa; sem fuzzy).
Qualquer outro caso -> `UNRESOLVED` (bloqueia): identificadores insuficientes, ticker sozinho, ticker fora da base,
mais de uma linha candidata, ticker de outro emissor (conflito), identificador com valores divergentes no documento,
razão social não resolvida pelo pipeline. O LLM nunca entra na decisão de identidade.

Nada aqui altera o validation engine: `apply_identity` pós-processa os resultados de `validate()` (as regras de
consistência são reavaliadas contra a linha casada no nível 2) e `gate_identity` recompõe o gate REFERENCE_VALIDATION
com as regras de identidade, porque `route_gated` só conhece as regras de referência baseadas em ISIN.
"""
import re

from .confidence_model import _decide
from .models import ERROR, FAIL, FOUND, LOW, NOT_EVALUATED, PASS, WARNING, ValidationResult

ISIN_EXACT, TICKER_AND_CNPJ_EXACT, TICKER_AND_ISSUER_EXACT, UNRESOLVED = (
    "ISIN_EXACT", "TICKER_AND_CNPJ_EXACT", "TICKER_AND_ISSUER_EXACT", "UNRESOLVED")
CONSISTENCY_RULES = ("REF_TICKER_CONSISTENT", "REF_CNPJ_CONSISTENT", "REF_ISSUER_NAME_CONSISTENT",
                     "REF_SHARE_CLASS_CONSISTENT", "REF_ISSUER_ACTIVE")


def _norm_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().casefold()


def _usable(rec, name):
    """Valor de identificador utilizável: encontrado, sem valores divergentes no documento e sem confiança LOW."""
    f = rec.fields.get(name)
    if f is None or f.status != FOUND:
        return None, None
    if f.distinct_values > 1 or f.confidence == LOW:
        return None, f"{name.upper()}_NOT_UNIQUE_IN_DOCUMENT"
    return f.value, None


def resolve_identity(rec, golden) -> dict:
    isin, isin_problem = _usable(rec, "isin")
    ticker, ticker_problem = _usable(rec, "ticker")
    cnpj, cnpj_problem = _usable(rec, "cnpj")
    issuer, issuer_problem = _usable(rec, "issuer_name")
    out = {"identity_method": UNRESOLVED, "identifiers_used": {}, "matched_reference": None,
           "status": "UNRESOLVED", "reason_code": None, "conflicts": []}

    def done(method=None, row=None, used=None, reason=None, conflicts=()):
        out.update(identifiers_used=used or {}, conflicts=list(conflicts), reason_code=reason)
        if method and row:
            out.update(identity_method=method, status="RESOLVED", matched_reference=row)
        return out

    if isin_problem:
        return done(reason="IDENTITY_CONFLICT", conflicts=[isin_problem])
    if isin:
        rows = [r for r in golden.rows if r["isin"] == isin.strip().upper()]
        if len(rows) == 1:
            return done(ISIN_EXACT, rows[0], {"isin": isin})
        return done(used={"isin": isin}, reason="AMBIGUOUS_REFERENCE" if rows else "REFERENCE_NOT_FOUND")
    if ticker_problem:
        return done(reason="IDENTITY_CONFLICT", conflicts=[ticker_problem])
    if not ticker:
        return done(reason="IDENTITY_INSUFFICIENT_IDENTIFIERS")
    rows = [r for r in golden.rows if r["ticker"] == ticker]
    if not rows:
        return done(used={"ticker": ticker}, reason="REFERENCE_NOT_FOUND")
    if len(rows) > 1:
        return done(used={"ticker": ticker}, reason="AMBIGUOUS_REFERENCE", conflicts=["MULTIPLE_REFERENCE_ROWS_FOR_TICKER"])
    row = rows[0]
    if cnpj_problem:
        return done(used={"ticker": ticker}, reason="IDENTITY_CONFLICT", conflicts=[cnpj_problem])
    if cnpj:
        if cnpj == row["cnpj"]:
            return done(TICKER_AND_CNPJ_EXACT, row, {"ticker": ticker, "cnpj": cnpj})
        return done(used={"ticker": ticker, "cnpj": cnpj}, reason="IDENTITY_CONFLICT",
                    conflicts=["TICKER_BELONGS_TO_DIFFERENT_CNPJ"])
    if issuer_problem:
        return done(used={"ticker": ticker}, reason="IDENTITY_CONFLICT", conflicts=[issuer_problem])
    if issuer:
        if _norm_name(issuer) == _norm_name(row["emissor"]):
            return done(TICKER_AND_ISSUER_EXACT, row, {"ticker": ticker, "issuer_name": issuer})
        return done(used={"ticker": ticker, "issuer_name": issuer}, reason="IDENTITY_CONFLICT",
                    conflicts=["TICKER_BELONGS_TO_DIFFERENT_ISSUER"])
    return done(used={"ticker": ticker}, reason="IDENTITY_INSUFFICIENT_IDENTIFIERS")


def _consistency(rec, row) -> list[ValidationResult]:
    """Mesmas regras de consistência do validation engine, contra a linha casada no nível 2."""
    def compare(rule_id, field, key, severity=ERROR, normalize=lambda x: x):
        value = rec.value(field)
        if value is None:
            return ValidationResult(rule_id, NOT_EVALUATED, severity, f"missing dependency: {field}", {"golden": row[key]})
        ok = normalize(value) == normalize(row[key])
        return ValidationResult(rule_id, PASS if ok else FAIL, severity,
                                f"{field} {'matches' if ok else 'differs from'} golden {key}",
                                {"extracted": value, "golden": row[key]})
    return [compare("REF_TICKER_CONSISTENT", "ticker", "ticker"), compare("REF_CNPJ_CONSISTENT", "cnpj", "cnpj"),
            compare("REF_ISSUER_NAME_CONSISTENT", "issuer_name", "emissor", WARNING, _norm_name),
            compare("REF_SHARE_CLASS_CONSISTENT", "share_class", "classe"),
            ValidationResult("REF_ISSUER_ACTIVE", PASS if row["status"] == "ativo" else FAIL, ERROR,
                             f"golden status = {row['status']}", {"golden_status": row["status"]})]


def apply_identity(validations: list, identity: dict, rec) -> list:
    """Resultados da G: regra REF_IDENTITY_RESOLVED; no nível 2, consistência contra a linha casada e dispensa
    do ISIN como campo obrigatório (a identidade exigida foi provada por outros identificadores exatos)."""
    level2 = identity["identity_method"] in (TICKER_AND_CNPJ_EXACT, TICKER_AND_ISSUER_EXACT)
    out = []
    for v in validations:
        if level2 and v.rule_id in CONSISTENCY_RULES:
            continue
        if level2 and v.rule_id == "REQUIRED_FIELDS_PRESENT" and "isin" in v.observed.get("not_found", []):
            missing = [f for f in v.observed["not_found"] if f != "isin"]
            v = ValidationResult(v.rule_id, FAIL if missing else PASS, v.severity,
                                 f"required fields not found: {missing}" if missing else
                                 f"all required fields present (isin waived: identity {identity['identity_method']})",
                                 {**v.observed, "not_found": missing, "isin_waived_by": identity["identity_method"]})
        out.append(v)
    resolved = identity["status"] == "RESOLVED"
    out.append(ValidationResult("REF_IDENTITY_RESOLVED", PASS if resolved else FAIL, ERROR,
                                f"identity {identity['identity_method']}" if resolved else
                                f"identity unresolved: {identity['reason_code']} {identity['conflicts']}",
                                {"identity_method": identity["identity_method"],
                                 "identifiers_used": identity["identifiers_used"],
                                 "reason_code": identity["reason_code"], "conflicts": identity["conflicts"]}))
    if level2:
        out += _consistency(rec, identity["matched_reference"])
    return out


def gate_identity(routing: dict, validations: list) -> dict:
    """Recompõe o gate REFERENCE_VALIDATION incluindo a regra de identidade (bloqueante)."""
    ident = next(v for v in validations if v.rule_id == "REF_IDENTITY_RESOLVED")
    if ident.status != FAIL:
        return routing
    code = ident.observed["reason_code"] or "IDENTITY_UNRESOLVED"
    gates = [dict(g) for g in routing["gates"]]
    for g in gates:
        if g["gate"] == "REFERENCE_VALIDATION":
            g["reason_codes"] = sorted(set(g["reason_codes"]) | {code})
            g["explanations"] = g["explanations"] + [f"REF_IDENTITY_RESOLVED: {ident.message}"]
            g["status"] = "BLOCK"
    return _decide(gates)
