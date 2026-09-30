"""Camada de LLM isolada atrás de uma interface mínima (D-016).

Trocar de provedor/modelo = mudar LLM_PROVIDER / LLM_MODEL no .env. Um provedor novo é um
módulo que implementa `LLMProvider.structured_call` e uma linha em `registry.PROVIDERS`.
"""
