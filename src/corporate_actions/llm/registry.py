"""Registro de provedores e tabela de preços para estimativa de custo.

Para adicionar um provedor: criar `<nome>_provider.py` com uma classe que implemente
`LLMProvider.structured_call` e incluir uma linha em PROVIDERS. Nada mais no pipeline muda.
"""
import importlib
from decimal import Decimal

from .config import LLMConfig

PROVIDERS = {
    "anthropic": "corporate_actions.llm.anthropic_provider:AnthropicProvider",
}

# US$ por 1M tokens (entrada, saída). Fonte: tabela de preços Anthropic (cache da skill claude-api, 2026-06-24).
# Cache: leitura = 0,1× entrada; escrita = 1,25× entrada. Modelos fora da tabela -> custo "desconhecido".
PRICES_PER_MTOK = {
    "claude-opus-5": ("5.00", "25.00"), "claude-opus-4-8": ("5.00", "25.00"), "claude-sonnet-5": ("2.00", "10.00"),
    "claude-haiku-4-5": ("1.00", "5.00"), "claude-fable-5-1": ("10.00", "50.00"),
}


def get_provider(config: LLMConfig):
    if config.provider not in PROVIDERS:
        raise ValueError(f"unknown LLM provider {config.provider!r}; registered: {sorted(PROVIDERS)}")
    module_name, cls_name = PROVIDERS[config.provider].split(":")
    return getattr(importlib.import_module(module_name), cls_name)(config)


def estimate_cost_usd(model: str | None, usage: dict) -> Decimal | None:
    """Estimativa em Decimal exato (tokens inteiros × preço); sem float, sem arredondamento (D-007)."""
    if model not in PRICES_PER_MTOK:
        return None
    price_in, price_out = (Decimal(p) for p in PRICES_PER_MTOK[model])
    cost = (usage.get("input_tokens", 0) * price_in
            + usage.get("cache_read_input_tokens", 0) * price_in * Decimal("0.1")
            + usage.get("cache_creation_input_tokens", 0) * price_in * Decimal("1.25")
            + usage.get("output_tokens", 0) * price_out) / Decimal(1_000_000)
    return cost
