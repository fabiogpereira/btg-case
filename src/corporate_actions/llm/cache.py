"""Cache/replay de respostas do LLM (H-20): reprodutibilidade, auditoria e testes offline.

A chave é o hash de (provedor, modelo, effort, fingerprint do prompt, texto do usuário, tentativa).
Grava a resposta estruturada, o uso de tokens e as tool calls. Não grava o prompt nem o documento:
ambos são reconstruíveis pela versão do prompt + SHA-256 do documento.
"""
import dataclasses
import hashlib
import json
from pathlib import Path

from .base import LLMResponse, ToolCallRecord


class ResponseCache:
    def __init__(self, directory: Path, read: bool = True):
        self.directory = directory
        self.read = read
        directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(provider, system, user, schema, prompt_fp, attempt) -> str:
        cfg = provider.config
        blob = json.dumps({"provider": cfg.provider, "model": cfg.model, "effort": cfg.effort, "prompt": prompt_fp,
                           "system": hashlib.sha256(system.encode()).hexdigest(),
                           "user": hashlib.sha256(user.encode()).hexdigest(),
                           "schema": hashlib.sha256(json.dumps(schema, sort_keys=True).encode()).hexdigest(),
                           "attempt": attempt}, sort_keys=True)
        return hashlib.sha256(blob.encode()).hexdigest()

    def get(self, key: str) -> LLMResponse | None:
        path = self.directory / f"{key}.json"
        if not (self.read and path.exists()):
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tool_calls"] = [ToolCallRecord(**t) for t in data["tool_calls"]]
        data["replayed"] = True
        return LLMResponse(**data)

    def put(self, key: str, resp: LLMResponse) -> None:
        data = dataclasses.asdict(resp)
        data["replayed"] = False
        (self.directory / f"{key}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
