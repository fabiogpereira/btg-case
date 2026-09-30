"""Variante F (E-006): endurecimento da candidata E. Nenhuma regra é específica de documento.

1. Cobertura determinística (perfil v2): datas DD.MM.AAAA / DD-MM-AAAA; proporções em frases genéricas;
   emissor principal por papel estrutural no documento (não "a primeira S.A.").
2. Tratamento tributário explícito (`tax_treatment`): alíquota numérica, isenção declarada, "não haverá retenção",
   múltiplas alíquotas (condicional), não declarado, não aplicável — com exceções por beneficiário e condições.
   Isenção NÃO vira alíquota zero.
3. Contradições semânticas determinísticas (tipo × tributação, tipo × direção da proporção, isenção × alíquota).
4. Revogação/cancelamento: não suportado como evento -> revisão (UNSUPPORTED_EVENT_REVOCATION).
5. Gate de cobertura material: toda informação material detectada precisa estar representada, explicitamente
   não resolvida (bloqueando) ou justificada como não aplicável; senão MATERIAL_INFORMATION_NOT_REPRESENTED.
"""
import re

from .confidence import score_field
from .confidence_model import UNRESOLVED
from .extraction import DATE_LABELS, DATE_NUM, ExtractionResult, _evidence, _labeled
from .models import (DECLARED_PENDING, DIVIDEND, FOUND, HIGH, JCP, LOW, NOT_APPLICABLE, NOT_FOUND, REVERSE_SPLIT,
                     SPLIT, Candidate, ExtractedField)
from .normalization import DATE_NUM_V2, parse_date, resolve_field
from .schema import SHARE_EVENTS
from .semantic_llm import locate
from .semantic_patch import qualifier_window

MATERIAL_DATE_ROLES = {"record_date", "ex_date", "payment_date", "share_credit_date"}

# --- 1. Cobertura determinística ------------------------------------------------------------------

_ACAO = r"(?i:a[çc](?:ão|ões))"
_PAREN = r"(?:\([^)]*\)\s+)?"
# quantidades por extenso (1 a 10): classe geral de redação, convertida para dígitos antes da normalização
NUMBER_WORDS = {"um": 1, "uma": 1, "dois": 2, "duas": 2, "três": 3, "tres": 3, "quatro": 4, "cinco": 5, "seis": 6,
                "sete": 7, "oito": 8, "nove": 9, "dez": 10}
_N = r"(?:\d+|(?i:uma?|dois|duas|tr[êe]s|quatro|cinco|seis|sete|oito|nove|dez))"
RATIO_V2 = [
    ("ratio.v2_convert_each_into", "phrase_existing_to_new",
     rf"(?i:cada)\s+(?P<a>{_N})\s+{_PAREN}{_ACAO}(?:\s+[\wÀ-ÿ]+){{0,3}}?\s+"
     r"(?i:(?:ser[áã]o?|passar[áã]o?\s+a\s+ser)\s+(?:desdobrad|convertid|grupad|agrupad|transformad)[ao]s?\s+em"
     r"|dar[áã]o?\s+origem\s+a|passar[áã]o?\s+a\s+ser\s+representad[ao]s?\s+por|corresponder[áã]o?\s+a"
     rf"|ser[áã]o?\s+substitu[íi]d[ao]s?\s+por)\s+(?P<b>{_N})\b"),
    ("ratio.v2_proportion_n_to_m", "phrase_existing_to_new",
     rf"(?i:propor[çc][ãa]o\s+de|raz[ãa]o\s+de)\s+(?P<a>\d+)\s+{_PAREN}(?:{_ACAO}\s+)?(?:(?i:existentes?|atuais|antigas?)\s+)?"
     rf"(?i:para)\s+(?P<b>\d+)(?!\s*{_PAREN}{_ACAO}\s+(?i:nova))"),
    ("ratio.v2_label_colon_or_x", "label_proporcao_colon",
     r"(?i:propor[çc][ãa]o|raz[ãa]o|fator)[^\d]{0,20}?(?P<a>\d+)\s*[:x×]\s*(?P<b>\d+)"),
    ("ratio.v2_bonus_per_held_receive", "phrase_bonus_new_per_held",
     rf"(?i:para\s+cada|a\s+cada)\s+(?P<held>\d+)\s+{_PAREN}{_ACAO}[^.;]{{0,80}}?"
     rf"(?i:receber[áã]o?|ser[áã]o?\s+atribu[íi]d[ao]s?|far[áã]o\s+jus\s+a)\s+(?P<new>\d+)\s+{_PAREN}(?:(?i:novas?)\s+)?{_ACAO}"),
]


