"""Contrato neutro de provedor: uma chamada estruturada com tools determinísticas."""
from dataclasses import dataclass, field
from typing import Callable, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], dict]    # determinística; executada pelo nosso código, nunca pelo modelo


@dataclass
class ToolCallRecord:
    name: str
    arguments: dict
    result: dict | None
    latency_us: int
    error: str | None = None


@dataclass
class LLMResponse:
    provider: str
    requested_model: str
    served_model: str | None
    output_text: str | None
    parsed: dict | None
    stop_reason: str | None
    api_calls: int
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0,
                                                   "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0})
    latency_ms: int = 0
    errors: list[str] = field(default_factory=list)
    refusal: dict | None = None        # recusa registrada como resultado (sem fallback no E-003)
    request_ids: list[str] = field(default_factory=list)
    replayed: bool = False


class LLMProvider(Protocol):
    name: str

    def structured_call(self, system: str, user_text: str, tools: list[ToolSpec], output_schema: dict,
                        max_tool_rounds: int = 3) -> LLMResponse:
        """Roda o loop de tool calling até a resposta final, que deve ser JSON conforme output_schema."""
        ...
