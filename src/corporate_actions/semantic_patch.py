"""Variante B (E-003): patch semântico determinístico, pequeno e genérico.

Duas peças, nenhuma específica de documento ou emissor:
1. Classificação com negação: descarta sinais de tipo precedidos por "não/nem/sem" na mesma oração;
   e marca a classificação como não resolvida se a oração do sinal declara que a natureza será definida depois.
2. Qualificadores ao redor de valores extraídos (a frase, limitada por pontuação e por início de linha de tabela):
   - padrão conhecido e interpretável -> interpreta (semântica HIGH):
       THRESHOLD ("sobre a parcela que exceder", "acima de" ...)  -> base do IR = EXCESS_OVER_THRESHOLD
       EXCEPTION + HOLDER_EXEMPTION ("ressalvados ... imunes ou isentos") -> exceção por titular; base inalterada
   - qualificador presente mas não interpretável (negação, condição, adiamento, exceção genérica)
       -> semântica LOW (vai para revisão pelo gate semântico)
   - nenhum qualificador -> semântica HIGH (NO_QUALIFIERS)
Não mapeia rótulos de data alternativos: isso está fora do escopo do patch (limite a medir).
"""
import dataclasses
import re

from .classification import classify
from .confidence_model import UNRESOLVED, SemanticAssessment
from .extraction import ExtractionResult
from .ingestion import TextLayer
from .models import DECLARED_PENDING, FOUND, HIGH, LOW, Classification

SOURCE = "deterministic_patch"
NEGATION_CUE = r"(?i)\b(?:n[ãa]o|nem|sem)\b"
DEFERRAL_CUE = r"(?i)ser[áa]\s+(?:oportunamente\s+)?(?:definid|deliberad|divulgad)[ao]|a\s+(?:ser\s+)?definir|a\s+ser\s+definid[ao]"
QUALIFIERS = {
    "THRESHOLD": r"(?i)sobre\s+a\s+parcela\s+que\s+exceder|que\s+(?:exceder|excederem|ultrapassar|ultrapassarem)\b"
                 r"|apenas\s+sobre|somente\s+sobre|acima\s+de|superior(?:es)?\s+a\b|at[ée]\s+o\s+limite",
    "HOLDER_EXEMPTION": r"(?i)\b(?:imunes|isentos)\b",
    "EXCEPTION": r"(?i)\bexceto\b|\bsalvo\b|ressalvad[oa]s?|com\s+exce[çc][ãa]o",
    "NEGATION": r"(?i)\bn[ãa]o\b",
    "CONDITION": r"(?i)\bdesde\s+que\b|\bcaso\b|condicionad[oa]",
    "DEFERRAL": DEFERRAL_CUE,
}
# Fim de oração: ponto seguido de espaço (não pega "50.000,00" nem "12/06/2026") ou ponto e vírgula.
BOUNDARY = r"\.(?=\s|$)|;"
MAX_SENTENCE = 400
# Início de linha de tabela rótulo/valor (forma capitalizada dos rótulos que o extrator já conhece).
# Tabelas achatadas pelo pypdf não têm pontuação entre linhas; sem este limite a janela vaza
# para a linha vizinha (ex.: "Data de pagamento A definir" contaminando as datas ao lado).
ROW_LABEL = (r"Tipo de evento|Natureza do provento|Valor bruto|Valor líquido|IRRF na fonte|Data de aprovação"
             r"|Data-base|Data [“\"]?ex|Data de pagamento|Crédito das ações|Proporção|Custo atribuído|Código de negociação")
SEMANTIC_FIELDS = ["record_date", "ex_date", "payment_date", "approval_date", "gross_amount_per_share",
                   "net_amount_per_share", "withholding_tax", "ratio", "share_credit_date"]


def qualifier_window(text: str, start: int, end: int) -> str:
    """Onde procurar qualificadores de um trecho: a frase que o contém (prosa), limitada também
    pelo início da linha de tabela anterior e da seguinte (tabela achatada)."""
    base = max(0, start - MAX_SENTENCE)
    cuts = [base + m.end() for m in re.finditer(BOUNDARY, text[base:start])]
    cuts += [base + m.start() for m in re.finditer(ROW_LABEL, text[base:start + 1])]
    left = max([base] + [c for c in cuts if c <= start])
    tail = text[end:end + MAX_SENTENCE]
    stops = [m.start() for m in re.finditer(BOUNDARY, tail)][:1] + [m.start() for m in re.finditer(ROW_LABEL, tail)][:1]
    right = end + (min(stops) if stops else len(tail))
    return text[left:right]


def _clause_before(text: str, start: int, width: int = 60) -> str:
    left = max(0, start - width)
    segment = text[left:start]
    cuts = [m.end() for m in re.finditer(BOUNDARY, segment)]
    return segment[cuts[-1]:] if cuts else segment


# --- 1. Classificação com negação ------------------------------------------------------------