# rótulo de crédito com qualificador entre "das" e "ações" ("crédito das novas ações")
SHARE_CREDIT_LABEL_V2 = ("share_credit_date.v2_label_credito_qualified", r"cr[ée]dito\s+d[ao]s\s+[\wÀ-ÿ]+\s+a[çc][õo]es")


def extra_candidates(extraction: ExtractionResult, tl) -> None:
    """Acrescenta candidatos do perfil v2 (dedupe por posição, como no extrator base)."""
    text = tl.normalized_text
    for name, rules in DATE_LABELS.items():
        _labeled(tl, extraction, name, [(rid + ".v2fmt", rx) for rid, rx in rules], rf"(?P<value>{DATE_NUM_V2})")
    _labeled(tl, extraction, "share_credit_date", [SHARE_CREDIT_LABEL_V2], rf"(?P<value>{DATE_NUM}|{DATE_NUM_V2})",
             pending_ok=True)
    known = [(m.evidence.start, m.evidence.end) for m in extraction.date_mentions]
    for m in re.finditer(rf"(?P<value>{DATE_NUM_V2})", text):
        if not any(m.start() < e and m.end() > s for s, e in known):
            extraction.date_mentions.append(Candidate(raw=m.group("value"), evidence=_evidence(tl, m.start(), m.end()),
                                                      rule_id="date.any.v2fmt", anchor="pattern"))
    for rule_id, form, rx in RATIO_V2:
        for m in re.finditer(rx, text):
            attrs = {k: str(NUMBER_WORDS.get(v.lower(), v)) for k, v in m.groupdict().items() if v is not None}
            attrs["form"] = form
            extraction.add("ratio", Candidate(raw=m.group(0), evidence=_evidence(tl, m.start(), m.end()),
                                              rule_id=rule_id, anchor="phrase", attributes=attrs))


def extend_specific_v2(specific: dict, extraction: ExtractionResult, event_type) -> None:
    """Schema semantic-record/0.4: data de crédito das novas ações também para desdobramento/grupamento
    (opcional, não obrigatória). Sem esse campo, uma data de crédito declarada não teria onde ser representada."""
    if event_type in (SPLIT, REVERSE_SPLIT) and "share_credit_date" not in specific:
        f = resolve_field("share_credit_date", extraction, event_type)
        score_field(f)
        specific["share_credit_date"] = f


# Emissor principal por papel estrutural
THIRD_PARTY = (r"(?i)escritur|deposit[áa]ri|agente\s|custodiante|institui[çc][ãa]o\s+financeira|coordenador|auditor"
               r"|banco\s+(?:escriturador|mandat[áa]rio|liquidante)|prestador")
ROLE_DEFINED = r'^\s*,?\s*\((?:a\s+|o\s+)?["“]?(?:Companhia|Emissora|Sociedade)["”]?\)'
ROLE_ANNOUNCER = r"^\s*(?:\([^)]*\)\s*)?,?\s*(?:comunica|informa|torna\s+p[úu]blico|vem\s+a\s+p[úu]blico|divulga)"


def issuer_roles(text: str, first_line_len: int, cand: Candidate, cnpj_start: int | None) -> set[str]:
    s, e = cand.evidence.start, cand.evidence.end
    roles = set()
    if s <= first_line_len + 2:
        roles.add("LETTERHEAD")
    if cnpj_start is not None and 0 <= cnpj_start - e <= 120:
        roles.add("CNPJ_ADJACENT")
    after = text[e:e + 60]
    if re.search(ROLE_DEFINED, after):
        roles.add("DEFINED_AS_COMPANY")
    if re.search(ROLE_ANNOUNCER, after):
        roles.add("ANNOUNCER")
    if re.search(THIRD_PARTY, text[max(0, s - 60):s]) or re.search(THIRD_PARTY, after[:40]):
        roles.add("THIRD_PARTY")
    return roles


