"""Extração determinística (Baseline A): rótulos, padrões e frases-âncora -> candidatos brutos.

Princípios deste extrator:
- O léxico contém apenas rótulos que nomeiam *literalmente* o campo (vocabulário B3/CVM).
  Mapeamentos que exigem interpretação (ex.: "Início da negociação grupada" -> data ex)
  ficam fora de propósito: são o limite que este experimento quer medir.
- Cada regra tem um rule_id, gravado no candidato, para auditoria e para medir quantos
  documentos cada regra cobre (regra que só dispara em 1 documento = sinal de sobreajuste).
- Nada aqui olha o nome do arquivo (D-004). O título é extraído só para a checagem de
  consistência; a classificação usa o conteúdo sem o título.
- Aqui não se normaliza nem se decide nada: só se coletam candidatos com evidência.
"""
import re
from dataclasses import dataclass, field

from .ingestion import TextLayer
from .models import BONUS_SHARES, DIVIDEND, JCP, REVERSE_SPLIT, SPLIT, Candidate, Evidence

DATE_NUM = r"\d{2}/\d{2}/\d{4}"
MONTHS = "janeiro|fevereiro|março|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
DATE_TEXT = rf"\d{{1,2}}º?\s+de\s+(?:{MONTHS})\s+de\s+\d{{4}}"
MONEY_VALUE = r"R\$\s*(?P<value>\d{1,3}(?:\.\d{3})*,\d+|\d+,\d+)"
PERCENT_VALUE = r"(?P<value>\d{1,3}(?:,\d+)?)\s*%"
PENDING = (r"(?i:a\s+definir|a\s+ser\s+(?:definid|divulgad|informad)[ao]"
           r"|(?:será\s+)?oportunamente\s+(?:definid|divulgad|informad)[ao])")

# --- Rótulos por campo: (rule_id, regex do rótulo) — case-insensitive -------------------------
DATE_LABELS = {
    "record_date": [("record_date.label_data_base", r"data[\s-]base"),
                    ("record_date.label_data_com", r"\bdata\s+com\b")],
    "ex_date": [("ex_date.label_data_ex", r"data\s+[“\"]?ex(?:-[\wÀ-ÿ]+)?[”\"]?")],
    "payment_date": [("payment_date.label_data_pagamento", r"data\s+de\s+pagamento")],
    "approval_date": [("approval_date.label_data_aprovacao", r"data\s+de\s+aprova[çc][ãa]o")],
    "share_credit_date": [("share_credit_date.label_credito_acoes", r"cr[ée]dito\s+das\s+a[çc][õo]es")],
}
MONEY_LABELS = {
    "gross_amount_per_share": [("gross.label_valor_bruto", r"valor\s+bruto")],
    "net_amount_per_share": [("net.label_valor_liquido", r"valor\s+l[íi]quido")],
    "tax_cost_per_share": [("tax_cost.label_custo_atribuido", r"custo\s+(?:unit[áa]rio\s+)?atribu[íi]do")],
}
TAX_LABELS = [("withholding.label_imposto_renda", r"imposto\s+de\s+renda"), ("withholding.label_irrf", r"\bIRRF\b")]
TAX_BASE_GROSS = r"(?i:sobre\s+o\s+valor\s+bruto)"

# --- Léxico de tipo de evento (a priori, vocabulário do domínio) ------------------------------
EVENT_LEXICON = {
    JCP: [("event.jcp_juros_capital_proprio", r"juros\s+sobre\s+(?:o\s+)?capital\s+pr[óo]prio"),
          ("event.jcp_sigla", r"\bJCP\b"),
          ("event.jcp_remuneracao_capital_proprio", r"remunera[çc][ãa]o\s+do\s+capital\s+pr[óo]prio"),
          ("event.jcp_lei_9249", r"lei\s+n?[ºo°]?\s*9\.249")],
    DIVIDEND: [("event.dividend_dividendo", r"\bdividendos?\b")],
    BONUS_SHARES: [("event.bonus_bonificacao", r"\bbonifica[çc][ãa]o\b"),
                   ("event.bonus_acoes_bonificadas", r"a[çc][õo]es\s+bonificadas")],
    REVERSE_SPLIT: [("event.reverse_split_grupamento", r"\bgrupamento\b"),
                    ("event.reverse_split_inplit", r"\binplit\b")],
    SPLIT: [("event.split_desdobramento", r"\bdesdobramento\b")],
}
TITLE_MARKERS = r"(AVISO AOS ACIONISTAS|FATO RELEVANTE|COMUNICADO AO MERCADO)"

# --- Identificadores ----------------------------------------------------------------------
CNPJ = r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"
ISIN = r"[A-Z]{2}[A-Z0-9]{9}\d"
TICKER = r"[A-Z]{4}(?:3|4|5|6|11)"
_WORD = r"[A-ZÀ-Ý][\wÀ-ÿ-]*"
COMPANY_SA = rf"{_WORD}(?:\s+(?:(?:d[aeo]s?|e)\s+)?{_WORD})*\s+S\.A\."
SHARE_CLASS = r"(?i:por\s+a[çc][ãa]o\s+(?:ordin[áa]ria\s+|preferencial\s+)?)\(?(?P<value>ON|PN|UNT)\)?(?![\w])"

