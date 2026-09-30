"""Política de incerteza crítica da percepção (E-010, variante J).

Quando a camada de percepção (hoje: vision) declara trechos incertos, a pipeline não os ignora. Para cada campo:
- `vision_uncertain`: algum token incerto (com conteúdo alfanumérico) sobrepõe, no texto normalizado, o VALOR do campo
  (não o rótulo; pontilhado e preenchimento sem letras/dígitos são ignorados);
- `critical_field`: identificadores do ativo, tipo de evento, datas materiais, valores, tributação, proporção e todo
  campo obrigatório do tipo de evento. Texto irrelevante (assinatura, NIRE, contexto) não é crítico;
- campo crítico incerto só segue se houver corroboração determinística INDEPENDENTE que confirme exatamente o valor:
  1. identificadores (ISIN, ticker, CNPJ, razão social, classe): linha única da base de referência encontrada por OUTRO
     identificador, que não seja incerto e não seja o próprio campo, e cujo valor coincide exatamente com o do campo.
     No ISIN incerto, a linha encontrada pelo próprio ISIN só conta se outro identificador não incerto coincidir com
     ela (uma leitura errada pode cair em outra linha válida da base; a existência na base, sozinha, não prova a leitura);
  2. valor bruto, valor líquido ou alíquota: a relação bruto × (1 − alíquota) = líquido, avaliada como PASS exato pela
     validação, quando EXATAMENTE UM dos três é incerto — os outros dois, lidos com segurança, determinam o terceiro.
     Limitação: os três vêm da mesma leitura; a relação só corrobora supondo erros independentes em tokens diferentes,
     e nada prova quando dois ou três são incertos;
  3. datas, proporção e tipo de evento: não há fonte determinística independente (regras de ordem de datas não fixam
     o valor; "ex = próximo dia útil" é expectativa de negócio, não identidade) -> não corroborados.
- nunca vale como corroboração: a confiança da própria percepção, a normalização do próprio valor, ou uma linha da base
  encontrada usando o próprio campo incerto (circular).
Resultado por campo: `corroboration_status` EXACT_MATCH | CONFLICT | NO_INDEPENDENT_SOURCE; bloqueio
`CRITICAL_FIELD_UNCERTAIN_UNCORROBORATED` ou `CRITICAL_FIELD_UNCERTAIN_CONFLICT`. Token incerto com dígitos ou forma de
identificador que não pode ser localizado no texto -> `UNCERTAIN_TOKEN_UNLOCATED` (bloqueia; não há como saber a que
campo pertence).
O gate `PERCEPTION_UNCERTAINTY` é acrescentado ao roteamento e recomposto com `_decide`, como o gate de identidade.
"""
import re

from .confidence_model import _decide
from .schema import REQUIRED

IDENTIFIERS = {"isin": "isin", "ticker": "ticker", "cnpj": "cnpj", "issuer_name": "emissor", "share_class": "classe"}
MATERIAL = {"record_date", "ex_date", "payment_date", "share_credit_date", "gross_amount_per_share",
            "net_amount_per_share", "withholding_tax", "tax_treatment", "ratio"}
AMOUNTS = ("gross_amount_per_share", "net_amount_per_share", "withholding_tax")
UNCORROBORATED, CONFLICT = "CRITICAL_FIELD_UNCERTAIN_UNCORROBORATED", "CRITICAL_FIELD_UNCERTAIN_CONFLICT"
UNLOCATED = "UNCERTAIN_TOKEN_UNLOCATED"


def _norm_name(s):
    return re.sub(r"\s+", " ", s or "").strip().casefold()


def critical_fields(event_type) -> set[str]:
    return set(IDENTIFIERS) | MATERIAL | set(REQUIRED.get(event_type, []))


def _value_spans(field) -> list[tuple[int, int]]:
    out = []
    for ev in field.evidence or []:
        raw = field.raw or ""
        i = ev.text.rfind(raw) if raw else -1
        out.append((ev.start + i, ev.start + i + len(raw)) if i >= 0 else (ev.start, ev.end))
    return out


def _locate(token, text) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in re.finditer(re.escape(token), text)]


def _row_via(golden, key, value):
    rows = [r for r in golden.rows if (_norm_name(r[key]) if key == "emissor" else r[key]) == value]
    return rows[0] if len(rows) == 1 else None


def _corroborate_identifier(name, fields, uncertain, golden):
    """Linha única da base encontrada por outro identificador não incerto; compara o valor exato do campo."""
    value = fields[name].value
    for src in ("isin", "ticker", "cnpj"):
        if src == name or src in uncertain:
            continue
        f = fields.get(src)
        if f is None or f.status != "found":
            continue
        row = _row_via(golden, IDENTIFIERS[src], f.value)
        if row is None:
            continue
        expected = row[IDENTIFIERS[name]]
        ok = _norm_name(value) == _norm_name(expected) if name == "issuer_name" else value == expected
        return ("EXACT_MATCH" if ok else "CONFLICT", f"golden_records row via {src}={f.value}", expected)
    if name == "isin":                        # linha pelo próprio ISIN só vale se outro identificador a confirmar
        row = _row_via(golden, "isin", value)
        if row is not None:
            for src in ("ticker", "cnpj"):
                f = fields.get(src)
                if src not in uncertain and f is not None and f.status == "found":
                    ok = f.value == row[IDENTIFIERS[src]]
                    return ("EXACT_MATCH" if ok else "CONFLICT",
                            f"golden_records row via isin, cross-checked with {src}={f.value}", row[IDENTIFIERS[src]])
    return ("NO_INDEPENDENT_SOURCE", None, None)


