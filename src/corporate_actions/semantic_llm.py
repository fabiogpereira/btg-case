"""Variante C (E-003): intérprete semântico por LLM, restrito, grounded e subordinado às validações.

Escopo do LLM (e só isto): tipo de evento, papel das datas, semântica do IR (base e qualificadores),
e uma consulta de referência via tool determinística (function calling real, D-002).

O LLM NÃO calcula, NÃO converte formatos, NÃO aprova, NÃO substitui o golden lookup nem o
validation engine. Todo trecho que ele devolve precisa ser localizado literalmente no documento
(grounding determinístico); o que não for localizado é descartado e marcado como não resolvido.
"""
import datetime as dt
import hashlib
import json
import re

from .confidence_model import UNRESOLVED, SemanticAssessment
from .ingestion import TextLayer
from .llm.base import ToolSpec
from .models import (BONUS_SHARES, DECLARED_PENDING, DIVIDEND, FOUND, HIGH, JCP, LOW, MEDIUM, REVERSE_SPLIT, SPLIT,
                     Classification, Evidence, ExtractedField)
from .normalization import parse_date
from .numeric import parse_br_percent
from .reference import GoldenRecords

PROMPT_VERSION = "semantic-interpreter/v1"
SOURCE = "llm"
EVENT_TYPES = [DIVIDEND, JCP, BONUS_SHARES, REVERSE_SPLIT, SPLIT, "UNRESOLVED"]
DATE_ROLES = ["approval_date", "record_date", "ex_date", "payment_date", "share_credit_date"]
TAX_BASES = ["GROSS_AMOUNT", "EXCESS_OVER_THRESHOLD", "EXEMPT", "NOT_STATED"]
QUALIFIER_TYPES = ["THRESHOLD", "HOLDER_EXEMPTION", "EXCEPTION", "CONDITION", "NEGATION", "DEFERRAL"]

SYSTEM_PROMPT = """You are the semantic interpreter inside a corporate-actions extraction pipeline for Asset Servicing (Brazilian B3/CVM shareholder notices, in Portuguese).

Deterministic code already extracts identifiers, amounts and labelled dates, and it runs every financial and reference validation. Your only job is semantic interpretation of the notice:
1. event type: which corporate action THIS notice announces;
2. date roles: which date plays which role for THIS event;
3. withholding-tax semantics: the rate as written, the base it applies to, and any qualifiers;
4. reference check: call the lookup_security tool with the security's ISIN (or ticker if there is no ISIN) and report what it returns.

Hard rules:
- Use only the notice text. Never use outside knowledge to fill in, correct or complete information.
- Every quote you output must be copied verbatim from the notice: same characters, accents and punctuation. Keep each quote short: the minimal span that supports the claim.
- Do not compute and do not convert formats. Report values exactly as written, e.g. "12/06/2026", "12 de junho de 2026", "17,5%".
- If the text does not support a conclusion unambiguously, say so (UNRESOLVED, AMBIGUOUS or NOT_STATED). An honest unresolved answer is always better than a guess.
- You do not approve or reject anything.

Event types:
- DIVIDEND: distribution of profits ("dividendos", including "intercalares"/"intermediários").
- JCP: "juros sobre o capital próprio" / "remuneração do capital próprio" (Lei 9.249/95, limited by TJLP). JCP is often "imputado ao dividendo (mínimo) obrigatório"; that does not make it a dividend.
- BONUS_SHARES: "bonificação em ações" (new shares from capitalization of reserves).
- REVERSE_SPLIT: "grupamento" / "inplit" (several shares become one).
- SPLIT: "desdobramento".
- UNRESOLVED: the notice does not state the nature of the distribution, defers it to a later decision, or is contradictory in a way the text itself does not resolve.
Mentions that are negated, that refer to other or past events, or that describe what the event does not affect are not the event: list them in misleading_mentions. The title may contradict the body; decide from the full content and cite it.

Date roles (only dates of THIS event):
- approval_date: board or shareholders' meeting approval.
- record_date: the last day, or the shareholding position, that determines who is entitled to the event (e.g. "data com", "data-base").
- ex_date: the first trading day on which the shares trade without the right, or with the event already applied (e.g. "data ex").
- payment_date: cash payment. share_credit_date: credit of new shares.
Notices label these roles in many different ways, or state them only in running text; identify the role from what the sentence says, not from a fixed label.
Use status PENDING when the notice says the date will be defined later, AMBIGUOUS when the role is unclear. Omit roles the notice does not mention. Never include dates that belong to other events.

Withholding-tax base:
- GROSS_AMOUNT: a flat rate applied to the gross amount.
- EXCESS_OVER_THRESHOLD: the rate applies only to the portion exceeding a threshold.
- EXEMPT: the notice states there is no withholding.
- NOT_STATED: a rate is given but the notice does not say what it applies to.
Holder-level exemptions ("ressalvados os acionistas imunes ou isentos") do not change the base; report them as HOLDER_EXEMPTION qualifiers. Use withholding status NOT_STATED if the notice says nothing about income tax."""