# --- Proporções ---------------------------------------------------------------------------
RATIO_COLON = r"(?i:propor[çc][ãa]o)[^\d]{0,20}?(?P<a>\d+)\s*:\s*(?P<b>\d+)"
RATIO_BONUS = (r"(?P<new>\d+)\s+(?:\([^)]*\)\s+)?(?i:a[çc](?:ão|ões)\s+novas?\s+para\s+cada)\s+(?P<held>\d+)"
               r"\s+(?:\([^)]*\)\s+)?(?i:a[çc][õo]es)(?:\s*\((?P<pct>\d+(?:,\d+)?)\s*%\))?")
RATIO_EXISTING_TO_NEW = (r"(?P<a>\d+)\s+(?:\([^)]*\)\s+)?(?i:a[çc][õo]es\s+existentes\s+para)\s+(?P<b>\d+)"
                         r"\s+(?:\([^)]*\)\s+)?(?i:a[çc][ãa]o)")

# --- Data de aprovação por frase (reunião/assembleia + data por extenso) -------------------
APPROVAL_PHRASE = (r"(?i:reuni[ãa]o|assembleia\s+geral(?:\s+(?:extraordin[áa]ria|ordin[áa]ria))?)"
                   rf"(?:\s+realizada)?\s+(?:em|de)\s+(?P<value>{DATE_TEXT})")

# Campos que o esquema comum conhece mas este extrator deliberadamente não suporta.
UNSUPPORTED_FIELDS = ["fraction_adjustment_period"]


@dataclass
class ExtractionResult:
    candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    event_signals: dict[str, list[Candidate]] = field(default_factory=dict)
    title: str | None = None
    title_span: tuple[int, int] | None = None
    date_mentions: list[Candidate] = field(default_factory=list)   # todas as datas do texto (corroboração)
    unsupported_fields: list[str] = field(default_factory=lambda: list(UNSUPPORTED_FIELDS))

    def add(self, name: str, cand: Candidate):
        existing = self.candidates.setdefault(name, [])
        # a mesma ocorrência de valor encontrada por dois rótulos sobrepostos conta uma vez
        if any(c.evidence.end == cand.evidence.end for c in existing):
            return
        existing.append(cand)


def _evidence(tl: TextLayer, start: int, end: int) -> Evidence:
    return Evidence(text=tl.normalized_text[start:end], start=start, end=end, page=tl.page_of(start))


def _labeled(tl, result, name, rules, value_re, gap=r"[^\d]", max_gap=40, pending_ok=False, attrs=None):
    text = tl.normalized_text
    for rule_id, label_re in rules:
        for m in re.finditer(rf"(?i:{label_re})", text):
            after = text[m.end():]
            vm = re.match(rf"(?P<gap>{gap}{{0,{max_gap}}}?){value_re}", after)
            if vm:
                label = (m.group(0) + vm.group("gap")).strip(" :–—-")
                end = m.end() + vm.end()
                extra = attrs(text, m.start(), end) if attrs else {}
                result.add(name, Candidate(raw=vm.group("value"), evidence=_evidence(tl, m.start(), end),
                                           rule_id=rule_id, anchor="label", source_label=label, attributes=extra))
                continue
            if pending_ok:
                pm = re.match(rf"(?P<gap>[^\d]{{0,{max_gap}}}?)(?P<value>{PENDING})", after)
                if pm:
                    end = m.end() + pm.end()
                    label = (m.group(0) + pm.group("gap")).strip(" :–—-")
                    result.add(name, Candidate(raw=pm.group("value"), evidence=_evidence(tl, m.start(), end),
                                               rule_id=rule_id + ".pending", anchor="label", source_label=label,
                                               pending=True))


def _pattern(tl, result, name, rule_id, regex, anchor="pattern", group="value"):
    for m in re.finditer(regex, tl.normalized_text):
        raw = m.group(group) if group in m.re.groupindex else m.group(0)
        result.add(name, Candidate(raw=raw, evidence=_evidence(tl, m.start(), m.end()), rule_id=rule_id,
                                   anchor=anchor, attributes={k: v for k, v in m.groupdict().items() if k != "value"}))


def _company_names(tl, result):
    """Razão social terminada em 'S.A.'.

    Heurística frágil (registrada como limite do baseline): o texto normalizado perde as quebras
    de linha, então o título ("... de Dividendos") pode colar no nome ("A Energética ... S.A.").
    Cortamos a partir do último artigo isolado ("A", "O") dentro da ocorrência.
    """
    for m in re.finditer(COMPANY_SA, tl.normalized_text):
        start = m.start()
        articles = list(re.finditer(r"(?:^|\s)(?:A|O|As|Os)\s+(?=[A-ZÀ-Ý])", m.group(0)))
        if articles:
            start = m.start() + articles[-1].end()
        result.add("issuer_name", Candidate(raw=tl.normalized_text[start:m.end()], evidence=_evidence(tl, start, m.end()),
                                            rule_id="issuer_name.pattern_company_sa", anchor="pattern"))


