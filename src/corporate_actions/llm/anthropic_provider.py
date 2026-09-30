"""Adaptador Anthropic (SDK oficial `anthropic`). Loop manual de tool use para registrar cada chamada.

- Structured outputs (`output_config.format`) garantem que a resposta final seja JSON do schema.
- Tools com `strict: True`: os argumentos sempre validam contra o schema.
- Fallback de recusa do lado do servidor DESLIGADO por padrão (E-003 avalia uma configuração fixa;
  recusa é resultado registrado). Pode ser ligado com LLM_FALLBACKS=default para avaliar resiliência.
  O modelo que de fato respondeu é sempre registrado em `served_model`.
"""
import json
import os
import time

import anthropic

from .base import LLMResponse, ToolCallRecord, ToolSpec
from .config import LLMConfig

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, config: LLMConfig):
        self.config = config
        # Chaves de API não associadas a um workspace exigem o header anthropic-workspace-id.
        workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID")
        headers = {"anthropic-workspace-id": workspace} if workspace else None
        self.client = anthropic.Anthropic(timeout=config.timeout_s, max_retries=2, default_headers=headers)

    def _create(self, **kwargs):
        if self.config.fallbacks == "default":
            return self.client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        return self.client.messages.create(**kwargs)

    def structured_call(self, system, user_text, tools: list[ToolSpec], output_schema, max_tool_rounds=3) -> LLMResponse:
        resp_out = LLMResponse(provider=self.name, requested_model=self.config.model, served_model=None,
                               output_text=None, parsed=None, stop_reason=None, api_calls=0)
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.input_schema, "strict": True}
                     for t in tools]
        handlers = {t.name: t.handler for t in tools}
        messages = [{"role": "user", "content": user_text}]
        t0 = time.perf_counter()
        rounds = 0
        while True:
            try:
                response = self._create(
                    model=self.config.model, max_tokens=self.config.max_tokens, system=system,
                    messages=messages, tools=tool_defs,
                    output_config={"effort": self.config.effort,
                                   "format": {"type": "json_schema", "schema": output_schema}})
            except anthropic.APIStatusError as exc:
                resp_out.errors.append(f"api_status_error:{exc.status_code}:{exc.message}")
                break
            except anthropic.APIConnectionError as exc:
                resp_out.errors.append(f"api_connection_error:{exc}")
                break
            resp_out.api_calls += 1
            resp_out.request_ids.append(getattr(response, "_request_id", None) or "")
            resp_out.served_model = response.model
            resp_out.stop_reason = response.stop_reason
            u = response.usage
            for key in resp_out.usage:
                resp_out.usage[key] += getattr(u, key, 0) or 0

            if response.stop_reason == "tool_use":
                rounds += 1
                if rounds > max_tool_rounds:
                    resp_out.errors.append("max_tool_rounds_exceeded")
                    break
                messages.append({"role": "assistant", "content": response.content})
                results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    ts = time.perf_counter()
                    try:
                        result, error = handlers[block.name](dict(block.input)), None
                    except Exception as exc:        # a falha da tool volta ao modelo como erro, sem derrubar o run
                        result, error = None, f"{type(exc).__name__}: {exc}"
                    resp_out.tool_calls.append(ToolCallRecord(block.name, dict(block.input), result,
                                                              round((time.perf_counter() - ts) * 1_000_000), error))
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": json.dumps(result if error is None else {"error": error}, ensure_ascii=False),
                                    **({"is_error": True} if error else {})})
                messages.append({"role": "user", "content": results})
                continue

            if response.stop_reason == "refusal":
                details = getattr(response, "stop_details", None)
                resp_out.refusal = {"category": getattr(details, "category", None),
                                    "explanation": getattr(details, "explanation", None)}
                resp_out.errors.append("stop_reason:refusal")
                break
            if response.stop_reason == "max_tokens":
                resp_out.errors.append(f"stop_reason:{response.stop_reason}")
                break
            text = "".join(b.text for b in response.content if b.type == "text")
            resp_out.output_text = text
            try:
                resp_out.parsed = json.loads(text)
            except json.JSONDecodeError as exc:
                resp_out.errors.append(f"json_parse_error:{exc}")
            break
        resp_out.latency_ms = round((time.perf_counter() - t0) * 1000)
        return resp_out