def _corroborate_amount(name, uncertain, validations):
    rule = next((v for v in validations if v.rule_id == "AMOUNT_NET_MATCHES_GROSS_AND_TAX"), None)
    if sum(a in uncertain for a in AMOUNTS) == 1 and rule is not None and rule.status == "PASS":
        others = [a for a in AMOUNTS if a != name]
        return ("EXACT_MATCH", f"arithmetic gross x (1 - tax) = net (PASS) with {' and '.join(others)} read without uncertainty", None)
    return ("NO_INDEPENDENT_SOURCE", None, None)


def assess(fallback_audit, fields, specific, classification, validations, golden, text) -> dict | None:
    if not fallback_audit or "uncertain_tokens" not in fallback_audit:
        return None
    tokens = [t for t in fallback_audit["uncertain_tokens"] if re.search(r"[\wÀ-ÿ]", t["token"])]
    ignored = [t for t in fallback_audit["uncertain_tokens"] if t not in tokens]
    located = {t["token"]: _locate(t["token"], text) for t in tokens}
    all_fields = {**fields, **specific}
    critical = critical_fields(classification.event_type)
    uncertain = {}
    for name, f in all_fields.items():
        if f.status != "found":
            continue
        spans = _value_spans(f)
        hits = [t["token"] for t in tokens if any(s < e2 and s2 < e for s, e in spans for s2, e2 in located[t["token"]])]
        if hits:
            uncertain[name] = hits
    signal_spans = [(s["evidence"].start, s["evidence"].end) for sigs in (classification.signals or {}).values() for s in sigs]
    cls_hits = [t["token"] for t in tokens if any(s < e2 and s2 < e for s, e in signal_spans for s2, e2 in located[t["token"]])]
    rows, blocking = {}, []
    for name, f in all_fields.items():
        if f.status != "found":
            continue
        is_uncertain, is_critical = name in uncertain, name in critical
        entry = {"vision_uncertain": is_uncertain, "uncertain_tokens": uncertain.get(name, []), "critical_field": is_critical,
                 "corroboration_attempted": is_uncertain and is_critical, "corroboration_source": None,
                 "corroboration_status": None, "reference_value": None, "blocking_reason": None}
        if is_uncertain and is_critical:
            if name in IDENTIFIERS:
                status, source, ref = _corroborate_identifier(name, all_fields, uncertain, golden)
            elif name in AMOUNTS:
                status, source, ref = _corroborate_amount(name, uncertain, validations)
            elif name == "tax_treatment" and (f.value or {}).get("kind") == "WITHHOLDING_AT_RATE":
                status, source, ref = _corroborate_amount("withholding_tax", uncertain, validations)   # mesma alíquota lida
            else:
                status, source, ref = "NO_INDEPENDENT_SOURCE", None, None
            entry.update(corroboration_status=status, corroboration_source=source, reference_value=ref)
            if status != "EXACT_MATCH":
                entry["blocking_reason"] = CONFLICT if status == "CONFLICT" else UNCORROBORATED
                blocking.append((entry["blocking_reason"], f"{name}: uncertain {entry['uncertain_tokens']} -> {status}"))
        rows[name] = entry
    event = {"vision_uncertain": bool(cls_hits), "uncertain_tokens": cls_hits, "critical_field": True,
             "corroboration_attempted": bool(cls_hits), "corroboration_source": None,
             "corroboration_status": "NO_INDEPENDENT_SOURCE" if cls_hits else None,
             "blocking_reason": UNCORROBORATED if cls_hits else None}
    if cls_hits:
        blocking.append((UNCORROBORATED, f"event_type: uncertain {cls_hits} -> NO_INDEPENDENT_SOURCE"))
    unlocated = [t for t in tokens if not located[t["token"]]
                 and (re.search(r"\d", t["token"]) or re.fullmatch(r"[A-Z0-9./()-]{4,}", t["token"]))]
    for t in unlocated:
        blocking.append((UNLOCATED, f"uncertain token {t['token']!r} not found in the text"))
    mapped = {tok for v in uncertain.values() for tok in v} | set(cls_hits)
    return {"policy": "critical-uncertainty/1.0", "fields": rows, "event_type": event,
            "non_critical_uncertain_tokens": [t for t in tokens if t["token"] not in mapped and t not in unlocated],
            "unlocated_uncertain_tokens": unlocated, "ignored_non_alphanumeric_tokens": ignored, "blocking": blocking}


def gate_uncertainty(routing: dict, assessment: dict | None) -> dict:
    if assessment is None:
        return routing
    blocks = assessment["blocking"]
    gates = [dict(g) for g in routing["gates"]] + [{
        "gate": "PERCEPTION_UNCERTAINTY", "status": "BLOCK" if blocks else "PASS",
        "reason_codes": sorted({c for c, _ in blocks}), "explanations": [e for _, e in blocks]}]
    return _decide(gates)
