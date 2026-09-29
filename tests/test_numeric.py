"""D-007: aritmética decimal, precisão preservada, sem arredondamento implícito."""
from decimal import Decimal, Inexact, localcontext

import pytest

from corporate_actions.models import to_jsonable
from corporate_actions.numeric import (STRICT_CONTEXT, compare_calculated_to_declared, decimal_places, net_from_gross,
                                       parse_br_decimal, parse_br_percent, to_plain_string)

LOT_JCP_PAIRS = [  # (bruto, líquido) declarados nos docs 02, 03, 04 e 07; IRRF 17,5%
    ("0,1738420000", "0,1434196500"),
    ("0,0921500000", "0,0760237500"),
    ("0,2050000000", "0,1691250000"),
    ("0,1124300000", "0,0927547500"),
]


@pytest.mark.parametrize("raw, expected", [
    ("0,4275000000", "0.4275000000"), ("50.000,00", "50000.00"), ("7,820000", "7.820000"), ("10", "10"),
])
def test_parse_preserves_declared_precision(raw, expected):
    value = parse_br_decimal(raw)
    assert to_plain_string(value) == expected
    assert decimal_places(value) == (len(expected.split(".")[1]) if "." in expected else 0)


@pytest.mark.parametrize("raw", ["0.4275", "abc", "1,2,3", ""])
def test_parse_rejects_non_brazilian_numbers(raw):
    with pytest.raises(ValueError):
        parse_br_decimal(raw)


@pytest.mark.parametrize("raw, expected", [("17,5", "0.175"), ("10", "0.10"), ("5", "0.05")])
def test_percent_shifts_without_rounding(raw, expected):
    assert to_plain_string(parse_br_percent(raw)) == expected


@pytest.mark.parametrize("gross, net", LOT_JCP_PAIRS)
def test_lot_net_values_match_exactly_in_decimal(gross, net):
    cmp = compare_calculated_to_declared(net_from_gross(parse_br_decimal(gross), Decimal("0.175")), parse_br_decimal(net))
    assert cmp.status == "PASS"
    assert cmp.comparison_precision == 10
    assert cmp.rounding_rule is None


def test_binary_float_would_not_be_exact():
    """Motivo da D-007: em float, a mesma conta do doc 02 não fecha exatamente."""
    assert 0.1738420000 * (1 - 0.175) != 0.1434196500


def test_difference_below_declared_precision_is_inconclusive_not_pass():
    # declarado com 4 casas; calculado exato tem mais casas -> sem regra de arredondamento, inconclusivo
    cmp = compare_calculated_to_declared(Decimal("0.14341965"), Decimal("0.1434"))
    assert cmp.status == "NOT_EVALUATED"
    assert cmp.reason == "ROUNDING_RULE_UNDEFINED"
    assert cmp.comparison_precision == 4


def test_difference_at_or_above_declared_precision_fails():
    # 0.1435 ainda seria explicável por arredondamento para cima (diferença < 0.0001) -> inconclusivo
    assert compare_calculated_to_declared(Decimal("0.14341965"), Decimal("0.1435")).status == "NOT_EVALUATED"
    # 0.1436 não é explicável por nenhum arredondamento de 0.14341965 em 4 casas
    assert compare_calculated_to_declared(Decimal("0.14341965"), Decimal("0.1436")).status == "FAIL"
    # erro de um dígito (ex.: leitura errada de scan) é detectado
    assert compare_calculated_to_declared(Decimal("0.0927547500"), Decimal("0.0927547600")).status == "FAIL"


def test_strict_context_refuses_silent_rounding():
    with pytest.raises(Inexact):
        with localcontext(STRICT_CONTEXT):
            Decimal(1) / Decimal(3)


def test_serialization_rejects_float_and_keeps_decimal_digits():
    assert to_jsonable({"v": Decimal("0.0760237500")}) == {"v": "0.0760237500"}
    with pytest.raises(TypeError):
        to_jsonable({"v": 0.07})
