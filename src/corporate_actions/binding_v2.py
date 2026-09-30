"""Binding v2 (E-008, variante H): seleção do melhor par rótulo -> valor entre TODOS os plausíveis.

Failure mode corrigido (E-007): o extrator base guarda um único candidato por valor (deduplica pelo fim do valor),
sempre o do PRIMEIRO rótulo encontrado — que, com rótulo repetido, é o mais distante. O binding v1 (G) só julgava
esse sobrevivente; se ele fosse rejeitado, o par mais próximo e estruturalmente melhor já tinha sido descartado.

Estratégia (decisão tardia, sem regra por rótulo):
1. coletar: para cada ocorrência de cada rótulo do campo, o par com o primeiro valor à frente, com a mesma sintaxe
   do extrator base (mesmos rótulos, mesmo gap sem dígitos, mesmas distâncias máximas, pendência "a definir");
2. julgar cada par com as regras do binding v1 (`binding.judge`): rótulo anota o valor anterior, pista de outro campo
   no caminho, fim de frase;
3. escolher: para cada valor, fica o par válido de rótulo MAIS PRÓXIMO (menor gap); os demais pares válidos do mesmo
   valor ficam registrados como `SUPERSEDED_BY_NEARER_LABEL`;
4. sem vencedor claro: pares válidos que levam a valores DIFERENTES continuam todos como candidatos; a normalização
   registra `distinct_values > 1`, a confiança cai para LOW e o campo obrigatório vai para revisão (mecanismo existente).
Mais o binding "DATA (rótulo)" do v1. Candidatos não ancorados em rótulo (frase, padrão) não são tocados.
Cada par considerado fica em `record.binding` (decisão, motivo, distância do gap, travessia de linha).

Variante I (E-009): mesmo algoritmo com `judge_dot_leader`, que distingue pontilhado de tabela de pontuação real.
"""
import re

from .binding import LABELS, VALUE_BEFORE_PAREN, judge, line_breaks  # noqa: F401  (VALUE_BEFORE_PAREN: contrato do v1)
from .extraction import DATE_LABELS, DATE_NUM, DATE_TEXT, MONEY_VALUE, PENDING, PERCENT_VALUE, _evidence, _tax_base
from .models import Candidate
from .normalization import DATE_NUM_V2

DATE_VALUE = rf"(?P<value>{DATE_NUM}|{DATE_NUM_V2})"
SYNTAX = {  # campo -> (regex do valor, gap permitido, distância máxima, aceita pendência) — igual ao extrator base
    **{f: (DATE_VALUE, r"[^\d]", 40, True) for f in list(DATE_LABELS) + ["share_credit_date"]},
    "gross_amount_per_share": (MONEY_VALUE, r"[^\d]", 60, False),
    "net_amount_per_share": (MONEY_VALUE, r"[^\d]", 60, False),
    "tax_cost_per_share": (MONEY_VALUE, r"[^\d]", 60, False),
    "withholding_tax": (PERCENT_VALUE, r"[^\d%]", 60, False),
}
MONEY = {"gross_amount_per_share", "net_amount_per_share", "tax_cost_per_share"}


def _base_rule(rule_id):
    return rule_id.removesuffix(".pending").removesuffix(".v2fmt")


# Pontilhado de tabela ("Rótulo ........ VALOR"): 4+ pontos seguidos, com ou sem um espaço entre eles. É preenchimento
# de layout, não pontuação. Reticências (3 pontos, ou "…") e ponto final continuam sendo pontuação real.
DOT_LEADER = r"(?:[.·][ \t]?){4,}"


def judge_dot_leader(text, field, label_start, label_end, value_start):
    """`binding.judge` com uma única diferença: o teste de fim de frase ignora pontilhados de tabela."""
    reason = judge(text, field, label_start, label_end, value_start)
    if reason != "CROSSES_SENTENCE":
        return reason
    gap = re.sub(DOT_LEADER, " ", text[label_end:value_start])
    return "CROSSES_SENTENCE" if re.search(r"[.;]\s", gap) else None


