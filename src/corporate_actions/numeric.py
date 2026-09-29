"""Aritmética decimal (D-007).

- Valores sempre construídos a partir da string da fonte; nunca float.
- Precisão declarada preservada; nenhum arredondamento implícito.
- Operações de validação rodam num contexto que levanta exceção se o resultado não for exato.
"""
import re
from dataclasses import dataclass
from decimal import Context, Decimal, DivisionByZero, Inexact, InvalidOperation, Overflow, localcontext

# Qualquer operação que precisaria arredondar levanta `Inexact`. O `rounding` do contexto
# nunca chega a ser aplicado, porque o trap dispara antes; não é uma política de arredondamento.
STRICT_CONTEXT = Context(prec=60, traps=[InvalidOperation, DivisionByZero, Inexact, Overflow])

_BR_NUMBER = re.compile(r"^\d{1,3}(?:\.\d{3})*(?:,\d+)?$|^\d+(?:,\d+)?$")


def parse_br_decimal(raw: str) -> Decimal:
    """'0,4275000000' -> Decimal('0.4275000000'); '50.000,00' -> Decimal('50000.00')."""
    text = raw.strip()
    if not _BR_NUMBER.match(text):
        raise ValueError(f"not a Brazilian-formatted number: {raw!r}")
    return Decimal(text.replace(".", "").replace(",", "."))


def parse_br_percent(raw: str) -> Decimal:
    """'17,5' -> Decimal('0.175'); '10' -> Decimal('0.10'). Desloca a vírgula sem arredondar."""
    return parse_br_decimal(raw).scaleb(-2)


def decimal_places(value: Decimal) -> int:
    exponent = value.as_tuple().exponent
    return -exponent if exponent < 0 else 0


def to_plain_string(value: Decimal) -> str:
    """Serialização sem notação científica e sem perder casas: Decimal('0.0760237500') -> '0.0760237500'."""
    return format(value, "f")


@dataclass(frozen=True)
class DeclaredComparison:
    status: str                     # PASS | FAIL | NOT_EVALUATED
    declared_value: Decimal
    calculated_value: Decimal
    comparison_precision: int       # casas decimais do valor declarado
    rounding_rule: str | None       # sempre None: o case não define regra de arredondamento
    reason: str | None              # ex.: ROUNDING_RULE_UNDEFINED


def compare_calculated_to_declared(calculated: Decimal, declared: Decimal) -> DeclaredComparison:
    """Compara um valor calculado com o declarado, usando a precisão do declarado.

    - igualdade numérica exata                         -> PASS
    - diferença < 1 unidade da última casa declarada   -> NOT_EVALUATED (o declarado pode ter sido
      arredondado/truncado por regra que não conhecemos)
    - diferença >= 1 unidade da última casa declarada  -> FAIL
    """
    precision = decimal_places(declared)
    with localcontext(STRICT_CONTEXT):
        unit = Decimal(1).scaleb(-precision)
        difference = abs(calculated - declared)
    if difference == 0:
        return DeclaredComparison("PASS", declared, calculated, precision, None, None)
    if difference < unit:
        return DeclaredComparison("NOT_EVALUATED", declared, calculated, precision, None, "ROUNDING_RULE_UNDEFINED")
    return DeclaredComparison("FAIL", declared, calculated, precision, None, None)


def net_from_gross(gross: Decimal, tax_rate: Decimal) -> Decimal:
    """bruto × (1 − alíquota), exato. Levanta Inexact se não for representável sem arredondar."""
    with localcontext(STRICT_CONTEXT):
        return gross * (Decimal(1) - tax_rate)
