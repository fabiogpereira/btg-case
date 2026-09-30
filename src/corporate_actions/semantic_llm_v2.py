"""Intérprete semântico v2 (E-004, variante D): mesmo papel do v1, com qualificadores tipados.

Diferença conceitual em relação ao v1: o LLM não diz se algo "é uma condição"; ele DESCREVE cada
qualificador (tipo, o que afeta, efeito, citação literal). A materialidade e o bloqueio são decididos
por código (semantic_hybrid.QUALIFIER_POLICY). Os exemplos do prompt vêm só dos documentos originais
(conjunto de desenvolvimento); nenhuma frase do challenge set.
"""
import hashlib
import json

from .semantic_llm import (DATE_ROLES, EVENT_TYPES, LOOKUP_TOOL_SCHEMA, TAX_BASES, USER_TEMPLATE, _schema_ok, ground,
                           locate, lookup_tool)

PROMPT_VERSION = "semantic-interpreter/v2"

QUALIFIER_TYPES = ["tax_base_condition", "tax_rate_condition", "beneficiary_exception", "event_eligibility_condition",
                   "legal_context", "timing_context", "informational_context", "other", "unresolved"]
AFFECTS = ["tax_base", "tax_rate", "tax_application", "event_eligibility", "event_nature", "dates", "amounts", "none"]

SYSTEM_PROMPT = """You are the semantic interpreter inside a corporate-actions extraction pipeline for Asset Servicing (Brazilian B3/CVM shareholder notices, in Portuguese).

Deterministic code already extracts identifiers, amounts and labelled dates, and it runs every financial and reference validation. Your only job is semantic interpretation of the notice:
1. event type: which corporate action THIS notice announces;
2. date roles: which date plays which role for THIS event;
3. withholding-tax semantics: the rate as written and the base it applies to;
4. qualifiers: every expression that conditions, restricts or contextualizes the event, its dates, its amounts or its tax, described by type, what it affects and its effect;
5. reference check: call the lookup_security tool with the security's ISIN (or ticker if there is no ISIN) and report what it returns.

Hard rules:
- Use only the notice text. Never use outside knowledge to fill in, correct or complete information.
- Every quote you output must be copied verbatim from the notice: same characters, accents and punctuation. Keep each quote short: the minimal span that supports the claim.
- Do not compute and do not convert formats. Report values exactly as written.
- If the text does not support a conclusion unambiguously, say so (UNRESOLVED, AMBIGUOUS, NOT_STATED or qualifier type "unresolved"). An honest unresolved answer is always better than a guess.
- You describe; you do not approve, reject or decide what is blocking.

Event types:
- DIVIDEND: distribution of profits ("dividendos", including "intercalares"/"intermediários").
- JCP: "juros sobre o capital próprio" / "remuneração do capital próprio" (Lei 9.249/95, limited by TJLP). JCP is often "imputado ao dividendo (mínimo) obrigatório"; that does not make it a dividend.
- BONUS_SHARES: "bonificação em ações" (new shares from capitalization of reserves).
- REVERSE_SPLIT: "grupamento" / "inplit" (several shares become one).
- SPLIT: "desdobramento".
- UNRESOLVED: the notice does not state the nature of the distribution, defers it to a later decision, or is contradictory in a way the text itself does not resolve.
Mentions that are negated, that refer to other or past events, or that describe what the event does not affect are not the event: list each of them, with its quote, in misleading_mentions. The title may contradict the body; decide from the full content and cite it.

Date roles (only dates of THIS event):
- approval_date: board or shareholders' meeting approval.
- record_date: the last day, or the shareholding position, that determines who is entitled to the event (e.g. "data com", "data-base").
- ex_date: the first trading day on which the shares trade without the right, or with the event already applied (e.g. "data ex").
- payment_date: cash payment. share_credit_date: credit of new shares.
Notices label these roles in many different ways, or state them only in running text; identify the role from what the sentence says, not from a fixed label. Use status PENDING when the notice says the date will be defined later, AMBIGUOUS when the role is unclear. Omit roles the notice does not mention. Never include dates that belong to other events.

Withholding-tax base:
- GROSS_AMOUNT: a flat rate applied to the gross amount.
- EXCESS_OVER_THRESHOLD: the rate applies only to the portion exceeding a threshold.
- EXEMPT: the notice states there is no withholding.
- NOT_STATED: a rate is given but the notice does not say what it applies to.
Use withholding status NOT_STATED if the notice says nothing about income tax.

Qualifier types (describe each qualifier you find; one entry per qualifier):
- tax_base_condition: restricts the portion of the amount the tax applies to (e.g. "sobre a parcela que exceder ..."). affects: tax_base.
- tax_rate_condition: the rate itself depends on a condition (different rates for different situations). affects: tax_rate.
- beneficiary_exception: some holders are treated differently for tax purposes (e.g. "ressalvados os acionistas ... imunes ou isentos"). affects: tax_application.
- event_eligibility_condition: who is entitled to the event, or whether it happens, depends on a condition. affects: event_eligibility or event_nature.
- legal_context: the legal basis or the law in force (e.g. "conforme legislação vigente ..."). affects: none.
- timing_context: when something happens, without changing what or how much (e.g. "no momento do pagamento ou crédito ..."). affects: none or dates.
- informational_context: any other context that changes nothing in the record. affects: none.
- other: a qualifier that changes something but fits none of the types above; unresolved: you cannot tell what it changes.
For each qualifier give affects (what it changes), effect (one short sentence) and the verbatim quote."""