USER_TEMPLATE = "Shareholder notice (text extracted from the document):\n<<<\n{text}\n>>>"

_STR = {"type": "string"}
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["event", "dates", "withholding_tax", "security_reference"],
    "properties": {
        "event": {
            "type": "object", "additionalProperties": False,
            "required": ["type", "evidence", "misleading_mentions", "rationale"],
            "properties": {
                "type": {"type": "string", "enum": EVENT_TYPES},
                "evidence": {"type": "array", "items": _STR},
                "misleading_mentions": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["quote", "why_not_the_event"],
                    "properties": {"quote": _STR, "why_not_the_event": _STR}}},
                "rationale": _STR,
            }},
        "dates": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["role", "status", "value_as_written", "evidence"],
            "properties": {"role": {"type": "string", "enum": DATE_ROLES},
                           "status": {"type": "string", "enum": ["FOUND", "PENDING", "AMBIGUOUS"]},
                           "value_as_written": _STR, "evidence": _STR}}},
        "withholding_tax": {
            "type": "object", "additionalProperties": False,
            "required": ["status", "rate_as_written", "base", "evidence", "qualifiers"],
            "properties": {
                "status": {"type": "string", "enum": ["STATED", "NOT_STATED", "AMBIGUOUS"]},
                "rate_as_written": _STR,
                "base": {"type": "string", "enum": TAX_BASES},
                "evidence": {"type": "array", "items": _STR},
                "qualifiers": {"type": "array", "items": {
                    "type": "object", "additionalProperties": False, "required": ["type", "quote"],
                    "properties": {"type": {"type": "string", "enum": QUALIFIER_TYPES}, "quote": _STR}}},
            }},
        "security_reference": {
            "type": "object", "additionalProperties": False, "required": ["identifier_checked", "found_in_reference"],
            "properties": {"identifier_checked": _STR,
                           "found_in_reference": {"type": "string", "enum": ["YES", "NO", "NOT_CHECKED"]}}},
    },
}

LOOKUP_TOOL_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["identifier", "identifier_type"],
    "properties": {"identifier": {"type": "string", "description": "ISIN (12 chars) or B3 ticker, exactly as in the notice"},
                   "identifier_type": {"type": "string", "enum": ["ISIN", "TICKER"]}},
}


