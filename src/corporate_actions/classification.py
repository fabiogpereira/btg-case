"""Classificação determinística do tipo de evento pelo conteúdo (sem o título).

Regra:
- nenhum sinal                   -> indeterminado (LOW)
- sinais de um único tipo        -> esse tipo (HIGH)
- sinais de mais de um tipo      -> regra de precedência documentada, se existir (MEDIUM);
                                    senão, ambíguo (LOW)

Precedência JCP > DIVIDEND: avisos de JCP citam dividendos porque o JCP é imputado ao
dividendo obrigatório (Lei 9.249/95, art. 9º, §7º). É conhecimento de domínio a priori, mas
é frágil: não entende negação ("não haverá JCP"). Ver tests/test_known_limits.py.
"""
import re

from .extraction import EVENT_LEXICON, ExtractionResult
from .models import DIVIDEND, HIGH, JCP, LOW, MEDIUM, Classification

PRECEDENCE = {frozenset({JCP, DIVIDEND}): (JCP, "precedence:JCP_over_DIVIDEND")}


def _types_in(text: str) -> list[str]:
    return sorted(t for t, rules in EVENT_LEXICON.items() if any(re.search(rf"(?i:{rx})", text) for _, rx in rules))


def classify(extraction: ExtractionResult) -> Classification:
    signals = {t: [{"rule_id": c.rule_id, "evidence": c.evidence} for c in cands]
               for t, cands in extraction.event_signals.items() if cands}
    title_types = _types_in(extraction.title) if extraction.title else []
    types = frozenset(signals)
    if not types:
        return Classification(None, "no_signals", signals, extraction.title, title_types, LOW, ["NO_EVENT_SIGNALS"])
    if len(types) == 1:
        (only,) = types
        return Classification(only, "single_type", signals, extraction.title, title_types, HIGH,
                              [f"SINGLE_TYPE_SIGNALS:{only}"])
    if types in PRECEDENCE:
        winner, rule = PRECEDENCE[types]
        return Classification(winner, rule, signals, extraction.title, title_types, MEDIUM,
                              ["MULTIPLE_TYPE_SIGNALS", "PRECEDENCE_RULE_APPLIED"])
    return Classification(None, "ambiguous", signals, extraction.title, title_types, LOW,
                          [f"AMBIGUOUS_TYPE_SIGNALS:{','.join(sorted(types))}"])