def resolve_issuer_v2(fields: dict, extraction: ExtractionResult, tl) -> dict:
    """Escolhe o emissor por evidência estrutural; retorna o diagnóstico (auditável)."""
    text = tl.normalized_text
    cands = extraction.candidates.get("issuer_name", [])
    first_line = re.sub(r"\s+", " ", (tl.page_texts[0].strip().splitlines() or [""])[0]).strip()
    cnpj = re.search(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b", text)
    groups: dict = {}
    for c in cands:
        key = re.sub(r"\s+", " ", c.raw).strip().casefold()
        g = groups.setdefault(key, {"names": [], "roles": set(), "third_party_only": True, "evidence": []})
        roles = issuer_roles(text, len(first_line), c, cnpj.start() if cnpj else None)
        g["names"].append(c.raw)
        g["evidence"].append(c.evidence)
        g["roles"] |= roles - {"THIRD_PARTY"}
        if "THIRD_PARTY" not in roles:
            g["third_party_only"] = False
    # alias da mesma entidade: um nome que termina com o nome completo de outro candidato (fronteira de palavra)
    # é a mesma entidade precedida de um órgão/qualificador ("Diretoria da X S.A." -> "X S.A.")
    aliases = {}
    for key in sorted(groups, key=len):
        base = next((k for k in groups if k != key and key.endswith(" " + k) and k not in aliases), None)
        if base is not None:
            aliases[key] = base
    for key, base in aliases.items():
        g, b = groups.pop(key), groups[base]
        n = len(base.split())
        b["names"] += [" ".join(re.sub(r"\s+", " ", x).split()[-n:]) for x in g["names"]]
        b["evidence"] += g["evidence"]
        b["roles"] |= g["roles"]
        b["third_party_only"] = b["third_party_only"] and g["third_party_only"]
    structural = {k: g for k, g in groups.items() if g["roles"] and not g["third_party_only"]}
    diag = {"groups": {k: {"roles": sorted(g["roles"]), "third_party_only": g["third_party_only"]} for k, g in groups.items()},
            "aliases": aliases, "decision": None}
    if (len(groups) <= 1 and not aliases) or not structural:
        diag["decision"] = "V1_RESOLUTION"          # sem ambiguidade, ou sem evidência estrutural: comportamento base
        return diag
    f = fields["issuer_name"]
    if len(structural) == 1:
        (key, g), = structural.items()
        name = next((n for n in g["names"] if any(ch.islower() for ch in n)), g["names"][0])
        others = [k for k in groups if k != key]
        fields["issuer_name"] = ExtractedField(
            status=FOUND, value=re.sub(r"\s+", " ", name).strip(), raw=name, evidence=g["evidence"],
            extraction_rules=["issuer_name.v2_structural_role"], anchor="phrase", distinct_values=1,
            corroborations=len(g["evidence"]) - 1,
            notes=[f"other entities mentioned (not primary): {others}"] + ([f"aliases grouped: {aliases}"] if aliases else []),
            confidence=HIGH, confidence_reasons=[f"STRUCTURAL_ROLE:{'+'.join(sorted(g['roles']))}"])
        diag["decision"] = "STRUCTURAL_PRIMARY"
    else:
        f.confidence, f.confidence_reasons = LOW, ["ISSUER_UNRESOLVED_MULTIPLE_STRUCTURAL_CANDIDATES"]
        diag["decision"] = "UNRESOLVED_MULTIPLE_STRUCTURAL"
    return diag


# --- 2. Tratamento tributário --------------------------------------------------------------------

TAX_WORDS = r"(?i)imposto\s+(?:de|sobre\s+a)\s+renda|\bIR\b|\bIRRF\b|tributa[çc]"
HOLDER_BEFORE_EXEMPT = r"(?i)(?:acionistas?|benefici[áa]rios?|investidores?|titulares?|pessoas?|entidades?|imunes?)[^.;]{0,40}$"
EXEMPT = r"(?i)\bisent[oa]s?\b|\bisen[çc][ãa]o\b"
NO_WITHHOLDING = (r"(?i)n[ãa]o\s+(?:haver[áa]|incidir[áa]|ser[áa]\s+(?:retido|aplicad[oa]|descontad[oa]))\s+"
                  r"(?:(?:qualquer\s+)?reten[çc][ãa]o\s+(?:de\s+)?)?(?:imposto|IR\b|IRRF)|sem\s+reten[çc][ãa]o\s+(?:de\s+)?(?:imposto|IR\b|IRRF)")


def detect_tax_statements(tl) -> list[dict]:
    """Declarações tributárias NO NÍVEL DA DISTRIBUIÇÃO (isenção, ausência de retenção). Isenção de titular
    ("acionistas imunes ou isentos") é exceção por beneficiário, não isenção da distribuição."""
    text = tl.normalized_text
    out = []
    for m in re.finditer(EXEMPT, text):
        sentence = qualifier_window(text, m.start(), m.end())
        if not re.search(TAX_WORDS, sentence):
            continue
        if re.search(HOLDER_BEFORE_EXEMPT, text[max(0, m.start() - 60):m.start()]):
            continue
        out.append({"kind": "EXEMPT", "evidence": sentence.strip(), "cue": m.group(0)})
    for m in re.finditer(NO_WITHHOLDING, text):
        out.append({"kind": "NO_WITHHOLDING_DECLARED", "evidence": qualifier_window(text, m.start(), m.end()).strip(),
                    "cue": m.group(0)})
    return out


def build_tax_treatment(fields: dict, b_field_sem: dict, statements: list[dict], event_type, tl) -> ExtractedField:
    wt = fields["withholding_tax"]
    sem = b_field_sem.get("withholding_tax")
    exceptions = [q["evidence"] for q in (sem.qualifiers if sem else []) if q["type"] == "HOLDER_EXEMPTION"]
    conditions = [q["evidence"] for q in (sem.qualifiers if sem else []) if q["type"] == "THRESHOLD"]
    ev = lambda quote: [_evidence(tl, *locate(tl.normalized_text, quote))] if locate(tl.normalized_text, quote) else []
    if statements:
        st = statements[0]
        value = {"kind": st["kind"], "rate": None, "base": None, "beneficiary_exceptions": exceptions, "conditions": conditions}
        return ExtractedField(status=FOUND, value=value, raw=st["cue"], evidence=ev(st["evidence"]),
                              extraction_rules=[f"tax_treatment.v2_{st['kind'].lower()}"], anchor="phrase", distinct_values=1,
                              confidence=HIGH, confidence_reasons=["PHRASE_ANCHORED", "DISTRIBUTION_LEVEL_STATEMENT"])
    if wt.status == FOUND:
        kind = "CONDITIONAL_MULTIPLE_RATES" if wt.distinct_values > 1 else "WITHHOLDING_AT_RATE"
        value = {"kind": kind, "rate": wt.value["rate"], "base": wt.value["base"],
                 "beneficiary_exceptions": exceptions, "conditions": conditions}
        return ExtractedField(status=FOUND, value=value, raw=wt.raw, source_label=wt.source_label, evidence=wt.evidence,
                              extraction_rules=["tax_treatment.v2_from_withholding"], anchor=wt.anchor,
                              distinct_values=wt.distinct_values, confidence=wt.confidence,
                              confidence_reasons=list(wt.confidence_reasons))
    status = NOT_APPLICABLE if event_type in SHARE_EVENTS else NOT_FOUND
    return ExtractedField(status=status, notes=["no tax statement found" if status == NOT_FOUND else "non-cash event"])


def merge_llm_tax_treatment(fields: dict, grounding: dict, tl) -> dict | None:
    """Isenção identificada pelo LLM com evidência literal não pode ser descartada por não ter porcentagem."""
    wt = grounding["withholding"]
    if wt["status"] != "STATED" or wt["base"] != "EXEMPT":
        return None
    spans = [locate(tl.normalized_text, q) for q in wt["evidence"]]
    if not wt["evidence"] or not all(spans):
        return {"category": "tax_treatment", "result": "LLM_UNGROUNDED"}
    tt = fields["tax_treatment"]
    if tt.status == FOUND and tt.value["kind"] in ("EXEMPT", "NO_WITHHOLDING_DECLARED"):
        return {"category": "tax_treatment", "result": "AGREEMENT"}
    if tt.status == FOUND:
        return {"category": "tax_treatment", "result": "TRUE_DISAGREEMENT", "deterministic": tt.value["kind"]}
    fields["tax_treatment"] = ExtractedField(
        status=FOUND, value={"kind": "EXEMPT", "rate": None, "base": None, "beneficiary_exceptions": [], "conditions": []},
        raw=wt["rate_as_written"] or wt["evidence"][0], evidence=[_evidence(tl, *s) for s in spans],
        extraction_rules=["llm.tax_treatment_exempt"], anchor="llm", distinct_values=1, confidence=HIGH,
        confidence_reasons=["LITERAL_GROUNDED_QUOTE"], notes=["exemption interpreted by LLM; no numeric rate by design"])
    return {"category": "tax_treatment", "result": "LLM_ONLY_GROUNDED"}


# --- 3/4. Contradições e revogação -----------------------------------------------------------------

REVOCATION = (r"(?i)\brevog(?:a|ad[oa]s?|a[çc][ãa]o|ou|ar)\b|\bcancelad[oa]s?\b|\bcancelamento\b|\bsem\s+efeito\b"
              r"|n[ãa]o\s+(?:ser[áa]|ser[ãa]o)\s+mais\s+(?:pag|realizad|distribu[íi]d|creditad)"
              r"|n[ãa]o\s+(?:ser[áa]|ser[ãa]o)\s+(?:pag[oa]s?|realizad[oa]s?|distribu[íi]d[oa]s?|creditad[oa]s?)\b")
EVENT_CONTEXT = r"(?i)provento|dividend|juros\s+sobre|\bJCP\b|bonifica|grupamento|desdobramento|delibera|aprova[çc][ãa]o|distribui"
SHARE_CANCELLATION = r"(?i)cancelamento\s+de\s+(?:\d+\s+)?a[çc][õo]es"


def detect_revocation(tl) -> list[dict]:
    text = tl.normalized_text
    out = []
    for m in re.finditer(REVOCATION, text):
        sentence = qualifier_window(text, m.start(), m.end())
        if re.search(EVENT_CONTEXT, sentence) and not re.search(SHARE_CANCELLATION, sentence):
            out.append({"cue": m.group(0), "evidence": sentence.strip()})
    return out


def detect_contradictions(event_type, fields: dict) -> list[dict]:
    """Combinações materialmente incompatíveis (documentadas em docs/04 E-006). Não decide qual lado está certo."""
    out = []
    tt = fields.get("tax_treatment")
    kind = tt.value["kind"] if tt is not None and tt.status == FOUND else None
    if event_type == DIVIDEND and kind == "WITHHOLDING_AT_RATE" and tt.value["base"] != "EXCESS_OVER_THRESHOLD" \
            and not tt.value["conditions"]:
        out.append({"code": "EVENT_TYPE_VS_TAX_TREATMENT",
                    "detail": "dividendo com retenção à alíquota fixa para todos os titulares, sem condição de limite: "
                              "regime característico de JCP (retenção na fonte sobre o bruto), não do dividendo"})
    if event_type == JCP and kind in ("EXEMPT", "NO_WITHHOLDING_DECLARED"):
        out.append({"code": "EVENT_TYPE_VS_TAX_TREATMENT",
                    "detail": "JCP declarado isento/sem retenção no nível da distribuição; isenção de JCP é por titular"})
    ratio = fields.get("ratio")
    if ratio is not None and ratio.status == FOUND and event_type in (SPLIT, REVERSE_SPLIT):
        before, after = ratio.value["shares_before"], ratio.value["shares_after"]
        if (event_type == SPLIT and after <= before) or (event_type == REVERSE_SPLIT and after >= before):
            out.append({"code": "EVENT_TYPE_VS_RATIO_DIRECTION",
                        "detail": f"{event_type} com proporção {before}->{after}"})
    wt = fields.get("withholding_tax")
    if kind in ("EXEMPT", "NO_WITHHOLDING_DECLARED") and wt is not None and wt.status == FOUND:
        out.append({"code": "TAX_TREATMENT_INTERNAL_CONFLICT", "detail": "isenção/sem retenção e alíquota numérica no mesmo aviso"})
    return out


# --- 5. Gate de cobertura material -----------------------------------------------------------------

# Pistas de papel de data. A pista mais próxima (à esquerda) da data decide o papel: "pagos com base na posição
# do dia X" é data-base, não pagamento.
ROLE_CUES = [
    ("settlement", r"(?i)cr[ée]dit|pagamento|\bpag[oa]s?\b|liquida[çc]"),
    ("record", r"(?i)data[\s-]base|data\s+com\b|posi[çc][ãa]o|titular|inscrit|registrad"),
    ("ex", r"(?i)\bex\b|\bex-|negociad|negocia[çc]"),
    ("approval", r"(?i)aprova|reuni[ãa]o|assembleia|delibera"),
]
SHARE_CREDIT_CUE = r"(?i)cr[ée]dit"
PAST_SETTLEMENT = r"(?i)\bj[áa]\s+(?:foram|foi)\b|\b(?:foram|foi)\s+(?:\w+\s+)?(?:pag|creditad|liquidad)"


def settlement_date_inventory(event_type, fields: dict, specific: dict, extraction: ExtractionResult, text: str):
    """Inventário determinístico (independe do LLM): data cuja pista de papel mais próxima é de liquidação
    (crédito/pagamento), na mesma linha/frase e sem outra data no meio, precisa estar no campo de liquidação.
    Liquidação no passado ("já foram pagos em") é de evento anterior: registrada como não material, com justificativa."""
    out = []
    ends = sorted(m.evidence.end for m in extraction.date_mentions)
    for m in extraction.date_mentions:
        s = m.evidence.start
        prev_date_end = max((e for e in ends if e <= s), default=0)
        start = max(text.rfind("\n", 0, s) + 1, text.rfind(". ", 0, s) + 2, text.rfind(";", 0, s) + 1, s - 80, prev_date_end)
        context = text[start:s]
        cues = [(c.start(), kind) for kind, rx in ROLE_CUES for c in re.finditer(rx, context)]
        if not cues or max(cues)[1] != "settlement":
            continue
        try:
            value = parse_date(m.raw)
        except ValueError:
            continue
        if event_type in SHARE_EVENTS:
            if not re.search(SHARE_CREDIT_CUE, context):
                continue                      # "pagamento" em evento de ações: frações/leilão (nota operacional, E-005)
            role, target = "share_credit_date", specific.get("share_credit_date")
        else:
            role, target = "payment_date", fields.get("payment_date")
        historical = bool(re.search(PAST_SETTLEMENT, context))
        out.append((role, target, value, (context + m.raw).strip(), historical))
    return out


def coverage_gate(event_type, fields: dict, specific: dict, field_sem: dict, grounding, material_q: list,
                  extraction: ExtractionResult, revocations: list, tax_statements: list, text: str) -> tuple[list[dict], list[str]]:
    """Inventário auditável: cada informação material detectada e seu status de representação."""
    items = []

    def add(category, source, evidence, target, status, justification=None):
        items.append({"category": category, "source": source, "evidence": (evidence or "")[:240],
                      "expected_target": target, "representation_status": status, "justification": justification,
                      "blocks": status == "NOT_REPRESENTED"})

    def sem_unresolved(name):
        a = field_sem.get(name)
        return a is not None and a.confidence in (LOW, UNRESOLVED)

    tt = fields.get("tax_treatment")
    tt_found = tt is not None and tt.status == FOUND
    for st in tax_statements:
        add("tax_treatment", "deterministic", st["evidence"], "tax_treatment",
            "REPRESENTED" if tt_found and tt.value["kind"] == st["kind"] else "NOT_REPRESENTED")
    wt = fields.get("withholding_tax")
    if wt is not None and wt.status == FOUND:
        add("tax_treatment", "deterministic", wt.evidence[0].text if wt.evidence else wt.raw, "tax_treatment",
            "REPRESENTED" if tt_found else "NOT_REPRESENTED")
    if grounding is not None:
        g = grounding["withholding"]
        if g["status"] == "STATED" and g["evidence"] and all(locate(text, q) for q in g["evidence"]):
            just = None
            if event_type in SHARE_EVENTS:
                status, just = "NON_MATERIAL_JUSTIFIED", f"withholding does not apply to {event_type} (no cash distribution)"
            elif tt_found and (g["base"] != "EXEMPT" or tt.value["kind"] in ("EXEMPT", "NO_WITHHOLDING_DECLARED")):
                status = "REPRESENTED"
            elif sem_unresolved("withholding_tax"):
                status = "UNRESOLVED_EXPLICIT"
            else:
                status = "NOT_REPRESENTED"
            add("tax_treatment", "llm", g["evidence"][0], "tax_treatment", status, just)
        for d in grounding["dates"]:
            if d["role"] not in MATERIAL_DATE_ROLES or d["span"] is None or d["status"] != "FOUND":
                continue
            target = specific.get(d["role"]) if d["role"] == "share_credit_date" else fields.get(d["role"])
            just = None
            if target is None or target.status == NOT_APPLICABLE:
                status, just = "NON_MATERIAL_JUSTIFIED", f"date role {d['role']} not applicable to {event_type}"
            elif target.status == FOUND and (d["value"] is None or target.value == d["value"]):
                status = "REPRESENTED"
            elif target.status == DECLARED_PENDING or sem_unresolved(d["role"]):
                status = "UNRESOLVED_EXPLICIT"
            elif target.status == FOUND:
                status = "UNRESOLVED_EXPLICIT" if target.alternatives else "NOT_REPRESENTED"
            else:
                status = "NOT_REPRESENTED"
            add("date_role", "llm", d["evidence"], d["role"], status, just)
        for q in material_q:
            if q.get("source") != "llm":
                continue
            add(f"qualifier:{q['affects']}", "llm", q["quote"], q["target_field"],
                "UNRESOLVED_EXPLICIT" if q["blocks"] else "REPRESENTED")
    for role, target, value, evidence, historical in settlement_date_inventory(event_type, fields, specific, extraction, text):
        if historical:
            add("date_role", "deterministic", evidence, role, "NON_MATERIAL_JUSTIFIED",
                "past-tense settlement: refers to a previous event, not to this notice's event")
        elif target is None or target.status == NOT_APPLICABLE:
            add("date_role", "deterministic", evidence, role, "NON_MATERIAL_JUSTIFIED",
                f"date role {role} not applicable to {event_type}")
        elif target.status == FOUND and target.value == value:
            add("date_role", "deterministic", evidence, role, "REPRESENTED")
        elif target.status == FOUND and any(a.get("value") == value for a in target.alternatives):
            add("date_role", "deterministic", evidence, role, "UNRESOLVED_EXPLICIT")
        else:
            add("date_role", "deterministic", evidence, role, "NOT_REPRESENTED")
    ratio_cands = extraction.candidates.get("ratio", [])
    rf = fields.get("ratio")
    if ratio_cands and rf is not None:
        if rf.status == FOUND:
            status = "REPRESENTED"
        elif rf.status == NOT_APPLICABLE:
            status = "NON_MATERIAL_JUSTIFIED"
        else:
            status = "NOT_REPRESENTED"
        add("ratio", "deterministic", ratio_cands[0].evidence.text, "ratio", status,
            f"ratio not applicable to {event_type}" if status == "NON_MATERIAL_JUSTIFIED" else None)
    for r in revocations:
        add("event_status:revocation", "deterministic", r["evidence"], "event", "UNRESOLVED_EXPLICIT")
    blocking = ["MATERIAL_INFORMATION_NOT_REPRESENTED"] if any(i["blocks"] for i in items) else []
    return items, blocking
