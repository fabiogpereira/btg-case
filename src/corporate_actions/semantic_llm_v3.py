"""Intérprete semântico v3 (E-005, variante E): qualificadores v3.

Mudança em relação ao v2: o LLM separa
- material_qualifiers: SÓ trechos cuja remoção mudaria um elemento financeiro do registro
  (natureza do evento, elegibilidade, direito, alíquota, base, valor, proporção, semântica de data);
  cada um com affects, target_field, effect, materiality_reason e citação literal;
- semantic_notes: instruções operacionais (ex.: tratamento de frações), contexto legal e informativo —
  registrados para auditoria, nunca bloqueiam.
Rótulo de campo com o próprio valor nunca é qualificador (regra de escopo no prompt e, de forma
determinística, em qualifiers_v3.scope_guard). Evento, datas, IR e referência: idênticos ao v2.
Exemplos só dos documentos originais e dos exemplos genéricos da especificação do E-005.
"""
import hashlib
import json

from .semantic_llm import (DATE_ROLES, EVENT_TYPES, LOOKUP_TOOL_SCHEMA, TAX_BASES, USER_TEMPLATE, _schema_ok, ground,
                           locate, lookup_tool)

PROMPT_VERSION = "semantic-interpreter/v3"

MATERIAL_KINDS = ["material_condition", "material_exception", "unresolved"]
AFFECTS_V3 = ["event_nature", "eligibility", "entitlement", "tax_rate", "tax_base", "beneficiary_tax_treatment",
              "amount", "ratio", "effective_dates"]
TARGET_FIELDS = ["event", "record_date", "ex_date", "payment_date", "share_credit_date", "approval_date",
                 "gross_amount_per_share", "net_amount_per_share", "withholding_tax", "ratio", "other"]
NOTE_KINDS = ["operational_instruction", "legal_context", "informational_context"]

SYSTEM_PROMPT = """You are the semantic interpreter inside a corporate-actions extraction pipeline for Asset Servicing (Brazilian B3/CVM shareholder notices, in Portuguese).

Deterministic code already extracts identifiers, amounts and labelled dates, and it runs every financial and reference validation. Your only job is semantic interpretation of the notice:
1. event type: which corporate action THIS notice announces;
2. date roles: which date plays which role for THIS event;
3. withholding-tax semantics: the rate as written and the base it applies to;
4. material qualifiers and semantic notes (see below);
5. reference check: call the lookup_security tool with the security's ISIN (or ticker if there is no ISIN) and report what it returns.

Hard rules:
- Use only the notice text. Never use outside knowledge to fill in, correct or complete information.
- Every quote you output must be copied verbatim from the notice: same characters, accents and punctuation. Keep each quote short: the minimal span that supports the claim.
- Do not compute and do not convert formats. Report values exactly as written.
- If the text does not support a conclusion unambiguously, say so (UNRESOLVED, AMBIGUOUS, NOT_STATED, or kind "unresolved"). An honest unresolved answer is always better than a guess.
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

Material qualifiers — the removal test:
Ask of each candidate passage: "If this passage were removed from the notice, would any of these elements of the financial record change: the nature of the event, who is eligible or entitled, the tax rate, the tax base, how tax applies to specific beneficiaries, a monetary amount, the ratio, or the meaning of an effective date?"
- Only if the answer is YES is it a material qualifier. Report it with: kind (material_condition, material_exception, or unresolved if you cannot tell what it changes but it might change one of them), affects (the element that changes), target_field (the record field it modifies, or "event"), effect (one short sentence), materiality_reason (why removing it would change the record), and the verbatim quote.
- Examples: "sobre a parcela que exceder ..." changes the tax base (material_condition, affects tax_base, target withholding_tax). "ressalvados os acionistas ... imunes ou isentos" changes how tax applies to some holders (material_exception, affects beneficiary_tax_treatment, target withholding_tax).
- If the answer is NO, it is NOT a material qualifier. If worth recording, put it in semantic_notes with kind operational_instruction (procedures such as how fractions are grouped and sold, how to adjust positions, where to send documents), legal_context (the legal basis, the law in force, "conforme legislação vigente"), or informational_context (anything else that changes nothing in the record, including timing wording such as "no momento do pagamento ou crédito").
- Scope rule: a field label together with its own value is never a qualifier and never a note (e.g. "Valor bruto por ação: R$ ...", "Data ex: ...", "Código de negociação: ..."). Neither is a passage that only states or explains a field that is already part of the record: the sentence that says who is entitled by their position on a date is the record date itself; the sentence that says what the rate applies to (e.g. "sobre o valor bruto") is the tax base itself. A passage qualifies only if it expresses a relation that modifies another concept.
- Words such as "condição", "exceto", "conforme" or "nos termos de" do not make a passage material by themselves; apply the removal test."""

_STR = {"type": "string"}
OUTPUT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["event", "dates", "withholding_tax", "material_qualifiers", "semantic_notes", "security_reference"],
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
        "material_qualifiers": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "affects", "target_field", "effect", "materiality_reason", "quote"],
            "properties": {"kind": {"type": "string", "enum": MATERIAL_KINDS},
                           "affects": {"type": "string", "enum": AFFECTS_V3},
                           "target_field": {"type": "string", "enum": TARGET_FIELDS},
                           "effect": _STR, "materiality_reason": _STR, "quote": _STR}}},
        "semantic_notes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["kind", "note", "quote"],
            "properties": {"kind": {"type": "string", "enum": NOTE_KINDS}, "note": _STR, "quote": _STR}}},
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
    """Mesmo protocolo do v1/v2: nova tentativa só em falha de parse/schema; recusa e erro de API são resultado."""
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
        p = resp.parsed
        if p is not None and _schema_ok(p) and isinstance(p.get("material_qualifiers"), list) \
                and isinstance(p.get("semantic_notes"), list):
            return p, attempts
        if resp.refusal is not None or resp.errors and not any(e.startswith("json_parse_error") for e in resp.errors):
            break
    return None, attempts


def ground_v3(parsed: dict, tl) -> dict:
    """Grounding do v1 (evento, datas, IR) + cada qualificador material e cada nota."""
    shaped = {**parsed, "withholding_tax": {**parsed["withholding_tax"], "qualifiers": []}}
    g = ground(shaped, tl)
    for key, where in (("material_qualifiers", "material_qualifiers"), ("semantic_notes", "semantic_notes")):
        items = []
        for q in parsed[key]:
            g["total_quotes"] += 1
            span = locate(tl.normalized_text, q["quote"])
            if span:
                g["grounded_quotes"] += 1
            else:
                g["ungrounded"].append({"where": where, "quote": q["quote"]})
            items.append({**q, "grounded": bool(span), "span": span})
        g[key] = items
    return g