def classify_negation_aware(extraction: ExtractionResult, tl: TextLayer) -> tuple[Classification, list[dict]]:
    text = tl.normalized_text
    kept, negated = {}, []
    for event_type, cands in extraction.event_signals.items():
        for c in cands:
            if re.search(NEGATION_CUE, _clause_before(text, c.evidence.start)):
                negated.append({"event_type": event_type, "rule_id": c.rule_id, "evidence": c.evidence.text,
                                "clause": _clause_before(text, c.evidence.start) + c.evidence.text})
            else:
                kept.setdefault(event_type, []).append(c)
    classification = classify(dataclasses.replace(extraction, event_signals=kept))
    if negated:
        classification.confidence_reasons.append(f"NEGATED_SIGNALS_DISCARDED:{len(negated)}")
    return classification, negated


def classification_semantics(classification: Classification, extraction: ExtractionResult, tl: TextLayer,
                             negated: list[dict]) -> SemanticAssessment:
    text = tl.normalized_text
    deferred = []
    for cands in extraction.event_signals.values():
        for c in cands:
            sentence = qualifier_window(text, c.evidence.start, c.evidence.end)
            m = re.search(DEFERRAL_CUE, sentence)
            if m:
                deferred.append({"type": "DEFERRAL", "cue": m.group(0), "evidence": sentence})
    reasons = [f"NEGATED_SIGNALS:{len(negated)}"] if negated else []
    if deferred:
        return SemanticAssessment(UNRESOLVED, SOURCE, reasons + ["EVENT_NATURE_DEFERRED"], deferred[:1])
    if classification.event_type is None:
        return SemanticAssessment(LOW, SOURCE, reasons + [classification.decision_rule.upper()])
    level = HIGH if classification.decision_rule == "single_type" else "MEDIUM"
    return SemanticAssessment(level, SOURCE, reasons + [classification.decision_rule.upper()])


# --- 2. Qualificadores ------------------------------------------------------------------------

def find_qualifiers(window: str) -> list[dict]:
    out = []
    for qtype, rx in QUALIFIERS.items():
        m = re.search(rx, window)
        if m:
            out.append({"type": qtype, "cue": m.group(0), "evidence": window.strip()})
    return out


def assess_field(name: str, f, text: str) -> tuple[SemanticAssessment, dict | None]:
    """Retorna a avaliação semântica e, se interpretado, o novo valor (só para withholding_tax)."""
    quals = []
    for ev in f.evidence:
        for q in find_qualifiers(qualifier_window(text, ev.start, ev.end)):
            if not any(q["type"] == x["type"] for x in quals):
                quals.append(q)
    types = {q["type"] for q in quals}
    if not quals:
        return SemanticAssessment(HIGH, SOURCE, ["NO_QUALIFIERS"]), None
    if name == "withholding_tax" and f.status == FOUND:
        uninterpretable = types - {"THRESHOLD", "HOLDER_EXEMPTION", "EXCEPTION"}
        if "EXCEPTION" in types and "HOLDER_EXEMPTION" not in types:
            uninterpretable.add("EXCEPTION")
        if not uninterpretable:
            new_value = dict(f.value)
            reasons = []
            if "THRESHOLD" in types:
                new_value["base"] = "EXCESS_OVER_THRESHOLD"
                reasons.append("INTERPRETED:THRESHOLD->EXCESS_OVER_THRESHOLD")
            if "HOLDER_EXEMPTION" in types:
                reasons.append("INTERPRETED:HOLDER_LEVEL_EXEMPTION")
            return SemanticAssessment(HIGH, SOURCE, reasons, quals,
                                      {"base": new_value["base"]}), new_value
        return SemanticAssessment(LOW, SOURCE, [f"UNINTERPRETED_QUALIFIER:{t}" for t in sorted(uninterpretable)],
                                  quals), None
    blocking = types & {"NEGATION", "CONDITION", "DEFERRAL", "THRESHOLD", "EXCEPTION"}
    if blocking:
        return SemanticAssessment(LOW, SOURCE, [f"UNINTERPRETED_QUALIFIER:{t}" for t in sorted(blocking)], quals), None
    return SemanticAssessment(HIGH, SOURCE, ["QUALIFIERS_NOT_AFFECTING_VALUE"], quals), None


def assess_fields(fields: dict, specific: dict, tl: TextLayer) -> dict:
    semantic = {}
    for name in SEMANTIC_FIELDS:
        f = fields.get(name) or specific.get(name)
        if f is None or f.status not in (FOUND, DECLARED_PENDING):
            continue
        if f.status == DECLARED_PENDING:
            semantic[name] = SemanticAssessment(HIGH, SOURCE, ["DECLARED_PENDING"])
            continue
        assessment, new_value = assess_field(name, f, tl.normalized_text)
        if new_value is not None:
            f.notes.append(f"semantic_patch: base interpreted as {new_value['base']}")
            f.value = new_value
        semantic[name] = assessment
    return semantic