def prompt_fingerprint() -> str:
    blob = json.dumps({"v": PROMPT_VERSION, "system": SYSTEM_PROMPT, "user": USER_TEMPLATE, "schema": OUTPUT_SCHEMA,
                       "tool": LOOKUP_TOOL_SCHEMA}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def lookup_tool(golden: GoldenRecords) -> ToolSpec:
    def handler(args: dict) -> dict:
        ident = (args.get("identifier") or "").strip().upper()
        if args.get("identifier_type") == "ISIN":
            ref = golden.lookup_by_isin(ident)
            row = ref["row"]
        else:
            row = next((r for r in golden.rows if r["ticker"] == ident), None)
        if not row:
            return {"found": False, "identifier": ident}
        return {"found": True, "issuer": row["emissor"], "isin": row["isin"], "ticker": row["ticker"],
                "share_class": row["classe"], "status": row["status"]}
    return ToolSpec(name="lookup_security",
                    description="Deterministic exact-match lookup of a security in the golden reference base "
                                "(issuer, ISIN, ticker, class, status). No fuzzy matching.",
                    input_schema=LOOKUP_TOOL_SCHEMA, handler=handler)


# --- Grounding -----------------------------------------------------------------------------

_QUOTE_CHARS = "\"“”„«»"


def locate(text: str, quote: str):
    """Localiza um trecho literal no texto normalizado (tolerando só espaços e o tipo de aspas)."""
    q = re.sub(r"\s+", " ", quote or "").strip()
    if not q:
        return None
    parts = []
    for ch in q:
        if ch in _QUOTE_CHARS:
            parts.append(f"[{re.escape(_QUOTE_CHARS)}]")
        elif ch == " ":
            parts.append(r"\s+")
        else:
            parts.append(re.escape(ch))
    m = re.search("".join(parts), text)
    return (m.start(), m.end()) if m else None


def _evidence(tl: TextLayer, span) -> Evidence:
    return Evidence(text=tl.normalized_text[span[0]:span[1]], start=span[0], end=span[1], page=tl.page_of(span[0]))


def ground(parsed: dict, tl: TextLayer) -> dict:
    """Verifica cada afirmação do LLM contra o texto. Retorna o que é utilizável e o que foi rejeitado."""
    text = tl.normalized_text
    report = {"ungrounded": [], "grounded_quotes": 0, "total_quotes": 0}

    def check(quote, where):
        report["total_quotes"] += 1
        span = locate(text, quote)
        if span:
            report["grounded_quotes"] += 1
        else:
            report["ungrounded"].append({"where": where, "quote": quote})
        return span

    event = parsed["event"]
    spans = [check(q, "event.evidence") for q in event["evidence"]]
    event_ok = bool(event["evidence"]) and all(spans)
    for mm in event["misleading_mentions"]:
        check(mm["quote"], "event.misleading_mentions")

    dates = []
    for d in parsed["dates"]:
        span = check(d["evidence"], f"dates.{d['role']}")
        item = {**d, "grounded": False, "span": span, "value": None, "problem": None}
        if not span:
            item["problem"] = "UNGROUNDED_EVIDENCE"
        elif d["status"] == "FOUND":
            if d["value_as_written"] and d["value_as_written"] in text[span[0]:span[1]]:
                try:
                    item["value"] = parse_date(d["value_as_written"])
                    item["grounded"] = True
                except ValueError:
                    item["problem"] = "UNPARSEABLE_DATE"
            else:
                item["problem"] = "VALUE_NOT_IN_EVIDENCE"
        else:
            item["grounded"] = True
        dates.append(item)

    wt = parsed["withholding_tax"]
    wt_spans = [check(q, "withholding_tax.evidence") for q in wt["evidence"]]
    qual_spans = [check(q["quote"], "withholding_tax.qualifiers") for q in wt["qualifiers"]]
    wt_item = {**wt, "grounded": all(wt_spans) and all(qual_spans), "rate": None, "problem": None}
    if wt["status"] == "STATED":
        if not wt["evidence"] or not wt_item["grounded"]:
            wt_item["grounded"], wt_item["problem"] = False, "UNGROUNDED_EVIDENCE"
        elif wt["rate_as_written"]:
            raw = wt["rate_as_written"].strip().rstrip("%").strip()
            if not any(wt["rate_as_written"].strip() in text[s:e] for s, e in wt_spans):
                wt_item["grounded"], wt_item["problem"] = False, "RATE_NOT_IN_EVIDENCE"
            else:
                try:
                    wt_item["rate"] = parse_br_percent(raw)
                except ValueError:
                    wt_item["grounded"], wt_item["problem"] = False, "UNPARSEABLE_RATE"
    return {"event_grounded": event_ok, "event_spans": spans, "dates": dates, "withholding": wt_item, **report}


# --- Fusão com o determinístico ------------------------------------------------------------

def decide_event_type(det: Classification, parsed: dict | None, grounding: dict | None):
    """Retorna (tipo final, avaliação semântica da classificação)."""
    if parsed is None:
        return det.event_type, SemanticAssessment(LOW, SOURCE, ["SEMANTIC_INTERPRETER_FAILED"])
    llm_type = parsed["event"]["type"]
    if llm_type == "UNRESOLVED":
        return None, SemanticAssessment(UNRESOLVED, SOURCE, ["LLM_EVENT_TYPE_UNRESOLVED"],
                                        interpretation={"deterministic_type": det.event_type,
                                                        "rationale": parsed["event"]["rationale"]})
    if not grounding["event_grounded"]:
        return det.event_type, SemanticAssessment(LOW, SOURCE, ["LLM_EVENT_EVIDENCE_UNGROUNDED"],
                                                  interpretation={"llm_type": llm_type})
    info = {"llm_type": llm_type, "deterministic_type": det.event_type, "deterministic_rule": det.decision_rule,
            "rationale": parsed["event"]["rationale"], "misleading_mentions": parsed["event"]["misleading_mentions"]}
    if det.event_type == llm_type:
        return llm_type, SemanticAssessment(HIGH, "llm+deterministic", ["LLM_AND_DETERMINISTIC_AGREE"], interpretation=info)
    if det.event_type is None:
        return llm_type, SemanticAssessment(MEDIUM, SOURCE, ["LLM_ONLY_DETERMINISTIC_UNDETERMINED"], interpretation=info)
    return llm_type, SemanticAssessment(LOW, SOURCE, ["CLASSIFICATION_DISAGREEMENT"], interpretation=info)


def _llm_field(tl, span, raw, value, rule, note) -> ExtractedField:
    ev = _evidence(tl, span)
    idx = ev.text.find(raw) if raw else -1
    label = ev.text[:idx].strip(" :–—-") if idx > 0 else None
    return ExtractedField(status=FOUND if value is not None else DECLARED_PENDING, value=value, raw=raw,
                          source_label=label or None, evidence=[ev], extraction_rules=[rule], anchor="llm",
                          distinct_values=1, notes=[note], confidence=HIGH,
                          confidence_reasons=["LITERAL_GROUNDED_QUOTE", "DETERMINISTIC_PARSE"])


def merge_dates(fields: dict, specific: dict, grounding: dict, tl: TextLayer) -> dict:
    semantic, mapped = {}, set()
    for item in grounding["dates"]:
        role = item["role"]
        target = specific if role == "share_credit_date" else fields
        if role == "share_credit_date" and "share_credit_date" not in specific:
            continue                                        # não se aplica ao tipo final
        det = target.get(role)
        mapped.add(role)
        if not item["grounded"]:
            semantic[role] = SemanticAssessment(LOW, SOURCE, [f"LLM_DATE_{item['problem']}"], interpretation=item_public(item))
            continue
        if item["status"] == "AMBIGUOUS":
            semantic[role] = SemanticAssessment(LOW, SOURCE, ["LLM_DATE_ROLE_AMBIGUOUS"], interpretation=item_public(item))
            continue
        if item["status"] == "PENDING":
            if det is not None and det.status == DECLARED_PENDING:
                semantic[role] = SemanticAssessment(HIGH, "llm+deterministic", ["PENDING_AGREE"])
            elif det is not None and det.status == FOUND:
                semantic[role] = SemanticAssessment(LOW, SOURCE, ["ROLE_CONFLICT_PENDING_VS_VALUE"], interpretation=item_public(item))
            else:
                target[role] = _llm_field(tl, item["span"], item["value_as_written"], None,
                                          "llm.date_role_mapping.pending", "pending declaration located by LLM")
                semantic[role] = SemanticAssessment(MEDIUM, SOURCE, ["LLM_ONLY_ROLE_MAPPING"])
            continue
        if det is not None and det.status == FOUND:
            if det.value == item["value"]:
                semantic[role] = SemanticAssessment(HIGH, "llm+deterministic", ["ROLE_AGREE"])
            else:
                det.alternatives.append({"value": item["value"], "source": "llm", "evidence": [item["evidence"]]})
                semantic[role] = SemanticAssessment(LOW, SOURCE, ["ROLE_CONFLICT"], interpretation=item_public(item))
        else:
            target[role] = _llm_field(tl, item["span"], item["value_as_written"], item["value"],
                                      "llm.date_role_mapping", "value located by LLM role mapping; literal quote grounded")
            semantic[role] = SemanticAssessment(MEDIUM, SOURCE, ["LLM_ONLY_ROLE_MAPPING"])
    for role in DATE_ROLES:
        target = specific if role == "share_credit_date" else fields
        f = target.get(role)
        if role not in mapped and f is not None and f.status in (FOUND, DECLARED_PENDING):
            semantic[role] = SemanticAssessment(MEDIUM, SOURCE, ["NOT_MAPPED_BY_LLM"])
    return semantic


def item_public(item: dict) -> dict:
    return {k: (v.isoformat() if isinstance(v, dt.date) else v) for k, v in item.items() if k not in ("span",)}


def merge_withholding(fields: dict, grounding: dict, tl: TextLayer, event_type: str | None):
    wt = grounding["withholding"]
    det = fields.get("withholding_tax")
    quals = [{"type": q["type"], "quote": q["quote"]} for q in wt["qualifiers"]]
    if wt["status"] == "AMBIGUOUS":
        return SemanticAssessment(LOW, SOURCE, ["LLM_TAX_AMBIGUOUS"], quals)
    if wt["status"] == "NOT_STATED":
        if det is not None and det.status == FOUND:
            return SemanticAssessment(LOW, SOURCE, ["LLM_SAYS_NOT_STATED_BUT_RATE_FOUND"], quals)
        return None
    if not wt["grounded"] or wt["rate"] is None:
        return SemanticAssessment(LOW, SOURCE, [f"LLM_TAX_{wt['problem'] or 'NO_RATE'}"], quals)
    base = None if wt["base"] == "NOT_STATED" else wt["base"]
    unresolved_quals = sorted({q["type"] for q in quals} & {"CONDITION", "DEFERRAL"})
    if det is None or det.status != FOUND:
        if det is not None and det.status == "not_applicable":
            return SemanticAssessment(LOW, SOURCE, ["TAX_STATED_FOR_NON_CASH_EVENT"], quals)
        span = locate(tl.normalized_text, wt["evidence"][0])
        fields["withholding_tax"] = _llm_field(tl, span, wt["rate_as_written"], {"rate": wt["rate"], "base": base},
                                               "llm.withholding_semantics", "rate and base located by LLM; literal quote grounded")
        level, reasons = MEDIUM, ["LLM_ONLY"]
    elif det.value["rate"] != wt["rate"]:
        return SemanticAssessment(LOW, SOURCE, ["RATE_CONFLICT"], quals, {"llm_rate": str(wt["rate"])})
    elif det.value["base"] not in (None, base):
        return SemanticAssessment(LOW, SOURCE, ["BASE_CONFLICT"], quals, {"llm_base": base})
    else:
        if base is not None and det.value["base"] is None:
            det.value = {"rate": det.value["rate"], "base": base}
            det.notes.append(f"semantic_llm: base interpreted as {base}")
        level, reasons = HIGH, ["LLM_INTERPRETED_GROUNDED"]
    if unresolved_quals:
        return SemanticAssessment(LOW, SOURCE, [f"UNRESOLVED_QUALIFIER:{t}" for t in unresolved_quals], quals, {"base": base})
    return SemanticAssessment(level, SOURCE, reasons, quals, {"base": base})


def interpret(provider, tl: TextLayer, golden: GoldenRecords, cache=None) -> tuple:
    """Chama o LLM (ou o cache). Uma nova tentativa só em caso de falha de parse/schema."""
    user = USER_TEMPLATE.format(text=tl.normalized_text)
    tools = [lookup_tool(golden)]
    attempts = []
    for attempt in range(2):
        key = cache.key(provider, SYSTEM_PROMPT, user, OUTPUT_SCHEMA, prompt_fingerprint(), attempt) if cache else None
        resp = cache.get(key) if cache else None
        if resp is None:
            resp = provider.structured_call(SYSTEM_PROMPT, user, tools, OUTPUT_SCHEMA)
            if cache:
                cache.put(key, resp)
        attempts.append(resp)
        if resp.parsed is not None and _schema_ok(resp.parsed):
            return resp.parsed, attempts
        if resp.refusal is not None or resp.errors and not any(e.startswith("json_parse_error") for e in resp.errors):
            break       # recusa ou erro de API: registrado como resultado; nova tentativa só para parse/schema
    return None, attempts


def _schema_ok(parsed: dict) -> bool:
    try:
        return (parsed["event"]["type"] in EVENT_TYPES and isinstance(parsed["dates"], list)
                and parsed["withholding_tax"]["status"] in ("STATED", "NOT_STATED", "AMBIGUOUS"))
    except (KeyError, TypeError):
        return False