_STR = {"type": "string"}
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["event", "dates", "withholding_tax", "qualifiers", "security_reference"],
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
            "type": "object", "additionalProperties": False, "required": ["status", "rate_as_written", "base", "evidence"],
            "properties": {"status": {"type": "string", "enum": ["STATED", "NOT_STATED", "AMBIGUOUS"]},
                           "rate_as_written": _STR, "base": {"type": "string", "enum": TAX_BASES},
                           "evidence": {"type": "array", "items": _STR}}},
        "qualifiers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["qualifier_type", "affects", "effect", "quote"],
            "properties": {"qualifier_type": {"type": "string", "enum": QUALIFIER_TYPES},
                           "affects": {"type": "string", "enum": AFFECTS}, "effect": _STR, "quote": _STR}}},
        "security_reference": {
            "type": "object", "additionalProperties": False, "required": ["identifier_checked", "found_in_reference"],
            "properties": {"identifier_checked": _STR,
                           "found_in_reference": {"type": "string", "enum": ["YES", "NO", "NOT_CHECKED"]}}},
    },
}


def prompt_fingerprint() -> str:
    blob = json.dumps({"v": PROMPT_VERSION, "system": SYSTEM_PROMPT, "user": USER_TEMPLATE, "schema": OUTPUT_SCHEMA,
                       "tool": LOOKUP_TOOL_SCHEMA}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def interpret(provider, tl, golden, cache=None):
    """Mesmo protocolo do v1: nova tentativa só em falha de parse/schema; recusa e erro de API são resultado."""
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
        if resp.parsed is not None and _schema_ok(resp.parsed) and isinstance(resp.parsed.get("qualifiers"), list):
            return resp.parsed, attempts
        if resp.refusal is not None or resp.errors and not any(e.startswith("json_parse_error") for e in resp.errors):
            break
    return None, attempts


def ground_v2(parsed: dict, tl) -> dict:
    """Grounding do v1 (evento, datas, IR) + cada qualificador tipado."""
    shaped = {**parsed, "withholding_tax": {**parsed["withholding_tax"], "qualifiers": []}}
    g = ground(shaped, tl)
    quals = []
    for q in parsed["qualifiers"]:
        g["total_quotes"] += 1
        span = locate(tl.normalized_text, q["quote"])
        if span:
            g["grounded_quotes"] += 1
        else:
            g["ungrounded"].append({"where": "qualifiers", "quote": q["quote"]})
        quals.append({**q, "grounded": bool(span), "span": span})
    g["qualifiers"] = quals
    return g
