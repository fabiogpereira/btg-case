"""Binding conservador entre rótulo e valor (E-007, variante G). Proximidade textual sozinha não é evidência.

O extrator base associa um rótulo ao primeiro valor encontrado até 40–60 caracteres sem dígitos depois dele. A G
reexamina cada candidato ancorado em rótulo (datas, valores, alíquota) e só mantém a associação se o trecho entre
rótulo e valor (o "gap") for inequívoco. Rejeita quando o gap:
  1. `LABEL_ANNOTATES_PRECEDING_VALUE` — o rótulo fecha um parêntese aberto logo após um valor ("VALOR (rótulo)"):
     o rótulo qualifica o valor anterior, não o seguinte;
  2. `CROSSES_OTHER_FIELD_CUE` — contém rótulo/pista de outro campo semântico (ex.: "a partir de", "pagamento",
     "negociadas", "valor líquido" para um rótulo de valor bruto);
  3. `CROSSES_SENTENCE` — atravessa fim de frase (". " ou "; ").
Quebra de linha NÃO é critério de rejeição: em PDFs de tabela a célula do rótulo quebra no meio ("Valor bruto por ação
ordinária / (ON) / R$ …" em três linhas) e OCR degrada ainda mais as linhas. A travessia fica registrada na auditoria
(`crosses_line`); as regras 1–3 são as que distinguem binding errado. (Ajuste feito no case original, E-007.)
Associação rejeitada -> o candidato sai; o campo fica com outros candidatos, com o LLM (sob as regras de sempre) ou
`not_found` (revisão, se obrigatório). Preferimos false review a wrong binding.

Único binding novo: "VALOR (rótulo)" para datas — o rótulo entre parênteses, sozinho, logo após a data, é delimitador
explícito da relação (o mesmo sinal que a regra 1 usa para rejeitar a associação para a frente).
Cada decisão fica auditável em `record.binding`.
"""
import re

from .extraction import DATE_LABELS, DATE_NUM, DATE_TEXT, MONEY_LABELS, TAX_LABELS, _evidence
from .hardening import SHARE_CREDIT_LABEL_V2
from .models import Candidate
from .normalization import DATE_NUM_V2

LABELS = {name: list(rules) for name, rules in DATE_LABELS.items()}
LABELS["share_credit_date"] = LABELS["share_credit_date"] + [SHARE_CREDIT_LABEL_V2]
LABELS.update({name: list(rules) for name, rules in MONEY_LABELS.items()})
LABELS["withholding_tax"] = list(TAX_LABELS)
DATE_FIELDS = set(DATE_LABELS)

# Pistas de cada campo semântico. Um gap que contém pista de OUTRO campo atravessa outro campo.
CUES = {
    "record_date": r"data[\s-]base|\bdata\s+com\b|posi[çc][ãa]o|titular|inscrit|registrad",
    "ex_date": r"\bex\b|\bex-|negociad|negocia[çc]|a\s+partir\s+d[eoa]",
    "payment_date": r"pagamento|\bpag[oa]s?\b",
    "share_credit_date": r"cr[ée]dit",
    "approval_date": r"aprova|reuni[ãa]o|assembleia|delibera",
    "gross_amount_per_share": r"\bbruto\b",
    "net_amount_per_share": r"l[íi]quido",
}
VALUE_BEFORE_PAREN = rf"(?:{DATE_NUM}|{DATE_NUM_V2}|{DATE_TEXT}|R\$\s*[\d.,]+|\d+(?:,\d+)?\s*%)\s*$"


def line_breaks(tl) -> set[int]:
    """Posições, no texto normalizado, dos espaços que substituíram uma quebra de linha (ou fronteira de página)."""
    out = set()
    for page, offset in zip(tl.page_texts, tl.page_offsets):
        stripped = page.strip()
        pos = last = 0
        for m in re.finditer(r"\s+", stripped):
            pos += m.start() - last
            if "\n" in m.group(0) or "\r" in m.group(0):
                out.add(offset + pos)
            pos += 1
            last = m.end()
        out.add(offset + pos + len(stripped) - last)
    return out


def _label_regex(field, rule_id):
    base = rule_id.removesuffix(".pending").removesuffix(".v2fmt")
    return next((rx for rid, rx in LABELS.get(field, []) if rid == base), None)


def judge(text, field, label_start, label_end, value_start) -> str | None:
    """Motivo de rejeição, ou None se a associação rótulo -> valor é inequívoca."""
    gap = text[label_end:value_start]
    close, open_ = gap.find(")"), gap.find("(")
    if close >= 0 and (open_ < 0 or close < open_):
        opened = text.rfind("(", 0, label_start)
        if opened >= 0 and re.search(VALUE_BEFORE_PAREN, text[max(0, opened - 40):opened]):
            return "LABEL_ANNOTATES_PRECEDING_VALUE"
    for other, cue in CUES.items():
        if other != field and re.search(rf"(?i:{cue})", gap):
            return "CROSSES_OTHER_FIELD_CUE"
    if re.search(r"[.;]\s", gap):
        return "CROSSES_SENTENCE"
    return None


def apply_safe_binding(extraction, tl) -> list[dict]:
    """Filtra candidatos ancorados em rótulo; acrescenta 'VALOR (rótulo)' para datas. Retorna a trilha de auditoria."""
    text = tl.normalized_text
    breaks = line_breaks(tl)
    audit = []
    for field in LABELS:
        kept = []
        for c in extraction.candidates.get(field, []):
            label_re = _label_regex(field, c.rule_id) if c.anchor == "label" else None
            if label_re is None:
                kept.append(c)
                continue
            m = re.match(rf"(?i:{label_re})", text[c.evidence.start:c.evidence.end])
            value_start = text.rfind(c.raw, c.evidence.start, c.evidence.end) if not c.pending else \
                c.evidence.end - len(c.raw)
            if m is None or value_start < 0:
                kept.append(c)
                continue
            label_end = c.evidence.start + m.end()
            if field in ("gross_amount_per_share", "net_amount_per_share", "tax_cost_per_share"):
                value_start = text.rfind("R$", label_end, value_start + 1) if "R$" in text[label_end:value_start] else value_start
            reason = judge(text, field, c.evidence.start, label_end, value_start)
            audit.append({"field": field, "rule_id": c.rule_id, "raw": c.raw, "evidence": c.evidence.text[:160],
                          "decision": "REJECTED" if reason else "BOUND", "reason": reason,
                          "crosses_line": any(label_end <= b < value_start for b in breaks)})
            if not reason:
                kept.append(c)
        if field in extraction.candidates:
            extraction.candidates[field] = kept
    for field in DATE_FIELDS | {"share_credit_date"}:
        for rid, label_re in LABELS[field]:
            for m in re.finditer(rf"(?P<value>{DATE_NUM}|{DATE_NUM_V2}|{DATE_TEXT})\s*\(\s*[“\"]?(?P<label>(?i:{label_re}))[”\"]?\s*\)",
                                 text):
                cand = Candidate(raw=m.group("value"), evidence=_evidence(tl, m.start(), m.end()),
                                 rule_id=f"{rid}.trailing_parenthetical", anchor="label", source_label=m.group("label"))
                before = len(extraction.candidates.get(field, []))
                extraction.add(field, cand)
                if len(extraction.candidates.get(field, [])) > before:
                    audit.append({"field": field, "rule_id": cand.rule_id, "raw": cand.raw, "evidence": m.group(0)[:160],
                                  "decision": "BOUND", "reason": "VALUE_FOLLOWED_BY_PARENTHETICAL_LABEL"})
    return audit