def _tax_base(text: str, start: int, end: int) -> dict:
    window = text[max(0, start - 80): end + 60]
    return {"base": "GROSS_AMOUNT"} if re.search(TAX_BASE_GROSS, window) else {"base": None}


def _find_title(tl: TextLayer):
    lines = [ln.strip() for page in tl.page_texts for ln in page.splitlines()]
    for i, line in enumerate(lines):
        m = re.search(TITLE_MARKERS + r"\s*[—–-]?\s*(.*)$", line)
        if m:
            title = m.group(2).strip() or next((ln for ln in lines[i + 1:] if ln), "")
            heading = re.sub(r"\s+", " ", line)
            start = tl.normalized_text.find(heading)
            span = (start, start + len(heading)) if start >= 0 else None
            return title or None, span
    return None, None


def extract_candidates(tl: TextLayer) -> ExtractionResult:
    r = ExtractionResult()
    text = tl.normalized_text

    # Identificadores
    for m in re.finditer(CNPJ, text):
        window_start = max(0, m.start() - 20)
        label = re.search(r"(?i)CNPJ[^\d]{0,15}$", text[window_start:m.start()])
        start = window_start + label.start() if label else m.start()
        r.add("cnpj", Candidate(raw=m.group(0), evidence=_evidence(tl, start, m.end()),
                                rule_id="cnpj.label_cnpj" if label else "cnpj.pattern",
                                anchor="label" if label else "pattern",
                                source_label=label.group(0).strip() if label else None))
    _labeled(tl, r, "isin", [("isin.label_isin", r"\bISIN\b")], rf"(?P<value>{ISIN})", gap=r"[^A-Za-z0-9]", max_gap=5)
    _pattern(tl, r, "isin", "isin.pattern", rf"\b(?P<value>{ISIN})\b")
    _labeled(tl, r, "ticker", [("ticker.label_codigo_negociacao", r"c[óo]digo\s+de\s+negocia[çc][ãa]o")],
             rf"(?P<value>{TICKER})\b", gap=r"[^A-Z0-9]", max_gap=10)
    _pattern(tl, r, "ticker", "ticker.pattern", rf"\b(?P<value>{TICKER})\b")
    _company_names(tl, r)
    _pattern(tl, r, "share_class", "share_class.phrase_por_acao", SHARE_CLASS, anchor="phrase")

    # Datas
    for name, rules in DATE_LABELS.items():
        _labeled(tl, r, name, rules, rf"(?P<value>{DATE_NUM})", pending_ok=True)
    _pattern(tl, r, "approval_date", "approval_date.phrase_meeting", APPROVAL_PHRASE, anchor="phrase")
    for regex in (rf"(?P<value>{DATE_NUM})", rf"(?P<value>{DATE_TEXT})"):
        for m in re.finditer(regex, text):
            r.date_mentions.append(Candidate(raw=m.group("value"), evidence=_evidence(tl, m.start(), m.end()),
                                             rule_id="date.any", anchor="pattern"))

    # Valores e alíquota
    for name, rules in MONEY_LABELS.items():
        _labeled(tl, r, name, rules, MONEY_VALUE, max_gap=60)
    _labeled(tl, r, "withholding_tax", TAX_LABELS, PERCENT_VALUE, gap=r"[^\d%]", max_gap=60, attrs=_tax_base)

    # Proporções
    _pattern(tl, r, "ratio", "ratio.label_proporcao_colon", RATIO_COLON, anchor="label", group="_none")
    _pattern(tl, r, "ratio", "ratio.phrase_bonus_new_per_held", RATIO_BONUS, anchor="phrase", group="_none")
    _pattern(tl, r, "ratio", "ratio.phrase_existing_to_new", RATIO_EXISTING_TO_NEW, anchor="phrase", group="_none")
    for c in r.candidates.get("ratio", []):
        c.attributes["form"] = c.rule_id.split(".", 1)[1]

    # Título (só para consistência) e sinais de tipo de evento (conteúdo sem o título)
    r.title, r.title_span = _find_title(tl)
    for event_type, rules in EVENT_LEXICON.items():
        for rule_id, regex in rules:
            for m in re.finditer(rf"(?i:{regex})", text):
                if r.title_span and m.start() < r.title_span[1] and m.end() > r.title_span[0]:
                    continue
                r.event_signals.setdefault(event_type, []).append(
                    Candidate(raw=m.group(0), evidence=_evidence(tl, m.start(), m.end()), rule_id=rule_id, anchor="phrase"))
    return r
