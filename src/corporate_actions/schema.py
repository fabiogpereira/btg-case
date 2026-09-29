"""Esquema comum: quais campos se aplicam e quais são obrigatórios por tipo de evento.

Premissas v1 (tests/ground_truth/README.md). Quando o tipo é desconhecido, nada é marcado
como `not_applicable`: sem saber o tipo, não dá para afirmar que um campo não se aplica.
"""
from .models import BONUS_SHARES, DIVIDEND, JCP, REVERSE_SPLIT, SPLIT

COMMON_FIELDS = [
    "issuer_name", "cnpj", "isin", "ticker", "share_class", "approval_date", "record_date", "ex_date",
    "payment_date", "gross_amount_per_share", "net_amount_per_share", "withholding_tax", "currency", "ratio",
]
EVENT_SPECIFIC_FIELDS = {
    BONUS_SHARES: ["share_credit_date", "tax_cost_per_share"],
    REVERSE_SPLIT: ["fraction_adjustment_period"],
    SPLIT: ["fraction_adjustment_period"],
}
_CASH_ONLY = {"payment_date", "gross_amount_per_share", "net_amount_per_share", "withholding_tax", "currency"}
NOT_APPLICABLE = {
    DIVIDEND: {"net_amount_per_share", "ratio"},   # IR do dividendo depende do beneficiário: sem líquido no emissor
    JCP: {"ratio"},
    BONUS_SHARES: _CASH_ONLY,
    REVERSE_SPLIT: _CASH_ONLY,
    SPLIT: _CASH_ONLY,
}
ALWAYS_REQUIRED = ["issuer_name", "isin", "ticker", "record_date", "ex_date"]
REQUIRED = {
    DIVIDEND: ALWAYS_REQUIRED + ["gross_amount_per_share", "currency", "payment_date"],
    JCP: ALWAYS_REQUIRED + ["gross_amount_per_share", "currency", "payment_date", "net_amount_per_share", "withholding_tax"],
    BONUS_SHARES: ALWAYS_REQUIRED + ["ratio"],
    REVERSE_SPLIT: ALWAYS_REQUIRED + ["ratio"],
    SPLIT: ALWAYS_REQUIRED + ["ratio"],
}
CASH_EVENTS = {DIVIDEND, JCP}
SHARE_EVENTS = {BONUS_SHARES, REVERSE_SPLIT, SPLIT}


def is_applicable(field: str, event_type: str | None) -> bool:
    return event_type is None or field not in NOT_APPLICABLE.get(event_type, set())