def _pairs(text, field, rules):
    """Todos os pares rótulo -> primeiro valor à frente, com a sintaxe do extrator base."""
    value_re, gap, max_gap, pending_ok = SYNTAX[field]
    out = []
    for rule_id, label_re in rules:
        for m in re.finditer(rf"(?i:{label_re})", text):
            after = text[m.end():]
            vm = re.match(rf"(?P<gap>{gap}{{0,{max_gap}}}?){value_re}", after)
            pending = False
            if not vm and pending_ok:
                vm = re.match(rf"(?P<gap>[^\d]{{0,{max_gap}}}?)(?P<value>{PENDING})", after)
                pending = bool(vm)
            if not vm:
                continue
            value_start = m.end() + vm.start("value")
            if field in MONEY:
                value_start = m.end() + vm.end("gap")          # o gap termina antes de "R$"
            rid = rule_id + (".pending" if pending else "")
            if field in DATE_LABELS and not pending and not re.fullmatch(DATE_NUM, vm.group("value")):
                rid = rule_id + ".v2fmt"
            out.append({"field": field, "rule_id": rid, "label_start": m.start(), "label_end": m.end(), "value_start": value_start,
                        "end": m.end() + vm.end(), "raw": vm.group("value"), "pending": pending,
                        "label": (m.group(0) + vm.group("gap")).strip(" :–—-")})
    return out


def apply_best_binding(extraction, tl, judge_fn=judge) -> list[dict]:
    text = tl.normalized_text
    breaks = line_breaks(tl)
    audit = []
    for field, rules in LABELS.items():
        label_rules = {rid for rid, _ in rules}
        kept = [c for c in extraction.candidates.get(field, [])
                if not (c.anchor == "label" and _base_rule(c.rule_id) in label_rules)]
        valid_by_end = {}
        for p in _pairs(text, field, rules):
            reason = judge_fn(text, field, p["label_start"], p["label_end"], p["value_start"])
            p["gap_chars"] = p["value_start"] - p["label_end"]
            p["crosses_line"] = any(p["label_end"] <= b < p["value_start"] for b in breaks)
            p["reason"] = reason
            if reason is None:
                best = valid_by_end.get(p["end"])
                if best is None or p["label_start"] > best["label_start"]:
                    if best is not None:
                        best["reason"] = "SUPERSEDED_BY_NEARER_LABEL"
                    valid_by_end[p["end"]] = p
                else:
                    p["reason"] = "SUPERSEDED_BY_NEARER_LABEL"
            audit.append(p)
        for p in sorted(valid_by_end.values(), key=lambda x: x["end"]):
            attrs = _tax_base(text, p["label_start"], p["end"]) if field == "withholding_tax" else {}
            cand = Candidate(raw=p["raw"], evidence=_evidence(tl, p["label_start"], p["end"]), rule_id=p["rule_id"],
                             anchor="label", source_label=p["label"], attributes=attrs, pending=p["pending"])
            if not any(c.evidence.end == cand.evidence.end for c in kept):
                kept.append(cand)
        if field in extraction.candidates or kept:
            extraction.candidates[field] = kept
    for field in set(DATE_LABELS) | {"share_credit_date"}:        # "DATA (rótulo)", como no v1
        for rid, label_re in LABELS[field]:
            for m in re.finditer(rf"(?P<value>{DATE_NUM}|{DATE_NUM_V2}|{DATE_TEXT})\s*\(\s*[“\"]?(?P<label>(?i:{label_re}))[”\"]?\s*\)",
                                 text):
                cand = Candidate(raw=m.group("value"), evidence=_evidence(tl, m.start(), m.end()),
                                 rule_id=f"{rid}.trailing_parenthetical", anchor="label", source_label=m.group("label"))
                before = len(extraction.candidates.get(field, []))
                extraction.add(field, cand)
                if len(extraction.candidates.get(field, [])) > before:
                    audit.append({"field": field, "rule_id": cand.rule_id, "raw": cand.raw, "label_start": m.start(), "end": m.end(),
                                  "reason": "VALUE_FOLLOWED_BY_PARENTHETICAL_LABEL", "gap_chars": 0, "crosses_line": False,
                                  "trailing": True})
    return [{"field": a["field"], "rule_id": a["rule_id"], "raw": a["raw"],
             "evidence": text[a["label_start"]:a["end"]][:160],
             "decision": ("BOUND" if a["reason"] in (None, "VALUE_FOLLOWED_BY_PARENTHETICAL_LABEL") else
                          "SUPERSEDED" if a["reason"] == "SUPERSEDED_BY_NEARER_LABEL" else "REJECTED"),
             "reason": a["reason"], "gap_chars": a["gap_chars"], "crosses_line": a["crosses_line"]} for a in audit]
