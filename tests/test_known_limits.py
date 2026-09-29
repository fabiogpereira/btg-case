"""Limites conhecidos do Baseline A, documentados como xfail estrito.

Não são bugs a corrigir no Baseline A: medem o limite de uma solução por regras (H-04).
Se algum passar a funcionar, o xfail estrito falha e obriga a atualizar a documentação.
Os textos são variações plausíveis de avisos reais, escritas à mão; não vêm do lote.
"""
import pytest

from corporate_actions.classification import classify
from corporate_actions.extraction import extract_candidates
from corporate_actions.ingestion import TextLayer, normalize_whitespace
from corporate_actions.normalization import resolve_all


def layer(text: str) -> TextLayer:
    norm = normalize_whitespace(text)
    return TextLayer(usable=True, pages=1, alnum_chars=len(norm), min_alnum_chars_per_page=100,
                     page_texts=[text], normalized_text=norm, page_offsets=[0], reason=None)


def run(text):
    ex = extract_candidates(layer(text))
    cls = classify(ex)
    fields, specific = resolve_all(ex, cls.event_type)
    return cls, fields, specific


@pytest.mark.xfail(strict=True, reason="classificação por palavras-chave não entende negação")
def test_negated_jcp_mention_in_dividend_notice():
    cls, _, _ = run("AVISO AOS ACIONISTAS — Dividendos\nA Companhia aprovou a distribuição de dividendos. "
                    "Não haverá crédito de juros sobre o capital próprio neste exercício.")
    assert cls.event_type == "DIVIDEND"


@pytest.mark.xfail(strict=True, reason="mapeamento semântico de rótulo sem 'data ex' literal (limite observado no doc 06)")
def test_reverse_split_ex_date_expressed_as_trading_start():
    _, fields, _ = run("AVISO AOS ACIONISTAS — Grupamento\nGrupamento de ações. Data-base 26/06/2026. "
                       "Início da negociação grupada 29/06/2026. Proporção 10:1")
    assert fields["ex_date"].status == "found"


@pytest.mark.xfail(strict=True, reason="rótulo de valor sem a palavra 'bruto'")
def test_gross_amount_labelled_without_bruto():
    _, fields, _ = run("AVISO AOS ACIONISTAS — Dividendos\nDividendos. Valor por ação: R$ 0,50. "
                       "Data com 10/06/2026. Data ex 11/06/2026.")
    assert fields["gross_amount_per_share"].status == "found"


@pytest.mark.xfail(strict=True, reason="IR condicional (excedente por beneficiário) vira alíquota plana; base não capturada (doc 01)")
def test_conditional_dividend_tax_is_not_flattened():
    _, fields, _ = run("AVISO AOS ACIONISTAS — Dividendos\nOs dividendos estarão sujeitos à retenção de Imposto de Renda "
                       "na Fonte (IRRF) à alíquota de 10% sobre a parcela que exceder R$ 50.000,00 mensais por beneficiário.")
    assert fields["withholding_tax"].value["base"] is not None
