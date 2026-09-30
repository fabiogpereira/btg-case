"""Definição única de campo crítico (E-011). Usada pela política de incerteza (uncertainty.py) e pelo roteador de
percepção (perception/router.py). Nenhuma outra lista de campos críticos deve existir no código.

Campo crítico = campo cuja leitura errada ou ausência impede auto-approval seguro:
- identificadores do ativo e do emissor (ISIN, ticker, CNPJ, razão social, classe);
- datas materiais (data-base, ex, pagamento, crédito de ações);
- valores e tributação (bruto, líquido, IRRF, tratamento tributário);
- proporção (eventos em ações);
- todo campo obrigatório do tipo de evento (`schema.REQUIRED`), incluindo os específicos do evento.
O tipo de evento também é crítico; ele não é um campo do registro e é tratado à parte por quem o usa.
Texto de contexto, assinaturas, NIRE e demais campos não listados não são críticos.
"""
from .schema import REQUIRED

IDENTIFIERS = ("isin", "ticker", "cnpj", "issuer_name", "share_class")
MATERIAL = ("record_date", "ex_date", "payment_date", "share_credit_date", "gross_amount_per_share",
            "net_amount_per_share", "withholding_tax", "tax_treatment", "ratio")


def critical_fields(event_type) -> set[str]:
    return set(IDENTIFIERS) | set(MATERIAL) | set(REQUIRED.get(event_type, []))


def required_critical_fields(event_type) -> list[str]:
    """Campos críticos obrigatórios do tipo de evento (a ausência bloqueia auto-approval)."""
    return [f for f in REQUIRED.get(event_type, []) if f in critical_fields(event_type)]
